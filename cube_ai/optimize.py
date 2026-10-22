"""Evidence-led Cube revisions using drafted decks and native Forge game traces."""
import csv
import hashlib
import json
import math
import random
import re
import statistics
import uuid
import zipfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .catalog import exclusion_reasons
from .config import ROOT, GUILDS, BuildSpec
from .draft import draft_pod
from .engine import audit, completes_combo, export_run
from .features import VERSION
from .forge import card_index, configuration, engine_name, run_battle, simulate, write_deck, forge_session, evidence_files,campaign_resources
from .design import design_bonus, deck_design_report, package_roles
from .experiment import experiment_budget, execution_resources
from .performance import Timings

OPTIMIZATIONS=ROOT/'optimizations'
POLICY_VERSION='forge-feedback-1.5'
_eligible_cache={}
# Sparse self-play cannot justify cutting these efficient, broadly useful spells.
# This expert guard is versioned policy, not invented training labels.
CORE_GUARD={'Brainstorm','Ponder','Frantic Search','Deadly Rollick','Marionette Apprentice',
    "Caretaker's Talent",'Trouble in Pairs'}

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def schedule(pods,seed):
    return [seed+i*100 for i in range(pods)],[[GUILDS[(p*3+j)%10] for j in range(3)] for p in range(pods)]

def deck_metrics(catalog,deck):
    if not deck['buildable']:return dict(strength=0,buildable=False)
    cards=[catalog.cards[n] for n in deck['spells']]
    counts={f:sum(c[f] for c in cards) for f in ['creature','interaction','wipe','ramp','draw','finisher']}
    counts.update(low=sum(c['mv']<=2 for c in cards),expensive=sum(c['mv']>=6 for c in cards),
        spells=len(cards),lands=deck['land_count'],mean_mv=round(statistics.mean(c['mv'] for c in cards),3) if cards else 0,
        mean_quality=round(statistics.mean(c['quality'] for c in cards),3) if cards else 0)
    # A transparent structural utility, not a predicted game-win probability.
    parts=dict(low=min(1,counts['low']/14),interaction=min(1,counts['interaction']/7),
        draw=min(1,counts['draw']/6),finisher=min(1,counts['finisher']/3),
        creature=min(1,counts['creature']/16),quality=min(1,max(0,(counts['mean_quality']-2)/1.65)))
    weights=dict(low=.24,interaction=.22,draw=.13,finisher=.18,creature=.10,quality=.13)
    value=sum(parts[k]*v for k,v in weights.items())
    value-=min(.3,max(0,counts['lands']-28)*.025)
    return dict(buildable=True,identity=deck['identity'],preferred=deck['guild'],commander=deck['commander'],
        strength=round(value,6),components=parts,design=deck_design_report(catalog,deck),bracket=deck.get('bracket'),**counts)

def _pod_metrics(catalog,pod):
    metrics=[];counts=defaultdict(Counter)
    for d in pod['decks']:
        metrics.append(dict(seat=d['seat'],**deck_metrics(catalog,d)))
        used=set(d.get('spells',[])+d.get('lands',[])+([d['commander']] if d.get('commander') else []))
        for n in d['drafted']:
            c=catalog.cards[n];stat=counts[n];stat['drafted']+=1
            if d['buildable'] and (c['identity']=='C' or set(c['identity'])<=set(d['identity'])):
                stat['eligible_pool']+=1
                if n in used:stat['included']+=1
    return metrics,counts


def draft_evaluation(catalog,rows,spec,seeds,guilds,include_tables=False,learned=None,workspace=None):
    from .sim_cache import draft as cached_draft
    if len(seeds)!=len(guilds) or not seeds:raise ValueError('轮抓种子与色组安排需非空且长度相同')
    started=time.perf_counter();observations=[];tables=[];card_counts=defaultdict(Counter);cache_hits=0
    need_tables=include_tables or bool(learned and learned.get('active'))
    for p,(seed,prefs) in enumerate(zip(seeds,guilds)):
        from .task_control import checkpoint
        checkpoint()
        if workspace:
            (original,(metrics,counts)),hit=workspace.table(catalog,rows,spec,seed,prefs,lambda pod:_pod_metrics(catalog,pod))
            pod=dict(original) if need_tables else original
        else:
            pod,hit=cached_draft(catalog,rows,spec,seed,prefs);metrics,counts=_pod_metrics(catalog,pod)
        cache_hits+=hit
        if need_tables:
            pod=dict(pod,pod=p,draft_seed=seed);tables.append(pod)
        observations.extend(dict(pod=p,**m) for m in metrics)
        for n,stat in counts.items():card_counts[n].update(stat)
    values=[m['strength'] for m in observations]
    groups={}
    for g in GUILDS:
        own=[m for m in observations if m.get('preferred')==g or not m['buildable'] and guilds[m['pod']][m['seat']]==g]
        groups[g]=dict(decks=len(own),mean_strength=round(statistics.mean(m['strength'] for m in own),6) if own else None,
            buildable_rate=round(sum(m['buildable'] for m in own)/len(own),3) if own else None)
    report=dict(pods=len(seeds),seeds=seeds,guild_schedule=guilds,decks=len(observations),
        bracket_check=dict(target=spec.bracket,decks_checked=sum(bool(m.get('bracket')) for m in observations),
            violations=sum(bool(m.get('bracket',{}).get('violations')) for m in observations if m.get('bracket')),certified=False),
        buildable_rate=sum(m['buildable'] for m in observations)/max(1,len(observations)),
        mean_strength=float(np.mean(values)),p10_strength=float(np.quantile(values,.1)),
        guild_gap=max(v['mean_strength'] for v in groups.values() if v['mean_strength'] is not None)-min(v['mean_strength'] for v in groups.values() if v['mean_strength'] is not None),
        guilds=groups,observations=observations,cards={n:dict(c) for n,c in sorted(card_counts.items())},
        limitation='牌组强度为可解释结构指标：低费、互动、抓牌、终结、生物和原始启发式牌力。不是实战胜率，固定机器人会产生选牌偏差。')
    if include_tables:report['tables']=tables
    if learned and learned.get('active'):
        from .surrogate import predict_tables
        predicted=predict_tables(catalog,tables,learned)
        if predicted is not None:
            report['mean_predicted_activity']=float(np.mean(predicted));report['learned_model_id']=learned['id']
    report['execution']=dict(cache_hits=cache_hits,cache_misses=len(seeds)-cache_hits,opening_hand_sampling=False,
        incremental=workspace is not None,wall_seconds=round(time.perf_counter()-started,6))
    return report

