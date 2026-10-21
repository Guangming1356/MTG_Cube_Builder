import copy
import json
import random
import threading
import time
import zipfile
from pathlib import Path

import pytest

from cube_ai import forge, brackets, optimize
from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec, GUILDS
from cube_ai.draft import draft_pod
from cube_ai.experiment import experiment_budget, execution_resources


def test_resource_budget_reserves_memory_and_rejects_overcommit(monkeypatch):
    import cube_ai.experiment as e
    monkeypatch.setattr(e.os, 'cpu_count', lambda: 24)
    monkeypatch.setattr(e, 'configured_heap_mib', lambda: 2048)
    monkeypatch.setattr(e, 'memory_available', lambda: 32 * 2**30)
    assert execution_resources()['workers'] == 4
    assert execution_resources(8)['workers'] == 8
    monkeypatch.setattr(e, 'memory_available', lambda: 6 * 2**30)
    assert execution_resources()['workers'] == 1
    with pytest.raises(ValueError, match='空闲资源'): execution_resources(2)


def test_manual_resources_use_the_same_verified_heap_as_the_actual_queue(monkeypatch):
    import cube_ai.experiment as e
    monkeypatch.setattr(e.os,'cpu_count',lambda:24)
    monkeypatch.setattr(e,'memory_available',lambda:12*2**30)
    monkeypatch.setattr(forge,'configuration',lambda:dict(heap_mib=2048))
    assert execution_resources()['maximum']==3
    with pytest.raises(ValueError,match='空闲资源'):execution_resources(4)
    monkeypatch.setattr(forge,'configuration',lambda:dict(heap_mib=1536))
    resources=execution_resources(4)
    assert resources['workers']==resources['maximum']==4 and resources['heap_mib_per_game']==1536
    assert resources['ceiling']==4 # Preserve the user's cap.
    monkeypatch.setattr(e,'memory_available',lambda:None)
    assert execution_resources()['maximum']==1
    def unavailable():raise ValueError('No runtime installed')
    monkeypatch.setattr(forge,'configuration',unavailable)
    assert e.configured_heap_mib()==2048


@pytest.mark.parametrize('workers', [True, -1, 9, 2.5, '3'])
def test_invalid_worker_count(workers):
    with pytest.raises(ValueError): execution_resources(workers)


def test_budgets_count_tables_games_and_swap_caps():
    quick, standard, deep = [experiment_budget(p) for p in ('quick', 'standard', 'deep')]
    assert [b['training_pods'] for b in (quick, standard, deep)] == [10, 30, 100]
    assert [b['native_games_before_cross'] for b in (quick, standard, deep)] == [90, 270, 900]
    assert [b['max_swaps'] for b in (quick, standard, deep)] == [10, 24, 48]
    assert experiment_budget('deep', cube_size=360)['max_swaps'] == 36
    assert experiment_budget(max_swaps=60)['max_swaps'] == 60
    for kw in [dict(max_swaps=61), dict(max_swaps=True), dict(training_pods=11), dict(profile='unknown')]:
        with pytest.raises(ValueError): experiment_budget(**kw)


def test_large_protocol_schedules_are_disjoint_and_balanced():
    schedules=[optimize.schedule(n,42+offset) for n,offset in [(100,1000),(500,1000000),(100,2000000),(1000,3000000)]]
    for i,(seeds,guilds) in enumerate(schedules):
        assert len(set(seeds))==len(seeds)
        assert len({sum(g in p for p in guilds) for g in GUILDS})==1
        for previous,_ in schedules[:i]:assert set(seeds).isdisjoint(previous)


def test_pipeline_starts_games_before_next_draft_and_bounds_queue(tmp_path,monkeypatch):
    catalog=Catalog()
    rows,unknown=catalog.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    pod=draft_pod(catalog,rows,BuildSpec(),random.Random(42))
    started=threading.Event();active=0;peak=0;guard=threading.Lock();drafts=0
    def drafting(*a,**kw):
        nonlocal drafts
        drafts+=1
        if drafts==2:assert started.wait(2), 'All drafts were produced before games started'
        return copy.deepcopy(pod)
    def battle(config,deck_dir,order,seed,clock,out,log):
        nonlocal active,peak
        with guard:active+=1;peak=max(peak,active)
        started.set();time.sleep(.01)
        (out/log).write_text('mock engine result')
        with guard:active-=1
        return dict(outcome='win',winner=order[0],order=order,seed=seed,log=log,turns=20,wall_seconds=.01)
    monkeypatch.setattr(forge,'MATCHES',tmp_path)
    monkeypatch.setattr(forge,'configuration',lambda:dict(home=str(tmp_path),jar=str(tmp_path/'forge.jar'),java='unused',version='test'))
    monkeypatch.setattr(forge,'engine_description',lambda config:dict(version='test',fingerprint=['fixture']))
    (tmp_path/'forge.jar').write_bytes(b'test')
    monkeypatch.setattr(forge,'card_index',lambda c:{n.casefold():n for n in catalog.cards})
    monkeypatch.setattr(forge,'audit',lambda *a,**kw:dict(hard_errors=0))
    monkeypatch.setattr(forge,'write_deck',lambda *a,**kw:dict(total=60))
    monkeypatch.setattr(forge,'draft_pod',drafting)
    monkeypatch.setattr(forge,'run_battle',battle)
    monkeypatch.setattr(forge,'execution_resources',lambda w:dict(workers=2))
    monkeypatch.setattr(brackets,'cube_report',lambda *a:None)
    result=forge.simulate(catalog,rows,BuildSpec(),3,9,30,workers=2)
    assert result['summary']['completed']==27
    assert result['summary']['completed_draft_pods']==3
    assert peak==2 and result['execution']['peak_pending']<=4
    assert [(r['pod'],r['game']) for r in result['games']]==[(p,g) for p in range(3) for g in range(9)]


