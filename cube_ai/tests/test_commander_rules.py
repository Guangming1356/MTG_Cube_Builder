"""Eligibility, command-zone setup policy and whole-deck commander selection."""
from dataclasses import replace
import random
from types import SimpleNamespace
import pytest

from cube_ai.config import BuildSpec
from cube_ai.commander_rules import eligible,automatic
from cube_ai.draft import build_deck

@pytest.fixture(scope='module')
def catalog():
    from cube_ai.catalog import Catalog
    return Catalog()

@pytest.mark.parametrize('name',['Grist, the Hunger Tide','The Belligerent','Inspirit, Flagship Vessel',
    'Hearthhull, the Worldseed','The Seriema','Heart of Kiran','Shorikai, Genesis Engine'])
def test_current_eligible_commanders_include_grist_vehicles_and_spacecraft(catalog,name):
    assert catalog.cards[name]['commander']

@pytest.mark.parametrize('name',['The Eternity Elevator','Invasion of Kaladesh // Aetherwing, Golden-Scale Flagship',
    'Luxior, Giada\'s Gift','Teferi, Hero of Dominaria','Candlekeep Sage'])
def test_nonqualifying_front_faces_and_unconditional_backgrounds_are_not_single_commanders(catalog,name):
    assert not catalog.cards[name]['commander']

def test_grist_remains_a_planeswalker_for_battlefield_body_metrics(catalog):
    card=catalog.cards['Grist, the Hunger Tide']
    assert card['kind']=='planeswalker' and not card['creature'] and card['vector'][10]==1

@pytest.mark.parametrize('name',['Phage the Untouchable','Haakon, Stromgald Scourge','Asmoranomardicadaistinaculdacar'])
def test_legal_setup_commanders_are_default_automatic_opt_out(catalog,name):
    card=catalog.cards[name];spec=BuildSpec()
    assert card['commander'] and card['commander_setup'] and not automatic(card,spec)
    assert automatic(card,replace(spec,allow_setup_commanders=True))

def test_colorless_commander_policy_stays_in_effect_for_new_types(catalog):
    assert not automatic(catalog.cards['Heart of Kiran'],BuildSpec(allow_setup_commanders=True))

def test_graveyard_knight_cast_permission_is_recognized_as_a_tribal_dependency(catalog):
    assert 'knight' in catalog.cards['Haakon, Stromgald Scourge']['tribal']

@pytest.mark.parametrize('typ,power,toughness,expected',[
    ('Artifact — Vehicle','4','4',False),('Legendary Artifact — Vehicle','4','4',True),
    ('Legendary Artifact — Spacecraft',None,None,False),('Legendary Artifact — Spacecraft','*','*',True)])
def test_front_type_and_printed_spacecraft_boxes(typ,power,toughness,expected):
    assert eligible(dict(type_line=typ,oracle_text='',power=power,toughness=toughness)) is expected

def example_pool(catalog,strong,weak):
    base=catalog.cards['Gonti, Lord of Luxury'];filler=catalog.cards['Solemn Simulacrum']
    cards={n:dict(base,name=n,quality=q) for n,q in [('Weak commander',weak),('Strong commander',strong)]}
    cards.update({f'Filler {i}':dict(filler,name=f'Filler {i}',quality=3.) for i in range(45)})
    return SimpleNamespace(cards=cards),list(cards)

@pytest.mark.parametrize('strong,weak',[(4.,2.),(3.501,3.499)])
def test_whole_deck_objective_counts_the_commander_and_breaks_equal_totals_by_its_quality(catalog,strong,weak):
    example,pool=example_pool(catalog,strong,weak);before=list(pool)
    deck=build_deck(example,pool,BuildSpec(),random.Random(1),'BW',readiness_hands=0)
    assert deck['commander']=='Strong commander' and pool==before
    assert len(deck['spells'])+len(deck['lands'])+sum(deck['basics'].values())+1==60

def test_pool_with_only_setup_commander_has_an_explanation_and_explicit_opt_in(catalog):
    names=['Phage the Untouchable','Sol Ring','Swords to Plowshares']
    spec=BuildSpec()
    before=build_deck(catalog,names,spec,random.Random(1),'BW',readiness_hands=0)
    assert not before['buildable'] and '专门' in before['construction_warning']
    after=build_deck(catalog,names,replace(spec,allow_setup_commanders=True),random.Random(1),'BW',readiness_hands=0)
    assert after['buildable'] and after['commander']=='Phage the Untouchable'
    assert after['commander_setup_notes'] and after['design']['commander_setup']

def test_normal_hand_cast_of_phage_can_stay_in_the_main_deck(catalog):
    names=['Gonti, Lord of Luxury','Phage the Untouchable','Mind Stone']
    deck=build_deck(catalog,names,BuildSpec(),random.Random(1),'BW',readiness_hands=0)
    assert deck['commander']=='Gonti, Lord of Luxury' and 'Phage the Untouchable' in deck['spells']

@pytest.mark.parametrize('value',[None,1,'true',[],{}])
def test_setup_flag_must_be_boolean(value):
    with pytest.raises(ValueError,match='allow_setup_commanders'):BuildSpec.from_dict(dict(allow_setup_commanders=value))

def test_old_specs_default_to_ordinary_automatic_commanders():
    assert BuildSpec.from_dict().allow_setup_commanders is False
    spec=BuildSpec(allow_setup_commanders=True)
    assert BuildSpec.from_dict(spec.to_dict())==spec


def test_another_named_creature_outside_battlefield_does_not_grant_eligibility():
    text="As long as Grist isn't on the battlefield, it's a 1/1 Insect creature in addition to its other types."
    assert not eligible(dict(name='Other permanent',type_line='Legendary Enchantment',oracle_text=text))
    assert eligible(dict(name='Grist, the Hunger Tide',type_line='Legendary Planeswalker — Grist',oracle_text=text))


def test_another_named_graveyard_spell_is_not_a_self_cast_restriction():
    from cube_ai.commander_rules import setup_requirements
    assert not setup_requirements('You may cast Haakon from your graveyard, but not from anywhere else.','Other card','{3}')


def test_actual_form_preserves_setup_option_for_old_and_new_specs():
    import json,shutil,subprocess
    from pathlib import Path
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the developer form component test')
    samples=[BuildSpec.from_dict(dict(bracket=3)).to_dict(),BuildSpec(allow_setup_commanders=True,allow_extra_turns=True).to_dict()]
    old=dict(samples[0]);old.pop('allow_setup_commanders');samples.append(old)
    result=subprocess.run([node,str(Path(__file__).parent/'js/test_spec_roundtrip.cjs')],input=json.dumps(samples),capture_output=True,text=True,encoding='utf8',timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    restored=json.loads(result.stdout)
    assert [BuildSpec.from_dict(s) for s in restored]==[BuildSpec.from_dict(s) for s in samples]


def test_ai_plan_schema_exposes_setup_policy():
    from cube_ai.llm import plan_schema
    assert plan_schema()['properties']['allow_setup_commanders']=={'type':'boolean'}
