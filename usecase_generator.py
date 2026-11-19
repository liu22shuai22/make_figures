"""UML 用例图：自然语言 → 规格 → 出图。

复用 er_generator 的字体、LLM 调用与异常类型；本文件只负责用例图模型与绘制。
"""
from __future__ import annotations

from io import BytesIO
from itertools import chain, combinations, islice
import json
import math
import os
import re
import time

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.patches import Circle, Ellipse, Polygon, Rectangle

import er_generator as er
from er_generator import (
    LLMConnectionClosedError,
    LLMStreamInterruptedError,
    LLMTimeoutError,
    LLMUpstreamUnavailableError,
    SILICONFLOW_BASE_URL,
    SpecError,
    SpecSizeError,
    _canvas_dimensions,
    extract_json,
    init_font,
    llm_chat,
    llm_settings,
    safe,
)

MAX_ACTORS = 12
MAX_USE_CASES = 24
MAX_LINKS = 48
MAX_DEPS = 48
MAX_LABEL = 24
USECASE_RESUME_LIMIT = 3
USECASE_LINE_WIDTH = er.LINE_W
USECASE_TEXT_SIZE = er.FONT_SIZE

USECASE_SYSTEM_PROMPT = """你是软件需求分析专家。用户会用自然语言描述一个系统，请据此设计 UML 用例图规格。
【只输出一个 JSON 对象】，不要解释，不要 Markdown 代码块。格式：
{
  "title": "系统名称",
  "actors": [ {"name": "参与者名", "kind": "primary"} ],
  "useCases": ["用例名"],
  "links": [["参与者名", "用例名"]],
  "dependencies": [["include", "基用例", "被包含用例"]],
  "reviewNotes": ["仅列出需要用户确认的业务假设，可为空"]
}
设计规则：
1. actors.kind 只能是 primary（主要，主动发起）或 secondary（次要，被系统调用/协助）。
2. 参与者用角色名（读者、管理员），不用真实人名；通常 1–6 个。
3. 用例用动宾短语（借书、查询馆藏），简短；通常 2–12 个。参与者与用例名称不要重名。
4. links 表示通信关联：哪个参与者使用哪个用例；每个对外用例至少连一个参与者。
5. dependencies 可选，仅用例之间：
   - include：基用例 from 包含 to（虚线箭头 + «include»）
   - extend：扩展用例 from 扩展 to（虚线箭头 + «extend»）
   - generalize：子用例 from 泛化到父用例 to（空心三角箭头）
   每条依赖的两个端点都必须在 useCases 中完整列出，只被包含的用例也要列出。
6. include 只表示基础用例每次执行都包含的行为。已登录之类的前置条件不画成 include，除非需求明确每次都执行验证。
   extend 只表示基础用例执行到扩展点时按条件插入的行为。时间先后、状态变化和单独发起的后续目标不构成 extend。
   例如：读者续借是独立目标。借阅完成是续借的前置条件，读者应直接关联「续借」。
   只有需求明确有申请和审核两个独立目标时，才拆成两个用例。管理员只关联其实际参与的用例。
   依赖和角色职责不明确时，省略推测的关联，在 reviewNotes 中简短说明待确认的问题，最多 3 条。
7. 系统边界沿用 title。dependencies、reviewNotes 无内容时可省略。
8. 名称一律中文，每个名称不超过 24 个字。
示例需求：读者可查询馆藏，到柜台借书和还书。管理员协助办理借还，每次都核对身份。
示例输出：
{"title":"图书借阅系统","actors":[{"name":"读者","kind":"primary"},{"name":"管理员","kind":"secondary"}],"useCases":["借书","还书","查询馆藏","验证身份"],"links":[["读者","借书"],["读者","还书"],["读者","查询馆藏"],["管理员","借书"],["管理员","还书"]],"dependencies":[["include","借书","验证身份"],["include","还书","验证身份"]]}"""

USECASE_WEB_RULES = f"""网页绘图硬性约束：
- 参与者最多 {MAX_ACTORS} 个，用例最多 {MAX_USE_CASES} 个，关联最多 {MAX_LINKS} 条，依赖最多 {MAX_DEPS} 条。
- 名称 1–{MAX_LABEL} 个可显示字符；参与者与用例名称全局唯一。
- 输出紧凑 JSON，省略缩进与换行。"""

_DEP_KINDS = {
    "include": "include",
    "包含": "include",
    "<<include>>": "include",
    "«include»": "include",
    "extend": "extend",
    "扩展": "extend",
    "<<extend>>": "extend",
    "«extend»": "extend",
    "generalize": "generalize",
    "generalisation": "generalize",
    "generalization": "generalize",
    "泛化": "generalize",
    "继承": "generalize",
}


def _text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and math.isfinite(value):
        return str(value).strip()
    return ""


def _label_ok(name: str) -> bool:
    return bool(name) and name.isprintable() and len(name) <= MAX_LABEL


def normalize_usecase_spec(raw, *, complete_dependency_cases=False):
    """把任意 JSON 转成内部模型：actors / use_cases / links / dependencies（下标引用）。"""
    if not isinstance(raw, dict):
        raise SpecError("用例图规格必须是 JSON 对象")

    actors_raw = raw.get("actors")
    use_cases_raw = raw.get("useCases", raw.get("use_cases"))
    if not isinstance(actors_raw, list) or not actors_raw:
        raise SpecError("用例图至少需要 1 个参与者（actors）")
    if not isinstance(use_cases_raw, list) or not use_cases_raw:
        raise SpecError("用例图至少需要 1 个用例（useCases）")

    actors = []
    actor_index = {}
    for item in actors_raw:
        if isinstance(item, (str, int, float)):
            name, kind = _text(item), "primary"
        elif isinstance(item, dict):
            name = _text(item.get("name"))
            kind_raw = _text(item.get("kind")).lower()
            kind = "secondary" if kind_raw in {"secondary", "次", "次要"} else "primary"
        else:
            continue
        if not name:
            continue
        if not _label_ok(name):
            raise SpecError(f"参与者名「{name}」须为 1–{MAX_LABEL} 个可显示字符")
        if name in actor_index:
            continue
        actor_index[name] = len(actors)
        actors.append({"name": name, "kind": kind})

    use_cases = []
    use_case_index = {}
    for item in use_cases_raw:
        if isinstance(item, (str, int, float)):
            name = _text(item)
        elif isinstance(item, dict):
            name = _text(item.get("name"))
        else:
            continue
        if not name:
            continue
        if not _label_ok(name):
            raise SpecError(f"用例名「{name}」须为 1–{MAX_LABEL} 个可显示字符")
        if name in actor_index:
            raise SpecError(f"用例名「{name}」与参与者重名")
        if name in use_case_index:
            continue
        use_case_index[name] = len(use_cases)
        use_cases.append({"name": name})

    if not actors:
        raise SpecError("actors 解析后为空")
    if not use_cases:
        raise SpecError("useCases 解析后为空")
    if len(actors) > MAX_ACTORS:
        raise SpecSizeError(f"参与者最多 {MAX_ACTORS} 个，当前 {len(actors)} 个")
    if len(use_cases) > MAX_USE_CASES:
        raise SpecSizeError(f"用例最多 {MAX_USE_CASES} 个，当前 {len(use_cases)} 个")

    links = []
    seen = set()
    links_raw = raw.get("links")
    if links_raw is None:
        links_raw = []
    if not isinstance(links_raw, list):
        raise SpecError("links 必须是数组")
    for item in links_raw:
        if not isinstance(item, dict):
            continue
        actor_name = _text(item.get("actor") or item.get("actorName"))
        use_case_name = _text(item.get("useCase") or item.get("usecase") or item.get("use_case"))
        if actor_name not in actor_index:
            raise SpecError(f"关联引用了不存在的参与者「{actor_name or '?'}」")
        if use_case_name not in use_case_index:
            raise SpecError(f"关联引用了不存在的用例「{use_case_name or '?'}」")
        key = (actor_index[actor_name], use_case_index[use_case_name])
        if key in seen:
            continue
        seen.add(key)
        links.append({"actor": key[0], "use_case": key[1]})

    if len(links) > MAX_LINKS:
        raise SpecSizeError(f"关联最多 {MAX_LINKS} 条，当前 {len(links)} 条")
    if not links:
        raise SpecError("至少需要 1 条参与者—用例关联（links）")

    dependencies = []
    dep_seen = set()
    deps_raw = raw.get("dependencies", raw.get("deps", raw.get("relations")))
    if deps_raw is None:
        deps_raw = []
    if not isinstance(deps_raw, list):
        raise SpecError("dependencies 必须是数组")
    declared_cases = set(use_case_index)
    for item in deps_raw:
        if not isinstance(item, dict):
            continue
        kind_raw = _text(item.get("kind") or item.get("type") or item.get("relation"))
        kind = _DEP_KINDS.get(kind_raw.lower()) or _DEP_KINDS.get(kind_raw)
        if kind is None:
            raise SpecError("依赖 kind 只能是 include / extend / generalize")
        from_name = _text(item.get("from") or item.get("source") or item.get("base"))
        to_name = _text(item.get("to") or item.get("target") or item.get("inclusion") or item.get("parent"))
        for endpoint in (from_name, to_name):
            if endpoint in actor_index:
                raise SpecError(f"依赖「{from_name} → {to_name}」包含参与者「{endpoint}」，请用参与者关联表达职责")
        if complete_dependency_cases:
            # 仅补充与已声明用例相连、且由模型明确命名的漏列用例。
            for existing, missing in ((from_name, to_name), (to_name, from_name)):
                if existing in declared_cases and missing not in use_case_index and _label_ok(missing):
                    if len(use_cases) == MAX_USE_CASES:
                        raise SpecSizeError(f"补齐依赖用例「{missing}」会超过 {MAX_USE_CASES} 个用例上限")
                    use_case_index[missing] = len(use_cases)
                    use_cases.append({"name": missing})
        if from_name not in use_case_index:
            raise SpecError(f"依赖引用了不存在的用例「{from_name or '?'}」")
        if to_name not in use_case_index:
            raise SpecError(f"依赖引用了不存在的用例「{to_name or '?'}」")
        if from_name == to_name:
            raise SpecError(f"依赖不能指向同一用例「{from_name}」")
        key = (kind, use_case_index[from_name], use_case_index[to_name])
        if key in dep_seen:
            continue
        dep_seen.add(key)
        dependencies.append({"kind": kind, "from": key[1], "to": key[2]})

    if len(dependencies) > MAX_DEPS:
        raise SpecSizeError(f"依赖最多 {MAX_DEPS} 条，当前 {len(dependencies)} 条")

    title = _text(raw.get("title"))
    system = _text(raw.get("system")) or title or "系统"
    if not _label_ok(system):
        raise SpecError(f"系统边界名须为 1–{MAX_LABEL} 个可显示字符")
    if title and not _label_ok(title):
        raise SpecError(f"课题标题须为 1–{MAX_LABEL} 个可显示字符")

    return {
        "title": title,
        "system": system,
        "actors": actors,
        "use_cases": use_cases,
        "links": links,
        "dependencies": dependencies,
    }


