import copy
import json
import random
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from cube_ai import acceleration,forge,sim_cache,surrogate
from cube_ai.catalog import Catalog
from cube_ai.config import BuildSpec
from cube_ai.draft import draft_pod
from cube_ai.optimize import game_trace,feedback_model,utility,opponent_gift
from cube_ai.candidate_scoring import batch_utility

@pytest.fixture(scope='module')
def fixture():
    c=Catalog();rows,unknown=c.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'))
    assert not unknown
    return c,rows,BuildSpec()

def test_omitting_unused_readiness_does_not_change_draft_or_deck(fixture):
    c,rows,spec=fixture
    a=draft_pod(c,rows,spec,random.Random(42),['UW','BU','BR'])
    b=draft_pod(c,rows,spec,random.Random(42),['UW','BU','BR'],readiness_hands=0)
    assert a['packs']==b['packs']
    for old,new in zip(a['decks'],b['decks']):
        assert {k:v for k,v in old.items() if k!='ready'}=={k:v for k,v in new.items() if k!='ready'}

def test_cache_exact_inputs_and_invalidating_preferences_and_spec(fixture):
    c,rows,spec=fixture
    a,hit=sim_cache.draft(c,rows,spec,42,['UW','BU','BR']);assert not hit
    b,hit=sim_cache.draft(c,rows,spec,42,['UW','BU','BR']);assert hit and a==b
    assert not sim_cache.draft(c,rows,spec,43,['UW','BU','BR'])[1]
    assert not sim_cache.draft(c,rows,spec,42,['BU','BR','UW'])[1]
    changed=BuildSpec.from_dict(dict(spec.to_dict(),bracket=2))
    assert not sim_cache.draft(c,rows,changed,42,['UW','BU','BR'])[1]
    b['decks'].clear()
    assert sim_cache.draft(c,rows,spec,42,['UW','BU','BR'])[0]['decks']

def test_corrupted_cache_is_a_miss():
    db=sim_cache.connection()
    with db:db.execute('INSERT INTO entries VALUES (?,?,?,?)',('broken','draft',b'bad gzip',0))
    assert sim_cache.get('broken') is None
    sim_cache.put('valid',dict(x=1),'draft');assert sim_cache.get('valid')==dict(x=1)

def test_batch_utility_matches_scalar_with_package_and_guild_weights(fixture):
    c,_,spec=fixture
    model=feedback_model(c,dict(summary=dict(mean_early_no_spell_rate=.4,no_finisher_cast_rate=.2),guilds={}),dict(observations=[]))
    model['guilds']['BR']['pressure']=1.12
    model['guilds']['BR']['package_gaps']={'sacrifice:outlet':.7,'reanimator:return':.5}
    cards=[c.cards[n] for n in ['Sun Titan','Blood Artist','Sol Ring','Counterspell','Phyrexian Altar','Reanimate']]
    scores,meta=batch_utility(cards,model,spec,opponent_gift,'cpu')
    assert meta['backend']=='cpu'
    for card in cards:assert scores[card['name']]==pytest.approx(utility(card,model,spec=spec),abs=2e-6)

def test_cuda_fallback_discloses_failure_and_cpu_is_correct(monkeypatch):
    monkeypatch.setattr(acceleration,'_cuda',None);monkeypatch.setattr(acceleration,'_failure',None)
    monkeypatch.setattr(acceleration,'_choices',{})
    def fail():raise acceleration.CUDAError('no device')
    monkeypatch.setattr(acceleration,'CUDALinear',fail)
    x=np.arange(24,dtype=np.float32).reshape(6,4);w=np.ones((4,3),dtype=np.float32)
    actual,meta=acceleration.linear(x,w,'gpu')
    np.testing.assert_allclose(actual,x@w);assert meta['backend']=='cpu' and meta['fallback']=='no device'

def test_cuda_validation_cannot_return_wrong_results(monkeypatch):
    class Wrong:
        def linear(self,x,w):return np.zeros((len(x),w.shape[1]),dtype=np.float32)
    monkeypatch.setattr(acceleration,'_cuda',Wrong());monkeypatch.setattr(acceleration,'_failure',None);monkeypatch.setattr(acceleration,'_choices',{})
    x=np.ones((4,3),dtype=np.float32);w=np.ones((3,2),dtype=np.float32)
    actual,meta=acceleration.linear(x,w,'gpu')
    assert meta['backend']=='cpu' and '容差' in meta['fallback'];np.testing.assert_array_equal(actual,x@w)


