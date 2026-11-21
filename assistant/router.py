"""Route one turn: model structured plan with rule fallback (Phase 1)."""
from __future__ import annotations

from request_limits import BusyError

import logging

from .knowledge import lookup_faq
from .policy import force_plan, has_binary_relation
from .registry import TOOLS
from .skills.router_prompt import ROUTER_SYSTEM, router_user_payload
from .types import Band, Locale, RoutePlan, TurnContext

logger = logging.getLogger(__name__)

_BAND_TOOLS: dict[Band, set[str]] = {
    "local_faq": {"faq.answer", "usage.explain_channel", "usage.explain"},
    "product_tool": {"draft.propose_cardinality"},
    "refuse": {"scope.refuse"},
    "open_review": {"draft.open_review"},
    "web_search": {"web.lookup"},
}


def route(ctx: TurnContext) -> RoutePlan:
    """Prefer model router when eligible; always safe to call repeatedly."""
    forced = force_plan(ctx)
    # Keep cheap deterministic intents off the model (check / identity / clear edit).
    if forced is not None:
        return forced

    if lookup_faq(ctx.message, ctx.locale):
        return rule_route(ctx)

    model_plan = try_model_route(ctx)
    if model_plan is not None:
        return model_plan
    return rule_route(ctx)


def rule_route(ctx: TurnContext) -> RoutePlan:
    forced = force_plan(ctx)
    if forced is not None:
        return forced

    locale: Locale = ctx.locale if ctx.locale in ("zh", "en") else "zh"
    if lookup_faq(ctx.message, locale):
        return RoutePlan(band="local_faq", tool="faq.answer", reason="knowledge_hit")

    from .memory import last_topic, looks_like_follow_up
    from .tools.web_lookup import looks_like_lookup

    if looks_like_lookup(ctx.message):
        return RoutePlan(band="web_search", tool="web.lookup", reason="lookup_pattern")

    if last_topic(ctx) and looks_like_follow_up(ctx.message):
        return RoutePlan(band="web_search", tool="web.lookup", reason="follow_up_topic")

    return RoutePlan(band="refuse", tool="scope.refuse", reason="out_of_scope")


def can_model_route(ctx: TurnContext) -> bool:
    if not ctx.authenticated:
        return False
    try:
        from llm_providers import active_provider

        entry = active_provider()
    except BusyError:
        return False
    except Exception:  # noqa: BLE001
        return False
    if not entry:
        return False
    return bool(str(entry.get("api_key") or "").strip() and str(entry.get("model") or "").strip())


def try_model_route(ctx: TurnContext) -> RoutePlan | None:
    if not can_model_route(ctx):
        return None
    try:
        raw = _call_router_model(ctx)
        plan = parse_route_payload(raw)
        if plan is None:
            logger.info("Assistant model router returned unusable plan")
            return None
        plan.reason = f"model:{plan.reason}" if plan.reason else "model"
        return plan
    except BusyError:
        logger.info("Assistant model router busy; using rule route")
        return None
    except Exception as error:  # noqa: BLE001 — always fall back to rules
        logger.warning("Assistant model router failed (%s); using rule route", type(error).__name__)
        return None


def parse_route_payload(raw) -> RoutePlan | None:
    if not isinstance(raw, dict):
        return None
    band = str(raw.get("band") or "").strip()
    tool = str(raw.get("tool") or "").strip()
    reason = str(raw.get("reason") or "").strip()[:120]
    if band not in _BAND_TOOLS or tool not in TOOLS:
        return None
    if tool not in _BAND_TOOLS[band]:  # type: ignore[index]
        return None
    return RoutePlan(band=band, tool=tool, reason=reason or "model")  # type: ignore[arg-type]


def _call_router_model(ctx: TurnContext) -> dict:
    from er_generator import extract_json, llm_chat, llm_settings
    from llm_providers import apply_active_to_environ
    from token_usage import record_usage

    from .memory import last_topic

    apply_active_to_environ()
    provider, model, key, base_url = llm_settings()
    payload = router_user_payload(
        ctx.message,
        surface=ctx.surface,
        diagram_kind=ctx.diagram_kind,
        has_relations=has_binary_relation(ctx.spec),
        history_topic=last_topic(ctx),
    )
    reply = llm_chat(
        [{"role": "user", "content": payload}],
        provider,
        model,
        key,
        base_url,
        timeout=20,
        stream=False,
        system_prompt=ROUTER_SYSTEM,
        on_usage=record_usage,
    )
    return extract_json(reply)
