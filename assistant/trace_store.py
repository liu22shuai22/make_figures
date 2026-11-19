"""Account-scoped execution metadata. No prompts, draft contents or model responses."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "assistant-traces.sqlite3"
KEEP = 30


def _connect():
    db = sqlite3.connect(DB_PATH, timeout=2)
    db.execute("""CREATE TABLE IF NOT EXISTS turns (
        id INTEGER PRIMARY KEY, owner TEXT NOT NULL, created TEXT NOT NULL, steps TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS turns_owner ON turns(owner, id)")
    return db


def save(owner, steps):
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_connect()) as db, db:
        db.execute("INSERT INTO turns(owner,created,steps) VALUES(?,?,?)",
                   (owner, created, json.dumps(steps)))
        db.execute("""DELETE FROM turns WHERE owner=? AND id NOT IN
                      (SELECT id FROM turns WHERE owner=? ORDER BY id DESC LIMIT ?)""", (owner, owner, KEEP))


def recent(owner):
    with closing(_connect()) as db:
        rows = db.execute("SELECT id,created,steps FROM turns WHERE owner=? ORDER BY id DESC LIMIT ?", (owner, KEEP))
        return [{"id": key, "created": created, "steps": json.loads(steps)} for key, created, steps in rows]
