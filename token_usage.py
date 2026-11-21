"""Local ERFlow model usage, by calendar day and provider channel."""
from contextlib import closing
from datetime import date, timedelta
import logging
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit


DB_PATH = Path(__file__).with_name("token-usage.sqlite3")
LEGACY_CHANNEL = "_legacy"
LEGACY_NAME = "未区分渠道"
logger = logging.getLogger(__name__)

_HOST_NAMES = {
    "api.deepseek.com": "DeepSeek",
    "api.siliconflow.cn": "硅基流动",
    "api.siliconflow.com": "硅基流动",
    "api.openai.com": "OpenAI",
    "api.anthropic.com": "Anthropic",
    "api.moonshot.cn": "月之暗面",
    "dashscope.aliyuncs.com": "通义",
    "open.bigmodel.cn": "智谱",
}


def _connect():
    from request_scope import current_scope
    from hashlib import sha256
    scope = current_scope.get()
    path = DB_PATH
    if scope is not None:
        if not scope.username:
            raise sqlite3.OperationalError("Authenticated usage context required")
        directory = DB_PATH.parent / "user-usage"
        directory.mkdir(exist_ok=True)
        path = directory / (sha256(scope.username.encode()).hexdigest() + ".sqlite3")
    db = sqlite3.connect(path, timeout=1)
    db.row_factory = sqlite3.Row
    return db


def _text(value) -> str:
    return str(value or "").strip()


def _host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        return ""


