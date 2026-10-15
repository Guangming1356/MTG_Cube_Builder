"""Native Forge AI games. Outcomes come exclusively from the rules engine."""
import hashlib
import json
import os
import random
import re
import subprocess
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT
from .draft import draft_pod
from .engine import audit
from .forge_setup import RUNTIME, sha256, write_profile

MATCHES=ROOT/'matches'
_lock=threading.Lock()
_indices={}
BASICS=dict(W='Plains',U='Island',B='Swamp',R='Mountain',G='Forest',C='Wastes')

def configuration():
    path=RUNTIME/'forge.json'
    value=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if os.getenv('CUBE_FORGE_HOME'):
        home=Path(os.environ['CUBE_FORGE_HOME']).resolve()
        jars=list(home.glob('forge-gui-desktop-*.jar'))
        if not jars:raise ValueError('CUBE_FORGE_HOME 没有 Forge Desktop jar')
        value.update(home=str(home),jar=str(jars[0]),version='external')
    if os.getenv('CUBE_FORGE_JAVA'):value['java']=os.environ['CUBE_FORGE_JAVA']
    for key in ('home','jar','java'):
        if value.get(key) and not Path(value[key]).is_absolute():
            value[key]=str((RUNTIME/value[key]).resolve())
    if not value or not all(Path(value.get(k,'__missing__')).is_file() for k in ('jar','java')):
        raise ValueError('Forge 尚未安装。运行 python -m cube_ai forge-setup')
    home=Path(value.get('home','__missing__')).resolve()
    if not os.getenv('CUBE_FORGE_HOME') and home.is_relative_to(RUNTIME.resolve()) and (home/'.installed').is_file():
        write_profile(home)
    return value

def status():
    try:
        config=configuration()
        return dict(available=True,version=config['version'],pilot='Forge 原生 AI',seed_supported=True)
    except (ValueError,OSError,KeyError,json.JSONDecodeError) as e:
        return dict(available=False,reason=str(e))

def card_index(config):
    home=Path(config['home']);key=(str(home),config.get('jar_sha256'))
    if key in _indices:return _indices[key]
    names={}
    def add(raw):
        text=raw.decode('utf-8-sig',errors='replace')
        found=re.findall(r'^Name:(.+)$',text,re.M)
        if not found:return
        first=found[0].strip()
        names[first.casefold()]=first
        names.setdefault(first.split(' // ')[0].casefold(),first)
    folder=home/'res'/'cardsfolder'
    if folder.is_dir():
        for p in folder.rglob('*.txt'):add(p.read_bytes())
    for p in (home/'res').rglob('*.zip'):
        if 'card' not in p.name.lower():continue
        with zipfile.ZipFile(p) as archive:
            for n in archive.namelist():
                if n.endswith('.txt'):add(archive.read(n))
    if not names:raise ValueError('运行时没有找到 Forge 牌张脚本')
    _indices[key]=names
    return names

def engine_name(name,index):
    return index.get(name.casefold()) or index.get(name.split(' // ')[0].casefold())

def coverage(rows,config=None):
    index=card_index(config or configuration())
    missing=[r['name'] for r in rows if not engine_name(r['name'],index)]
    return dict(total=len(rows),supported=len(rows)-len(missing),missing=missing)

