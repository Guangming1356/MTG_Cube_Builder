import os
import threading
from types import SimpleNamespace

from cube_ai import forge, forge_worker, optimize, task_control
from cube_ai.game_queue import GameQueue
from cube_ai.resources import MIB, capacity, process_memory, system_memory


def test_full_heap_budget_credits_owned_memory_without_double_counting():
    assert capacity(dict(available=7*1024*MIB))['capacity']==2
    owned=[dict(working_set=1024*MIB,private_bytes=1200*MIB)]*2
    # Two live heaps have already used RAM; still reserve their remaining growth.
    assert capacity(dict(available=6*1024*MIB),owned)['capacity']==2
    assert capacity(dict(available=6*1024*MIB))['capacity']==1
    # Momentarily tiny JVMs cannot authorize eight heaps.
    assert capacity(dict(available=7*1024*MIB),[dict(working_set=1*MIB)]*8)['capacity']==2
    assert capacity(dict(available=32*1024*MIB,commit_available=5*1024*MIB))['capacity']==1
    assert capacity({})['capacity']==1
    assert capacity(dict(available=32*1024*MIB),heap_mib=1536)['capacity']==8
    # A measured native peak above the heap allowance increases future budgets.
    unusually_large=[dict(working_set=4*1024*MIB,private_bytes=4*1024*MIB,peak_commit=4*1024*MIB)]
    assert capacity(dict(available=7*1024*MIB),unusually_large)['capacity']==1


def test_real_memory_api_and_exited_process():
    assert system_memory()['available']>0
    value=process_memory(os.getpid())
    assert value and value['working_set']>0
    assert process_memory(4294967294) is None


def test_dynamic_queue_ramps_drains_pressure_and_keeps_every_game():
    now=[0.];free=[32*1024*MIB];release=threading.Event();started=[];trimmed=[]
    lock=threading.Lock()
    def battle(n):
        with lock:started.append(n)
        assert release.wait(3)
        return dict(outcome='win',seed=n,cache_hit=n==0)
    q=GameQueue(dict(workers=1,dynamic=True,ceiling=4),{},clock=lambda:now[0],
                sample=lambda:(dict(available=free[0]),[]),trim=trimmed.append)
    with q:
        try:
            for n in range(10):q.submit(n,battle,n)
            assert len(q.pending)==1
            free[0]=10*1024*MIB;now[0]=3;q.pump();assert len(q.pending)==2
            now[0]=6;q.pump();assert len(q.pending)==2 # expansion needs extra headroom
            free[0]=11*1024*MIB;now[0]=9;q.pump();assert len(q.pending)==3
            free[0]=0;now[0]=10;q.pump()
            assert q.target==1 and len(q.pending)==3 # active games are not stopped
        finally:release.set()
        results=[]
        while q:results.extend(q.collect(True))
        free[0]=4*1024*MIB;now[0]=11;q.pump()
    assert sorted(started)==list(range(10))
    assert sorted((tag,r['seed']) for tag,r in results)==[(n,n) for n in range(10)]
    report=q.report()
    assert report['peak_active']==3 and report['final_target']==1
    assert report['normal_new_games']==9 and report['reused_games']==1
    assert report['minimum_available_memory_bytes']==0
    assert [d['target'] for d in report['decisions']]==[1,2,3,1]
    assert trimmed[-1]==1


def test_fixed_legacy_queue_does_not_change_concurrency_or_sample():
    def bad():raise AssertionError('legacy fixed worker protocol must stay fixed')
    with GameQueue(dict(workers=2),{},sample=bad) as q:
        for n in range(6):q.submit(n,lambda:dict(outcome='draw'))
        results=[]
        while q:results.extend(q.collect(True))
        assert len(results)==6 and q.target==2 and not q.report()['dynamic']


def test_trim_closes_only_surplus_idle_owned_workers(monkeypatch):
    closed=[]
    def worker(n,busy):return SimpleNamespace(closed=False,busy=busy,close=lambda:closed.append(n))
    active=worker('active',True);idle1=worker('idle1',False);idle2=worker('idle2',False)
    monkeypatch.setattr(forge_worker,'_workers',[active,idle1,idle2])
    forge_worker.trim_idle(1)
    assert closed==['idle1','idle2'] and forge_worker._workers==[active]


