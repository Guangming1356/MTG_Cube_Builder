"""Native Forge AI games. Outcomes come exclusively from the rules engine."""
import hashlib
from contextlib import contextmanager
import json
import os
import random
import re
import subprocess
import threading
import time
import uuid
import tempfile
from functools import lru_cache
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT
from .draft import draft_pod
from .engine import audit
from .forge_setup import RUNTIME, sha256, write_profile
from .experiment import MAX_PODS, execution_resources
from .game_queue import GameQueue

MATCHES=ROOT/'matches'
_lock=threading.RLock()
_worker_state=threading.local()
_indices={}
INDEX_CACHE=RUNTIME/'cache/card-indices'
_campaign=threading.local()
BASICS=dict(W='Plains',U='Island',B='Swamp',R='Mountain',G='Forest',C='Wastes')

@contextmanager
def forge_session():
    """One campaign owns the machine budget, including selection/validation stages."""
    if not _lock.acquire(blocking=False):raise ValueError('已有 Forge 实战或改进任务，请等它完成')
    if not getattr(_campaign,'depth',0):_campaign.resources=None
    _campaign.depth=getattr(_campaign,'depth',0)+1
    try:yield
    finally:
        _campaign.depth-=1
        if not _campaign.depth:
            from .forge_worker import close_all
            close_all()
        _lock.release()

def campaign_resources(workers=0):
    reserved=getattr(_campaign,'resources',None) if getattr(_campaign,'depth',0) else None
    if reserved and type(workers)==int and workers in {0,reserved.get('requested',reserved['workers'])}:return dict(reserved)
    try:resources=execution_resources(workers)
    except ValueError:
        if not getattr(_campaign,'depth',0) or type(workers)!=int or not 1<=workers<=8:raise
        resources=execution_resources(0)
        resources.update(requested=workers,reduced_for_current_memory=True,
                         ceiling=min(workers,resources.get('ceiling',workers)))
    if getattr(_campaign,'depth',0):_campaign.resources=resources
    return resources

def worker_home(config,out):
    """Share read-only assets; isolate preferences, caches and rolling engine logs."""
    key=(str(Path(config['home']).resolve()),str(out.resolve()))
    cached=getattr(_worker_state,'home',None)
    if cached and cached[0]==key:return cached[1]
    home=out/'engine'/('worker_'+uuid.uuid4().hex[:10]);home.mkdir(parents=True)
    target=Path(config['home']).resolve()/'res';link=home/'res'
    if os.name=='nt':
        try:
            import _winapi
            _winapi.CreateJunction(str(target),str(link))
        except (ImportError,AttributeError):
            # Older or alternative Python runtimes keep the existing path.
            env=dict(os.environ,CUBE_SIM_LINK=str(link.absolute()),CUBE_SIM_TARGET=str(target))
            subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
                "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:CUBE_SIM_LINK -Target $env:CUBE_SIM_TARGET | Out-Null"],
                env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    else:link.symlink_to(target,target_is_directory=True)
    def escaped(path):
        return ''.join(c if ord(c)<128 else f'\\u{ord(c):04x}' for c in path.resolve().as_posix())
    (home/'forge.profile.properties').write_text(
        f'userDir={escaped(home/"userdata")}\ncacheDir={escaped(home/"cache")}\n',encoding='ascii')
    _worker_state.home=(key,home)
    return home

def evidence_files(out):
    # Do not follow shared resource junctions or package disposable JVM caches.
    for root,dirs,files in os.walk(out,followlinks=False):
        dirs[:]=[d for d in dirs if d!='engine']
        for name in files:
            if name!='evidence.zip':yield Path(root)/name

def configuration(compatibility_mode=None):
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
    value['backend']='isolated'
    st=Path(value['jar']).stat();actual=_file_hash(value['jar'],st.st_size,st.st_mtime_ns)
    value['jar_sha256']=actual
    try:
        from .forge_worker import available,bridge_signature
        verified=json.loads((RUNTIME/'acceleration/resident-validation.json').read_text(encoding='utf8'))
        if available() and verified.get('passed') and verified.get('jar_sha256')==actual and verified.get('bridge_sha256')==bridge_signature():
            value['backend']='resident'
    except (OSError,ValueError,KeyError):pass
    from .forge_compat import apply as compatibility
    value=compatibility(value,mode=compatibility_mode)
    from .tuning import apply
    return apply(value)

def status():
    try:
        config=configuration()
        return dict(available=True,version=config['version'],pilot='Forge 原生 AI',seed_supported=True,backend=config['backend'],compatibility=config.get('compatibility'))
    except (ValueError,OSError,KeyError,json.JSONDecodeError) as e:
        return dict(available=False,reason=str(e))


