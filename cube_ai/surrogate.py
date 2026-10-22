"""Learn observed deck activity, with grouped evaluation and conservative adoption."""
import hashlib
import json
import statistics
import time
import uuid
import threading
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from .config import ROOT
from .acceleration import linear

MODELS=ROOT/'models'
VERSION='activity-6'
_training_lock=threading.Lock()

def engine_scope():
    """Exact engine, Java, native entry, bridge and managed compatibility bytes."""
    from .forge import configuration
    from .tuning import engine_key
    try:return engine_key(configuration())
    except (OSError,ValueError,KeyError,TypeError):return None

def fingerprint(deck):
    return hashlib.sha256(json.dumps([deck.get('commander'),sorted(deck.get('spells',[])),
        sorted(deck.get('lands',[])),deck.get('basics',{})],sort_keys=True).encode()).hexdigest()

def deck_vector(catalog,deck):
    cards=[catalog.cards[n] for n in deck['spells']];cmd=catalog.cards[deck['commander']]
    return np.array([len(cards)/40,deck['land_count']/60,
        statistics.mean(c['mv'] for c in cards)/6 if cards else 0,
        statistics.mean(c['quality'] for c in cards)/5 if cards else 0,
        sum(c['mv']<=2 for c in cards)/40,
        *[sum(c[k] for c in cards)/40 for k in ['creature','interaction','wipe','ramp','draw','finisher']],
        cmd['mv']/8,cmd['quality']/5,*[float(c in cmd['identity']) for c in 'WUBRG']],dtype=np.float32)

def contexts(vectors):
    x=np.asarray(vectors,dtype=np.float32);other=(x.sum(axis=0)-x)/max(1,len(x)-1)
    return np.concatenate([x,other,x-other],axis=1)

def collect(catalog,progress=lambda _:None):
    from .forge import MATCHES,verified_game_result
    from .cube_family import pool_counts,group_cubes
    from .optimize import game_trace
    x=[];y=[];groups=[];cubes=[];seen=set();games=0;sources=[];censored=0
    scope=engine_scope();excluded_engine_games=0;excluded_evidence_games=0
    pools={};pool_conflicts=set();deck_entities={};excluded_pool_games=0;unverified_pool_sources=set()
    for path in sorted(MATCHES.glob('*/report.json')):
        try:
            r=json.loads(path.read_text(encoding='utf8'));tables={p['pod']:p for p in r['tables']}
            if scope is None or r.get('engine',{}).get('fingerprint')!=scope:
                excluded_engine_games+=len(r.get('games',[]));continue
            try:
                rows=json.loads((path.parent/'cube.json').read_text(encoding='utf8'))['cards']
                cube=r['cube_sha256']
                if hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()!=cube:
                    raise ValueError('原始牌池身份与对局记录不匹配')
                counts=pool_counts(rows,catalog)
                if cube in pools and pools[cube]!=counts:pool_conflicts.add(cube)
                pools[cube]=counts
            except (OSError,ValueError,KeyError,TypeError):
                # One damaged legacy source must not permanently block learning
                # from other verified pools. Keep raw files and count exclusions.
                excluded_pool_games+=len(r.get('games',[]))
                unverified_pool_sources.add(str(r.get('cube_sha256') or path.parent.name))
                continue
            for game in r['games']:
                if game['outcome'] not in {'win','draw'} or game.get('cache_hit'):continue
                actual=game.get('backend','')
                if not (actual.startswith('resident') if scope[2]=='resident' else actual=='isolated'):
                    excluded_engine_games+=1;continue
                decks=tables[game['pod']]['decks']
                if not all(d.get('buildable') for d in decks):continue
                identities={d['id']:fingerprint(d) for d in decks}
                group=hashlib.sha256(json.dumps(sorted(identities.values())).encode()).hexdigest()
                unique=(r['engine'].get('jar_sha256'),tuple(identities[n] for n in game['order']),game['seed'])
                if unique in seen:continue
                log=(path.parent/game['log']).read_text(encoding='utf8')
                if verified_game_result(log,game,game['order']) is None:
                    excluded_evidence_games+=1;continue
                trace=game_trace(catalog,log,decks,extended=True)
                if any(trace['players'][d['id']]['complete_early_cycles']<4 for d in decks):
                    censored+=1;continue
                features=contexts([deck_vector(catalog,d) for d in decks])
                labels=[]
                for d in decks:
                    p=trace['players'][d['id']]
                    labels.append([1-p['no_action_cycle_rate'],min(1,p['spellcasts']/max(1,p['own_turns']*1.5)),float(p['finisher_casts']>0)])
                seen.add(unique);games+=1;x.extend(features);y.extend(labels)
                groups.extend([group]*3);cubes.extend([r['cube_sha256']]*3)
                deck_entities[group]=sorted(identities.values())
            sources.append(r['match_id'])
        except (KeyError,ValueError,OSError,TypeError):continue
    used=set(cubes);known={c:pools[c] for c in used if c in pools and c not in pool_conflicts}
    families,family_report=group_cubes(known)
    missing=sorted(used-set(known))
    return dict(x=np.asarray(x,dtype=np.float32),y=np.asarray(y,dtype=np.float32),groups=groups,cubes=cubes,games=games,sources=sources,censored_games=censored,
                engine=scope,excluded_engine_games=excluded_engine_games,excluded_evidence_games=excluded_evidence_games,
                families=[families.get(c,c) for c in cubes],deck_entities=deck_entities,
                family_scope_complete=not missing,family_report=family_report,
                excluded_pool_games=excluded_pool_games,unverified_pool_sources=sorted(unverified_pool_sources),
                missing_cube_sources=missing)