def test_pause_time_not_counted_as_slow_native_execution(monkeypatch):
    now=[0.];control=SimpleNamespace(paused_seconds=10.)
    monkeypatch.setattr(task_control,'_current',control)
    with GameQueue(dict(workers=1),{},clock=lambda:now[0]) as q:
        control.paused_seconds=40.;now[0]=50.;q.normal=2
        assert q.report()['active_wall_seconds']==20.
        assert q.report()['normal_new_games_per_minute']==6.


def test_optimizer_preserves_explicit_automatic_request(monkeypatch):
    monkeypatch.setattr(optimize,'audit',lambda *a,**kw:dict(hard_errors=0))
    monkeypatch.setattr(optimize,'execution_resources',lambda w:dict(workers=3))
    captured=[]
    def run(catalog,rows,spec,progress,workers,*args):captured.append(workers)
    monkeypatch.setattr(optimize,'_optimize',run)
    optimize.optimize(None,[{}]*600,None,workers=0)
    optimize.optimize(None,[{}]*600,None,workers=2)
    assert captured==[0,2]


def test_training_protocol_keeps_auto_for_all_later_stages(tmp_path,monkeypatch):
    from cube_ai import surrogate
    from cube_ai.config import BuildSpec
    from cube_ai.experiment import experiment_budget
    monkeypatch.setattr(surrogate,'active_model',lambda c:None)
    monkeypatch.setattr(optimize,'campaign_resources',lambda w:dict(workers=2,requested=w))
    monkeypatch.setattr(optimize,'draft_evaluation',lambda *a,**kw:{})
    seen=[]
    def simulate(*args,**kw):seen.append(kw['workers']);return {}
    monkeypatch.setattr(optimize,'simulate',simulate)
    monkeypatch.setattr(optimize,'evidence_from_match',lambda *a:{})
    protocol,*_=optimize.collect_training(None,[],BuildSpec(),tmp_path,pods=10,workers=0,
        budget=experiment_budget('quick'),progress=lambda _:None)
    assert protocol['game_workers']==2 and protocol['requested_game_workers']==0 and seen==[0]


def test_cross_games_use_auto_and_keep_all_rotations(tmp_path,monkeypatch):
    monkeypatch.setattr(optimize,'configuration',lambda:{})
    monkeypatch.setattr(optimize,'card_index',lambda c:{})
    monkeypatch.setattr(optimize,'write_deck',lambda *a:None)
    requests=[]
    def resources(w):requests.append(w);return dict(workers=2)
    monkeypatch.setattr(optimize,'campaign_resources',resources)
    def battle(c,decks,order,seed,clock,out,log):return dict(outcome='win',winner=order[0],seed=seed,order=order)
    monkeypatch.setattr(optimize,'run_battle',battle)
    def table(changed):
        return dict(decks=[dict(commander='new' if changed and i==0 else 'old',spells=[],lands=[],
             basics={},buildable=True,engine_supported=True) for i in range(3)])
    result=optimize.cross_cube(None,dict(tables=[table(False)]*2),dict(tables=[table(True)]*2),
          dict(game_workers=2,requested_game_workers=0,holdout_seeds=[100,200],clock_seconds=30),tmp_path,lambda _:None)
    assert requests==[0] and result['attempted']==6
    assert [(r['fixture'],r['game']) for r in result['games']]==[(n,g) for n in range(2) for g in range(3)]
    for r in result['games']:
        ids=result['fixtures'][r['fixture']]['ids'];g=r['game']
        assert r['order']==ids[g:]+ids[:g]
        assert r['seed']==[100,200][r['fixture']]+50000+g


def test_manual_cap_survives_memory_reduction_between_stages(monkeypatch):
    calls=[]
    def resources(w):
        calls.append(w)
        if w==2:raise ValueError('memory changed after initial validation')
        return dict(workers=1,requested=0,ceiling=8,dynamic=True)
    monkeypatch.setattr(forge,'execution_resources',resources)
    with forge.forge_session():
        first=forge.campaign_resources(2)
        assert first['workers']==1 and first['ceiling']==2 and first['requested']==2
        assert forge.campaign_resources(2)==first
    assert calls==[2,0]