def test_partial_cuda_initialization_releases_its_own_context_and_search_directory(monkeypatch):
    import ctypes
    calls=[]
    def initialize(self):
        self.context=ctypes.c_void_p(17)
        self.destroy=lambda context:calls.append(('destroy',context.value))
        self.dll_dir=SimpleNamespace(close=lambda:calls.append(('directory',None)))
        raise acceleration.CUDAError('compiler failed')
    monkeypatch.setattr(acceleration.CUDALinear,'_initialize',initialize)
    with pytest.raises(acceleration.CUDAError,match='compiler failed'):acceleration.CUDALinear()
    assert calls==[('destroy',17),('directory',None)]


def test_cached_auto_cpu_choice_releases_old_gpu_and_does_not_reinitialize(monkeypatch):
    calls=[]
    monkeypatch.setattr(acceleration,'_cuda',SimpleNamespace(close=lambda:calls.append('closed')))
    monkeypatch.setattr(acceleration,'_failure',None)
    x=np.ones((512,64),dtype=np.float32);w=np.ones((64,64),dtype=np.float32)
    monkeypatch.setattr(acceleration,'_choices',{(len(x).bit_length(),64,64):'cpu'})
    def forbidden():raise AssertionError('Cached CPU choice must not compile GPU')
    monkeypatch.setattr(acceleration,'CUDALinear',forbidden)
    actual,meta=acceleration.linear(x,w,'auto')
    assert meta['backend']=='cpu' and meta['calibrated'] and acceleration._cuda is None
    np.testing.assert_array_equal(actual,x@w)
    acceleration.release();assert calls==['closed']


def test_small_auto_cpu_operation_releases_unused_context_but_keeps_useful_gpu_shape(monkeypatch):
    calls=[];gpu=SimpleNamespace(close=lambda:calls.append('closed'))
    monkeypatch.setattr(acceleration,'_cuda',gpu);monkeypatch.setattr(acceleration,'_failure',None)
    monkeypatch.setattr(acceleration,'_choices',{(15,48,32):'gpu'})
    x=np.ones((4,3),dtype=np.float32);w=np.ones((3,2),dtype=np.float32)
    actual,meta=acceleration.linear(x,w,'auto')
    assert calls==[] and acceleration._cuda is gpu and meta['backend']=='cpu'
    monkeypatch.setattr(acceleration,'_choices',{})
    actual,meta=acceleration.linear(x,w,'auto')
    assert calls==['closed'] and acceleration._cuda is None
    np.testing.assert_array_equal(actual,x@w)

def test_game_cache_reuses_only_same_seed_decks_and_backend(tmp_path,monkeypatch):
    out=tmp_path/'out';out.mkdir();decks=tmp_path/'decks';decks.mkdir()
    for n in ['a','b','c']:(decks/(n+'.dck')).write_text(n)
    jar=tmp_path/'forge.jar';jar.write_bytes(b'jar');java=tmp_path/'java';java.write_bytes(b'java')
    calls=[]
    def battle(config,deck_dir,order,seed,clock,out,log_name):
        calls.append(seed);(out/log_name).write_text('Game Result: Game 1 ended in 1000 ms. Ai(1)-a has won!')
        return dict(outcome='win',winner='a',order=order,seed=seed,log=log_name,wall_seconds=1,turns=12)
    monkeypatch.setattr(forge,'_run_battle',battle)
    c=dict(jar=str(jar),java=str(java))
    first=forge.run_battle(c,decks,['a','b','c'],42,90,out,'first.log')
    second=forge.run_battle(c,decks,['a','b','c'],42,90,out,'second.log')
    assert not first['cache_hit'] and second['cache_hit'] and len(calls)==1
    assert (out/'second.log').read_text()=='Game Result: Game 1 ended in 1000 ms. Ai(1)-a has won!'
    forge.run_battle(c,decks,['a','b','c'],43,90,out,'third.log');assert len(calls)==2
    (decks/'a.dck').write_text('changed')
    forge.run_battle(c,decks,['a','b','c'],42,90,out,'fourth.log');assert len(calls)==3

def test_engine_failures_are_never_cached(tmp_path,monkeypatch):
    for n in ['jar','java','a.dck']:(tmp_path/n).write_text(n)
    calls=[]
    def bad(*args):calls.append(1);return dict(outcome='engine_error',wall_seconds=1)
    monkeypatch.setattr(forge,'_run_battle',bad)
    config=dict(jar=str(tmp_path/'jar'),java=str(tmp_path/'java'))
    for _ in range(2):forge.run_battle(config,tmp_path,['a'],42,90,tmp_path,'x.log')
    assert len(calls)==2