def public_usecase_spec(model):
    actors = model["actors"]
    use_cases = model["use_cases"]
    return {
        "kind": "usecase",
        "title": model["title"],
        "system": model["system"],
        "actors": [{"name": a["name"], "kind": a["kind"]} for a in actors],
        "useCases": [{"name": u["name"]} for u in use_cases],
        "links": [
            {"actor": actors[link["actor"]]["name"], "useCase": use_cases[link["use_case"]]["name"]}
            for link in model["links"]
        ],
        "dependencies": [
            {
                "kind": dep["kind"],
                "from": use_cases[dep["from"]]["name"],
                "to": use_cases[dep["to"]]["name"],
            }
            for dep in model["dependencies"]
        ],
    }


def validate_usecase_workflow(model):
    linked_actors = {link["actor"] for link in model["links"]}
    for index, actor in enumerate(model["actors"]):
        if index not in linked_actors:
            raise SpecError(f"参与者「{actor['name']}」没有关联用例")

    graph = nx.Graph()
    graph.add_nodes_from(range(len(model["use_cases"])))
    graph.add_edges_from((dep["from"], dep["to"]) for dep in model["dependencies"])
    linked_cases = {link["use_case"] for link in model["links"]}
    for component in nx.connected_components(graph):
        if not component & linked_cases:
            names = "、".join(model["use_cases"][index]["name"] for index in sorted(component))
            raise SpecError(f"用例「{names}」没有连接到任何参与者的业务流程")

    for kind in ("include", "generalize"):
        dependencies = nx.DiGraph((dep["from"], dep["to"]) for dep in model["dependencies"] if dep["kind"] == kind)
        if not nx.is_directed_acyclic_graph(dependencies):
            cycle = nx.find_cycle(dependencies)
            names = " → ".join(model["use_cases"][index]["name"] for index in [cycle[0][0], *(target for _, target in cycle)])
            raise SpecError(f"{kind} 依赖形成循环：{names}")


def _parse_generated_usecase(reply):
    raw = extract_json(reply)
    if not isinstance(raw, dict):
        raise SpecError("用例图规格必须是 JSON 对象")
    # 模型可用短数组减少输出，校验和客户端仍使用对象字段。
    for field, keys in (("links", ("actor", "useCase")), ("dependencies", ("kind", "from", "to"))):
        records = raw.get(field)
        if not isinstance(records, list):
            continue
        expanded = []
        for record in records:
            if isinstance(record, list):
                if len(record) != len(keys) or not all(isinstance(value, str) for value in record):
                    raise SpecError(f"{field} 每条记录须包含 {len(keys)} 个文本字段")
                record = dict(zip(keys, record))
            expanded.append(record)
        raw[field] = expanded
    model = normalize_usecase_spec(raw, complete_dependency_cases=True)
    validate_usecase_workflow(model)
    spec = public_usecase_spec(model)
    notes = raw.get("reviewNotes")
    if isinstance(notes, list):
        spec["reviewNotes"] = list(dict.fromkeys(
            note.strip()[:160] for note in notes[:3] if isinstance(note, str) and note.strip()
        ))
    return model, spec


_USECASE_ARRAY_FIELDS = ("actors", "useCases", "use_cases", "links", "dependencies", "reviewNotes")


def _usecase_checkpoint(text):
    for prefix, closing in er._json_array_checkpoints(text, compact=True):
        try:
            snapshot = json.loads(prefix + closing)
        except (ValueError, RecursionError):
            continue
        if isinstance(snapshot.get("actors"), list) and snapshot["actors"]:
            return prefix, snapshot
    return None


def _resume_usecase(partial, request_model, messages, prompt, deadline):
    checkpoint = _usecase_checkpoint(partial)
    if checkpoint is None:
        return None
    prefix, snapshot = checkpoint
    resume_prompt = (prompt + "\n本轮只续写 JSON。只输出给定前缀之后缺少的字符，"
                     "补全原需求中的其余记录并闭合 JSON。不要重复已完成记录、重发前缀或输出 Markdown。")

    def preserves(document):
        return isinstance(document, dict) and er._preserves_spec_checkpoint(
            document, snapshot, array_keys=_USECASE_ARRAY_FIELDS,
        )

    for attempt in range(1, USECASE_RESUME_LIMIT + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 7:
            break
        print(f"用例规格断流，已保留 {len(prefix)} 个字符，正在同一入口续写（第 {attempt} 次）……", flush=True)
        context = json.dumps({"需求对话": messages, "已完成的 JSON 前缀": prefix}, ensure_ascii=False)
        try:
            suffix = request_model([{"role": "user", "content": context}], resume_prompt,
                                   min(18, remaining - 6), stream=attempt % 2 == 0)
        except LLMStreamInterruptedError as error:
            suffix = error.partial
        except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError) as error:
            print(f"用例规格续写请求未完成（{error}）。", flush=True)
            continue
        suffix = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", suffix, flags=re.I).strip()
        candidates = (prefix + suffix, suffix)
        advanced = None
        for candidate in candidates:
            try:
                complete = json.loads(candidate)
            except (ValueError, RecursionError):
                complete = None
            if preserves(complete):
                try:
                    return _parse_generated_usecase(candidate)
                except SpecError:
                    pass
            next_checkpoint = _usecase_checkpoint(candidate)
            if next_checkpoint and preserves(next_checkpoint[1]) and any(
                isinstance(next_checkpoint[1].get(key), list)
                and len(next_checkpoint[1][key]) > len(snapshot.get(key) or ())
                for key in _USECASE_ARRAY_FIELDS
            ):
                if advanced is None or len(next_checkpoint[0]) > len(advanced[0]):
                    advanced = next_checkpoint
        if advanced is not None:
            prefix, snapshot = advanced
    return None


def usecase_from_text(text, args=None, *, timeout=90, total_timeout=120, on_usage=None, generation_rules=""):
    provider, model_name, key, base_url = llm_settings(args)
    prompt = USECASE_SYSTEM_PROMPT
    if generation_rules:
        prompt = prompt + "\n\n" + generation_rules
    request = {"role": "user", "content": "请为下面的系统生成 UML 用例图规格：\n\n" + text}
    messages = [request]
    print("正在请求大模型生成用例图规格（%s / %s）……" % (provider, model_name), flush=True)
    deadline = time.monotonic() + total_timeout
    siliconflow = provider == "openai" and (base_url or "").rstrip("/") == SILICONFLOW_BASE_URL
    modes = (False, True, False) if siliconflow else (True, True)

    def request_model(request_messages, system_prompt, request_timeout, *, stream):
        return llm_chat(request_messages, provider, model_name, key, base_url, timeout=min(timeout, request_timeout),
                        system_prompt=system_prompt, stream=stream, on_usage=on_usage)

    for attempt, stream in enumerate(modes, start=1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LLMTimeoutError("已达到用例图生成等待上限，请稍后重试")
        can_retry = attempt < len(modes)
        # 给同一入口的下一次尝试保留时间，避免首次超时耗掉整个预算。
        request_timeout = min(timeout, remaining / 2 if siliconflow and can_retry else remaining)
        try:
            reply = request_model(messages, prompt, request_timeout, stream=stream)
        except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError) as error:
            if isinstance(error, LLMStreamInterruptedError) and error.partial:
                try:
                    return _parse_generated_usecase(error.partial)
                except SpecError:
                    pass
                if siliconflow:
                    recovered = _resume_usecase(error.partial, request_model, messages, prompt, deadline)
                    if recovered is not None:
                        return recovered
            if not can_retry or deadline - time.monotonic() <= 1:
                raise
            response_mode = "流式" if modes[attempt] else "一次返回"
            print(f"用例规格请求未完成（{error}），正在同一入口改用{response_mode}响应重试……", flush=True)
            continue

        try:
            return _parse_generated_usecase(reply)
        except SpecError as error:
            if not can_retry or deadline - time.monotonic() <= 1:
                raise
            correction = json.dumps({"error": str(error)[:600], "previousOutput": reply[:12_000]}, ensure_ascii=False)
            messages = [request, {"role": "user", "content": "上一次规格未通过校验。根据原需求修正以下数据，保留已正确的业务关系并输出完整 JSON。\n" + correction}]