def split_units(groups,cubes,families=None,deck_entities=None):
    """Join whole pools, near-pool families and any repeated individual deck."""
    if len(groups)!=len(cubes) or families is not None and len(families)!=len(cubes):
        raise ValueError('训练分组元数据长度不一致')
    parent={c:c for c in cubes};owners={};family_owners={};deck_owners={}
    def find(c):
        while parent[c]!=c:parent[c]=parent[parent[c]];c=parent[c]
        return c
    def join(a,b):
        x,y=find(a),find(b)
        if x!=y:parent[max(x,y)]=min(x,y)
    for index,(group,cube) in enumerate(zip(groups,cubes)):
        if group in owners:join(cube,owners[group])
        else:owners[group]=cube
        if families is not None:
            family=families[index]
            if family in family_owners:join(cube,family_owners[family])
            else:family_owners[family]=cube
        for deck in (deck_entities or {}).get(group,()):
            if deck in deck_owners:join(cube,deck_owners[deck])
            else:deck_owners[deck]=cube
    return [find(c) for c in cubes]


def split_groups(groups,cubes,families=None,deck_entities=None):
    """Never split a supplied pool family just to manufacture a holdout."""
    components=split_units(groups,cubes,families,deck_entities)
    rng=np.random.default_rng(193);unique=sorted(set(components))
    if len(unique)>=5:
        rng.shuffle(unique);a=max(1,len(unique)//5);test=set(unique[:a]);val=set(unique[a:2*a])
        return ['test' if c in test else 'validation' if c in val else 'train' for c in components],('cube_family_and_deck_group' if families is not None else 'cube_and_deck_group')
    if families is not None:return ['train']*len(groups),'insufficient_cube_families'
    unique=sorted(set(groups));rng.shuffle(unique);a=max(1,len(unique)//5)
    test=set(unique[:a]);val=set(unique[a:2*a])
    return ['test' if g in test else 'validation' if g in val else 'train' for g in groups],'deck_group_only'

def predict(model,x,backend='auto'):
    x=(np.asarray(x,dtype=np.float32)-np.asarray(model['mean'],dtype=np.float32))/np.asarray(model['scale'],dtype=np.float32)
    if model['kind']=='ridge':
        a,_=linear(np.column_stack([x,np.ones(len(x),dtype=np.float32)]),np.asarray(model['weights'],dtype=np.float32),backend)
    else:
        hidden,_=linear(x,np.asarray(model['w1'],dtype=np.float32),backend)
        hidden=np.maximum(0,hidden+np.asarray(model['b1'],dtype=np.float32))
        a,_=linear(hidden,np.asarray(model['w2'],dtype=np.float32),backend);a+=np.asarray(model['b2'],dtype=np.float32)
    return np.clip(a,0,1)

def predict_tables(catalog,tables,model,backend='auto'):
    features=[]
    for table in tables:
        if not all(d.get('buildable') for d in table['decks']):return None
        features.extend(contexts([deck_vector(catalog,d) for d in table['decks']]))
    return predict(model,features,backend)[:,0] if features else None

def train(catalog,progress=lambda _:None):
    from .ai_settings import ProcessLock
    if not _training_lock.acquire(blocking=False):raise ValueError('已有实战模型学习任务，请等待完成')
    try:
        with ProcessLock(MODELS/'training'):return _train(catalog,progress)
    finally:_training_lock.release()

def _train(catalog,progress=lambda _:None):
    started=time.perf_counter();progress('学习历史实战：排除异常、重复比赛，按整桌与 Cube 分组')
    data=collect(catalog,progress);x,y=data['x'],data['y'];groups=data['groups']
    root=MODELS/(datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);root.mkdir(parents=True)
    report=dict(id=root.name,version=VERSION,games=data['games'],independent_groups=len(set(groups)),cubes=len(set(data['cubes'])),
        status='insufficient_data',active=False,targets=['前四完整个人周期的主动行动','每回合施放密度','本局施放过终结牌'],
        censored_games=data.get('censored_games',0),
        engine=data.get('engine'),catalog=catalog.signature,excluded_engine_games=data.get('excluded_engine_games',0),
        excluded_evidence_games=data.get('excluded_evidence_games',0),
        excluded_pool_games=data.get('excluded_pool_games',0),
        independent_cube_families=len(set(data.get('families',[]))),
        activity_definition='完整个人周期内任意回合的施放、主动异能或宣攻；不计自动触发、下地及最后未完整观察的周期。四周期不足的整局不训练，可能少代表结束很早的牌组。',
        limitation='学习 Forge 原生 AI 的可观测行为，不预测人类娱乐性或认证牌力。没有把一副牌的胜负分摊到单卡。')
    (root/'families.json').write_text(json.dumps(data.get('family_report',{}),ensure_ascii=False,indent=2),encoding='utf8')
    if len(set(groups))<10:
        report['reason']='独立轮抓牌组不足10组；保留固定评分，继续积累实战'
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        return report
    if not data.get('family_scope_complete'):
        report['reason']='缺少可核对的原始 Cube 牌池，无法隔离相近改版；保留固定评分并保留历史数据'
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return report
    labels,method=split_groups(groups,data['cubes'],data['families'],data.get('deck_entities'))
    units=split_units(groups,data['cubes'],data['families'],data.get('deck_entities'))
    report['independent_split_sources']=len(set(units))
    indices={k:np.where(np.array(labels)==k)[0] for k in ['train','validation','test']}
    if any(len(v)<3 for v in indices.values()):
        report['reason']='相近牌池与重复牌组合并后，训练或保留来源不足；不会拆开同一来源凑测试集';(root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return report
    tr,va,te=[indices[k] for k in ['train','validation','test']]
    mean=x[tr].mean(axis=0);scale=x[tr].std(axis=0);scale[scale<.001]=1
    z=(x-mean)/scale;aug=np.column_stack([z,np.ones(len(z),dtype=np.float32)])
    base=dict(version=VERSION,mean=mean.tolist(),scale=scale.tolist(),catalog=catalog.signature,engine=data.get('engine'))
    candidates=[]
    for alpha in [.1,1.,10.]:
        penalty=np.eye(aug.shape[1])*alpha;penalty[-1,-1]=0
        w=np.linalg.solve(aug[tr].T@aug[tr]+penalty,aug[tr].T@y[tr])
        model=dict(base,kind='ridge',weights=w.tolist(),alpha=alpha)
        candidates.append((float(np.mean((predict(model,x[va],'cpu')-y[va])**2)),model))
    # Ablation: does opponent context help beyond the deck's own features?
    own=aug[:,:19].copy();own[:,-1]=1
    penalty=np.eye(19);penalty[-1,-1]=0
    small=np.linalg.solve(own[tr].T@own[tr]+penalty,own[tr].T@y[tr])
    weights=np.zeros((aug.shape[1],3));weights[:18]=small[:18];weights[-1]=small[-1]
    model=dict(base,kind='ridge',weights=weights.tolist(),alpha=1,ablation='own_deck_only')
    candidates.append((float(np.mean((predict(model,x[va],'cpu')-y[va])**2)),model))
    # A small nonlinear challenger. Adam, fixed seed and validation stopping only.
    rng=np.random.default_rng(194);w1=rng.normal(0,.1,(x.shape[1],32)).astype(np.float32);b1=np.zeros(32,dtype=np.float32)
    w2=rng.normal(0,.1,(32,3)).astype(np.float32);b2=y[tr].mean(axis=0).copy()
    params=[w1,b1,w2,b2];m=[np.zeros_like(p) for p in params];v=[np.zeros_like(p) for p in params]
    best=float('inf');best_model=None;patience=0
    for step in range(1,301):
        h=np.maximum(0,z[tr]@w1+b1);output=h@w2+b2;dy=2*(output-y[tr])/y[tr].size
        dh=(dy@w2.T)*(h>0)
        gradients=[z[tr].T@dh+.001*w1,dh.sum(axis=0),h.T@dy+.001*w2,dy.sum(axis=0)]
        for i,(p,g) in enumerate(zip(params,gradients)):
            m[i]=.9*m[i]+.1*g;v[i]=.999*v[i]+.001*g*g
            p-=.005*(m[i]/(1-.9**step))/(np.sqrt(v[i]/(1-.999**step))+1e-8)
        if step%10==0:
            model=dict(base,kind='mlp',w1=w1.tolist(),b1=b1.tolist(),w2=w2.tolist(),b2=b2.tolist())
            loss=float(np.mean((predict(model,x[va],'cpu')-y[va])**2))
            if loss<best-1e-5:best=loss;best_model=model;patience=0
            else:patience+=1
            if patience>=8:break
    candidates.append((best,best_model));_,chosen=min(candidates,key=lambda a:a[0])
    intercept=np.broadcast_to(y[tr].mean(axis=0),y[te].shape)
    # Rule baseline uses pregame deck features only, never observations from a test game.
    rule=np.column_stack([np.clip(.35+1.5*x[te,4]+.3*x[te,9],0,1),np.clip(.2+x[te,4]+.3*x[te,9],0,1),np.clip(x[te,10]*4,0,1)])
    losses={'mean_baseline':np.mean((intercept-y[te])**2,axis=1),'rule_baseline':np.mean((rule-y[te])**2,axis=1)}
    prediction=predict(chosen,x[te],'cpu');candidate_loss=np.mean((prediction-y[te])**2,axis=1)
    baseline_name=min(losses,key=lambda k:float(losses[k].mean()));delta=candidate_loss-losses[baseline_name]
    clustered=defaultdict(list);source_losses=defaultdict(list)
    for i,diff in zip(te,delta):
        clustered[groups[i]].append(float(diff));source_losses[units[i]].append(float(diff))
    # Tables from one related pool family are not independent test sources.
    # Do not print a zero-width "confidence" interval for a single source.
    interval=None
    if len(source_losses)>=3:
        values=np.array([np.mean(v) for v in source_losses.values()]);rng=np.random.default_rng(195)
        boot=np.mean(rng.choice(values,size=(2000,len(values)),replace=True),axis=1);interval=np.quantile(boot,[.025,.975]).tolist()
    test_sources=len({units[i] for i in te});report['test_independent_sources']=test_sources
    enough=data['games']>=500 and len(set(groups))>=100 and len(clustered)>=20 and method=='cube_family_and_deck_group' and test_sources>=3
    improvement=1-float(candidate_loss.mean())/max(1e-9,float(losses[baseline_name].mean()))
    activity_candidate=float(np.mean((prediction[:,0]-y[te,0])**2))
    activity_baseline=min(float(np.mean((intercept[:,0]-y[te,0])**2)),float(np.mean((rule[:,0]-y[te,0])**2)))
    accepted=bool(data.get('engine') and enough and interval is not None and interval[1]<0 and improvement>=.03 and activity_candidate<activity_baseline)
    chosen.update(id=root.name,active=accepted,source_games=data['games'],training_dataset=hashlib.sha256(x.tobytes()+y.tobytes()).hexdigest())
    report.update(status='accepted' if accepted else 'diagnostic',active=accepted,model_kind=chosen['kind'],split=method,
        split_groups={k:len({groups[i] for i in ix}) for k,ix in indices.items()},
        validation_candidates=[dict(kind=m['kind'],alpha=m.get('alpha'),ablation=m.get('ablation'),mse=loss) for loss,m in candidates],
        test_mse=dict({k:float(v.mean()) for k,v in losses.items()},candidate=float(candidate_loss.mean())),
        relative_improvement=improvement,source_bootstrap95_loss_difference=interval,enough_data=enough,
        activity_mse=dict(candidate=activity_candidate,baseline=activity_baseline),
        adoption='至少500局、100组独立牌组、20组测试牌组及3个独立测试来源；相近Cube和重复单副牌不跨拆分；优于最强简单基准至少3%，按来源重抽样的损失差95%区间上限小于0',
        seconds=time.perf_counter()-started)
    (root/'model.json').write_text(json.dumps(chosen,ensure_ascii=False),encoding='utf8')
    (root/'split.json').write_text(json.dumps(dict(groups=groups,cubes=data['cubes'],families=data['families'],units=units,assignment=labels,sources=data['sources']),ensure_ascii=False),encoding='utf8')
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    if accepted:
        temp=MODELS/'active.tmp';temp.write_text(json.dumps(chosen,ensure_ascii=False),encoding='utf8');temp.replace(MODELS/'active.json')
    return report

def active_model(catalog):
    try:
        model=json.loads((MODELS/'active.json').read_text(encoding='utf8'))
        if not isinstance(model,dict):return None
        if not model.get('active') or model.get('version')!=VERSION or model.get('catalog')!=catalog.signature:return None
        scope=engine_scope()
        if scope is None or model.get('engine')!=scope:return None
        if model.get('kind') not in {'ridge','mlp'}:return None
        shapes=dict(mean=(54,),scale=(54,))
        shapes.update(dict(weights=(55,3)) if model.get('kind')=='ridge' else dict(w1=(54,32),b1=(32,),w2=(32,3),b2=(3,)))
        for k,shape in shapes.items():
            a=np.asarray(model[k],dtype=float)
            if a.shape!=shape or not np.isfinite(a).all():return None
        if (np.asarray(model['scale'])<=0).any():return None
        return model
    except (OSError,ValueError,TypeError,KeyError):return None

def status(catalog):
    reports=sorted(MODELS.glob('*/report.json'),reverse=True);scope=engine_scope()
    latest=None;historical=None
    # A task started before an update can finish afterwards. Its legacy report
    # must not hide a current-version report or imply the active model is stale.
    for path in reports[:30]:
        try:record=json.loads(path.read_text(encoding='utf8'))
        except (OSError,ValueError):continue
        if not isinstance(record,dict):continue
        if historical is None:historical=record
        if (record.get('version')==VERSION and scope is not None and record.get('engine')==scope
            and record.get('catalog')==catalog.signature):latest=record;break
    latest=latest or historical
    model=active_model(catalog)
    return dict(version=VERSION,active=bool(model),active_id=model.get('id') if model else None,latest=latest,
                engine=scope,latest_compatible=bool(latest and latest.get('version')==VERSION and scope is not None
                    and latest.get('engine')==scope and latest.get('catalog')==catalog.signature))
