"""Cooperative pause at safe boundaries, durable progress and native results."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import time

_current=None


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+str(threading.get_ident())+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');os.replace(tmp,path)


class TaskStopped(Exception):pass


class TaskControl:
    def __init__(self,folder):
        self.folder=Path(folder);self.lock=threading.RLock();self.active_native=0
        self.last_message='准备运行';self.pause_started=None;self.paused_seconds=0.

    def command(self):
        try:return json.loads((self.folder/'command.json').read_text(encoding='utf8'))['action']
        except (OSError,ValueError,KeyError):return 'run'

    def emit(self,state):
        with self.lock:atomic_json(self.folder/'progress.json',dict(state=state,progress=self.last_message))

    def checkpoint(self):
        while True:
            action=self.command()
            if action=='cancel':raise TaskStopped('已强制结束')
            if action!='pause':
                with self.lock:
                    if self.pause_started is not None:
                        self.paused_seconds+=time.monotonic()-self.pause_started;self.pause_started=None
                        self.emit('running')
                return
            with self.lock:
                if self.active_native==0 and self.pause_started is None:
                    self.pause_started=time.monotonic();self.emit('paused')
            time.sleep(.1)

    def progress(self,message):
        with self.lock:self.last_message=str(message)
        self.checkpoint();self.emit('running')

    @contextmanager
    def native(self):
        while True:
            self.checkpoint()
            with self.lock:
                if self.command()=='pause':continue
                self.active_native+=1;break
        try:yield
        finally:
            with self.lock:self.active_native-=1

    def record(self,record,out):
        # Written by the completing game thread before the main loop can pause.
        with self.lock:
            with (self.folder/'completed-games.jsonl').open('a',encoding='utf8') as f:
                f.write(json.dumps(dict(path=str(out),record=record),ensure_ascii=False)+'\n');f.flush()


def bind(control):
    global _current
    _current=control


def checkpoint():
    if _current:_current.checkpoint()


@contextmanager
def native_activity():
    if _current:
        with _current.native():yield
    else:yield


def record_game(record,out):
    if _current:_current.record(record,out)