def iter_log_events(log):
    """Stream events without copying every remaining suffix of a large log."""
    text=log.replace('\r\n','\n')
    previous=None
    for match in re.finditer(r'^(?:Turn|Phase|Land|Add To Stack|Resolve Stack|Combat|Damage|Life|Mulligan|Game Outcome|Match Result|Game Result):',text,re.M):
        if previous is not None and not text.startswith(('Match Result:','Game Result:'),previous):
            yield text[previous:match.start()].strip().replace('\n','')
        previous=match.start()
    if previous is not None and not text.startswith(('Match Result:','Game Result:'),previous):
        yield text[previous:].strip().replace('\n','')


def log_events(log):
    """Compatibility list for trace fingerprints and stored evidence."""
    return list(iter_log_events(log))

def game_trace(catalog,log,decks,*,extended=False):
    from .forge_card_names import trace_name_pairs
    native_names=dict(trace_name_pairs())
    cards={};players={};active=None
    for d in decks:
        players[d['id']]=dict(own_turns=0,turn_spells=[],casts=Counter(),activations=Counter(),
            spellcasts=0,first_spell_turn=None,damage_taken=0,loss_reason=None)
        if extended:
            players[d['id']].update(cycle_spells=[],cycle_activations=[],cycle_attacks=[],early_offturn_casts=0)
        for n in d['spells']+[d['commander']]:
            c=catalog.cards[n]
            cards[n.split(' // ')[0]]=n
            if ' // ' in n:cards[n.split(' // ')[1]]=n
            for face in n.split(' // '):
                if primary:=native_names.get(face):cards.setdefault(primary,n)
    card_prefixes=sorted(cards.items(),key=lambda x:-len(x[0]))
    def name_of(text):
        if text in cards:return cards[text]
        return next((name for prefix,name in card_prefixes if text.startswith(prefix+' targeting') or text.startswith(prefix+' (')),None)
    for event in iter_log_events(log):
        turn=re.match(r'Turn: Turn (\d+) \(Ai\(\d+\)-([^\)]+)\)',event)
        if turn:
            active=turn[2]
            if active in players:
                players[active]['own_turns']+=1;players[active]['turn_spells'].append(0)
                if extended:
                    for key in ['cycle_spells','cycle_activations','cycle_attacks']:players[active][key].append(0)
            continue
        cast=re.match(r'Add To Stack: Ai\(\d+\)-(\S+) cast (.+)',event)
        if cast and cast[1] in players:
            p=players[cast[1]];n=name_of(cast[2]);p['spellcasts']+=1
            if n:p['casts'][n]+=1
            if cast[1]==active and p['turn_spells']:p['turn_spells'][-1]+=1
            if extended and p['cycle_spells']:
                p['cycle_spells'][-1]+=1
                if cast[1]!=active and p['own_turns']<=4:p['early_offturn_casts']+=1
            if p['first_spell_turn'] is None and cast[1]==active:p['first_spell_turn']=p['own_turns']
        ability=re.match(r'Add To Stack: Ai\(\d+\)-(\S+) (activated|triggered) (.+)',event)
        if ability and ability[1] in players:
            n=name_of(ability[3])
            if n:players[ability[1]]['activations'][n]+=1
            if extended and ability[2]=='activated' and players[ability[1]]['cycle_activations']:
                players[ability[1]]['cycle_activations'][-1]+=1
        if extended:
            attack=re.match(r'Combat: Ai\(\d+\)-(\S+) assigned .+ to attack ',event)
            if attack and attack[1] in players and players[attack[1]]['cycle_attacks']:
                players[attack[1]]['cycle_attacks'][-1]+=1
        damage=re.search(r'Damage: .+ deals (\d+) (?:combat )?damage to Ai\(\d+\)-(\S+)\.',event)
        if damage and damage[2] in players:players[damage[2]]['damage_taken']+=int(damage[1])
        loss=re.match(r'Game Outcome: Ai\(\d+\)-(\S+) has lost because (.+)',event)
        if loss and loss[1] in players:players[loss[1]]['loss_reason']=loss[2]
    for p in players.values():
        first=p['turn_spells'][:4]
        p['early_turns']=len(first);p['early_spell_turns']=sum(x>0 for x in first)
        p['no_spell_first4_rate']=sum(x==0 for x in first)/max(1,len(first))
        p['finisher_casts']=sum(count for n,count in p['casts'].items() if catalog.cards[n]['finisher'])
        p['interaction_casts']=sum(count for n,count in p['casts'].items() if catalog.cards[n]['interaction'])
        p['casts']=dict(p['casts']);p['activations']=dict(p['activations'])
        if extended:
            # A player's last interval is right-censored at game end. Four
            # complete cycles require observing the start of their fifth turn.
            count=min(4,max(0,p['own_turns']-1));p['complete_early_cycles']=count
            p['no_spell_cycle_rate']=sum(x==0 for x in p['cycle_spells'][:count])/count if count else None
            actions=[sum(values) for values in zip(p['cycle_spells'][:count],p['cycle_activations'][:count],p['cycle_attacks'][:count])]
            p['no_action_cycle_rate']=sum(x==0 for x in actions)/count if count else None
    result=dict(players=players,ai_missing_apis=sorted(set(re.findall(r'No AI assigned for API: (\w+)',log))),
        limitation='前四个自己的回合只统计实际施放咒语；零施放不等于卡手，保留互动或发动异能也可能是正确策略。未记录手牌，未施放牌不能当作抽到的死牌。')
    if extended:
        result.update(activity_version='completed-player-cycles-1',
            activity_definition='从自己的回合开始，到自己的下一回合开始为一个周期；计入期间任意回合施放、主动异能和宣攻，排除自动触发、下地及未完整观察的最后周期。零行动不能证明卡手，未记录手牌。')
    return result

