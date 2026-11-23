import random
import pytest

from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec
from cube_ai.draft import build_deck,stress_test
from cube_ai.draft_strength import bundle_asset,draft_score,report,vintage_prior
from cube_ai.vintage_data import reference


@pytest.fixture(scope='module')
def fixture():
    catalog=Catalog();ref=reference(catalog)
    return catalog,ref,BuildSpec.from_dict(ref['spec'])


def test_prior_is_sourced_and_ranks_power_cards_above_ordinary_spells(fixture):
    catalog,ref,spec=fixture;prior=vintage_prior()
    assert prior['count']==522 and prior['reference_count']==540
    assert prior['source'].startswith('https://cubecobra-public.s3.amazonaws.com/')
    assert draft_score(catalog.cards['Black Lotus'],spec)>draft_score(catalog.cards['Solemn Simulacrum'],spec)
    assert draft_score(catalog.cards['Ancestral Recall'],spec)>draft_score(catalog.cards['Oko, Thief of Crowns'],spec)
    assert report(ref['cards'],spec)['covered']==522
    assert 'cube_ai/data/vintage_pick_prior.json' in bundle_asset()


def test_prior_does_not_change_commander_or_nonvintage_scores(fixture):
    catalog,_,_=fixture;card=catalog.cards['Black Lotus']
    for spec in [BuildSpec(),BuildSpec.from_dict(dict(mode='classic',legality_format='legacy'))]:
        assert draft_score(card,spec)==card['quality']
        assert report([{'name':card['name']}],spec) is None


def test_vintage_deck_includes_relevant_strong_card_from_full_pool(fixture):
    catalog,ref,spec=fixture
    pool=[row['name'] for row in ref['cards'] if catalog.cards[row['name']]['kind']!='land'
          and (catalog.cards[row['name']]['identity']=='C' or set(catalog.cards[row['name']]['identity'])<=set('UW'))]
    assert len(pool)>23 and 'Black Lotus' in pool and 'Ancestral Recall' in pool
    deck=build_deck(catalog,pool,spec,random.Random(18),'UW',readiness_hands=0)
    assert 'Black Lotus' in deck['spells'] and 'Ancestral Recall' in deck['spells']
    assert len(deck['spells'])+len(deck['lands'])+sum(deck['basics'].values())==40


def test_stress_results_explain_pick_prior_scope(fixture):
    catalog,ref,spec=fixture
    result=stress_test(catalog,ref['cards'],spec,trials=5)
    assert result['draft_strength']['covered']==522
    assert '不是实战胜率' in result['draft_strength']['limitation']
