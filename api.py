import base64
from contextlib import redirect_stdout
import json
import logging
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import BoundedSemaphore
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, StringConstraints
from token_usage import read_usage, record_usage
from auth import (
    USERNAME_MAX,
    USERNAME_MIN,
    PASSWORD_MAX,
    PASSWORD_MIN,
    EMAIL_MAX,
    AuthError,
    BadCodeError,
    CodeRateError,
    EmailTakenError,
    InvalidEmailError,
    MailDeliveryError,
    MailNotConfiguredError,
    UsernameTakenError,
    issue_email_code,
    close_session,
    create_user,
    open_session,
    session_username,
    verify_login,
)


app = FastAPI(title="ERFlow")
logger = logging.getLogger(__name__)
render_slot = BoundedSemaphore(1)
generate_slot = BoundedSemaphore(1)
usecase_review_slot = BoundedSemaphore(1)
worker_script = Path(__file__).resolve()
RENDER_REQUEST_LIMIT = 128 * 1024
RENDER_WORKER_TIMEOUT = 55
MODEL_REQUEST_TIMEOUT = 90
MODEL_GENERATION_BUDGET = 120
WEB_TARGET_ENTITIES = 20
WEB_MAX_ENTITIES = 24
WEB_MAX_RELATIONS = 40
WEB_GENERATION_RULES = f"""网页绘图的硬性约束优先于上面的通用设计规则：
- 实体通常控制在 {WEB_TARGET_ENTITIES} 个以内。确有业务需要时可保留到 {WEB_MAX_ENTITIES} 个，整份 JSON 最多 {WEB_MAX_RELATIONS} 条联系。输出前检查两个数组的数量。
- 优先保留用户明确要求的核心实体和业务联系。状态、类型和描述性信息在语义合适时用属性表达。
- 多实体规格中，每个实体都应与其他实体有业务上成立的联系。若将借阅记录、评论这类事件单列为实体，要连接其参与实体；同一业务含义只表达一次。
- 如果超限，重新规划核心模型，合并含义重复的概念，并省略自行补充的外围内容。
- 每个实体或联系最多 12 个属性（含主键），实体、联系和属性名称最多 24 个可显示字符。
- 输出紧凑 JSON，省略缩进与换行。"""


class GenerateRequest(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ReviewRequest(BaseModel):
    spec: dict


class UseCaseReviewRequest(GenerateRequest):
    spec: dict


class CardinalityRequest(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    spec: dict


class AuthCredentials(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=USERNAME_MIN, max_length=USERNAME_MAX)]
    password: Annotated[str, StringConstraints(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)]


class RegisterRequest(AuthCredentials):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=EMAIL_MAX)]
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=6)]


class EmailCodeRequest(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=EMAIL_MAX)]


class LogoutRequest(BaseModel):
    token: str


def bearer_token(authorization: str | None) -> str:
    """从 Authorization: Bearer <token> 里取出会话 token。"""
    if authorization and authorization.startswith("Bearer "):
        return authorization[len("Bearer "):].strip()
    return ""