def evidence_from_match(catalog,result):
    out=Path(result['path']);tables={p['pod']:p for p in result['tables']};traces=[];card_stats=defaultdict(Counter)
    for r in result['games']:
        if r['outcome'] not in {'win','draw'}:continue
        trace=game_trace(catalog,(out/r['log']).read_text(encoding='utf-8'),tables[r['pod']]['decks'],extended=True)
        traces.append(dict(pod=r['pod'],game=r['game'],winner=r['winner'],turns=r['turns'],**trace))
        for d in tables[r['pod']]['decks']:
            p=trace['players'][d['id']]
            for n in d['spells']+[d['commander']]:
                c=card_stats[n];c['deck_games']+=1;c['cast_games']+=int(p['casts'].get(n,0)>0)
                c['casts']+=p['casts'].get(n,0);c['ability_events']+=p['activations'].get(n,0)
    normal=result['summary']['completed'];all_players=[p for t in traces for p in t['players'].values()]
    full_cycles=[p for p in all_players if p['complete_early_cycles']==4]
    summary=dict(completed=normal,attempted=result['summary']['games'],skipped_pods=result['skipped_pods'],
        completed_draft_pods=result['summary'].get('completed_draft_pods',0),
        independent_pods_by_guild=result['summary'].get('independent_pods_by_guild',{}),
        failure_rate=1-normal/max(1,result['summary']['games']),
        mean_early_no_spell_rate=statistics.mean(p['no_spell_first4_rate'] for p in all_players) if all_players else None,
        mean_early_no_action_rate=statistics.mean(p['no_action_cycle_rate'] for p in full_cycles) if full_cycles else None,
        complete_cycle_coverage=len(full_cycles)/len(all_players) if all_players else None,
        no_finisher_cast_rate=statistics.mean(p['finisher_casts']==0 for p in all_players) if all_players else None,
        deckout_rate=statistics.mean('draw a card' in (p['loss_reason'] or '') or 'library' in (p['loss_reason'] or '').lower() for p in all_players) if all_players else None,
        median_global_turns=statistics.median(t['turns'] for t in traces) if traces else None)
    return dict(match_id=result['match_id'],summary=summary,traces=traces,
        cards={n:dict(v) for n,v in sorted(card_stats.items())},guilds=result['summary']['guilds'])

def collect_training(catalog,rows,spec,out,pods=30,workers=0,clock=120,progress=print,experiment_seed=None,budget=None):
    from .surrogate import active_model
    learned=active_model(catalog)
    seed=spec.seed if experiment_seed is None else experiment_seed
    budget=budget or experiment_budget(training_pods=pods,cube_size=len(rows))
    requested_workers=workers
    resources=campaign_resources(workers);workers=resources['workers']
    holdout=budget['holdout_pods']
    seeds,guilds=schedule(pods,seed+1000)
    # Independent development and held-out schedules are declared before card selection.
    protocol=dict(owner='用户的 Cube 构筑任务',policy_version=POLICY_VERSION,
        experiment_seed=seed,budget=budget,resources=resources,learned_model=learned,train_seeds=seeds,train_guilds=guilds,
        holdout_seeds=schedule(holdout,seed+2000000)[0],holdout_guilds=schedule(holdout,seed+2000000)[1],
        ranking_seeds=schedule(budget['ranking_pods'],seed+1000000)[0],ranking_guilds=schedule(budget['ranking_pods'],seed+1000000)[1],
        structural_holdout_seeds=schedule(budget['structural_pods'],seed+3000000)[0],structural_holdout_guilds=schedule(budget['structural_pods'],seed+3000000)[1],
        max_swaps=budget['max_swaps'],max_evaluated_alternatives=budget['alternatives'],game_workers=workers,
        requested_game_workers=requested_workers,clock_seconds=clock,
        search=dict(version='screen-1',mode='full',batch_size=8,patience=3,stages=sorted({10,30,budget['ranking_pods']})),
        cross_strategy='每个发生牌组变化的独立轮抓席位：旧牌组、新牌组、旧桌下一席位锚牌组；三局轮换座位；种子=对应保留桌种子+50000+席位*100+局序号',
        adoption='结构均值与低分位改善、色组差不扩大、所有硬约束通过；实战用于确认正常终结、行为节奏及回归。少量实战不宣称统计显著牌力提升。',
        risks=['原生 AI 驾驶偏差','同桌三局相关','启发式语义标签可能错误','结构强度不是胜率','未施放不等于抽到但不能用'])
    save(out/'protocol.json',protocol);save(out/'base_cube.json',dict(cards=rows,spec=spec.to_dict()))
    progress(f'收集训练：{pods} 桌 / {pods*3} 局，最多同时 {workers} 局；另做开发轮抓')
    # CPU drafting runs while native JVMs play. Selection waits for both datasets.
    timing=Timings(out/'timings.json')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(timing.call,'development_drafts',draft_evaluation,catalog,rows,spec,protocol['ranking_seeds'],protocol['ranking_guilds'],learned=learned)
        match=timing.call('training_forge',simulate,catalog,rows,spec,pods,3,clock,progress,pod_seeds=seeds,preferred_guilds=guilds,workers=requested_workers)
        offline=pending.result()
    evidence=timing.call('training_trace_analysis',evidence_from_match,catalog,match)
    save(out/'training_match.json',match);save(out/'training_evidence.json',evidence)
    save(out/'training_drafts.json',offline)
    return protocol,match,evidence,offline

def opponent_gift(card):
    return bool(re.search(r'each opponent may search their library for a creature card and put it onto the battlefield|(?:target|an|each) opponent creates|any player may sacrifice a land',card['text'],re.I))

def unsupported_cost(card):
    return bool(re.search(r'\b(?:full party|number of creatures in your party)\b|when [^.]* enters, (?:you )?(?:discard a card|sacrifice (?:a|an|another) creature)',card['text'],re.I))

