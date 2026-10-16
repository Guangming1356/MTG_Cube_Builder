"""Local pairwise preference learning. No synthetic labels or API keys are stored."""
import hashlib
import json
import math
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DATA

class FeedbackStore:
    def __init__(self, path=None):
        DATA.mkdir(exist_ok=True)
        self.path = path or DATA / "preferences.sqlite"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS comparisons(id INTEGER PRIMARY KEY, winner TEXT, loser TEXT, context TEXT, note TEXT, created TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS models(context TEXT PRIMARY KEY, payload TEXT)")

    @contextmanager
    def connect(self):
        # sqlite3's own context manager handles transactions, not handle closure.
        # Closing here avoids idle database locks and abandoned connections.
        database=sqlite3.connect(self.path, timeout=15)
        try:
            with database:yield database
        finally:database.close()

    @staticmethod
    def context(spec):
        return f"{spec.legality_format}:{spec.mode}"

    def add(self, winner, loser, context, note=""):
        if winner == loser: raise ValueError("偏好比较需要两张不同的牌")
        with self.connect() as db:
            db.execute("INSERT INTO comparisons(winner,loser,context,note,created) VALUES(?,?,?,?,?)",
                       (winner, loser, context, note[:2000], datetime.now(timezone.utc).isoformat()))
        return self.status(context)

    def status(self, context):
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM comparisons WHERE context=?", (context,)).fetchone()[0]
            row = db.execute("SELECT payload FROM models WHERE context=?", (context,)).fetchone()
        return dict(comparisons=count, model=json.loads(row[0]) if row else None, minimum=8)

    def train(self, catalog, context):
        with self.connect() as db:
            rows = db.execute("SELECT winner,loser FROM comparisons WHERE context=? ORDER BY id", (context,)).fetchall()
        rows = [(a,b) for a,b in rows if a in catalog.cards and b in catalog.cards]
        if len(rows) < 8: raise ValueError("至少需要 8 次真实偏好比较；当前不会用旧 Cube 版本伪造训练标签")
        vectors = [(catalog.cards[a]["vector"], catalog.cards[b]["vector"]) for a,b in rows]
        holdout = max(1, len(vectors) // 5)
        train = vectors[:-holdout]
        weights = [0.0] * len(vectors[0][0])
        rng = random.Random(42)
        for epoch in range(250):
            order = list(train); rng.shuffle(order)
            rate = .09 / (1 + epoch / 120)
            for a,b in order:
                delta = [x-y for x,y in zip(a,b)]
                z = sum(x*w for x,w in zip(delta, weights))
                p = 1 / (1 + math.exp(-max(-20, min(20, z))))
                weights = [w + rate * ((1-p)*d - .04*w) for w,d in zip(weights, delta)]
        test = vectors[-holdout:]
        correct = sum(sum((x-y)*w for x,y,w in zip(a,b,weights)) > 0 for a,b in test)
        payload = dict(weights=weights, comparisons=len(rows), train_rows=len(train), holdout_rows=holdout,
                       holdout_accuracy=round(correct/holdout,3), context=context,
                       model_id=hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16],
                       limitation="时间顺序留出；小样本指标不能证明泛化或胜率")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO models(context,payload) VALUES(?,?)", (context,json.dumps(payload)))
        return payload

    def scorer(self, spec):
        model = self.status(self.context(spec))["model"]
        def score(card):
            if not model: return 0.0
            z = sum(w*x for w,x in zip(model["weights"],card["vector"]))
            return .5 * math.tanh(z)
        return score, model
