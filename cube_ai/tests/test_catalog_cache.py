"""Cache format must preserve data and recover through the original source."""
import copy
import json

import pytest

from cube_ai import catalog as module


@pytest.fixture
def data():
    return dict(signature='fixture',snapshot='2026-10-08',version='fixture',cards=[
        dict(name='one',legalities={'commander':'legal','modern':'banned'}),
        dict(name='two',legalities={'commander':'legal','modern':'banned'}),
        dict(name='reverse',legalities={'modern':'banned','commander':'legal'})])


def test_packed_cache_preserves_order_values_sharing_and_input(tmp_path,data):
    before=copy.deepcopy(data);path=tmp_path/'catalog.json';module._write_catalog_cache(data,path)
    disk=json.loads(path.read_text(encoding='utf8'))
    assert disk['_catalog_cache_format']==2 and len(disk['_legalities_pool'])==2
    actual=module._decode_catalog_cache(module._read_catalog_json(path))
    assert json.dumps(actual)==json.dumps(data) and data==before
    a,b,reverse=[c['legalities'] for c in actual['cards']]
    assert a is b and reverse is not a
    with pytest.raises(TypeError):a['commander']='banned'


@pytest.mark.parametrize('reserved,value',[('_catalog_cache_format',99),('_legalities_pool',['unrelated legacy metadata'])])
def test_metadata_cannot_override_format_owned_fields(tmp_path,data,reserved,value):
    data[reserved]=value;path=tmp_path/'catalog.json';module._write_catalog_cache(data,path)
    actual=module._decode_catalog_cache(module._read_catalog_json(path))
    assert actual['cards']==data['cards'] and actual['signature']==data['signature']


@pytest.mark.parametrize('index',[True,-1,2,None,'0',1.5,{}])
def test_bad_references_are_rejected(data,index):
    value=dict(data,_catalog_cache_format=2,_legalities_pool=[{'commander':'legal'}])
    value['cards']=copy.deepcopy(data['cards']);value['cards'][0]['legalities']=index
    with pytest.raises(ValueError,match='引用'):module._decode_catalog_cache(value)


@pytest.mark.parametrize('version',[True,1,3,None,'2'])
def test_unknown_formats_are_rejected(data,version):
    with pytest.raises(ValueError,match='格式'):module._decode_catalog_cache(dict(data,_catalog_cache_format=version))


@pytest.mark.parametrize('pool',[None,{},['bad'],[{'commander':True}]])
def test_invalid_maps_are_rejected(data,pool):
    with pytest.raises(ValueError):module._decode_catalog_cache(dict(data,_catalog_cache_format=2,_legalities_pool=pool))


def test_failed_replace_keeps_old_cache_and_removes_owned_temp(tmp_path,data,monkeypatch):
    path=tmp_path/'catalog.json';path.write_bytes(b'old cache');before=set(tmp_path.iterdir())
    def fail(*args):raise PermissionError('target busy')
    monkeypatch.setattr(module.os,'replace',fail)
    with pytest.raises(PermissionError):module._write_catalog_cache(data,path)
    assert path.read_bytes()==b'old cache' and set(tmp_path.iterdir())==before


def test_legacy_migration_readonly_failure_and_corruption_recovery(tmp_path,monkeypatch):
    source=tmp_path/'source.json';source.write_text(json.dumps(dict(date='2026-10-08',cards={
        'Fixture':dict(name='Fixture',type_line='Creature',legalities={'commander':'legal'})})),encoding='utf8')
    cache_dir=tmp_path/'data';cache_dir.mkdir();cache=cache_dir/'catalog.json'
    monkeypatch.setattr(module,'DATA',cache_dir)
    monkeypatch.setattr(module,'tribes_from_cards',lambda cards:set())
    monkeypatch.setattr(module,'extract',lambda card,tribes:dict(quality=3.0,kind='creature'))
    original=module.Catalog(source=source,use_cache=False)
    legacy=module._decode_catalog_cache(module._read_catalog_json(cache));cache.write_text(json.dumps(legacy),encoding='utf8')
    old_bytes=cache.read_bytes();writer=module._write_catalog_cache
    def fail(*args):raise PermissionError('readonly installation')
    with monkeypatch.context() as scoped:
        scoped.setattr(module,'_write_catalog_cache',fail)
        assert module.Catalog(source=source).cards==original.cards
    assert cache.read_bytes()==old_bytes
    assert module.Catalog(source=source).cards==original.cards
    assert json.loads(cache.read_text(encoding='utf8'))['_catalog_cache_format']==2
    corrupted=json.loads(cache.read_text(encoding='utf8'));corrupted['cards'][0]['legalities']=True
    cache.write_text(json.dumps(corrupted),encoding='utf8')
    assert module.Catalog(source=source).cards==original.cards
    repaired=module._decode_catalog_cache(module._read_catalog_json(cache))
    assert repaired['cards']==legacy['cards'] and module._write_catalog_cache is writer
