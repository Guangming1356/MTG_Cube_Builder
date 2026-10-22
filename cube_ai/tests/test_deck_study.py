import copy
import json
from pathlib import Path
import random
from types import SimpleNamespace

import pytest

from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec
from cube_ai.deck_building import revise
from cube_ai.deck_study import summarize,compare
from cube_ai.draft import draft_pod


@pytest.fixture(scope='module')
def fixture():
    catalog=Catalog();rows,unknown=catalog.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    return catalog,rows


@pytest.mark.parametrize('bracket',[None,1,3,5])
def test_spell_selection_preserves_pool_commander_lands_and_valid_deck_size(fixture,bracket):
    catalog,rows=fixture;spec=BuildSpec.from_dict({'bracket':bracket})
    for seed in [1937,12451,31754]:
        pod=draft_pod(catalog,rows,spec,random.Random(seed),['UW','BR','GU'],readiness_hands=0)
        before=copy.deepcopy(pod)
        for deck in pod['decks']:
            after=revise(catalog,deck,spec)
            for key in ['commander','identity','lands','land_count','drafted']:assert after[key]==deck[key]
            assert len(after['spells'])==len(deck['spells'])
            assert set(after['spells'])<=set(deck['drafted'])
            assert len(after['spells'])+len(after['lands'])+sum(after['basics'].values())+1==60
            assert len(after['research_changes'])<=6
            assert not after['bracket'] or not after['bracket']['violations']
            for package,previous in deck['design']['packages'].items():
                if not previous['missing']:assert not after['design']['packages'][package]['missing']
        assert pod==before


def activity(rate):return dict(no_action_cycle_rate=rate,no_spell_cycle_rate=rate,no_spell_first4_rate=rate,finisher_presence=.5,own_turns=8,complete_first4_coverage=1)


def test_protected_policy_keeps_every_selected_finisher_and_can_still_change_spells(fixture):
    catalog,rows=fixture;spec=BuildSpec();changes=0
    for seed in [1937,12451,31754]:
        pod=draft_pod(catalog,rows,spec,random.Random(seed),['UW','BR','GU'],readiness_hands=0)
        for deck in pod['decks']:
            after=revise(catalog,deck,spec,'protected')
            finishers={n for n in deck['spells'] if catalog.cards[n]['finisher']}
            assert finishers<=set(after['spells'])
            assert after['commander']==deck['commander'] and after['drafted']==deck['drafted']
            assert after['lands']==deck['lands'] and after['land_count']==deck['land_count']
            changes+=len(after['research_changes'])
    assert changes>0


def test_analysis_keeps_failed_attempts_and_excludes_entire_incomplete_paired_table():
    records=[dict(pod=pod,policy=policy,game=game,outcome='win',activity=activity(.6 if policy=='quality' else .4))
             for pod in range(20) for policy in ['quality','balanced'] for game in range(3)]
    records[3].update(outcome='engine_error');records[3].pop('activity')
    summary=summarize(records,20)
    assert summary['paired_complete_pods']==19
    assert summary['policies']['balanced']['outcomes']['engine_error']==1
    assert summary['policies']['balanced']['normal']==59
    assert summary['supports_activity_improvement'] and not summary['changes_default_policy']
    assert summary['no_action_cluster_interval95'][1]<0
    for record in records:
        if record['policy']=='balanced' and record['game']==0:record.update(outcome='engine_error')
    assert not summarize(records,20)['gates']['normal_completion']
    assert not summarize(records,20)['supports_activity_improvement']


def test_missing_first_four_turn_windows_are_not_fabricated_as_zero_spell_rates():
    records=[dict(pod=pod,policy=policy,game=game,outcome='win',
                  activity=dict(activity(.5),no_action_cycle_rate=None,complete_first4_coverage=0))
             for pod in range(20) for policy in ['quality','balanced'] for game in range(3)]
    summary=summarize(records,20)
    assert summary['no_action_difference'] is None and summary['analyzed_pods']==0
    assert not summary['supports_activity_improvement']