def write_deck(deck,path,index,catalog,spec=None):
    """Export exactly 60 including commander; free basics are not draft cards."""
    if spec is not None:
        from .brackets import deck_report
        report=deck_report(catalog,deck,spec)
        if report and report['violations']:raise ValueError('组牌违反 Bracket 构筑限制：'+'; '.join(report['violations']))
    cmd=deck['commander'];main=Counter(deck['spells']+deck['lands'])
    for color,count in deck['basics'].items():
        if color not in BASICS or type(count)!=int or count<0:raise ValueError('基本地数量或颜色无效')
        main[BASICS[color]]+=count
    if sum(main.values())+int(bool(cmd))!=60:raise ValueError('组牌结果必须为 60 张（含指挥官）')
    if not cmd or not catalog.cards[cmd]['commander']:raise ValueError('缺少可用指挥官')
    identity=set(catalog.cards[cmd]['identity'])
    if any(color!='C' and color not in identity and count for color,count in deck['basics'].items()):raise ValueError('基本地颜色身份违规')
    drafted=Counter(deck['drafted'])
    for n in deck['spells']+deck['lands']+[cmd]:
        if drafted[n]<1:raise ValueError('组入了未抓到的非基本地牌：'+n)
        drafted[n]-=1
        c=catalog.cards[n]
        if c['identity']!='C' and not set(c['identity'])<=identity:raise ValueError('颜色身份违规：'+n)
    missing=[n for n in list(main)+[cmd] if not engine_name(n,index)]
    if missing:raise ValueError('Forge 不支持这些牌，未替换或丢弃：'+', '.join(missing))
    content=['[metadata]','Name='+path.stem,'[Commander]','1 '+engine_name(cmd,index),'[Main]']
    content += [str(count)+' '+engine_name(n,index) for n,count in sorted(main.items())]
    path.write_text('\n'.join(content)+'\n',encoding='utf-8')
    return dict(main=sum(main.values()),commander=1,total=60,sha256=sha256(path))

def parse_log(log,returncode=0,process_timeout=False):
    """Engine failures and time limits are never counted as ordinary wins/draws."""
    duration=re.search(r'Game Result: Game \d+ ended (?:in a Draw! Took |in )(\d+) ms',log)
    turn_numbers=[int(n) for n in re.findall(r'\bTurn\s+(\d+)\b',log,re.I)]
    base=dict(engine_ms=int(duration.group(1)) if duration else None,
              turns=max(turn_numbers) if turn_numbers else None)
    if process_timeout:return dict(base,outcome='process_timeout',winner=None)
    pattern=r'(?:Exception in thread|\w+(?:Exception|Error):|^\s+at forge\.|Could not load deck|No deck found|[Cc]ould not find card|[Cc]ard not found)'
    # Forge cancels its AI future on an announced time limit, which can print an
    # InterruptedException stack. Preserve real errors preceding the time limit.
    if not returncode and 'Stopping slow match as draw' in log and not re.search(pattern,log.split('Stopping slow match as draw',1)[0],re.M):
        return dict(base,outcome='engine_timeout',winner=None)
    errors=re.search(pattern,log,re.M)
    if returncode or errors:return dict(base,outcome='engine_error',winner=None,error=errors.group(0) if errors else f'exit {returncode}')
    if 'Stopping slow match as draw' in log:return dict(base,outcome='engine_timeout',winner=None)
    winner=re.search(r'Game Result: Game \d+ ended in \d+ ms\. Ai\((\d+)\)-(.+) has won!',log)
    if winner:return dict(base,outcome='win',winner=winner.group(2).strip(),engine_seat=int(winner.group(1))-1)
    if re.search(r'Game Result: Game \d+ ended in a Draw!',log):return dict(base,outcome='draw',winner=None)
    return dict(base,outcome='unrecognized',winner=None,error='未找到 Forge 正式比赛结果')

def wilson(wins,n):
    if not n:return None
    z=1.96;p=wins/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den
    delta=z*((p*(1-p)/n+z*z/(4*n*n))**.5)/den
    return [round(max(0,center-delta),3),round(min(1,center+delta),3)]

