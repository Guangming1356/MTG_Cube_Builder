"""Maintainer tool: inspect native name resolution and build a pinned manifest.

Run with ``python -m cube_ai.tools.verify_card_names --compiler ECJ.jar
--output NEW_DIRECTORY``. This starts one original Forge loader, no games or AI
services. Existing evidence is never overwritten. Review the resulting manifest
and update forge_card_names.ASSET_SHA explicitly before enabling new bindings.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

from cube_ai.config import ROOT
from cube_ai.forge_card_names import script_names


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def inspect_scripts(home):
    home=Path(home);folder=home/'res/cardsfolder'
    if list(folder.rglob('*.txt')):raise ValueError('Loose script overrides require a separate review')
    mapping={};backs=[];archives=[]
    for path in sorted((home/'res').rglob('*.zip')):
        if 'card' not in path.name.lower():continue
        archives.append(dict(name=path.relative_to(home).as_posix(),sha256=sha(path)))
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not name.endswith('.txt'):continue
                raw=archive.read(name);names=script_names(raw)
                if not names:continue
                for alias in names[1:]:
                    if alias in mapping and mapping[alias]!=names[0]:raise ValueError('Ambiguous native name: '+alias)
                    mapping[alias]=names[0]
                parts=re.split(r'^ALTERNATE\s*$',raw.decode('utf-8-sig'),maxsplit=1,flags=re.M)
                if len(parts)==2:
                    back=script_names(parts[1].encode('utf8'))
                    # Pair the declared front/back variants in their script order.
                    if back and len(back)==len(names):
                        backs.extend(dict(requested=b,native=back[0],front=f) for f,b in zip(names[1:],back[1:]))
                    elif back and len(back)>1:raise ValueError('Unpaired front/back native variants: '+name)
    root=home/'res/editions';digest=hashlib.sha256()
    for path in sorted(root.rglob('*.txt'),key=lambda p:p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode('utf8')+b'\0')
        digest.update(bytes.fromhex(sha(path)))
    return dict(mapping=dict(sorted(mapping.items())),back_faces=sorted(backs,key=lambda p:p['requested']),
                script_archives=archives,editions_sha256=digest.hexdigest())


def build_manifest(config,scripts,records,source,compiler):
    mapping=scripts['mapping']
    if not mapping or set(records)!=set(mapping):raise ValueError('Native query coverage is incomplete')
    if any(not records[n].get('found') or records[n].get('loaded_name')!=primary or records[n].get('rules_name')!=primary for n,primary in mapping.items()):
        raise ValueError('Native loader did not resolve every alias to its declared primary')
    preserved=sum(records[n]['loaded_name']==n for n in mapping)
    return dict(version='native-name-aliases-1',forge_sha256=config['jar_sha256'],
        script_archives=scripts['script_archives'],editions_sha256=scripts['editions_sha256'],
        pairs=[dict(requested=n,native=p) for n,p in mapping.items()],
        query=dict(requested=len(mapping),resolved_to_declared_primary=len(mapping),
            loaded_under_requested_name=preserved,
            source_sha256=sha(source),compiler_sha256=compiler['sha256'],compiler_source=compiler['source'],
            method='Native CardDb.getCard(requested) returned the script-declared primary name and rules. Deck exports preserve requested names. Native logs require reverse mapping.',
            strict_name_check=f'{preserved}/{len(mapping)}: native objects use primary names. The initial result is retained; this manifest certifies resolution, not name preservation inside Forge.',
            utf8_protocol=True),
        source='Original Forge 2.0.15 scripts and native CardDb. Declared UniversesWithin front names only.',back_faces=scripts['back_faces'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',type=Path,required=True,help='Official ECJ JAR matching pinned dependencies.json')
    parser.add_argument('--output',type=Path,required=True,help='New evidence directory; must not exist')
    args=parser.parse_args()
    from cube_ai.forge import configuration,worker_home
    config=configuration();source=Path(__file__).with_name('NativeCardNames.java')
    pins=json.loads((ROOT/'native/compatibility/modal-context-1/build/dependencies.json').read_bytes())['ecj']
    if sha(args.compiler)!=pins['sha256']:raise ValueError('ECJ hash does not match the reviewed compiler')
    scripts=inspect_scripts(config['home'])
    args.output.mkdir(parents=True,exist_ok=False);output=args.output.resolve()
    def save(name,value):(output/name).write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
    save('requested.json',scripts['mapping']);classes=output/'classes'
    subprocess.run([config['java'],'-Xmx256m','-jar',str(args.compiler.resolve()),'-21','-encoding','UTF-8','-cp',config['jar'],'-d',str(classes),str(source)],check=True)
    home=worker_home(config,output);preferences=home/'userdata/preferences/forge.preferences'
    preferences.parent.mkdir(parents=True,exist_ok=True);preferences.write_bytes(b'LOAD_CARD_SCRIPTS_LAZILY=false\n')
    cp=os.pathsep.join([str(classes),config['jar']])
    command=[config['java'],'-Xmx2048m','-Dfile.encoding=UTF-8','-Djava.awt.headless=true','-cp',cp,'cube.tools.NativeCardNames',str(output/'requested.json')]
    result=subprocess.run(command,cwd=home,encoding='utf8',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (output/'stdout.txt').write_bytes(result.stdout.encode('utf8'));(output/'stderr.txt').write_bytes(result.stderr.encode('utf8'))
    result.check_returncode()
    line=next(s for s in result.stdout.splitlines() if s.startswith('CUBE_CARD_NAMES '))
    records=json.loads(line[len('CUBE_CARD_NAMES '):]);save('native-query.json',records)
    # A changed archive/edition during the query invalidates the assay.
    if inspect_scripts(config['home'])!=scripts:raise ValueError('Native card data changed during inspection')
    manifest=build_manifest(config,scripts,records,source,pins);save('forge_name_aliases.json',manifest)
    print(json.dumps(dict(requested=len(records),resolved=manifest['query']['resolved_to_declared_primary'],manifest_sha256=sha(output/'forge_name_aliases.json'),games_run=0),ensure_ascii=False))


if __name__=='__main__':main()