def test_plain_and_wrapped_logs_have_same_behavior(fixture):
    c,_,_=fixture;decks=[dict(id='a',spells=['Swords to Plowshares'],commander='Sun Titan')]
    prefix='Turn: Turn 1 (Ai(1)-a)'
    plain=prefix+'\nAdd To Stack: Ai(1)-a cast Swords to Plowshares targeting Sun Titan\nGame Outcome: Ai(1)-a has lost because life total reached 0\nMatch Result: data\nGame Result: Game 1 ended in 50 ms.'
    wrapped=prefix+'\n\nAdd To Stack: Ai(1)-a cast Swords to Plow\nshares targeting Sun Titan\n\nGame Outcome: Ai(1)-a has lost because life total reached 0\n\nMatch Result: data\n\nGame Result: Game 1 ended in 200 ms.'
    assert game_trace(c,plain,decks)==game_trace(c,wrapped,decks)
    assert game_trace(c,plain,decks)['players']['a']['loss_reason']=='life total reached 0'

def test_split_has_no_cross_cube_or_deck_group_leakage():
    groups=[];cubes=[]
    for cube in range(10):
        for j in range(4):groups.extend([f'{cube}_{j}']*3);cubes.extend([str(cube)]*3)
    # One deck triple shared by cube 0 and cube 1 joins the whole cube components.
    groups[12:15]=groups[:3]
    labels,method=surrogate.split_groups(groups,cubes);assert method=='cube_and_deck_group'
    for values in [groups,cubes]:
        parts={label:{v for v,s in zip(values,labels) if s==label} for label in ['train','validation','test']}
        assert not parts['train']&parts['test'] and not parts['train']&parts['validation'] and not parts['validation']&parts['test']

def test_weak_or_small_learned_model_is_saved_but_not_enabled(monkeypatch):
    rng=np.random.default_rng(42);x=rng.normal(size=(180,54)).astype('float32');y=np.full((180,3),.5,dtype='float32')
    data=dict(x=x,y=y,groups=[f'g{i//3}' for i in range(180)],cubes=[f'c{i//36}' for i in range(180)],games=60,sources=['synthetic-test'])
    data.update(families=list(data['cubes']),family_scope_complete=True,deck_entities={})
    monkeypatch.setattr(surrogate,'collect',lambda *a:data)
    report=surrogate.train(SimpleNamespace(signature='fixture'))
    assert not report['active'] and not report['enough_data']
    assert report['test_independent_sources']==1 and report['source_bootstrap95_loss_difference'] is None
    assert (surrogate.MODELS/report['id']/'model.json').is_file()
    assert not (surrogate.MODELS/'active.json').exists()

def test_malformed_active_model_is_rejected():
    surrogate.MODELS.mkdir()
    (surrogate.MODELS/'active.json').write_text(json.dumps(dict(active=True,version=surrogate.VERSION,catalog='fixture')))
    assert surrogate.active_model(SimpleNamespace(signature='fixture')) is None


def test_learning_excludes_other_engines_and_legacy_reports_before_loading_logs(tmp_path,monkeypatch):
    matches=tmp_path/'matches';monkeypatch.setattr(forge,'MATCHES',matches)
    monkeypatch.setattr(surrogate,'engine_scope',lambda:['current','patched'])
    for name,engine in [('legacy',dict(jar_sha256='same-jar')),('original',dict(fingerprint=['current','off']))]:
        folder=matches/name;folder.mkdir(parents=True)
        (folder/'report.json').write_text(json.dumps(dict(engine=engine,tables=[],games=[dict(outcome='win')]*3)))
    result=surrogate.collect(SimpleNamespace())
    assert result['games']==0 and result['excluded_engine_games']==6 and result['engine']==['current','patched']


def test_valid_model_is_rejected_after_engine_change_and_restored_for_original_scope(monkeypatch):
    model=dict(active=True,version=surrogate.VERSION,catalog='fixture',engine=['original'],kind='ridge',
        mean=[0]*54,scale=[1]*54,weights=np.zeros((55,3)).tolist())
    surrogate.MODELS.mkdir();(surrogate.MODELS/'active.json').write_text(json.dumps(model))
    catalog=SimpleNamespace(signature='fixture')
    monkeypatch.setattr(surrogate,'engine_scope',lambda:['patched']);assert surrogate.active_model(catalog) is None
    monkeypatch.setattr(surrogate,'engine_scope',lambda:['original']);assert surrogate.active_model(catalog)==model


