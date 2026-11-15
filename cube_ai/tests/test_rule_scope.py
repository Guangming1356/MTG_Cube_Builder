"""Rule reuse is table-local; text parsing alone may be cached across tables."""
from dataclasses import replace
from collections import Counter
import random
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from cube_ai.brackets import DeckRules,card_reasons,deck_report,extra_turn,_extra_turn_text
from cube_ai.config import BuildSpec
from cube_ai.draft import build_deck,draft_pod
from cube_ai.deck_building import revise


@pytest.fixture(scope='module')
def fixture():
    from pathlib import Path
    from cube_ai.catalog import Catalog
    catalog=Catalog();rows,unknown=catalog.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    return catalog,rows


@pytest.mark.parametrize('bracket',[None,1,2,3,4,5])
def test_reused_reasons_and_fresh_reports_match_one_off_checks(fixture,bracket):
    catalog,_=fixture;spec=BuildSpec.from_dict(dict(bracket=bracket));rules=DeckRules(catalog,spec)
    names=['Gonti, Lord of Luxury','Mind Stone','Warping Wail','Time Warp','Rhystic Study','Cyclonic Rift','Island']
    for name in names:
        expected=card_reasons(catalog.cards[name],spec)
        assert list(rules.reasons(name))==expected and rules.allowed(name)==(not expected)
    deck=dict(commander=names[0],spells=names[1:-1],lands=names[-1:])
    assert deck_report(catalog,deck,spec,_rules=rules)==deck_report(catalog,deck,spec)


def test_complete_build_checks_each_card_at_most_once_in_the_shared_scope(fixture):
    catalog,rows=fixture;spec=BuildSpec.from_dict(dict(bracket=3,deck_policy='balanced'))
    source=draft_pod(catalog,rows,spec,random.Random(1937),readiness_hands=0)['decks'][0]
    rules=DeckRules(catalog,spec);names=[]
    def counted(card,*args,**kwargs):names.append(card['name']);return card_reasons(card,*args,**kwargs)
    with patch('cube_ai.brackets.card_reasons',side_effect=counted):
        actual=build_deck(catalog,source['drafted'],spec,random.Random(1937),source['guild'],readiness_hands=0,_rules=rules)
        assert actual['buildable'];deck_report(catalog,actual,spec,_rules=rules)
        revise(catalog,actual,spec,_rules=rules)
    assert names and max(Counter(names).values())==1 and set(names)<=set(source['drafted'])


@pytest.mark.parametrize('entry',['build','revise','report'])
@pytest.mark.parametrize('mismatch',['catalog','spec'])
def test_wrong_rule_scope_is_rejected_before_it_can_affect_a_deck(fixture,entry,mismatch):
    catalog,_=fixture;spec=BuildSpec();rules=DeckRules(catalog,spec)
    other_catalog=SimpleNamespace(cards=catalog.cards) if mismatch=='catalog' else catalog
    other_spec=replace(spec) if mismatch=='spec' else spec
    deck=dict(buildable=False,spells=[],lands=[],commander=None,drafted=[])
    with pytest.raises(ValueError,match='上下文'):
        if entry=='build':build_deck(other_catalog,[],other_spec,random.Random(0),'UW',_rules=rules)
        elif entry=='revise':revise(other_catalog,deck,other_spec,_rules=rules)
        else:deck_report(other_catalog,deck,other_spec,_rules=rules)


def test_new_parameters_get_fresh_checks_instead_of_old_decisions(fixture):
    catalog,_=fixture;blocked=BuildSpec(allow_colorless_costs=False);allowed=replace(blocked,allow_colorless_costs=True)
    first=DeckRules(catalog,blocked);second=DeckRules(catalog,allowed)
    assert not first.allowed('Warping Wail') and second.allowed('Warping Wail')
    assert not first.allowed('Warping Wail')  # A later request cannot rewrite the earlier context.


def test_new_catalog_content_is_not_hidden_by_a_global_legality_cache(fixture):
    catalog,_=fixture;spec=BuildSpec.from_dict(dict(bracket=3))
    cards=dict(catalog.cards);cards['Mind Stone']=dict(cards['Mind Stone'],quality=5.)
    changed=SimpleNamespace(cards=cards)
    assert DeckRules(catalog,spec).allowed('Mind Stone')
    assert not DeckRules(changed,spec).allowed('Mind Stone')


def test_rejection_reasons_cannot_be_mutated_by_a_report_consumer(fixture):
    catalog,_=fixture;rules=DeckRules(catalog,BuildSpec());reasons=rules.reasons('Warping Wail')
    assert isinstance(reasons,tuple) and reasons
    with pytest.raises(TypeError):reasons[0]='changed'
    assert rules.reasons('Warping Wail')==reasons


@pytest.mark.parametrize('text,expected',[
    ('Take an extra turn after this one.',True),('Target opponent takes two extra turns.',True),
    ('TAKE X EXTRA TURNS.',True),('You skip your next two turns.',False),
    ('At the beginning of your next upkeep, draw a card.',False),('',False)])
def test_extra_turn_text_cache_preserves_classification(text,expected):
    assert extra_turn(dict(text=text)) is expected


def test_text_edits_change_the_cached_answer_and_the_cache_is_bounded():
    _extra_turn_text.cache_clear()
    try:
        card=dict(name='Same name',text='Take an extra turn after this one.')
        assert extra_turn(card)
        card['text']='Skip your next turn.';assert not extra_turn(card)
        card['text']='Take an extra turn after this one.';assert extra_turn(card)
        for n in range(8300):extra_turn(dict(text=f'Unique unrelated rules text {n}.'))
        assert _extra_turn_text.cache_info().currsize<=8192
    finally:_extra_turn_text.cache_clear()