def run_battle(config,deck_dir,order,seed,clock_seconds,out,log_name):
    """One native game, usable for both a draft pod and controlled cross-Cube matches."""
    command=[config['java'],'-Xmx2048m','-Dfile.encoding=UTF-8','-Djava.awt.headless=true',
        '-jar',config['jar'],'sim','-D',str(deck_dir.resolve()),'-d',*[n+'.dck' for n in order],
        '-f','Commander','-n','1','-s',str(seed),'-c',str(clock_seconds)]
    started=time.monotonic();timeout=False
    try:
        process=subprocess.run(command,cwd=config['home'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            timeout=clock_seconds+90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        log=process.stdout.decode('utf-8',errors='replace');code=process.returncode
    except subprocess.TimeoutExpired as e:
        log=(e.stdout or b'').decode('utf-8',errors='replace');code=-1;timeout=True
    (out/log_name).write_text(log,encoding='utf-8')
    record=dict(order=order,seed=seed,command=command,log=log_name,
        wall_seconds=round(time.monotonic()-started,3),returncode=code,**parse_log(log,code,timeout))
    if record['outcome']=='win' and record['winner'] not in order:
        record.update(outcome='unrecognized',error='获胜牌组与提交牌组不匹配',winner=None)
    return record

def summarize(records,pods):
    outcomes=Counter(r['outcome'] for r in records);groups=defaultdict(Counter)
    identities={d['id']:d['identity'] for p in pods for d in p['decks'] if d['buildable']}
    for r in records:
        if r['outcome'] not in {'win','draw'}:continue
        for deck_id in r['order']:
            g=groups[identities[deck_id]];g['appearances']+=1
            if r['winner']==deck_id:g['wins']+=1
            if r['outcome']=='draw':g['draws']+=1
    return dict(outcomes=dict(outcomes),games=len(records),completed=outcomes['win']+outcomes['draw'],
        guilds={g:dict(c,win_rate=round(c['wins']/c['appearances'],3),wilson95=wilson(c['wins'],c['appearances'])) for g,c in sorted(groups.items())},
        median_turns=__import__('statistics').median([r['turns'] for r in records if r['turns'] is not None and r['outcome'] in {'win','draw'}]) if any(r['turns'] is not None and r['outcome'] in {'win','draw'} for r in records) else None)

def simulate(catalog,rows,spec,pods=2,games_per_pod=3,clock_seconds=90,progress=lambda _:None,
             pod_seeds=None,preferred_guilds=None,workers=1):
    if spec.mode!='commander' or spec.players!=3:raise ValueError('当前 Forge 集成针对三人 Commander Cube')
    if type(pods)!=int or not 1<=pods<=30:raise ValueError('实战轮抓桌数需为 1–30')
    if type(games_per_pod)!=int or not 3<=games_per_pod<=30 or games_per_pod%3:raise ValueError('每桌对局数需为 3–30 且是 3 的倍数，以轮换座位')
    if type(clock_seconds)!=int or not 15<=clock_seconds<=300:raise ValueError('单局时限需为 15–300 秒')
    if type(workers)!=int or not 1<=workers<=3:raise ValueError('Forge 同时运行进程需为 1–3')
    if pod_seeds is not None and (len(pod_seeds)!=pods or any(type(s)!=int for s in pod_seeds)):raise ValueError('每桌随机种子数量无效')
    if preferred_guilds is not None and len(preferred_guilds)!=pods:raise ValueError('每桌轮抓色组数量无效')
    if audit(catalog,rows,spec)['hard_errors']:raise ValueError('请先修复牌表中的硬性错误')
    config=configuration();index=card_index(config);support=coverage(rows,config)
    if support['missing']:progress('Forge 尚未支持：'+', '.join(support['missing'][:15])+'；若实际组入牌组，整桌跳过并记录，不换牌')
    # A single JVM job at a time prevents competing native AI jobs from distorting clocks.
    if not _lock.acquire(blocking=False):raise ValueError('已有 Forge 实战任务，请等它完成')
    try:
        match_id=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
        out=MATCHES/match_id;out.mkdir(parents=True)
        deck_dir=out/'decks';deck_dir.mkdir();records=[];tables=[];rng=random.Random(spec.seed);tasks=[]
        cube_hash=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
        for p in range(pods):
            progress(f'Forge 实战：第 {p+1}/{pods} 桌轮抓与组牌')
            pod_rng=random.Random(pod_seeds[p]) if pod_seeds is not None else rng
            pod=draft_pod(catalog,rows,spec,pod_rng,preferred_guilds[p] if preferred_guilds is not None else None);pod['pod']=p
            pod['draft_seed']=pod_seeds[p] if pod_seeds is not None else None
            for d in pod['decks']:
                d['id']=f'p{p:03d}_s{d["seat"]}_{d.get("identity","none")}'
                if d['buildable']:
                    d['unsupported']=[n for n in d['spells']+d['lands']+[d['commander']] if not engine_name(n,index)]
                    d['engine_supported']=not d['unsupported']
                    if d['engine_supported']:d['export']=write_deck(d,deck_dir/(d['id']+'.dck'),index,catalog,spec)
            tables.append(pod)
            if not all(d['buildable'] and d.get('engine_supported') for d in pod['decks']):
                pod['skip_reason']='无指挥官或组入了 Forge 未实现的牌'
                progress('整桌因无指挥官或包含未实现牌而跳过；保留真实轮抓，不换牌组');continue
            ids=[d['id'] for d in pod['decks']]
            for game in range(games_per_pod):
                rotation=game%3;order=ids[rotation:]+ids[:rotation]
                seed=(pod_seeds[p] if pod_seeds is not None else spec.seed+p*10000)+game
                tasks.append((p,game,order,seed,f'pod{p:03d}_game{game:03d}.log'))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending={pool.submit(run_battle,config,deck_dir,order,seed,clock_seconds,out,log): (p,g)
                for p,g,order,seed,log in tasks}
            for future in as_completed(pending):
                p,g=pending[future];record=dict(pod=p,game=g,**future.result());records.append(record)
                progress(f'Forge 实战已完成 {len(records)}/{len(tasks)} 局：桌 {p+1} 局 {g+1} {record["outcome"]}')
                (out/'games.json').write_text(json.dumps(sorted(records,key=lambda r:(r['pod'],r['game'])),ensure_ascii=False,indent=2),encoding='utf-8')
        records.sort(key=lambda r:(r['pod'],r['game']))
        from .brackets import cube_report
        result=dict(match_id=match_id,path=str(out),engine=dict(version=config['version'],jar_sha256=sha256(config['jar']),
            java=config['java'],pilot='Forge native AI',rng='Forge -s'),spec=spec.to_dict(),cube_sha256=cube_hash,
            coverage=support,pods=pods,games_per_pod=games_per_pod,clock_seconds=clock_seconds,seed=spec.seed,
            rules=dict(players=3,deck_minimum=60,deck_total_exported=60,commander_in_total=True,starting_life=40,
                free_basic_lands=True,land_count='按曲线与可用牌决定，不固定 22 张',rounds=spec.rounds,
                pack_size=spec.pack_size,pick_count=spec.pick_count,discard_after_pass=spec.discard_after_pass),
            tables=tables,games=records,summary=summarize(records,tables),workers=workers,bracket=cube_report(catalog,rows,spec),
            pod_seeds=pod_seeds,preferred_guilds=preferred_guilds,
            skipped_pods=sum('skip_reason' in p for p in tables),
            limitation='真实 Forge 规则引擎对局，使用 Forge 原生 AI。胜率反映这套抓牌、组牌与驾驶策略；原生 AI 对控制、组合技和多人政治有偏差。小样本及同桌重复对局不能证明色组平衡；Wilson 区间仅为描述性参考。超时与引擎错误不计作正常和局或胜负。')
        (out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'cube.json').write_text(json.dumps(dict(cards=rows,spec=spec.to_dict()),ensure_ascii=False,indent=2),encoding='utf-8')
        text=f'# Forge 实战报告\n\n- 引擎：{config["version"]}，Forge 原生 AI\n- 轮抓：{pods} 桌；每桌 {games_per_pod} 局，轮换三个座位\n- 牌组：60 张含指挥官，基本地自由补入，40 点生命\n- 正常完成：{result["summary"]["completed"]}/{len(records)} 局\n- 结果：{json.dumps(result["summary"]["outcomes"],ensure_ascii=False)}\n\n{result["limitation"]}\n\n## 每局记录\n\n'
        text+='\n'.join(f'- 桌 {r["pod"]+1} 局 {r["game"]+1}：{r["outcome"]}；胜者 {r["winner"]}；回合 {r["turns"]}；日志 [{r["log"]}]({r["log"]})' for r in records)
        (out/'report.md').write_text(text+'\n',encoding='utf-8')
        with zipfile.ZipFile(out/'evidence.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for p in out.rglob('*'):
                if p.is_file() and p.name!='evidence.zip':archive.write(p,p.relative_to(out))
        return result
    finally:_lock.release()