@app.post("/api/auth/email-code")
def auth_email_code(body: EmailCodeRequest):
    try:
        issue_email_code(body.email)
    except EmailTakenError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except CodeRateError as error:
        raise HTTPException(status_code=429, detail=str(error)) from None
    except InvalidEmailError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except MailNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except (MailDeliveryError, AuthError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    return {"ok": True}


@app.post("/api/auth/register", status_code=201)
def auth_register(credentials: RegisterRequest):
    try:
        token = create_user(credentials.username, credentials.password, credentials.email, credentials.code)
    except (UsernameTakenError, EmailTakenError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except BadCodeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except AuthError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return {"username": credentials.username, "token": token}


@app.post("/api/auth/login")
def auth_login(credentials: AuthCredentials):
    try:
        verify_login(credentials.username, credentials.password)
    except AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from None
    return {"token": open_session(credentials.username), "username": credentials.username}


@app.post("/api/auth/logout")
def auth_logout(request: LogoutRequest):
    close_session(request.token)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(authorization: str | None = Header(default=None)):
    try:
        return {"username": session_username(bearer_token(authorization))}
    except AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from None


def require_render_account(authorization: Annotated[str | None, Header()] = None) -> str:
    try:
        return session_username(bearer_token(authorization))
    except AuthError:
        raise HTTPException(status_code=401, detail="请先登录，再生成或排版 E-R 图") from None


@app.get("/api/usage")
def get_usage():
    try:
        return read_usage()
    except sqlite3.Error:
        logger.exception("Could not read model token usage")
        raise HTTPException(status_code=503, detail="暂时无法读取用量记录") from None


class ProviderUpsert(BaseModel):
    id: str | None = None
    name: str | None = None
    kind: Literal["openai", "anthropic"] | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    preset: str | None = None
    activate: bool = False


class ProviderActive(BaseModel):
    id: str


class GatewayProbeRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None


# 兼容旧前端字段名
MagpieProbeRequest = GatewayProbeRequest


class ModelsProbeRequest(BaseModel):
    base_url: str
    api_key: str | None = None
    id: str | None = None


class ProviderImportRequest(BaseModel):
    bundle: dict
    mode: Literal["merge", "replace"] = "merge"


@app.get("/api/providers", dependencies=[Depends(require_render_account)])
def get_providers():
    from llm_providers import public_store

    return public_store()


@app.get("/api/providers/export", dependencies=[Depends(require_render_account)])
def export_providers(secrets: bool = False):
    from llm_providers import export_bundle

    return export_bundle(include_secrets=secrets)


@app.post("/api/providers/import", dependencies=[Depends(require_render_account)])
def import_providers(body: ProviderImportRequest):
    from llm_providers import import_bundle

    try:
        return import_bundle(body.bundle, mode=body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/providers", dependencies=[Depends(require_render_account)])
def upsert_provider(body: ProviderUpsert):
    from llm_providers import load_store, normalize_provider, public_store, save_store

    store = load_store()
    previous = next((item for item in store["providers"] if item["id"] == body.id), None) if body.id else None
    raw = body.model_dump(exclude_none=False)
    entry = normalize_provider(raw, keep_id=bool(body.id), previous=previous)
    if not entry:
        raise HTTPException(status_code=422, detail="供应商配置无效：请检查接口类型与 Base URL")
    if previous:
        store["providers"] = [entry if item["id"] == previous["id"] else item for item in store["providers"]]
    else:
        store["providers"].append(entry)
    if body.activate or not store.get("active_id"):
        store["active_id"] = entry["id"]
    save_store(store)
    return public_store(store)


@app.put("/api/providers/active", dependencies=[Depends(require_render_account)])
def set_active_provider(body: ProviderActive):
    from llm_providers import load_store, public_store, save_store

    store = load_store()
    if not any(item["id"] == body.id for item in store["providers"]):
        raise HTTPException(status_code=404, detail="找不到该供应商")
    store["active_id"] = body.id
    save_store(store)
    return public_store(store)


@app.delete("/api/providers/{provider_id}", dependencies=[Depends(require_render_account)])
def delete_provider(provider_id: str):
    from llm_providers import load_store, public_store, save_store

    store = load_store()
    before = len(store["providers"])
    store["providers"] = [item for item in store["providers"] if item["id"] != provider_id]
    if len(store["providers"]) == before:
        raise HTTPException(status_code=404, detail="找不到该供应商")
    if store.get("active_id") == provider_id:
        store["active_id"] = store["providers"][0]["id"] if store["providers"] else None
    save_store(store)
    return public_store(store)


@app.post("/api/providers/probe-gateway", dependencies=[Depends(require_render_account)])
def providers_probe_gateway(body: GatewayProbeRequest):
    from llm_providers import probe_gateway

    return probe_gateway(
        body.base_url or "http://127.0.0.1:3000/v1",
        body.api_key or "",
    )


@app.post("/api/providers/probe-magpie", dependencies=[Depends(require_render_account)])
def providers_probe_magpie(body: GatewayProbeRequest):
    """兼容旧路径；默认仍探测 Magpie，也可传 New API 地址。"""
    from llm_providers import probe_gateway

    return probe_gateway(
        body.base_url or "http://127.0.0.1:3425/v1",
        body.api_key or "magpie-erflow",
    )


@app.post("/api/providers/list-models", dependencies=[Depends(require_render_account)])
def providers_list_models(body: ModelsProbeRequest):
    from llm_providers import list_openai_models, load_store

    key = (body.api_key or "").strip()
    if body.id and (not key or "•" in key):
        store = load_store()
        found = next((item for item in store["providers"] if item["id"] == body.id), None)
        if found:
            key = found.get("api_key") or ""
    if not key:
        raise HTTPException(status_code=422, detail="请先填写 API Key")
    try:
        models = list_openai_models(body.base_url, key)
    except Exception as error:  # noqa: BLE001 - 探测失败直接回给前端
        raise HTTPException(status_code=502, detail=f"拉取模型列表失败：{type(error).__name__}") from error
    return {"models": models}


@app.post("/api/assistant/review", dependencies=[Depends(require_render_account)])
def assistant_review(body: ReviewRequest):
    from er_generator import SpecError, normalize_spec
    from model_review import review_model

    if len(render_request_body(body.spec, "png")) > RENDER_REQUEST_LIMIT:
        raise HTTPException(413, "规格太大")
    try:
        model = normalize_spec(body.spec, report_isolated=False)
        validate_web_spec(model)
        spec = public_spec(model)
    except SpecError as error:
        raise HTTPException(422, str(error)) from None
    return review_model(spec)


@app.post("/api/assistant/review-usecase", dependencies=[Depends(require_render_account)])
def assistant_review_usecase(body: UseCaseReviewRequest):
    from er_generator import SpecError
    from llm_providers import apply_active_to_environ
    from model_review import review_usecase

    if len(render_request_body(body.spec, "png", kind="usecase")) > RENDER_REQUEST_LIMIT:
        raise HTTPException(413, "用例图草稿太大")
    if not usecase_review_slot.acquire(blocking=False):
        raise HTTPException(503, "正在审查另一份用例图")
    try:
        apply_active_to_environ()
        return review_usecase(body.text, body.spec)
    except SpecError as error:
        raise HTTPException(422, str(error)) from None
    finally:
        usecase_review_slot.release()


@app.post("/api/assistant/cardinality", dependencies=[Depends(require_render_account)])
def assistant_cardinality(body: CardinalityRequest):
    from pydantic import ValidationError
    from assistant_edit import propose_cardinality
    from er_generator import LLMConfigurationError, LLMError, LLMTimeoutError, SpecError, normalize_spec
    from llm_providers import apply_active_to_environ

    if len(render_request_body(body.spec, "png")) > RENDER_REQUEST_LIMIT:
        raise HTTPException(413, "规格太大")
    try:
        model = normalize_spec(body.spec, report_isolated=False)
        validate_web_spec(model)
    except SpecError as error:
        raise HTTPException(422, str(error)) from None
    relations = [{key: relation[key] for key in ("name", "entities", "card")}
                 for relation in public_spec(model)["relations"]]
    if not any(len(relation["entities"]) == 2 and len(set(relation["entities"])) == 2 for relation in relations):
        raise HTTPException(422, "请先添加一条连接两个不同实体的二元联系")
    if not generate_slot.acquire(blocking=False):
        raise HTTPException(503, "模型正在处理另一项任务，请稍后重试")
    try:
        apply_active_to_environ()
        return propose_cardinality(body.text, relations)
    except LLMConfigurationError:
        raise HTTPException(503, "未配置可用的大模型，请检查 API 平台") from None
    except LLMTimeoutError:
        raise HTTPException(504, "理解修改要求超时，请稍后重试") from None
    except LLMError as error:
        logger.warning("Cardinality model request failed: %s", error)
        raise HTTPException(502, f"模型调用失败：{error}") from None
    except (SpecError, ValidationError) as error:
        logger.warning("Cardinality suggestion unavailable: %s", type(error).__name__)
        raise HTTPException(502, "模型已返回，但基数修改建议的格式无效") from None
    finally:
        generate_slot.release()


@app.post("/api/generate", dependencies=[Depends(require_render_account)])
def generate(request: GenerateRequest):
    from er_generator import LLMConfigurationError, LLMError, LLMTimeoutError, spec_from_text
    from llm_providers import apply_active_to_environ

    apply_active_to_environ()
    if not generate_slot.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="正在生成另一份规格，请稍后重试")
    try:
        model, _ = spec_from_text(request.text, retries=1, timeout=MODEL_REQUEST_TIMEOUT,
                                  total_timeout=MODEL_GENERATION_BUDGET,
                                  validate=validate_generated_spec, retry_disconnect=True,
                                  validate_final=validate_generated_connectivity,
                                  entity_limit=WEB_MAX_ENTITIES, relation_limit=WEB_MAX_RELATIONS,
                                  generation_rules=WEB_GENERATION_RULES, on_usage=record_usage)
    except LLMConfigurationError:
        raise HTTPException(status_code=503, detail="服务端尚未配置可用的大模型，请检查模型和 API Key") from None
    except LLMTimeoutError as error:
        logger.warning("Model generation timed out: %s", error)
        raise HTTPException(status_code=504, detail=str(error)) from None
    except LLMError as error:
        logger.warning("Model generation failed: %s", error)
        raise HTTPException(status_code=502, detail=str(error)) from None
    finally:
        generate_slot.release()
    return {"spec": public_spec(model)}


@app.post("/api/generate-usecase", dependencies=[Depends(require_render_account)])
def generate_usecase(request: GenerateRequest):
    from er_generator import LLMConfigurationError, LLMError, LLMTimeoutError, SpecError, SpecSizeError
    from llm_providers import apply_active_to_environ
    from usecase_generator import USECASE_WEB_RULES, usecase_from_text

    apply_active_to_environ()
    if not generate_slot.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="正在生成另一份规格，请稍后重试")
    try:
        _, public = usecase_from_text(
            request.text,
            timeout=MODEL_REQUEST_TIMEOUT,
            total_timeout=MODEL_GENERATION_BUDGET,
            on_usage=record_usage,
            generation_rules=USECASE_WEB_RULES,
        )
        if len(json.dumps({"spec": public}, ensure_ascii=False).encode("utf-8")) > RENDER_REQUEST_LIMIT:
            raise SpecSizeError("JSON 规格太大，请减少参与者或用例")
    except LLMConfigurationError:
        raise HTTPException(status_code=503, detail="服务端尚未配置可用的大模型，请检查模型和 API Key") from None
    except LLMTimeoutError as error:
        logger.warning("Use-case generation timed out: %s", error)
        raise HTTPException(status_code=504, detail=str(error)) from None
    except (SpecError, SpecSizeError) as error:
        logger.warning("Use-case generation rejected: %s", error)
        raise HTTPException(status_code=502, detail=f"模型规格未通过校验：{error}") from None
    except LLMError as error:
        logger.warning("Use-case generation failed: %s", error)
        raise HTTPException(status_code=502, detail=str(error)) from None
    finally:
        generate_slot.release()
    return {"spec": public}


@app.post("/api/render")
def render(spec: dict, username: Annotated[str, Depends(require_render_account)],
           format: Literal["png", "svg"] = "png",
           aspect: Literal["auto", "16:9", "4:3", "1:1", "9:16"] = "auto"):
    request = render_request_body(spec, format, aspect)
    if len(request) > RENDER_REQUEST_LIMIT:
        raise HTTPException(status_code=413, detail="JSON 规格太大")
    if not render_slot.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="正在为另一份规格出图，请稍后重试")
    try:
        try:
            result = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", str(worker_script)],
                input=request, capture_output=True, timeout=RENDER_WORKER_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="排版超时，请减少实体或联系后重试") from None
        if result.returncode:
            logger.error("Render worker failed: %s", result.stderr[-2000:].decode("utf-8", errors="replace"))
            raise HTTPException(status_code=500, detail="出图失败，请检查服务端的中文字体和运行日志")
        payload = json.loads(result.stdout)
        if "error" in payload:
            logger.warning("Render rejected (%s, %s layout): %s", format,
                           "manual" if "positions" in spec else "automatic", payload["error"])
            raise HTTPException(status_code=422, detail=payload["error"])
        if not payload.get("overview", {}).get("url") or not payload.get("entities"):
            logger.error("Render worker did not produce a complete diagram set")
            raise HTTPException(status_code=500, detail="出图结果不完整，请重新排版")
        return payload
    finally:
        render_slot.release()


