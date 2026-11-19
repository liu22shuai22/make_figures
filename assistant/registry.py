"""Tool registry for the execution plane."""
from __future__ import annotations

from collections.abc import Callable

from .tools import cardinality, faq, review, usage_info, web_lookup
from .policy import check_access
from .types import TurnContext, TurnResult

ToolFn = Callable[[TurnContext], TurnResult]

TOOLS: dict[str, ToolFn] = {
    "faq.answer": faq.answer_faq,
    "scope.refuse": faq.refuse_scope,
    "usage.explain_channel": usage_info.explain_channel,
    "usage.explain": usage_info.explain_usage,
    "draft.propose_cardinality": cardinality.propose_cardinality,
    "draft.open_review": review.open_review,
    "web.lookup": web_lookup.lookup,
}


def run_tool(name: str, ctx: TurnContext) -> TurnResult:
    blocked = check_access(name, ctx)
    if blocked:
        return blocked
    tool = TOOLS.get(name)
    if tool is None:
        return faq.refuse_scope(ctx)
    return tool(ctx)
