"""Names explicitly declared by a native script's front card and its variants.

UniversesWithin names are enabled only for the exact loader and data inspected
in the pinned manifest. Native primary names are mapped back when reading logs.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import re
from .config import ROOT


INDEX_VERSION='forge-card-index-2-front-variants'
ASSET=ROOT/'data/forge_name_aliases.json'
ASSET_SHA='953de295493de20a2c6b14f0a5bf46a9c5ef148a6070dfc417963ef2ff32bb9e'


@lru_cache(maxsize=4)
def _asset(path,size,modified):
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ASSET_SHA:raise ValueError('Native name manifest hash mismatch')
    return json.loads(raw)


def _load():
    stat=ASSET.stat()
    return _asset(str(ASSET.resolve()),stat.st_size,stat.st_mtime_ns)


def name_pairs():
    """Verified native primary-name bindings; also used to read native logs."""
    try:return tuple((p['requested'],p['native']) for p in _load()['pairs'])
    except (OSError,ValueError,KeyError,TypeError):return ()


def manifest_available():
    try:return bool(_load())
    except (OSError,ValueError,KeyError,TypeError):return False


def trace_name_pairs():
    try:return name_pairs()+tuple((p['requested'],p['native']) for p in _load().get('back_faces',[]))
    except (OSError,ValueError,KeyError,TypeError):return name_pairs()


def add_catalog_aliases(aliases):
    for requested,native in name_pairs():
        a=aliases.get(requested.casefold());b=aliases.get(native.casefold())
        if a and not b:aliases[native.casefold()]=a
        elif b and not a:aliases[requested.casefold()]=b


def bundle_alias_asset(path):
    path=Path(path);raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ASSET_SHA:raise ValueError('Native name manifest missing or modified')
    return {'cube_ai/data/forge_name_aliases.json':raw}


@lru_cache(maxsize=2048)
def _file_sha(path,size,modified):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@lru_cache(maxsize=4)
def _editions_sha(root,metadata):
    digest=hashlib.sha256()
    for name,size,modified in metadata:
        digest.update(name.encode('utf8')+b'\0')
        digest.update(bytes.fromhex(_file_sha(str(Path(root)/name),size,modified)))
    return digest.hexdigest()


def verified_runtime_aliases(config,archives,loose,editions):
    """Enable only bindings inspected with these exact scripts and editions."""
    try:
        data=_load()
        if loose or config.get('jar_sha256')!=data['forge_sha256']:return frozenset()
        home=Path(config['home']);actual=[]
        for path in archives:
            stat=path.stat()
            actual.append(dict(name=path.relative_to(home).as_posix(),sha256=_file_sha(str(path.resolve()),stat.st_size,stat.st_mtime_ns)))
        if sorted(actual,key=lambda p:p['name'])!=sorted(data['script_archives'],key=lambda p:p['name']):return frozenset()
        root=home/'res/editions';metadata=[]
        for path in editions:
            stat=path.stat();metadata.append((path.relative_to(root).as_posix(),stat.st_size,stat.st_mtime_ns))
        if _editions_sha(str(root.resolve()),tuple(sorted(metadata)))!=data['editions_sha256']:return frozenset()
        return frozenset(p['requested'] for p in data['pairs'])
    except (OSError,ValueError,KeyError,TypeError):return frozenset()


def script_names(raw):
    text=raw.decode('utf-8-sig',errors='replace')
    front=re.split(r'^ALTERNATE\s*$',text,maxsplit=1,flags=re.M)[0]
    primary=re.search(r'^Name:([^\r\n]+)',front,re.M)
    if primary is None:return ()
    names=[primary[1].strip()]
    names.extend(value.strip() for value in re.findall(
        r'^Variant:UniversesWithin:FlavorName:([^\r\n]+)',front,re.M))
    unique=[];seen=set()
    for name in names:
        if name and name.casefold() not in seen:
            seen.add(name.casefold());unique.append(name)
    return tuple(unique)
