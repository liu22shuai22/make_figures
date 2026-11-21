"""Lightweight agent continue: rule-first, optional model, hard cap."""
from __future__ import annotations

from request_limits import BusyError

import logging
import re

from .policy import is_edit_intent
from .router import can_model_route, parse_route_payload
from .types import RoutePlan, TurnContext, TurnResult

logger = logging.getLogger(__name__)

MAX_AGENT_STEPS = 3

# Tools that may run inside the loop (and may be chosen as a continue target).
LOOPABLE_TOOLS = frozenset({
    "faq.answer",
    "usage.explain_channel",
    "usage.explain",
    "draft.open_review",
    "web.lookup",
    "draft.propose_cardinality",
})

_STOP_STATUSES = frozenset({
    "error", "internal", "timeout", "llm", "config", "shape", "refused",
})


def tool_status(result: TurnResult) -> str:
    return str(
        result.trace.get("blocked")
        or result.trace.get("error")
        or result.trace.get("fallback")
        or (
            "refused" if result.band == "refuse"
            else "no_match" if result.trace.get("hit") is False
            else "ok"
        )
    )


def decide_continue(
    ctx: TurnContext,
    *,
    tools_run: list[str],
    last_tool: str,
    last_result: TurnResult,
) -> RoutePlan | None:
    """Return the next plan, or None to stop."""
    if len(tools_run) >= MAX_AGENT_STEPS:
        return None
    if last_tool == "draft.propose_cardinality":
        return None
    if last_tool == "scope.refuse":
        return None
    status = tool_status(last_result)
    # FAQ miss is band=refuse with hit=False; still allow a follow-up encyclopedia try.
    faq_miss = last_tool == "faq.answer" and last_result.trace.get("hit") is False
    if last_result.band == "refuse" and not faq_miss:
        return None
    if status in _STOP_STATUSES and not faq_miss:
        return None

    used = set(tools_run)
    ruled = _rule_continue(ctx, used, last_tool, last_result, status)
    if ruled is not None:
        return ruled
    if last_tool in {"faq.answer", "usage.explain", "usage.explain_channel"}:
        return None
    return _model_continue(ctx, tools_run, last_tool, status)


def _rule_continue(
    ctx: TurnContext,
    used: set[str],
    last_tool: str,
    last_result: TurnResult,
    status: str,
) -> RoutePlan | None:
    from .tools.web_lookup import looks_like_lookup

    # FAQ miss on a lookup-shaped ask → try encyclopedia.
    if last_tool == "faq.answer" and status == "no_match" and "web.lookup" not in used:
        if looks_like_lookup(ctx.message):
            return RoutePlan("web_search", "web.lookup", "loop:faq_miss_to_web")

    # FAQ hit, but the same utterance also asks an encyclopedia question.
    if last_tool == "faq.answer" and status == "ok" and "web.lookup" not in used:
        if looks_like_lookup(ctx.message) and re.search(r"顺便|并且|同时|also|\band\b", ctx.message, re.I):
            return RoutePlan("web_search", "web.lookup", "loop:also_web")

    # Same utterance also asks for usage (when connector-split did not fire).
    if last_tool in {"faq.answer", "web.lookup", "usage.explain_channel"} and status in {"ok", "model_brief"}:
        if "usage.explain" not in used and re.search(
            r"token\s*用量|用量面板|查看用量|token usage|usage dashboard",
            ctx.message,
            re.I,
        ):
            return RoutePlan("local_faq", "usage.explain", "loop:also_usage")

    # Review then cardinality when the same ask clearly wants an edit.
    if last_tool == "draft.open_review" and "draft.propose_cardinality" not in used:
        if is_edit_intent(ctx.message):
            return RoutePlan("product_tool", "draft.propose_cardinality", "loop:also_cardinality")

    return None


def _model_continue(
    ctx: TurnContext,
    tools_run: list[str],
    last_tool: str,
    status: str,
) -> RoutePlan | None:
    if not can_model_route(ctx):
        return None
    remaining = sorted(LOOPABLE_TOOLS - set(tools_run))
    if not remaining:
        return None
    try:
        raw = _call_continue_model(ctx, tools_run, last_tool, status, remaining)
    except BusyError:
        logger.info("Agent continue model busy; keeping completed results")
        return None
    except Exception as error:  # noqa: BLE001
        logger.warning("Agent continue model failed (%s)", type(error).__name__)
        return None
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or "").strip().casefold()
    if action != "continue":
        return None
    plan = parse_route_payload(raw)
    if plan is None or not plan.tool or plan.tool not in remaining:
        return None
    plan.reason = f"loop:model:{plan.reason}" if plan.reason else "loop:model"
    return plan


_CONTINUE_SYSTEM = """你是 ERFlow「语义沙」的续跑判定模块。用户话已执行过若干工具，你只决定是否再跑一步。
只输出一个 JSON 对象：
{"action":"stop"}
或
{"action":"continue","band":"...","tool":"...","reason":"简短原因"}

规则：
1. 用户问题已被充分回答 → stop
2. continue 的 tool 必须从 remaining_tools 里选，且符合 band/tool 白名单
3. 不要重复已跑过的工具；不要为了凑步数而 continue
4. 基数修改(draft.propose_cardinality)仅在用户明确要求改基数且尚未跑过时考虑
5. 不要输出 Markdown 或解释
"""


def _call_continue_model(
    ctx: TurnContext,
    tools_run: list[str],
    last_tool: str,
    status: str,
    remaining: list[str],
) -> dict:
    import json

    from er_generator import extract_json, llm_chat, llm_settings
    from llm_providers import apply_active_to_environ
    from token_usage import record_usage

    apply_active_to_environ()
    provider, model, key, base_url = llm_settings()
    payload = {
        "message": ctx.message,
        "surface": ctx.surface,
        "diagram_kind": ctx.diagram_kind,
        "tools_run": tools_run,
        "last_tool": last_tool,
        "last_status": status,
        "remaining_tools": remaining,
    }
    reply = llm_chat(
        [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        provider,
        model,
        key,
        base_url,
        timeout=20,
        stream=False,
        system_prompt=_CONTINUE_SYSTEM,
        on_usage=record_usage,
    )
    return extract_json(reply)
