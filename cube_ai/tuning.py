"""Opt-in native calibration. Only measured, trace-compatible settings are used."""
import hashlib
import json
import os
import platform
import random
import re
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from .config import ROOT

PROFILE=ROOT/'private/performance-profile.json'
RUNS=ROOT/'private/tuning'
VERSION='native-tuning-2'
EVENT_COMPARISON='native-events-3-block-target-order'
JVM_PROFILES={
    'default':dict(heap_mib=2048,options=[]),
    'bounded_gc':dict(heap_mib=2048,options=['-XX:ActiveProcessorCount=2','-XX:ParallelGCThreads=1','-XX:ConcGCThreads=1']),
    'parallel_gc':dict(heap_mib=2048,options=['-XX:+UseParallelGC','-XX:ActiveProcessorCount=2','-XX:ParallelGCThreads=1']),
    'compact_heap':dict(heap_mib=1536,options=['-XX:ActiveProcessorCount=2','-XX:ParallelGCThreads=1','-XX:ConcGCThreads=1']),
    'parallel_small':dict(heap_mib=1536,options=['-XX:+UseParallelGC','-XX:ActiveProcessorCount=2','-XX:ParallelGCThreads=1']),
}


def machine_key():
    return [platform.system(),platform.machine(),platform.processor(),os.cpu_count()]


def engine_key(config):
    from .forge import _file_hash
    from .forge_worker import bridge_signature
    def digest(path):
        p=Path(path);s=p.stat();return _file_hash(str(p.resolve()),s.st_size,s.st_mtime_ns)
    result=[digest(config['jar']),digest(config['java']),config.get('backend','isolated'),bridge_signature()]
    from .forge_compat import signature
    if compat:=signature(config):result.append(compat)
    return result


def profile_for(config):
    try:
        value=json.loads(PROFILE.read_text(encoding='utf8'))
        if (value.get('version')==VERSION and value.get('machine')==machine_key()
            and value.get('engine')==engine_key(config) and value.get('adopted')
            and value.get('jvm_profile') in JVM_PROFILES and not JVM_PROFILES[value['jvm_profile']].get('experimental')
            and type(value.get('workers')) is int and 1<=value['workers']<=8):return value
    except (OSError,ValueError,KeyError,TypeError):pass
    return None


def recommendation(maximum):
    from .forge import configuration
    try:
        value=profile_for(configuration())
        # A memory-limited calibration cannot establish that its highest tested
        # concurrency remains optimal after more resources become available.
        if value and maximum>max(value.get('tested_workers',[value['workers']])) and value['workers']==max(value.get('tested_workers',[value['workers']])):
            return None
        return min(maximum,value['workers']) if value else None
    except (OSError,ValueError,KeyError):return None


def status():
    from .forge import configuration
    try:value=profile_for(configuration())
    except (OSError,ValueError,KeyError):value=None
    return dict(calibrated=bool(value),workers=value['workers'] if value else None,
        jvm_profile=value['jvm_profile'] if value else 'default',measured=value.get('measured') if value else None)


def apply(config):
    value=profile_for(config)
    if value:
        settings=JVM_PROFILES[value['jvm_profile']]
        config.update(heap_mib=settings['heap_mib'],jvm_options=list(settings['options']),calibrated_workers=value['workers'])
    return config


def canonical_attackers(event):
    """Normalize only one target's unordered printed attacker collection.

    Forge's GameEventAttackersDeclared converts its collection to HashMultimap.
    Keep full names, instance IDs and multiplicities. Never reorder events,
    blocker assignments, damage or declarations with an unrecognized layout.
    """
    if not event.startswith('Combat: ') or event.count(' to attack ')!=1:return event
    prefix,separator,rest=event.partition(' assigned ')
    if not separator or ' assigned ' in rest:return event
    body,separator,target=rest.partition(' to attack ')
    if not separator or not target.endswith('.') or not body.endswith(')'):return event
    markers=list(re.finditer(r'(?P<id>\(\d+\))(?P<separator>, | and |$)',body))
    if len(markers)<2 or markers[-1].end()!=len(body) or markers[-1]['separator']:return event
    cards=[];position=0
    for marker in markers:
        name=body[position:marker.start()]
        if not name.strip():return event
        cards.append(name+marker['id']);position=marker.end()
    return prefix+' assigned '+', '.join(sorted(cards))+' to attack '+target


