import random
from types import SimpleNamespace

import pytest

from cube_ai.brackets import DeckRules,card_reasons,may_add
from cube_ai.catalog import Catalog,exclusion_reasons
from cube_ai.config import BuildSpec
from cube_ai.draft import draft_pod
from cube_ai.engine import audit,quotas
from cube_ai.llm import plan_schema
from cube_ai.mana import commander_basic_sources,requires_colorless_mana


@pytest.fixture(scope='module')
def catalog():return Catalog()


@pytest.mark.parametrize('name',['Eldrazi Confluence','Warping Wail',"Kozilek's Command",'Eldrazi Displacer','Mirrorpool','Ulalek, Fused Atrocity'])
def test_colorless_payments_excluded_by_default_but_can_be_enabled(catalog,name):
    card=catalog.cards[name]
    assert requires_colorless_mana(card)
    assert any('无色法术力' in r for r in exclusion_reasons(card,BuildSpec()))
    assert not any('无色法术力' in r for r in exclusion_reasons(card,BuildSpec(allow_colorless_costs=True)))


@pytest.mark.parametrize('name',['Mind Stone','Worn Powerstone','Llanowar Wastes','Arcane Signet','Wurmcoil Engine'])
def test_producing_colorless_generic_or_hybrid_costs_are_not_required_colorless(catalog,name):
    assert not requires_colorless_mana(catalog.cards[name])


@pytest.mark.parametrize('text',[
    'Ward {C}', 'Kicker {2}{C}', 'You may pay {1}{C}. If you do, draw a card.',
    '{2}{C}, {T}: Exile target creature.',
])
def test_keyword_triggered_and_activated_payments(text):
    assert requires_colorless_mana(dict(mana_cost='{3}',text=text))


def test_producer_reminder_and_multiple_abilities_are_distinct_from_payments():
    for text in ['{T}: Add {C}.', '({C} represents colorless mana.)',
                 'Create a token with "Sacrifice this token: Add {C}."',
                 '{T}: Add {C}. {T}, Sacrifice this artifact: Draw a card.']:
        assert not requires_colorless_mana(dict(mana_cost='{2}',text=text))
    assert requires_colorless_mana(dict(mana_cost='{2}',text='{T}: Add {C}. {C}, Sacrifice this artifact: Draw a card.'))
    assert not requires_colorless_mana(dict(mana_cost='{C/W}{C/U}',text='Flying'))


@pytest.mark.parametrize('bracket',[None,1,3,5])
def test_deck_selection_and_one_off_checks_respect_preference_without_a_bracket(catalog,bracket):
    spec=BuildSpec.from_dict(dict(bracket=bracket))
    catalog=SimpleNamespace(cards={n:dict(catalog.cards[n],released='2020-01-01',quality=3.0) for n in ['Warping Wail','Mind Stone']})
    names=['Warping Wail','Mind Stone']
    assert DeckRules(catalog,spec).select([],names)==['Mind Stone']
    assert not may_add(catalog,[],'Warping Wail',spec)
    assert card_reasons(catalog.cards['Warping Wail'],spec)


def test_option_roundtrip_schema_and_boolean_validation():
    assert BuildSpec.from_dict().allow_colorless_costs is False
    assert BuildSpec.from_dict(dict(allow_colorless_costs=True)).to_dict()['allow_colorless_costs'] is True
    assert plan_schema()['properties']['allow_colorless_costs']==dict(type='boolean')
    with pytest.raises(ValueError,match='allow_colorless_costs'):BuildSpec.from_dict(dict(allow_colorless_costs='false'))


def test_no_colorless_commander_slot_and_no_artifact_legend_as_fallback(catalog):
    assert 'C' not in quotas(BuildSpec())[1]
    names=['The Vision','Mind Stone','Wurmcoil Engine','Worn Powerstone','Solemn Simulacrum','Wayfarer\'s Bauble','Arcane Signet']
    packs=[[dict(name=n,role='Main') for n in names] for _ in range(3)]
    spec=BuildSpec(rounds=1,pack_size=7)
    pod=draft_pod(catalog,[],spec,random.Random(42),['UW','BR','GU'],readiness_hands=0,_packs=packs)
    assert all(not d['buildable'] for d in pod['decks'])
    report=audit(catalog,[dict(name='The Vision',role='Commander')],spec)
    assert any(i['code']=='colorless_commander' for i in report['issues'])


def test_commander_sources_can_supply_a_splash_absent_from_selected_spells():
    catalog=SimpleNamespace(cards={'commander':dict(mana_cost='{2}{B}{R}'),'spell':dict(mana_cost='{B}{B}')})
    before={'B':23}
    assert commander_basic_sources(catalog,['spell'],[],before,'commander')==dict(B=22,R=1)
    assert before==dict(B=23)


def test_commander_source_repair_credits_nonbasics_and_preserves_other_spell_costs():
    catalog=SimpleNamespace(cards={'commander':dict(mana_cost='{2}{B}{R}'),'spell':dict(mana_cost='{B}{B}'),
                                  'dual':dict(fixing=['B','R'])})
    assert commander_basic_sources(catalog,['spell'],['dual'],dict(B=22),'commander')==dict(B=22)
    # Two basics cannot pay both BB and the BR commander. Keep the original
    # allocation instead of silently breaking a previously payable spell.
    assert commander_basic_sources(catalog,['spell'],[],dict(B=2),'commander')==dict(B=2)


def test_commander_repair_does_not_introduce_wastes_or_change_sourced_decks():
    catalog=SimpleNamespace(cards={'commander':dict(mana_cost='{C}{C}'),'colored':dict(mana_cost='{G}'),
                                  'green':dict(fixing=['G'])})
    assert commander_basic_sources(catalog,[],[],dict(B=23),'commander')==dict(B=23)
    assert commander_basic_sources(catalog,[],['green'],dict(B=22),'colored')==dict(B=22)
