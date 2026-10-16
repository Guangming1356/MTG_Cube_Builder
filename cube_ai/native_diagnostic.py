"""Replay one saved game through both native entries; never training data."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import uuid
import zipfile

from .config import ROOT
from .forge import configuration,diagnose_log,evidence_files,forge_session,run_battle
from .task_control import atomic_json

DIAGNOSTICS=ROOT/'private/native-diagnostics'
VERSION='native-entry-diagnostic-1'


def validate_case(source_type,source_id,game_index):
    if source_type not in {'match','study'}:raise ValueError('诊断来源无效')
    if not isinstance(source_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',source_id):raise ValueError('诊断记录编号无效')
    if type(game_index) is not int or not 0<=game_index<3600:raise ValueError('诊断局序号无效')


def load_case(source_type,source_id,game_index):
    validate_case(source_type,source_id,game_index)
    folder=(ROOT/'matches' if source_type=='match' else ROOT/'private/deck-studies')/source_id
    report=json.loads((folder/'report.json').read_text(encoding='utf8'))
    games=report.get('games',[])
    if game_index>=len(games):raise ValueError('该局记录不存在')
    game=games[game_index];order=game.get('order')
    if not isinstance(order,list) or len(order)!=3 or any(not isinstance(n,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,119}',n) for n in order) or len(set(order))!=3:raise ValueError('该局牌组标识无效')
    log=game.get('log','')
    if not isinstance(log,str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.log',log):raise ValueError('该局日志标识无效')
    if type(game.get('seed')) is not int:raise ValueError('该局缺少可复现的随机种子')
    if any(not (folder/'decks'/(n+'.dck')).is_file() for n in order):raise ValueError('原始牌组文件已不在本机，无法精确复现')
    return folder,report,game


def compare_entries(source_type,source_id,game_index,progress=lambda _:None):
    folder,source,original=load_case(source_type,source_id,game_index)
    clock=source.get('clock_seconds',180)
    if type(clock) is not int or not 15<=clock<=300:clock=180
    from .tuning import apply,engine_key
    from .forge_worker import available,close_all
    config=apply(configuration())
    if not available():raise ValueError('需要已验证的常驻桥接组件才能比较两种入口')
    config['cache']=False
    id_=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    out=DIAGNOSTICS/id_;decks=out/'decks';decks.mkdir(parents=True)
    expected={}
    for table in source.get('tables',[]):
        groups=table.get('policies',{}).values() if table.get('policies') else [table.get('decks',[])]
        for group in groups:
            for deck in group:
                if deck.get('id') and deck.get('export',{}).get('sha256'):expected[deck['id']+'.dck']=deck['export']['sha256']
    files={}
    for name in original['order']:
        path=decks/(name+'.dck');shutil.copyfile(folder/'decks'/path.name,path)
        files[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name in expected and files[path.name]!=expected[path.name]:raise ValueError('保存的牌组文件已发生变化，未进行原牌组复现')
    original_diagnostics=diagnose_log((folder/original['log']).read_text(encoding='utf8',errors='replace'))
    result=dict(diagnostic_id=id_,version=VERSION,state='running',source=dict(type=source_type,id=source_id,game_index=game_index),
        original=dict(outcome=original['outcome'],diagnostics=original_diagnostics,engine=source.get('engine')),
        order=original['order'],seed=original['seed'],clock_seconds=clock,deck_sha256=files,
        original_deck_hashes_verified=all(name in expected for name in files),
        current_engine=dict(fingerprint=engine_key(config),compatibility=config.get('compatibility'),heap_mib=config.get('heap_mib',2048),jvm_options=config.get('jvm_options',[])),
        training_samples_added=0,games=[],limitation='已知个案的入口诊断，不是新的牌力测试；不修改原记录、牌组或 Cube，不自动排除任何卡牌。引擎或机器负载变化可能影响复现。')
    if not result['original_deck_hashes_verified']:
        result['limitation']+=' 原报告缺少部分牌组校验值，仅复制当前保存文件，无法确认它们从未修改。'
    atomic_json(out/'report.json',result);started=time.monotonic()
    with forge_session():
        for backend,label in [('resident','常驻入口'),('isolated','Forge 原生命令入口')]:
            progress(f'使用同一牌组与种子复现：{label}；单局引擎时限 {clock} 秒，启动与回收另计')
            # Keep only one engine's memory live. A fresh CLI JVM has no resident
            # worker state and supplies the control for bridge contamination.
            close_all();current=dict(config,backend=backend)
            record=run_battle(current,decks,original['order'],original['seed'],clock,out,backend+'.log')
            result['games'].append(dict(requested_backend=backend,**record));atomic_json(out/'report.json',result)
    codes=lambda findings:{f['code'] for f in findings if f.get('severity')=='error'}
    original_codes=codes(original_diagnostics)
    shared=original_codes.copy()
    for game in result['games']:shared&=codes(game.get('diagnostics',[]))
    distinct=result['games'][0].get('backend','').startswith('resident') and result['games'][1].get('backend')=='isolated'
    result.update(state='done',wall_seconds=time.monotonic()-started,common_error_symptoms=sorted(shared),distinct_entries=distinct,
        reproduced_both=bool(shared and distinct),
        interpretation='常驻入口回退或返回方式异常，没有获得两种独立入口的有效对照；请先检查启动日志。' if not distinct else
            '两种入口均出现原有异常症状，证据更支持 Forge/AI 相关问题，不能仅归因于常驻桥接。未定位具体卡牌或声称已修复。' if shared else
            '两种入口均正常完成，本次未复现；不能仅据此断言原问题已修复。' if all(g['outcome'] in {'win','draw'} for g in result['games']) else
            '入口间的复现情况不一致，需结合日志继续定位；不将诊断中的胜负用于牌力结论。')
    atomic_json(out/'report.json',result)
    lines=['# 对局入口诊断','',result['interpretation'],'',
           f'同一牌组文件、顺序与种子；两种入口各一局，单局时限 {clock} 秒；不复用比赛缓存。','']
    for game in result['games']:
        lines.extend([f'- {game["requested_backend"]}：{game["outcome"]}，日志 {game["log"]}。'])
        lines.extend('  - '+finding['message'] for finding in game.get('diagnostics',[]))
    lines.extend(['',result['limitation']]);(out/'report.md').write_text('\n'.join(lines),encoding='utf8')
    with zipfile.ZipFile(out/'evidence.zip','w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
        for path in evidence_files(out):archive.write(path,path.relative_to(out))
    return result
