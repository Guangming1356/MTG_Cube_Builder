from datetime import date,timedelta

import pytest

from cube_ai.brackets import card_reasons
from cube_ai.catalog import Catalog,exclusion_reasons
from cube_ai.config import BuildSpec
from cube_ai import release_dates


@pytest.mark.parametrize('name',['Mind Stone','Chaos Warp','Fellwar Stone'])
def test_existing_paper_card_is_not_blocked_by_future_snapshot_reprint(name):
    card=Catalog().cards[name]
    assert card_reasons(card,BuildSpec.from_dict(dict(bracket=3)))==[]


def future(card):return dict(card,released=(date.today()+timedelta(days=365)).isoformat())


@pytest.mark.parametrize('bracket',[None,1,3,5])
def test_unknown_future_card_is_blocked_even_without_a_bracket(bracket):
    card=future(dict(name='Future test card',oracle_id='11111111-1111-1111-1111-111111111111',
                     mana_cost='{2}',text='',quality=3.0,kind='artifact'))
    assert any('纸质印张' in r for r in card_reasons(card,BuildSpec.from_dict(dict(bracket=bracket))))


def test_evidence_requires_both_oracle_id_and_name_and_does_not_leak_mutations():
    card=Catalog().cards['Mind Stone']
    first=release_dates.paper_witness(card);assert first and first['released_at']=='1997-06-09'
    first['name']='modified'
    assert release_dates.paper_witness(card)['name']=='Mind Stone'
    assert release_dates.paper_witness(dict(card,name='Another card')) is None
    assert release_dates.paper_witness(dict(card,oracle_id='11111111-1111-1111-1111-111111111111')) is None
    assert release_dates.paper_witness(card,as_of='1997-06-08') is None
    assert release_dates.paper_witness(card,as_of='1997-06-09')


@pytest.mark.parametrize('state',['missing','modified'])
def test_missing_or_tampered_evidence_cannot_unlock_future_cards(tmp_path,monkeypatch,state):
    raw=release_dates.ASSET.read_bytes();path=tmp_path/'witnesses.json'
    if state=='modified':path.write_bytes(raw+b' ')
    monkeypatch.setattr(release_dates,'ASSET',path)
    card=future(Catalog().cards['Mind Stone'])
    assert release_dates.paper_witness(card) is None
    assert any('纸质印张' in r for r in card_reasons(card,BuildSpec.from_dict(dict(bracket=3))))


def test_evidence_invalidation_after_first_success(tmp_path,monkeypatch):
    path=tmp_path/'witnesses.json';path.write_bytes(release_dates.ASSET.read_bytes())
    monkeypatch.setattr(release_dates,'ASSET',path)
    card=future(Catalog().cards['Mind Stone']);assert release_dates.paper_witness(card)
    path.write_bytes(path.read_bytes()+b' ')
    assert release_dates.paper_witness(card) is None


def test_paper_witness_never_overrides_legality_colorless_or_print_filters():
    card=future(Catalog().cards['Mind Stone'])
    banned=dict(card,legalities=dict(card['legalities'],commander='banned'))
    spec=BuildSpec.from_dict(dict(bracket=3))
    assert '该赛制不合法/受限' in exclusion_reasons(banned,spec)
    colored_cost=dict(card,mana_cost='{1}{C}')
    assert any('无色法术力' in r for r in card_reasons(colored_cost,spec))
    spec=BuildSpec.from_dict(dict(bracket=3,sets=['wth'],max_year=2020))
    assert {'不在指定快照印张系列','印张年份不符'}<=set(exclusion_reasons(card,spec))
    assert card['set']=='mbc' and card['released']>date.today().isoformat()


def test_repackage_requires_verified_data_and_includes_policy_docs(tmp_path):
    from cube_ai.tools.repackage_release import overlay_files
    app=tmp_path/'cube_ai';app.mkdir();(app/'release_dates.py').write_bytes(b'# module')
    with pytest.raises(FileNotFoundError):overlay_files(tmp_path)
    (app/'data').mkdir();target=app/'data/paper_release_witnesses.json';target.write_bytes(release_dates.ASSET.read_bytes())
    (app/'docs').mkdir();doc=app/'docs/OPTIMIZATION_20261027_COLOR_POLICY.md';doc.write_text('Public policy notes',encoding='utf8')
    overlays=overlay_files(tmp_path)
    assert overlays['cube_ai/data/paper_release_witnesses.json']==release_dates.ASSET.read_bytes()
    assert overlays['cube_ai/docs/OPTIMIZATION_20261027_COLOR_POLICY.md']==b'Public policy notes'
    target.write_bytes(target.read_bytes()+b' ')
    with pytest.raises(ValueError,match='modified'):overlay_files(tmp_path)


def test_offline_queries_are_not_required_for_release_check(monkeypatch):
    import requests
    monkeypatch.setattr(requests,'get',lambda *a,**kw:pytest.fail('Release decisions must be offline'))
    assert release_dates.paper_witness(Catalog().cards['Chaos Warp'])


def test_public_verifier_rejects_digital_future_and_wrong_identity():
    from cube_ai.tools.verify_paper_releases import witness
    card=dict(name='Test',oracle_id='11111111-1111-1111-1111-111111111111')
    p=dict(card,id='22222222-2222-2222-2222-222222222222',set='tst',lang='en',games=['paper'],digital=False,released_at='2000-01-01')
    assert witness(card,dict(object='list',data=[p]),'2026-10-27')['released_at']=='2000-01-01'
    for changed in [dict(p,games=['arena'],digital=True),dict(p,released_at='2030-01-01'),dict(p,oversized=True)]:
        assert witness(card,dict(object='list',data=[changed]),'2026-10-27') is None
    with pytest.raises(ValueError,match='mismatch'):witness(card,dict(object='list',data=[dict(p,name='Wrong')]),'2026-10-27')
    with pytest.raises(ValueError):witness(card,dict(object='list',data=[dict(p,released_at='not-a-date')]),'2026-10-27')
