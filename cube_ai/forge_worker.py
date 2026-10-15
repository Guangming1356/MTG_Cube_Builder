"""Sequential resident JVMs, leased by bounded Python game workers."""
import atexit
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .forge_setup import RUNTIME

BRIDGE_VERSION='resident-1'
_guard=threading.Lock()
_workers=[]

class WorkerUnavailable(RuntimeError):pass

def available():
    return (RUNTIME/'acceleration/classes/cube/worker/CubeWorker.class').is_file()

def bridge_signature():
    digest=hashlib.sha256(BRIDGE_VERSION.encode())
    for p in sorted((RUNTIME/'acceleration/classes').rglob('*.class')):
        digest.update(p.name.encode());digest.update(p.read_bytes())
    return digest.hexdigest()

class Worker:
    def __init__(self,config,make_home,out):
        self.key=(config['java'],config['jar']);self.busy=True;self.closed=False
        self.home=make_home(config,out)
        classes=(RUNTIME/'acceleration/classes').resolve()
        self.command=[config['java'],'-Xmx2048m','-Dfile.encoding=UTF-8','-Djava.awt.headless=true',
            '-cp',str(classes)+os.pathsep+config['jar'],'cube.worker.CubeWorker']
        self.process=subprocess.Popen(self.command,cwd=self.home,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.messages=queue.Queue();self.games=0
        def read():
            for line in self.process.stdout:
                if line.startswith(('CUBE_READY ','CUBE_RESULT ')):self.messages.put(line.rstrip())
            self.messages.put(None)
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        try:
            ready=self.messages.get(timeout=90)
            if ready!='CUBE_READY 1':raise WorkerUnavailable('常驻 Forge 未能完成初始化')
        except queue.Empty:
            self.close();raise WorkerUnavailable('常驻 Forge 初始化超时')
        except Exception:
            self.close();raise

    def close(self):
        if self.closed:return
        self.closed=True
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        for stream in [self.process.stdin,self.process.stdout]:
            if stream:
                try:stream.close()
                except (OSError,ValueError):pass

    def run(self,deck_dir,order,seed,clock,out,log_name):
        id_=uuid.uuid4().hex
        request=dict(id=id_,deck_dir=str(deck_dir.resolve()),order=order,seed=seed,clock=clock,
            log=str((out/log_name).resolve()))
        started=time.monotonic();timeout=False;retire=False;error=None
        try:
            self.process.stdin.write(json.dumps(request,ensure_ascii=False)+'\n');self.process.stdin.flush()
            line=self.messages.get(timeout=clock+30)
            if not line or not line.startswith('CUBE_RESULT '):raise RuntimeError('常驻 Forge 意外退出')
            response=json.loads(line[len('CUBE_RESULT '):])
            if response.get('id')!=id_:raise RuntimeError('常驻 Forge 回复与比赛不匹配')
            retire=response.get('retire',True)
        except queue.Empty:timeout=True;retire=True
        except (OSError,ValueError,RuntimeError) as e:error=str(e);retire=True
        self.games+=1
        if retire:self.close()
        log=(out/log_name).read_text(encoding='utf-8',errors='replace') if (out/log_name).exists() else ''
        if error:log+='\nCubeWorkerError: '+error+'\n';(out/log_name).write_text(log,encoding='utf-8')
        if not (out/log_name).exists():(out/log_name).write_text(log,encoding='utf-8')
        return dict(log_text=log,returncode=-1 if error or timeout else 0,process_timeout=timeout,
            command=self.command,wall_seconds=time.monotonic()-started,worker_game=self.games,
            worker_directory=str(self.home),backend=BRIDGE_VERSION)

def run(config,make_home,deck_dir,order,seed,clock,out,log_name):
    if not available():raise WorkerUnavailable('常驻引擎组件尚未编译')
    started=time.monotonic()
    with _guard:
        _workers[:]=[w for w in _workers if not w.closed]
        worker=next((w for w in _workers if not w.busy and not w.closed and w.key==(config['java'],config['jar'])),None)
        if worker:worker.busy=True
    if worker is None:
        worker=Worker(config,make_home,out)
        with _guard:_workers.append(worker)
    try:
        value=worker.run(deck_dir,order,seed,clock,out,log_name)
        value['wall_seconds']=round(time.monotonic()-started,3)
        return value
    finally:
        with _guard:worker.busy=False

def close_all():
    with _guard:workers=list(_workers);_workers.clear()
    for worker in workers:worker.close()

atexit.register(close_all)
