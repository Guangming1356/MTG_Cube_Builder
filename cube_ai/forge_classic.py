"""Native two-player Forge Draft games from traditional Cube draft pods.

This path deliberately uses isolated Forge processes: the resident bridge is
Commander-only. Unsupported drafted decks are never substituted or discarded;
only pairings involving them are skipped and counted explicitly.
"""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import random
import time
import uuid
import zipfile

from . import forge
from .brackets import cube_report
from .draft import draft_pod
from .engine import audit
from .game_queue import GameQueue
from .task_control import atomic_json


def classic_round_size(players):
    if type(players) is not int or not 2<=players<=12:raise ValueError('传统轮抽人数需为 2–12')
    return 2*(players//2)


def classic_min_games(players):
    size=classic_round_size(players)
    return size if players%2==0 else 2*size


def classic_pairings(ids,games):
    """Circle method; each pairing plays twice with reversed starting seats."""
    if len(set(ids))!=len(ids):raise ValueError('轮抽座位不能重复')
    size=classic_round_size(len(ids));minimum=classic_min_games(len(ids))
    if type(games) is not int or games<minimum or games>30 or games%size:
        raise ValueError(f'每桌对局数需为 {minimum}–30，且是 {size} 的倍数')
    players=list(ids)+([None] if len(ids)%2 else [])
    orders=[]
    while len(orders)<games:
        for _ in range(len(players)-1):
            for i in range(len(players)//2):
                a,b=players[i],players[-1-i]
                if a is not None and b is not None:orders.extend([(a,b),(b,a)])
            players=[players[0],players[-1],*players[1:-1]]
            if len(orders)>=games:return orders[:games]
    return orders[:games]


def write_classic_deck(deck,path,index,catalog):
    if deck.get('commander'):raise ValueError('传统轮抽牌组不能包含指挥官区')
    main=Counter(deck['spells']+deck['lands']);drafted=Counter(deck['drafted'])
    for name in deck['spells']+deck['lands']:
        if drafted[name]<1:raise ValueError('组入了未抓到的非基本地牌：'+name)
        drafted[name]-=1
    for color,count in deck['basics'].items():
        if color not in forge.BASICS or type(count) is not int or count<0:raise ValueError('基本地数量或颜色无效')
        main[forge.BASICS[color]]+=count
    if sum(main.values())!=40:raise ValueError('传统轮抽牌组必须为 40 张')
    missing=[n for n in main if not forge.engine_name(n,index)]
    if missing:raise ValueError('Forge 不支持这些牌，未替换或丢弃：'+', '.join(missing))
    lines=['[metadata]','Name='+path.stem,'[Main]']
    lines += [str(count)+' '+forge.engine_name(name,index) for name,count in sorted(main.items())]
    path.write_text('\n'.join(lines)+'\n',encoding='utf8')
    return dict(main=40,commander=0,total=40,sha256=forge.sha256(path),deck_policy=deck.get('deck_policy','quality'))


def simulate(catalog,rows,spec,pods=10,games_per_pod=8,clock_seconds=90,progress=lambda _:None,
             pod_seeds=None,preferred_guilds=None,workers=0):
    if spec.mode!='classic':raise ValueError('此流程仅用于传统轮抽')
    if type(pods) is not int or not 1<=pods<=forge.MAX_PODS:raise ValueError('轮抽桌数无效')
    classic_pairings([str(i) for i in range(spec.players)],games_per_pod)
    if type(clock_seconds) is not int or not 15<=clock_seconds<=300:raise ValueError('单局时限需为 15–300 秒')
    if pod_seeds is not None and (not isinstance(pod_seeds,list) or len(pod_seeds)!=pods or any(type(s) is not int for s in pod_seeds)):
        raise ValueError('每桌随机种子数量无效')
    if preferred_guilds is not None:
        from .config import GUILDS
        if not isinstance(preferred_guilds,list) or len(preferred_guilds)!=pods or any(not isinstance(g,list) or len(g)!=spec.players or any(x not in GUILDS for x in g) for g in preferred_guilds):
            raise ValueError('每桌的偏好色组数量需与轮抽人数相同')
    if audit(catalog,rows,spec)['hard_errors']:raise ValueError('请先修复牌表中的硬性错误')
    resources=forge.campaign_resources(workers)
    config=dict(forge.configuration(),backend='isolated',game_format='Draft')
    index=forge.card_index(config);coverage=forge.coverage(rows,config)
    if not forge._lock.acquire(blocking=False):raise ValueError('已有 Forge 实战任务，请等它完成')
    try:
        match_id=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
        out=forge.MATCHES/match_id;out.mkdir(parents=True);deck_dir=out/'decks';deck_dir.mkdir()
        cube_hash=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
        records=[];tables=[];rng=random.Random(spec.seed);submitted=0;skipped=0;started=time.monotonic();draft_seconds=0;peak_pending=0
        with GameQueue(resources,config,progress) as queue:
            def collect(block=False):
                completed=queue.collect(block)
                for (pod,game),record in completed:
                    records.append(dict(pod=pod,game=game,**record))
                    progress(f'Forge 已完成 {len(records)}/{submitted} 局；已组牌 {len(tables)}/{pods} 桌')
                if completed:atomic_json(out/'games.json',sorted(records,key=lambda r:(r['pod'],r['game'])))
            for p in range(pods):
                while len(queue)>=queue.ceiling*2:collect(True)
                begin=time.monotonic();pod_rng=random.Random(pod_seeds[p]) if pod_seeds is not None else rng
                pod=draft_pod(catalog,rows,spec,pod_rng,preferred_guilds[p] if preferred_guilds is not None else None)
                pod.update(pod=p,draft_seed=pod_seeds[p] if pod_seeds is not None else None,skipped_pairings=[])
                for deck in pod['decks']:
                    deck['id']=f'p{p:03d}_s{deck["seat"]}_{deck.get("identity","none")}'
                    if deck['buildable']:
                        deck['unsupported']=[n for n in deck['spells']+deck['lands'] if not forge.engine_name(n,index)]
                        deck['engine_supported']=not deck['unsupported']
                        if deck['engine_supported']:deck['export']=write_classic_deck(deck,deck_dir/(deck['id']+'.dck'),index,catalog)
                tables.append(pod);draft_seconds+=time.monotonic()-begin
                by_id={d['id']:d for d in pod['decks']}
                for game,order in enumerate(classic_pairings(list(by_id),games_per_pod)):
                    if any(not by_id[n].get('buildable') or not by_id[n].get('engine_supported') for n in order):
                        pod['skipped_pairings'].append(dict(game=game,order=order,reason='unsupported_deck'));skipped+=1;continue
                    while len(queue)>=queue.ceiling*2:collect(True)
                    seed=(pod_seeds[p] if pod_seeds is not None else spec.seed+p*10000)+game
                    queue.submit((p,game),forge.run_battle,config,deck_dir,list(order),seed,clock_seconds,out,f'pod{p:03d}_game{game:03d}.log')
                    submitted+=1;peak_pending=max(peak_pending,len(queue))
                if len(pod['skipped_pairings'])==games_per_pod:pod['skip_reason']='每个配对都涉及 Forge 未支持的牌组'
                if pod['skipped_pairings']:
                    progress(f'第 {p+1} 桌有 {len(pod["skipped_pairings"])} 个配对涉及未支持的牌，已跳过且未替换牌组')
                collect()
            while queue:collect(True)
            scheduling=queue.report()
        records.sort(key=lambda r:(r['pod'],r['game']));summary=forge.summarize(records,tables)
        played={d['id']:d['identity'] for p in tables for d in p['decks'] if d['buildable']}
        independent={}
        for game in records:
            if game['outcome'] not in {'win','draw'}:continue
            for identifier in game['order']:independent.setdefault(played[identifier],set()).add(game['pod'])
        summary['independent_pods_by_guild']={k:len(v) for k,v in independent.items()}
        result=dict(match_id=match_id,path=str(out),engine=forge.engine_description(config),spec=spec.to_dict(),cube_sha256=cube_hash,
            coverage=coverage,pods=pods,games_per_pod=games_per_pod,clock_seconds=clock_seconds,seed=spec.seed,
            rules=dict(players=2,draft_players=spec.players,deck_minimum=40,deck_total_exported=40,commander_in_total=False,starting_life=20,
                free_basic_lands=True,rounds=spec.rounds,pack_size=spec.pack_size,pick_count=spec.pick_count,discard_after_pass=spec.discard_after_pass),
            tables=tables,games=records,summary=summary,workers=max(1,scheduling['peak_active']),bracket=cube_report(catalog,rows,spec),
            execution=dict(resources,wall_seconds=round(time.monotonic()-started,3),draft_seconds=round(draft_seconds,3),
                game_wall_seconds_sum=round(sum(r['wall_seconds'] for r in records),3),peak_pending=peak_pending,isolated_worker_directories=True,scheduling=scheduling),
            pod_seeds=pod_seeds,preferred_guilds=preferred_guilds,skipped_pods=sum('skip_reason' in p for p in tables),skipped_games=skipped,
            limitation='真实 Forge Draft 规则与原生 AI；每局两人、40 张、20 点生命。未支持的牌组仅跳过相关配对，不替换牌。小样本和同桌对局不能证明颜色平衡或人类胜率；异常和超时不计为正常胜负。')
        atomic_json(out/'report.json',result);atomic_json(out/'cube.json',dict(cards=rows,spec=spec.to_dict()))
        text=(f'# Forge 传统轮抽对局报告\n\n- 引擎：{config["version"]}；每局两人、40 张、20 点生命\n'
              f'- 轮抽：{pods} 桌；每桌计划 {games_per_pod} 局；跳过配对 {skipped} 局\n'
              f'- 正常完成：{summary["completed"]}/{len(records)} 局\n\n{result["limitation"]}\n\n## 每局记录\n\n')
        text+='\n'.join(f'- 桌 {r["pod"]+1} 局 {r["game"]+1}：{r["outcome"]}；胜者 {r["winner"]}；日志 [{r["log"]}]({r["log"]})' for r in records)
        (out/'report.md').write_text(text+'\n',encoding='utf8')
        with zipfile.ZipFile(out/'evidence.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for path in forge.evidence_files(out):archive.write(path,path.relative_to(out))
        return result
    finally:forge._lock.release()
