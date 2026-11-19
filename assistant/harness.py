"""Execute explicit product requests in order. Each tool sees only its own clause."""
from __future__ import annotations

from dataclasses import replace
import logging
import re
from time import perf_counter

from .policy import preflight
from .registry import run_tool
from .router import can_model_route, route, rule_route
from .types import RoutePlan, TurnContext, TurnMessage, TurnResult

logger = logging.getLogger(__name__)

# Lightweight multi-tool only: explicit connectors, hard cap, product tools (no web / refuse).
_SEPARATOR = re.compile(r"[；;。？?]|(?:然后|并且|顺便|再帮我|同时)|\band (?:then|also)\b", re.I)
_MAX_PARTS = 3
_COMBINABLE_TOOLS = frozenset({
    "faq.answer",
    "usage.explain_channel",
    "usage.explain",
    "draft.open_review",
    "draft.propose_cardinality",
})


def _requests(ctx: TurnContext) -> list[tuple[TurnContext, RoutePlan | None]]:
    parts = [part.strip(" ，,") for part in _SEPARATOR.split(ctx.message) if part.strip(" ，,")]
    if 2 <= len(parts) <= _MAX_PARTS:
        requests = [replace(ctx, message=part) for part in parts]
        plans = [rule_route(request) for request in requests]
        tools = [plan.tool for plan in plans]
        # Distinct product tools only — never split one edit or stack paid/external lookups.
        if len(set(tools)) == len(tools) and all(tool in _COMBINABLE_TOOLS for tool in tools):
            return list(zip(requests, plans))
    return [(ctx, None)]


def execute_turn(ctx: TurnContext) -> TurnResult:
    start = perf_counter()
    steps: list[dict] = []

    def record(stage: str, name: str, status: str, since: float) -> None:
        now = perf_counter()
        steps.append({
            "stage": stage,
            "name": name,
            "status": status,
            "startMs": round((since - start) * 1000),
            "durationMs": round((now - since) * 1000),
        })

    early = preflight(ctx)
    record("policy", "preflight", "blocked" if early else "ok", start)
    if early:
        early.trace["steps"] = steps
        return early

    merged = TurnResult("refuse")
    eligible = can_model_route(ctx)
    planned_at = perf_counter()
    tools_run: list[str] = []
    for request, plan in _requests(ctx):
        plan = plan or route(request)
        tool = plan.tool or "scope.refuse"
        model_route = plan.reason.startswith("model:") or plan.reason == "model"
        record("route", tool, "model" if model_route else "rule", planned_at)
        called_at = perf_counter()
        try:
            result = run_tool(tool, request)
        except Exception:
            logger.exception("Assistant tool failed: %s", tool)
            text = "这一步执行失败，请稍后重试。" if ctx.locale == "zh" else "This step failed. Please try again."
            result = TurnResult(plan.band, [TurnMessage("bot", text)], trace={"tool": tool, "error": "internal"})
        status = (
            result.trace.get("blocked")
            or result.trace.get("error")
            or result.trace.get("fallback")
            or (
                "refused" if result.band == "refuse"
                else "no_match" if result.trace.get("hit") is False
                else "ok"
            )
        )
        record("tool", tool, status, called_at)
        tools_run.append(tool)
        for message in result.messages:
            message.band, message.trace = result.band, dict(result.trace)
        merged.band = result.band
        merged.messages.extend(result.messages)
        merged.actions.extend(result.actions)
        merged.cardinality = result.cardinality or merged.cardinality
        merged.trace = {
            **result.trace,
            "route_band": plan.band,
            "route_tool": tool,
            "route_reason": plan.reason,
            "routed_by_model": model_route,
            "model_router_eligible": eligible,
        }
        planned_at = perf_counter()
    merged.trace["steps"] = steps
    merged.trace["tools"] = tools_run
    merged.trace["combined"] = len(tools_run) > 1
    return merged
