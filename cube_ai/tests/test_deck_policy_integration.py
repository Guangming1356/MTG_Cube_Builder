"""The selected policy must reach normal drafts, caches and exported decks."""
from dataclasses import replace
import json
from pathlib import Path
import random
from unittest.mock import patch

import pytest

from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec
from cube_ai.deck_building import revise
from cube_ai.draft import draft_pod,opening_test,stress_test


@pytest.fixture(scope='module')
def fixture():
    catalog=Catalog()
    rows,unknown=catalog.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    return catalog,rows


def test_old_recipes_remain_quality_first_and_explicit_policy_roundtrips():
    assert BuildSpec.from_dict().deck_policy=='quality'
    assert BuildSpec.from_dict({'mode':'classic'}).deck_policy=='quality'
    spec=BuildSpec.from_dict({'bracket':3,'deck_policy':'balanced'})
    assert BuildSpec.from_dict(json.loads(json.dumps(spec.to_dict())))==spec
    from cube_ai.llm import plan_schema
    assert plan_schema()['properties']['deck_policy']['enum']==['quality','balanced']
    for value in [None,[],{},3,'tempo']:
        with pytest.raises(ValueError,match='deck_policy'):BuildSpec.from_dict({'deck_policy':value})


@pytest.mark.parametrize('hands',[0,40])
@pytest.mark.parametrize('bracket',[None,3])
def test_balanced_normal_draft_matches_tested_policy_and_preserves_rng(fixture,hands,bracket):
    catalog,rows=fixture;spec=BuildSpec.from_dict({'bracket':bracket});changes=0
    for seed in [1937,12451,31754]:
        q_rng=random.Random(seed);b_rng=random.Random(seed)
        quality=draft_pod(catalog,rows,spec,q_rng,['UW','BR','GU'],readiness_hands=hands)
        with patch('cube_ai.draft.opening_test',wraps=opening_test) as readiness:
            balanced=draft_pod(catalog,rows,replace(spec,deck_policy='balanced'),b_rng,['UW','BR','GU'],readiness_hands=hands)
        assert readiness.call_count==3  # No duplicate opening-hand evaluation.
        assert b_rng.getstate()==q_rng.getstate() and balanced['packs']==quality['packs']
        assert balanced['deck_policy']=='balanced'
        for before,after in zip(quality['decks'],balanced['decks']):
            direct=revise(catalog,before,spec)
            for key in ['spells','basics','design','bracket','deck_policy_changes']:
                assert after[key]==direct[key]
            for key in ['commander','identity','lands','land_count','drafted','spell_count']:
                assert before[key]==after[key]
            assert len(after['spells'])+len(after['lands'])+sum(after['basics'].values())+1==60
            assert 'research_changes' not in after
            changes+=len(after['deck_policy_changes'])
    assert changes>0


def test_cache_isolates_policy_and_forge_exports_the_selected_cards(fixture,tmp_path):
    from cube_ai import sim_cache
    from cube_ai.forge import write_deck,BASICS
    from collections import Counter
    catalog,rows=fixture;spec=BuildSpec(deck_policy='balanced')
    quality,hit=sim_cache.draft(catalog,rows,replace(spec,deck_policy='quality'),1937,['UW','BR','GU'])
    assert not hit
    balanced,hit=sim_cache.draft(catalog,rows,spec,1937,['UW','BR','GU'])
    assert not hit
    reused,hit=sim_cache.draft(catalog,rows,spec,1937,['UW','BR','GU'])
    assert hit and reused==balanced and balanced['packs']==quality['packs']
    index={n.casefold():n for n in catalog.cards};index.update({n.casefold():n for n in BASICS.values()})
    for deck in balanced['decks']:
        path=tmp_path/f"deck{deck['seat']}.dck";metadata=write_deck(deck,path,index,catalog,spec)
        assert metadata['deck_policy']=='balanced' and metadata['total']==60
        lines=path.read_text(encoding='utf8').split('[Main]\n')[1].splitlines()
        exported=Counter({line.split(' ',1)[1]:int(line.split(' ',1)[0]) for line in lines})
        expected=Counter(deck['spells']+deck['lands'])
        expected.update({BASICS[c]:n for c,n in deck['basics'].items()})
        assert exported==expected


def test_stress_report_records_the_actual_policy(fixture):
    catalog,rows=fixture;report=stress_test(catalog,rows,BuildSpec(deck_policy='balanced'),trials=5)
    assert report['deck_policy']=='balanced'
    assert all(d['deck_policy']=='balanced' for d in report['examples'])


def test_classic_policy_keeps_40_cards_and_the_same_draft(fixture):
    catalog,rows=fixture;spec=BuildSpec.from_dict({'mode':'classic'})
    quality=draft_pod(catalog,rows,spec,random.Random(1937),readiness_hands=0)
    balanced=draft_pod(catalog,rows,replace(spec,deck_policy='balanced'),random.Random(1937),readiness_hands=0)
    assert quality['packs']==balanced['packs'] and len(balanced['decks'])==8
    for old,deck in zip(quality['decks'],balanced['decks']):
        assert old['drafted']==deck['drafted'] and old['lands']==deck['lands']
        assert deck['commander'] is None and deck['deck_policy']=='balanced'
        assert len(deck['spells'])+len(deck['lands'])+sum(deck['basics'].values())==40
