"""Interpret one E-R cardinality edit without mutating the draft."""
import json
import logging
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from er_generator import extract_json, llm_chat, llm_settings
from token_usage import record_usage

logger = logging.getLogger(__name__)


class CardinalityIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Annotated[str, StringConstraints(min_length=1, max_length=24)]
    target: Annotated[str, StringConstraints(min_length=1, max_length=24)]
    card: Literal["1", "m", "n", "p"]


PROMPT = """你只负责识别 E-R 草稿的一项基数修改。下面的 JSON 数据含用户的话和现有联系。只输出 JSON，不修改草稿。
把口语和简称对应到现有实体名，例如「限制每个学生最多选一门课」在学生与课程之间表示课程端改为 1。
source 是从哪个实体出发描述数量，target 是被计数的实体，也就是要改基数的那端。必须使用现有实体的准确名称。
允许 1、m、n、p。用户说多而未指定符号时用 n。只处理两个不同实体之间已有的二元联系，一次只修改一端。
同一对实体有多条联系时仍返回这对实体，由用户选择具体联系。
请求若不明确、有多项改动、涉及条件/范围无法用基数表达，或要求改名、添加或删除等，返回 {}。
其余只返回形如 {"source":"学生","target":"课程","card":"1"} 的对象。"""


def resolve_cardinality_reply(reply, relations):
    raw = extract_json(reply)
    if raw == {}:
        return {"choices": []}
    intent = CardinalityIntent.model_validate(raw)
    pair = {intent.source, intent.target}
    if len(pair) != 2:
        return {"choices": []}
    choices = [
        {"relationIndex": index, "endpointIndex": relation["entities"].index(intent.target), "card": intent.card}
        for index, relation in enumerate(relations)
        if len(relation["entities"]) == 2 and set(relation["entities"]) == pair
    ]
    return {"choices": choices}


def propose_cardinality(text, relations):
    data = json.dumps({"request": text, "relations": relations}, ensure_ascii=False, separators=(",", ":"))
    provider, model, key, base_url = llm_settings()
    logger.info("Requesting cardinality interpretation (%s / %s)", provider, model)
    reply = llm_chat([{"role": "user", "content": data}], provider, model, key, base_url,
                     timeout=25, stream=False, system_prompt=PROMPT, on_usage=record_usage)
    return {**resolve_cardinality_reply(reply, relations), "model": model}