def feedback_model(catalog,evidence,drafts):
    """Small, bounded feedback weights; no card receives its deck's win as a label."""
    summary=evidence['summary']
    # New traces include offturn instants and deliberate abilities. Historical
    # evidence retains its explicit legacy definition instead of fabricating it.
    cycle_metric=summary.get('mean_early_no_action_rate')
    use_cycles=cycle_metric is not None and (summary.get('complete_cycle_coverage') or 0)>=.9
    early=cycle_metric if use_cycles else (summary['mean_early_no_spell_rate'] or 0)
    finisher=evidence['summary']['no_finisher_cast_rate'] or 0
    needs={}
    for g in GUILDS:
        decks=[x for x in drafts['observations'] if x.get('preferred')==g and x['buildable']]
        observed=evidence['guilds'].get(g,{})
        games=observed.get('appearances',0);wins=observed.get('wins',0)
        # Prior: three wins per nine observations; sparse group wins have little influence.
        posterior=(wins+3)/(games+9)
        pressure=max(.85,min(1.15,1+(1/3-posterior)*.6))
        needs[g]={k:statistics.mean(max(0,1-d['components'][k]) for d in decks) if decks else 0 for k in ['low','interaction','draw','finisher','creature']}
        needs[g]['pressure']=pressure;needs[g]['observed_games']=games;needs[g]['posterior_win']=posterior
        needs[g]['package_gaps']={}
        for package in ['sacrifice','reanimator']:
            for component in (['fodder','outlet','reward'] if package=='sacrifice' else ['entry','return','target']):
                key=package+':'+component
                needs[g]['package_gaps'][key]=statistics.mean(component in d.get('design',{}).get('packages',{}).get(package,{}).get('missing',[]) for d in decks) if decks else 0
    return dict(version=POLICY_VERSION,early_no_spell=early,early_activity_metric='completed_cycle_no_action' if use_cycles else 'legacy_own_turn_no_spell',finisher_uncast=finisher,guilds=needs,
        low_weight=.15+.35*early,finisher_weight=.12+.25*finisher,
        note='权重来自整副牌的缺口与真实行为；胜率仅做收缩后的弱压力信号。未施放牌不扣分，未知牌不伪造样本。')

def utility(card,model,game_stats=None,spec=None):
    available=[g for g in GUILDS if card['identity']=='C' or set(card['identity'])<=set(g)]
    role=sum(model['guilds'][g]['pressure']*(
        model['low_weight']*(card['mv']<=2)*(1+model['guilds'][g]['low'])+
        .18*card['interaction']*(1+model['guilds'][g]['interaction'])+
        .10*card['draw']*(1+model['guilds'][g]['draw'])+
        model['finisher_weight']*card['finisher']*(1+model['guilds'][g]['finisher'])+
        .08*card['creature']*(1+model['guilds'][g]['creature'])) for g in available)/max(1,len(available))
    observed=game_stats or {}
    # Positive evidence only: no negative inference about unseen cards or undrawn hands.
    use=.06*observed.get('cast_games',0)/(observed.get('deck_games',0)+8)
    components=package_roles(card)
    support=sum(model['guilds'][g].get('package_gaps',{}).get(p+':'+k,0)*components[p]['return_' if k=='return' else k]
        for g in available for p,keys in {'sacrifice':['fodder','outlet','reward'],'reanimator':['entry','return','target']}.items() for k in keys)/max(1,len(available))
    from .brackets import score_adjustment
    return card['quality']+role+use+min(.06,.03*support)+(design_bonus(card,spec)+score_adjustment(card,spec) if spec else 0)-.9*opponent_gift(card)

def objective(report):
    return .40*report['mean_strength']+.40*report['p10_strength']-.20*report['guild_gap']+.02*report.get('mean_predicted_activity',0)