@app.post("/api/render-usecase")
def render_usecase(spec: dict, username: Annotated[str, Depends(require_render_account)],
                   format: Literal["png", "svg"] = "png",
                   aspect: Literal["auto", "16:9", "4:3", "1:1", "9:16"] = "auto"):
    request = render_request_body(spec, format, aspect, kind="usecase")
    if len(request) > RENDER_REQUEST_LIMIT:
        raise HTTPException(status_code=413, detail="JSON 规格太大")
    if not render_slot.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="正在为另一份规格出图，请稍后重试")
    try:
        try:
            result = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", str(worker_script)],
                input=request, capture_output=True, timeout=RENDER_WORKER_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="用例图排版超时，请减少参与者或用例后重试") from None
        if result.returncode:
            failure_id = uuid4().hex[:12]
            logger.error("Use-case render worker failed: id=%s exit_code=%s format=%s aspect=%s\n%s",
                         failure_id, result.returncode, format, aspect,
                         result.stderr[-6000:].decode("utf-8", errors="replace"))
            raise HTTPException(status_code=500, detail=f"用例图渲染进程异常（诊断编号 {failure_id}）")
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ValueError("render worker returned a non-object payload")
        except (ValueError, UnicodeError) as error:
            failure_id = uuid4().hex[:12]
            logger.error("Use-case render worker failed: id=%s invalid response: %s", failure_id, error)
            raise HTTPException(status_code=500, detail=f"用例图渲染返回异常（诊断编号 {failure_id}）") from None
        if "error" in payload:
            logger.warning("Use-case render rejected (%s): %s", format, payload["error"])
            raise HTTPException(status_code=422, detail=payload["error"])
        if not payload.get("overview", {}).get("url"):
            logger.error("Use-case render worker did not produce overview")
            raise HTTPException(status_code=500, detail="用例图出图结果不完整，请重新排版")
        return payload
    finally:
        render_slot.release()


