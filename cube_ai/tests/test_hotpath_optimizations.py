"""Equivalence and bounded-memory checks for optimized local evaluation."""
import random
from pathlib import Path

import pytest

from cube_ai.brackets import DeckRules,may_add
from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec
from cube_ai.optimize import _pod_metrics,draft_evaluation,schedule
from cube_ai.search import CandidateEvaluator
from cube_ai.sim_cache import DraftWorkspace


@pytest.fixture(scope='module')
def fixture():
    catalog=Catalog()
    rows,unknown=catalog.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    return catalog,rows


@pytest.mark.parametrize('bracket',[None,1,2,3,4,5])
def test_incremental_legality_matches_original_card_by_card(fixture,bracket):
    catalog,rows=fixture;spec=BuildSpec.from_dict({'bracket':bracket})
    names=[r['name'] for r in rows]+['Rhystic Study','Cyclonic Rift','Smothering Tithe','Demonic Tutor','Ancient Tomb']
    random.Random(731).shuffle(names)
    initial=['Atraxa, Praetors\' Voice']
    expected=[]
    for name in names:
        if may_add(catalog,initial+expected,name,spec):expected.append(name)
    rules=DeckRules(catalog,spec)
    assert rules.select(initial,names)==expected
    # Selecting a second deck must reset the running budget while retaining only
    # per-card checks. A first deck may have exhausted its Game Changer slots.
    assert rules.select(initial,names)==expected


@pytest.mark.parametrize('query,identity,limit',[
    ('draw card',None,30),('sun titan','W',5),('',None,10),('sAcRiFiCe',None,100),
    ('not-a-real-card','BU',10),('+1/+1',None,2),('  draw ',None,-1),('mana',None,101)])
def test_bounded_search_matches_exhaustive_order(fixture,query,identity,limit):
    catalog,_=fixture;words=query.casefold().split()
    expected=[c for c in catalog.cards.values() if (not identity or c['identity']==identity)
              and all(w in (c['name']+' '+c['text']+' '+c['type']).casefold() for w in words)]
    expected.sort(key=lambda c:(not c['name'].casefold().startswith(query.casefold()),-c['quality'],c['name']))
    expected=expected[:min(100,max(1,limit))]
    assert catalog.search(query,identity,limit)==expected
    returned=catalog.search(query,identity,limit);returned.clear()
    assert catalog.search(query,identity,limit)==expected


def test_compressed_workspace_is_bounded_and_results_are_not_mutable_aliases(fixture):
    catalog,rows=fixture;spec=BuildSpec.from_dict({'bracket':3});workspace=DraftWorkspace(catalog,spec,max_bytes=28000)
    summarize=lambda pod:_pod_metrics(catalog,pod)
    first,hit=workspace.table(catalog,rows,spec,41,['UW','BR','GU'],summarize)
    assert not hit
    original_packs=[list(p) for p in first[0]['packs']]
    first[0]['packs'][0].clear()
    cached,hit=workspace.table(catalog,rows,spec,41,['UW','BR','GU'],summarize)
    assert hit and cached[0]['packs']==original_packs
    for seed in range(50):workspace.table(catalog,rows,spec,seed,['UW','BR','GU'],summarize)
    assert 0<workspace.bytes_used<=28000 and len(workspace.entries)<50
    tiny=DraftWorkspace(catalog,spec,max_bytes=1)
    result,hit=tiny.table(catalog,rows,spec,41,['UW','BR','GU'],summarize)
    assert not hit and result==cached and tiny.bytes_used==0 and not tiny.entries