def propose_revision(catalog,rows,spec,protocol,evidence,drafts,progress=print):
    config=configuration();index=card_index(config)
    model=feedback_model(catalog,evidence,drafts)
    present={r['name'] for r in rows};pins={catalog.resolve(n) for n in spec.pins}
    criteria=spec.to_dict();criteria.pop('seed',None);criteria.pop('name',None)
    eligibility_key=(catalog.signature,json.dumps(criteria,sort_keys=True),config.get('jar_sha256'),config['home'])
    if eligibility_key not in _eligible_cache:
        if len(_eligible_cache)>=4:_eligible_cache.clear()
        _eligible_cache[eligibility_key]=[c['name'] for c in catalog.cards.values() if not exclusion_reasons(c,spec) and engine_name(c['name'],index)]
    eligible=[catalog.cards[n] for n in _eligible_cache[eligibility_key]]
    from .candidate_scoring import batch_utility
    scores,scoring=batch_utility(eligible,model,spec,opponent_gift,protocol.get('scoring_backend','auto'))
    def score(c,observed=False):
        value=scores.get(c['name'])
        if value is None:return utility(c,model,evidence['cards'].get(c['name']) if observed else None,spec=spec)
        if observed:
            stats=evidence['cards'].get(c['name'],{})
            value+=.06*stats.get('cast_games',0)/(stats.get('deck_games',0)+8)
        return value
    by_slot=defaultdict(list)
    for c in eligible:
        if c['kind']=='land' or c['name'] in present or opponent_gift(c) or unsupported_cost(c):continue
        by_slot[(c['identity'],c['bucket'],c['mv']>=6)].append(c)
    for pool in by_slot.values():pool.sort(key=lambda c:(-score(c),c['name']))
    ranked=[]
    for i,row in enumerate(rows):
        old=catalog.cards[row['name']];stat=drafts['cards'].get(old['name'],{})
        if old['name'] in pins or old['name'] in CORE_GUARD or row['role']=='Land':continue
        if row['role']=='Commander':
            if engine_name(old['name'],index):continue
            options=sorted([c for c in eligible if c['commander'] and c['identity']==old['identity'] and c['name'] not in present],key=lambda c:-score(c))[:5]
            priority=4
        else:
            exposures=stat.get('eligible_pool',0)
            if exposures<12:continue
            inclusion=(stat.get('included',0)+3)/(exposures+6)
            # Preserve political engines and the existing well-calibrated core.
            if re.search(r'\bmonarch\b|\binitiative\b',old['text'],re.I):continue
            priority=(1-inclusion)+max(0,3.65-old['quality'])*.45+.8*opponent_gift(old)
            pool=by_slot[(old['identity'],old['bucket'],old['mv']>=6)]
            # Rank cheap candidates first. Audit only when the search reaches a
            # candidate; infeasible ones do not consume its evaluation budget.
            # This avoids thousands of full-cube audits for cards never evaluated.
            options=[c for c in pool if c['creature']==old['creature']]
        for c in options:
            if row['role']=='Main' and c['creature']!=old['creature']:continue
            improvement=score(c)-score(old,observed=True)
            if row['role']=='Main' and (improvement<-.4 or c['quality']<old['quality']-.45):continue
            ranked.append((priority+improvement*.75,i,c,improvement))
    ranked.sort(key=lambda x:(-x[0],x[1],x[2]['name']))
    # All candidates within a batch share one immutable base. Commit at most one,
    # then build the next batch against the updated base; no stale combinations.
    from .search import CandidateEvaluator
    candidate=[dict(r) for r in rows];changes=[];taken=set();considered=[]
    current=drafts;best_value=objective(current);attempts=Counter();cursor=0;tested=0;empty_batches=0
    started=time.perf_counter();search_policy=protocol.get('search',{})
    batch_size=search_policy.get('batch_size',8);patience=search_policy.get('patience',3)
    with CandidateEvaluator(catalog,spec,protocol['ranking_seeds'],protocol['ranking_guilds'],
            protocol.get('learned_model'),workers=search_policy.get('workers'),adaptive=search_policy.get('mode','full')=='adaptive') as evaluator:
        while len(changes)<protocol['max_swaps'] and tested<protocol.get('max_evaluated_alternatives',80):
            batch=[];present={r['name'] for r in candidate}
            while cursor<len(ranked) and len(batch)<batch_size and tested+len(batch)<protocol.get('max_evaluated_alternatives',80):
                if cursor%64==0:
                    from .task_control import checkpoint
                    checkpoint()
                _,i,c,gain=ranked[cursor];cursor+=1
                if i in taken or c['name'] in present or attempts[i]>=3:continue
                trial=[dict(r) for r in candidate];trial[i]['name']=c['name']
                if audit(catalog,trial,spec,strict=True)['hard_errors']:continue
                attempts[i]+=1
                batch.append(dict(index=i,rows=trial,remove=candidate[i]['name'],add=c['name'],gain=gain))
            if not batch:break
            tested+=len(batch)
            survivors,rejected=evaluator.screen(batch,candidate,progress);considered.extend(rejected)
            passing=[]
            for item in survivors:
                i=item['index'];old=catalog.cards[item['remove']];evaluated=item['evaluation'];value=objective(evaluated)
                supported=not engine_name(old['name'],index)
                group_changes={g:evaluated['guilds'][g]['mean_strength']-drafts['guilds'][g]['mean_strength'] for g in GUILDS}
                passes=(value>best_value+.000015 and evaluated['mean_strength']>=current['mean_strength']-.00015
                    and evaluated['p10_strength']>=current['p10_strength']-.0008
                    and evaluated['guild_gap']<=drafts['guild_gap']+.002 and min(group_changes.values())>=-.006
                    ) or (supported and value>=best_value-.0005)
                record=dict(remove=old['name'],add=item['add'],role=item['rows'][i]['role'],identity=old['identity'],
                    bucket=old['bucket'],draft_usage=drafts['cards'].get(old['name'],{}),forge_usage=evidence['cards'].get(old['name'],{}),
                    utility_gain=round(item['gain'],5),development_objective_before=round(best_value,6),
                    development_objective_after=round(value,6),stage_pods=len(protocol['ranking_seeds']),
                    accepted=False,passes_full_gate=passes,status='full_evaluation',
                    reason=('Forge 未实现，换为同色合规指挥官' if supported else
                        '实战行为与开发轮抓缺口筛选；完整开发集检查均值、弱牌组及色组均衡后采用'))
                considered.append(record)
                if passes:passing.append((value,item,record))
            if passing:
                passing.sort(key=lambda x:(-x[0],x[1]['index'],x[1]['add']))
                value,item,record=passing[0];record['accepted']=True
                candidate=item['rows'];current=item['evaluation'];best_value=value;taken.add(item['index']);changes.append(record)
                empty_batches=0;progress(f'采用替换 {item["remove"]} → {item["add"]}；共 {len(changes)} 张')
            else:empty_batches+=1
            if empty_batches>=patience:
                progress(f'连续 {patience} 批没有通过完整检查的改进，提前结束搜索');break
        search=dict(evaluator.stats,wall_seconds=round(time.perf_counter()-started,3),fallback=evaluator.fallback,
            stop_reason='no_improvement' if empty_batches>=patience else 'budget_or_candidates',
            approximate=search_policy.get('mode','full')=='adaptive',note='分轮筛选可能遗漏候选；只在完整开发集通过后采用。独立验收不参与选择。')
    if not changes:raise ValueError('训练数据下没有通过约束与开发集门槛的替换；未生成虚假改进')
    result=dict(cards=candidate,spec=spec.to_dict(),audit=audit(catalog,candidate,spec,strict=True),solver=None,
        changes=dict(removed=[r['remove'] for r in changes],added=[r['add'] for r in changes]),
        provenance=dict(snapshot=catalog.snapshot,catalog=catalog.signature,features=VERSION,source=POLICY_VERSION,
            feedback=model,scoring=scoring,training_match=evidence['match_id'],training_draft_seeds=protocol['ranking_seeds']))
    return result,dict(model=model,swaps=changes,considered=considered,training_before=drafts,training_after=current,search=search)

def paired_structural(before,after):
    a={(r['pod'],r['seat']):r['strength'] for r in before['observations']}
    b={(r['pod'],r['seat']):r['strength'] for r in after['observations']}
    diffs=np.array([b[k]-a[k] for k in sorted(a)])
    # Resample entire draft pods; decks from a table are dependent.
    by_pod=defaultdict(list)
    for k in a:by_pod[k[0]].append(b[k]-a[k])
    means=np.array([statistics.mean(v) for v in by_pod.values()]);rng=np.random.default_rng(781)
    bootstrap=np.array([np.mean(rng.choice(means,len(means),replace=True)) for _ in range(1000)])
    return dict(mean_difference=float(np.mean(diffs)),pod_bootstrap95=[float(x) for x in np.quantile(bootstrap,[.025,.975])],
        better=int(sum(diffs>1e-9)),equal=int(sum(abs(diffs)<=1e-9)),worse=int(sum(diffs< -1e-9)),
        mean_before=before['mean_strength'],mean_after=after['mean_strength'],p10_before=before['p10_strength'],p10_after=after['p10_strength'],
        gap_before=before['guild_gap'],gap_after=after['guild_gap'],
        guild_differences={g:after['guilds'][g]['mean_strength']-before['guilds'][g]['mean_strength'] for g in GUILDS})

