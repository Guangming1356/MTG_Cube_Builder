"""Additional costs affect the estimate without changing printed mana value."""
import random
from types import SimpleNamespace
import pytest
from cube_ai.casting_costs import extract,curve_value,mana_cost
from cube_ai.draft import opening_test


@pytest.mark.parametrize('text,expected',[
    ('As an additional cost to cast this spell, waterbend {5}.',7),
    ('As an additional cost to cast this spell, sacrifice a creature or pay {3}.',5),
    ('As an additional cost to cast this spell, pay {3} or sacrifice a creature.',5),
    ('As an additional cost to cast this spell, waterbend {X}.',3),
])
def test_recognized_mana_only_cost(text,expected):
    result=extract(text,'{U}{U}',2)
    assert result['cast_mv']==expected and mana_cost(result).startswith('{U}{U}')


@pytest.mark.parametrize('text',[
    'As an additional cost to cast this spell, you may waterbend {5}.',
    'As an additional cost to cast this spell, sacrifice a creature.',
    'As an additional cost to cast another spell, pay {5}.',
])
def test_optional_or_other_requirements_are_not_invented_as_mana(text):
    assert extract(text,'{U}{U}',2)=={}


def test_absent_printed_cost_remains_unpayable():
    assert extract('As an additional cost to cast this spell, pay {3}.','',0)=={}


def test_river_spirit_keeps_printed_value_and_is_not_a_two_mana_action():
    from cube_ai.catalog import Catalog
    catalog=Catalog();card=catalog.cards['Benevolent River Spirit']
    assert card['mv']==2 and card['mana_cost']=='{U}{U}'
    assert curve_value(card)==7 and card['bucket']=='5+' and mana_cost(card)=='{U}{U}{5}'
    class Fixed:
        def sample(self,deck,count):return deck
    result=opening_test(catalog,[card['name']]*7,[],'U',11,Fixed(),hands=1)
    assert not any(result['ready_by_turn'].values())


def test_multiple_exact_requirements_add_without_changing_printed_cost():
    result=extract("As an additional cost to cast this spell, pay {2}.\nAs an additional cost to cast this spell, waterbend {3}.","{U}{U}",2)
    assert result['cast_mv']==7 and result['cast_mana_cost']=="{U}{U}{2}{3}"
    assert len(result['casting_requirements'])==2


def test_reverse_face_additional_cost_does_not_apply_to_front():
    from cube_ai.features import extract as features
    raw=dict(name='Front // Back',type_line='Creature // Creature',layout='modal_dfc',cmc=2,card_faces=[dict(name='Front',type_line='Creature',mana_cost='{1}{U}',oracle_text='Flying',power='2',toughness='2'),dict(name='Back',type_line='Creature',mana_cost='{5}{U}',oracle_text='As an additional cost to cast this spell, pay {3}.',power='5',toughness='5')])
    assert 'cast_mv' not in features(raw,set())


def test_card_and_audit_explain_estimate():
    from cube_ai.catalog import Catalog
    from cube_ai.engine import audit
    from cube_ai.config import BuildSpec
    from cube_ai.casting_costs import messages
    catalog=Catalog();card=catalog.cards['Benevolent River Spirit']
    result=audit(catalog,[dict(name=card['name'],role='Main')],BuildSpec())
    assert result['casting_costs'][0]['printed_mv']==2
    assert result['casting_costs'][0]['estimated_cast_mv']==7
    assert '协助' in messages(card)[0]
