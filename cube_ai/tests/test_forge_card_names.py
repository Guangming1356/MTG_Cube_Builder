import pytest
import hashlib
import json
from types import SimpleNamespace
import zipfile

from cube_ai.forge_card_names import script_names


@pytest.mark.parametrize('text,names',[
    ('Name:Front\nManaCost:2 R W\n',('Front',)),
    ('\ufeffName:Chief Jim Hopper\r\nVariant:UniversesWithin:FlavorName:Sophina, Spearsage Deserter\r\n',
     ('Chief Jim Hopper','Sophina, Spearsage Deserter')),
    ('Name:Front\nVariant:UniversesWithin:FlavorName:Within Front\nALTERNATE\nName:Back\nVariant:UniversesWithin:FlavorName:Within Back\n',
     ('Front','Within Front')),
    ('Name:Front\nOracle:Mention Name:Invented or Variant:UniversesWithin:FlavorName:Fake\n',('Front',)),
    ('Name:Front\nVariant:Unsupported:FlavorName:Fake\nVariant:UniversesWithin:FlavorName:front\n',('Front',)),
    ('Variant:UniversesWithin:FlavorName:Name Without A Script\n',()),
])
def test_native_name_parser_preserves_explicit_front_variants_only(text,names):
    assert script_names(text.encode('utf8'))==names


def test_pinned_asset_and_packaging_fail_closed(tmp_path,monkeypatch):
    from cube_ai import forge_card_names as names
    assert len(names.name_pairs())==182
    assert len(names.trace_name_pairs())==189
    assert dict(names.name_pairs())['Sophina, Spearsage Deserter']=='Chief Jim Hopper'
    raw=names.ASSET.read_bytes()
    assert names.bundle_alias_asset(names.ASSET)=={'cube_ai/data/forge_name_aliases.json':raw}
    path=tmp_path/'altered.json';path.write_bytes(raw+b' ')
    with pytest.raises(ValueError):names.bundle_alias_asset(path)
    monkeypatch.setattr(names,'ASSET',path)
    assert names.name_pairs()==() and names.trace_name_pairs()==()
    path.unlink()
    assert names.name_pairs()==()


def test_runtime_binding_requires_jar_scripts_editions_and_no_overrides(tmp_path,monkeypatch):
    from cube_ai import forge_card_names as names
    from cube_ai import forge
    home=tmp_path/'engine';folder=home/'res/cardsfolder';folder.mkdir(parents=True)
    archive=folder/'cardsfolder.zip'
    script='Name:Chief Jim Hopper\nVariant:UniversesWithin:FlavorName:Sophina, Spearsage Deserter\nALTERNATE\nName:Back\nVariant:UniversesWithin:FlavorName:Fake Back\n'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('test.txt',script)
    editions=home/'res/editions';editions.mkdir();edition=editions/'TEST.txt';edition.write_bytes(b'edition')
    digest=hashlib.sha256(b'TEST.txt\0'+hashlib.sha256(b'edition').digest()).hexdigest()
    manifest=dict(forge_sha256='exact',script_archives=[dict(name='res/cardsfolder/cardsfolder.zip',sha256=hashlib.sha256(archive.read_bytes()).hexdigest())],editions_sha256=digest,pairs=[dict(requested='Sophina, Spearsage Deserter',native='Chief Jim Hopper')])
    monkeypatch.setattr(names,'_load',lambda:manifest)
    config=dict(home=str(home),jar_sha256='exact')
    assert names.verified_runtime_aliases(config,[archive],[],[edition])=={'Sophina, Spearsage Deserter'}
    index=forge.card_index(config)
    assert index['sophina, spearsage deserter']=='Sophina, Spearsage Deserter'
    assert index['chief jim hopper']=='Chief Jim Hopper' and 'fake back' not in index
    original_loader=names._load
    def unavailable():raise ValueError('modified manifest')
    monkeypatch.setattr(names,'_load',unavailable)
    assert 'sophina, spearsage deserter' not in forge.card_index(config)
    forge._indices.clear() # The persistent cache must fail closed as well.
    assert 'sophina, spearsage deserter' not in forge.card_index(config)
    monkeypatch.setattr(names,'_load',original_loader)
    assert not names.verified_runtime_aliases(dict(config,jar_sha256='other'),[archive],[],[edition])
    assert not names.verified_runtime_aliases(config,[archive],[folder/'override.txt'],[edition])
    edition.write_bytes(b'changed edition')
    assert not names.verified_runtime_aliases(config,[archive],[],[edition])
    assert 'sophina, spearsage deserter' not in forge.card_index(config)
    edition.write_bytes(b'edition')
    with zipfile.ZipFile(archive,'a') as z:z.writestr('other.txt','Name:Unverified\n')
    assert not names.verified_runtime_aliases(config,[archive],[],[edition])


