import json
from pathlib import Path

import pytest

from cube_ai.card_roles import creature_types,resource_roles


CASES=json.loads((Path(__file__).parent/'fixtures/resource_roles.json').read_bytes())['cases']


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['split']+'-'+c['topic']+'-'+c['name'])
def test_reviewed_resource_boundaries_and_frozen_holdout(case):
    roles=resource_roles(dict(type_line=case['type'],oracle_text=case['text']))
    assert roles['draw_source' if case['topic']=='draw' else 'equipment_piece']==case['expected_resource']


def test_mixed_card_types_do_not_make_artifact_or_land_subtypes_into_tribes():
    cards=[dict(type_line=t) for t in ['Artifact Creature — Equipment Insect',
        'Land Creature — Forest Dryad','Enchantment Creature — Shrine',
        'Creature — Time Lord Doctor','Kindred Enchantment — Elf','Creature — Dragon']]
    assert creature_types(cards)=={'insect','dryad','time lord','doctor','elf','dragon'}
    from cube_ai.features import tribal_requirements
    tribes=creature_types(cards)
    assert tribal_requirements('Other Time Lords you control get +1/+1.',tribes)==['time lord']
    assert tribal_requirements('Each time you draw a card, gain 1 life.',tribes)==[]
    assert tribal_requirements('Search your library for a Forest card.',tribes)==[]
    assert tribal_requirements('Other Dragons you control have haste.',tribes)==['dragon']


@pytest.mark.parametrize('text,expected',[
    ('Each opponent draws a card.',False),
    ('Target player draws two cards.',True),
    ('Whenever an opponent draws a card, each opponent loses 1 life.',False),
    ('Whenever you draw a card, draw a card.',True),
    ('If you would draw a card, draw two cards instead.',False),
    ('Whenever you cast a spell, if you control an artifact, draw a card.',True),
])
def test_draw_effects_are_separate_from_conditions_and_beneficiaries(text,expected):
    assert resource_roles(dict(type_line='Enchantment',oracle_text=text))['draw_source']==expected


def test_modal_equipment_face_is_a_resource_but_equipment_tutor_is_access():
    card=dict(type_line='Legendary Creature — God // Legendary Artifact — Equipment',oracle_text='Equip {2}')
    assert resource_roles(card)['equipment_piece']
    roles=resource_roles(dict(type_line='Sorcery',oracle_text='Search your library for an Equipment card, put it into your hand, then shuffle.'))
    assert not roles['equipment_piece'] and roles['equipment_access'] and roles['equipment_payoff']
