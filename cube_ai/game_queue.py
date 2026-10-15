"""Bounded native game queue; resource changes affect new starts, never live games."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import time

from .resources import MIB, capacity, system_memory


class GameQueue:
    def __init__(self, resources, config, progress=lambda _: None, *, sample=None, trim=None, clock=time.monotonic):
        from .forge_worker import memory_snapshot, trim_idle
        self.resources = resources
        self.dynamic = resources.get('dynamic', False)
        self.ceiling = resources.get('ceiling', resources['workers'])
        self.target = min(self.ceiling, resources['workers'])
        self.heap_mib = config.get('heap_mib', 2048)
        self.sample = sample or (lambda: (system_memory(), memory_snapshot()))
        self.trim = trim or trim_idle
        self.clock = clock; self.started = clock(); self.last_check = -float('inf'); self.last_ramp = self.started
        self.progress = progress; self.waiting = deque(); self.pending = {}
        self.pool = ThreadPoolExecutor(max_workers=self.ceiling)
        self.peak_active = 0; self.completed = 0; self.normal = 0; self.reused = 0
        self.events = []; self.samples = 0; self.minimum_available = None; self.peak_owned = 0
        from . import task_control
        self.pause_baseline = task_control._current.paused_seconds if task_control._current else 0

    def __enter__(self):return self

    def __exit__(self, *exc):
        self.pool.shutdown(wait=True, cancel_futures=bool(exc[0]))

    def __len__(self):return len(self.waiting) + len(self.pending)

    def _adjust(self):
        now = self.clock()
        if not self.dynamic or now-self.last_check < 1:return
        self.last_check = now
        snapshot, engines = self.sample()
        status = capacity(snapshot, engines, self.heap_mib, self.ceiling)
        self.samples += 1
        available = status.get('available_memory_bytes')
        if available is not None:
            self.minimum_available = available if self.minimum_available is None else min(self.minimum_available, available)
        self.peak_owned = max(self.peak_owned, status.get('owned_working_set_bytes', 0))
        old = self.target; allowed = status['capacity']
        if allowed < self.target:
            self.target = allowed; self.last_ramp = now
        elif allowed > self.target and now-self.last_ramp >= 3:
            # Extra room before expansion avoids repeated cold starts near a
            # memory boundary. Reductions use the ordinary reserve immediately.
            expansion=dict(snapshot)
            for key in ('available','commit_available'):
                if expansion.get(key) is not None:expansion[key]-=384*MIB
            if capacity(expansion,engines,self.heap_mib,self.ceiling)['capacity']>self.target:
                self.target += 1; self.last_ramp = now
        # Idle engines from an earlier larger phase otherwise retain their heap.
        self.trim(self.target)
        if old != self.target or not self.events:
            self.events.append(dict(seconds=round(now-self.started, 3), previous=old, target=self.target, **status))
            if old != self.target:
                direction = '增加' if self.target > old else '减少'
                self.progress(f'根据剩余内存{direction}新开对局：目标同时 {self.target} 局；正在进行的对局正常完成')

    def pump(self):
        self._adjust()
        while self.waiting and len(self.pending) < self.target:
            tag, fn, args = self.waiting.popleft()
            self.pending[self.pool.submit(fn, *args)] = tag
            self.peak_active = max(self.peak_active, len(self.pending))

    def submit(self, tag, fn, *args):
        self.waiting.append((tag, fn, args)); self.pump()

    def collect(self, block=False):
        self.pump()
        while self.pending:
            done = {f for f in self.pending if f.done()}
            if not done and block:
                done = wait(self.pending, timeout=1, return_when=FIRST_COMPLETED)[0]
                if not done:self.pump();continue
            results = []
            for future in done:
                tag = self.pending.pop(future); record = future.result()
                self.completed += 1
                self.reused += bool(record.get('cache_hit'))
                self.normal += record.get('outcome') in {'win', 'draw'} and not record.get('cache_hit')
                results.append((tag, record))
            self.pump();return results
        return []

    def report(self):
        elapsed = max(.001, self.clock()-self.started)
        # Exclude deliberate user pauses from throughput; never tune using outcomes.
        from . import task_control
        control = task_control._current
        paused = max(0, control.paused_seconds-self.pause_baseline) if control else 0
        elapsed = max(.001, elapsed-paused)
        return dict(dynamic=self.dynamic, ceiling=self.ceiling, final_target=self.target,
                    peak_active=self.peak_active, decisions=self.events, memory_samples=self.samples,
                    expansion_headroom_bytes=384*MIB,
                    minimum_available_memory_bytes=self.minimum_available, peak_owned_working_set_bytes=self.peak_owned,
                    normal_new_games=self.normal, reused_games=self.reused,
                    normal_new_games_per_minute=round(self.normal*60/elapsed, 3), active_wall_seconds=round(elapsed, 3))