def canonical_blockers(event):
    """Sort one controller's per-attacker statements inside one printed event.

    Forge copies the declaration to HashMap/HashMultimap. Preserve blocker
    lists, instances, targets, duplicates and other event order; fail closed
    on unknown player names, mixed controllers or incomplete layouts.
    """
    match=re.match(r"Combat: (Ai\(\d+\)-[A-Za-z0-9_-]+) (?=assigned |didn't block )",event)
    if not match:return event
    player=match[1];body=event[len('Combat: '):]
    ends=list(re.finditer(r"\(\d+\)\.(?="+re.escape(player)+r" (?:assigned |didn't block )|$)",body))
    if len(ends)<2 or ends[-1].end()!=len(body):return event
    statements=[];position=0
    for end in ends:
        statement=body[position:end.end()];position=end.end()
        if not statement.startswith(player+' '):return event
        content=statement[len(player)+1:]
        if content.startswith("didn't block "):target=content[len("didn't block "):]
        elif content.startswith('assigned '):
            if content.count(' to block ')!=1:return event
            blockers,_,target=content[len('assigned '):].partition(' to block ')
            markers=list(re.finditer(r'\(\d+\)(?:, | and |$)',blockers))
            if not markers or markers[-1].end()!=len(blockers):return event
            start=0
            for marker in markers:
                if not blockers[start:marker.start()].strip():return event
                start=marker.end()
        else:return event
        if not re.fullmatch(r'.+ \(\d+\)\.',target) or re.search(r'Ai\(\d+\)-',content):return event
        statements.append(statement)
    return 'Combat: '+''.join(sorted(statements))


def _canonical(log):
    from .optimize import log_events
    return [canonical_blockers(canonical_attackers(event)) for event in log_events(log) if not event.startswith('Game Outcome: Match Duration')]


def compatible(reference,records):
    if len(reference)!=len(records):return False
    return all((a['outcome'],a.get('winner'))==(b['outcome'],b.get('winner')) and
        (a['outcome'] not in {'win','draw'} or a['events_sha256']==b['events_sha256'])
        for a,b in zip(reference,records))


def baseline_check(phase):
    """Require a repeated unchanged control before comparing configurations."""
    result=dict(version='native-baseline-1',status='pending',repetitions=0,compared_games=0,unstable_games=[],abnormal_games=[])
    if not phase or not phase.get('runs'):return result
    runs=phase['runs'];reference=runs[0]
    result.update(workers=phase['workers'],jvm_profile=phase['jvm_profile'],repetitions=len(runs),compared_games=len(reference))
    if not reference:result['status']='incomplete';return result
    result['abnormal_games']=sorted({i for run in runs for i,r in enumerate(run) if r.get('outcome') not in {'win','draw'}})
    if result['abnormal_games']:result['status']='abnormal'
    elif not phase.get('same_native_backend') or any(r.get('cache_hit') for run in runs for r in run):result['status']='backend_mismatch'
    elif phase.get('resource_interrupted'):result['status']='incomplete'
    else:
        changed=set()
        for run in runs[1:]:
            for i in range(max(len(reference),len(run))):
                if i>=len(reference) or i>=len(run) or not compatible([reference[i]],[run[i]]):changed.add(i)
        result['unstable_games']=sorted(changed)
        result['status']='unstable' if changed else 'consistent' if len(runs)>=2 else 'insufficient_repetitions'
    return result


def phase_memory(phase):
    measured=phase.get('peak_engine_private_bytes')
    if measured:return measured
    # Older evidence sampled individual engines after completed games. Keep the
    # conservative worker-count estimate labelled separately from live totals.
    samples=[(r.get('engine_memory') or {}).get('private_bytes',0) for run in phase.get('runs',[]) for r in run]
    return max(samples,default=0)*phase['workers'] or None


def choose(phases,minimum_normal=5,goal='balanced'):
    """Require repeated measurements and exact normal-event agreement."""
    valid=[p for p in phases if p['compatible'] and len(p['seconds'])>=2 and p['normal_games']>=max(minimum_normal,.9*p.get('attempted_games',minimum_normal))]
    if not valid:return None
    if goal not in {'balanced','speed','memory'}:raise ValueError('测速目标无效')
    # Prefer fewer processes for differences within 5% of the best throughput.
    fastest=min(statistics.median(p['seconds']) for p in valid)
    if goal in {'balanced','memory'} and all(phase_memory(p) for p in valid):
        near=[p for p in valid if goal=='memory' or statistics.median(p['seconds'])<=fastest*1.15]
        least=min(phase_memory(p) for p in near)
        # Ignore tiny working-set differences; within 10% of the smallest
        # measured footprint prefer the faster configuration.
        economical=[p for p in near if phase_memory(p)<=least*1.10]
        return min(economical,key=lambda p:(statistics.median(p['seconds']),p['workers'],p['jvm_profile']))
    near=[p for p in valid if statistics.median(p['seconds'])<=fastest*1.05]
    return min(near,key=lambda p:(p['workers'],statistics.median(p['seconds']),p['jvm_profile']))


