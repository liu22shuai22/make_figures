from __future__ import annotations

from ..policy import has_binary_relation
from ..types import Locale, TurnContext, TurnMessage, TurnResult


def _locale(ctx: TurnContext) -> Locale:
    return ctx.locale if ctx.locale in ("zh", "en") else "zh"


def propose_cardinality(ctx: TurnContext) -> TurnResult:
    locale = _locale(ctx)
    if not has_binary_relation(ctx.spec):
        text = (
            "请先打开一份含有联系的 E-R 图草稿，再告诉我怎么改基数。"
            if locale == "zh"
            else "Open an E-R draft with a relation before asking to change cardinality."
        )
        return TurnResult(
            band="product_tool",
            messages=[TurnMessage(role="bot", text=text)],
            trace={"tool": "draft.propose_cardinality", "blocked": "no_relation"},
        )

    from assistant_edit import propose_cardinality as propose
    from er_generator import (
        LLMConfigurationError,
        LLMError,
        LLMTimeoutError,
        SpecError,
        normalize_spec,
    )
    from llm_providers import apply_active_to_environ
    from pydantic import ValidationError

    from api import public_spec, validate_web_spec

    try:
        apply_active_to_environ()
        model = normalize_spec(ctx.spec, report_isolated=False)
        validate_web_spec(model)
        relations = [
            {key: relation[key] for key in ("name", "entities", "card")}
            for relation in public_spec(model)["relations"]
        ]
        if not any(
            len(relation["entities"]) == 2 and len(set(relation["entities"])) == 2
            for relation in relations
        ):
            text = (
                "请先添加一条连接两个不同实体的二元联系。"
                if locale == "zh"
                else "Add a binary relation between two different entities first."
            )
            return TurnResult(
                band="product_tool",
                messages=[TurnMessage(role="bot", text=text)],
                trace={"tool": "draft.propose_cardinality", "blocked": "no_binary"},
            )

        result = propose(ctx.message, relations)
    except LLMConfigurationError:
        text = (
            "未配置可用的大模型，请到 API 平台接入并启用渠道。"
            if locale == "zh"
            else "No usable model channel — connect one in the API platform."
        )
        return TurnResult(
            band="product_tool",
            messages=[TurnMessage(role="bot", text=text)],
            trace={"tool": "draft.propose_cardinality", "error": "config"},
        )
    except LLMTimeoutError:
        text = (
            "理解修改要求超时，请稍后重试。"
            if locale == "zh"
            else "Timed out while interpreting the edit. Try again shortly."
        )
        return TurnResult(
            band="product_tool",
            messages=[TurnMessage(role="bot", text=text)],
            trace={"tool": "draft.propose_cardinality", "error": "timeout"},
        )
    except LLMError as error:
        text = (
            f"模型调用失败：{error}"
            if locale == "zh"
            else f"Model call failed: {error}"
        )
        return TurnResult(
            band="product_tool",
            messages=[TurnMessage(role="bot", text=text)],
            trace={"tool": "draft.propose_cardinality", "error": "llm"},
        )
    except (SpecError, ValidationError, TypeError, KeyError, ValueError):
        text = (
            "模型已返回，但基数修改建议的格式无效。"
            if locale == "zh"
            else "The model replied, but the cardinality suggestion was invalid."
        )
        return TurnResult(
            band="product_tool",
            messages=[TurnMessage(role="bot", text=text)],
            trace={"tool": "draft.propose_cardinality", "error": "shape"},
        )

    model_name = str(result.get("model") or "")
    choices = result.get("choices") or []
    if locale == "zh":
        header = f"收到模型「{model_name}」的返回结果。" if model_name else "已收到模型返回。"
    else:
        header = f"Received a response from {model_name}." if model_name else "Received a model response."
    if not choices:
        follow = (
            "请说明要限制哪两个实体之间的数量，以及哪一端要改。例如「限制每个学生最多选一门课」。"
            if locale == "zh"
            else "Name both entities and which end to change, e.g. limit each student to one course."
        )
        return TurnResult(
            band="product_tool",
            messages=[
                TurnMessage(role="bot", text=header),
                TurnMessage(role="bot", text=follow),
            ],
            cardinality={"choices": [], "model": model_name},
            trace={"tool": "draft.propose_cardinality", "choices": 0, "model": model_name},
        )
    return TurnResult(
        band="product_tool",
        messages=[TurnMessage(role="bot", text=header)],
        cardinality={"choices": choices, "model": model_name},
        trace={"tool": "draft.propose_cardinality", "choices": len(choices), "model": model_name},
    )