def resolve_channel(usage: dict) -> tuple[str, str, str]:
    """Return (channel_id, channel_name, model) for one upstream call.

    Prefer the request host so different custom gateways stay separate.
    Fall back to the active API-platform entry only when hosts match (or host is missing).
    """
    usage = usage if isinstance(usage, dict) else {}
    model = _text(usage.get("model"))[:120]
    base_url = _text(usage.get("base_url"))
    provider = _text(usage.get("provider")).lower() or "openai"
    host = _host(base_url)

    try:
        from llm_providers import active_provider

        entry = active_provider()
    except Exception:  # noqa: BLE001 - usage must never break generation
        entry = None

    entry_host = _host((entry or {}).get("base_url") or "") if entry else ""
    entry_model = _text((entry or {}).get("model")) if entry else ""
    # Use the active platform entry only when the request host matches, or when the
    # request omitted base_url and the model is compatible with the active entry.
    use_entry = bool(entry) and (
        (bool(host) and host == entry_host)
        or (not host and (not model or not entry_model or model == entry_model))
    )
    if use_entry:
        # Host is the stable id; preset "custom" alone would merge unrelated gateways.
        channel = host or entry_host or _text(entry.get("preset")) or _text(entry.get("id")) or provider
        name = _text(entry.get("name")) or _HOST_NAMES.get(channel) or channel
        return channel[:64], name[:48], model or entry_model[:120]

    if host:
        return host[:64], (_HOST_NAMES.get(host) or host)[:48], model
    return (provider or "unknown")[:64], (provider or "unknown")[:48], model


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS daily_usage_by_channel (
            day TEXT NOT NULL,
            channel TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            calls INTEGER NOT NULL,
            unreported_calls INTEGER NOT NULL,
            PRIMARY KEY (day, channel, model)
        )
    """)
    # One-time move from the old day-only table.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_usage'").fetchone():
        existing = db.execute("SELECT COUNT(*) AS n FROM daily_usage_by_channel").fetchone()["n"]
        if existing == 0:
            db.execute("""
                INSERT INTO daily_usage_by_channel
                    (day, channel, channel_name, model, input_tokens, output_tokens, calls, unreported_calls)
                SELECT day, ?, ?, '', input_tokens, output_tokens, calls, unreported_calls
                FROM daily_usage
            """, (LEGACY_CHANNEL, LEGACY_NAME))


def ensure_usage_schema() -> None:
    """Create/migrate tables and commit. Safe to call from read or write paths."""
    try:
        with closing(_connect()) as db, db:
            _ensure_schema(db)
    except sqlite3.Error:
        logger.exception("Could not migrate model token usage schema")


def _empty_counts():
    return {"input_tokens": 0, "output_tokens": 0, "calls": 0, "unreported_calls": 0}


def _add_counts(target: dict, row) -> None:
    target["input_tokens"] += int(row["input_tokens"] or 0)
    target["output_tokens"] += int(row["output_tokens"] or 0)
    target["calls"] += int(row["calls"] or 0)
    target["unreported_calls"] += int(row["unreported_calls"] or 0)


def record_usage(usage):
    """Record each upstream request once, tagged by provider channel and model."""
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    counts = [input_tokens, output_tokens]
    if "input_tokens" in usage and "prompt_tokens" not in usage:
        counts.extend(usage.get(key, 0) for key in ("cache_creation_input_tokens", "cache_read_input_tokens"))
    reported = all(type(value) is int and 0 <= value < 2**53 for value in counts)
    channel, channel_name, model = resolve_channel(usage)
    try:
        with closing(_connect()) as db, db:
            _ensure_schema(db)
            db.execute("""
                INSERT INTO daily_usage_by_channel VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(day, channel, model) DO UPDATE SET
                    channel_name = excluded.channel_name,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    calls = calls + 1,
                    unreported_calls = unreported_calls + excluded.unreported_calls
            """, (
                date.today().isoformat(),
                channel,
                channel_name,
                model,
                input_tokens + sum(counts[2:]) if reported else 0,
                output_tokens if reported else 0,
                int(not reported),
            ))
    except sqlite3.Error:
        logger.exception("Could not record model token usage")


def read_usage():
    empty = _empty_counts()
    today = date.today()
    result = {
        "today": {"day": today.isoformat(), **empty},
        "total": dict(empty),
        "daily": [],
        "channels": [],
    }
    ensure_usage_schema()
    with closing(_connect()) as db:
        start = (today - timedelta(days=29)).isoformat()
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_usage_by_channel'"
        ).fetchone() is None:
            return result
        rows = list(db.execute(
            """
            SELECT * FROM daily_usage_by_channel
            WHERE day BETWEEN ? AND ?
            ORDER BY day DESC, input_tokens + output_tokens DESC, channel, model
            """,
            (start, today.isoformat()),
        ))
        daily_map: dict[str, dict] = {}
        channel_map: dict[str, dict] = {}
        for row in rows:
            day = row["day"]
            day_counts = daily_map.setdefault(day, {"day": day, **_empty_counts()})
            _add_counts(day_counts, row)

            channel = row["channel"]
            channel_entry = channel_map.setdefault(channel, {
                "id": channel,
                "name": row["channel_name"] or channel,
                **_empty_counts(),
                "models": {},
            })
            if row["channel_name"]:
                channel_entry["name"] = row["channel_name"]
            _add_counts(channel_entry, row)
            model_key = row["model"] or ""
            model_entry = channel_entry["models"].setdefault(model_key, {
                "model": model_key,
                **_empty_counts(),
            })
            _add_counts(model_entry, row)

        result["daily"] = sorted(daily_map.values(), key=lambda item: item["day"], reverse=True)
        channels = []
        for entry in channel_map.values():
            models = sorted(
                entry.pop("models").values(),
                key=lambda item: item["input_tokens"] + item["output_tokens"],
                reverse=True,
            )
            entry["models"] = models
            channels.append(entry)
        # Named providers first so the split is visible; legacy bucket stays at the end.
        channels.sort(
            key=lambda item: (
                item["id"] == LEGACY_CHANNEL,
                -(item["input_tokens"] + item["output_tokens"]),
            ),
        )
        result["channels"] = channels
        older = db.execute("""
            SELECT COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(calls), 0) AS calls,
                   COALESCE(SUM(unreported_calls), 0) AS unreported_calls
            FROM daily_usage_by_channel
        """).fetchone()
        result["total"] = {
            "input_tokens": int(older["input_tokens"] or 0),
            "output_tokens": int(older["output_tokens"] or 0),
            "calls": int(older["calls"] or 0),
            "unreported_calls": int(older["unreported_calls"] or 0),
        }
    if result["daily"] and result["daily"][0]["day"] == today.isoformat():
        result["today"] = result["daily"][0]
    return result