def profile_choices(requested,best,profile_name,snapshot=None):
    """Recheck full-heap capacity for the actual profile, before starting JVMs."""
    from .resources import system_memory,capacity
    settings=JVM_PROFILES[profile_name]
    memory=capacity(system_memory() if snapshot is None else snapshot,
                    heap_mib=settings['heap_mib'],ceiling=min(8,max(1,(os.cpu_count() or 1)//2)))
    allowed=[n for n in requested if n<=memory['capacity']]
    if not allowed:return [],memory
    # A smaller heap may permit another concurrent game. Test that boundary in
    # addition to the default profile winner, rather than fixing its old limit.
    return sorted({min(best,max(allowed)),max(allowed)} & set(allowed)),memory


def calibrate(catalog,rows,spec,progress=print,mode='quick',worker_choices=None,
              jvm_choices=None,repetitions=2,fixtures=None,apply_result=True,goal='balanced'):
    from .draft import draft_pod
    from .experiment import execution_resources
    from .forge import configuration,card_index,write_deck,engine_name,run_battle,forge_session
    from .forge_worker import close_all
    if mode not in {'quick','full'}:raise ValueError('校准档位无效')
    if goal not in {'balanced','speed','memory'}:raise ValueError('测速目标无效')
    if spec.mode!='commander' or spec.players!=3:raise ValueError('速度校准需要三人 Commander Cube')
    if type(repetitions)!=int or not 1<=repetitions<=3:raise ValueError('校准重复数需为 1–3')
    if type(apply_result) is not bool:raise ValueError('是否应用测速结果需为布尔值')
    if worker_choices is not None and not isinstance(worker_choices,(list,tuple)):raise ValueError('并行数范围需为列表')
    if jvm_choices is not None and not isinstance(jvm_choices,(list,tuple)):raise ValueError('引擎配置范围需为列表')
    with forge_session():
        resources=execution_resources();config=configuration()
        if config.get('backend')!='resident':raise ValueError('先安装并验证常驻 Forge，才能校准')
        maximum=resources['maximum']
        requested=worker_choices if worker_choices is not None else ([1,2,3,4] if mode=='quick' else [1,2,3,4,6,8])
        if not requested or any(type(n)!=int or not 1<=n<=8 for n in requested):raise ValueError('无效并行数')
        choices=sorted({n for n in requested if n<=maximum})
        if not choices:raise ValueError('当前资源不足以运行所选并行数')
        variants=jvm_choices if jvm_choices is not None else [name for name,settings in JVM_PROFILES.items() if not settings.get('experimental')]
        if not variants or any(not isinstance(n,str) or n not in JVM_PROFILES for n in variants):raise ValueError('无效引擎配置')
        if apply_result and any(JVM_PROFILES[n].get('experimental') for n in variants):raise ValueError('试验引擎配置只允许预览测速，不可自动应用')
        out=RUNS/(datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
        deck_dir=out/'decks';deck_dir.mkdir();index=card_index(config)
        tasks=[]
        if fixtures:
            source_dir,source_tasks=fixtures
            import shutil
            for p in Path(source_dir).glob('*.dck'):shutil.copyfile(p,deck_dir/p.name)
            tasks=[dict(order=t['order'],seed=t['seed']) for t in source_tasks]
        else:
            for p in range(2 if mode=='quick' else 6):
                seed=spec.seed+71000000+p*100
                pod=draft_pod(catalog,rows,spec,random.Random(seed),readiness_hands=0)
                if not all(d['buildable'] and all(engine_name(n,index) for n in d['spells']+d['lands']+[d['commander']]) for d in pod['decks']):
                    raise ValueError('校准轮抓含无法组牌或引擎未支持的牌；请先检查牌表')
                ids=[]
                for d in pod['decks']:
                    d['id']=f'calibration_{p}_{d["seat"]}';ids.append(d['id']);write_deck(d,deck_dir/(d['id']+'.dck'),index,catalog,spec)
                tasks.extend(dict(order=ids[r:]+ids[:r],seed=seed+r) for r in range(3))
        report=dict(version=VERSION,path=str(out),machine=machine_key(),engine=engine_key(config),phases=[],
            resources=resources,cache=False,fixture_games=len(tasks),adopted=False,goal=goal,profile_specific_concurrency=True,skipped_configurations=[],apply_requested=apply_result,event_comparison=EVENT_COMPARISON,
            note='同一批固定牌组与种子重复测速，不进入学习或独立强度样本。均衡模式在最快耗时15%以内优先低内存，内存相差10%以内再选更快设置；缺少内存数据时沿用速度对照。')
        def save():
            tmp=out/'report.tmp';tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(out/'report.json')
        reference=None;reference_phase=None
        def phase(workers,jvm):
            nonlocal reference,reference_phase
            settings=JVM_PROFILES[jvm]
            eligible,memory=profile_choices([workers],workers,jvm)
            if not eligible:
                report['skipped_configurations'].append(dict(workers=workers,jvm_profile=jvm,reason='当前空闲内存不足',memory=memory));save();return
            phase=dict(workers=workers,jvm_profile=jvm,seconds=[],runs=[],measurements=[],compatible=True,same_native_backend=True,normal_games=0,attempted_games=len(tasks),peak_engine_private_bytes=0,memory_budget_at_start=memory)
            report['phases'].append(phase)
            # Never reuse a JVM across different parameter sets or measurements.
            for repeat in range(repetitions):
                close_all()
                eligible,memory=profile_choices([workers],workers,jvm)
                if not eligible:
                    phase.update(resource_interrupted=True,compatible=False)
                    report['skipped_configurations'].append(dict(workers=workers,jvm_profile=jvm,repeat=repeat,
                        reason='重复测量前内存余量变化，当前配置已不满足预算；已完成记录保留',memory=memory))
                    progress(f'跳过未满足内存预算的后续测量：同时 {workers} 局，配置 {jvm}')
                    save();break
                folder=out/f'{jvm}_{workers}_{repeat}';folder.mkdir()
                c=dict(config,cache=False,heap_mib=settings['heap_mib'],jvm_options=settings['options'])
                progress(f'速度校准：同时 {workers} 局，配置 {jvm}，第 {repeat+1}/{repetitions} 轮')
                from . import task_control
                control=task_control._current
                paused_before=control.paused_seconds if control else 0
                start=time.perf_counter()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures=[pool.submit(run_battle,c,deck_dir,t['order'],t['seed'],90,folder,f'game_{i}.log') for i,t in enumerate(tasks)]
                    records=[]
                    for f in futures:
                        r=f.result();log=(folder/r['log']).read_text(encoding='utf8')
                        events=_canonical(log);r['events_sha256']=hashlib.sha256(json.dumps(events,ensure_ascii=False).encode()).hexdigest()
                        records.append(r)
                        from .forge_worker import memory_snapshot
                        memory=memory_snapshot()
                        phase['peak_engine_private_bytes']=max(phase['peak_engine_private_bytes'],sum(m.get('private_bytes',0) for m in memory))
                elapsed=time.perf_counter()-start
                paused=max(0,control.paused_seconds-paused_before) if control else 0
                interrupted=bool(paused or control and control.pause_started is not None)
                if reference is None:reference=records;reference_phase=phase
                phase['measurements'].append(dict(repeat=repeat,wall_seconds=elapsed,paused_seconds=paused,used_for_timing=not interrupted))
                if not interrupted:phase['seconds'].append(elapsed)
                phase['runs'].append(records)
                same_backend=all(isinstance(r.get('backend'),str) and r['backend'].startswith('resident') and not r.get('resident_fallback') for r in records)
                phase['same_native_backend'] &= same_backend
                phase['compatible'] &= compatible(reference,records) and same_backend
                phase['normal_games']=sum(r['outcome'] in {'win','draw'} for r in records)
                phase['median_seconds']=statistics.median(phase['seconds']) if phase['seconds'] else None
                report['reference_check']=baseline_check(reference_phase)
                close_all();save()
        def invalid_control():
            report['reference_check']=baseline_check(reference_phase)
            if report['reference_check']['status'] not in {'unstable','abnormal','backend_mismatch','incomplete'}:return False
            report.update(stopped_early=True,stop_reason='invalid_reference')
            progress('测速参考设置未通过重复检查，已停止后续对照并保留原设置；详情已保存。')
            save();return True
        try:
            for workers in choices:
                phase(workers,'default')
                if invalid_control():return report
            best=choose(report['phases'],goal=goal)
            best_workers=best['workers'] if best else choices[0]
            for jvm in variants:
                if jvm!='default':
                    tested,_=profile_choices(requested,best_workers,jvm)
                    for workers in tested:
                        phase(workers,jvm)
                        if invalid_control():return report
            selected=choose(report['phases'],goal=goal) if report.get('reference_check',{}).get('status')=='consistent' else None
            if selected and apply_result:
                by_profile={name:sorted({p['workers'] for p in report['phases'] if p['jvm_profile']==name}) for name in JVM_PROFILES}
                report.update(adopted=True,workers=selected['workers'],jvm_profile=selected['jvm_profile'],measured=datetime.now(timezone.utc).isoformat(),
                              tested_workers=by_profile[selected['jvm_profile']],tested_workers_by_profile=by_profile)
                value={k:report[k] for k in ['version','machine','engine','adopted','workers','jvm_profile','measured','tested_workers','event_comparison']}
                value['evidence']=out.name;value['goal']=goal;PROFILE.parent.mkdir(parents=True,exist_ok=True)
                tmp=PROFILE.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(PROFILE)
            elif selected:report['recommendation']=dict(workers=selected['workers'],jvm_profile=selected['jvm_profile'])
            save();return report
        finally:close_all()