def cross_cube(catalog,before,after,protocol,out,progress=print):
    """Matched old/new draft-seat decks face the same untouched third deck."""
    config=configuration();index=card_index(config);folder=out/'cross';folder.mkdir(exist_ok=True)
    decks_dir=folder/'decks';decks_dir.mkdir(exist_ok=True);fixtures=[];tasks=[];records=[]
    fingerprint=lambda d:json.dumps([d['commander'],sorted(d['spells']),sorted(d['lands']),d['basics']],sort_keys=True)
    for p,(a,b) in enumerate(zip(before['tables'],after['tables'])):
        for seat in range(3):
            old=a['decks'][seat];new=b['decks'][seat];anchor=a['decks'][(seat+1)%3]
            if fingerprint(old)==fingerprint(new):continue
            if not all(d['buildable'] and d.get('engine_supported') for d in [old,new,anchor]):continue
            n=len(fixtures);ids=[f'f{n:03d}_old',f'f{n:03d}_new',f'f{n:03d}_anchor']
            for deck,id_ in zip([old,new,anchor],ids):write_deck(deck,decks_dir/(id_+'.dck'),index,catalog)
            fixtures.append(dict(fixture=n,pod=p,seat=seat,old=old,new=new,anchor=anchor,ids=ids))
            for g in range(3):
                tasks.append((n,g,ids[g:]+ids[:g],protocol['holdout_seeds'][p]+50000+seat*100+g))
    from .game_queue import GameQueue
    resources=campaign_resources(protocol.get('requested_game_workers',protocol['game_workers']))
    with GameQueue(resources,config,progress) as pool:
        def collect(block=False):
            completed=pool.collect(block)
            for (n,g),record in completed:
                records.append(dict(fixture=n,game=g,**record))
                progress(f'新旧牌组交叉对局 {len(records)}/{len(tasks)}；当前目标同时 {pool.target} 局：{record["outcome"]}')
            if completed:save(folder/'games.json',sorted(records,key=lambda r:(r['fixture'],r['game'])))
        for n,g,order,seed in tasks:
            while len(pool)>=pool.ceiling*2:collect(True)
            pool.submit((n,g),run_battle,config,decks_dir,order,seed,protocol['clock_seconds'],folder,f'fixture{n:03d}_game{g:03d}.log')
            collect()
        while pool:collect(True)
        scheduling=pool.report()
    counts=Counter()
    for r in records:
        counts[r['outcome']]+=1
        if r['outcome']=='win':counts[r['winner'].rsplit('_',1)[1]+'_wins']+=1
    result=dict(fixtures=fixtures,games=sorted(records,key=lambda r:(r['fixture'],r['game'])),summary=dict(counts),
        matched_fixtures=len(fixtures),attempted=len(records),execution=dict(resources,scheduling=scheduling),
        limitation='每个相同轮抓种子/席位的旧牌组与新牌组、固定旧版第三副牌同桌，三局换座。完全相同牌组不重复测试。同桌相关且每桌共享牌组，小样本结果不是独立胜率证据。')
    result['uncertainty']=cross_uncertainty(result)
    save(out/'cross_match.json',result);return result

def cross_uncertainty(result):
    """Cluster by original draft table, including all correlated fixtures/seats."""
    fixtures={f['fixture']:f for f in result['fixtures']};by_pod=defaultdict(list)
    for game in result['games']:
        if game['outcome'] not in {'win','draw'}:continue
        winner=game.get('winner') or ''
        value=1 if winner.endswith('_new') else -1 if winner.endswith('_old') else 0
        by_pod[fixtures[game['fixture']]['pod']].append(value)
    values=np.array([statistics.mean(v) for _,v in sorted(by_pod.items())])
    if not len(values):return dict(independent_pods=0,mean_new_minus_old=None,pod_bootstrap95=None)
    rng=np.random.default_rng(782)
    bootstrap=np.mean(rng.choice(values,size=(2000,len(values)),replace=True),axis=1)
    return dict(independent_pods=len(values),mean_new_minus_old=float(np.mean(values)),
        pod_bootstrap95=[float(x) for x in np.quantile(bootstrap,[.025,.975])],
        limitation='按原轮抓桌整体重采样；同桌多个交叉席位及换座对局属于同一个簇。固定预算，不因区间好看而提前停止；区间仅覆盖当前机器人和发生变化的牌组。')

def sampling_report(protocol,before,after,cross,training=None):
    target=len(protocol['holdout_seeds']);minimum=6
    reports={}
    for label,evidence in [('before',before),('after',after)]:
        summary=evidence['summary']
        reports[label]=dict(independent_pods=summary.get('completed_draft_pods',0),
            by_guild={g:summary.get('independent_pods_by_guild',{}).get(g,0) for g in GUILDS},
            completed=summary['completed'],attempted=summary['attempted'])
    uncertainty=cross.get('uncertainty') or cross_uncertainty(cross)
    adequate=(target>=30 and all(r['independent_pods']>=target*.9 and min(r['by_guild'].values())>=minimum
        and r['completed']>=r['attempted']*.9 for r in reports.values()) and uncertainty['independent_pods']>=10)
    training_ok=None
    if training is not None:
        summary=training['summary'];planned=len(protocol['train_seeds'])
        training_ok=(summary['completed']>=planned*3*.9 and summary.get('completed_draft_pods',0)>=planned*.9)
        adequate=adequate and training_ok
    return dict(target_pods_per_version=target,versions=reports,cross=uncertainty,adequate=adequate,
        minimum_guild_pods=minimum,training_completion_adequate=training_ok,
        note='快速档用于排错，不给出实战优势结论。标准门槛为新旧各至少30桌、90%桌有正常结果、每个双色至少6桌、交叉至少10个原轮抓桌；门槛是项目工作标准，不是统计功效保证。')

