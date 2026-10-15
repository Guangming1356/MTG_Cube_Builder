import json
from pathlib import Path
from unittest.mock import patch
import pytest
from cube_ai.catalog import Catalog
from cube_ai.config import ROOT,GUILDS,BuildSpec
from cube_ai.engine import audit
from cube_ai.optimize import schedule,game_trace,evidence_from_match,feedback_model,paired_structural,paired_behavior,opponent_gift,unsupported_cost,CORE_GUARD

@pytest.fixture(scope='module')
def cards():return Catalog()

def test_balanced_and_disjoint_grouped_schedules():
    seeds,guilds=schedule(10,1042)
    assert all(sum(g in p for p in guilds)==3 for g in GUILDS)
    assert set(seeds).isdisjoint(schedule(4,100042)[0])
    assert set(schedule(100,2042)[0]).isdisjoint(schedule(100,200042)[0])

def test_midword_wrapping_and_own_turn_instant(cards):
    decks=[dict(id='a',spells=['Swords to Plowshares'],commander='Sun Titan'),dict(id='b',spells=['Counterspell'],commander='Talrand, Sky Summoner')]
    log='Turn: Turn 1 (Ai(1)-a)\n\nAdd To Stack: Ai(1)-a cast Swords to Plow\nshares targeting Sun Titan (19)\n\nAdd To Stack: Ai(2)-b cast Counterspell targeting Swords to Plowshares\n\nTurn: Turn 2 (Ai(2)-b)\n\n'
    p=game_trace(cards,log,decks)['players']
    assert p['a']['casts']=={'Swords to Plowshares':1}
    assert p['a']['early_spell_turns']==1
    assert p['b']['casts']=={'Counterspell':1}
    assert p['b']['early_spell_turns']==0 # Off-turn interaction is not a missed own-turn spell.

def test_failed_game_not_used_as_positive_card_training(cards,tmp_path):
    (tmp_path/'bad.log').write_text('Game Result: fake winner')
    result=dict(path=str(tmp_path),match_id='test',tables=[],games=[dict(outcome='engine_error',log='bad.log')],
        summary=dict(completed=0,games=1,guilds={}),skipped_pods=0)
    e=evidence_from_match(cards,result)
    assert not e['cards'] and not e['traces']
    assert e['summary']['failure_rate']==1

def test_sparse_win_pressure_shrunk_and_no_labels(cards):
    e=dict(summary=dict(mean_early_no_spell_rate=.4,no_finisher_cast_rate=.2),guilds={'BR':dict(appearances=3,wins=3)})
    d=dict(observations=[])
    m=feedback_model(cards,e,d)
    assert .85<=m['guilds']['BR']['pressure']<1
    assert m['guilds']['BU']['pressure']==1
    assert m['low_weight']==pytest.approx(.29)

def test_bootstrap_resamples_pods_not_players():
    groups={g:dict(mean_strength=.5) for g in GUILDS}
    a=dict(observations=[dict(pod=p,seat=s,strength=.5) for p in range(2) for s in range(3)],mean_strength=.5,p10_strength=.5,guild_gap=0,guilds=groups)
    b=dict(a,observations=[dict(x,strength=x['strength']+(.1 if x['pod']==0 else -.1)) for x in a['observations']])
    r=paired_structural(a,b)
    assert abs(r['mean_difference'])<1e-8
    assert r['better']==r['worse']==3
    assert r['pod_bootstrap95']==pytest.approx([-.1,.1])

def test_behavior_uses_jointly_valid_games_only():
    p=dict(no_spell_first4_rate=.5,finisher_casts=1,interaction_casts=2,spellcasts=3)
    a=dict(traces=[dict(pod=0,game=0,players={'p000_s1_BU':p})])
    b=dict(traces=[dict(pod=0,game=0,players={'p000_s1_UB':dict(p,no_spell_first4_rate=.25)}),
        dict(pod=0,game=1,players={'p000_s1_BU':dict(p,no_spell_first4_rate=1)})])
    r=paired_behavior(a,b)
    assert r['paired_games']==r['paired_player_observations']==1
    assert r['metrics']['no_spell_first4_rate']==dict(before=.5,after=.25)

@pytest.mark.parametrize('name',['Hunted Lammasu','Argothian Wurm','Boldwyr Heavyweights'])
def test_opponent_gift_not_mistaken_for_free_standalone_body(cards,name):
    assert opponent_gift(cards.cards[name])

def test_semantic_guards(cards):
    assert unsupported_cost(cards.cards['Pale Rider of Trostad'])
    assert unsupported_cost(cards.cards['Squad Commander'])
    assert 'Brainstorm' in CORE_GUARD and 'Deadly Rollick' in CORE_GUARD

def test_current_frozen_candidate_conserves_hard_constraints(cards):
    folder=ROOT/'optimizations/forge_feedback_v1'
    if not (folder/'candidate.json').exists():pytest.skip('local evidence not shipped')
    b=json.loads((folder/'base_cube.json').read_text(encoding='utf-8'))
    n=json.loads((folder/'candidate.json').read_text(encoding='utf-8'))
    assert len(n['cards'])==len({r['name'] for r in n['cards']})==600
    assert audit(cards,n['cards'],BuildSpec.from_dict(n['spec']),strict=True)['hard_errors']==0
    for a,z in zip(b['cards'],n['cards']):
        old,new=cards.cards[a['name']],cards.cards[z['name']]
        assert old['identity']==new['identity'] and old['bucket']==new['bucket']
        assert old['creature']==new['creature']
        assert (old['mv']>=6)==(new['mv']>=6)
