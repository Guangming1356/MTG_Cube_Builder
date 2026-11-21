"""Pin the MIT-licensed upstream metric and its conservative offline adapter."""
from pathlib import Path
import pytest

from cube_ai.catalog import Catalog
from cube_ai.external_deck_evaluator import evaluate,COMMIT
from cube_ai.mtg_draft_metrics import removal_quality
from cube_ai.surrogate import deck_vector,DECK_FEATURES


def test_upstream_removal_weights_and_offline_unclassified_interaction():
    catalog=Catalog()
    names=["Assassin's Trophy",'Swords to Plowshares','Lightning Bolt','Counterspell']
    report=evaluate([catalog.cards[n] for n in names])
    values={row['name']:row['value'] for row in report['entries']}
    assert values["Assassin's Trophy"]==pytest.approx(.9)
    assert values['Swords to Plowshares']==pytest.approx(.7)
    assert values['Lightning Bolt']==pytest.approx(.48)
    assert report['classified']==3 and report['interactions']==4
    assert report['unclassified']==['Counterspell'] and len(COMMIT)==40


def test_upstream_metric_is_used_and_recorded_in_training_features():
    catalog=Catalog()
    deck=dict(spells=["Assassin's Trophy",'Counterspell'],commander='Sun Titan',land_count=24)
    vector=deck_vector(catalog,deck)
    assert len(vector)==DECK_FEATURES==20
    assert vector[-2]==pytest.approx(.09) and vector[-1]==pytest.approx(.1)
    from cube_ai.design import deck_design_report
    report=deck_design_report(catalog,deck)['external_evaluation']
    assert report['classified']==1 and report['removal_power']==pytest.approx(.9)


def test_vendored_license_and_upstream_function_available():
    license_text=(Path(__file__).parents[1]/'data/mtg_draft_LICENSE.txt').read_text(encoding='utf8')
    assert 'MIT License' in license_text and 'albertngo1' in license_text
    value,_=removal_quality({'types':['Instant'],'keywords':[],'cmc':2},
                            {'removal-permanent','removal-destroy'})
    assert value==pytest.approx(.9)
