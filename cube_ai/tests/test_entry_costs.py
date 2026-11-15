"""Explicit Oracle cases, ordinary ETB controls, and narrow parser boundaries."""
import pytest
from cube_ai.features import extract
from cube_ai.entry_costs import entry_burden


NEGATIVE={
    'Phyrexian Dreadnought':('sacrifice_large_power',2.),'Leveler':('exile_own_library',2.),
    'Inverter of Truth':('exile_own_library',2.5),'Sky Swallower':('give_away_board',2.),
    'Eater of Days':('skip_own_turns',2.),'Mold Demon':('sacrifice_multiple_lands',2.1),
    'Primeval Force':('sacrifice_multiple_lands',2.),'Jokulmorder':('sacrifice_multiple_lands',2.4),
    'Wormfang Manta':('skip_own_turns',2.4),
}
POSITIVE=['Sun Titan','Mulldrifter','Shriekmaw','Fleshbag Marauder','Plaguecrafter',
    "Kroxa, Titan of Death's Hunger","Uro, Titan of Nature's Wrath","Phlage, Titan of Fire's Fury",
    'Plaxmanta','Quickling','Glint Hawk','Waterspout Elemental']


@pytest.fixture(scope='module')
def catalog():
    from cube_ai.catalog import Catalog
    return Catalog()


@pytest.mark.parametrize('name',list(NEGATIVE))
def test_mandatory_burdens_do_not_receive_positive_entry_or_blink_credit(catalog,name):
    card=catalog.cards[name];risk,ceiling=NEGATIVE[name]
    assert risk in card.get('entry_risks',[]) and card['quality']<ceiling
    assert 'blink' not in card['payoffs'] and card['vector'][9]==0


@pytest.mark.parametrize('name',POSITIVE)
def test_ordinary_positive_entry_and_sacrifice_cards_have_no_severe_burden(catalog,name):
    assert 'entry_risks' not in catalog.cards[name]


@pytest.mark.parametrize('body',[
    'When this creature enters, if it was kicked, you skip your next turn.',
    'When this creature enters, each player sacrifices a creature.',
    'When this creature enters, you may sacrifice another creature. If you do, draw a card.',
    'When this creature enters, sacrifice it unless you return an artifact you control to its owner\'s hand.',
    'When another creature enters, exile all cards from your library.',
    'When this creature dies, exile all cards from your library.',
])
def test_optional_effects_other_subjects_and_other_events_are_not_mandatory_entry_costs(body):
    assert not entry_burden(body,'Fixture')['risks']


def test_an_independent_positive_entry_trigger_keeps_entry_benefit():
    text='When this creature enters, exile all cards from your library.\nWhenever this creature enters, draw a card.'
    burden=entry_burden(text,'Fixture')
    assert burden['risks']==['exile_own_library'] and not burden['negative_only']


def test_reverse_face_does_not_add_a_cost_to_the_front_face():
    raw=dict(name='Fixture Front // Fixture Back',type_line='Creature // Creature',layout='modal_dfc',cmc=2,
        card_faces=[dict(name='Fixture Front',type_line='Creature',mana_cost='{1}{U}',oracle_text='Flying',power='2',toughness='2'),
                    dict(name='Fixture Back',type_line='Creature',mana_cost='{5}{U}',oracle_text='When this creature enters, exile all cards from your library.',power='6',toughness='6')])
    assert not extract(raw,set()).get('entry_risks')


def test_risky_card_is_not_a_ban_and_is_explained_in_cube_and_deck_reports(catalog):
    from cube_ai.engine import audit
    from cube_ai.config import BuildSpec
    from cube_ai.catalog import exclusion_reasons
    from cube_ai.design import deck_design_report
    card=catalog.cards['Phyrexian Dreadnought'];spec=BuildSpec()
    assert not exclusion_reasons(card,spec)
    result=audit(catalog,[dict(name=card['name'],role='Main')],spec)
    assert any(i['severity']=='warning' and i['code']=='entry_cost' and card['name'] in i['cards'] for i in result['issues'])
    report=deck_design_report(catalog,dict(spells=[card['name']],commander=None))
    assert report['entry_costs'][0]['name']==card['name']


def test_card_details_explain_the_cost_only_for_flagged_cards(catalog,tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    import requests
    from cube_ai.server import Application,handler_for
    from cube_ai.ai_settings import SettingsStore
    app=Application(ai_store=SettingsStore(tmp_path/'settings.bin'),restore_history=False);app._catalog=catalog
    http=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        url=f'http://127.0.0.1:{http.server_port}/api/card'
        card=requests.get(url,params=dict(name='Phyrexian Dreadnought')).json()
        assert card['entry_risks']==['sacrifice_large_power'] and '总力量' in card['entry_cost_notes'][0]
        assert 'entry_cost_notes' not in requests.get(url,params=dict(name='Sun Titan')).json()
        phage=requests.get(url,params=dict(name='Phage the Untouchable')).json()
        assert phage['commander'] and phage['commander_setup']==['hand_cast_required']
        assert '败北' in phage['commander_setup_notes'][0]
        assert 'commander_setup_notes' not in requests.get(url,params=dict(name='Sun Titan')).json()
    finally:http.shutdown();http.server_close();app.shutdown();thread.join()


def test_card_detail_renderer_uses_notes_and_omits_empty_notices():
    import shutil,subprocess
    from pathlib import Path
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed only for this developer component test')
    script=Path(__file__).parent/'js/test_entry_details.cjs'
    result=subprocess.run([node,str(script)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    assert '"passed":3' in result.stdout
