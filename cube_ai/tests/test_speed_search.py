import copy
import json
import threading
import time
from pathlib import Path
import pytest

from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec,GUILDS
from cube_ai.optimize import draft_evaluation,schedule
from cube_ai.sim_cache import DraftWorkspace
from cube_ai.search import CandidateEvaluator,stages
from cube_ai.performance import Timings
from cube_ai import tuning
from cube_ai.forge_worker import worker_key


@pytest.fixture(scope='module')
def fixture():
    c=Catalog();rows,unknown=c.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    return c,rows,BuildSpec()


def replacements(c,rows,number=4):
    present={r['name'] for r in rows};result=[]
    for i,row in enumerate(rows):
        if row['role']!='Main':continue
        old=c.cards[row['name']]
        for n,new in c.cards.items():
            if n not in present and new['identity']==old['identity'] and new['bucket']==old['bucket'] and new['kind']==old['kind'] and (new['mv']>=6)==(old['mv']>=6):
                trial=copy.deepcopy(rows);trial[i]['name']=n
                result.append(dict(index=i,rows=trial,remove=old['name'],add=n))
                if len(result)==number:return result
                break


def semantic(report):return {k:v for k,v in report.items() if k!='execution'}


def test_incremental_matches_fresh_tables_pools_metrics_and_counts(fixture):
    c,rows,spec=fixture;seeds,guilds=schedule(20,88242);workspace=DraftWorkspace(c,spec)
    original=draft_evaluation(c,rows,spec,seeds,guilds,True,workspace=workspace)
    again=draft_evaluation(c,rows,spec,seeds,guilds,True,workspace=workspace)
    assert semantic(original)==semantic(again) and again['execution']['cache_hits']==20
    changed=replacements(c,rows)[0]['rows']
    incremental=draft_evaluation(c,changed,spec,seeds,guilds,True,workspace=workspace)
    fresh=draft_evaluation(c,changed,spec,seeds,guilds,True)
    assert semantic(incremental)==semantic(fresh)
    assert incremental['execution']['cache_misses']>0
    # The full pack layout, including discarded cards, determines affected tables.
    identical=sum(a['packs']==b['packs'] for a,b in zip(original['tables'],fresh['tables']))
    assert incremental['execution']['cache_hits']==identical
    assert semantic(draft_evaluation(c,rows,spec,seeds,guilds,True,workspace=workspace))==semantic(original)


def test_workspace_rejects_changed_policy_and_bounds_memory(fixture):
    c,rows,spec=fixture;workspace=DraftWorkspace(c,spec,limit=3)
    seeds,guilds=schedule(10,42);draft_evaluation(c,rows,spec,seeds,guilds,workspace=workspace)
    assert len(workspace.entries)==3
    other=BuildSpec.from_dict(dict(spec.to_dict(),bracket=2))
    with pytest.raises(ValueError,match='参数'):draft_evaluation(c,rows,other,seeds,guilds,workspace=workspace)


def test_parallel_spawn_has_same_decks_and_metrics_as_serial(fixture):
    c,rows,spec=fixture;seeds,guilds=schedule(10,92242);items=replacements(c,rows,2)
    with CandidateEvaluator(c,spec,seeds,guilds,workers=2) as evaluator:
        parallel=evaluator.batch(items,10)
        assert not evaluator.fallback
        serial=[evaluator.evaluate(item['rows'],10) for item in items]
    assert [semantic(r) for r in parallel]==[semantic(r) for r in serial]