def paired_behavior(before,after):
    """Only compare game/seat observations valid in both versions."""
    indexed=[]
    for evidence in [before,after]:
        own={}
        for t in evidence['traces']:
            for id_,p in t['players'].items():
                seat=int(re.search(r'_s(\d+)_',id_)[1])
                own[(t['pod'],t['game'],seat)]=p
        indexed.append(own)
    a,b=indexed;shared=sorted(set(a)&set(b))
    metrics={}
    for field in ['no_spell_first4_rate','finisher_casts','interaction_casts','spellcasts']:
        metrics[field]=dict(before=statistics.mean(a[k][field] for k in shared) if shared else None,
            after=statistics.mean(b[k][field] for k in shared) if shared else None)
    cycle_pairs=[k for k in shared if a[k].get('complete_early_cycles')==4 and b[k].get('complete_early_cycles')==4]
    for field in ['no_action_cycle_rate','no_spell_cycle_rate']:
        metrics[field]=dict(before=statistics.mean(a[k][field] for k in cycle_pairs) if cycle_pairs else None,
                           after=statistics.mean(b[k][field] for k in cycle_pairs) if cycle_pairs else None)
    return dict(paired_player_observations=len(shared),paired_games=len({k[:2] for k in shared}),metrics=metrics,
        complete_cycle_paired_observations=len(cycle_pairs),
        limitation='仅比较两版都正常完成的同种子/局序/玩家席位；同桌重复相关。异常导致缺失选择偏差，行为不是独立牌力标签。')

def finish_revision(catalog,out,progress=print):
    """Resume the frozen candidate; never retune against these holdouts."""
    with forge_session():return _finish_revision(catalog,out,progress)