def render_request_body(spec, image_format, aspect="auto", kind="er"):
    return json.dumps({"kind": kind, "spec": spec, "format": image_format, "aspect": aspect},
                      ensure_ascii=False).encode("utf-8", "backslashreplace")


def validate_web_spec(model):
    from er_generator import SpecError, SpecSizeError

    entities, relations = model["ents"], model["rels"]
    if len(entities) > WEB_MAX_ENTITIES or len(relations) > WEB_MAX_RELATIONS:
        raise SpecSizeError(f"一次最多绘制 {WEB_MAX_ENTITIES} 个实体和 {WEB_MAX_RELATIONS} 条联系"
                            f"（实际生成 {len(entities)} 个实体和 {len(relations)} 条联系）")
    named_attributes = [(entity["name"], [name for name, _ in entity["attrs"]]) for entity in entities]
    named_attributes.extend((relation["name"], relation["attrs"]) for relation in relations)
    for name, attrs in named_attributes:
        if len(attrs) > 12:
            raise SpecError(f"「{name}」有 {len(attrs)} 个属性，最多可有 12 个（含主键）")
        for label in [name, *attrs]:
            if len(label) > 24 or not label.isprintable():
                raise SpecError("实体、联系及属性名称须为 1–24 个可显示字符")
    for relation in relations:
        if any(card not in {"1", "m", "n", "p"} for _, card in relation["ends"]):
            raise SpecError(f"联系“{relation['name']}”的基数须为 1、m、n 或 p")