def test_screen_only_promotes_full_development_evaluations(fixture):
    c,rows,spec=fixture;seeds,guilds=schedule(50,95242);items=replacements(c,rows,8)
    with CandidateEvaluator(c,spec,seeds,guilds,workers=1) as evaluator:
        survivors,rejected=evaluator.screen(items,rows)
        assert 2<=len(survivors)<=8 and len(survivors)+len(rejected)==8
        assert evaluator.stats['table_evaluations']<=8*(10+30+50)
        assert all(item['evaluation']['seeds']==seeds for item in survivors)
        assert all(sum(g in prefs for prefs in guilds[:n])==n*3//10 for n in stages(50) for g in GUILDS)


def test_full_mode_does_not_eliminate_on_small_samples(fixture):
    c,rows,spec=fixture;seeds,guilds=schedule(10,42)
    with CandidateEvaluator(c,spec,seeds,guilds,workers=1,adaptive=False) as evaluator:
        survivors,rejected=evaluator.screen(replacements(c,rows,4),rows)
        assert len(survivors)==4 and not rejected


def test_tied_early_candidates_reach_full_evaluation(fixture,monkeypatch):
    c,rows,spec=fixture;seeds,guilds=schedule(50,42);items=replacements(c,rows,8)
    def report(value,count):
        return dict(mean_strength=value,p10_strength=value,guild_gap=0,
            observations=[dict(pod=p,seat=s,strength=value) for p in range(count) for s in range(3)],
            execution=dict(cache_hits=0,cache_misses=count),seeds=seeds[:count])
    with CandidateEvaluator(c,spec,seeds,guilds,workers=1) as evaluator:
        monkeypatch.setattr(evaluator,'evaluate',lambda rows,count:report(.5,count))
        monkeypatch.setattr(evaluator,'batch',lambda batch,count:[report(.6 if count==50 and item['add']==items[-1]['add'] else .5,count) for item in batch])
        survivors,rejected=evaluator.screen(items,rows)
        assert len(survivors)==8 and not rejected
        assert max(item['evaluation']['mean_strength'] for item in survivors)==.6


def test_timings_preserve_overlapping_and_failed_stages(tmp_path):
    clock=Timings(tmp_path/'timings.json')
    def task():
        with clock.span('background'):time.sleep(.01)
    thread=threading.Thread(target=task);thread.start()
    with clock.span('foreground'):time.sleep(.01)
    thread.join()
    with pytest.raises(ValueError):
        with clock.span('failed'):raise ValueError('expected')
    data=json.loads(clock.path.read_text(encoding='utf8'))
    assert {s['stage'] for s in data['stages']}=={'background','foreground','failed'}
    assert data['stages'][-1]['status']=='failed'
    other=Timings(clock.path);other.call('resumed',lambda:None)
    assert len(other.snapshot()['stages'])==4


def test_calibration_rejects_faster_changed_events_and_sparse_measurement():
    baseline=dict(outcome='win',winner='a',events_sha256='same')
    assert tuning.compatible([baseline],[dict(baseline)])
    assert not tuning.compatible([baseline],[dict(baseline,events_sha256='changed')])
    def phase(workers,seconds,**kw):return dict(workers=workers,seconds=seconds,compatible=True,normal_games=6,jvm_profile='default',**kw)
    a=phase(2,[10,10]);b=phase(4,[9.8,9.8]);bad=phase(8,[1,1]);bad['compatible']=False
    assert tuning.choose([a,b,bad]) is a
    assert tuning.choose([phase(4,[1])]) is None
    a['normal_games']=2;assert tuning.choose([a]) is None


def test_calibration_is_invalidated_by_machine_or_engine(tmp_path,monkeypatch):
    monkeypatch.setattr(tuning,'engine_key',lambda c:['forge-a'])
    profile=dict(version=tuning.VERSION,machine=tuning.machine_key(),engine=['forge-a'],adopted=True,workers=3,jvm_profile='bounded_gc')
    tuning.PROFILE.write_text(json.dumps(profile))
    assert tuning.profile_for({})['workers']==3
    assert tuning.apply({})['jvm_options']==tuning.JVM_PROFILES['bounded_gc']['options']
    monkeypatch.setattr(tuning,'engine_key',lambda c:['forge-b'])
    assert tuning.profile_for({}) is None


def test_memory_limited_boundary_does_not_cap_future_free_machine(monkeypatch):
    from cube_ai import forge
    monkeypatch.setattr(forge,'configuration',lambda:{})
    monkeypatch.setattr(tuning,'profile_for',lambda c:dict(workers=1,tested_workers=[1]))
    assert tuning.recommendation(1)==1
    assert tuning.recommendation(4) is None


def test_workers_with_different_java_options_cannot_be_reused():
    config=dict(java='java',jar='forge')
    assert worker_key(config)!=worker_key(dict(config,heap_mib=1536))
    assert worker_key(config)!=worker_key(dict(config,jvm_options=['-XX:ActiveProcessorCount=2']))


def test_calibration_runs_repeats_and_saves_only_validated_profile(fixture,tmp_path,monkeypatch):
    from cube_ai import forge,experiment
    c,rows,spec=fixture;decks=tmp_path/'decks';decks.mkdir()
    for name in ['a','b','c']:(decks/(name+'.dck')).write_text(name)
    monkeypatch.setattr(experiment,'execution_resources',lambda:dict(maximum=1))
    monkeypatch.setattr(forge,'configuration',lambda:dict(backend='resident'))
    monkeypatch.setattr(forge,'card_index',lambda config:{})
    monkeypatch.setattr(tuning,'engine_key',lambda config:['fixed-engine'])
    calls=[]
    def battle(config,folder,order,seed,clock,out,log):
        assert config['cache'] is False
        calls.append(seed);(out/log).write_text('Turn: Turn 1\nGame Outcome: Ai(1)-a has won!\n')
        return dict(outcome='win',winner=order[0],log=log)
    monkeypatch.setattr(forge,'run_battle',battle)
    result=tuning.calibrate(c,rows,spec,worker_choices=[1],jvm_choices=['default'],fixtures=(decks,[dict(order=['a','b','c'],seed=n) for n in range(6)]))
    assert len(calls)==12 and result['adopted'] and tuning.profile_for({})['workers']==1
    assert not any((tmp_path/'matches').glob('*'))


def test_calibration_http_job_reaches_native_tuner(monkeypatch):
    from cube_ai.server import Application
    app=Application();done=threading.Event();captured={}
    def calibrate(catalog,rows,spec,progress,mode):
        captured['mode']=mode;done.set();return dict(adopted=False)
    monkeypatch.setattr(tuning,'calibrate',calibrate)
    try:
        job=app.submit(dict(operation='calibrate',mode='full',cards=[dict(name='Sun Titan',role='Main')]))
        assert done.wait(5) and captured['mode']=='full'
    finally:app.executor.shutdown(wait=True)
