"""Paired native-policy study. The Cube, draft and commanders never change.

These controlled games are deliberately outside matches/optimizations so they
cannot silently become additional model-training or strength-validation samples.
"""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import random
import statistics
import time
import uuid
import zipfile

from .config import ROOT
from .deck_building import revise
from .draft import draft_pod
from .engine import audit
from .forge import (campaign_resources,card_index,configuration,engine_name,
                    evidence_files,forge_session,run_battle,write_deck)
from .game_queue import GameQueue
from .optimize import game_trace,schedule
from .task_control import atomic_json

STUDIES=ROOT/'private/deck-studies'
VERSION='deck-policy-study-3'
NORMAL={'win','draw'}


def snapshot_sources(catalog,rows,out):
    """Preserve the code and trusted card features used before native outcomes."""
    names=['deck_study','deck_building','optimize','draft','forge','forge_worker','game_queue',
           'task_control','config','brackets','design','catalog','features','sim_cache',
           'tuning','experiment','resources','acceleration','engine']
    folder=out/'source';folder.mkdir()
    hashes={}
    for name in names:
        path=Path(__file__).with_name(name+'.py');data=path.read_bytes()
        (folder/path.name).write_bytes(data);hashes[path.name]=hashlib.sha256(data).hexdigest()
    cards=[catalog.cards[name] for name in sorted({row['name'] for row in rows})]
    atomic_json(folder/'catalog.json',dict(cards=cards,snapshot=catalog.snapshot,signature=catalog.signature))
    return dict(files=hashes,card_records=len(cards),stored_before_games=True,
                activity_version='completed-player-cycles-1')


def _average(records,key):
    values=[record['activity'][key] for record in records if record.get('activity') and record['activity'].get(key) is not None]
    return statistics.mean(values) if values else None


def _interval(differences):
    if len(differences)<5:return None
    rng=random.Random(843017);count=len(differences)
    values=sorted(statistics.mean(rng.choices(differences,k=count)) for _ in range(2000))
    return [values[49],values[1949]]


def summarize(records,pods):
    groups={}
    for policy in ['quality','balanced']:
        attempted=[r for r in records if r['policy']==policy]
        normal=[r for r in attempted if r['outcome'] in NORMAL]
        groups[policy]=dict(attempted=len(attempted),normal=len(normal),outcomes=dict(Counter(r['outcome'] for r in attempted)),
            normal_rate=len(normal)/max(1,pods*3),no_spell_first4_rate=_average(normal,'no_spell_first4_rate'),
            no_action_cycle_rate=_average(normal,'no_action_cycle_rate'),no_spell_cycle_rate=_average(normal,'no_spell_cycle_rate'),
            finisher_presence=_average(normal,'finisher_presence'),own_turns=_average(normal,'own_turns'),
            complete_first4_coverage=_average(normal,'complete_first4_coverage'))
    by_key={(r['pod'],r['policy'],r['game']):r for r in records}
    paired=[]
    for pod in range(pods):
        before=[by_key.get((pod,'quality',game)) for game in range(3)]
        after=[by_key.get((pod,'balanced',game)) for game in range(3)]
        if any(not r or r['outcome'] not in NORMAL or not r.get('activity') for r in before+after):continue
        row=dict(pod=pod)
        for key in ['no_action_cycle_rate','no_spell_first4_rate','finisher_presence','own_turns']:
            a=_average(before,key);b=_average(after,key)
            row[key]=b-a if a is not None and b is not None else None
        paired.append(row)
    differences=[p['no_action_cycle_rate'] for p in paired if p['no_action_cycle_rate'] is not None]
    finishers=[p['finisher_presence'] for p in paired if p['finisher_presence'] is not None]
    interval=_interval(differences)
    gates=dict(normal_completion=all(v['normal_rate']>=.9 for v in groups.values()),
               first4_coverage=all(v['complete_first4_coverage'] is not None and v['complete_first4_coverage']>=.9 for v in groups.values()),
               independent_pods=len(differences)>=15,
               fewer_no_action_cycles=bool(interval and interval[1]<0),
               finisher_observation_not_lower=bool(finishers and statistics.mean(finishers)>=-.05))
    return dict(policies=groups,paired_complete_pods=len(paired),analyzed_pods=len(differences),
        no_action_difference=statistics.mean(differences) if differences else None,no_action_cluster_interval95=interval,
        finisher_difference=statistics.mean(finishers) if finishers else None,finisher_cluster_interval95=_interval(finishers),
        gates=gates,supports_activity_improvement=all(gates.values()),changes_default_policy=False,
        limitation='整桌配对的描述性自助区间；没有重复开有利的包。未完成局保留并计入完成率。少量 Forge 对照不能证明人类娱乐性、色组均衡或普遍胜率。')