def public_spec(model):
    names = [entity["name"] for entity in model["ents"]]
    return {
        "title": model["title"],
        "entities": [
            {"name": entity["name"], "attrs": [{"name": name, "pk": pk} for name, pk in entity["attrs"]]}
            for entity in model["ents"]
        ],
        "relations": [
            {"name": relation["name"], "entities": [names[index] for index, _ in relation["ends"]],
             "card": [card for _, card in relation["ends"]], "attrs": relation["attrs"]}
            for relation in model["rels"]
        ],
    }


def validate_generated_spec(model):
    from er_generator import SpecError, SpecSizeError

    validate_web_spec(model)
    if any(name.startswith("*") for entity in model["ents"] for name, _ in entity["attrs"]):
        raise SpecError("属性名称不能以 * 开头，请用 pk 字段或字符串前缀标记主键")
    if len(render_request_body(public_spec(model), "png")) > RENDER_REQUEST_LIMIT:
        raise SpecSizeError("JSON 规格太大，请减少实体、联系或属性")


def validate_generated_connectivity(model):
    from er_generator import SpecConnectivityError, isolated_entity_names

    if len(model["ents"]) > 1:
        isolated = isolated_entity_names(model)
        if isolated:
            raise SpecConnectivityError("以下实体未连接其他实体：「" + "」、「".join(isolated) + "」")


