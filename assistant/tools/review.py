from __future__ import annotations

from ..types import Locale, TurnContext, TurnMessage, TurnResult


def open_review(ctx: TurnContext) -> TurnResult:
    locale: Locale = ctx.locale if ctx.locale in ("zh", "en") else "zh"
    text = (
        "可在「检查模型」查看当前草稿的结构检查结果。"
        if locale == "zh"
        else "Open Check model to see structural findings for your draft."
    )
    return TurnResult(
        band="open_review",
        messages=[TurnMessage(role="bot", text=text)],
        actions=[{"type": "open_review"}],
        trace={"tool": "draft.open_review"},
    )
