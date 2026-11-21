"""Configurable pack passing, including multiple picks and unseeded packs."""
import random
from pathlib import Path

import pytest

from cube_ai.catalog import Catalog,exclusion_reasons
from cube_ai.config import BuildSpec
from cube_ai.draft import deal,draft_pod
from cube_ai.engine import audit
from cube_ai.vintage_data import reference


@pytest.fixture(scope='module')
def pool():
    catalog=Catalog()
    rows,unknown=catalog.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    return catalog,rows


def test_complete_passing_supports_two_picks_with_odd_pack(pool):
    catalog,rows=pool
    spec=BuildSpec.from_dict(dict(mode='classic',players=3,rounds=1,pack_size=7,pick_count=2,discard_after_pass=False))
    result=draft_pod(catalog,rows,spec,random.Random(701),readiness_hands=0)
    drafted=[name for deck in result['decks'] for name in deck['drafted']]
    assert len(drafted)==21 and len(set(drafted))==21
    assert sorted(len(d['drafted']) for d in result['decks'])==[7,7,7]
    assert set(drafted)=={name for pack in result['packs'] for name in pack}


def test_one_pass_can_consume_entire_pack_without_discarding(pool):
    catalog,rows=pool
    spec=BuildSpec.from_dict(dict(players=3,rounds=1,pack_size=6,pick_count=2,discard_after_pass=True,pack_collation='random'))
    result=draft_pod(catalog,rows,spec,random.Random(702),readiness_hands=0)
    assert [len(d['drafted']) for d in result['decks']]==[6,6,6]
    assert len({n for d in result['decks'] for n in d['drafted']})==18


def test_random_collation_does_not_require_seeded_commander_or_land_slots(pool):
    catalog,rows=pool
    main=[r for r in rows if r['role']=='Main']
    spec=BuildSpec.from_dict(dict(players=3,rounds=1,pack_size=15,pick_count=2,pack_collation='random'))
    assert len(deal(catalog,main,spec,random.Random(703)))==3


def test_vintage_restricted_card_allowed_once_but_not_in_legacy(pool):
    catalog,_=pool
    card=catalog.cards['Sol Ring']
    assert card['legalities']['vintage']=='restricted'
    vintage=BuildSpec.from_dict(dict(mode='classic',legality_format='vintage',allow_fast_mana=True,allow_colorless_costs=True))
    legacy=BuildSpec.from_dict(dict(mode='classic',legality_format='legacy',allow_fast_mana=True,allow_colorless_costs=True))
    assert '该赛制不合法/受限' not in exclusion_reasons(card,vintage)
    assert '该赛制不合法/受限' in exclusion_reasons(card,legacy)


def test_official_vintage_reference_supports_power_and_eight_player_drafting(pool):
    catalog,_=pool
    cube=reference(catalog);spec=BuildSpec.from_dict(cube['spec'])
    assert len(cube['cards'])==540 and spec.lands==96
    assert {'Black Lotus','Ancestral Recall','Mox Sapphire'}<={r['name'] for r in cube['cards']}
    assert audit(catalog,cube['cards'],spec,strict=True)['hard_errors']==0
    pod=draft_pod(catalog,cube['cards'],spec,random.Random(704),readiness_hands=0)
    assert len(pod['decks'])==8 and all(len(d['drafted'])==45 for d in pod['decks'])
    for deck in pod['decks']:
        assert deck['buildable'] and len(deck['spells'])+len(deck['lands'])+sum(deck['basics'].values())==40


def test_vintage_reference_endpoint_returns_complete_snapshot(pool,tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    import requests
    from cube_ai.ai_settings import SettingsStore
    from cube_ai.server import Application,handler_for
    catalog,_=pool
    app=Application(catalog=catalog,ai_store=SettingsStore(tmp_path/'settings.bin'),restore_history=False)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        response=requests.get(f'http://127.0.0.1:{server.server_port}/api/vintage',timeout=15)
        response.raise_for_status();data=response.json()
        assert len(data['cards'])==540 and data['spec']['legality_format']=='vintage'
        assert data['spec']['audit_profile']=='open' and data['source'].startswith('https://www.mtgo.com/')
        response=requests.post(f'http://127.0.0.1:{server.server_port}/api/analyze',
            json={'cards':data['cards'],'spec':data['spec']},timeout=30)
        response.raise_for_status()
        assert response.json()['audit']['hard_errors']==0
        language=requests.get(f'http://127.0.0.1:{server.server_port}/i18n_en.json',timeout=10)
        language.raise_for_status()
        assert len(language.json())>=250
    finally:server.shutdown();server.server_close();app.shutdown();thread.join()
