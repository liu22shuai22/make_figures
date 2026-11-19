"""Controlled external lookup via Wikipedia (no API key)."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from ..types import Locale, TurnContext, TurnMessage, TurnResult

logger = logging.getLogger(__name__)

_UA = "ERFlowSemanticSand/0.1 (local assistant; educational)"
_TIMEOUT = 12

_STRIP_RE = re.compile(
    r"^(?:请\s*)?(?:帮我\s*)?(?:介绍一下|讲讲|说说|查一下|搜索)?"
    r"(?:你知道|知道|了解)?\s*"
    r"(?:什么是|啥是|who\s+is|what\s+is|what's|tell\s+me\s+about)?\s*",
    re.I,
)
_TRAIL_RE = re.compile(r"[?？!！。.\s]+$|(?:吗|呢|啊|呀)+$")


def lookup(ctx: TurnContext) -> TurnResult:
    from ..memory import resolve_lookup_query

    locale: Locale = ctx.locale if ctx.locale in ("zh", "en") else "zh"
    extracted = extract_lookup_query(ctx.message)
    query, topic_used = resolve_lookup_query(ctx, extracted)
    if not query:
        text = (
            "请用更具体的名称再问一次，例如「什么是 UML」或「介绍一下范式」。"
            if locale == "zh"
            else "Ask with a clearer name, e.g. “What is UML?” or “Tell me about ER models.”"
        )
        return TurnResult(
            band="web_search",
            messages=[TurnMessage(role="bot", text=text)],
            trace={"tool": "web.lookup", "blocked": "empty_query"},
        )

    wiki_error = None
    page = None
    try:
        page = _wikipedia_summary(query, locale)
    except Exception as error:  # noqa: BLE001
        wiki_error = type(error).__name__
        logger.warning("Wikipedia lookup failed (%s)", wiki_error)

    if page:
        title = page["title"]
        extract = page["extract"]
        url = page["url"]
        if locale == "zh":
            text = f"「{title}」\n{extract}\n\n来源：维基百科 · {url}\n（受控外联检索，仅作参考。）"
        else:
            text = (
                f"“{title}”\n{extract}\n\nSource: Wikipedia · {url}\n"
                "(Controlled web lookup; for reference only.)"
            )
        return TurnResult(
            band="web_search",
            messages=[TurnMessage(role="bot", text=text)],
            trace={
                "tool": "web.lookup",
                "hit": True,
                "query": query,
                "title": title,
                "url": url,
                "topic": title,
                "follow_up_of": topic_used,
            },
        )

    # Encyclopedia unreachable or empty → brief answer via active model when possible.
    brief = _model_brief_answer(query, locale) if ctx.authenticated else None
    if brief is not None:
        note = (
            "（百科外联暂不可用，以下为启用模型的简要说明，仅供参考。）"
            if locale == "zh"
            else "(Encyclopedia lookup unavailable; brief answer from your active model.)"
        )
        topic = topic_used or extracted or query
        return TurnResult(
            band="web_search",
            messages=[TurnMessage(role="bot", text=f"{brief}\n\n{note}")],
            trace={
                "tool": "web.lookup",
                "hit": False,
                "fallback": "model_brief",
                "query": query,
                "wiki_error": wiki_error,
                "topic": topic,
                "follow_up_of": topic_used,
            },
        )

    if wiki_error:
        text = (
            f"没能查到「{query}」的可靠公开资料。请确认已接通模型渠道，或稍后再试。"
            if locale == "zh"
            else f"Could not reach a public page for “{query}”. Connect a model channel, or try again later."
        )
    else:
        text = (
            f"公开百科里没有找到与「{query}」足够匹配的条目。"
            if locale == "zh"
            else f"No close encyclopedia match for “{query}”."
        )
    return TurnResult(
        band="web_search",
        messages=[TurnMessage(role="bot", text=text)],
        trace={"tool": "web.lookup", "hit": False, "query": query, "wiki_error": wiki_error},
    )


def extract_lookup_query(message: str) -> str:
    text = message.strip()
    text = _STRIP_RE.sub("", text).strip()
    text = _TRAIL_RE.sub("", text).strip()
    text = re.sub(r"^(?:关于|有关)\s*", "", text).strip()
    return text[:80]


def looks_like_lookup(message: str) -> bool:
    text = message.strip()
    if len(text) < 2:
        return False
    return bool(
        re.search(
            r"你知道|什么是|啥是|介绍一下|讲讲|是什么|who\s+is|what\s+is|what's|tell\s+me\s+about|介绍下",
            text,
            re.I,
        )
    )


_ACRONYM_RE = re.compile(r"^[A-Za-z]{2,8}$")
_YEAR_PREFIX_RE = re.compile(r"^(?:19|20)\d{2}")


def _is_acronym(query: str) -> bool:
    return bool(_ACRONYM_RE.fullmatch(query.strip()))


def _paren_defines_acronym(text: str, acronym: str) -> bool:
    """Wikipedia leads often introduce a topic as “Full Name (ACRONYM)”."""
    return bool(
        re.search(rf"[\(（]\s*{re.escape(acronym)}\s*[\)）]", text[:360], re.I)
    )


def _compound_acronym_title(title: str, acronym: str) -> bool:
    """Title embeds the acronym plus other content (nested/event pages)."""
    if not re.search(re.escape(acronym), title, flags=re.I):
        return False
    leftover = re.sub(re.escape(acronym), "", title, count=1, flags=re.I)
    leftover = re.sub(r"[\s\-–—:/·•、,，.。()（）\[\]]+", "", leftover)
    return len(leftover) >= 2


def _wikipedia_summary(query: str, locale: Locale) -> dict[str, str] | None:
    primary = "zh" if locale == "zh" else "en"
    secondary = "en" if primary == "zh" else "zh"
    # Latin acronyms: English first (cleaner redirects), then Chinese search.
    langs = ("en", "zh") if _is_acronym(query) else (primary, secondary)

    candidates: list[tuple[float, dict[str, str]]] = []

    def consider(summary: dict[str, str] | None) -> None:
        if not summary:
            return
        score = _summary_score(query, summary)
        if score >= 20:
            candidates.append((score, summary))

    for lang in langs:
        consider(_summary_for_title(query, lang))

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    for lang in langs:
        hit = _wikipedia_summary_lang(query, lang)
        if hit:
            return hit
    return None


def _wikipedia_summary_lang(query: str, lang: str) -> dict[str, str] | None:
    titles = _search_titles(query, lang)
    if not titles:
        return None
    ranked = sorted(
        ((_summary_score(query, {"title": title, "extract": ""}), title) for title in titles),
        key=lambda item: item[0],
        reverse=True,
    )
    for _, title in ranked[:6]:
        summary = _summary_for_title(title, lang)
        if summary and _summary_score(query, summary) >= 20:
            return summary
    return None


def _search_titles(query: str, lang: str) -> list[str]:
    titles: list[str] = []
    # list=search usually ranks the canonical topic above nested events.
    search_url = (
        f"https://{lang}.wikipedia.org/w/api.php?"
        + urllib.parse.urlencode(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 8,
                "srnamespace": 0,
                "format": "json",
            }
        )
    )
    data = _http_json(search_url)
    if isinstance(data, dict):
        query_block = data.get("query")
        if isinstance(query_block, dict):
            for item in query_block.get("search") or []:
                if isinstance(item, dict) and item.get("title"):
                    titles.append(str(item["title"]))

    if not titles:
        open_url = (
            f"https://{lang}.wikipedia.org/w/api.php?"
            + urllib.parse.urlencode(
                {
                    "action": "opensearch",
                    "search": query,
                    "limit": 8,
                    "namespace": 0,
                    "format": "json",
                }
            )
        )
        open_data = _http_json(open_url)
        if isinstance(open_data, list) and len(open_data) > 1:
            titles.extend(str(item) for item in open_data[1] if item)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for title in titles:
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(title)
    return unique


def _title_score(query: str, title: str) -> float:
    q = query.strip()
    t = title.strip()
    if not q or not t:
        return -100.0
    ql, tl = q.casefold(), t.casefold()
    score = 0.0
    if ql == tl:
        score += 100.0
    elif tl.startswith(ql) and (len(tl) == len(ql) or not tl[len(ql)].isalnum()):
        score += 70.0
    elif ql in tl:
        score += 20.0
    # Prefer compact canonical pages over long event/subtopic titles.
    score -= max(0, len(t) - max(len(q), 8)) * 0.8
    if _YEAR_PREFIX_RE.match(t):
        score -= 45.0
    if _is_acronym(q) and _compound_acronym_title(t, q):
        # Acronym is only a slice of the title (side event / nested page).
        score -= 50.0
    return score


def _summary_score(query: str, summary: dict[str, str]) -> float:
    title = summary.get("title") or ""
    extract = summary.get("extract") or ""
    score = _title_score(query, title)
    if not _is_acronym(query):
        return score

    acronym = query.strip()
    blob = f"{title}\n{extract}"
    defined = _paren_defines_acronym(blob, acronym)
    if defined:
        score += 55.0
    elif re.search(rf"(?<![A-Za-z]){re.escape(acronym)}(?![A-Za-z])", extract[:360], re.I):
        score += 20.0

    # Compound acronym titles without a lead definition are almost always side events.
    if _compound_acronym_title(title, acronym) and not defined:
        return -1.0
    if _YEAR_PREFIX_RE.match(title.strip()) and not defined:
        return -1.0
    return score


def _summary_for_title(title: str, lang: str) -> dict[str, str] | None:
    url = (
        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
        + urllib.parse.quote(title.replace(" ", "_"))
    )
    data = _http_json(url)
    if not isinstance(data, dict):
        return None
    extract = str(data.get("extract") or "").strip()
    if not extract:
        return None
    # Keep answers short for chat UI.
    if len(extract) > 600:
        extract = extract[:597].rstrip() + "…"
    page_url = ""
    if isinstance(data.get("content_urls"), dict):
        desktop = data["content_urls"].get("desktop")
        if isinstance(desktop, dict):
            page_url = str(desktop.get("page") or "")
    if not page_url:
        page_url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
    return {
        "title": str(data.get("title") or title),
        "extract": extract,
        "url": page_url,
    }


def _model_brief_answer(query: str, locale: Locale) -> str | None:
    try:
        from er_generator import llm_chat, llm_settings
        from llm_providers import apply_active_to_environ, active_provider
        from token_usage import record_usage
    except Exception:  # noqa: BLE001
        return None

    entry = None
    try:
        entry = active_provider()
    except Exception:  # noqa: BLE001
        entry = None
    if not entry or not str(entry.get("api_key") or "").strip() or not str(entry.get("model") or "").strip():
        return None

    apply_active_to_environ()
    try:
        provider, model, key, base_url = llm_settings()
    except Exception:  # noqa: BLE001
        return None

    if locale == "zh":
        system = (
            "你是简明百科助手。用中文回答用户询问的概念/组织/术语，3～6 句，客观准确。"
            "不要编造精确数据；不确定就明说。不要提 ERFlow，不要输出 JSON。"
        )
        user = f"请简要介绍：{query}"
    else:
        system = (
            "You are a concise encyclopedia helper. Answer in English in 3–6 sentences. "
            "Be factual; say when unsure. Do not mention ERFlow. No JSON."
        )
        user = f"Briefly explain: {query}"
    try:
        reply = llm_chat(
            [{"role": "user", "content": user}],
            provider,
            model,
            key,
            base_url,
            timeout=25,
            stream=False,
            system_prompt=system,
            on_usage=record_usage,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Model brief fallback failed", exc_info=False)
        return None
    text = str(reply or "").strip()
    return text[:900] if text else None


def _http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
