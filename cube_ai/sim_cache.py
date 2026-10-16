"""Bounded, versioned cache. Cached games are reuse, never new observations."""
import gzip
import hashlib
import json
import sqlite3
import threading
import time
import pickle
import sys
import zlib
from array import array
from functools import lru_cache
from pathlib import Path
from .config import ROOT

CACHE=ROOT/'cache/simulation.sqlite'
_local=threading.local()

@lru_cache(maxsize=1)
def code_signature():
    base=Path(__file__).parent
    digest=hashlib.sha256()
    for name in ['draft.py','design.py','features.py','brackets.py','optimize.py','sim_cache.py']:
        digest.update((base/name).read_bytes())
    for p in [base/'data/cube_studies.json',base.parent/'ref_thecommandercube.csv']:
        if p.is_file():digest.update(p.read_bytes())
    return digest.hexdigest()[:20]

def draft(catalog,rows,spec,seed,prefs):
    import random
    from .draft import deal,draft_pod
    rng=random.Random(seed);packs=deal(catalog,rows,spec,rng)
    # The whole opened layout, not only the old selected pool, determines reuse.
    settings=spec.to_dict();settings.pop('name',None);settings.pop('seed',None)
    k=key('draft',[code_signature(),catalog.signature,settings,seed,prefs,
        [[(r['name'],r['role']) for r in pack] for pack in packs]])
    cached=get(k)
    if cached is not None:return cached,True
    pod=draft_pod(catalog,rows,spec,rng,prefs,readiness_hands=0,_packs=packs)
    put(k,pod,'draft')
    return pod,False


class DraftWorkspace:
    """Bounded per-search memory. Reuse requires identical *entire* pack layout.

    Trial cubes are not written to disk. Changed tables are redrafted completely;
    unchanged tables reuse both their draft and deck metrics. No picked-pool shortcut.
    """
    def __init__(self,catalog,spec,limit=4096,max_bytes=32*1024**2):
        from collections import OrderedDict
        if limit<1 or max_bytes<1:raise ValueError('轮抓缓存容量需为正数')
        self.catalog=catalog;self.settings=spec.to_dict();self.entries=OrderedDict();self.limit=limit
        self.max_bytes=max_bytes;self.bytes_used=0;self._codes={}

    def _layout(self,packs):
        # A lossless code for each (name, role), not a hash of only picked cards.
        # Pack lengths are included even if a future deal policy varies them.
        codes=array('I')
        for pack in packs:
            for row in pack:
                item=(row['name'],row['role'])
                code=self._codes.get(item)
                if code is None:code=len(self._codes);self._codes[item]=code
                codes.append(code)
        return (tuple(map(len,packs)),codes.tobytes())

    def table(self,catalog,rows,spec,seed,prefs,summarize):
        import random
        from .draft import deal,draft_pod
        if catalog is not self.catalog or spec.to_dict()!=self.settings:
            raise ValueError('增量轮抓工作区不能跨卡池或构筑参数复用')
        rng=random.Random(seed);packs=deal(catalog,rows,spec,rng)
        layout=self._layout(packs)
        token=(seed,tuple(prefs),layout)
        if token in self.entries:
            payload,_=self.entries[token];self.entries.move_to_end(token)
            # Only bytes created by this workspace are unpickled. No disk/input
            # pickle is accepted, and callers cannot mutate cached evidence.
            return pickle.loads(zlib.decompress(payload)),True
        pod=draft_pod(catalog,rows,spec,rng,prefs,readiness_hands=0,_packs=packs)
        result=(pod,summarize(pod))
        payload=zlib.compress(pickle.dumps(result,protocol=5),level=1)
        weight=(sys.getsizeof(payload)+sys.getsizeof(layout[1])+sys.getsizeof(layout[0])
                +sys.getsizeof(token)+sys.getsizeof(token[1])+256)
        # Oversized tables are still fully evaluated; only reuse is declined.
        if weight<=self.max_bytes:
            self.entries[token]=(payload,weight);self.bytes_used+=weight
            while len(self.entries)>self.limit or self.bytes_used>self.max_bytes:
                _,(_,removed)=self.entries.popitem(last=False);self.bytes_used-=removed
        return result,False

def key(kind,value):
    return kind+':'+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def connection():
    cached=getattr(_local,'connection',None)
    if cached and cached[0]==str(CACHE):return cached[1]
    CACHE.parent.mkdir(exist_ok=True)
    db=sqlite3.connect(CACHE,timeout=30)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, kind TEXT, payload BLOB, touched REAL)')
    _local.connection=(str(CACHE),db)
    return db

def get(cache_key):
    try:
        row=connection().execute('SELECT payload FROM entries WHERE key=?',(cache_key,)).fetchone()
        value=json.loads(gzip.decompress(row[0])) if row else None
        return value if isinstance(value,dict) else None
    except (OSError,sqlite3.DatabaseError,ValueError,EOFError):return None

def put(cache_key,value,kind):
    try:
        payload=gzip.compress(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode(),compresslevel=1)
        db=connection()
        with db:
            db.execute('INSERT OR REPLACE INTO entries VALUES (?,?,?,?)',(cache_key,kind,payload,time.time()))
            # Bounded disk use: about 20k draft tables plus a modest game trace cache.
            count=db.execute('SELECT COUNT(*) FROM entries').fetchone()[0]
            if count>24000:db.execute('DELETE FROM entries WHERE key IN (SELECT key FROM entries ORDER BY touched LIMIT 2000)')
            _local.writes=getattr(_local,'writes',0)+1
            if _local.writes%128==0:
                while (db.execute('SELECT COALESCE(SUM(length(payload)),0) FROM entries').fetchone()[0])>512*1024**2:
                    db.execute('DELETE FROM entries WHERE key IN (SELECT key FROM entries ORDER BY touched LIMIT 1000)')
    except (OSError,sqlite3.DatabaseError):pass

def status():
    if not CACHE.exists():return dict(entries=0,bytes=0)
    try:
        rows=connection().execute('SELECT kind,COUNT(*) FROM entries GROUP BY kind').fetchall()
        return dict(entries=sum(n for _,n in rows),kinds=dict(rows),bytes=CACHE.stat().st_size)
    except (OSError,sqlite3.DatabaseError):return dict(entries=0,bytes=0,unavailable=True)