def test_evidence_excludes_engine_directories_and_linked_assets(tmp_path):
    (tmp_path/'engine/res').mkdir(parents=True)
    (tmp_path/'engine/res/secret.txt').write_text('not evidence')
    (tmp_path/'report.json').write_text('{}')
    (tmp_path/'evidence.zip').touch()
    assert [p.name for p in forge.evidence_files(tmp_path)]==['report.json']


def cross_result(pods=2):
    fixtures=[dict(fixture=p*3+s,pod=p) for p in range(pods) for s in range(3)]
    return dict(fixtures=fixtures,games=[dict(fixture=f['fixture'],outcome='win',winner='f_new') for f in fixtures for _ in range(3)])


def test_cross_interval_clusters_repeated_fixtures_and_excludes_timeouts():
    result=cross_result()
    result['games'].append(dict(fixture=0,outcome='engine_timeout',winner='f_old'))
    stats=optimize.cross_uncertainty(result)
    assert stats['independent_pods']==2 # not 18 games or 6 fixtures
    assert stats['mean_new_minus_old']==1
    assert stats['pod_bootstrap95']==[1,1]
    result['games']=[]
    assert optimize.cross_uncertainty(result)['pod_bootstrap95'] is None


def test_quick_or_missing_guilds_never_pass_sample_gate():
    def evidence(n):return dict(summary=dict(completed_draft_pods=n,independent_pods_by_guild={g:n*3//10 for g in GUILDS},completed=n*3,attempted=n*3))
    quick=evidence(10);standard=evidence(30);cross=cross_result(30)
    assert not optimize.sampling_report(dict(holdout_seeds=list(range(10))),quick,quick,cross)['adequate']
    assert optimize.sampling_report(dict(holdout_seeds=list(range(30))),standard,standard,cross)['adequate']
    standard['summary']['independent_pods_by_guild']['GU']=0
    assert not optimize.sampling_report(dict(holdout_seeds=list(range(30))),standard,standard,cross)['adequate']


def test_failed_training_or_many_engine_failures_prevent_adoption():
    e=dict(summary=dict(completed_draft_pods=30,independent_pods_by_guild={g:9 for g in GUILDS},completed=90,attempted=90))
    protocol=dict(holdout_seeds=list(range(30)),train_seeds=list(range(30)))
    failed=copy.deepcopy(e);failed['summary']['completed']=3
    assert not optimize.sampling_report(protocol,e,e,cross_result(30),failed)['adequate']
    assert not optimize.sampling_report(protocol,failed,e,cross_result(30),e)['adequate']


def test_http_task_settings_reach_optimizer(monkeypatch):
    from cube_ai.server import Application
    import cube_ai.server as server
    app=Application();completed=threading.Event();captured={}
    def optimizer(catalog,rows,spec,progress,**kwargs):
        captured.update(kwargs);completed.set()
        return dict(revision=dict(cards=[]))
    monkeypatch.setattr(server,'optimize',optimizer)
    try:
        app.submit(dict(operation='optimize',cards=[dict(name='Sun Titan',role='Main')],
            profile='deep',max_swaps=48,workers=2,training_pods=40))
        assert completed.wait(5)
        assert captured==dict(workers=2,clock=120,profile='deep',max_swaps=48,training_pods=40,scoring_backend='auto',search_mode='full')
    finally:app.executor.shutdown()


def test_campaign_budget_is_exclusive_across_threads_but_reentrant():
    errors=[]
    def contender():
        try:
            with forge.forge_session():pass
        except ValueError as e:errors.append(str(e))
    with forge.forge_session():
        with forge.forge_session():pass
        thread=threading.Thread(target=contender);thread.start();thread.join(2)
        assert not thread.is_alive()
    assert errors
    with forge.forge_session():pass # released after campaign
