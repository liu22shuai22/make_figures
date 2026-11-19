from __future__ import annotations

from ..types import Locale, TurnContext, TurnMessage, TurnResult


def explain_usage(ctx: TurnContext) -> TurnResult:
    text = ("用量页按服务商和渠道汇总本机记录的模型请求、输入和输出 Token。"
            if ctx.locale == "zh" else
            "Usage shows this installation’s model requests and input/output tokens by provider and channel.")
    return TurnResult("local_faq", [TurnMessage("bot", text)], actions=[{"type": "show_usage"}],
                      trace={"tool": "usage.explain"})


def explain_channel(ctx: TurnContext) -> TurnResult:
    locale: Locale = ctx.locale if ctx.locale in ("zh", "en") else "zh"
    try:
        from llm_providers import active_provider

        entry = active_provider()
    except Exception:  # noqa: BLE001 — never break the turn
        entry = None

    if not entry or not str(entry.get("model") or "").strip():
        text = (
            "当前还没有接通可用的模型渠道。请到 API 平台接入并启用一条渠道；"
            "「使用问答」里的产品说明仍可本地回答，改基数等能力需要启用模型。"
            if locale == "zh"
            else "No active model channel yet. Connect one in the API platform. "
            "Product Q&A still works locally; cardinality edits need an active model."
        )
        return TurnResult(
            band="local_faq",
            messages=[TurnMessage(role="bot", text=text)],
            trace={"tool": "usage.explain_channel", "active": False},
        )

    name = str(entry.get("name") or entry.get("id") or "channel")
    model = str(entry.get("model"))
    host = str(entry.get("base_url") or "")
    if locale == "zh":
        text = (
            f"语义沙的「使用问答」里，产品说明走本地知识库；"
            f"改基数、用例语义审查等会调用你启用的渠道。"
            f"当前启用：{name} · 模型 {model}"
            + (f" · {host}" if host else "")
            + "。"
        )
    else:
        text = (
            "Semantic Sand answers product FAQ from a local knowledge base; "
            "cardinality edits and use-case semantic review use your active channel. "
            f"Active now: {name} · model {model}"
            + (f" · {host}" if host else "")
            + "."
        )
    return TurnResult(
        band="local_faq",
        messages=[TurnMessage(role="bot", text=text)],
        trace={"tool": "usage.explain_channel", "active": True, "model": model, "name": name},
    )
