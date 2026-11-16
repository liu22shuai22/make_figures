"""Local ERFlow model usage, aggregated by the server's calendar date."""
from contextlib import closing
from datetime import date, timedelta
import logging
from pathlib import Path
import sqlite3


DB_PATH = Path(__file__).with_name("token-usage.sqlite3")
logger = logging.getLogger(__name__)


def _connect():
    db = sqlite3.connect(DB_PATH, timeout=1)
    db.row_factory = sqlite3.Row
    return db


def record_usage(usage):
    """Record each upstream request once, even if it returned no token counts."""
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    counts = [input_tokens, output_tokens]
    if "input_tokens" in usage and "prompt_tokens" not in usage:
        counts.extend(usage.get(key, 0) for key in ("cache_creation_input_tokens", "cache_read_input_tokens"))
    reported = all(type(value) is int and 0 <= value < 2**53 for value in counts)
    try:
        with closing(_connect()) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS daily_usage (
                    day TEXT PRIMARY KEY,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    calls INTEGER NOT NULL,
                    unreported_calls INTEGER NOT NULL
                )
            """)
            db.execute("""
                INSERT INTO daily_usage VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(day) DO UPDATE SET
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    calls = calls + 1,
                    unreported_calls = unreported_calls + excluded.unreported_calls
            """, (date.today().isoformat(), input_tokens + sum(counts[2:]) if reported else 0,
                  output_tokens if reported else 0, int(not reported)))
    except sqlite3.Error:
        logger.exception("Could not record model token usage")


def read_usage():
    fields = ("input_tokens", "output_tokens", "calls", "unreported_calls")
    empty = dict.fromkeys(fields, 0)
    today = date.today()
    result = {"today": {"day": today.isoformat(), **empty}, "total": empty, "daily": []}
    if not DB_PATH.exists():
        return result

    with closing(_connect()) as db:
        db.execute("BEGIN")
        # A newly created file may be visible before the first usage write commits.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_usage'").fetchone() is None:
            return result
        start = (today - timedelta(days=29)).isoformat()
        result["daily"] = [dict(row) for row in db.execute(
            "SELECT * FROM daily_usage WHERE day BETWEEN ? AND ? ORDER BY day DESC",
            (start, today.isoformat()),
        )]
        result["total"] = dict(db.execute("""
            SELECT COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(calls), 0) AS calls,
                   COALESCE(SUM(unreported_calls), 0) AS unreported_calls
            FROM daily_usage
        """).fetchone())
    if result["daily"] and result["daily"][0]["day"] == today.isoformat():
        result["today"] = result["daily"][0]
    return result
