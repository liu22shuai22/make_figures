"""Executor / harness: policy → route → tool → result."""
from __future__ import annotations

from .policy import preflight
from .registry import run_tool
from .router import can_model_route, route
from .types import TurnContext, TurnResult


def execute_turn(ctx: TurnContext) -> TurnResult:
    early = preflight(ctx)
    if early is not None:
        return early

    plan = route(ctx)
    tool_name = plan.tool or "scope.refuse"
    result = run_tool(tool_name, ctx)
    result.trace = {
        **result.trace,
        "route_band": plan.band,
        "route_tool": plan.tool,
        "route_reason": plan.reason,
        "model_router_eligible": can_model_route(ctx),
        "routed_by_model": str(plan.reason or "").startswith("model"),
    }
    return result
