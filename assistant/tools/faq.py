from __future__ import annotations

from ..knowledge import lookup_faq, scope_refuse
from ..types import Locale, TurnContext, TurnMessage, TurnResult


def answer_faq(ctx: TurnContext) -> TurnResult:
    locale: Locale = ctx.locale if ctx.locale in ("zh", "en") else "zh"
    hit = lookup_faq(ctx.message, locale)
    if hit:
        return TurnResult(
            band="local_faq",
            messages=[TurnMessage(role="bot", text=hit)],
            trace={"tool": "faq.answer", "hit": True},
        )
    return TurnResult(
        band="refuse",
        messages=[TurnMessage(role="bot", text=scope_refuse(locale))],
        trace={"tool": "faq.answer", "hit": False},
    )


def refuse_scope(ctx: TurnContext) -> TurnResult:
    locale: Locale = ctx.locale if ctx.locale in ("zh", "en") else "zh"
    return TurnResult(
        band="refuse",
        messages=[TurnMessage(role="bot", text=scope_refuse(locale))],
        trace={"tool": "scope.refuse"},
    )
