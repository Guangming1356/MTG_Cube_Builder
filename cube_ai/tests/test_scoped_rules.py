"""Request-scoped preparation must preserve independent rule checks."""
from datetime import date,timedelta

import pytest

from cube_ai.brackets import profile,score_adjustment
from cube_ai.catalog import Catalog,exclusion_reasons
from cube_ai.config import BuildSpec
from cube_ai.design import applicable_themes,design_bonus


@pytest.mark.parametrize('bracket',[None,1,3,5])
def test_prepared_power_keeps_all_exclusions_and_role_scores(bracket):
    catalog=Catalog();spec=BuildSpec.from_dict(dict(bracket=bracket,exclude=['  mind stone ']))
    power=profile(spec)
    cards=[catalog.cards[n] for n in ['Mind Stone','Warping Wail','Time Warp','Chrome Mox']]
    cards.append(dict(catalog.cards['Mind Stone'],legalities=dict(catalog.cards['Mind Stone']['legalities'],commander='banned')))
    cards.append(dict(catalog.cards['Mind Stone'],name='Unverified future card',
                      oracle_id='11111111-1111-1111-1111-111111111111',released=(date.today()+timedelta(days=365)).isoformat()))
    for card in cards:
        assert exclusion_reasons(card,spec,power=power)==exclusion_reasons(card,spec)
        for role in ['Main','Commander']:
            assert score_adjustment(card,spec,role,power=power)==score_adjustment(card,spec,role)
    assert any('无色法术力' in r for r in exclusion_reasons(cards[1],spec,power=power))
    assert '用户排除' in exclusion_reasons(cards[0],spec,power=power)
    assert '该赛制不合法/受限' in exclusion_reasons(cards[-2],spec,power=power)
    assert any('纸质印张' in r for r in exclusion_reasons(cards[-1],spec,power=power))


def test_prepared_power_does_not_cache_mutable_colorless_preferences():
    card=Catalog().cards['Warping Wail'];spec=BuildSpec.from_dict(dict(bracket=3));power=profile(spec)
    assert any('无色法术力' in r for r in exclusion_reasons(card,spec,power=power))
    spec.allow_colorless_costs=True
    assert not any('无色法术力' in r for r in exclusion_reasons(card,spec,power=power))
    spec.allow_colorless_costs=False
    assert any('无色法术力' in r for r in exclusion_reasons(card,spec,power=power))


def test_empty_prepared_themes_are_distinct_from_unspecified_themes():
    card=dict(name='Independent theme test',identity='C',quality=3.0,creature=True,
              enablers=['sacrifice','tokens','artifacts'],payoffs=[])
    spec=BuildSpec()
    assert design_bonus(card,spec)==.04
    assert design_bonus(card,spec,available=set())==0


def test_theme_preparation_stays_with_its_spec_and_does_not_share_sets():
    first=BuildSpec(pair_themes={'UW':['blink','artifacts']})
    second=BuildSpec(pair_themes={'UW':['control']})
    themes=applicable_themes('U',first)
    assert themes=={'blink','artifacts'}
    assert applicable_themes('U',second)=={'control'}
    themes.add('sacrifice')
    assert applicable_themes('U',first)=={'blink','artifacts'}
    first.pair_themes={'UW':[]}
    assert applicable_themes('U',first)==set()
    assert applicable_themes('C',second)=={'control'}
    assert applicable_themes('B',second)==set()