def read_positions(spec, model):
    from er_generator import SpecError

    if "positions" not in spec:
        return None
    positions = spec["positions"]
    names = [entity["name"] for entity in model["ents"]]
    if not isinstance(positions, dict) or positions.keys() != set(names):
        raise SpecError("布局坐标必须与当前实体一一对应")
    ordered = []
    for name in names:
        point = positions[name]
        if (not isinstance(point, list) or len(point) != 2
                or any(type(value) not in (int, float) or not -48 <= value <= 48 for value in point)):
            raise SpecError(f"实体“{name}”的布局坐标无效")
        ordered.append(tuple(point))
    return ordered


def render_in_worker(request):
    from er_generator import SpecError, matplotlib, normalize_spec, render_spec

    image_format = request["format"]
    mime_type = {"png": "image/png", "svg": "image/svg+xml"}[image_format]
    try:
        spec = request["spec"]
        model = normalize_spec(spec)
        validate_web_spec(model)
        positions = read_positions(spec, model)
        relation_positions = {}
        if "relationPositions" in spec:
            points = spec["relationPositions"]
            if positions is None or not isinstance(points, list) or len(points) != len(model["rels"]):
                raise SpecError("联系坐标须与规格中的联系顺序一一对应，并同时提供实体坐标")
            for index, point in enumerate(points):
                if point is None:
                    continue
                if (not isinstance(point, list) or len(point) != 2
                        or any(type(value) not in (int, float) or not -48 <= value <= 48 for value in point)):
                    raise SpecError(f"第 {index + 1} 条联系的布局坐标无效")
                relation_positions[index] = tuple(point)
        aspect = request.get("aspect", "auto")
        canvas_ratio = None if aspect == "auto" else tuple(map(int, aspect.split(":")))
        large = (len(model["ents"]) > 15 or len(model["rels"]) > 30
                 or sum(len(r["attrs"]) for r in model["rels"]) > 160)
        with matplotlib.rc_context({"text.parse_math": False, "text.usetex": False, "svg.fonttype": "path"}):
            diagrams = render_spec(model, image_format=image_format, effort=0.5,
                                   time_limit=10, parallel=False, positions=positions,
                                   layout_budget=32.0 if large else 20.0, canvas_ratio=canvas_ratio,
                                   relation_positions=relation_positions)
    except SpecError as error:
        return {"error": str(error)}
    entities = []
    for diagram in diagrams:
        data = base64.b64encode(diagram["content"]).decode("ascii")
        image = {"filename": diagram["filename"], "url": f"data:{mime_type};base64,{data}"}
        if diagram["entity"] is None:
            overview = image
            layout = diagram["layout"]
        else:
            entities.append(dict(image, entity=diagram["entity"], frame=diagram["layout"]))
    return {"overview": overview, "entities": entities, "layout": layout}


def render_usecase_in_worker(request):
    from er_generator import SpecError, SpecSizeError, matplotlib
    from usecase_generator import (
        normalize_usecase_spec, read_dependency_label_positions, read_usecase_positions, render_usecase_spec,
    )

    image_format = request["format"]
    mime_type = {"png": "image/png", "svg": "image/svg+xml"}[image_format]
    try:
        spec = request["spec"]
        model = normalize_usecase_spec(spec)
        positions = read_usecase_positions(spec, model)
        label_positions = read_dependency_label_positions(spec, model)
        aspect = request.get("aspect", "auto")
        canvas_ratio = None if aspect == "auto" else tuple(map(int, aspect.split(":")))
        with matplotlib.rc_context({"text.parse_math": False, "text.usetex": False, "svg.fonttype": "path"}):
            diagrams = render_usecase_spec(
                model, image_format=image_format, canvas_ratio=canvas_ratio, positions=positions,
                label_positions=label_positions,
            )
    except (SpecError, SpecSizeError) as error:
        return {"error": str(error)}
    overview = None
    layout = None
    for diagram in diagrams:
        data = base64.b64encode(diagram["content"]).decode("ascii")
        overview = {"filename": diagram["filename"], "url": f"data:{mime_type};base64,{data}"}
        layout = diagram.get("layout")
    if overview is None:
        return {"error": "用例图没有生成任何图片"}
    return {"overview": overview, "entities": [], "layout": layout}


if __name__ == "__main__":
    with redirect_stdout(sys.stderr):
        inbound = json.load(sys.stdin)
        if inbound.get("kind") == "usecase":
            payload = render_usecase_in_worker(inbound)
        else:
            payload = render_in_worker(inbound)
    json.dump(payload, sys.stdout)
