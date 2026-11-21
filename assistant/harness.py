"""Execute turns: connector-split product tools, or a capped agent loop."""
from __future__ import annotations

from request_limits import BusyError

from dataclasses import replace
import logging
import re
from time import perf_counter

from .loop import MAX_AGENT_STEPS, decide_continue, tool_status
from .policy import preflight
from .registry import run_tool
from .router import can_model_route, route, rule_route
from .types import RoutePlan, TurnContext, TurnMessage, TurnResult

logger = logging.getLogger(__name__)

# Explicit multi-tool: connectors, hard cap, product tools (no web / refuse).
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

    eligible = can_model_route(ctx)
    clauses = _requests(ctx)
    # Connector-split stays a plain sequential pass (no agent continue on top).
    if len(clauses) > 1:
        return _run_sequence(ctx, clauses, steps, start, eligible, record, agent_loop=False)

    return _run_sequence(ctx, clauses, steps, start, eligible, record, agent_loop=True)


def _run_sequence(ctx, clauses, steps, start, eligible, record, *, agent_loop: bool) -> TurnResult:
    merged = TurnResult("refuse")
    planned_at = perf_counter()
    tools_run: list[str] = []
    stop_reason = "done"
    looped = False

    for request, plan in clauses:
        plan = plan or route(request)
        while True:
            tool = plan.tool or "scope.refuse"
            model_route = str(plan.reason).startswith("model:") or plan.reason in {"model", "loop:model"}
            route_label = "loop" if str(plan.reason).startswith("loop:") else ("model" if model_route else "rule")
            record("route", tool, route_label, planned_at)
            called_at = perf_counter()
            try:
                result = run_tool(tool, request)
            except BusyError:
                raise
            except Exception:
                logger.exception("Assistant tool failed: %s", tool)
                text = "这一步执行失败，请稍后重试。" if ctx.locale == "zh" else "This step failed. Please try again."
                result = TurnResult(plan.band, [TurnMessage("bot", text)], trace={"tool": tool, "error": "internal"})
            status = tool_status(result)
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

            if not agent_loop:
                break
            if len(tools_run) >= MAX_AGENT_STEPS:
                stop_reason = "max_steps"
                break
            nxt = decide_continue(ctx, tools_run=tools_run, last_tool=tool, last_result=result)
            if nxt is None:
                stop_reason = "done"
                break
            looped = True
            plan = nxt
            record("loop", nxt.tool or "continue", nxt.reason or "continue", planned_at)
            planned_at = perf_counter()

    merged.trace["steps"] = steps
    merged.trace["tools"] = tools_run
    merged.trace["combined"] = len(tools_run) > 1 and not looped
    merged.trace["agent_loop"] = looped
    if agent_loop:
        merged.trace["loop_stop"] = stop_reason
        merged.trace["loop_steps"] = len(tools_run)
    return merged
