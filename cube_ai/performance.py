"""Small persistent stage ledger; overlapping spans are not added as wall time."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import threading
import time


class Timings:
    def __init__(self, path):
        self.path=path;self.lock=threading.Lock();self.started=time.perf_counter()
        try:self.data=json.loads(path.read_text(encoding='utf8'))
        except (OSError,ValueError):self.data=dict(version=1,stages=[],note='阶段可能重叠，耗时不可直接相加；续跑保留各次执行记录。')

    @contextmanager
    def span(self, name):
        start=time.perf_counter();status='completed'
        try:yield
        except BaseException:
            status='failed';raise
        finally:
            with self.lock:
                self.data['stages'].append(dict(stage=name,seconds=round(time.perf_counter()-start,6),
                    status=status,finished=datetime.now(timezone.utc).isoformat()))
                self.data['last_session_wall_seconds']=round(time.perf_counter()-self.started,6)
                self.path.parent.mkdir(parents=True,exist_ok=True)
                tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(self.path)

    def snapshot(self):
        with self.lock:return json.loads(json.dumps(self.data))

    def call(self,name,function,*args,**kwargs):
        with self.span(name):return function(*args,**kwargs)
