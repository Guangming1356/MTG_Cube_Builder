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
VERSION='activity-2'
_training_lock=threading.Lock()

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
    from .forge import MATCHES
    from .optimize import game_trace
    x=[];y=[];groups=[];cubes=[];seen=set();games=0;sources=[]
    for path in sorted(MATCHES.glob('*/report.json')):
        try:
            r=json.loads(path.read_text(encoding='utf8'));tables={p['pod']:p for p in r['tables']}
            for game in r['games']:
                if game['outcome'] not in {'win','draw'} or game.get('cache_hit'):continue
                decks=tables[game['pod']]['decks']
                if not all(d.get('buildable') for d in decks):continue
                identities={d['id']:fingerprint(d) for d in decks}
                group=hashlib.sha256(json.dumps(sorted(identities.values())).encode()).hexdigest()
                unique=(r['engine'].get('jar_sha256'),tuple(identities[n] for n in game['order']),game['seed'])
                if unique in seen:continue
                trace=game_trace(catalog,(path.parent/game['log']).read_text(encoding='utf8'),decks)
                features=contexts([deck_vector(catalog,d) for d in decks])
                labels=[]
                for d in decks:
                    p=trace['players'][d['id']]
                    if not p['early_turns']:raise ValueError('没有可用行动记录')
                    labels.append([1-p['no_spell_first4_rate'],min(1,p['spellcasts']/max(1,p['own_turns']*1.5)),float(p['finisher_casts']>0)])
                seen.add(unique);games+=1;x.extend(features);y.extend(labels)
                groups.extend([group]*3);cubes.extend([r['cube_sha256']]*3)
            sources.append(r['match_id'])
        except (KeyError,ValueError,OSError,TypeError):continue
    return dict(x=np.asarray(x,dtype=np.float32),y=np.asarray(y,dtype=np.float32),groups=groups,cubes=cubes,games=games,sources=sources)

def split_groups(groups,cubes):
    """Keep both related decks and entire Cube versions out of training when possible."""
    parent={c:c for c in cubes};owners={}
    def find(c):
        while parent[c]!=c:parent[c]=parent[parent[c]];c=parent[c]
        return c
    for group,cube in zip(groups,cubes):
        if group in owners:parent[find(cube)]=find(owners[group])
        else:owners[group]=cube
    components=[find(c) for c in cubes]
    rng=np.random.default_rng(193);unique=sorted(set(components))
    if len(unique)>=5:
        rng.shuffle(unique);a=max(1,len(unique)//5);test=set(unique[:a]);val=set(unique[a:2*a])
        return ['test' if c in test else 'validation' if c in val else 'train' for c in components],'cube_and_deck_group'
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
        status='insufficient_data',active=False,targets=['前四回合施放活动','每回合施放密度','本局施放过终结牌'],
        limitation='学习 Forge 原生 AI 的可观测行为，不预测人类娱乐性或认证牌力。没有把一副牌的胜负分摊到单卡。')
    if len(set(groups))<10:
        report['reason']='独立轮抓牌组不足10组；保留固定评分，继续积累实战'
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        return report
    labels,method=split_groups(groups,data['cubes']);indices={k:np.where(np.array(labels)==k)[0] for k in ['train','validation','test']}
    if any(len(v)<3 for v in indices.values()):
        report['reason']='分组后训练或保留数据不足';(root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return report
    tr,va,te=[indices[k] for k in ['train','validation','test']]
    mean=x[tr].mean(axis=0);scale=x[tr].std(axis=0);scale[scale<.001]=1
    z=(x-mean)/scale;aug=np.column_stack([z,np.ones(len(z),dtype=np.float32)])
    base=dict(version=VERSION,mean=mean.tolist(),scale=scale.tolist(),catalog=catalog.signature)
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
    clustered=defaultdict(list)
    for i,diff in zip(te,delta):clustered[groups[i]].append(float(diff))
    values=np.array([np.mean(v) for v in clustered.values()]);rng=np.random.default_rng(195)
    boot=np.mean(rng.choice(values,size=(2000,len(values)),replace=True),axis=1);interval=np.quantile(boot,[.025,.975]).tolist()
    enough=data['games']>=500 and len(set(groups))>=100 and len(clustered)>=20 and method=='cube_and_deck_group'
    improvement=1-float(candidate_loss.mean())/max(1e-9,float(losses[baseline_name].mean()))
    activity_candidate=float(np.mean((prediction[:,0]-y[te,0])**2))
    activity_baseline=min(float(np.mean((intercept[:,0]-y[te,0])**2)),float(np.mean((rule[:,0]-y[te,0])**2)))
    accepted=bool(enough and interval[1]<0 and improvement>=.03 and activity_candidate<activity_baseline)
    chosen.update(id=root.name,active=accepted,source_games=data['games'],training_dataset=hashlib.sha256(x.tobytes()+y.tobytes()).hexdigest())
    report.update(status='accepted' if accepted else 'diagnostic',active=accepted,model_kind=chosen['kind'],split=method,
        split_groups={k:len({groups[i] for i in ix}) for k,ix in indices.items()},
        validation_candidates=[dict(kind=m['kind'],alpha=m.get('alpha'),ablation=m.get('ablation'),mse=loss) for loss,m in candidates],
        test_mse=dict({k:float(v.mean()) for k,v in losses.items()},candidate=float(candidate_loss.mean())),
        relative_improvement=improvement,pod_bootstrap95_loss_difference=interval,enough_data=enough,
        activity_mse=dict(candidate=activity_candidate,baseline=activity_baseline),
        adoption='至少500局、100组独立牌组、20组测试牌组，整Cube及牌组分组保留；优于最强简单基准至少3%，损失差95%区间上限小于0',
        seconds=time.perf_counter()-started)
    (root/'model.json').write_text(json.dumps(chosen,ensure_ascii=False),encoding='utf8')
    (root/'split.json').write_text(json.dumps(dict(groups=groups,cubes=data['cubes'],assignment=labels,sources=data['sources']),ensure_ascii=False),encoding='utf8')
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    if accepted:
        temp=MODELS/'active.tmp';temp.write_text(json.dumps(chosen,ensure_ascii=False),encoding='utf8');temp.replace(MODELS/'active.json')
    return report

def active_model(catalog):
    try:
        model=json.loads((MODELS/'active.json').read_text(encoding='utf8'))
        if not isinstance(model,dict):return None
        if not model.get('active') or model.get('version')!=VERSION or model.get('catalog')!=catalog.signature:return None
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
    reports=sorted(MODELS.glob('*/report.json'),reverse=True)
    try:latest=json.loads(reports[0].read_text(encoding='utf8')) if reports else None
    except (OSError,ValueError):latest=None
    if not isinstance(latest,dict):latest=None
    model=active_model(catalog)
    return dict(active=bool(model),active_id=model.get('id') if model else None,latest=latest)