def _actor_size(name):
    head_r = 0.12
    body_h = 0.42
    label_w = max(er.tw(name) + 0.2, 0.75)
    return label_w, head_r * 2 + body_h + 0.34


def _use_case_size(name):
    w = max(er.tw(name) + 0.7, 1.35)
    h = 0.62
    return w, h


def _ellipse_edge(cx, cy, w, h, toward_x, toward_y):
    dx = toward_x - cx
    dy = toward_y - cy
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return cx, cy
    rx, ry = w / 2, h / 2
    scale = 1.0 / math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
    return cx + dx * scale, cy + dy * scale


def read_usecase_positions(spec, model):
    """positions：参与者名与用例名 → [x, y]，与自动布局返回的 entities 一一对应。"""
    if not isinstance(spec, dict) or "positions" not in spec:
        return None
    positions = spec["positions"]
    names = [a["name"] for a in model["actors"]] + [u["name"] for u in model["use_cases"]]
    if not isinstance(positions, dict) or set(positions.keys()) != set(names):
        raise SpecError("布局坐标必须与当前参与者、用例一一对应")
    ordered = {}
    for name in names:
        point = positions[name]
        if (not isinstance(point, list) or len(point) != 2
                or any(type(value) not in (int, float) or not -48 <= value <= 48 for value in point)):
            raise SpecError(f"「{name}」的布局坐标无效")
        ordered[name] = (float(point[0]), float(point[1]))
    return ordered


def read_dependency_label_positions(spec, model):
    if "dependencyLabelPositions" not in spec:
        return {}
    points = spec["dependencyLabelPositions"]
    deps = model["dependencies"]
    if not isinstance(points, list) or len(points) != len(deps):
        raise SpecError("标签坐标必须与依赖顺序一一对应")
    positions = {}
    for index, point in enumerate(points):
        if point is None:
            continue
        if (deps[index]["kind"] not in {"include", "extend"} or not isinstance(point, list) or len(point) != 2
                or any(type(value) not in (int, float) or not -48 <= value <= 48 for value in point)):
            raise SpecError(f"第 {index + 1} 条依赖的标签坐标无效")
        positions[index] = tuple(point)
    return positions