def compare(catalog,rows,spec,pods=20,workers=0,clock_seconds=180,seed=None,progress=lambda _:None):
    if spec.mode!='commander' or spec.players!=3:raise ValueError('组牌方式比较目前需要三人 Commander Cube')
    if type(pods) is not int or not 1<=pods<=100:raise ValueError('组牌对照需为 1–100 桌；少于 15 桌仅供排错')
    if type(clock_seconds) is not int or not 30<=clock_seconds<=300:raise ValueError('单局时限需为 30–300 秒')
    if seed is None:seed=spec.seed+37000000
    if type(seed) is not int or not 0<=seed<2**62:raise ValueError('对照种子无效')
    if audit(catalog,rows,spec,strict=True)['hard_errors']:raise ValueError('请先修复牌表中的构筑错误，再比较组牌方式')
    with forge_session():
        from .tuning import apply,engine_key
        config=apply(configuration());config['cache']=False;index=card_index(config)
        resources=campaign_resources(workers);started=time.monotonic()
        id_=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
        out=STUDIES/id_;decks_dir=out/'decks';decks_dir.mkdir(parents=True)
        seeds,guilds=schedule(pods,seed);tables=[];records=[];prepared={};submitted=0
        result=dict(study_id=id_,version=VERSION,purpose='controlled_policy_comparison',state='running',
            spec=spec.to_dict(),pods=pods,games_per_policy=pods*3,seed=seed,clock_seconds=clock_seconds,
            cube_sha256=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),
            engine=dict(version=config['version'],backend=config.get('backend'),fingerprint=engine_key(config)),
            fixed=['drafted_pool','commander','identity','nonbasic_lands','land_count','deck_size'],
            policy=dict(name='balanced',low_target=12,high_target=6,max_spell_swaps=6,experimental=True),
            policy_sha256=hashlib.sha256(Path(__file__).with_name('deck_building.py').read_bytes()).hexdigest(),
            training_samples_added=0,tables=tables,games=records)
        result['activity_definition']='前四个完整的个人回合周期：从自己的回合开始至下一次自己的回合开始，计入期间任意回合施放、主动异能和宣攻；不计自动触发及下地。第五次自己的回合未开始，则不足四个完整周期。'
        result['source_snapshot']=snapshot_sources(catalog,rows,out)
        atomic_json(out/'cube.json',dict(spec=spec.to_dict(),cards=rows));atomic_json(out/'report.json',result)
        metadata=dict(id=id_,label=spec.name,pods=pods,state='running')
        atomic_json(out/'summary.json',metadata)
        with GameQueue(resources,config,progress) as queue:
            def collect(block=False):
                nonlocal records
                for (pod,policy,game),value in queue.collect(block):
                    record=dict(pod=pod,policy=policy,game=game,**value)
                    if record['outcome'] in NORMAL:
                        trace=game_trace(catalog,(out/record['log']).read_text(encoding='utf8',errors='replace'),prepared[(pod,policy)],extended=True)
                        players=list(trace['players'].values());full=[p for p in players if p['complete_early_cycles']==4]
                        record['activity']=dict(no_action_cycle_rate=statistics.mean(p['no_action_cycle_rate'] for p in full) if full else None,
                            no_spell_cycle_rate=statistics.mean(p['no_spell_cycle_rate'] for p in full) if full else None,
                            no_spell_first4_rate=statistics.mean(p['no_spell_first4_rate'] for p in players if p['early_turns']==4) if any(p['early_turns']==4 for p in players) else None,
                            finisher_presence=statistics.mean(p['finisher_casts']>0 for p in players),
                            own_turns=statistics.mean(p['own_turns'] for p in players),complete_first4_coverage=len(full)/len(players))
                        atomic_json(out/(Path(record['log']).stem+'.trace.json'),trace)
                    records.append(record)
                if records:
                    result['games']=sorted(records,key=lambda r:(r['pod'],r['policy'],r['game']))
                    # Full tables/packs are immutable shards. Avoid serializing
                    # every earlier table again after each completed game.
                    atomic_json(out/'games.json',result['games'])
                progress(f'组牌方式对照：已完成 {len(records)}/{pods*6} 局；已准备 {len(tables)}/{pods} 桌；当前目标同时 {queue.target} 局')
            for pod,(draft_seed,prefs) in enumerate(zip(seeds,guilds)):
                while len(queue)>=queue.ceiling*2:collect(True)
                progress(f'准备同一桌抓牌的两种组牌：{pod+1}/{pods}')
                drafted=draft_pod(catalog,rows,spec,random.Random(draft_seed),prefs,readiness_hands=0)
                before=drafted['decks'];after=[revise(catalog,deck,spec,'balanced') for deck in before]
                table=dict(pod=pod,draft_seed=draft_seed,guilds=prefs,policies={'quality':before,'balanced':after},packs=drafted['packs'])
                tables.append(table);unsupported=[]
                for policy,decks in table['policies'].items():
                    prepared[(pod,policy)]=decks
                    for deck in decks:
                        deck['id']=f'p{pod:03d}_{policy}_s{deck["seat"]}_{deck.get("identity","none")}'
                        if not deck['buildable']:continue
                        missing=[name for name in deck['spells']+deck['lands']+[deck['commander']] if not engine_name(name,index)]
                        unsupported.extend(missing)
                        if not missing:deck['export']=write_deck(deck,decks_dir/(deck['id']+'.dck'),index,catalog,spec)
                if unsupported or not all(d['buildable'] for d in before+after):
                    table['skip_reason']='两种组牌中存在无法组牌或 Forge 未实现的牌，整桌配对跳过；未换牌或重开包'
                    table['unsupported']=sorted(set(unsupported))
                    atomic_json(out/'tables'/f'pod{pod:03d}.json',table);continue
                atomic_json(out/'tables'/f'pod{pod:03d}.json',table)
                for policy in (['quality','balanced'] if pod%2==0 else ['balanced','quality']):
                    ids=[deck['id'] for deck in prepared[(pod,policy)]]
                    for game in range(3):
                        while len(queue)>=queue.ceiling*2:collect(True)
                        order=ids[game:]+ids[:game]
                        queue.submit((pod,policy,game),run_battle,config,decks_dir,order,draft_seed+game,clock_seconds,out,f'p{pod:03d}_{policy}_g{game:03d}.log')
                        submitted+=1
                collect()
            while queue:collect(True)
            result['execution']=dict(resources,**queue.report(),wall_seconds=time.monotonic()-started,submitted_games=submitted)
        result.update(state='done',summary=summarize(records,pods),games=sorted(records,key=lambda r:(r['pod'],r['policy'],r['game'])),
                      skipped_pods=sum(bool(table.get('skip_reason')) for table in tables))
        atomic_json(out/'report.json',result)
        metadata['state']='done';atomic_json(out/'summary.json',metadata)
        summary=result['summary'];lines=['# 同一抓牌池的组牌方式对照','',f'轮抓桌数：{pods}；每种方式每桌 3 局换座；没有修改 Cube。','',
            '| 组牌方式 | 正常完成 / 计划 | 前四完整周期零行动比例 | 施放过终结牌的玩家比例 |', '|---|---:|---:|---:|']
        for policy,label in [('quality','单卡质量优先'),('balanced','均衡费用（实验）')]:
            value=summary['policies'][policy]
            fmt=lambda v:'缺少记录' if v is None else f'{v:.1%}'
            lines.append(f'| {label} | {value["normal"]}/{pods*3} | {fmt(value["no_action_cycle_rate"])} | {fmt(value["finisher_presence"])} |')
        lines.extend(['',f'完整配对的独立轮抓桌：{summary["paired_complete_pods"]}。',
                      '观察支持前期行动改善。' if summary['supports_activity_improvement'] else '目前不足以确认前期行动改善；未更改默认组牌。','',result['activity_definition'],'',summary['limitation']])
        (out/'report.md').write_text('\n'.join(lines),encoding='utf8')
        with zipfile.ZipFile(out/'evidence.zip','w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for path in evidence_files(out):archive.write(path,path.relative_to(out))
        return result
