"""本机大模型渠道配置（New API 风格）：统一接入各类 OpenAI / Anthropic 兼容接口。

参考 QuantumNous/new-api：先配渠道（供应商 + Key + 模型），再让 ERFlow 走当前启用项。
配置写在 llm.local.json，不要提交。Web 出图/生成以 API 平台启用项为准。
"""
from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from request_scope import current_scope

CONFIG_PATH = Path(__file__).with_name("llm.local.json")
BUNDLE_FORMAT = "erflow-providers"
BUNDLE_VERSION = 1
LLM_ENV_KEYS = (
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)

# 预设对齐 New API 常见渠道：https://github.com/QuantumNous/new-api
PRESETS: dict[str, dict[str, str]] = {
    "newapi": {
        "name": "New API 网关",
        "kind": "openai",
        "base_url": "http://127.0.0.1:3000/v1",
        "api_key": "",
        "model": "",
        "hint": "自建 New API（QuantumNous/new-api）。控制台建渠道与令牌后，填这里的 Base URL 与令牌，再「拉取模型」。",
    },
    "siliconflow": {
        "name": "硅基流动",
        "kind": "openai",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key": "",
        "model": "deepseek-ai/DeepSeek-V3",
        "hint": "国内 OpenAI 兼容接口，填 API Key 即可。",
    },
    "deepseek": {
        "name": "DeepSeek",
        "kind": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "hint": "DeepSeek 官方 OpenAI 兼容接口。",
    },
    "openai": {
        "name": "OpenAI",
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "hint": "官方 OpenAI Chat Completions。",
    },
    "anthropic": {
        "name": "Anthropic",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key": "",
        "model": "claude-sonnet-4-5",
        "hint": "Anthropic Messages API。",
    },
    "openrouter": {
        "name": "OpenRouter",
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "",
        "model": "openai/gpt-4o-mini",
        "hint": "聚合多家上游，模型 ID 形如 provider/model。",
    },
    "gemini": {
        "name": "Google Gemini",
        "kind": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key": "",
        "model": "gemini-2.0-flash",
        "hint": "Google Gemini 的 OpenAI 兼容端点。",
    },
    "moonshot": {
        "name": "Moonshot",
        "kind": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "api_key": "",
        "model": "moonshot-v1-8k",
        "hint": "月之暗面 Kimi OpenAI 兼容接口。",
    },
    "dashscope": {
        "name": "通义千问",
        "kind": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen-plus",
        "hint": "阿里云 DashScope 兼容模式。",
    },
    "xiaomi": {
        "name": "小米 MiMo",
        "kind": "openai",
        "base_url": "https://api.xiaomimimo.com/v1",
        "api_key": "",
        "model": "mimo-v2.5",
        "hint": "小米 MiMo 按量付费 OpenAI 兼容接口；Token Plan 请改用专属 Base URL。",
    },
    "hunyuan": {
        "name": "腾讯混元",
        "kind": "openai",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "api_key": "",
        "model": "hunyuan-turbos-latest",
        "hint": "腾讯混元 / TokenHub OpenAI 兼容接口。",
    },
    "zhipu": {
        "name": "智谱 GLM",
        "kind": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "",
        "model": "glm-4.5-air",
        "hint": "智谱开放平台 OpenAI 兼容接口。",
    },
    "doubao": {
        "name": "豆包 / 火山方舟",
        "kind": "openai",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key": "",
        "model": "",
        "hint": "字节火山方舟；模型 ID 多为控制台创建的接入点 ep-…。",
    },
    "qianfan": {
        "name": "百度千帆",
        "kind": "openai",
        "base_url": "https://qianfan.baidubce.com/v2",
        "api_key": "",
        "model": "ernie-4.0-8k",
        "hint": "百度智能云千帆 OpenAI 兼容接口。",
    },
    "minimax": {
        "name": "MiniMax",
        "kind": "openai",
        "base_url": "https://api.minimax.cn/v1",
        "api_key": "",
        "model": "MiniMax-M2.5",
        "hint": "MiniMax 国内 OpenAI 兼容接口（亦常见 api.minimaxi.com）。",
    },
    "stepfun": {
        "name": "阶跃星辰",
        "kind": "openai",
        "base_url": "https://api.stepfun.com/v1",
        "api_key": "",
        "model": "step-2-16k",
        "hint": "阶跃星辰 OpenAI 兼容接口。",
    },
    "baichuan": {
        "name": "百川",
        "kind": "openai",
        "base_url": "https://api.baichuan-ai.com/v1",
        "api_key": "",
        "model": "Baichuan4",
        "hint": "百川智能 OpenAI 兼容接口。",
    },
    "yi": {
        "name": "零一万物",
        "kind": "openai",
        "base_url": "https://api.lingyiwanwu.com/v1",
        "api_key": "",
        "model": "yi-lightning",
        "hint": "零一万物 Yi OpenAI 兼容接口。",
    },
    "spark": {
        "name": "讯飞星火",
        "kind": "openai",
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "api_key": "",
        "model": "generalv3.5",
        "hint": "讯飞星火 HTTP OpenAI 兼容；Key 填控制台 APIPassword。",
    },
    "sensenova": {
        "name": "商汤日日新",
        "kind": "openai",
        "base_url": "https://api.sensenova.cn/compatible-mode/v1",
        "api_key": "",
        "model": "SenseChat-5",
        "hint": "商汤 SenseNova 兼容模式。",
    },
    "modelscope": {
        "name": "魔搭 ModelScope",
        "kind": "openai",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "api_key": "",
        "model": "",
        "hint": "魔搭推理 OpenAI 兼容接口，模型以控制台为准。",
    },
    "groq": {
        "name": "Groq",
        "kind": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "",
        "model": "llama-3.3-70b-versatile",
        "hint": "Groq OpenAI 兼容接口。",
    },
    "mistral": {
        "name": "Mistral",
        "kind": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "api_key": "",
        "model": "mistral-small-latest",
        "hint": "Mistral AI OpenAI 兼容接口。",
    },
    "xai": {
        "name": "xAI Grok",
        "kind": "openai",
        "base_url": "https://api.x.ai/v1",
        "api_key": "",
        "model": "grok-2-latest",
        "hint": "xAI Grok OpenAI 兼容接口。",
    },
    "together": {
        "name": "Together AI",
        "kind": "openai",
        "base_url": "https://api.together.xyz/v1",
        "api_key": "",
        "model": "",
        "hint": "Together AI 聚合推理。",
    },
    "fireworks": {
        "name": "Fireworks",
        "kind": "openai",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "api_key": "",
        "model": "",
        "hint": "Fireworks Inference OpenAI 兼容接口。",
    },
    "ollama": {
        "name": "Ollama",
        "kind": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key": "ollama",
        "model": "",
        "hint": "本机 Ollama 的 OpenAI 兼容端点。",
    },
    "magpie": {
        "name": "Magpie 网关",
        "kind": "openai",
        "base_url": "http://127.0.0.1:3425/v1",
        "api_key": "magpie-erflow",
        "model": "",
        "hint": "本机 Magpie 网关；先在 Magpie 里加好供应商，再点「探测网关」选模型。",
    },
    "custom": {
        "name": "自定义",
        "kind": "openai",
        "base_url": "",
        "api_key": "",
        "model": "",
        "hint": "任意 OpenAI 兼容 Base URL（通常以 /v1 结尾），例如自建 New API 公网地址。",
    },
}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _new_id() -> str:
    return secrets.token_hex(4)