def _finish_revision(catalog,out,progress=print):
    timing=Timings(out/'timings.json')
    read=lambda n:json.loads((out/n).read_text(encoding='utf-8'))
    base=read('base_cube.json');candidate=read('candidate.json');selection=read('selection.json');protocol=read('protocol.json')
    spec=BuildSpec.from_dict(base['spec']);rows=candidate['cards']
    digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    frozen=out/'frozen_candidate.json'
    if frozen.exists() and read('frozen_candidate.json')['sha256']!=digest:raise ValueError('已冻结的候选发生变化，禁止复用测试集')
    save(frozen,dict(sha256=digest,policy=POLICY_VERSION,created=datetime.now(timezone.utc).isoformat()))
    structural_pods=len(protocol['structural_holdout_seeds']);holdout_pods=len(protocol['holdout_seeds'])
    progress(f'独立测试：{structural_pods} 桌 / {structural_pods*3} 副牌组，新旧使用同样轮抓种子与色组')
    for label,items in [('before',base['cards']),('after',rows)]:
        file=out/f'holdout_drafts_{label}.json'
        if not file.exists():save(file,timing.call('holdout_structure_'+label,draft_evaluation,catalog,items,spec,protocol['structural_holdout_seeds'],protocol['structural_holdout_guilds'],learned=protocol.get('learned_model')))
    paired=paired_structural(read('holdout_drafts_before.json'),read('holdout_drafts_after.json'))
    for label,items in [('before',base['cards']),('after',rows)]:
        file=out/f'holdout_match_{label}.json'
        if not file.exists():
            progress(f'独立 Forge 对局：{label}，{holdout_pods} 桌 / {holdout_pods*3} 局')
            value=timing.call('holdout_forge_'+label,simulate,catalog,items,spec,holdout_pods,3,protocol['clock_seconds'],progress,
                pod_seeds=protocol['holdout_seeds'],preferred_guilds=protocol['holdout_guilds'],workers=protocol.get('requested_game_workers',protocol['game_workers']))
            save(file,value)
        save(out/f'holdout_evidence_{label}.json',timing.call('holdout_trace_'+label,evidence_from_match,catalog,read(f'holdout_match_{label}.json')))
    if not (out/'cross_match.json').exists():timing.call('cross_forge',cross_cube,catalog,read('holdout_match_before.json'),read('holdout_match_after.json'),protocol,out,progress)
    before=read('holdout_evidence_before.json');after=read('holdout_evidence_after.json');cross=read('cross_match.json')
    sampling=sampling_report(protocol,before,after,cross,read('training_evidence.json'))
    interval=sampling['cross']['pod_bootstrap95'];margin=sampling['cross']['mean_new_minus_old']
    strict=audit(catalog,rows,spec,strict=True)
    gates=dict(hard_constraints=strict['hard_errors']==0,
        all_buildable=read('holdout_drafts_after.json')['buildable_rate']==1,
        structural_mean=paired['mean_difference']>0,structural_lower_tail=paired['p10_after']>=paired['p10_before'],
        structural_interval=paired['pod_bootstrap95'][0]>0,
        structural_balance=paired['gap_after']<=paired['gap_before']+.002,
        no_guild_regression=min(paired['guild_differences'].values())>=-.006,
        native_completion=after['summary']['completed']>=before['summary']['completed'] and after['summary']['skipped_pods']==0,
        cross_evidence=cross['attempted']>=9 and cross['summary'].get('win',0)+cross['summary'].get('draw',0)>=cross['attempted']*.9,
        sampling_adequacy=sampling['adequate'],
        observed_cross_regression=bool(interval and interval[0]>0 and margin>0))
    status='provisional' if all(gates.values()) else 'experimental'
    if not (out/'exported_candidate.json').exists() or read('exported_candidate.json')['provenance'].get('validation_status')!=status:
        candidate['spec']['name']+=' · Forge反馈改进候选'
        candidate['provenance'].update(optimization_id=out.name,validation_status=status,candidate_sha256=digest)
        save(out/'exported_candidate.json',export_run(catalog,candidate))
    revision=read('exported_candidate.json')
    report=dict(optimization_id=out.name,status=status,gates=gates,revision=revision,swaps=selection['swaps'],
        sampling=sampling,budget=protocol.get('budget'),execution=protocol.get('resources'),timings=timing.snapshot(),search=selection.get('search'),
        structural=paired,behavior=paired_behavior(before,after),training=read('training_evidence.json')['summary'],
        forge_before=before['summary'],forge_after=after['summary'],cross=cross['summary'],cross_games=cross['attempted'],
        matches=dict(training=read('training_match.json')['match_id'],before=read('holdout_match_before.json')['match_id'],after=read('holdout_match_after.json')['match_id']),
        limitation='结构指标来自固定轮抓/组牌机器人与启发式特征；实战来自 Forge 原生 AI。颜色均衡、娱乐性及人类驾驶下的强度未获统计证明。若门槛失败保留为实验候选，不自动推荐替换。')
    save(out/'report.json',report)
    with (out/'swaps.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['remove','add','role','identity','reason']);writer.writeheader()
        writer.writerows({k:r[k] for k in writer.fieldnames} for r in selection['swaps'])
    lines=['# Forge 数据反馈改进报告','',f'状态：{status}；替换 {len(selection["swaps"])} 张；{len(rows)} 张原版保留。','',
        '## Problem','用实际对局及轮抓后可构筑牌组改进 Cube。','',
        '## Inputs',f'训练 {report["training"]["completed"]}/{report["training"]["attempted"]} 局；{len(protocol["ranking_seeds"])} 桌开发轮抓。独立结构测试 {structural_pods} 桌、{structural_pods*3} 副牌组；新旧各 {holdout_pods*3} 局；交叉 {cross["attempted"]} 局。','',
        '## Checks performed','按整桌保留独立种子；卡表先冻结；每次替换严格审计；同色、同费用档、生物密度保留；引擎异常排除；每三局轮换座位。','',
        '## Findings',f'结构指标（不是胜率）：均值 {paired["mean_before"]:.6f} → {paired["mean_after"]:.6f}；第10百分位 {paired["p10_before"]:.6f} → {paired["p10_after"]:.6f}；色组差 {paired["gap_before"]:.6f} → {paired["gap_after"]:.6f}。',
        f'按整桌重采样的结构差95%区间：{paired["pod_bootstrap95"]}。',
        f'实战前后：{json.dumps(before["summary"],ensure_ascii=False)} → {json.dumps(after["summary"],ensure_ascii=False)}。',
        f'交叉对局：{json.dumps(cross["summary"],ensure_ascii=False)}。','',
        f'独立桌数与交叉差区间：{json.dumps(sampling,ensure_ascii=False)}。','',
        f'共同正常对局的行为对比：{json.dumps(report["behavior"],ensure_ascii=False)}。','',
        '## Decision',f'门槛：{json.dumps(gates,ensure_ascii=False)}。'+('可作为暂定改进版；实战优势仍待更多整桌样本确认。' if status=='provisional' else '仅保留实验版本，未达到全部改进门槛，不能宣称优于原版。'),'',
        '## Risks',report['limitation']+' 自己的回合没有施放不等于卡手；未施放不等于抽到的死牌。每局必有一名胜者，因此同一Cube自我对局的平均胜率不能衡量整体升级。','',
        '## Next actions','继续积累新轮抓桌；仅在新的开发数据上调整，再声明新的保留集；不以人工作牌力标签为必要输入。','',
        '## Artifacts',f'新版 runs/{revision["run_id"]}；protocol.json、training_evidence.json、selection.json、holdout*.json、cross_match.json、cross/*.log、swaps.csv。','',
        '## 替换明细','']
    lines.extend(f'- {r["remove"]} → **{r["add"]}**（{r["identity"]}）：{r["reason"]}' for r in selection['swaps'])
    (out/'report.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    with timing.span('export_evidence'),zipfile.ZipFile(out/'evidence.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in evidence_files(out):z.write(p,p.relative_to(out))
        for label,id_ in report['matches'].items():
            from .forge import MATCHES
            for p in evidence_files(MATCHES/id_):z.write(p,Path('native_matches')/label/p.relative_to(MATCHES/id_))
    report['timings']=timing.snapshot();save(out/'report.json',report)
    return report

def optimize(catalog,rows,spec,progress=print,workers=0,clock=120,training_pods=None,profile='standard',max_swaps=None,scoring_backend='auto',search_mode='full'):
    if audit(catalog,rows,spec,strict=True)['hard_errors']:raise ValueError('先修复严格审计中的错误')
    budget=experiment_budget(profile,training_pods,max_swaps,len(rows))
    execution_resources(workers)
    if scoring_backend not in {'auto','cpu','gpu'}:raise ValueError('评分后端需为 auto、cpu 或 gpu')
    if search_mode not in {'adaptive','full'}:raise ValueError('候选搜索方式无效')
    if type(clock)!=int or not 15<=clock<=300:raise ValueError('单局时限需为 15–300 秒')
    with forge_session():
        return _optimize(catalog,rows,spec,progress,workers,clock,budget,scoring_backend,search_mode)

def _optimize(catalog,rows,spec,progress,workers,clock,budget,scoring_backend='auto',search_mode='full'):
    id_=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    out=OPTIMIZATIONS/id_;out.mkdir(parents=True)
    # Each subsequent optimization receives fresh declared seeds; a new card list
    # must not repeatedly be selected against a previously inspected holdout.
    seed=random.SystemRandom().randrange(1,1_000_000_000)
    protocol,match,evidence,drafts=collect_training(catalog,rows,spec,out,budget['training_pods'],workers,clock,progress,experiment_seed=seed,budget=budget)
    protocol['scoring_backend']=scoring_backend;protocol['search']['mode']=search_mode;save(out/'protocol.json',protocol)
    candidate,selection=Timings(out/'timings.json').call('candidate_search',propose_revision,catalog,rows,spec,protocol,evidence,drafts,progress)
    save(out/'candidate.json',candidate);save(out/'selection.json',selection)
    report=finish_revision(catalog,out,progress)
    from .surrogate import train
    timing=Timings(out/'timings.json')
    try:report['learning_update']=timing.call('learning_update',train,catalog,progress)
    except (OSError,ValueError,RuntimeError,np.linalg.LinAlgError) as e:report['learning_update']=dict(status='failed',reason=str(e))
    report['timings']=timing.snapshot();save(out/'report.json',report)
    return report