def _usecase_candidate(model, positions=None, *, order=None, columns=None, group_actors=False,
                       right_actors=(), actor_gap=1.05, shared_row_offset=0.5, route=True):
    """标准用例图布局：左主参与者、右次参与者，系统框内用例自上而下排列。

    坐标系与 E-R 一致：数据 y 增大朝图像下方（出图时 ylim 倒置），便于拖拽叠加层共用。
    仅作为 include/extend 目标、且无参与者关联的用例，放到框内右侧列，避免依赖线竖向叠在椭圆上。
    """
    actors = model["actors"]
    use_cases = model["use_cases"]
    primary = [i for i, a in enumerate(actors) if a["kind"] != "secondary"]
    secondary = [i for i, a in enumerate(actors) if a["kind"] == "secondary"]
    if not primary and secondary:
        primary, secondary = secondary, []

    uc_sizes = [_use_case_size(u["name"]) for u in use_cases]
    linked = {link["use_case"] for link in model["links"]}
    # 无参与者关联的用例放在独立列。
    indices = range(len(use_cases)) if order is None else order
    main_indices = [i for i in indices if i in linked]
    side_indices = [i for i in range(len(use_cases)) if i not in linked]
    if not main_indices:
        main_indices, side_indices = list(range(len(use_cases))), []

    spread_actors = bool(right_actors)
    if spread_actors:
        secondary = list(right_actors)
        primary = [i for i in range(len(actors)) if i not in right_actors]
        right_cases = {link["use_case"] for link in model["links"] if link["actor"] in right_actors}
        left_cases = {link["use_case"] for link in model["links"] if link["actor"] not in right_actors}
        lanes = [
            [i for i in main_indices if i not in right_cases],
            [i for i in main_indices if i in right_cases and i in left_cases],
            [i for i in main_indices if i not in left_cases],
        ]

    title_h = 0.45
    pad = 0.45
    cell_h = max((h for _, h in uc_sizes), default=0.62) + (0.55 if model["dependencies"] else 0.45)
    main_cols = columns or (1 if len(main_indices) <= 4 else 2)
    main_w = max((uc_sizes[i][0] for i in main_indices), default=1.35) + 0.55
    side_w = max((uc_sizes[i][0] for i in side_indices), default=1.35) + 0.5 if side_indices else 0.0
    gap_cols = 0.85 if side_indices else 0.0
    cols_w = main_cols * main_w + (gap_cols + side_w if side_indices else 0.0)
    main_rows = int(math.ceil(len(main_indices) / main_cols))
    if spread_actors:
        main_rows = max(map(len, lanes))
        main_w = max(main_w, side_w)
        cols_w = 3 * main_w
    title_width = er.tw(model["system"]) + 0.8
    system_w = max(cols_w + pad * 2, title_width, 3.2)
    system_h = title_h + max(main_rows, 1) * cell_h + pad
    system_x0, system_y0 = 0.0, 0.0

    uc_boxes = [(0.0, 0.0, w, h) for w, h in uc_sizes]
    if not positions:
        primary_links = {link["use_case"] for link in model["links"] if link["actor"] in primary}
        secondary_links = {link["use_case"] for link in model["links"] if link["actor"] in secondary}
        side_dependencies = {dep["from"] for dep in model["dependencies"] if dep["to"] in side_indices}
        shared_with_dependencies = primary_links & secondary_links & side_dependencies
        main_left = system_x0 + pad
        slots = [(index, *divmod(row, main_cols)) for row, index in enumerate(main_indices)]
        if spread_actors:
            # The middle lane points through the gaps in the outer lanes.
            middle_start = max(0, (main_rows - len(lanes[1])) // 2 + shared_row_offset)
            slots = [(index, row + (middle_start if col == 1 else (main_rows - len(lane)) // 2), col)
                     for col, lane in enumerate(lanes) for row, index in enumerate(lane)]
            if lanes[1]:
                system_h += max(0, middle_start + len(lanes[1]) - main_rows) * cell_h
        for index, row, col in slots:
            w, h = uc_sizes[index]
            if not spread_actors and main_cols > 1 and row == main_rows - 1:
                last_count = len(main_indices) - row * main_cols
                offset = (main_cols - last_count) * main_w / 2
            else:
                offset = 0.0
            cx = main_left + offset + col * main_w + main_w / 2
            if not spread_actors and main_cols == 1 and index in shared_with_dependencies:
                # 借用两列之间的空白，缩短次参与者的横向连线。
                cx += min(0.6, gap_cols * 0.7)
            cy = system_y0 + title_h + pad / 2 + row * cell_h + cell_h / 2
            uc_boxes[index] = (cx, cy, w, h)

        if side_indices:
            # 右侧列：按依赖对端的平均 y 对齐，并做简单防重叠
            side_x = main_left + main_cols * main_w + gap_cols + side_w / 2
            if spread_actors:
                side_x = main_left + 1.5 * main_w
            neighbors = {i: [] for i in side_indices}
            for dep in model["dependencies"]:
                if dep["to"] in neighbors:
                    neighbors[dep["to"]].append(dep["from"])
                if dep["from"] in neighbors:
                    neighbors[dep["from"]].append(dep["to"])
            desired = []
            for index in side_indices:
                w, h = uc_sizes[index]
                refs = [uc_boxes[j][1] for j in neighbors[index] if j in linked]
                cy = sum(refs) / len(refs) if refs else (system_y0 + system_h / 2)
                desired.append([index, cy, w, h])
            desired.sort(key=lambda item: item[1])
            min_gap = cell_h * 0.85
            if spread_actors:
                reserved = [uc_boxes[j][1] for j in lanes[1]]
                for item in desired:
                    for cy in sorted(reserved):
                        if abs(item[1] - cy) < min_gap:
                            item[1] = cy + min_gap
                    reserved.append(item[1])
            else:
                for i in range(1, len(desired)):
                    desired[i][1] = max(desired[i][1], desired[i - 1][1] + min_gap)
            # 先保证顶端在标题下；侧列过长时扩展系统框。
            if desired:
                top = min(cy - h / 2 for _, cy, _, h in desired)
                bottom = max(cy + h / 2 for _, cy, _, h in desired)
                low = system_y0 + title_h + 0.2
                high = system_y0 + system_h - 0.2
                shift = 0.0 if spread_actors else max(low - top, min(0.0, high - bottom))
                for index, cy, w, h in desired:
                    uc_boxes[index] = (side_x, cy + shift, w, h)
                system_h = max(system_h, bottom + shift - system_y0 + 0.25)
    else:
        for index, (w, h) in enumerate(uc_sizes):
            name = use_cases[index]["name"]
            cx, cy = positions[name]
            uc_boxes[index] = (cx, cy, w, h)

    if positions:
        # 按用例实际位置重算系统边界
        xs = [cx - w / 2 for cx, cy, w, h in uc_boxes] + [cx + w / 2 for cx, cy, w, h in uc_boxes]
        ys = [cy - h / 2 for cx, cy, w, h in uc_boxes] + [cy + h / 2 for cx, cy, w, h in uc_boxes]
        system_x0 = min(xs) - pad
        system_y0 = min(ys) - title_h - pad / 2
        system_w = max(xs) - min(xs) + pad * 2
        system_h = max(ys) - min(ys) + title_h + pad
        system_w = max(system_w, title_width)

    def place_actors(indices, side):
        boxes = []
        if not indices:
            return boxes
        if group_actors and not positions:
            rows = {i: [] for i in indices}
            for link in model["links"]:
                if link["actor"] in rows:
                    rows[link["actor"]].append(uc_boxes[link["use_case"]][1])
            centers = {i: sum(rows[i]) / len(rows[i]) if rows[i] else system_h / 2 for i in indices}
            indices = sorted(indices, key=lambda i: (centers[i], i))
        sizes = [_actor_size(actors[i]["name"]) for i in indices]
        if positions:
            for i, (w, h) in zip(indices, sizes):
                name = actors[i]["name"]
                if name in positions:
                    cx, cy = positions[name]
                else:
                    gap = 1.05
                    cx = (system_x0 - gap - w / 2) if side == "left" else (system_x0 + system_w + gap + w / 2)
                    cy = system_y0 + system_h / 2
                boxes.append((i, cx, cy, w, h))
            return boxes
        total_h = sum(h for _, h in sizes) + 0.35 * max(0, len(indices) - 1)
        y = system_y0 + system_h / 2 - total_h / 2
        for i, (w, h) in zip(indices, sizes):
            if side == "left":
                cx = system_x0 - actor_gap - w / 2
            else:
                cx = system_x0 + system_w + actor_gap + w / 2
            cy = y + h / 2
            if group_actors and (main_cols == 1 or spread_actors):
                cy = centers[i]
                if boxes:
                    _, _, previous_y, _, previous_h = boxes[-1]
                    cy = max(cy, previous_y + (previous_h + h) / 2 + 0.35)
            boxes.append((i, cx, cy, w, h))
            y += h + 0.35
        return boxes

    actor_boxes = place_actors(primary, "left") + place_actors(secondary, "right")

    def direct_paths():
        paths = []
        endpoints = []
        shapes = [(*box, "a", index) for index, box in enumerate(uc_boxes)]
        for link in model["links"]:
            actor_box = next(box for box in actor_boxes if box[0] == link["actor"])
            ux, uy, uw, uh = uc_boxes[link["use_case"]]
            ax_, ay = actor_box[1:3]
            start_x = ax_ + (0.22 if ax_ < system_x0 else -0.22)
            start_y = ay - 0.02
            end_x, end_y = _ellipse_edge(ux, uy, uw, uh, start_x, start_y)
            paths.append([(start_x, start_y), (end_x, end_y)])
            endpoints.append(((start_x, start_y), shapes[link["use_case"]]))

        dep_paths = []
        for dep in model["dependencies"]:
            fx, fy, fw, fh = uc_boxes[dep["from"]]
            tx, ty, tw_, th = uc_boxes[dep["to"]]
            start = _ellipse_edge(fx, fy, fw, fh, tx, ty)
            end = _ellipse_edge(tx, ty, tw_, th, fx, fy)
            dep_paths.append({"kind": dep["kind"], "points": (start, end)})
        return paths, endpoints, shapes, dep_paths

    paths, endpoints, shapes, dep_paths = direct_paths()
    if route:
        paths = _route_actor_links(paths, endpoints, shapes, dep_paths)
    if (route and not positions and len(side_indices) == 1 and len(shared_with_dependencies) >= 2
            and any(len(path) > 2 for path in paths)):
        index = side_indices[0]
        x, y, w, h = uc_boxes[index]
        for dx, dy in ((-0.50, 0.34), (-0.55, 0.35), (-0.65, 0.35), (-0.8, 0.25), (-0.55, -0.35)):
            candidate = (x + dx, y + dy, w, h)
            if (candidate[1] - h / 2 < title_h or candidate[1] + h / 2 > system_h - 0.2
                    or any(er.boxes_overlap(candidate, box, gap=0.16)
                           for j, box in enumerate(uc_boxes) if index != j)):
                continue
            uc_boxes[index] = candidate
            direct, ends, trial_shapes, trial_deps = direct_paths()
            if _clear_usecase_paths(direct, ends, trial_shapes, trial_deps, model["dependencies"]):
                paths, dep_paths = direct, trial_deps
                break
        else:
            uc_boxes[index] = (x, y, w, h)

    return {
        "system": (system_x0, system_y0, system_w, system_h),
        "actors": actor_boxes,
        "use_cases": uc_boxes,
        "paths": paths,
        "dep_paths": dep_paths,
    }


def _finish_usecase_scene(model, scene, label_positions=None, *, short_labels_first=False):
    system_x0, system_y0, system_w, system_h = scene["system"]
    actor_boxes, uc_boxes, paths, dep_paths = (scene[key] for key in ("actors", "use_cases", "paths", "dep_paths"))
    shapes = [(*box, "a", i) for i, box in enumerate(uc_boxes)]
    actor_routes = [er._path_segments(path) for path in paths]
    dependency_routes = [er._path_segments(dep["points"]) for dep in dep_paths]
    routes = actor_routes + dependency_routes
    occupied = [line for segments in routes for line in segments]
    overlaps = sum(er.boxes_overlap(box, other, gap=0.04) for i, box in enumerate(shapes) for other in shapes[:i])
    hits = sum(er._route_box_hits(lines, shapes, None, shapes[link["use_case"]], exact=True)
               for lines, link in zip(actor_routes, model["links"]))
    hits += sum(er._route_box_hits(lines, shapes, shapes[rel["from"]], shapes[rel["to"]], exact=True)
                for lines, rel in zip(dependency_routes, model["dependencies"]))
    conflicts = sum(er._route_crosses_itself(lines) for lines in routes)
    conflicts += sum(er._routes_conflict(lines, other) for i, lines in enumerate(routes) for other in routes[:i])
    conflicts += sum(_near_dependency(lines, dependency) and not er._routes_conflict(lines, dependency)
                     for lines in actor_routes for dependency in dependency_routes)

    pinned_labels = {
        i: (*point, *_dependency_label_size(dep_paths[i]["kind"]))
        for i, point in (label_positions or {}).items()
    }
    labels = []
    actor_shapes = [(*box, "e", index) for index, *box in actor_boxes] if pinned_labels else []
    for label in pinned_labels.values():
        if _dependency_label_score(label, occupied, shapes + actor_shapes, labels):
            raise SpecError("标签与图形、连线或其他标签重叠，请拖到附近空白处")
        labels.append(label)
    label_conflicts = 0
    label_order = range(len(dep_paths))
    if short_labels_first:
        label_order = sorted(label_order, key=lambda index: sum(
            math.dist(line[:2], line[2:]) for line in dependency_routes[index]
        ))
    for index in label_order:
        dep = dep_paths[index]
        if dep["kind"] not in {"include", "extend"}:
            continue
        if index in pinned_labels:
            dep["label"] = pinned_labels[index]
            continue
        label, score = _choose_dependency_label(dep["kind"], dep["points"], occupied, shapes, labels,
                                                wider=short_labels_first)
        dep["label"] = label
        labels.append(label)
        label_conflicts += bool(score)

    xs = [system_x0, system_x0 + system_w]
    ys = [system_y0, system_y0 + system_h]
    for path in [*paths, *(dep["points"] for dep in dep_paths)]:
        xs.extend(x for x, _ in path)
        ys.extend(y for _, y in path)
    for _, cx, cy, w, h in actor_boxes:
        xs.extend([cx - w / 2, cx + w / 2])
        ys.extend([cy - h / 2, cy + h / 2])
    for cx, cy, w, h in uc_boxes:
        xs.extend([cx - w / 2, cx + w / 2])
        ys.extend([cy - h / 2, cy + h / 2])
    for x, y, w, h in labels:
        xs.extend((x - w / 2, x + w / 2))
        ys.extend((y - h / 2, y + h / 2))
    margin = 0.4
    scene["bounds"] = (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
    scene["useCaseQuality"] = {"overlaps": int(overlaps), "boxHits": int(hits),
                               "lineConflicts": int(conflicts), "labelConflicts": int(label_conflicts)}
    bends = sum(er._path_bends(path) for path in [*paths, *(dep["points"] for dep in dep_paths)])
    length = sum(math.dist(line[:2], line[2:]) for line in occupied)
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    # 相同的几何质量下，避免为了稍短的连线拉成又高又窄的画布。
    return (overlaps, hits, conflicts, label_conflicts, bends,
            length + 0.28 * width * height + 0.55 * max(width / 1.55, height)
            + 1.6 * max(0.0, height - width))


def _usecase_actor_partitions(actors, participation):
    counts = [0] * len(actors)
    for group in participation:
        for index in group:
            counts[index] += 1
    active = sorted((i for i, count in enumerate(counts) if count), key=lambda i: (-counts[i], i))
    if len(active) < 2:
        return [], []
    # For two or three active actors, isolating each role tries every split.
    splits = [(i,) for i in active]
    additional = []
    if len(active) > 3:
        secondary = tuple(i for i in active if actors[i]["kind"] == "secondary")
        if 1 < len(secondary) < len(active):
            splits.append(secondary)
        sides = [[], []]
        loads = [0, 0]
        for index in active:
            side = 0 if loads[0] <= loads[1] else 1
            sides[side].append(index)
            loads[side] += counts[index]
        balanced = tuple(sorted(sides[1]))
        if balanced not in splits:
            splits.append(balanced)
        # Keep frequently shared use cases on one side when both sides still have useful work.
        groups = [set(group) for group in participation if group]
        active_set = set(active)
        ranked = []
        for size in range(2, len(active) // 2 + 1):
            for selection in combinations(sorted(active), size):
                right = set(selection)
                left = active_set - right
                left_only = sum(group <= left for group in groups)
                right_only = sum(group <= right for group in groups)
                if not left_only or not right_only:
                    continue
                shared = len(groups) - left_only - right_only
                rank = (max(left_only, right_only, shared) + 0.5 * shared, abs(left_only - right_only))
                ranked.append((rank, selection))
        additional = [selection for _, selection in sorted(ranked) if selection not in splits][:2]
    return splits, additional


def _layout_usecase_candidate_search(model, positions=None):
    baseline = _usecase_candidate(model, positions)
    if positions:
        routed = _route_usecase_dependencies(baseline, model)
        return routed if _finish_usecase_scene(model, routed) < _finish_usecase_scene(model, baseline) else baseline

    count = len(model["use_cases"])
    order = list(range(count))
    participation = [[] for _ in order]
    for link in model["links"]:
        participation[link["use_case"]].append(link["actor"])
    grouped = sorted(order, key=lambda i: (sum(participation[i]) / len(participation[i]) if participation[i] else math.inf,
                                           -len(participation[i]), i))
    linked_count = sum(bool(group) for group in participation)
    default_cols = 1 if linked_count <= 4 else 2
    options = [
        {"order": order, "columns": default_cols},
        {"order": grouped, "columns": default_cols, "group_actors": True},
    ]
    extra_options = []
    if linked_count > 2:
        options.append({"order": grouped, "columns": 2 if default_cols == 1 else 3, "group_actors": True})
    if linked_count > 4:
        options.append({"order": list(reversed(grouped)), "columns": default_cols, "group_actors": True})
        options.append({"order": grouped, "columns": 1, "group_actors": True})
        partitions, alternative_partitions = _usecase_actor_partitions(model["actors"], participation)
        for right in partitions + alternative_partitions:
            target = options if right in partitions else extra_options
            split = {"order": grouped, "group_actors": True, "right_actors": right}
            target.append(split)
            # A longer run gives a busy actor's outermost links a clear angle past adjacent use cases.
            widened = dict(split, actor_gap=1.85)
            target.append(widened)
            if len(model["dependencies"]) == 1:
                # Place a dependent task near its actor's center so the side lane stays reachable.
                dep = model["dependencies"][0]
                centered = grouped.copy()
                for case in (dep["from"], dep["to"]):
                    peers = [i for i in centered if participation[i] == participation[case]]
                    if len(peers) > 2:
                        a, b = centered.index(case), centered.index(peers[len(peers) // 2])
                        centered[a], centered[b] = centered[b], centered[a]
                target.append(dict(widened, order=centered))
            if any(any(i in right for i in group) and any(i not in right for i in group)
                   for group in participation):
                target.extend(dict(widened, shared_row_offset=offset) for offset in (0.25, 0.75))
        if len(model["dependencies"]) >= 3:
            # Put related cases near one another within their actor groups.
            graph = nx.Graph()
            graph.add_nodes_from(order)
            graph.add_edges_from((dep["from"], dep["to"]) for dep in model["dependencies"])
            order_index = {index: rank for rank, index in enumerate(grouped)}
            component_start = {}
            for component in nx.connected_components(graph):
                start = min(order_index[node] for node in component)
                component_start.update(dict.fromkeys(component, start))
            related = sorted(grouped, key=lambda index: component_start[index])
            if related != grouped:
                extra_options.extend({"order": related, "columns": columns, "group_actors": True} for columns in (2, 3))
                for right in partitions[-1:] + alternative_partitions:
                    extra_options.append({"order": related, "group_actors": True, "right_actors": right, "actor_gap": 1.85})
    candidates, extra_candidates = [], []
    best = baseline
    best_rank = _finish_usecase_scene(model, best)
    for choices, scored in ((options, candidates), (extra_options, extra_candidates)):
        for option in choices:
            trial = _usecase_candidate(model, route=False, **option)
            rank = _finish_usecase_scene(model, trial)
            scored.append((rank, option))
            if rank < best_rank:
                best, best_rank = trial, rank
    if any(best_rank[:5]):
        routed_baseline = _route_usecase_dependencies(baseline, model)
        rank = _finish_usecase_scene(model, routed_baseline)
        if rank < best_rank:
            best, best_rank = routed_baseline, rank
        shortlisted = sorted(candidates, key=lambda candidate: candidate[0])[:2]
        shortlisted += sorted(extra_candidates, key=lambda candidate: candidate[0])[:2]
        for _, option in shortlisted:
            trial = _usecase_candidate(model, **option)
            trial = _route_usecase_dependencies(trial, model)
            rank = _finish_usecase_scene(model, trial)
            if rank < best_rank:
                best, best_rank = trial, rank
        if any(best_rank[1:3]):
            refined = _refine_usecase_routes(best, model)
            rank = _finish_usecase_scene(model, refined)
            if rank < best_rank:
                best, best_rank = refined, rank
    if best_rank[3]:
        trial = dict(best, dep_paths=[dict(dep) for dep in best["dep_paths"]])
        rank = _finish_usecase_scene(model, trial, short_labels_first=True)
        if rank < best_rank:
            best, best_rank = trial, rank
    if best_rank[4]:
        best = _straighten_dependency_fans(model, best, best_rank, participation)
    return best


def _straighten_dependency_fans(model, best, best_rank, participation):
    """Move dependency-only fans away from the lane that obstructs their straight edges."""
    cases = model["use_cases"]
    neighbors = [set() for _ in participation]
    for dep in model["dependencies"]:
        neighbors[dep["from"]].add(dep["to"])
        neighbors[dep["to"]].add(dep["from"])
    for hub, adjacent in enumerate(neighbors):
        if participation[hub]:
            continue
        leaves = tuple(sorted(i for i in adjacent if not participation[i] and len(neighbors[i]) == 1))
        if len(leaves) < 3:
            continue
        moved = {hub, *leaves}
        affected = [index for index, dep in enumerate(model["dependencies"])
                    if dep["from"] in moved or dep["to"] in moved]
        if not any(er._path_bends(best["dep_paths"][index]["points"]) for index in affected):
            continue
        boxes = best["use_cases"]
        positions = {case["name"]: box[:2] for case, box in zip(cases, boxes)}
        positions.update((model["actors"][index]["name"], (x, y)) for index, x, y, _, _ in best["actors"])
        hub_x, hub_y, hub_width, _ = boxes[hub]
        anchors = [boxes[index][1] for index in adjacent - moved]
        anchor_y = sum(anchors) / len(anchors) if anchors else hub_y
        separation = (hub_width + max(boxes[index][2] for index in leaves)) / 2
        for side in (1, -1):
            for gap in (0.85, 1.35):
                for center_y in (anchor_y, anchor_y - 0.5, anchor_y + 0.5, hub_y):
                    positions[cases[hub]["name"]] = (hub_x, center_y)
                    for row, index in enumerate(leaves):
                        leaf_y = center_y + (row - (len(leaves) - 1) / 2) * 1.17
                        positions[cases[index]["name"]] = (hub_x + side * (separation + gap), leaf_y)
                    trial = _usecase_candidate(model, positions, route=False)
                    sx, _, sw, _ = trial["system"]
                    if any(x + w / 2 >= sx and x - w / 2 <= sx + sw for _, x, _, w, _ in trial["actors"]):
                        continue
                    trial["paths"] = best["paths"]
                    trial["dep_paths"] = [dep if index in affected else dict(best["dep_paths"][index])
                                          for index, dep in enumerate(trial["dep_paths"])]
                    rank = _finish_usecase_scene(model, trial, short_labels_first=True)
                    if rank < best_rank:
                        best, best_rank = trial, rank
    return best


def _layout_two_actor_group(model):
    if len(model["actors"]) != 2:
        return None
    cases = model["use_cases"]
    participation = [set() for _ in cases]
    for link in model["links"]:
        participation[link["use_case"]].add(link["actor"])
    shared = [index for index, actors in enumerate(participation) if len(actors) == 2]
    if len(shared) < 2:
        return None
    private = [[index for index, actors in enumerate(participation) if actors == {actor}] for actor in (0, 1)]
    dependency_only = [index for index, actors in enumerate(participation) if not actors]
    shared_set = set(shared)
    between_shared = {
        other for dep in model["dependencies"] for linked, other in (
            (dep["from"], dep["to"]), (dep["to"], dep["from"]),
        ) if linked in shared_set and len(participation[other]) == 1
    }
    shared.sort(key=lambda index: -sum(index in (dep["from"], dep["to"]) for dep in model["dependencies"]))
    lane_width = max(_use_case_size(case["name"])[0] for case in cases) + 0.25
    actor_width = max(_actor_size(actor["name"])[0] for actor in model["actors"])
    actor_distance = max(4.15, 1.5 * lane_width + actor_width / 2 + 1.1)
    candidates = []
    for direction in (1, -1):
        for spacing in (0.85, 1.0, 1.15):
            positions = {actor["name"]: (side * actor_distance, 0.02)
                         for actor, side in zip(model["actors"], (-1, 1))}
            shared_top = -(len(shared) - 1) * 0.8
            for row, index in enumerate(shared):
                positions[cases[index]["name"]] = (0.0, direction * spacing * (shared_top + row * 1.6))
            private_y = shared_top - 1.4
            for side, indices in zip((-1, 1), private):
                for row, index in enumerate(indices):
                    positions[cases[index]["name"]] = (side * lane_width,
                                                       direction * spacing * (private_y - row * 1.1))
            dependency_y = private_y - (max(1, *map(len, private)) - 1) * 1.1 - 1.15
            for row, index in enumerate(dependency_only):
                positions[cases[index]["name"]] = (0.0, direction * spacing * (dependency_y - row * 1.1))
            layouts = [positions]
            if between_shared:
                centered = dict(positions)
                for side, indices in zip((-1, 1), private):
                    middle = [index for index in indices if index in between_shared]
                    for row, index in enumerate(middle):
                        y = direction * spacing * (row - (len(middle) - 1) / 2) * 1.1
                        centered[cases[index]["name"]] = (side * lane_width, y)
                layouts.append(centered)
            for layout in layouts:
                scene = _usecase_candidate(model, layout, route=False)
                boundary_x, _, width, _ = scene["system"]
                left, right = scene["actors"]
                if left[1] + left[3] / 2 >= boundary_x or right[1] - right[3] / 2 <= boundary_x + width:
                    continue
                rank = _finish_usecase_scene(model, scene, short_labels_first=True)
                if not any(rank[:4]):
                    candidates.append((rank, scene))
    return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None


def _usecase_components(model):
    graph = nx.Graph()
    graph.add_nodes_from(("actor", index) for index in range(len(model["actors"])))
    graph.add_nodes_from(("case", index) for index in range(len(model["use_cases"])))
    graph.add_edges_from((("actor", link["actor"]), ("case", link["use_case"])) for link in model["links"])
    graph.add_edges_from((("case", dep["from"]), ("case", dep["to"])) for dep in model["dependencies"])
    return list(nx.connected_components(graph))


def _layout_usecase_components(model, components):
    """Pack disconnected workflows into separate bands inside a single system boundary."""
    combined = {
        "actors": [],
        "use_cases": [None] * len(model["use_cases"]),
        "paths": [None] * len(model["links"]),
        "dep_paths": [None] * len(model["dependencies"]),
    }
    width = er.tw(model["system"]) + 0.8
    bottom = 0.0
    for component in components:
        actors = sorted(index for kind, index in component if kind == "actor")
        cases = sorted(index for kind, index in component if kind == "case")
        if not actors or not cases:
            return None
        actor_map = {index: local for local, index in enumerate(actors)}
        case_map = {index: local for local, index in enumerate(cases)}
        links = [(index, {"actor": actor_map[link["actor"]], "use_case": case_map[link["use_case"]]})
                 for index, link in enumerate(model["links"]) if link["actor"] in actor_map]
        deps = [(index, {**dep, "from": case_map[dep["from"]], "to": case_map[dep["to"]]})
                for index, dep in enumerate(model["dependencies"]) if dep["from"] in case_map]
        local_model = dict(model, actors=[model["actors"][i] for i in actors],
                           use_cases=[model["use_cases"][i] for i in cases],
                           links=[link for _, link in links], dependencies=[dep for _, dep in deps])
        scene = _layout_two_actor_group(local_model) or _usecase_candidate(local_model, route=False)
        if any(_finish_usecase_scene(local_model, scene, short_labels_first=True)[:4]):
            tree = _layout_tree_component(local_model)
            if tree is not None:
                scene = tree
            else:
                # Shared actors make a component cyclic even when straight drawing is possible.
                scene = _layout_usecase_candidate_search(local_model)
                scene = _improve_straight_usecase(local_model, scene)
                if any(_finish_usecase_scene(local_model, scene, short_labels_first=True)[:4]):
                    return None
        sx, sy, sw, sh = scene["system"]
        _, top, _, local_bottom = scene["bounds"]
        dx, dy = -sx - sw / 2, bottom - min(top, sy)
        width = max(width, sw)
        bottom = max(local_bottom, sy + sh) + dy + 0.25
        combined["actors"].extend((actors[index], x + dx, y + dy, w, h) for index, x, y, w, h in scene["actors"])
        for index, (x, y, w, h) in zip(cases, scene["use_cases"]):
            combined["use_cases"][index] = (x + dx, y + dy, w, h)
        for (index, _), path in zip(links, scene["paths"]):
            combined["paths"][index] = [(x + dx, y + dy) for x, y in path]
        for (index, _), dep in zip(deps, scene["dep_paths"]):
            combined["dep_paths"][index] = dict(dep, points=[(x + dx, y + dy) for x, y in dep["points"]])
    # Align actors with the common boundary and recompute ports after packing.
    if any(abs(x) - w / 2 <= width / 2 for _, x, _, w, _ in combined["actors"]):
        positions = {case["name"]: box[:2] for case, box in zip(model["use_cases"], combined["use_cases"])}
        for index, x, y, w, _ in combined["actors"]:
            distance = max(abs(x), width / 2 + w / 2 + 1.05)
            positions[model["actors"][index]["name"]] = (math.copysign(distance, x), y)
        return _usecase_candidate(model, positions, route=False)
    combined["system"] = (-width / 2, 0.0, width, bottom)
    return combined


def _layout_tree_component(model):
    """Place sibling subtrees in separate row spans and leaf actors outside the boundary."""
    actors, cases = model["actors"], model["use_cases"]
    offset = len(actors)
    graph = nx.Graph()
    graph.add_edges_from((link["actor"], offset + link["use_case"]) for link in model["links"])
    graph.add_edges_from((offset + d["from"], offset + d["to"]) for d in model["dependencies"])
    if not nx.is_tree(graph):
        return None
    column = max(_use_case_size(case["name"])[0] for case in cases) + 1.6
    for root in sorted(range(offset), key=lambda i: -graph.degree(i)):
        positions = {}
        row = 0

        def place(node, parent, depth):
            nonlocal row
            children = sorted(n for n in graph[node] if n != parent)
            if children:
                centers = [place(n, node, depth + 1) for n in children]
                y = (centers[0] + centers[-1]) / 2
            else:
                y = row * 1.6
                row += 1
            name = actors[node]["name"] if node < offset else cases[node - offset]["name"]
            positions[name] = (depth * column, y)
            return y

        place(root, None, 0)
        right = max(positions[c["name"]][0] + _use_case_size(c["name"])[0] / 2 for c in cases) + 2
        for index, actor in enumerate(actors):
            if index != root:
                name = actor["name"]
                positions[name] = (right + _actor_size(name)[0] / 2, positions[name][1])
        scene = _usecase_candidate(model, positions, route=False)
        if not any(_finish_usecase_scene(model, scene, short_labels_first=True)[:4]):
            return scene
    return None


def layout_usecase(model, positions=None):
    if positions:
        return _layout_usecase_candidate_search(model, positions)
    actors, cases = model["actors"], model["use_cases"]
    associations = [0] * len(actors)
    for link in model["links"]:
        associations[link["actor"]] += 1
    actor_order = sorted(range(len(actors)), key=lambda i: (actors[i]["kind"], associations[i], actors[i]["name"]))
    actor_index = {original: i for i, original in enumerate(actor_order)}
    participants = [[] for _ in cases]
    degree = [0] * len(cases)
    for link in model["links"]:
        participants[link["use_case"]].append(actor_index[link["actor"]])
    for dep in model["dependencies"]:
        degree[dep["from"]] += 1
        degree[dep["to"]] += 1
    case_order = sorted(range(len(cases)), key=lambda i: (
        -len(participants[i]), sorted(participants[i]), -degree[i], cases[i]["name"]))
    case_index = {original: i for i, original in enumerate(case_order)}
    links = [dict(link, actor=actor_index[link["actor"]], use_case=case_index[link["use_case"]])
             for link in model["links"]]
    deps = [{**dep, "from": case_index[dep["from"]], "to": case_index[dep["to"]]} for dep in model["dependencies"]]
    link_order = sorted(range(len(links)), key=lambda i: (links[i]["actor"], links[i]["use_case"]))
    dep_order = sorted(range(len(deps)), key=lambda i: (deps[i]["from"], deps[i]["to"], deps[i]["kind"]))
    ordered = dict(model, actors=[actors[i] for i in actor_order], use_cases=[cases[i] for i in case_order],
                   links=[links[i] for i in link_order], dependencies=[deps[i] for i in dep_order])
    scene = _compact_usecase_scene(ordered, _layout_automatic_usecase(ordered))
    # The editor and pinned dependency labels address records in their original order.
    scene["actors"] = sorted((actor_order[i], *box) for i, *box in scene["actors"])
    for key, order in (("use_cases", case_order), ("paths", link_order), ("dep_paths", dep_order)):
        values = scene[key].copy()
        for i, original in enumerate(order):
            scene[key][original] = values[i]
    return scene


def _compact_usecase_scene(model, scene):
    """Remove empty coordinate bands, then validate newly straightened edges and labels."""
    best_rank = _finish_usecase_scene(model, scene, short_labels_first=True)
    for gap in (0.9, 0.6):
        boxes = [*scene["use_cases"], *(box for _, *box in scene["actors"])]
        shifts = []
        for axis in (0, 1):
            intervals = sorted((b[axis] - b[axis + 2] / 2, b[axis] + b[axis + 2] / 2) for b in boxes)
            bands = []
            right = intervals[0][1]
            for left, end in intervals[1:]:
                if left - right > gap:
                    bands.append((right, left, left - right - gap))
                right = max(right, end)
            shifts.append(bands)

        def move(x, y):
            return tuple(value - sum(amount for _, end, amount in shifts[axis] if value >= end)
                         for axis, value in enumerate((x, y)))

        positions = {case["name"]: move(*box[:2]) for case, box in zip(model["use_cases"], scene["use_cases"])}
        for index, x, y, _, _ in scene["actors"]:
            positions[model["actors"][index]["name"]] = move(x, y)
        trial = _usecase_candidate(model, positions, route=False)
        sx, _, sw, _ = trial["system"]
        # Keep each actor adjacent to the actual system boundary and its associated cases.
        for index, x, y, w, _ in trial["actors"]:
            side = -1 if x < sx + sw / 2 else 1
            positions[model["actors"][index]["name"]] = (
                sx - w / 2 - 0.7 if side < 0 else sx + sw + w / 2 + 0.7, y)
        trial = _usecase_candidate(model, positions, route=False)
        rank = _finish_usecase_scene(model, trial, short_labels_first=True)
        if rank < best_rank:
            scene, best_rank = trial, rank
        for index, actor in enumerate(model["actors"]):
            ys = [positions[model["use_cases"][link["use_case"]]["name"]][1]
                  for link in model["links"] if link["actor"] == index]
            if not ys:
                continue
            name = actor["name"]
            half_width = _actor_size(name)[0] / 2
            for x in (sx - half_width - 0.7, sx + sw + half_width + 0.7):
                for offset in (0, -0.8, 0.8):
                    moved = dict(positions, **{name: (x, sum(ys) / len(ys) + offset)})
                    trial = _usecase_candidate(model, moved, route=False)
                    actor_boxes = [box for _, *box in trial["actors"]]
                    if any(er.boxes_overlap(box, other, gap=0.15)
                           for i, box in enumerate(actor_boxes) for other in actor_boxes[:i]):
                        continue
                    rank = _finish_usecase_scene(model, trial, short_labels_first=True)
                    if rank < best_rank:
                        positions, scene, best_rank = moved, trial, rank
    return scene


def _layout_automatic_usecase(model):
    best = _layout_usecase_candidate_search(model)
    conflicts = any(best["useCaseQuality"].values())
    bends = sum(er._path_bends(path) for path in best["paths"])
    bends += sum(er._path_bends(dep["points"]) for dep in best["dep_paths"])
    if not conflicts and not bends:
        return best
    components = _usecase_components(model)
    if len(components) > 1:
        candidate = _layout_usecase_components(model, components)
    else:
        candidate = _layout_two_actor_group(model)
    if candidate:
        rank = _finish_usecase_scene(model, candidate, short_labels_first=True)
        if not any(rank[:4]) and (conflicts or rank[4] < bends):
            return candidate
    if len(model["links"]) + len(model["dependencies"]) <= 40:
        candidate = _improve_straight_usecase(model, best)
        if _finish_usecase_scene(model, candidate, short_labels_first=True) < _finish_usecase_scene(model, best):
            return candidate
    return best


def _improve_straight_usecase(model, scene):
    """Move nodes before accepting detours, evaluating all associations and labels together."""
    positions = {case["name"]: box[:2] for case, box in zip(model["use_cases"], scene["use_cases"])}
    positions.update((model["actors"][i]["name"], (x, y)) for i, x, y, _, _ in scene["actors"])
    actors = {actor["name"] for actor in model["actors"]}
    sx, _, sw, _ = scene["system"]
    cases = [case["name"] for case in model["use_cases"]]

    def evaluate(points):
        trial = _usecase_candidate(model, points, route=False)
        rank = _finish_usecase_scene(model, trial, short_labels_first=True)
        # A single count of geometric violations allows moves that trade a crossing for a box hit
        # temporarily, instead of trapping the search behind a lexicographic barrier.
        return (sum(rank[:4]), rank[0], rank[1], rank[2], rank[3], rank[-1]), trial

    score, best = evaluate(positions)
    for step in (1.2, 0.6, 0.3):
        for name in [*cases, *sorted(actors)]:
            x, y = positions[name]
            choices = [(x, y + dy) for dy in (-2 * step, -step, step, 2 * step)]
            if name in actors:
                # A shared use case often needs its actors on opposite sides.
                gap = _actor_size(name)[0] / 2 + 1.05
                opposite = sx + sw + gap if x < sx else sx - gap
                choices += [(opposite, y + dy) for dy in (-step, 0, step)]
            else:
                choices += [(x + dx, y + dy) for dx in (-step, step) for dy in (-step, 0, step)
                            if sx + 0.8 < x + dx < sx + sw - 0.8]
            for point in choices:
                moved = dict(positions, **{name: point})
                candidate_score, candidate = evaluate(moved)
                if candidate_score < score:
                    positions, score, best = moved, candidate_score, candidate
        if not score[0]:
            break
    return best


def _clear_usecase_paths(paths, endpoints, shapes, dependencies, relations):
    actor_routes = [er._path_segments(path) for path in paths]
    dep_routes = [er._path_segments(dep["points"]) for dep in dependencies]
    routes = actor_routes + dep_routes
    if any(er._routes_conflict(route, other) for i, route in enumerate(routes) for other in routes[:i]):
        return False
    if any(_near_dependency(lines, dependency) for lines in actor_routes for dependency in dep_routes):
        return False
    if any(er._route_box_hits(route, shapes, None, target, exact=True)
           for route, (_, target) in zip(actor_routes, endpoints)):
        return False
    return not any(er._route_box_hits(route, shapes, shapes[rel["from"]], shapes[rel["to"]], exact=True)
                   for route, rel in zip(dep_routes, relations))


def _near_dependency(lines, dependency):
    return any(sum(er._waypoint_near_line((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t), dep, gap=0.085)
                   for t in (0.25, 0.5, 0.75)) >= 2 for x0, y0, x1, y1 in lines for dep in dependency)


def _route_usecase_paths(paths, endpoints, shapes, obstacles, *, refine=False):
    paths = list(paths)
    routes = [er._path_segments(path) for path in paths]
    order = range(len(endpoints))
    if refine:
        def priority(index):
            _, source, target = endpoints[index]
            lines = routes[index]
            hits = er._route_box_hits(lines, shapes, source, target, exact=True)
            conflicts = sum(er._routes_conflict(lines, route) for j, route in enumerate(routes) if j != index)
            conflicts += sum(er._routes_conflict(lines, route) or _near_dependency(lines, route)
                             for route in obstacles)
            return hits, conflicts

        order = sorted(order, key=priority, reverse=True)
    for i in order:
        start, source, target = endpoints[i]
        end = target[:2]
        if start == end:
            continue
        others = routes[:i] + routes[i + 1:]

        def score(lines):
            return (er._route_box_hits(lines, shapes, source, target, exact=True),
                    sum(er._routes_conflict(lines, other) for other in [*obstacles, *others]),
                    sum(_near_dependency(lines, other) for other in obstacles))

        best = score(routes[i])
        if best == (0, 0, 0):
            continue
        baseline = best
        best_rank = (*best, math.inf)
        # Bound geometry work independently of machine speed. The worker enforces the wall-clock limit.
        workload = len(routes) + len(obstacles)
        limit = 360 if workload <= 20 else max(24, 5400 // (workload * workload))
        candidates = er._detour_candidates(start, end, shapes)
        if limit < 68:
            # Sample short offsets and obstacle corners even when the budget is small.
            offsets = list(islice(candidates, 20))
            candidates = chain(offsets[:4], islice(candidates, limit - 4))
        for points in islice(candidates, limit):
            if points[-2] == end or points[1] == start:
                continue
            first = start if source is None else er._edge_port(start, points[1], source)
            candidate = (first, *points[1:-1], er._edge_port(end, points[-2], target))
            lines = er._path_segments(candidate)
            if er._route_crosses_itself(lines):
                continue
            length = sum(math.dist(line[:2], line[2:]) for line in lines)
            if refine and length > math.dist(start, end) * 1.45 + 0.7:
                continue
            quality = score(lines)
            if quality >= baseline:
                continue
            cost = length + 0.2 * er._path_bends(candidate)
            rank = (*quality, cost)
            if rank < best_rank:
                paths[i], routes[i], best_rank = candidate, lines, rank
    return paths


def _route_actor_links(paths, endpoints, shapes, dependencies):
    dep_routes = [er._path_segments(dep["points"]) for dep in dependencies]
    return _route_usecase_paths(paths, [(start, None, target) for start, target in endpoints], shapes,
                                dep_routes)


def _route_usecase_dependencies(scene, model, *, refine=False):
    shapes = [(*box, "a", i) for i, box in enumerate(scene["use_cases"])]
    endpoints = [(shapes[dep["from"]][:2], shapes[dep["from"]], shapes[dep["to"]]) for dep in model["dependencies"]]
    paths = _route_usecase_paths([dep["points"] for dep in scene["dep_paths"]], endpoints, shapes,
                                  [er._path_segments(path) for path in scene["paths"]],
                                  refine=refine)
    return dict(scene, dep_paths=[dict(dep, points=path) for dep, path in zip(scene["dep_paths"], paths)])


def _refine_usecase_routes(scene, model):
    shapes = [(*box, "a", i) for i, box in enumerate(scene["use_cases"])]
    endpoints = [(path[0], None, shapes[link["use_case"]]) for path, link in zip(scene["paths"], model["links"])]
    dependencies = [er._path_segments(dep["points"]) for dep in scene["dep_paths"]]
    paths = _route_usecase_paths(scene["paths"], endpoints, shapes, dependencies,
                                refine=True)
    return _route_usecase_dependencies(dict(scene, paths=paths), model, refine=True)


def _draw_stick_actor(ax, cx, cy, name):
    """倒置坐标系：较小 y 在图像上方；头朝上、脚朝下，名称写在脚下。"""
    lw = USECASE_LINE_WIDTH
    head_r = 0.11
    head_y = cy - 0.2
    neck = head_y + head_r
    hip = cy + 0.06
    ax.add_patch(Circle((cx, head_y), head_r, fc="white", ec="black", lw=lw, zorder=4))
    ax.plot([cx, cx], [neck, hip], color="black", lw=lw, zorder=4)
    ax.plot([cx - 0.17, cx + 0.17], [neck + 0.06, neck + 0.06], color="black", lw=lw, zorder=4)
    ax.plot([cx, cx - 0.14], [hip, hip + 0.2], color="black", lw=lw, zorder=4)
    ax.plot([cx, cx + 0.14], [hip, hip + 0.2], color="black", lw=lw, zorder=4)
    ax.text(cx, hip + 0.28, name, fontproperties=er.FP, fontsize=USECASE_TEXT_SIZE,
            ha="center", va="top", zorder=5)


def _dependency_label_size(kind):
    text = "«include»" if kind == "include" else "«extend»"
    return max(0.30, er.tw(text)) + 0.07, 0.20


def _dependency_label_score(box, occupied, shapes, placed):
    return (sum(er._seg_hits_rect(*line, *box) for line in occupied)
            + sum(er.label_hits_shape(box, shape) for shape in shapes)
            + sum(er.boxes_overlap(box, other, gap=0.025) for other in placed))


def _choose_dependency_label(kind, path, occupied, shapes, placed, *, wider=False):
    width, height = _dependency_label_size(kind)
    best, best_score = None, math.inf
    segments = sorted(er._path_segments(path), key=lambda line: -math.dist(line[:2], line[2:]))
    fractions = (0.5, 0.35, 0.65, 0.2, 0.8)
    offsets = (-0.16, 0.16, -0.24, 0.24, -0.36, 0.36, -0.48, 0.48, -0.62, 0.62)
    if wider:
        fractions += (0.1, 0.9)
        offsets += (-0.75, 0.75, -0.86, 0.86)
    for x0, y0, x1, y1 in segments[:3]:
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        nx, ny = -dy / length, dx / length
        for fraction in fractions:
            for offset in offsets:
                box = (x0 + dx * fraction + nx * offset, y0 + dy * fraction + ny * offset, width, height)
                score = _dependency_label_score(box, occupied, shapes, placed)
                if score == 0:
                    return box, 0
                if score < best_score:
                    best, best_score = box, score
    if best is None:
        best = (*path[0], width, height)
    return best, best_score


def _draw_dependency(ax, dep):
    lw = USECASE_LINE_WIDTH
    kind, points = dep["kind"], dep["points"]
    x0, y0 = points[-2]
    x1, y1 = points[-1]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if not length:
        return
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux

    if kind in {"include", "extend"}:
        tip_len = min(0.18, length / 2)
        tip_width = tip_len * 0.45
        shaft_x, shaft_y = x1 - ux * tip_len, y1 - uy * tip_len
        px, py = zip(*points)
        ax.plot(px, py, color="black", lw=lw, linestyle="--", zorder=3)
        ax.plot([shaft_x + nx * tip_width, x1, shaft_x - nx * tip_width],
                [shaft_y + ny * tip_width, y1, shaft_y - ny * tip_width],
                color="black", lw=lw, zorder=3)
        label = "«include»" if kind == "include" else "«extend»"
        tx, ty = dep["label"][:2]
        ax.text(tx, ty, label, fontproperties=er.FP, ha="center", va="center",
                fontsize=USECASE_TEXT_SIZE, zorder=6, color="black")
        return

    # 泛化：实线 + 空心三角指向父用例
    tip_len = min(0.22, length / 2)
    tip_w = tip_len * 0.64
    base_x = x1 - ux * tip_len
    base_y = y1 - uy * tip_len
    px, py = zip(*points[:-1], (base_x, base_y))
    ax.plot(px, py, color="black", lw=lw, zorder=3)
    triangle = Polygon(
        [
            (x1, y1),
            (base_x + nx * tip_w, base_y + ny * tip_w),
            (base_x - nx * tip_w, base_y - ny * tip_w),
        ],
        closed=True,
        fc="white",
        ec="black",
        lw=lw,
        zorder=4,
    )
    ax.add_patch(triangle)


def draw_usecase(model, scene, out, image_format="png", canvas_ratio=None):
    x0, y0, x1, y1 = scene["bounds"]
    Wd, Hd = x1 - x0, y1 - y0
    content_frame = {"x": x0, "y": y0, "width": Wd, "height": Hd}
    target_width, target_height, render_dpi = _canvas_dimensions(Wd, Hd, image_format, canvas_ratio)
    x0 -= (target_width - Wd) / 2
    y0 -= (target_height - Hd) / 2
    Wd, Hd = target_width, target_height
    fig = plt.figure(figsize=(Wd, Hd), dpi=render_dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0, x0 + Wd)
    # 与 E-R 一致：倒置 y，较小 y 在图像上方，拖拽叠加层可直接复用
    ax.set_ylim(y0 + Hd, y0)
    ax.axis("off")

    lw = USECASE_LINE_WIDTH
    sx, sy, sw, sh = scene["system"]
    ax.add_patch(Rectangle((sx, sy), sw, sh, fc="white", ec="black", lw=lw, zorder=1))
    # 倒置后 sy 靠近图像上方
    ax.text(sx + sw / 2, sy + 0.22, model["system"], fontproperties=er.FP,
            fontsize=USECASE_TEXT_SIZE, ha="center", va="center", zorder=2)

    for path in scene["paths"]:
        xs, ys = zip(*path)
        ax.plot(xs, ys, color="black", lw=lw, zorder=3)

    for dep in scene.get("dep_paths", []):
        _draw_dependency(ax, dep)

    for index, (cx, cy, w, h) in enumerate(scene["use_cases"]):
        ax.add_patch(Ellipse((cx, cy), w, h, fc="white", ec="black", lw=lw, zorder=4))
        ax.text(cx, cy, model["use_cases"][index]["name"], fontproperties=er.FP,
                fontsize=USECASE_TEXT_SIZE, ha="center", va="center", zorder=5)

    for actor_i, cx, cy, w, h in scene["actors"]:
        _draw_stick_actor(ax, cx, cy, model["actors"][actor_i]["name"])

    fig.savefig(out, format=image_format, dpi=render_dpi, facecolor="white")
    plt.close(fig)
    print("已生成", out, "(%.2f x %.2f 英寸)" % (Wd, Hd))

    entities = []
    for i, cx, cy, w, h in scene["actors"]:
        entities.append({
            "entity": model["actors"][i]["name"],
            "x": cx,
            "y": cy,
            "width": w,
            "height": h,
        })
    for i, (cx, cy, w, h) in enumerate(scene["use_cases"]):
        entities.append({
            "entity": model["use_cases"][i]["name"],
            "x": cx,
            "y": cy,
            "width": w,
            "height": h,
        })

    return {
        "x": x0,
        "y": y0,
        "width": Wd,
        "height": Hd,
        "contentFrame": content_frame,
        "useCaseQuality": scene["useCaseQuality"],
        "entities": entities,
        "dependencyLabels": [
            {"index": index, "name": f"«{dep['kind']}»", "x": x, "y": y, "width": w, "height": h}
            for index, dep in enumerate(scene["dep_paths"]) if "label" in dep
            for x, y, w, h in [dep["label"]]
        ],
        "actors": [
            {"actor": model["actors"][i]["name"], "x": cx, "y": cy, "width": w, "height": h}
            for i, cx, cy, w, h in scene["actors"]
        ],
        "useCases": [
            {"useCase": model["use_cases"][i]["name"], "x": cx, "y": cy, "width": w, "height": h}
            for i, (cx, cy, w, h) in enumerate(scene["use_cases"])
        ],
    }


def render_usecase_spec(model, output_dir=None, *, image_format="png", font=None, dpi=300,
                        chapter="1", canvas_ratio=None, positions=None, label_positions=None):
    er.DPI = dpi
    init_font(font)
    diagrams = []

    def draw(filename, draw_image, *args, **kwargs):
        destination = os.path.join(output_dir, filename) if output_dir is not None else BytesIO()
        layout = draw_image(*args, destination, **kwargs)
        diagram = {"filename": filename, "entity": None, "layout": layout}
        if isinstance(destination, BytesIO):
            diagram["content"] = destination.getvalue()
            destination.close()
        diagrams.append(diagram)

    try:
        if output_dir is not None:
            os.makedirs(output_dir, exist_ok=True)
        scene = layout_usecase(model, positions=positions)
        if label_positions:
            _finish_usecase_scene(model, scene, label_positions)
        filename = f"图{chapter}-1_{safe(model['system'] or model['title'] or '用例图')}用例图.{image_format}"
        draw(filename, draw_usecase, model, scene, image_format=image_format, canvas_ratio=canvas_ratio)
        return diagrams
    finally:
        plt.close(er._fig0)
        er._fig0 = er._renderer = None
