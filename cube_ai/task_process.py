"""Own one complete task process tree. Never terminate a shared server or PID name."""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from .config import ROOT,WORKSPACE
from .task_control import atomic_json

JOBS=ROOT/'private/jobs'
ACTIVE={'queued','running','pausing','paused','cancelling'}


class ProcessTree:
    def __init__(self):
        self.handle=None
        if os.name=='nt':
            from ctypes import wintypes as w
            api=ctypes.WinDLL('kernel32',use_last_error=True);self.api=api
            api.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];api.CreateJobObjectW.restype=w.HANDLE
            api.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
            api.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
            api.TerminateJobObject.argtypes=[w.HANDLE,w.UINT];api.CloseHandle.argtypes=[w.HANDLE]
            class Basic(ctypes.Structure):
                _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',w.DWORD),
                    ('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('process_limit',w.DWORD),
                    ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
            class IO(ctypes.Structure):_fields_=[(n,ctypes.c_uint64) for n in ['read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes']]
            class Extended(ctypes.Structure):
                _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                    ('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]
            self.handle=api.CreateJobObjectW(None,None)
            if not self.handle:raise OSError(ctypes.get_last_error(),'无法创建任务进程组')
            info=Extended();info.basic.flags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not api.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
                self.close();raise OSError(ctypes.get_last_error(),'无法配置任务进程组')

    def assign(self,process):
        if self.handle and not self.api.AssignProcessToJobObject(self.handle,int(process._handle)):
            raise OSError(ctypes.get_last_error(),'无法隔离任务进程；未开始计算')

    def terminate(self,process):
        if self.handle:
            if not self.api.TerminateJobObject(self.handle,2):raise OSError(ctypes.get_last_error(),'未能结束任务进程组')
        elif process and process.poll() is None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass

    def close(self):
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None


class TaskProcess:
    def __init__(self,id_,request,settings_path=None):
        self.folder=JOBS/id_;self.folder.mkdir(parents=True,exist_ok=False)
        self.lock=threading.RLock();self.process=None;self.tree=None;self.cancelled=False;self.action='run'
        self.request=request;self.settings_path=settings_path
        atomic_json(self.folder/'command.json',dict(action='run'))

    def command(self,action):
        with self.lock:
            self.action=action
            atomic_json(self.folder/'command.json',dict(action=action))
            if action=='cancel':
                self.cancelled=True
                if self.process and self.tree:self.tree.terminate(self.process)

    def run(self,update):
        with self.lock:
            if self.cancelled:return dict(state='cancelled',progress='已强制结束')
            atomic_json(self.folder/'input.json',dict(request=self.request,settings_path=str(self.settings_path) if self.settings_path else None))
            self.tree=ProcessTree()
            executable=Path(sys.executable)
            if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
            log=(self.folder/'worker.log').open('ab')
            try:
                self.process=subprocess.Popen([str(executable),'-X','utf8','-m','cube_ai.task_worker',str(self.folder.resolve())],
                    cwd=WORKSPACE,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
                # Child waits for this handshake before importing/launching any engine.
                self.tree.assign(self.process);(self.folder/'start').touch()
            except BaseException:
                if self.process and self.process.poll() is None:self.process.kill();self.process.wait(timeout=5)
                self.tree.close();log.close();raise
        update(dict(worker_pid=self.process.pid))
        try:
            last=None
            while self.process.poll() is None:
                try:
                    state=json.loads((self.folder/'progress.json').read_text(encoding='utf8'))
                    if state!=last:update(state);last=state
                except (OSError,ValueError):pass
                time.sleep(.1)
            if self.cancelled:return dict(state='cancelled',progress='已强制结束；已落盘的结果保留')
            try:return json.loads((self.folder/'result.json').read_text(encoding='utf8'))
            except (OSError,ValueError):return dict(state='failed',progress='任务异常退出',error='任务未返回完整结果，已完成的中间记录仍保留。')
        finally:
            with self.lock:self.tree.close();log.close()

    def checkpoint_summary(self):
        completed=0;paths=set()
        try:
            for line in (self.folder/'completed-games.jsonl').read_text(encoding='utf8').splitlines():
                try:
                    r=json.loads(line);completed+=1;paths.add(r['path'])
                except (ValueError,KeyError):continue
        except OSError:pass
        return dict(completed_game_records=completed,paths=sorted(paths))

    def checkpoint_records(self):
        records=[]
        try:
            for line in (self.folder/'completed-games.jsonl').read_text(encoding='utf8').splitlines():
                try:records.append(json.loads(line))
                except ValueError:continue
        except OSError:pass
        return dict(completed_games=records,note='仅包含已经完成并保存的比赛；强制结束时正在进行的比赛不计入。')
