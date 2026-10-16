"""Managed, hash-pinned Forge formatter compatibility; absent assets stay inert."""
import hashlib
import json
import os
from pathlib import Path
import re

from .config import ROOT

ASSETS=ROOT/'native/compatibility/modal-context-1'
ID='modal-context-1'
FORGE_SHA='85a4c31e07d4d5621a84bb03b6d75fd08e9f4ba289e575c870579b49c0033766'
CLASS_SHA='e0b5bda6dae6fab57e1a062d8e1731056d54c997d9629b01e0f0d3bc1ea4c8dd'
# Exact reviewed manifest: native development, holdout and both entry probes.
MANIFEST_SHA='1682e3b2cd2775d1ca223a51be372a83a932de55ae47934dc58ccc27bfc0bcf9'
CLASS_PATH='classes/forge/game/ability/effects/CharmEffect.class'
SOURCE_FILES={'README.md','LICENSE.txt','build/build.py','build/classfile.py',
              'build/dependencies.json','build/ModalDescriptionPatch.java'}


def _sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def apply(config,mode=None):
    value=dict(config)
    mode=mode or os.getenv('CUBE_FORGE_COMPAT') or value.get('compatibility_mode','auto')
    if mode not in {'auto','off'}:raise ValueError('Forge 兼容修复设置需为 auto 或 off')
    for key in ['extra_classpath','native_main_class','native_add_opens']:value.pop(key,None)
    value['compatibility']=dict(id=ID,mode=mode,active=False,reason='disabled' if mode=='off' else 'not_installed')
    if mode=='off':return value
    path=ASSETS/'manifest.json'
    if not path.is_file():return value
    try:
        raw=path.read_bytes();manifest=json.loads(raw)
        if manifest.get('id')!=ID or not manifest.get('validated'):
            value['compatibility']['reason']='pending_validation';return value
        if MANIFEST_SHA is None:
            value['compatibility']['reason']='pending_validation';return value
        if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA:raise ValueError('Unreviewed compatibility manifest')
        if manifest.get('forge_sha256')!=FORGE_SHA or manifest.get('patched_class_sha256')!=CLASS_SHA:
            raise ValueError('Compatibility manifest does not match reviewed bytes')
        if not manifest.get('identity_byte_equal') or not manifest.get('other_methods_byte_equal'):
            raise ValueError('Compatibility scope verification missing')
        from .forge import _file_hash
        jar=Path(value['jar']);stat=jar.stat()
        if _file_hash(str(jar.resolve()),stat.st_size,stat.st_mtime_ns)!=FORGE_SHA:
            value['compatibility']['reason']='different_engine';return value
        if _sha(ASSETS/CLASS_PATH)!=CLASS_SHA:raise ValueError('Compatibility class hash mismatch')
        main=manifest.get('native_main_class','');opens=manifest.get('native_add_opens',[])
        if main!='forge.view.Main' or not isinstance(opens,list) or any(not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.]+/[A-Za-z0-9_.]+',name) for name in opens):
            raise ValueError('Compatibility native entry declaration invalid')
        value.update(extra_classpath=[str((ASSETS/'classes').resolve())],native_main_class=main,native_add_opens=opens)
        value['compatibility'].update(active=True,reason='verified',sha256=CLASS_SHA,
            scope='Initialize missing controller context before modal description formatting')
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        value['compatibility']['reason']='asset_verification_failed'
    return value


def signature(config):
    info=config.get('compatibility',{})
    return info.get('sha256','') if info.get('active') else ''


def bundle_files(assets=None):
    """Allowlist reviewed bytes and reproducible source for clean distribution."""
    folder=Path(assets) if assets is not None else ASSETS
    raw=(folder/'manifest.json').read_bytes();manifest=json.loads(raw)
    if MANIFEST_SHA is None or hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA:
        raise ValueError('兼容组件发布清单尚未通过审阅')
    if manifest.get('id')!=ID or not manifest.get('validated') or manifest.get('forge_sha256')!=FORGE_SHA or manifest.get('patched_class_sha256')!=CLASS_SHA:
        raise ValueError('兼容组件发布清单无效')
    hashes=manifest.get('source_sha256',{})
    if set(hashes)!=SOURCE_FILES:raise ValueError('兼容组件缺少完整对应源码或许可证')
    files={'manifest.json':raw}
    for name,expected in {**hashes,CLASS_PATH:CLASS_SHA}.items():
        data=(folder/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('兼容组件源码或二进制校验失败：'+name)
        files[name]=data
    return files


def set_mode(mode):
    if mode not in {'auto','off'}:raise ValueError('请选择自动修复或原始引擎')
    if os.getenv('CUBE_FORGE_COMPAT'):raise ValueError('当前由 CUBE_FORGE_COMPAT 环境变量控制，请先移除该覆盖设置')
    from .forge_setup import RUNTIME
    from .task_control import atomic_json
    path=RUNTIME/'forge.json';value=json.loads(path.read_text(encoding='utf8'))
    value['compatibility_mode']=mode;atomic_json(path,value)