def test_catalog_alias_resolves_without_overwriting_existing_names():
    from cube_ai.catalog import Catalog
    from cube_ai.forge_card_names import add_catalog_aliases
    name='Sophina, Spearsage Deserter';card=dict(name=name,legality={})
    catalog=Catalog.from_records([card],'fixture','signature')
    assert catalog.resolve('Chief Jim Hopper')==name
    aliases={name.casefold():name,'chief jim hopper':'already known'}
    add_catalog_aliases(aliases)
    assert aliases['chief jim hopper']=='already known'
    assert catalog.cards[name]==card


def test_native_log_primary_and_back_names_recover_catalog_names():
    from cube_ai.optimize import game_trace
    front='Sophina, Spearsage Deserter'
    double='Casal, Lurkwood Pathfinder // Casal, Pathbreaker Owlbear'
    cards={n:dict(finisher=n==double,interaction=False) for n in [front,double]}
    deck=dict(id='a',spells=[double],commander=front)
    log='\n\n'.join(['Turn: Turn 1 (Ai(1)-a)',
        'Add To Stack: Ai(1)-a cast Chief Jim Hopper',
        'Add To Stack: Ai(1)-a triggered Chief Jim Hopper targeting a',
        'Add To Stack: Ai(1)-a cast Doric, Owlbear Avenger',
        'Add To Stack: Ai(1)-a activated Doric, Nature\'s Warden (1)',
        'Add To Stack: Ai(1)-a cast Chief Jim Hoppers'])+'\n\n'
    p=game_trace(SimpleNamespace(cards=cards),log,[deck],extended=True)['players']['a']
    assert p['casts']=={front:1,double:1} and p['finisher_casts']==1
    assert p['activations']=={front:1,double:1} and p['spellcasts']==3


def test_maintainer_manifest_rejects_incomplete_or_wrong_native_resolution(tmp_path):
    from cube_ai.tools.verify_card_names import inspect_scripts,build_manifest
    home=tmp_path/'engine';folder=home/'res/cardsfolder';folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'cards.zip','w') as z:
        z.writestr('test.txt','Name:Native Front\nVariant:UniversesWithin:FlavorName:Within Front\nALTERNATE\nName:Native Back\nVariant:UniversesWithin:FlavorName:Within Back\n')
    (home/'res/editions').mkdir();(home/'res/editions/ED.txt').write_bytes(b'fixed')
    scripts=inspect_scripts(home)
    assert scripts['mapping']=={'Within Front':'Native Front'}
    assert scripts['back_faces']==[dict(requested='Within Back',native='Native Back',front='Within Front')]
    source=tmp_path/'helper.java';source.write_bytes(b'fixture')
    args=(dict(jar_sha256='jar'),scripts)
    compiler=dict(sha256='compiler',source='https://example.com/compiler')
    with pytest.raises(ValueError,match='incomplete'):build_manifest(*args,{},source,compiler)
    record={'Within Front':dict(found=True,loaded_name='Native Front',rules_name='Native Front')}
    manifest=build_manifest(*args,record,source,compiler)
    assert manifest['query']['resolved_to_declared_primary']==1
    assert manifest['query']['loaded_under_requested_name']==0
    record['Within Front']['rules_name']='Different rules'
    with pytest.raises(ValueError,match='declared primary'):build_manifest(*args,record,source,compiler)
    (folder/'override.txt').write_bytes(b'Name:Override')
    with pytest.raises(ValueError,match='overrides'):inspect_scripts(home)
