"""Hard gates that run before routing."""
from __future__ import annotations

import re

from .knowledge import empty_prompt, scope_refuse
from .types import Locale, RoutePlan, TurnContext, TurnMessage, TurnResult

# Obvious off-product / sensitive probes — keep narrow; router still owns soft refuse.
_REFUSE_RE = re.compile(
    r"(习近平|毛泽东|台湾独立|法轮功|色情|赌博|毒品|"
    r"\b(who\s+is\s+xi|porn|gambling)\b)",
    re.I,
)

_MODEL_IDENTITY_RE = re.compile(
    r"(你是什么模型|你用的什么模型|哪个模型|当前模型|what\s+model|which\s+model|are\s+you\s+(?:gpt|claude|an?\s+ai))",
    re.I,
)

_CHECK_RE = re.compile(
    r"^(?:请\s*)?(?:帮我\s*)?(?:检查|审查|核对)(?:一下)?|^(?:please\s+)?(?:check|review)\b",
    re.I,
)

_EDIT_RE = re.compile(
    r"改成|改为|替换|帮我改|基数|限制|只能|仅能|最多|至多|不超过|"
    r"^(?:请\s*)?(?:帮我\s*)?(?:修改|添加|删除)|"
    r"\b(?:change|replace|add|delete|modify|cardinality|at\s+most|at\s+least)\b",
    re.I,
)


def is_check_intent(message: str) -> bool:
    return bool(_CHECK_RE.search(message.strip()))


def is_edit_intent(message: str) -> bool:
    return bool(_EDIT_RE.search(message.strip()))


def is_model_identity(message: str) -> bool:
    return bool(_MODEL_IDENTITY_RE.search(message.strip()))


def is_hard_refuse(message: str) -> bool:
    return bool(_REFUSE_RE.search(message.strip()))


def preflight(ctx: TurnContext) -> TurnResult | None:
    """Return an early TurnResult when a hard gate fires; else None."""
    locale: Locale = ctx.locale if ctx.locale in ("zh", "en") else "zh"
    text = ctx.message.strip()
    if not text:
        return TurnResult(
            band="refuse",
            messages=[TurnMessage(role="bot", text=empty_prompt(locale))],
            trace={"gate": "empty", "reason": "empty_input"},
        )
    if is_hard_refuse(text):
        return TurnResult(
            band="refuse",
            messages=[TurnMessage(role="bot", text=scope_refuse(locale))],
            trace={"gate": "policy_refuse", "reason": "hard_refuse"},
        )
    return None


def force_plan(ctx: TurnContext) -> RoutePlan | None:
    """Deterministic plans that should not wait for soft FAQ matching."""
    text = ctx.message.strip()
    if is_check_intent(text):
        return RoutePlan(band="open_review", tool="draft.open_review", reason="check_intent")
    if is_model_identity(text):
        return RoutePlan(band="local_faq", tool="usage.explain_channel", reason="model_identity")
    if is_edit_intent(text):
        return RoutePlan(band="product_tool", tool="draft.propose_cardinality", reason="edit_intent")
    return None
