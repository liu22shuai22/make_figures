"""Short conversational memory helpers for one assistant session."""
from __future__ import annotations

import re
from typing import Any

from .types import TurnContext

_FOLLOW_RE = re.compile(
    r"^(?:那|那么|它|他|她|这个|那个|上面|刚才|以及|还有|"
    r"its?\b|their\b|this\b|that\b|those\b|and\b|also\b|what\s+about)",
    re.I,
)
_TOPIC_TITLE_RE = re.compile(r"^[「\"](.+?)[」\"]")


def normalize_history(raw: list[Any] | None, *, limit: int = 8) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        text = str(item.get("text") or "").strip()
        if role not in {"user", "bot"} or not text:
            continue
        row = {"role": role, "text": text[:400]}
        band = str(item.get("band") or "").strip()
        if band:
            row["band"] = band
        topic = str(item.get("topic") or "").strip()
        if topic:
            row["topic"] = topic[:80]
        out.append(row)
    return out


def last_topic(ctx: TurnContext) -> str:
    for item in reversed(ctx.history):
        topic = str(item.get("topic") or "").strip()
        if topic:
            return topic[:80]
        if item.get("band") == "web_search" and item.get("role") == "bot":
            match = _TOPIC_TITLE_RE.match(str(item.get("text") or ""))
            if match:
                return match.group(1).strip()[:80]
    return ""


def looks_like_follow_up(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    if _FOLLOW_RE.search(text):
        return True
    # Short continuation questions that omit the entity name.
    if len(text) <= 36 and re.search(
        r"成员|成立|时候|哪里|谁发起|有哪些|有多少|何时|历史|作用|why|when|where|who|member|founded|history",
        text,
        re.I,
    ):
        if not re.search(r"什么是|啥是|你知道|介绍一下|what\s+is|who\s+is|tell\s+me\s+about", text, re.I):
            return True
    return False


def resolve_lookup_query(ctx: TurnContext, extracted: str) -> tuple[str, str | None]:
    """Return (query, topic_used)."""
    topic = last_topic(ctx)
    message = ctx.message.strip()
    if topic and (looks_like_follow_up(message) or not extracted):
        # 「它有哪些成员」→ 「亚太经济合作组织 有哪些成员」
        follow = extracted or message
        follow = re.sub(r"^(?:那|那么|它|他|她|这个|那个)\s*", "", follow).strip() or message
        if topic.casefold() not in follow.casefold():
            return f"{topic} {follow}".strip()[:100], topic
        return follow[:100], topic
    if extracted:
        return extracted[:100], None
    if topic:
        return topic, topic
    return "", None
