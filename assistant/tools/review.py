from __future__ import annotations

from ..types import Locale, TurnContext, TurnMessage, TurnResult


def open_review(ctx: TurnContext) -> TurnResult:
    locale: Locale = ctx.locale if ctx.locale in ("zh", "en") else "zh"
    if ctx.surface != "workbench":
        text = (
            "模型检查在工作台里进行。请先进入工作台，打开或生成一份草稿，再让我检查。"
            if locale == "zh"
            else "Model checks run on the workbench. Open a draft there, then ask me to check."
        )
        return TurnResult(
            band="open_review",
            messages=[TurnMessage(role="bot", text=text)],
            trace={"tool": "draft.open_review", "blocked": "not_workbench"},
        )
    text = (
        "好的，已切换到「检查模型」。结构检查走本地规则；登录后还可检查重复联系。"
        if locale == "zh"
        else "Switched to Check model. Structure uses local rules; sign in to also check duplicate relations."
    )
    return TurnResult(
        band="open_review",
        messages=[TurnMessage(role="bot", text=text)],
        actions=[{"type": "open_review"}],
        trace={"tool": "draft.open_review"},
    )