def test_cycle_activity_includes_offturn_interaction_but_not_triggers_or_partial_cycles():
    from cube_ai.optimize import game_trace
    catalog=SimpleNamespace(cards={'Ponder':dict(finisher=False,interaction=False)})
    decks=[dict(id=player,spells=['Ponder'],commander='Ponder') for player in ['a','b']]
    lines=[
        'Add To Stack: Ai(1)-a cast Ponder',  # Before a's first turn: no fabricated cycle.
        'Turn: Turn 1 (Ai(1)-a)',
        'Turn: Turn 2 (Ai(2)-b)',
        'Add To Stack: Ai(1)-a cast Ponder',  # a's offturn interaction belongs to cycle 1.
        'Turn: Turn 3 (Ai(1)-a)',
        'Add To Stack: Ai(1)-a triggered Ponder',
        'Turn: Turn 4 (Ai(1)-a)',
        'Add To Stack: Ai(1)-a activated Ponder',
        'Turn: Turn 5 (Ai(1)-a)',
        'Combat: Ai(1)-a assigned Ponder (1) to attack Ai(2)-b.',
        'Turn: Turn 6 (Ai(1)-a)',
        'Add To Stack: Ai(2)-b cast Ponder',
    ]
    log='\n'.join(lines)
    old=game_trace(catalog,log,decks);extended=game_trace(catalog,log,decks,extended=True)
    for name,p in old['players'].items():
        for key,value in p.items():assert extended['players'][name][key]==value
    a=extended['players']['a'];b=extended['players']['b']
    assert a['complete_early_cycles']==4 and a['no_spell_first4_rate']==1
    assert a['cycle_spells']==[1,0,0,0,0] and a['early_offturn_casts']==1
    assert a['no_spell_cycle_rate']==.75 and a['no_action_cycle_rate']==.25
    assert b['complete_early_cycles']==0 and b['no_action_cycle_rate'] is None


@pytest.mark.parametrize('variant',['balanced','protected'])
def test_controlled_pipeline_preserves_both_policies_and_writes_replayable_evidence(fixture,tmp_path,monkeypatch,variant):
    from cube_ai import deck_study,tuning
    catalog,rows=fixture;before=copy.deepcopy(rows)
    monkeypatch.setattr(deck_study,'STUDIES',tmp_path/'studies')
    monkeypatch.setattr(deck_study,'configuration',lambda:dict(version='test-fixture',backend='resident'))
    monkeypatch.setattr(tuning,'apply',lambda config:config)
    monkeypatch.setattr(tuning,'engine_key',lambda config:['test-fixture'])
    monkeypatch.setattr(deck_study,'campaign_resources',lambda workers:dict(workers=1,ceiling=1,dynamic=False))
    monkeypatch.setattr(deck_study,'card_index',lambda config:{name.casefold():name for name in catalog.cards})
    calls=[]
    def battle(config,folder,order,seed,clock,out,log):
        assert config['cache'] is False
        calls.append((tuple(order),seed));lines=[]
        for turn in range(4):
            for player in order:
                lines.append(f'Turn: Turn {turn*3+1} (Ai(1)-{player})')
                lines.append(f'Add To Stack: Ai(1)-{player} cast Ponder')
        (out/log).write_text('\n'.join(lines),encoding='utf8')
        return dict(outcome='win',winner=order[0],log=log,turns=12,cache_hit=False)
    monkeypatch.setattr(deck_study,'run_battle',battle)
    result=compare(catalog,rows,BuildSpec(),pods=2,workers=1,clock_seconds=30,seed=1937,variant=variant)
    assert result['policy']['name']==variant and result['policy']['preserve_finishers']==(variant=='protected')
    assert rows==before and len(calls)==12 and result['training_samples_added']==0
    assert result['summary']['paired_complete_pods']==2 and not result['summary']['supports_activity_improvement']
    for pod in range(2):
        own=[call for call in calls if call[0][0].startswith(f'p{pod:03d}_')]
        assert sorted(seed for _,seed in own)==sorted([1937+pod*100+game for game in range(3)]*2)
    out=deck_study.STUDIES/result['study_id']
    assert (out/'evidence.zip').is_file() and (out/'report.md').is_file()
    assert json.loads((out/'summary.json').read_text(encoding='utf8'))['state']=='done'
    saved=json.loads((out/'report.json').read_text(encoding='utf8'))
    assert saved['state']=='done' and saved['source_snapshot']['stored_before_games']
    assert len(list((out/'tables').glob('*.json')))==2
    assert json.loads((out/'games.json').read_text(encoding='utf8'))==saved['games']
    assert (out/'source/forge.py').is_file() and (out/'source/catalog.json').is_file()


def test_http_operation_forwards_the_explicit_research_variant(monkeypatch):
    import threading
    from cube_ai import deck_study
    from cube_ai.server import Application
    completed=threading.Event();captured={}
    def fake(catalog,rows,spec,**options):
        captured.update(options);completed.set();return dict(training_samples_added=0)
    monkeypatch.setattr(deck_study,'compare',fake)
    app=Application()
    try:
        app.submit(dict(operation='deck-study',cards=[dict(name='Sun Titan',role='Main')],deck_variant='protected',study_seed=93000000))
        assert completed.wait(5) and captured['variant']=='protected' and captured['seed']==93000000
    finally:app.shutdown()
