"""Cross-process admission control for bounded model and rendering work."""
from contextlib import closing, contextmanager
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

DB_PATH = Path(__file__).with_name("service-limits.sqlite3")


class BusyError(Exception):
    pass


@contextmanager
def admit(owner, kind):
    limits = {"model": int(os.getenv("ERFLOW_MODEL_CONCURRENCY", "4")),
              "render": int(os.getenv("ERFLOW_RENDER_CONCURRENCY", "2")),
              "auth": 10}
    capacity = max(1, min(16, limits[kind])) if kind != "auth" else 10
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
        rate = {"model": 30, "render": 60, "auth": 10}[kind]
        if row and row[0] >= rate:
            raise BusyError("请求过于频繁，请稍后重试")
        if kind != "auth":
            count = db.execute("SELECT COUNT(*) FROM leases WHERE kind=?", (kind,)).fetchone()[0]
            personal = db.execute("SELECT COUNT(*) FROM leases WHERE owner=? AND kind=?", (owner, kind)).fetchone()[0]
            if personal or count >= capacity:
                raise BusyError("任务正在处理中，请稍后重试")
            db.execute("INSERT INTO leases VALUES(?,?,?,?)", (ticket, owner, kind, now + 240))
        db.execute("INSERT INTO rates VALUES(?,?,?,1) ON CONFLICT(owner,kind,minute) DO UPDATE SET count=count+1", (owner, kind, minute))
    try:
        yield
    finally:
        if kind != "auth":
            with closing(sqlite3.connect(DB_PATH, timeout=3)) as db, db:
                db.execute("DELETE FROM leases WHERE id=?", (ticket,))