def _empty_store() -> dict:
    return {"active_id": None, "providers": []}


def load_store() -> dict:
    scope = current_scope.get()
    if scope is not None:
        data = scope.store
    else:
        if not CONFIG_PATH.is_file():
            return _empty_store()
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    providers = data.get("providers")
    if not isinstance(providers, list):
        providers = []
    cleaned = []
    for item in providers:
        if not isinstance(item, dict):
            continue
        entry = normalize_provider(item, keep_id=True)
        if entry:
            cleaned.append(entry)
    active = _text(data.get("active_id")) or None
    if active and not any(item["id"] == active for item in cleaned):
        active = cleaned[0]["id"] if cleaned else None
    return {"active_id": active, "providers": cleaned}


def save_store(store: dict) -> None:
    scope = current_scope.get()
    if scope is not None:
        scope.store = store
        return
    CONFIG_PATH.write_text(
        json.dumps(store, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize_provider(raw: dict, *, keep_id: bool = False, previous: dict | None = None) -> dict | None:
    kind = _text(raw.get("kind") or (previous or {}).get("kind") or "openai").lower()
    if kind not in {"openai", "anthropic"}:
        return None
    name = _text(raw.get("name") or (previous or {}).get("name")) or "未命名供应商"
    base_url = _text(raw.get("base_url") if "base_url" in raw else (previous or {}).get("base_url"))
    if base_url:
        try:
            endpoint = urlsplit(base_url)
            if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
                return None
        except ValueError:
            return None
    model = _text(raw.get("model") if "model" in raw else (previous or {}).get("model"))
    preset = _text(raw.get("preset") or (previous or {}).get("preset")) or "custom"
    api_key = raw.get("api_key")
    if api_key is None:
        api_key = (previous or {}).get("api_key") or ""
    else:
        api_key = _text(api_key)
        # 前端回传脱敏串时保留原密钥
        if previous and api_key and "•" in api_key:
            api_key = previous.get("api_key") or ""
    entry_id = _text(raw.get("id")) if keep_id else ""
    if not entry_id:
        entry_id = _text((previous or {}).get("id")) or _new_id()
    return {
        "id": entry_id,
        "name": name[:48],
        "kind": kind,
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": model[:120],
        "preset": preset[:32],
    }


def mask_key(key: str) -> str:
    key = _text(key)
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return key[:3] + "•" * max(4, len(key) - 7) + key[-4:]


def public_provider(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "name": entry["name"],
        "kind": entry["kind"],
        "base_url": entry["base_url"],
        "api_key_masked": mask_key(entry.get("api_key") or ""),
        "has_key": bool(_text(entry.get("api_key"))),
        "model": entry["model"],
        "preset": entry.get("preset") or "custom",
        "ready": bool(_text(entry.get("api_key")) and _text(entry.get("model")) and (
            entry["kind"] == "anthropic" or _text(entry.get("base_url"))
        )),
    }


def public_store(store: dict | None = None) -> dict:
    data = store if store is not None else load_store()
    return {
        **({"browser_store": data} if current_scope.get() is not None else {}),
        "active_id": data.get("active_id"),
        "providers": [public_provider(item) for item in data.get("providers") or []],
        "presets": [
            {
                "id": key,
                "name": value["name"],
                "kind": value["kind"],
                "base_url": value["base_url"],
                "model": value["model"],
                "hint": value["hint"],
                "default_key": value["api_key"],
            }
            for key, value in PRESETS.items()
            if current_scope.get() is None or not value["base_url"].startswith("http://")
        ],
    }


def active_provider(store: dict | None = None) -> dict | None:
    data = store or load_store()
    active = data.get("active_id")
    for item in data.get("providers") or []:
        if item["id"] == active:
            return item
    return None


def export_bundle(*, include_secrets: bool = False, store: dict | None = None) -> dict:
    """导出可移植渠道包；默认不含明文 Key，适合课堂模板。"""
    data = store or load_store()
    channels: list[dict] = []
    for item in data.get("providers") or []:
        row = {
            "id": item["id"],
            "name": item["name"],
            "kind": item["kind"],
            "base_url": item["base_url"],
            "model": item["model"],
            "preset": item.get("preset") or "custom",
        }
        if include_secrets:
            row["api_key"] = item.get("api_key") or ""
        else:
            row["has_key"] = bool(_text(item.get("api_key")))
        channels.append(row)
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "include_secrets": bool(include_secrets),
        "active_id": data.get("active_id"),
        "providers": channels,
    }


def import_bundle(payload: Any, *, mode: str = "merge") -> dict:
    """导入渠道包。mode=merge 按 id 覆盖/追加；replace 整表替换。"""
    if not isinstance(payload, dict):
        raise ValueError("导入文件必须是 JSON 对象")
    fmt = _text(payload.get("format"))
    if fmt and fmt != BUNDLE_FORMAT:
        raise ValueError(f"无法识别的格式：{fmt}")
    raw_list = payload.get("providers")
    if not isinstance(raw_list, list):
        raise ValueError("缺少 providers 数组")
    mode = (mode or "merge").strip().lower()
    if mode not in {"merge", "replace"}:
        raise ValueError("mode 只能是 merge 或 replace")

    incoming: list[dict] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        entry = normalize_provider(item, keep_id=True)
        if entry:
            incoming.append(entry)
    if not incoming and raw_list:
        raise ValueError("没有可导入的有效渠道")

    store = load_store() if mode == "merge" else _empty_store()
    if mode == "replace":
        store["providers"] = incoming
    else:
        by_id = {item["id"]: item for item in store.get("providers") or []}
        for entry in incoming:
            by_id[entry["id"]] = entry
        store["providers"] = list(by_id.values())

    preferred = _text(payload.get("active_id"))
    if preferred and any(item["id"] == preferred for item in store["providers"]):
        store["active_id"] = preferred
    elif store.get("active_id") and not any(item["id"] == store["active_id"] for item in store["providers"]):
        store["active_id"] = store["providers"][0]["id"] if store["providers"] else None
    elif not store.get("active_id") and store["providers"]:
        store["active_id"] = store["providers"][0]["id"]

    save_store(store)
    return public_store(store)


def clear_llm_environ() -> None:
    """Drop process LLM credentials so shell / old start scripts cannot bypass API 平台."""
    for key in LLM_ENV_KEYS:
        os.environ.pop(key, None)


def apply_active_to_environ() -> None:
    """Sync process env from llm.local.json for er_generator.llm_settings.

    Active ready provider wins. Otherwise clear LLM_* so stale env cannot serve traffic.
    """
    if current_scope.get() is not None:
        return
    entry = active_provider()
    if not entry or not _text(entry.get("api_key")) or not _text(entry.get("model")):
        clear_llm_environ()
        return
    clear_llm_environ()
    os.environ["LLM_PROVIDER"] = entry["kind"]
    os.environ["LLM_MODEL"] = entry["model"]
    os.environ["LLM_API_KEY"] = entry["api_key"]
    if entry["kind"] == "anthropic":
        os.environ["ANTHROPIC_API_KEY"] = entry["api_key"]
        if entry.get("base_url"):
            os.environ["LLM_BASE_URL"] = entry["base_url"]
    else:
        if entry.get("base_url"):
            os.environ["LLM_BASE_URL"] = entry["base_url"]


def _http_json(url: str, headers: dict, timeout: float = 8) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    from model_transport import model_urlopen
    with model_urlopen(request, timeout=timeout) as response:
        payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise ValueError("模型列表响应过大")
        return json.loads(payload.decode("utf-8"))


def probe_gateway(
    base_url: str,
    api_key: str = "",
) -> dict:
    """探测任意 OpenAI 兼容接口的 /models（含 New API / Magpie / 云厂商）。"""
    requested = _text(base_url).rstrip("/")
    if not requested:
        return {
            "ok": False,
            "hello": None,
            "models": [],
            "error": "请先填写 Base URL。",
            "base_url": "",
        }
    endpoint = requested if requested.endswith("/v1") else requested + "/v1"
    root = endpoint[:-3]
    models_url = endpoint + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    # Magpie 可选 hello；多数云厂商没有该接口，失败可忽略
    hello = None
    try:
        hello = _http_json(root + "/api/hello", {}, timeout=2)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        hello = None
    models: list[dict] = []
    try:
        payload = _http_json(models_url, headers, timeout=8)
        raw = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                model_id = _text(item.get("id"))
                if not model_id:
                    continue
                models.append({
                    "id": model_id,
                    "display_name": _text(item.get("display_name") or item.get("id")),
                    "owned_by": _text(item.get("owned_by")),
                })
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as error:
        return {
            "ok": False,
            "hello": hello,
            "models": [],
            "error": f"无法读取模型列表：{type(error).__name__}。请确认 Base URL 与 API Key 正确，服务可访问。",
            "base_url": requested,
        }
    return {
        "ok": True,
        "hello": hello,
        "models": models,
        "base_url": requested,
        "error": None if models else "接口已连通，但还没有返回可用模型。",
    }


def list_openai_models(base_url: str, api_key: str) -> list[dict]:
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/v1"):
        endpoint = endpoint + "/v1"
    payload = _http_json(
        endpoint + "/models",
        {"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    raw = payload.get("data") if isinstance(payload, dict) else None
    models = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            model_id = _text(item.get("id"))
            if model_id:
                models.append({"id": model_id, "display_name": model_id})
    return models