def test_spawn_workers_do_not_load_the_full_card_pool_and_accept_new_cards(fixture,tmp_path):
    import copy
    catalog,rows=fixture;spec=BuildSpec.from_dict({'bracket':3});seeds,guilds=schedule(10,11825)
    items=[];present={r['name'] for r in rows}
    for i,row in enumerate(rows):
        old=catalog.cards[row['name']]
        if row['role']!='Main':continue
        replacement=next((c for c in catalog.cards.values() if c['name'] not in present and c['identity']==old['identity'] and c['kind']==old['kind']),None)
        if not replacement:continue
        trial=copy.deepcopy(rows);trial[i]['name']=replacement['name']
        items.append(dict(add=replacement['name'],rows=trial))
        if len(items)==4:break
    assert len(items)==4
    # No readable source is available to a worker; only the required records are
    # sent by the parent. Later batches introduce names absent from first tasks.
    original=catalog.source;catalog.source=tmp_path/'not-present.json'
    try:
        with CandidateEvaluator(catalog,spec,seeds,guilds,workers=2) as evaluator:
            parallel=evaluator.batch(items[:2],10)+evaluator.batch(items[2:],10)
            assert not evaluator.fallback
            serial=[evaluator.evaluate(item['rows'],10) for item in items]
            semantic=lambda r:{k:v for k,v in r.items() if k!='execution'}
            assert list(map(semantic,parallel))==list(map(semantic,serial))
            assert all(len(names)<len(catalog.cards)//10 for names in evaluator._worker_names)
    finally:catalog.source=original


def test_parallel_assignment_balances_name_collisions_and_keeps_warm_ties(monkeypatch):
    from collections import Counter
    from types import SimpleNamespace
    from cube_ai import experiment,search
    monkeypatch.setattr(experiment,'memory_available',lambda:16*1024**3)
    monkeypatch.setattr(search.os,'cpu_count',lambda:8)
    items=[dict(add=chr(65+4*i)) for i in range(8)]
    assert len({sum(item['add'].encode())%4 for item in items})==1
    with CandidateEvaluator(SimpleNamespace(cards={}),BuildSpec(),[1],[['UW','BR','GU']],workers=4) as evaluator:
        first=evaluator._assign_slots(items)
        assert sorted(Counter(first).values())==[2,2,2,2]
        assert evaluator._assign_slots(items)==first
        assert evaluator.stats['max_batch_slot_load']==2


def test_readiness_chooses_feasible_seen_lands_without_exceeding_land_drop_limit(fixture):
    from cube_ai.draft import affordable,opening_test
    catalog,_=fixture
    class FixedOpening:
        def sample(self,deck,count):
            return sorted(deck,key=lambda c:0 if c['name']=='Forest' else 1 if c['name']=='Island' else 2)
    result=opening_test(catalog,['Counterspell']+['Darksteel Colossus']*7,['Forest','Island','Island'],'U',11,FixedOpening(),hands=1)
    assert result['ready_by_turn']=={'1':0,'2':1,'3':1,'4':1}
    assert affordable('{U}{U}',[{'G'},{'U'},{'U'}],max_sources=2)
    assert not affordable('{1}{U}{U}',[{'G'},{'U'},{'U'}],max_sources=2)
    assert not affordable('{U}{U}',[{'G','U'}],max_sources=2) # One dual cannot pay two pips.


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows native junction')
def test_worker_resources_use_native_junction_without_launching_powershell(tmp_path,monkeypatch):
    from cube_ai import forge
    target=tmp_path/'Forge resources 中文';(target/'res').mkdir(parents=True)
    (target/'res/card.txt').write_text('read-only fixture',encoding='utf8')
    output=tmp_path/'simulation 中文';output.mkdir()
    def forbidden(*args,**kwargs):raise AssertionError('Native junction should not start a shell')
    monkeypatch.setattr(forge.subprocess,'run',forbidden)
    home=forge.worker_home(dict(home=str(target)),output)
    assert (home/'res').is_junction() and (home/'res').resolve()==(target/'res').resolve()
    assert (home/'res/card.txt').read_text(encoding='utf8')=='read-only fixture'
    assert forge.worker_home(dict(home=str(target)),output)==home


def test_persisted_forge_index_reuses_archive_and_invalidates_on_source_change(tmp_path,monkeypatch):
    import zipfile
    from cube_ai import forge
    folder=tmp_path/'engine/res/cardsfolder';folder.mkdir(parents=True)
    archive=folder/'cardsfolder.zip'
    with zipfile.ZipFile(archive,'w') as stream:stream.writestr('test.txt','Name:Original\n')
    config=dict(home=str(tmp_path/'engine'))
    first=forge.card_index(config);assert first['original']=='Original'
    forge._indices.clear()
    original_zip=forge.zipfile.ZipFile
    def forbidden(*args,**kwargs):raise AssertionError('Warm index should not reread archives')
    monkeypatch.setattr(forge.zipfile,'ZipFile',forbidden)
    assert forge.card_index(config)==first
    monkeypatch.setattr(forge.zipfile,'ZipFile',original_zip)
    with zipfile.ZipFile(archive,'w') as stream:stream.writestr('test.txt','Name:Updated longer card name\n')
    assert 'updated longer card name' in forge.card_index(config)
    assert 'original' not in forge.card_index(config)
    # Corrupted cache must fall back to actual scripts, not disable the engine.
    forge._indices.clear()
    for path in forge.INDEX_CACHE.glob('*.json'):path.write_text('broken',encoding='utf8')
    assert 'updated longer card name' in forge.card_index(config)


def test_compact_task_catalog_matches_full_stress_without_loading_services(fixture):
    from cube_ai.server import Application,execute_operation
    catalog,rows=fixture;spec=BuildSpec()
    thin=Catalog.from_records([catalog.cards[r['name']] for r in rows],catalog.snapshot,catalog.signature)
    assert len(thin.cards)==600 and thin.resolve(rows[0]['name'].upper())==rows[0]['name']
    app=Application(catalog=thin)
    try:
        compact=execute_operation(app,'stress',spec,rows,{'trials':5},lambda _:None)
        assert app._knowledge is None and app._feedback is None
        from cube_ai.draft import stress_test
        assert compact==stress_test(catalog,rows,spec,5)
    finally:app.shutdown()


def test_feedback_transactions_close_handles_even_on_failure(tmp_path,monkeypatch):
    import sqlite3
    from cube_ai import feedback
    original=sqlite3.connect;opened=[]
    def connect(*args,**kwargs):
        value=original(*args,**kwargs);opened.append(value);return value
    monkeypatch.setattr(feedback.sqlite3,'connect',connect)
    store=feedback.FeedbackStore(tmp_path/'preferences.sqlite')
    store.add('Sun Titan','Serra Angel','commander:commander')
    with pytest.raises(RuntimeError):
        with store.connect() as database:
            database.execute("INSERT INTO comparisons(winner,loser) VALUES('a','b')")
            raise RuntimeError('rollback')
    for database in opened:
        with pytest.raises(sqlite3.ProgrammingError):database.execute('SELECT 1')
    assert store.status('commander:commander')['comparisons']==1


def test_calibration_goals_make_the_speed_memory_tradeoff_explicit():
    from cube_ai.tuning import choose
    def phase(name,seconds,memory,compatible=True):
        return dict(jvm_profile=name,workers=2,seconds=[seconds,seconds],compatible=compatible,
                    normal_games=6,attempted_games=6,peak_engine_private_bytes=memory)
    low=phase('default',54,1800);fast=phase('parallel_gc',48,2600);slow=phase('compact_heap',80,1200)
    broken=phase('broken',1,1,False)
    assert choose([low,fast,slow,broken],goal='balanced') is low
    assert choose([low,fast,slow,broken],goal='speed') is fast
    assert choose([low,fast,slow,broken],goal='memory') is slow
    with pytest.raises(ValueError):choose([low],goal='unknown')


def test_large_download_streams_bounded_chunks_and_static_etags(tmp_path):
    import hashlib
    from types import SimpleNamespace
    from cube_ai.server import handler_for
    target=tmp_path/'evidence.zip'
    block=bytes(range(256))*4096
    with target.open('wb') as stream:
        for _ in range(12):stream.write(block)
    expected=hashlib.sha256(block*12).hexdigest()
    class Sink:
        def __init__(self):self.digest=hashlib.sha256();self.maximum=0;self.total=0
        def write(self,data):self.digest.update(data);self.maximum=max(self.maximum,len(data));self.total+=len(data)
    headers={};statuses=[];sink=Sink()
    fake=SimpleNamespace(headers={},send_response=statuses.append,send_header=lambda k,v:headers.update({k:v}),end_headers=lambda:None,wfile=sink)
    method=handler_for(None).file
    method(fake,target,download=True)
    assert sink.digest.hexdigest()==expected and sink.maximum<=128*1024
    assert sink.total==int(headers['Content-Length'])==target.stat().st_size
    assert headers['Content-Type'] in {'application/zip','application/x-zip-compressed'} and 'attachment' in headers['Content-Disposition']
    headers.clear();method(fake,target)
    fake.headers={'If-None-Match':headers['ETag']};before=sink.total
    method(fake,target)
    assert statuses[-1]==304 and sink.total==before


def test_finished_jobs_survive_restart_without_eagerly_loading_results(tmp_path,monkeypatch):
    import json
    from cube_ai import task_process
    from cube_ai.server import Application
    id_='1234567890abcdef';folder=task_process.JOBS/id_;folder.mkdir(parents=True)
    summary=dict(id=id_,state='done',operation='stress',progress='完成',cube_name='Restored fixture')
    (folder/'summary.json').write_text(json.dumps(summary),encoding='utf8')
    result_path=folder/'result.json';result_path.write_text(json.dumps(dict(result=dict(trials=5))),encoding='utf8')
    original=Path.read_text
    def forbid_result(path,*args,**kwargs):
        if path==result_path:raise AssertionError('Task listing must not load the full result')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',forbid_result)
    app=Application(catalog=Catalog.from_records([],None,'test'))
    try:
        assert app.public_jobs()[0]['state']=='done' and not app.public_jobs()[0]['controllable']
        assert 'result' not in app.jobs[id_]
        monkeypatch.setattr(Path,'read_text',original)
        assert app.get_job(id_)['result']==dict(trials=5)
        assert 'result' not in app.jobs[id_]
    finally:app.shutdown()


def test_shutdown_refuses_live_work_and_blocks_new_submissions(fixture):
    import requests,threading
    from http.server import ThreadingHTTPServer
    from cube_ai.server import Application,handler_for
    catalog,_=fixture;app=Application(catalog=catalog)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    url=f'http://127.0.0.1:{server.server_port}'
    try:
        app.jobs['test']=dict(operation='forge',state='paused')
        response=requests.post(url+'/api/shutdown',json={},timeout=3)
        assert response.status_code==400 and not app.closing
        app.jobs.clear()
        response=requests.post(url+'/api/shutdown',json={},timeout=3)
        assert response.status_code==200 and app.closing
        worker.join(3);assert not worker.is_alive()
        with pytest.raises(ValueError,match='退出'):app.submit(dict(operation='learn-games'))
    finally:server.shutdown();server.server_close();app.shutdown()


def test_streamed_native_events_preserve_wrapping_and_skip_summary_blocks():
    from cube_ai.optimize import log_events,iter_log_events
    text=('startup text\r\nTurn: Turn 1 (Ai(1)-a)\r\n'
          'Add To Stack: Ai(1)-a cast Fire\r\n targeting b\r\n'
          'Game Outcome: a has won!\r\nMatch Result: summary\r\n'
          'Game Result: details\r\n')
    expected=['Turn: Turn 1 (Ai(1)-a)','Add To Stack: Ai(1)-a cast Fire targeting b','Game Outcome: a has won!']
    assert log_events(text)==expected and list(iter_log_events(text))==expected
    assert log_events('startup only')==[]


def test_trace_card_prefixes_and_alternate_faces_remain_unambiguous():
    from types import SimpleNamespace
    from cube_ai.optimize import game_trace
    cards={name:dict(finisher=name=='Fireball',interaction=name=='Fire') for name in ['Commander','Fire','Fireball','Front // Back']}
    deck=dict(id='a',commander='Commander',spells=['Fire','Fireball','Front // Back'])
    log=('Turn: Turn 1 (Ai(1)-a)\n'
         'Add To Stack: Ai(1)-a cast Fireball targeting b\n'
         'Add To Stack: Ai(1)-a cast Fire\n'
         'Add To Stack: Ai(1)-a cast Back (alternate face)\n')
    value=game_trace(SimpleNamespace(cards=cards),log,[deck])['players']['a']
    assert value['casts']=={'Fireball':1,'Fire':1,'Front // Back':1}
    assert value['finisher_casts']==1 and value['interaction_casts']==1 and value['spellcasts']==3
