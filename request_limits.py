"""Cross-process admission control for bounded model and rendering work."""
from contextlib import closing, contextmanager
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4
from functools import wraps
from threading import BoundedSemaphore

# Read once at startup, shared by SQLite admission and the local hard ceiling.
MODEL_CAPACITY = max(1, min(16, int(os.getenv("ERFLOW_MODEL_CONCURRENCY", "4"))))
RENDER_CAPACITY = max(1, min(16, int(os.getenv("ERFLOW_RENDER_CONCURRENCY", "2"))))
model_slot = BoundedSemaphore(MODEL_CAPACITY)

DB_PATH = Path(__file__).with_name("service-limits.sqlite3")


class BusyError(Exception):
    pass


@contextmanager
def admit(owner, kind):
    capacity = {"model": MODEL_CAPACITY, "render": RENDER_CAPACITY, "probe": MODEL_CAPACITY,
                "auth": 10, "assistant": 1}[kind]
    owner = sha256(owner.encode()).hexdigest()
    now = time.time()
    ticket = uuid4().hex
    with closing(sqlite3.connect(DB_PATH, timeout=3)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS leases (id TEXT PRIMARY KEY, owner TEXT, kind TEXT, expires REAL)")
        db.execute("CREATE TABLE IF NOT EXISTS rates (owner TEXT, kind TEXT, minute INTEGER, count INTEGER, PRIMARY KEY(owner,kind,minute))")
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM leases WHERE expires < ?", (now,))
        db.execute("DELETE FROM rates WHERE minute < ?", (int(now // 60) - 2,))
        minute = int(now // 60)
        row = db.execute("SELECT count FROM rates WHERE owner=? AND kind=? AND minute=?", (owner, kind, minute)).fetchone()
        rate = {"model": 30, "render": 60, "auth": 10, "probe": 30, "assistant": 60}[kind]
        if row and row[0] >= rate:
            raise BusyError("请求过于频繁，请稍后重试")
        if kind not in {"auth", "assistant"}:
            count = db.execute("SELECT COUNT(*) FROM leases WHERE kind=?", (kind,)).fetchone()[0]
            personal = db.execute("SELECT COUNT(*) FROM leases WHERE owner=? AND kind=?", (owner, kind)).fetchone()[0]
            if personal or count >= capacity:
                raise BusyError("任务正在处理中，请稍后重试")
            db.execute("INSERT INTO leases VALUES(?,?,?,?)", (ticket, owner, kind, now + 240))
        db.execute("INSERT INTO rates VALUES(?,?,?,1) ON CONFLICT(owner,kind,minute) DO UPDATE SET count=count+1", (owner, kind, minute))
    try:
        yield
    finally:
        if kind not in {"auth", "assistant"}:
            with closing(sqlite3.connect(DB_PATH, timeout=3)) as db, db:
                db.execute("DELETE FROM leases WHERE id=?", (ticket,))


def model_admitted(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from request_scope import current_scope
        scope = current_scope.get()
        if scope is None or scope.model_depth:
            return function(*args, **kwargs)
        if not scope.username:
            raise BusyError("请先登录，再调用模型")
        with admit("account:" + scope.username, "model"):
            if not model_slot.acquire(blocking=False):
                raise BusyError("模型任务繁忙，请稍后重试")
            scope.model_depth += 1
            try:
                return function(*args, **kwargs)
            finally:
                scope.model_depth -= 1
                model_slot.release()
    return wrapped