def test_current_model_report_is_not_hidden_by_late_finishing_legacy_task(monkeypatch):
    monkeypatch.setattr(surrogate,'engine_scope',lambda:['jar','java','resident','bridge'])
    for name,version in [('20260101_current',surrogate.VERSION),('20260102_legacy','activity-2')]:
        folder=surrogate.MODELS/name;folder.mkdir(parents=True)
        (folder/'report.json').write_text(json.dumps(dict(id=name,version=version,catalog='fixture',engine=['jar','java','resident','bridge'])),encoding='utf8')
    status=surrogate.status(SimpleNamespace(signature='fixture'))
    assert status['latest']['id']=='20260101_current' and status['latest_compatible']


def test_activity_training_counts_offturn_actions_censors_short_games_and_deduplicates(fixture,tmp_path,monkeypatch):
    import hashlib
    catalog,rows,_=fixture;matches=tmp_path/'matches';folder=matches/'fixture';folder.mkdir(parents=True)
    (folder/'cube.json').write_text(json.dumps(dict(cards=rows)),encoding='utf8')
    cube_hash=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    monkeypatch.setattr(forge,'MATCHES',matches)
    monkeypatch.setattr(surrogate,'engine_scope',lambda:['jar','java','resident','bridge'])
    decks=[dict(id=name,commander='Talrand, Sky Summoner',spells=['Counterspell'],lands=[],basics={'U':24},land_count=24) for name in ['a','b','c']]
    lines=[]
    for turn in range(5):
        for name in ['a','b','c']:
            lines.append(f'Turn: Turn {turn*3+1} (Ai(1)-{name})')
            if name=='b':
                lines.append('Add To Stack: Ai(1)-a cast Counterspell')
                lines.append('Add To Stack: Ai(1)-b triggered Talrand, Sky Summoner')
            if name=='c':lines.append('Combat: Ai(1)-c assigned Drake (1) to attack Ai(1)-a.')
    end='\nGame Result: Game 1 ended in 10 ms. Ai(1)-a has won!'
    (folder/'full.log').write_text('\n'.join(lines)+end,encoding='utf8')
    (folder/'short.log').write_text('\n'.join(lines[:5])+end,encoding='utf8')
    game=dict(pod=0,outcome='win',winner='a',order=['a','b','c'],seed=1,log='short.log',backend='resident-1')
    report=dict(match_id='fixture',cube_sha256=cube_hash,engine={'jar_sha256':'fixture','fingerprint':['jar','java','resident','bridge']},tables=[dict(pod=0,decks=[dict(d,buildable=True) for d in decks])],
                games=[game,dict(game,seed=2,log='full.log'),dict(game,seed=2,log='full.log'),dict(game,seed=3,log='full.log',cache_hit=True)])
    (folder/'report.json').write_text(json.dumps(report),encoding='utf8')
    data=surrogate.collect(catalog)
    assert data['games']==1 and data['censored_games']==1 and data['x'].shape==(3,54)
    assert data['y'][:,0].tolist()==[1,0,1]
    assert data['family_scope_complete'] and data['family_report']['families']==1
    # Raw files remain, but unverified source rows cannot manufacture families.
    (folder/'cube.json').write_text(json.dumps(dict(cards=rows[:-1])),encoding='utf8')
    changed=surrogate.collect(catalog)
    assert changed['games']==0 and changed['excluded_pool_games']==4
    assert changed['unverified_pool_sources']==[cube_hash]


def test_feedback_uses_observed_cycle_metric_when_coverage_is_sufficient(fixture):
    catalog,_,_=fixture
    summary=dict(mean_early_no_spell_rate=.4,mean_early_no_action_rate=.2,complete_cycle_coverage=1,no_finisher_cast_rate=.2)
    model=feedback_model(catalog,dict(summary=summary,guilds={}),dict(observations=[]))
    assert model['early_activity_metric']=='completed_cycle_no_action' and model['low_weight']==pytest.approx(.22)
    summary['complete_cycle_coverage']=.4
    assert feedback_model(catalog,dict(summary=summary,guilds={}),dict(observations=[]))['early_activity_metric']=='legacy_own_turn_no_spell'

def test_resident_memory_reservation_survives_next_validation_stage(monkeypatch):
    calls=[]
    def resources(workers):
        calls.append(workers)
        if len(calls)>1:raise ValueError('live workers already use the memory')
        return dict(workers=2,requested=workers)
    monkeypatch.setattr(forge,'execution_resources',resources)
    with forge.forge_session():
        assert forge.campaign_resources(2)['workers']==2
        with forge.forge_session():assert forge.campaign_resources(2)['workers']==2
    assert calls==[2]