def engine_description(config):
    from .tuning import engine_key
    return dict(version=config['version'],jar_sha256=config.get('jar_sha256'),java=config.get('java'),backend=config.get('backend','isolated'),
                pilot='Forge native AI',rng='Forge -s',fingerprint=engine_key(config),compatibility=config.get('compatibility'))

def card_index(config):
    from .forge_card_names import INDEX_VERSION,ASSET_SHA,script_names,verified_runtime_aliases,manifest_available
    home=Path(config['home']);folder=home/'res'/'cardsfolder'
    loose=list(folder.rglob('*.txt')) if folder.is_dir() else []
    archives=[p for p in (home/'res').rglob('*.zip') if 'card' in p.name.lower()]
    editions=list((home/'res/editions').rglob('*.txt'))
    sources=sorted((str(p.relative_to(home)),p.stat().st_size,p.stat().st_mtime_ns) for p in loose+archives+editions)
    # Cached aliases must also stop working when their pinned manifest is gone
    # or modified, even if all native script metadata is unchanged.
    key=hashlib.sha256(json.dumps([INDEX_VERSION,ASSET_SHA,manifest_available(),str(home.resolve()),config.get('jar_sha256'),sources]).encode()).hexdigest()
    if key in _indices:return _indices[key]
    cache=INDEX_CACHE/(key+'.json')
    try:
        saved=json.loads(cache.read_text(encoding='utf8'))
        names=saved.get('names')
        if (saved.get('signature')==key and isinstance(names,dict) and names
                and all(isinstance(k,str) and isinstance(v,str) and v for k,v in names.items())):
            _indices[key]=names
            if len(_indices)>4:_indices.pop(next(iter(_indices)))
            return names
    except (OSError,ValueError,AttributeError):pass
    names={}
    verified=verified_runtime_aliases(config,archives,loose,editions)
    def add(raw):
        found=script_names(raw)
        if not found:return
        first=found[0]
        names[first.casefold()]=first
        names.setdefault(first.split(' // ')[0].casefold(),first)
        for alias in found[1:]:
            if alias in verified:names.setdefault(alias.casefold(),alias)
    for p in loose:add(p.read_bytes())
    for p in archives:
        with zipfile.ZipFile(p) as archive:
            for n in archive.namelist():
                if n.endswith('.txt'):add(archive.read(n))
    if not names:raise ValueError('运行时没有找到 Forge 牌张脚本')
    _indices[key]=names
    if len(_indices)>4:_indices.pop(next(iter(_indices)))
    try:
        INDEX_CACHE.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='index-',suffix='.tmp',dir=INDEX_CACHE)
        try:
            with os.fdopen(fd,'w',encoding='utf8') as stream:json.dump(dict(signature=key,names=names),stream,ensure_ascii=False)
            os.replace(tmp,cache)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        # Only generated cache files are evicted; never touch engine/user files.
        for old in sorted(INDEX_CACHE.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[8:]:
            try:old.unlink()
            except OSError:pass
    except OSError:pass
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

def diagnose_log(log):
    """Explain engine symptoms without blaming a card or changing outcomes."""
    findings=[]
    def add(code,message,hint,severity='error'):
        findings.append(dict(code=code,message=message,hint=hint,severity=severity))
    if 'getActivatingPlayer()' in log and 'is null' in log and 'CharmEffect.' in log:
        add('null_modal_activator','Forge AI 评估模式目标时缺少施放者',
            '这是引擎内部异常，不能当作正常胜负，也不能仅凭同桌出现就认定某张牌有问题。降低并行数不一定能修复；保留日志供复现。')
    if 'OutOfMemoryError' in log or 'Could not reserve enough space' in log:
        add('engine_memory','引擎无法分配所需内存','先减少同时进行的对局，再检查剩余内存；此局不纳入正常胜负。')
    if 'TimeoutException' in log and 'Stopping slow match as draw' not in log:
        add('ai_choice_timeout','Forge AI 的单次行动选择超时',
            '这与整局时限不同。可能是复杂决策或异常循环，不能把日志最后的胜者直接视为可靠实战证据。')
    apis=sorted(set(re.findall(r'No AI assigned for API: (\w+)',log)))
    if apis:
        add('missing_ai_api','引擎提示缺少 AI 驾驶逻辑：'+', '.join(apis[:8]),
            '牌张有规则实现不等于 AI 能正确使用。此提示本身不改变原始结果分类，也不代表人类使用时牌张较弱。','warning')
    return findings


def parse_log(log,returncode=0,process_timeout=False):
    """Engine failures and time limits are never counted as ordinary wins/draws."""
    duration=re.search(r'Game Result: Game \d+ ended (?:in a Draw! Took |in )(\d+) ms',log)
    turn_numbers=[int(n) for n in re.findall(r'\bTurn\s+(\d+)\b',log,re.I)]
    base=dict(engine_ms=int(duration.group(1)) if duration else None,diagnostics=diagnose_log(log),
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
    from .task_control import native_activity,record_game
    with native_activity():
        record=_cached_battle(config,deck_dir,order,seed,clock_seconds,out,log_name)
        record_game(record,out)
        return record


def _cached_battle(config,deck_dir,order,seed,clock_seconds,out,log_name):
    from .sim_cache import key,get,put
    from .forge_compat import signature
    compat=signature(config)
    cache_key=None
    if config.get('cache',True) and config.get('version')!='external' and (not config.get('extra_classpath') or compat):
        def fingerprint(p):
            p=Path(p);s=p.stat();return _file_hash(str(p.resolve()),s.st_size,s.st_mtime_ns)
        from .forge_worker import bridge_signature
        identity=['native-cache-2',fingerprint(config['jar']),fingerprint(config['java']),
            bridge_signature() if config.get('backend')=='resident' else '',
            config.get('backend','isolated'),config.get('heap_mib',2048),config.get('jvm_options',[]),order,seed,clock_seconds,
            [fingerprint(deck_dir/(n+'.dck')) for n in order]]
        if compat:identity.extend(['compatibility',compat])
        cache_key=key('game',identity)
        cached=get(cache_key)
        if cached and isinstance(cached.get('record'),dict) and isinstance(cached.get('log'),str) and cached['record'].get('outcome') in {'win','draw'}:
            (out/log_name).write_text(cached['log'],encoding='utf8')
            return dict(cached['record'],log=log_name,wall_seconds=0.0,cache_hit=True,
                original_wall_seconds=cached['record']['wall_seconds'],diagnostics=diagnose_log(cached['log']))
    record=_run_battle(config,deck_dir,order,seed,clock_seconds,out,log_name)
    record['cache_hit']=False
    if cache_key and record['outcome'] in {'win','draw'}:
        put(cache_key,dict(record=record,log=(out/log_name).read_text(encoding='utf8')),'game')
    return record

@lru_cache(maxsize=128)
def _file_hash(path,size,mtime):return sha256(Path(path))

def _run_battle(config,deck_dir,order,seed,clock_seconds,out,log_name):
    """One native game, usable for both a draft pod and controlled cross-Cube matches."""
    fallback=None
    if config.get('backend')=='resident':
        from .forge_worker import run,WorkerUnavailable
        def fresh_home(c,o):
            _worker_state.home=None
            return worker_home(c,o)
        try:
            value=run(config,fresh_home,deck_dir,order,seed,clock_seconds,out,log_name)
            log=value.pop('log_text');timeout=value.pop('process_timeout')
            value.update(order=order,seed=seed,log=log_name,**parse_log(log,value['returncode'],timeout))
            if value['outcome']=='win' and value['winner'] not in order:
                value.update(outcome='unrecognized',error='获胜牌组与提交牌组不匹配',winner=None)
            return value
        except WorkerUnavailable as e:
            fallback=str(e) # Startup unavailable: the untouched native CLI is the fallback.
    command=[config['java'],f'-Xmx{config.get("heap_mib",2048)}m',*config.get('jvm_options',[]),'-Dfile.encoding=UTF-8','-Djava.awt.headless=true']
    if config.get('extra_classpath'):
        # -cp does not apply the JAR's manifest module declarations. Preserve
        # exactly the reviewed native entry declarations when adding an overlay.
        command += ['--add-opens='+name+'=ALL-UNNAMED' for name in config.get('native_add_opens',[])]
        command += ['-cp',os.pathsep.join([*config['extra_classpath'],config['jar']]),config['native_main_class']]
    else:command += ['-jar',config['jar']]
    command += ['sim','-D',str(deck_dir.resolve()),'-d',*[n+'.dck' for n in order],
        '-f','Commander','-n','1','-s',str(seed),'-c',str(clock_seconds)]
    home=worker_home(config,out)
    started=time.monotonic();timeout=False
    try:
        process=subprocess.run(command,cwd=home,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            timeout=clock_seconds+90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        log=process.stdout.decode('utf-8',errors='replace');code=process.returncode
    except subprocess.TimeoutExpired as e:
        log=(e.stdout or b'').decode('utf-8',errors='replace');code=-1;timeout=True
    (out/log_name).write_text(log,encoding='utf-8')
    record=dict(order=order,seed=seed,command=command,log=log_name,
        backend='isolated',resident_fallback=fallback,
        wall_seconds=round(time.monotonic()-started,3),worker_directory=str(home.relative_to(out)),
        returncode=code,**parse_log(log,code,timeout))
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
    completed_pods={r['pod'] for r in records if r.get('pod') is not None and r['outcome'] in {'win','draw'}}
    independent={g:len({p['pod'] for p in pods if p.get('pod') in completed_pods and
        any(d.get('buildable') and d.get('identity')==g for d in p['decks'])}) for g in groups}
    diagnostics=Counter(finding['code'] for record in records for finding in record.get('diagnostics',[]))
    return dict(outcomes=dict(outcomes),games=len(records),completed=outcomes['win']+outcomes['draw'],diagnostics=dict(diagnostics),
        executed_games=sum(not r.get('cache_hit') for r in records),reused_games=sum(bool(r.get('cache_hit')) for r in records),
        completed_draft_pods=len(completed_pods),independent_pods_by_guild=independent,
        guilds={g:dict(c,win_rate=round(c['wins']/c['appearances'],3),wilson95=wilson(c['wins'],c['appearances'])) for g,c in sorted(groups.items())},
        median_turns=__import__('statistics').median([r['turns'] for r in records if r['turns'] is not None and r['outcome'] in {'win','draw'}]) if any(r['turns'] is not None and r['outcome'] in {'win','draw'} for r in records) else None)

def simulate(catalog,rows,spec,pods=10,games_per_pod=3,clock_seconds=90,progress=lambda _:None,
             pod_seeds=None,preferred_guilds=None,workers=0):
    if spec.mode!='commander' or spec.players!=3:raise ValueError('当前 Forge 集成针对三人 Commander Cube')
    if type(pods)!=int or not 1<=pods<=MAX_PODS:raise ValueError(f'实战轮抓桌数需为 1–{MAX_PODS}')
    if type(games_per_pod)!=int or not 3<=games_per_pod<=30 or games_per_pod%3:raise ValueError('每桌对局数需为 3–30 且是 3 的倍数，以轮换座位')
    if type(clock_seconds)!=int or not 15<=clock_seconds<=300:raise ValueError('单局时限需为 15–300 秒')
    resources=campaign_resources(workers);workers=resources['workers']
    if pod_seeds is not None and (not isinstance(pod_seeds,list) or len(pod_seeds)!=pods or any(type(s)!=int for s in pod_seeds)):raise ValueError('每桌随机种子数量无效')
    if preferred_guilds is not None:
        from .config import GUILDS
        if not isinstance(preferred_guilds,list) or len(preferred_guilds)!=pods or any(not isinstance(g,list) or len(g)!=3 or any(n not in GUILDS for n in g) for g in preferred_guilds):raise ValueError('每桌需指定三个有效双色身份')
    if audit(catalog,rows,spec)['hard_errors']:raise ValueError('请先修复牌表中的硬性错误')
    config=configuration();index=card_index(config);support=coverage(rows,config)
    if support['missing']:progress('Forge 尚未支持：'+', '.join(support['missing'][:15])+'；若实际组入牌组，整桌跳过并记录，不换牌')
    # Reserve a bounded machine budget for the entire campaign.
    if not _lock.acquire(blocking=False):raise ValueError('已有 Forge 实战任务，请等它完成')
    try:
        match_id=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
        out=MATCHES/match_id;out.mkdir(parents=True)
        deck_dir=out/'decks';deck_dir.mkdir();records=[];tables=[];rng=random.Random(spec.seed)
        started=time.monotonic();draft_seconds=0;submitted=0;peak_pending=0
        cube_hash=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
        with GameQueue(resources,config,progress) as pool:
            def collect(block=False):
                completed=pool.collect(block)
                for (p,g),value in completed:
                    record=dict(pod=p,game=g,**value);records.append(record)
                    progress(f'Forge 已完成 {len(records)}/{submitted} 局；已组牌 {len(tables)}/{pods} 桌；当前目标同时 {pool.target} 局：{record["outcome"]}')
                if completed:
                    from .task_control import atomic_json
                    atomic_json(out/'games.json',sorted(records,key=lambda r:(r['pod'],r['game'])))
            for p in range(pods):
                # Backpressure bounds queued JVM jobs and keeps results/progress flowing.
                while len(pool)>=pool.ceiling*2:collect(True)
                progress(f'轮抓与对局并行：组牌第 {p+1}/{pods} 桌；已完成 {len(records)} 局')
                draft_started=time.monotonic()
                pod_rng=random.Random(pod_seeds[p]) if pod_seeds is not None else rng
                pod=draft_pod(catalog,rows,spec,pod_rng,preferred_guilds[p] if preferred_guilds is not None else None);pod['pod']=p
                pod['draft_seed']=pod_seeds[p] if pod_seeds is not None else None
                for d in pod['decks']:
                    d['id']=f'p{p:03d}_s{d["seat"]}_{d.get("identity","none")}'
                    if d['buildable']:
                        d['unsupported']=[n for n in d['spells']+d['lands']+[d['commander']] if not engine_name(n,index)]
                        d['engine_supported']=not d['unsupported']
                        if d['engine_supported']:d['export']=write_deck(d,deck_dir/(d['id']+'.dck'),index,catalog,spec)
                tables.append(pod);draft_seconds+=time.monotonic()-draft_started
                if not all(d['buildable'] and d.get('engine_supported') for d in pod['decks']):
                    pod['skip_reason']='无指挥官或组入了 Forge 未实现的牌'
                    progress('整桌因无指挥官或包含未实现牌而跳过；保留真实轮抓，不换牌组');continue
                ids=[d['id'] for d in pod['decks']]
                for game in range(games_per_pod):
                    while len(pool)>=pool.ceiling*2:collect(True)
                    rotation=game%3;order=ids[rotation:]+ids[:rotation]
                    seed=(pod_seeds[p] if pod_seeds is not None else spec.seed+p*10000)+game
                    pool.submit((p,game),run_battle,config,deck_dir,order,seed,clock_seconds,out,f'pod{p:03d}_game{game:03d}.log')
                    submitted+=1
                    peak_pending=max(peak_pending,len(pool))
                collect()
            while pool:collect(True)
            scheduling=pool.report()
        workers=max(1,scheduling['peak_active'])
        records.sort(key=lambda r:(r['pod'],r['game']))
        from .brackets import cube_report
        result=dict(match_id=match_id,path=str(out),engine=engine_description(config),spec=spec.to_dict(),cube_sha256=cube_hash,
            coverage=support,pods=pods,games_per_pod=games_per_pod,clock_seconds=clock_seconds,seed=spec.seed,
            rules=dict(players=3,deck_minimum=60,deck_total_exported=60,commander_in_total=True,starting_life=40,
                free_basic_lands=True,land_count='按曲线与可用牌决定，不固定 22 张',rounds=spec.rounds,
                pack_size=spec.pack_size,pick_count=spec.pick_count,discard_after_pass=spec.discard_after_pass),
            tables=tables,games=records,summary=summarize(records,tables),workers=workers,bracket=cube_report(catalog,rows,spec),
            execution=dict(resources,wall_seconds=round(time.monotonic()-started,3),draft_seconds=round(draft_seconds,3),
                game_wall_seconds_sum=round(sum(r['wall_seconds'] for r in records),3),peak_pending=peak_pending,
                isolated_worker_directories=True,scheduling=scheduling),
            pod_seeds=pod_seeds,preferred_guilds=preferred_guilds,
            skipped_pods=sum('skip_reason' in p for p in tables),
            limitation='真实 Forge 规则引擎对局，使用 Forge 原生 AI。胜率反映这套抓牌、组牌与驾驶策略；原生 AI 对控制、组合技和多人政治有偏差。小样本及同桌重复对局不能证明色组平衡；Wilson 区间仅为描述性参考。超时与引擎错误不计作正常和局或胜负。')
        (out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'cube.json').write_text(json.dumps(dict(cards=rows,spec=spec.to_dict()),ensure_ascii=False,indent=2),encoding='utf-8')
        text=f'# Forge 实战报告\n\n- 引擎：{config["version"]}，Forge 原生 AI\n- 轮抓：{pods} 桌；每桌 {games_per_pod} 局，轮换三个座位\n- 牌组：60 张含指挥官，基本地自由补入，40 点生命\n- 正常完成：{result["summary"]["completed"]}/{len(records)} 局\n- 结果：{json.dumps(result["summary"]["outcomes"],ensure_ascii=False)}\n\n{result["limitation"]}\n\n## 每局记录\n\n'
        text+='\n'.join(f'- 桌 {r["pod"]+1} 局 {r["game"]+1}：{r["outcome"]}；胜者 {r["winner"]}；回合 {r["turns"]}；日志 [{r["log"]}]({r["log"]})' for r in records)
        (out/'report.md').write_text(text+'\n',encoding='utf-8')
        with zipfile.ZipFile(out/'evidence.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for p in evidence_files(out):archive.write(p,p.relative_to(out))
        return result
    finally:
        if not getattr(_campaign,'depth',0):
            from .forge_worker import close_all
            close_all()
        _lock.release()
