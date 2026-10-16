# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproduce a pinned modal-formatter overlay without altering the Forge JAR.

Build dependencies are explicit, hash-pinned inputs. Users of the portable app
do not need these tools; verified class bytes are distributed with their source.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

from classfile import parse

HERE=Path(__file__).resolve().parent
CLASS='forge/game/ability/effects/CharmEffect.class'
METHOD=('makeFormatedDescription','(Lforge/game/spellability/SpellAbility;Z)Ljava/lang/String;')


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def manifest_attributes(raw):
    # Preserve continuation whitespace after removing the one manifest folding
    # character. This pinned archive contains both CRLF and CRCRLF separators.
    text=re.sub(rb'\r+\n',b'\n',raw).replace(b'\r',b'\n').decode('utf8')
    values={};key=None
    for line in text.split('\n'):
        if line.startswith(' ') and key:values[key]+=line[1:]
        elif ':' in line:
            key,value=line.split(':',1);values[key]=value.lstrip(' ')
        elif not line:key=None
    return values


def build(java,ecj,asm,forge,out):
    pins=json.loads((HERE/'dependencies.json').read_text(encoding='utf8'))
    for name,path in [('ecj',ecj),('asm',asm)]:
        if digest(path)!=pins[name]['sha256']:raise ValueError(name+' build dependency hash mismatch')
    if digest(forge)!=pins['forge_sha256']:raise ValueError('Overlay applies only to the pinned Forge JAR')
    if digest(HERE/'ModalDescriptionPatch.java')!=pins['transformer_sha256']:raise ValueError('Transformer source hash mismatch')
    if out.exists():raise FileExistsError('Use a new empty output directory')
    with zipfile.ZipFile(forge) as archive:
        original=archive.read(CLASS);attributes=manifest_attributes(archive.read('META-INF/MANIFEST.MF'))
    if hashlib.sha256(original).hexdigest()!=pins['original_class_sha256']:raise ValueError('Original class hash mismatch')
    main=attributes.get('Main-Class','');opens=attributes.get('Add-Opens','').split()
    if not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$.]*',main):raise ValueError('Native entry class is invalid')
    if any(not re.fullmatch(r'[A-Za-z0-9_.]+/[A-Za-z0-9_.]+',name) for name in opens):raise ValueError('Native module-open declaration is invalid')
    with tempfile.TemporaryDirectory(prefix='forge-modal-build-') as temporary:
        work=Path(temporary);input_=work/'CharmEffect.class';input_.write_bytes(original)
        classes=work/'builder'
        subprocess.run([str(java),'-Xmx256m','-jar',str(ecj),'-21','-encoding','UTF-8','-cp',str(asm),'-d',str(classes),str(HERE/'ModalDescriptionPatch.java')],check=True)
        import os
        classpath=os.pathsep.join(map(str,[classes,asm,forge]));before=parse(original);outputs={}
        for variant in ['identity','patch']:
            result=work/variant/CLASS
            subprocess.run([str(java),'-Xmx256m','-cp',classpath,'ModalDescriptionPatch',str(input_),str(result),variant],check=True)
            data=result.read_bytes();after=parse(data)
            if not after['pool_bytes'].startswith(before['pool_bytes']) or sorted(after['tail'])!=sorted(before['tail']):raise ValueError('Unexpected class-pool or attribute changes')
            outputs[variant]=data[:after['tail_offset']]+original[before['tail_offset']:]
    if outputs['identity']!=original:raise ValueError('Identity roundtrip is not byte-identical')
    after=parse(outputs['patch'])
    for key in ['version','header','interfaces','fields','tail']:
        if before[key]!=after[key]:raise ValueError('Unexpected structural change: '+key)
    if set(before['methods'])!=set(after['methods']):raise ValueError('Method set changed')
    changed=[key for key in before['methods'] if before['methods'][key]!=after['methods'][key]]
    if changed!=[METHOD]:raise ValueError('Only the known formatter method may change')
    patched_sha=hashlib.sha256(outputs['patch']).hexdigest()
    if patched_sha!=pins['patched_class_sha256']:raise ValueError('Reproduced class differs from reviewed bytes')
    destination=out/'classes'/CLASS;destination.parent.mkdir(parents=True);destination.write_bytes(outputs['patch'])
    proof=dict(id='modal-context-1',forge_sha256=pins['forge_sha256'],original_class_sha256=pins['original_class_sha256'],
        patched_class_sha256=patched_sha,transformer_sha256=pins['transformer_sha256'],identity_byte_equal=True,
        other_methods_byte_equal=True,changed_methods=changed,native_main_class=main,native_add_opens=opens,
        production_adopted=False,native_game_validation_required=True)
    (out/'build-verification.json').write_text(json.dumps(proof,indent=2),encoding='utf8')
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['java','ecj','asm','forge','out']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(*(getattr(args,name).resolve() for name in ['java','ecj','asm','forge','out']))))
