import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import pytest
from cube_ai.task_control import TaskControl,atomic_json
from cube_ai.task_process import ProcessTree
from cube_ai.server import Application


def until(predicate,seconds=15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.05)
    raise AssertionError('等待状态超时')


def test_pause_drains_current_native_and_blocks_new_work(tmp_path,monkeypatch):
    from cube_ai import forge_worker
    trims=[]
    monkeypatch.setattr(forge_worker,'trim_idle',lambda limit:trims.append(limit))
    control=TaskControl(tmp_path);atomic_json(tmp_path/'command.json',dict(action='run'))
    started=threading.Event();finish=threading.Event();resumed=threading.Event()
    def game():
        with control.native():
            started.set();finish.wait(5);control.record(dict(outcome='win'),tmp_path)
    first=threading.Thread(target=game);first.start();assert started.wait(2)
    atomic_json(tmp_path/'command.json',dict(action='pause'))
    waiter=threading.Thread(target=lambda:(control.checkpoint(),resumed.set()));waiter.start()
    time.sleep(.15);assert not resumed.is_set() and control.pause_started is None
    assert trims==[]
    finish.set();first.join(2)
    until(lambda:(tmp_path/'progress.json').exists())
    assert json.loads((tmp_path/'progress.json').read_text(encoding='utf8'))['state']=='paused'
    assert len((tmp_path/'completed-games.jsonl').read_text().splitlines())==1
    assert trims==[0]
    atomic_json(tmp_path/'command.json',dict(action='run'));waiter.join(2);assert resumed.is_set()


def test_process_tree_termination_kills_descendants_and_preserves_other_process(tmp_path):
    tree=ProcessTree();start=tmp_path/'start';pidfile=tmp_path/'child'
    script="import pathlib,sys,time,subprocess; p=pathlib.Path(sys.argv[1]);\nwhile not p.exists(): time.sleep(.02)\nc=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);pathlib.Path(sys.argv[2]).write_text(str(c.pid));time.sleep(60)"
    sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    process=subprocess.Popen([sys.executable,'-c',script,str(start),str(pidfile)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
    try:
        tree.assign(process);start.touch();until(pidfile.exists)
        child=int(pidfile.read_text())
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes as w
            api=ctypes.WinDLL('kernel32');api.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];api.OpenProcess.restype=w.HANDLE
            api.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];api.CloseHandle.argtypes=[w.HANDLE]
            handle=api.OpenProcess(0x100000,False,child);assert handle
            try:tree.terminate(process);assert api.WaitForSingleObject(handle,5000)==0
            finally:api.CloseHandle(handle)
        else:tree.terminate(process)
        process.wait(timeout=5);assert sentinel.poll() is None
    finally:
        tree.close()
        if process.poll() is None:process.kill();process.wait(timeout=5)
        sentinel.kill();sentinel.wait(timeout=5)


def test_isolated_job_pause_resume_complete_and_cancel(tmp_path):
    app=Application(isolated_jobs=True)
    rows,unknown=app.catalog.parse((Path(__file__).parent/'fixtures/forge_cube.csv').read_text(encoding='utf-8-sig'));assert not unknown
    try:
        id_=app.submit(dict(operation='stress',cards=rows,trials=5))['job_id']
        app.control(id_,'pause');until(lambda:app.jobs[id_]['state']=='paused',30)
        time.sleep(.2);assert app.jobs[id_]['state']=='paused'
        app.control(id_,'resume');until(lambda:app.jobs[id_]['state'] in {'done','failed'},60)
        assert app.jobs[id_]['state']=='done',app.jobs[id_]
        assert app.jobs[id_]['result']['trials']==5
        second=app.submit(dict(operation='stress',cards=rows,trials=500))['job_id']
        app.control(second,'pause');until(lambda:app.jobs[second]['state']=='paused',30)
        process=app.controls[second].process;app.control(second,'cancel')
        until(lambda:app.jobs[second]['state']=='cancelled',5)
        assert process.poll() is not None
        assert app.jobs[id_]['state']=='done'
    finally:app.shutdown()


def test_queued_cancel_is_immediate_and_controls_validate():
    app=Application(isolated_jobs=True)
    gate=threading.Event()
    a=app.executor.submit(gate.wait);b=app.executor.submit(gate.wait)
    try:
        id_=app.submit(dict(operation='learn-games'))['job_id']
        assert app.control(id_,'cancel')['state']=='cancelled'
        assert app.controls[id_].process is None
        with pytest.raises(ValueError):app.control(id_,'delete')
        with pytest.raises(ValueError):app.control('missing','pause')
    finally:gate.set();a.result(2);b.result(2);app.shutdown()


def test_second_native_campaign_is_rejected_while_paused(monkeypatch):
    app=Application();app.jobs['existing']=dict(operation='forge',state='paused')
    try:
        with pytest.raises(ValueError,match='已有实战'):
            app.submit(dict(operation='forge',cards=[dict(name='Sun Titan',role='Main')]))
    finally:app.executor.shutdown(wait=True)


@pytest.mark.skipif(os.name!='nt',reason='Windows 旧后台兼容入口')
def test_legacy_stop_targets_only_verified_test_process(monkeypatch):
    from cube_ai import legacy_tasks
    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        monkeypatch.setattr(legacy_tasks,'health',lambda port:dict(pid=process.pid,task_controls=False))
        with pytest.raises(ValueError):legacy_tasks.stop('legacy_9999')
        assert process.poll() is None
        result=legacy_tasks.stop('legacy_8779')
        assert result['state']=='cancelled';process.wait(timeout=5)
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
