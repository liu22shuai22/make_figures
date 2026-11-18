# -*- coding: utf-8 -*-
"""
通用 E-R 图生成器  ——  自然语言 → 实体属性图 + 整体 E-R 图
==========================================================
流程：   自然语言课题描述
           │  (大模型，可选)
           ▼
        JSON 规格（实体 / 属性 / 联系 / 基数）   ← 可保存、可手改、可重复使用
           │  校验与规范化
           ▼
        自动布局（模拟退火：最少交叉、不压线、不重叠）
           ▼
        出图（PNG / SVG / PDF，真实尺寸：五号字、0.5 磅线）

用法示例
--------
1) 自然语言直接出图（需要大模型 API，见下方"大模型配置"）
       python er_generator.py "做一个图书管理系统，读者可以借阅图书，图书有分类，管理员负责……"
       python er_generator.py --text-file 需求.txt
       python er_generator.py                      # 不带参数 → 交互式输入

2) 没有 API？把提示词贴到任意网页版大模型，让它返回 JSON，保存为 spec.json 后：
       python er_generator.py --prompt-only "你的课题描述"    # 打印提示词
       python er_generator.py --spec spec.json

3) 手改规格再重画（第 1 步会自动把规格保存为 输出目录/spec.json）
       python er_generator.py --spec figures/spec.json

大模型配置（任选其一，只用到标准库，无需额外 pip 包）
--------
    Anthropic :  set ANTHROPIC_API_KEY=sk-ant-xxx            （Windows）
                 export ANTHROPIC_API_KEY=sk-ant-xxx         （macOS/Linux）
    OpenAI 兼容（DeepSeek、通义、Kimi、智谱、本地 Ollama 等都行）：
                 export LLM_API_KEY=xxx
                 export LLM_BASE_URL=https://api.deepseek.com/v1
                 export LLM_MODEL=deepseek-chat
    也可用命令行 --provider / --model / --base-url / --api-key 指定。

JSON 规格格式
-------------
{
  "title": "图书管理系统",
  "entities": [
    {"name": "读者", "attrs": ["*读者ID", "姓名", "电话"]},        # * 开头 = 主键（画下划线）
    {"name": "图书", "attrs": ["*图书ID", "书名", "作者"]}
  ],
  "relations": [
    {"name": "借阅", "a": "读者", "b": "图书", "card": ["m", "n"],
     "attrs": ["借阅日期", "归还日期"]}                            # 联系自己的属性，可省略
  ]
}
  * card 是 a 端、b 端的基数，如 ["1","n"]、["m","n"]、["1","1"]。
  * a、b 填同一个实体就是自联系（如"课程-前置-课程"）。
  * 三元联系：用 "entities": ["甲","乙","丙"], "card": ["m","n","p"]。

格式说明（与原脚本一致）
--------
  * 字号 10.5 磅（五号），线宽 0.5 磅，全部按真实尺寸绘制，Word 里请保持 100% 大小。
  * 字体请用简体中文字形（Windows 宋体 simsun.ttc）。可用 --font 指定，或设环境变量 FONT_PATH。
  * 整体 E-R 图较宽时，可用 --page-width 6.3 让布局尽量收在竖版正文宽度内。
"""
import argparse
from collections import Counter
import concurrent.futures
import heapq
from http.client import HTTPException as HTTPClientError
from http.client import IncompleteRead
from io import BytesIO
import itertools
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
from urllib.parse import urlsplit
import urllib.request

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import Ellipse, Polygon, Rectangle

# ============================== 全局样式 ==============================
FONT_SIZE = 10.5      # 五号
LINE_W = 0.5          # 线宽（磅）
DPI = 300
FP = None             # FontProperties，由 init_font 设置
_fig0 = None
_renderer = None

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\simsun.ttc",                                   # Windows 宋体
    "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",                  # macOS 宋体-简
    "/Library/Fonts/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",        # Linux 思源宋体
    "/usr/share/fonts/opentype/noto/NotoSerifCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSerifCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def find_font(cli_path=None):
    if cli_path and os.path.exists(cli_path):
        return cli_path
    env = os.environ.get("FONT_PATH")
    if env and os.path.exists(env):
        return env
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    sys.exit("没有找到中文字体文件，请用 --font \"字体文件路径\" 指定（推荐宋体 simsun.ttc）")


def init_font(cli_path=None):
    """加载字体。.ttc 合集里优先选"简体中文(SC)"字形，避免出现日文字形。"""
    global FP, _fig0, _renderer
    path = find_font(cli_path)
    fm.fontManager.addfont(path)
    FP = None
    if path.lower().endswith((".ttc", ".otc")):
        names = sorted({f.name for f in fm.fontManager.ttflist if f.fname == path})
        sc = [n for n in names if n.endswith(" SC") or "Simplified" in n or "简" in n]
        if sc:
            FP = fm.FontProperties(family=sc[0], size=FONT_SIZE)
    if FP is None:
        FP = fm.FontProperties(fname=path, size=FONT_SIZE)
    print("使用字体：", path)
    _fig0 = plt.figure(figsize=(1, 1), dpi=DPI)
    _renderer = _fig0.canvas.get_renderer()


def text_size(s):
    """文字宽高（英寸）。"""
    t = _fig0.text(0, 0, s, fontproperties=FP)
    bounds = t.get_window_extent(_renderer)
    t.remove()
    return bounds.width / DPI, bounds.height / DPI


def tw(s):
    return text_size(s)[0]


# ============================== 规格校验 ==============================
class SpecError(ValueError):
    pass


class SpecSizeError(SpecError):
    pass


class SpecConnectivityError(SpecError):
    pass


def isolated_entity_names(model):
    touched = {entity for relation in model["rels"] if not relation["self"]
               for entity, _ in relation["ends"]}
    return [entity["name"] for i, entity in enumerate(model["ents"]) if i not in touched]


def _split_card(c):
    if isinstance(c, str):
        c = [x for x in re.split(r"[:：\-—,，/\s]+", c.strip()) if x]
    if not isinstance(c, (list, tuple)):
        raise SpecError("card 必须是列表或以分隔符连接的字符串")
    return [str(x).strip().lower().replace("*", "n").replace("∞", "n") for x in c]


def spec_list(obj, key):
    values = obj.get(key, [])
    if not isinstance(values, list):
        raise SpecError(f"{key} 必须是列表")
    return values


def normalize_spec(spec, *, report_isolated=True):
    """校验并规范化 JSON 规格。出错抛 SpecError（错误信息可直接反馈给大模型重试）。"""
    if not isinstance(spec, dict):
        raise SpecError("顶层必须是 JSON 对象")
    ents_in = spec.get("entities")
    if not ents_in or not isinstance(ents_in, list):
        raise SpecError("缺少 entities 列表")
    ents, index = [], {}
    for e in ents_in:
        name = str(e.get("name", "")).strip() if isinstance(e, dict) else ""
        if not name:
            raise SpecError("存在没有 name 的实体")
        if name in index:
            raise SpecError("实体名重复：" + name)
        attrs, seen = [], set()
        for a in spec_list(e, "attrs"):
            if isinstance(a, dict):
                an, pk = str(a.get("name", "")).strip(), bool(a.get("pk"))
            else:
                an = str(a).strip()
                pk = an.startswith("*")
                an = an.lstrip("*").strip()
            if not an or an in seen:
                continue
            seen.add(an)
            attrs.append((an, pk))
        if not any(pk for _, pk in attrs):               # 没有主键就补一个
            key_name = name + "ID"
            if len(key_name) > 24:
                key_name = "ID"
            base = key_name
            suffix = 2
            while key_name in seen:
                suffix_text = str(suffix)
                key_name = base[:24 - len(suffix_text)] + suffix_text
                suffix += 1
            attrs.insert(0, (key_name, True))
        else:                                            # 主键排最前
            attrs.sort(key=lambda t: not t[1])
        index[name] = len(ents)
        ents.append(dict(name=name, attrs=attrs))

    rels = []
    for r in spec_list(spec, "relations"):
        if not isinstance(r, dict):
            raise SpecError("每条联系必须是对象")
        names = spec_list(r, "entities") if r.get("entities") is not None else []
        names = names or [r.get("a"), r.get("b")] + ([r["c"]] if r.get("c") else [])
        names = [str(x).strip() if x else "" for x in names]
        rname = str(r.get("name", "")).strip() or "关联"
        for x in names:
            if x not in index:
                raise SpecError("联系“%s”引用了不存在的实体：%r" % (rname, x))
        if len(names) not in (2, 3):
            raise SpecError("联系“%s”必须连接 2 个（或 3 个）实体" % rname)
        if len(names) == 3 and len(set(names)) < 3:
            raise SpecError("三元联系“%s”的三个实体必须互不相同" % rname)
        card = _split_card(r.get("card", ["1", "n"] if len(names) == 2 else ["m", "n", "p"]))
        if len(card) != len(names):
            raise SpecError("联系“%s”的 card 个数（%d）与实体个数（%d）不一致" % (rname, len(card), len(names)))
        rattrs = []
        for a in spec_list(r, "attrs"):
            a = str(a).strip().lstrip("*")
            if a and a not in rattrs:
                rattrs.append(a)
        ends = [(index[x], c) for x, c in zip(names, card)]
        rels.append(dict(name=rname, ends=ends, attrs=rattrs,
                         self=(len(ends) == 2 and ends[0][0] == ends[1][0])))
    # 同一对实体之间的多个联系：编号，后面错开画
    groups = {}
    for r in rels:
        key = tuple(sorted(e for e, _ in r["ends"]))
        groups.setdefault(key, []).append(r)
    for g in groups.values():
        for k, r in enumerate(g):
            r["par_k"], r["par_n"] = k, len(g)
    model = dict(title=str(spec.get("title", "")).strip(), ents=ents, rels=rels)
    if report_isolated and len(ents) > 1:
        lonely = isolated_entity_names(model)
        if lonely:
            print("提示：以下实体未连接其他实体，将单独画出：", "、".join(lonely))
    return model


# ============================== 大模型：自然语言 → 规格 ==============================
SYSTEM_PROMPT = """你是数据库概念结构设计专家。用户会用自然语言描述一个课题或系统，请据此设计其 E-R 模型。
【只输出一个 JSON 对象】，不要解释，不要 Markdown 代码块。格式：
{
  "title": "系统名称",
  "entities": [ {"name": "实体名", "attrs": ["*主键ID", "属性1", "属性2"]} ],
  "relations": [ {"name": "联系名", "a": "实体A", "b": "实体B", "card": ["1", "n"], "attrs": []} ]
}
设计规则：
1. 实体用名词，根据需求确定数量，简单需求只保留必要实体。名称宜简短。
2. 每个实体 3~7 个属性，属性名简短（不超过 6 个字）、不重复；每个实体有且仅有一个主键，用 * 开头并放在第一位（如 "*学生ID"）。
3. 不要把外键写进实体属性，实体之间的关系用 relations 表达。
4. 联系名用动词或动宾短语（不超过 3 个字，如 包含、借阅、产生）。card 是 [a 端基数, b 端基数]：
   一对多写 ["1","n"]（“1”的一方放在 a），多对多写 ["m","n"]，一对一写 ["1","1"]。
5. 描述一次联系的属性（如 借阅日期、归还日期、成绩）写进该联系的 attrs。
6. 自联系的 a 与 b 填同一个实体；三元联系用 entities 列出三个不同实体，card 按相同顺序列出三个基数。
7. 只添加业务中有依据的联系。单实体需求允许 relations 为空。
8. 用户明确给出的实体、属性、联系必须保留；缺失部分按常识补全，并保证合理。
9. 名称一律用中文（ID 可用英文）。
示例（仅示意格式）：
{"title":"选课系统","entities":[{"name":"学生","attrs":["*学生ID","姓名","专业"]},{"name":"课程","attrs":["*课程ID","课程名","学分"]}],
 "relations":[{"name":"选修","a":"学生","b":"课程","card":["m","n"],"attrs":["成绩","选课时间"]}]}"""


def extract_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        raise SpecError("回复中没有 JSON 对象")
    try:
        return json.loads(text[i:j + 1])
    except (ValueError, RecursionError) as e:
        raise SpecError("JSON 解析失败：%s" % e)


class LLMError(RuntimeError):
    pass


class LLMConfigurationError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMConnectionClosedError(LLMError):
    pass


class LLMStreamInterruptedError(LLMConnectionClosedError):
    def __init__(self, message, partial=""):
        super().__init__(message)
        self.partial = partial


class LLMUpstreamUnavailableError(LLMError):
    pass


SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
SILICONFLOW_RESUME_LIMIT = 12
SILICONFLOW_PAGE_LIMIT = 24


def _complete_spec_json(text, *, relations_only=False):
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.I | re.S)
    try:
        document = json.loads(fenced[1] if fenced else text)
    except (ValueError, RecursionError):
        return None
    if isinstance(document, dict) and (isinstance(document.get("entities"), list)
            or (relations_only and "entities" not in document and isinstance(document.get("relations"), list))):
        return document
    return None


def _json_array_checkpoints(text, *, compact=False):
    """Yield JSON prefixes ending at a complete record, with their missing closing delimiters."""
    start = text.find("{")
    if start < 0:
        return
    text = text[start:start + 32_768]
    stack, checkpoints = [], []
    quoted = escaped = False
    for i, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
                if compact and stack == ["{", "["]:
                    checkpoints.append((i + 1, "]}"))
        elif char == '"':
            quoted = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack or (stack.pop(), char) not in (("{", "}"), ("[", "]")):
                break
            if (char == "}" or compact) and stack == ["{", "["]:
                checkpoints.append((i + 1, "]}"))
            elif char == "]" and stack == ["{"]:
                checkpoints.append((i + 1, "}"))
    for end, closing in reversed(checkpoints):
        yield text[:end], closing


def _spec_checkpoint(text):
    """只保留截至顶层数组中最后一个完整对象的前缀。"""
    for candidate, closing in _json_array_checkpoints(text):
        document = _complete_spec_json(candidate + closing)
        if (document is not None and document["entities"]
                and isinstance(document.get("relations", []), list)):
            return candidate, document
    return None


def _preserves_spec_checkpoint(document, saved, *, array_keys=("entities", "relations")):
    for key, old in saved.items():
        new = document.get(key)
        if key in array_keys and isinstance(old, list):
            if not isinstance(new, list) or new[:len(old)] != old:
                return False
        elif key not in document or new != old:
            return False
    return True


def _read_spec_page(text, key):
    """读取逐条 JSON，兼容模型返回的数组或带阶段字段的 JSON 对象。"""
    records = []
    decoder = json.JSONDecoder()
    text = re.sub(r"(?im)^\s*```(?:jsonl?)?[^\S\r\n]*$", "", text).strip()
    while text:
        try:
            item, end = decoder.raw_decode(text)
        except (ValueError, RecursionError):
            # 分批回复也可能在数组中途断开，保留已完整收到的对象。
            array_start = re.match(rf'^(?:\{{\s*"{key}"\s*:\s*)?\[\s*', text)
            if array_start:
                remainder = text[array_start.end():]
                while remainder:
                    try:
                        item, end = decoder.raw_decode(remainder)
                    except (ValueError, RecursionError):
                        break
                    records.append(item)
                    remainder = remainder[end:].lstrip()
                    if not remainder.startswith(","):
                        break
                    remainder = remainder[1:].lstrip()
            break
        text = text[end:].lstrip()
        if isinstance(item, list):
            records.extend(item)
        elif isinstance(item, dict):
            if item.keys() == {"done"}:
                return records, item["done"] is True and not text
            if isinstance(item.get(key), list) and item.keys() <= {key, "done"}:
                records.extend(item[key])
                if item.get("done") is True:
                    return records, not text
            else:
                records.append(item)
        else:
            break
    return records, False


def _merge_spec_page(spec, key, records, validate):
    def identity(record):
        if key == "entities":
            return record["name"]
        return record["name"], tuple(sorted(record["ends"])), tuple(record["attrs"])

    normalized_key = "ents" if key == "entities" else "rels"
    known = {identity(item) for item in normalize_spec(spec, report_isolated=False)[normalized_key]}
    fields = {"name", "attrs"} if key == "entities" else {"name", "attrs", "a", "b", "c", "entities", "card"}
    added = 0
    valid = True
    for record in records:
        name = record.get("name") if isinstance(record, dict) else None
        if not isinstance(name, str) or not name.strip() or record.keys() - fields:
            valid = False
            continue
        if key == "entities" and name.strip() in known:
            continue  # 已提交实体保留原有属性。
        candidate = {**spec, key: [*spec[key], record]}
        try:
            normalized = normalize_spec(candidate, report_isolated=False)
            marker = identity(normalized[normalized_key][-1])
            if marker not in known and validate is not None:
                validate(normalized)
        except SpecError:
            valid = False
            continue
        if marker not in known:
            known.add(marker)
            spec[key].append(record)
            added += 1
    return added, valid


def _read_siliconflow_stream(response, deadline, usage=None):
    limit = 8 * 1024 * 1024
    read_bytes = 0
    event, chunks = [], []
    trace = response.headers.get("x-siliconcloud-trace-id", "")
    trace_note = f"，追踪 ID {trace}" if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", trace) else ""
    packets = 0
    text_length = 0
    finished = None

    def result():
        if finished == "length" and chunks:
            raise interrupted()
        if not chunks:
            raise LLMError("大模型接口未返回可用文本")
        return {"choices": [{"message": {"content": "".join(chunks)}}]}

    def interrupted():
        detail = f"已收到 {packets} 个事件、{text_length} 个正文字符{trace_note}"
        return LLMStreamInterruptedError(f"模型流式连接提前关闭（{detail}）", "".join(chunks))

    while time.monotonic() < deadline:
        try:
            line = response.readline(limit - read_bytes + 1)
        except (ConnectionResetError, ConnectionAbortedError, IncompleteRead):
            line = b""
        except TimeoutError:
            if finished:
                return result()
            if chunks:
                raise interrupted() from None
            raise
        if not line:
            if finished:
                return result()
            if chunks and not event and _complete_spec_json("".join(chunks), relations_only=True) is not None:
                print(f"模型流未发送结束标记，收到的完整 JSON 已交给规格校验{trace_note}。", flush=True)
                return result()
            raise interrupted()
        read_bytes += len(line)
        if read_bytes > limit:
            raise LLMError("大模型接口的响应过大")
        line = line.rstrip(b"\r\n")
        if line.startswith(b"data:"):
            event.append(line[5:].removeprefix(b" "))
        elif not line and event:
            raise interrupted()
        else:
            continue
        payload = b"\n".join(event)
        if payload.strip() == b"[DONE]":
            return result()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue  # 一个 SSE 事件也可能包含多行 data。
        event.clear()
        packets += 1
        if not isinstance(data, dict) or data.get("error"):
            raise LLMError("模型服务在流式生成时返回错误")
        if usage is not None and isinstance(data.get("usage"), dict):
            usage.update(data["usage"])
            if finished and usage:
                return result()
        choices = data.get("choices")
        if not choices:
            continue
        if not isinstance(choices, list) or not isinstance(choices[0], dict):
            raise LLMError("模型流式响应格式异常")
        choice = choices[0]
        delta = choice.get("delta") or {}
        content = delta.get("content") if isinstance(delta, dict) else None
        if isinstance(content, str) and content:
            chunks.append(content)
            text_length += len(content)
        finish_reason = choice.get("finish_reason")
        if finish_reason in ("stop", "length"):
            finished = finish_reason
            if usage is None or usage:
                return result()
        elif finish_reason:
            raise LLMError(f"模型提前结束生成，未返回完整的 E-R 规格{trace_note}")
    if finished:
        return result()
    if chunks:
        raise interrupted()
    raise LLMTimeoutError("已达到模型生成等待上限，请稍后重试")


def _http_json(url, headers, body, timeout=180, *, stream=None, on_usage=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    usage = {} if on_usage is not None else None
    try:
        deadline = time.monotonic() + timeout if stream else math.inf
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if stream and getattr(resp, "headers", {}).get("Content-Type", "").lower().startswith("text/event-stream"):
                return _read_siliconflow_stream(resp, deadline, usage)
            limit = 1024 * 1024
            payload = resp.read(limit + 1)
            if len(payload) > limit:
                raise LLMError("大模型接口的响应过大")
            data = json.loads(payload)
            if usage is not None and isinstance(data, dict) and isinstance(data.get("usage"), dict):
                usage.update(data["usage"])
            return data
    except urllib.error.HTTPError as e:
        e.close()
        if stream is not None and e.code in (502, 503, 504):
            raise LLMUpstreamUnavailableError(f"大模型服务暂时不可用（HTTP {e.code}）") from None
        raise LLMError(f"大模型接口返回错误（HTTP {e.code}）") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, (ConnectionResetError, ConnectionAbortedError)):
            raise LLMConnectionClosedError(f"模型连接提前关闭（{type(e.reason).__name__}）") from None
        if isinstance(e.reason, TimeoutError):
            raise LLMTimeoutError(f"等待大模型响应超过 {timeout:.0f} 秒，请稍后重试") from None
        raise LLMError("无法连接大模型接口") from None
    except (ConnectionResetError, ConnectionAbortedError, IncompleteRead) as error:
        raise LLMConnectionClosedError(f"模型连接提前关闭（{type(error).__name__}）") from None
    except TimeoutError:
        raise LLMTimeoutError(f"等待大模型响应超过 {timeout:.0f} 秒，请稍后重试") from None
    except (ValueError, RecursionError):
        raise LLMError("大模型接口返回了无效 JSON") from None
    except (OSError, HTTPClientError) as error:
        kind = type(error).__name__
        code = getattr(error, "winerror", None) or getattr(error, "errno", None)
        if isinstance(code, int):
            kind = f"{kind} {code}"
        raise LLMError(f"与大模型接口通信失败（{kind}）") from None
    finally:
        if on_usage is not None:
            on_usage(usage)


def llm_chat(messages, provider, model, api_key, base_url, *, timeout=180, system_prompt=SYSTEM_PROMPT,
             stream=True, on_usage=None):
    if provider == "anthropic":
        url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        data = _http_json(url, {"content-type": "application/json", "x-api-key": api_key,
                                "anthropic-version": "2023-06-01"},
                          {"model": model, "max_tokens": 4096, "system": system_prompt, "messages": messages},
                          timeout=timeout, on_usage=on_usage)
        try:
            return "".join(block.get("text", "") for block in data["content"])
        except (KeyError, TypeError, AttributeError):
            raise LLMError("大模型接口未返回可用文本") from None
    endpoint = (base_url or "https://api.openai.com/v1").rstrip("/")
    url = endpoint + "/chat/completions"
    body = {"model": model, "temperature": 0.2,
            "messages": [{"role": "system", "content": system_prompt}] + messages}
    siliconflow = endpoint == SILICONFLOW_BASE_URL
    headers = {"content-type": "application/json", "Authorization": "Bearer " + api_key}
    if siliconflow:
        body["stream"] = stream
        headers["Accept"] = "text/event-stream" if stream else "application/json"
        if model == "deepseek-ai/DeepSeek-V4.1-Flash":
            body["enable_thinking"] = False
    data = _http_json(url, headers, body, timeout=timeout, stream=stream if siliconflow else None,
                      on_usage=on_usage)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("大模型接口未返回可用文本") from None
    if not isinstance(content, str):
        raise LLMError("大模型接口未返回可用文本")
    return content


def llm_settings(args=None):
    provider = getattr(args, "provider", None) or os.environ.get("LLM_PROVIDER")
    key = getattr(args, "api_key", None)
    if not provider:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            raise LLMConfigurationError("没有配置大模型 API。请设置 ANTHROPIC_API_KEY 或 LLM_API_KEY。"
                                        "也可以用 --prompt-only 获取提示词，再用 --spec 出图。")
    if provider not in ("anthropic", "openai"):
        raise LLMConfigurationError("LLM_PROVIDER 须为 anthropic 或 openai")
    if not key:
        key = (os.environ.get("ANTHROPIC_API_KEY") if provider == "anthropic"
               else os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    if not key:
        raise LLMConfigurationError("缺少 API Key（--api-key 或环境变量）")
    model = (getattr(args, "model", None) or os.environ.get("LLM_MODEL")
             or ("claude-sonnet-5-5" if provider == "anthropic" and args is not None else None))
    if not model:
        raise LLMConfigurationError("请通过 LLM_MODEL 或 --model 指定大模型")
    base_url = getattr(args, "base_url", None) or os.environ.get("LLM_BASE_URL")
    if base_url:
        try:
            endpoint = urlsplit(base_url)
            if endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username is not None:
                raise ValueError
        except ValueError:
            raise LLMConfigurationError("LLM_BASE_URL 须为有效的 HTTP 或 HTTPS 地址") from None

    return provider, model, key, base_url


def spec_from_text(text, args=None, retries=2, *, timeout=180, total_timeout=None,
                   validate=None, validate_final=None, retry_disconnect=False, generation_rules="", on_usage=None,
                   entity_limit=None, relation_limit=None):
    provider, model, key, base_url = llm_settings(args)
    user_message = "请为下面的课题设计 E-R 模型：\n\n" + text
    messages = [{"role": "user", "content": user_message}]
    system_prompt = SYSTEM_PROMPT + "\n\n" + generation_rules if generation_rules else SYSTEM_PROMPT
    if total_timeout is None:
        total_timeout = timeout * (retries + 1) if retry_disconnect else math.inf
    deadline = time.monotonic() + total_timeout
    siliconflow = provider == "openai" and (base_url or "").rstrip("/") == SILICONFLOW_BASE_URL
    recover_siliconflow = retry_disconnect and siliconflow
    resume_budget = SILICONFLOW_RESUME_LIMIT if recover_siliconflow else 0
    pages_left = SILICONFLOW_PAGE_LIMIT

    def request_model(request_messages=None, prompt=system_prompt, *, max_wait=timeout, stream=True):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LLMTimeoutError("已达到生成等待上限，请稍后重试")
        return llm_chat(messages if request_messages is None else request_messages, provider, model, key, base_url,
                        timeout=min(timeout, max_wait, remaining), system_prompt=prompt, stream=stream, on_usage=on_usage)

    def complete_by_pages(snapshot):
        nonlocal pages_left
        spec = {**snapshot, "entities": list(snapshot["entities"]), "relations": list(snapshot.get("relations", []))}
        try:
            normalized = normalize_spec(spec, report_isolated=False)
            if validate is not None:
                validate(normalized)
        except SpecError as error:
            raise LLMError(f"已收到的记录无法作为分批补全的基础：{error}") from None
        prompt = (system_prompt + "\n本轮使用逐行 JSON，覆盖上面的单对象和不换行要求。"
                  "根据原始需求核对已提交的规格，只补充当前阶段缺失的记录，不重写已有内容。"
                  "每行只输出一个实体或联系对象，不加外层数组、说明或 Markdown。"
                  "联系仅使用已提交的实体名。按本轮条数限制输出，并尽量控制在 350 字以内。"
                  '当前阶段全部补齐或无需新增时，在最后单独一行输出 {"done":true}；'
                  '若还有遗漏则输出 {"done":false}。')
        print("原格式续写停滞，正在切换到分批补全规格……", flush=True)
        streaming_pages = True
        for key, limit, batch_size, example in (
            ("entities", entity_limit, 3, '{"name":"实体名","attrs":["*编号","名称"]}'),
            ("relations", relation_limit, 4, '{"name":"联系名","entities":["实体甲","实体乙"],"card":["1","n"],"attrs":[]}'),
        ):
            fields = list(snapshot)
            if key == "entities" and "relations" in fields and fields.index("entities") < fields.index("relations"):
                print("续写已进入联系数组，保留实体并继续补全联系。", flush=True)
                continue
            stalled = 0
            while True:
                remaining_slots = limit - len(spec[key]) if limit is not None else batch_size
                if remaining_slots <= 0:
                    print(f"分批补全阶段 {key} 已达到 {limit} 条上限，停止追加本阶段记录。", flush=True)
                    streaming_pages = False
                    break
                if deadline - time.monotonic() <= 1:
                    raise LLMTimeoutError("分批补全达到生成等待上限，请稍后重试") from None
                if not pages_left:
                    raise LLMConnectionClosedError("达到分批补全次数上限，请稍后重试") from None
                pages_left -= 1
                page_prompt = prompt + "\n当前阶段的单条记录格式示例：" + example
                if key == "entities":
                    page_prompt += "\n本阶段只补实体，关系、业务动作和基数留给联系阶段。"
                else:
                    page_prompt += "\n实体列表已确定。本阶段只补联系，不能新增实体。"
                if stalled:
                    page_prompt += ("\n上次没有新增可用记录。只找一条尚未提交且符合原始需求的记录。"
                                    '如果该阶段已齐，只输出 {"done":true}。')
                if stalled == 2:
                    page_prompt += (f'\n本次覆盖逐行格式，改用一个紧凑 JSON 对象，格式为 '
                                    f'{{"{key}":[{example}],"done":false}}。阶段已齐时将 done 设为 true。')
                page_stream = streaming_pages
                if stalled == 2:
                    page_stream = not streaming_pages
                    mode = "流式" if page_stream else "一次返回"
                    print(f"分批补全改用{mode}响应，尝试补一条记录。", flush=True)
                page_context = {"需求对话": messages, "当前阶段": key,
                                "本轮最多新增": min(remaining_slots, 1 if stalled else batch_size), "已提交规格": spec}
                if key == "entities":
                    page_context["禁止重复的已有名称"] = [item.get("name") for item in spec[key]]
                context = json.dumps(page_context, ensure_ascii=False)
                try:
                    reply = request_model([{"role": "user", "content": context}], page_prompt,
                                          max_wait=18, stream=page_stream)
                except LLMStreamInterruptedError as interrupted:
                    reply = interrupted.partial
                    print(str(interrupted), flush=True)
                except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError) as transient:
                    reply = ""
                    print(str(transient), flush=True)
                records, done = _read_spec_page(reply, key)
                added, valid = _merge_spec_page(spec, key, records, validate)
                if added or (done and valid):
                    streaming_pages = page_stream
                if added:
                    print(f"分批补全已合并 {added} 条{('实体' if key == 'entities' else '联系')}记录。", flush=True)
                if done and valid:
                    break
                stalled = 0 if added else stalled + 1
                if stalled:
                    print(f"分批补全阶段 {key} 未新增记录（解析到 {len(records)} 条，连续 {stalled} 次）。", flush=True)
                if stalled >= 3:
                    # 重复记录不代表阶段已完成。用独立、短小且必须完整的审核响应确认，
                    # 避免 done 标记总在长回复末尾被截断，也不把断流当成完成。
                    audit_issue = "未收到可用的新记录"
                    if pages_left and deadline - time.monotonic() > 1:
                        pages_left -= 1
                        audit_prompt = ("只审核当前阶段是否已覆盖原始需求。不要输出完整规格或记录。"
                                        '只返回一个完整的紧凑 JSON：{"done":true,"missing":[]}；'
                                        '如果还有遗漏，返回 {"done":false,"missing":["遗漏的名称"]}。'
                                        "已有名称不算遗漏，不得为了继续补全而编造额外业务。")
                        if key == "entities":
                            audit_prompt += ("当前只查缺少的实体名称。已有实体之间的联系、动作和基数留给下一阶段。"
                                             '如果只缺联系，此阶段返回 {"done":true,"missing":[]}。')
                        else:
                            audit_prompt += "当前只查已有实体之间遗漏的联系；不能新增实体。"
                        print("重复补全未取得进展，正在单独核对该阶段是否已完成……", flush=True)
                        try:
                            audit_reply = request_model([{"role": "user", "content": context}],
                                                        audit_prompt, max_wait=12, stream=False)
                            fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", audit_reply.strip(), re.I | re.S)
                            audit = json.loads(fenced[1] if fenced else audit_reply)
                        except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError) as error:
                            audit_issue = f"阶段核对请求未完成：{error}"
                            audit = None
                        except (ValueError, RecursionError):
                            audit_issue = "阶段核对未返回完整 JSON"
                            audit = None
                        if (isinstance(audit, dict) and audit.get("done") is True
                                and audit.get("missing") == []):
                            print(f"已确认 {key} 阶段无需新增，继续后续校验。", flush=True)
                            break
                        missing = audit.get("missing") if isinstance(audit, dict) and audit.get("done") is False else None
                        if isinstance(missing, list) and missing and all(isinstance(name, str) and name.strip() for name in missing):
                            existing = {item["name"].strip() for item in spec[key]}
                            targets = [name.strip() for name in missing if key != "entities" or name.strip() not in existing]
                            audit_issue = "阶段核对指出仍有遗漏，但未补到有效记录"
                            if targets and pages_left and deadline - time.monotonic() > 1:
                                target = targets[0]
                                pages_left -= 1
                                print(f"阶段核对发现缺少「{target}」，正在定向补全……", flush=True)
                                targeted_context = json.dumps({**page_context, "本轮最多新增": 1,
                                                               "指定补全名称": target}, ensure_ascii=False)
                                targeted_prompt = (prompt + f'\n本轮只补指定名称的一条记录。返回 {{"{key}":[{example}]}}。'
                                                   "若原始需求不支持这条记录，返回空数组。")
                                try:
                                    targeted_reply = request_model([{"role": "user", "content": targeted_context}],
                                                                   targeted_prompt, max_wait=12, stream=False)
                                    new_records, _ = _read_spec_page(targeted_reply, key)
                                    named_records = (record for record in new_records if isinstance(record, dict)
                                                     and isinstance(record.get("name"), str) and record["name"].strip() == target)
                                    added, _ = _merge_spec_page(spec, key, itertools.islice(named_records, 1), validate)
                                    if added:
                                        stalled = 0
                                        streaming_pages = False
                                        continue
                                except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError) as error:
                                    audit_issue = f"定向补全请求未完成：{error}"
                    raise LLMConnectionClosedError(
                        f"分批补全在{'实体' if key == 'entities' else '联系'}阶段未完成：{audit_issue}"
                    ) from None
        return json.dumps(spec, ensure_ascii=False)

    def resume_reply(error):
        nonlocal resume_budget
        if not resume_budget:
            return None
        saved = _spec_checkpoint(error.partial) if isinstance(error, LLMStreamInterruptedError) else None
        if saved is None:
            return None
        prefix, snapshot = saved
        if entity_limit is not None and len(snapshot["entities"]) == entity_limit and "relations" not in snapshot:
            return complete_by_pages(snapshot)
        resume_prompt = ("你在续写一个中断的 E-R 规格 JSON。参考原始设计规则：\n" + system_prompt
                         + "\n本轮的输出格式覆盖上面的初次生成要求。只输出给定 JSON 前缀之后缺少的字符。"
                         "保留所有已经完成的对象，不要重复前缀、重新开始 JSON 或加 Markdown。"
                         "用紧凑 JSON 补全原需求中的其余实体和联系，并确保合并后有完整的 entities 与 relations 数组。")
        stalled = 0
        # 为小批量请求保留等待时间，避免长续写耗尽整个预算。
        while resume_budget and deadline - time.monotonic() > 24:
            attempt = SILICONFLOW_RESUME_LIMIT - resume_budget + 1
            resume_budget -= 1
            print(f"模型流断开，正在从已收到的 {len(prefix)} 字继续生成（第 {attempt} 次）……", flush=True)
            context = json.dumps({"需求对话": messages, "已完成的 JSON 前缀": prefix}, ensure_ascii=False)
            try:
                suffix = request_model([{"role": "user", "content": context}], resume_prompt, max_wait=18)
            except LLMStreamInterruptedError as interrupted:
                suffix = interrupted.partial
                print(str(interrupted), flush=True)
            except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError) as transient:
                suffix = ""
                print(str(transient), flush=True)
            suffix = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", suffix, flags=re.I)
            combined = suffix if suffix.startswith(prefix) else prefix + suffix
            # 有时模型会换一种缩进重发整个规格。只有原有记录逐项一致才可接收。
            for reply in (combined, suffix):
                document = _complete_spec_json(reply)
                if (document is not None and isinstance(document.get("relations"), list)
                        and _preserves_spec_checkpoint(document, snapshot)):
                    return reply
            checkpoint = _spec_checkpoint(combined)
            if (checkpoint is None or len(checkpoint[0]) <= len(prefix)
                    or not _preserves_spec_checkpoint(checkpoint[1], snapshot)):
                checkpoint = _spec_checkpoint(suffix)
                if (checkpoint is not None and (not _preserves_spec_checkpoint(checkpoint[1], snapshot)
                        or not any(len(checkpoint[1].get(key, [])) > len(snapshot.get(key, []))
                                   for key in ("entities", "relations")))):
                    checkpoint = None
            if checkpoint is not None:
                prefix, snapshot = checkpoint
                if entity_limit is not None and len(snapshot["entities"]) == entity_limit and "relations" not in snapshot:
                    return complete_by_pages(snapshot)
                stalled = 0
            else:
                stalled += 1
                print(f"本次续写没有新增完整记录，已保留原进度（连续 {stalled} 次）。", flush=True)
                if stalled >= 2:
                    return complete_by_pages(snapshot)
        if deadline - time.monotonic() <= 1:
            raise LLMTimeoutError("续写达到生成等待上限，未能补全规格，请稍后重试") from None
        return complete_by_pages(snapshot)

    def request_with_recovery():
        nonlocal retry_disconnect
        print("正在请求大模型（%s / %s）……" % (provider, model))
        try:
            # 硅基流动首次请求预留一部分时间给同入口重试和断流恢复。
            return request_model(max_wait=timeout * 5 / 6 if siliconflow and retry_disconnect else timeout)
        except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError) as first_error:
            if isinstance(first_error, LLMStreamInterruptedError):
                resumed = resume_reply(first_error)
                if resumed is not None:
                    return resumed
            if not siliconflow and not isinstance(first_error, LLMConnectionClosedError):
                raise
            if not retry_disconnect or deadline - time.monotonic() <= 1:
                raise
            retry_disconnect = False
            retry_without_stream = (siliconflow and isinstance(first_error, LLMConnectionClosedError)
                                    and not isinstance(first_error, LLMStreamInterruptedError))
            if siliconflow:
                mode = "改用非流式响应重试" if retry_without_stream else "重试一次"
                print(f"硅基流动请求未完成（{first_error}），正在同一入口{mode}……", flush=True)
            else:
                print("模型连接提前关闭，正在重新连接一次……", flush=True)
                time.sleep(1)
            try:
                return request_model(stream=not retry_without_stream)
            except LLMStreamInterruptedError as interrupted:
                resumed = resume_reply(interrupted)
                if resumed is not None:
                    return resumed
                raise
            except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError) as retry_error:
                if retry_without_stream:
                    raise type(retry_error)(f"硅基流动的流式和非流式请求均未完成。最后一次错误：{retry_error}") from None
                raise

    def validate_repair_links(normalized, start, names):
        for relation in normalized["rels"][start:]:
            if relation["self"] or not any(normalized["ents"][i]["name"] in names
                                           for i, _ in relation["ends"]):
                raise SpecConnectivityError("新增联系须涉及至少一个原先未接入的实体，并连接到其他实体")

    def recover_repair(base, names, interrupted):
        original = spec_list(base, "relations")
        working = {**base, "relations": list(original)}

        def accept(normalized):
            validate_repair_links(normalized, len(original), names)
            if validate is not None:
                validate(normalized)

        def merge(reply):
            records, _ = _read_spec_page(reply, "relations")
            _merge_spec_page(working, "relations", records, accept)

        if isinstance(interrupted, LLMStreamInterruptedError):
            merge(interrupted.partial)
        for _ in range(5):
            pending = isolated_entity_names(normalize_spec(working, report_isolated=False))
            if not pending:
                return json.dumps({"relations": working["relations"][len(original):]}, ensure_ascii=False)
            if deadline - time.monotonic() <= 1:
                break
            target = pending[0]
            print(f"联系修正请求中断，保留完整记录，正在单独补全「{target}」……", flush=True)
            context = json.dumps({"原需求": text, "待连接实体": target, "当前规格": working}, ensure_ascii=False)
            prompt = ('只依据原需求，为待连接实体补一条连接到其他已有实体的联系。'
                      '不要改写已有规格。只返回紧凑 JSON：{"relations":[新增的一条联系]}。'
                      '联系包含 name、entities、card 和可选 attrs。无业务依据时返回空数组。')
            try:
                patch_reply = request_model([{"role": "user", "content": context}], prompt,
                                            max_wait=12, stream=False)
            except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError):
                break
            before = len(working["relations"])
            merge(patch_reply)
            if len(working["relations"]) == before:
                break
        pending = isolated_entity_names(normalize_spec(working, report_isolated=False))
        if not pending:
            return json.dumps({"relations": working["relations"][len(original):]}, ensure_ascii=False)
        remaining = "、".join(f"「{name}」" for name in pending)
        raise LLMError(f"仍未补全以下实体的联系：{remaining}。{interrupted}") from None

    validation_error = None
    repair_base = None
    repair_names = set()
    for attempt in range(retries + 1):
        try:
            if repair_base is not None and recover_siliconflow:
                try:
                    reply = request_model(max_wait=18)
                except (LLMConnectionClosedError, LLMTimeoutError, LLMUpstreamUnavailableError) as interrupted:
                    reply = recover_repair(repair_base, repair_names, interrupted)
            else:
                reply = request_with_recovery()
        except LLMError as error:
            if validation_error is None:
                raise
            raise type(error)(f"模型规格未通过校验：{validation_error}。修正请求失败：{error}") from None
        try:
            raw = extract_json(reply)
            if repair_base is not None:
                if not isinstance(raw, dict) or raw.keys() != {"relations"}:
                    raise SpecConnectivityError("补全结果须只包含新增联系")
                original_relations = spec_list(repair_base, "relations")
                raw = {**repair_base, "relations": [*original_relations, *spec_list(raw, "relations")]}
            normalized = normalize_spec(raw, report_isolated=validate_final is None)
            if repair_base is not None:
                validate_repair_links(normalized, len(original_relations), repair_names)
            if validate is not None:
                validate(normalized)
            if validate_final is not None:
                validate_final(normalized)
            return normalized, raw
        except SpecError as e:
            validation_error = str(e)
            print("模型输出有问题：%s" % e)
            if attempt == retries:
                if isinstance(e, SpecSizeError):
                    raise LLMError(f"模型生成的规格超出绘图上限：{e}。请描述需要优先绘制的业务范围。") from None
                if isinstance(e, SpecConnectivityError) or repair_base is not None:
                    names = "、".join(sorted(repair_names))
                    detail = f"模型未能补全实体「{names}」的联系：{e}" if names else str(e)
                    raise LLMError(detail) from None
                raise LLMError("大模型未生成有效的 E-R 规格，请补充需求后重试") from None
            if isinstance(e, SpecConnectivityError) and repair_base is None:
                repair_base = raw
                repair_names = set(isolated_entity_names(normalized))
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": f"{e}。保留全部已有实体、属性和联系。"
                              "只依据原需求为上述实体补充有业务依据的联系，端点必须是已有实体。"
                              '本轮覆盖之前的输出格式，只返回 {"relations":[新增联系]}。'}]
            elif isinstance(e, SpecSizeError):
                repair_base = None
                messages = [{"role": "user", "content": user_message +
                             f"\n\n上一次输出超出绘图上限：{e}。请重新规划核心模型，并只输出完整 JSON。"}]
            else:
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": "上面的 JSON 有问题：%s。请修正后重新只输出完整 JSON。" % e}]


# ============================== 实体属性图 ==============================
def rect_radius(ux, uy, w, h):
    return 0.5 / max(abs(ux) / w, abs(uy) / h)


def boxes_overlap(a, b, gap=0):
    return (abs(a[0] - b[0]) < (a[2] + b[2]) / 2 + gap
            and abs(a[1] - b[1]) < (a[3] + b[3]) / 2 + gap)


def layout_entity(name, attrs):
    """从实体边缘到属性边缘保持相同的可见线长，逐步让出避碰空间。"""
    rw, rh = tw(name) + 0.34, 0.44
    sizes = [(tw(a) + 0.30, 0.40) for a, _ in attrs]
    n = len(attrs)
    rays = []
    for i, (w, h) in enumerate(sizes):
        angle = math.pi / 2 - math.tau * i / n
        ux, uy = math.cos(angle), math.sin(angle)
        rays.append((ux, uy, rect_radius(ux, uy, rw, rh), 0.5 / math.hypot(ux / w, uy / h)))

    for step in range(401):
        gap = 0.22 + 0.05 * step
        pos, lines, boxes = [], [], []
        for (ux, uy, start, radius), (w, h) in zip(rays, sizes):
            end = start + gap
            x, y = (end + radius) * ux, (end + radius) * uy
            pos.append((x, y))
            lines.append((start * ux, start * uy, end * ux, end * uy))
            boxes.append((x, y, w, h))
        if any(boxes_overlap(box, (0, 0, rw, rh), gap=0.06) for box in boxes):
            continue
        if any(boxes_overlap(box, other, gap=0.06) for i, box in enumerate(boxes) for other in boxes[:i]):
            continue
        if any(_seg_hits_rect(*line, *box) for i, line in enumerate(lines) for j, box in enumerate(boxes) if i != j):
            continue
        break
    else:
        raise RuntimeError("属性过多，无法为实体“%s”排版" % name)

    boxes.append((0, 0, rw, rh))
    xs = [x + side * w / 2 for x, _, w, _ in boxes for side in (-1, 1)]
    ys = [y + side * h / 2 for _, y, _, h in boxes for side in (-1, 1)]
    return dict(pos=pos, sizes=sizes, lines=lines, rw=rw, rh=rh,
                x0=min(xs) - 0.05, x1=max(xs) + 0.05, y0=min(ys) - 0.05, y1=max(ys) + 0.05)


def _canvas_dimensions(width, height, image_format, ratio):
    render_dpi = DPI
    if ratio is not None:
        columns, rows = ratio
        unit = max(width / columns, height / rows)
        width, height = unit * columns, unit * rows
    if image_format not in ("svg", "pdf"):
        render_dpi = max(1, min(DPI, int(math.sqrt(24_000_000 / (width * height))),
                                int(12_000 / max(width, height))))
        if ratio is not None:
            # Avoid truncating a pixel when Matplotlib converts inches back to pixels.
            unit = math.nextafter(math.ceil(unit * render_dpi) / render_dpi, math.inf)
            width, height = unit * columns, unit * rows
    return width, height, render_dpi


def draw_entity_fig(name, attrs, out, image_format=None, canvas_ratio=None):
    """attrs: [(属性名, 是否主键)]"""
    c = layout_entity(name, attrs)
    W = (c["x1"] - c["x0"]) + 0.2
    H = (c["y1"] - c["y0"]) + 0.2
    width, height, render_dpi = _canvas_dimensions(W, H, image_format, canvas_ratio)
    x, y = (W - width) / 2, (H - height) / 2
    fig = plt.figure(figsize=(width, height), dpi=render_dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x, x + width)
    ax.set_ylim(y, y + height)
    ax.axis("off")
    cx, cy = 0.1 - c["x0"], 0.1 - c["y0"]
    for x0, y0, x1, y1 in c["lines"]:
        ax.plot([cx + x0, cx + x1], [cy + y0, cy + y1], color="black", lw=LINE_W, zorder=1)
    for (px, py), (sw, sh), (a, pk) in zip(c["pos"], c["sizes"], attrs):
        ax.add_patch(Ellipse((cx + px, cy + py), sw, sh, fc="white", ec="black", lw=LINE_W, zorder=2))
        ax.text(cx + px, cy + py, a, fontproperties=FP, ha="center", va="center", zorder=3)
        if pk:   # 主键下划线
            w = tw(a)
            yy = cy + py - 0.105
            ax.plot([cx + px - w / 2, cx + px + w / 2], [yy, yy], color="black", lw=LINE_W, zorder=3)
    ax.add_patch(Rectangle((cx - c["rw"] / 2, cy - c["rh"] / 2), c["rw"], c["rh"],
                           fc="white", ec="black", lw=LINE_W, zorder=4))
    ax.text(cx, cy, name, fontproperties=FP, ha="center", va="center", zorder=5)
    fig.savefig(out, format=image_format, dpi=render_dpi, facecolor="white")
    plt.close(fig)
    print("已生成", out, "(%.2f x %.2f 英寸)" % (width, height))
    return {"x": x, "y": y, "width": width, "height": height,
            "contentFrame": {"x": 0, "y": 0, "width": W, "height": H}}


# ============================== 整体 E-R 图：自动布局 ==============================
DW, DH, EH, AH = 0.86, 0.56, 0.44, 0.36     # 菱形宽高、实体高、属性椭圆高
W_OVERLAP, W_HIT, W_CROSS = 100, 60, 40     # 惩罚权重：图形重叠 / 连线穿过图形 / 连线交叉


def _seg_hits_rect(ax_, ay_, bx_, by_, cx, cy, w, h):
    """线段是否穿过矩形（Liang–Barsky）"""
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    if ((ax_ < x0 and bx_ < x0) or (ax_ > x1 and bx_ > x1)
            or (ay_ < y0 and by_ < y0) or (ay_ > y1 and by_ > y1)):
        return False
    dx, dy = bx_ - ax_, by_ - ay_
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, ax_ - x0), (dx, x1 - ax_), (-dy, ay_ - y0), (dy, y1 - ay_)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                if t > t1:
                    return False
                t0 = max(t0, t)
            else:
                if t < t0:
                    return False
                t1 = min(t1, t)
    return t0 <= t1


def _seg_cross(s, t):
    """两线段是否严格相交"""
    def o(px, py, qx, qy, rx, ry):
        v = (qx - px) * (ry - py) - (qy - py) * (rx - px)
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    a, b, c, d = (s[0], s[1]), (s[2], s[3]), (t[0], t[1]), (t[2], t[3])
    o1, o2 = o(*a, *b, *c), o(*a, *b, *d)
    o3, o4 = o(*c, *d, *a), o(*c, *d, *b)
    return o1 * o2 < 0 and o3 * o4 < 0


def collisions(boxes, segs, *, unchanged=(0, 0), ceiling=math.inf):
    """boxes: (x,y,w,h,kind,key)  kind: e=实体(key=实体序号) d=菱形/a=联系属性(key=联系序号)
       segs : (ax,ay,bx,by,联系序号,实体序号或-1)
       达到 ceiling 时返回已累计的惩罚，足以淘汰该候选。"""
    pen = 0
    nb = len(boxes)
    old_boxes, old_segs = unchanged
    new_boxes = boxes[old_boxes:] if old_boxes else boxes
    for i in range(nb):
        x1, y1, w1, h1 = boxes[i][:4]
        for j in range(max(i + 1, old_boxes), nb):
            x2, y2, w2, h2 = boxes[j][:4]
            if abs(x1 - x2) < (w1 + w2) / 2 + 0.05 and abs(y1 - y2) < (h1 + h2) / 2 + 0.05:
                pen += W_OVERLAP
                if pen >= ceiling:
                    return pen
    for i, s in enumerate(segs):
        sx0, sx1 = (s[0], s[2]) if s[0] < s[2] else (s[2], s[0])
        sy0, sy1 = (s[1], s[3]) if s[1] < s[3] else (s[3], s[1])
        for b in new_boxes if i < old_segs else boxes:
            hw, hh = b[2] / 2 + 0.02, b[3] / 2 + 0.02
            if b[0] + hw < sx0 or b[0] - hw > sx1 or b[1] + hh < sy0 or b[1] - hh > sy1:
                continue                                          # 包围盒不相交，必然不穿过
            if b[4] == "e":
                if b[5] == s[5]:
                    continue
            elif b[5] == s[4] and (b[4] == "d" or (s[5] == -1 and b[:2] == s[2:4])):
                continue
            if _seg_hits_rect(s[0], s[1], s[2], s[3], b[0], b[1], b[2] + 0.04, b[3] + 0.04):
                pen += W_HIT
                if pen >= ceiling:
                    return pen
    ns = len(segs)
    for i in range(ns):
        s = segs[i]
        sx0, sx1 = (s[0], s[2]) if s[0] < s[2] else (s[2], s[0])
        sy0, sy1 = (s[1], s[3]) if s[1] < s[3] else (s[3], s[1])
        for j in range(max(i + 1, old_segs), ns):
            t = segs[j]
            if s[4] == t[4] or s[2:4] == t[2:4]:
                continue
            if max(t[0], t[2]) < sx0 or min(t[0], t[2]) > sx1 or max(t[1], t[3]) < sy0 or min(t[1], t[3]) > sy1:
                continue
            if _seg_cross(s, t):
                pen += W_CROSS
                if pen >= ceiling:
                    return pen
    return pen


def base_geometry(model, P):
    """实体矩形 + 非自联系菱形中心"""
    ents = [(P[i][0], P[i][1], model["ent_w"][i], EH) for i in range(len(P))]
    dias = []
    for r in model["rels"]:
        if r["self"]:
            dias.append(None)
            continue
        pts = [P[e] for e, _ in r["ends"]]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        if len(pts) == 2 and r["par_n"] > 1:               # 同一对实体多个联系：垂直错开
            ea, eb = sorted(e for e, _ in r["ends"])
            (ax_, ay_), (bx_, by_) = P[ea], P[eb]
            L = math.hypot(bx_ - ax_, by_ - ay_) or 1
            px, py = -(by_ - ay_) / L, (bx_ - ax_) / L
            step = abs(px) * DW + abs(py) * DH + 0.14
            off = (r["par_k"] - (r["par_n"] - 1) / 2) * step
            cx, cy = cx + px * off, cy + py * off
        dias.append((cx, cy))
    return ents, dias


def _footprints(d, widths):
    """属性簇的粗略占位矩形（右/左/上/下四种），供布局搜索用"""
    n, mw, tot = len(widths), max(widths), sum(widths) + 0.12 * (len(widths) - 1)
    h = 0.44 * n - 0.08
    return [(d[0] + DW / 2 + 0.25 + mw / 2, d[1], mw, h), (d[0] - DW / 2 - 0.25 - mw / 2, d[1], mw, h),
            (d[0], d[1] - DH / 2 - 0.3 - AH / 2, tot, AH), (d[0], d[1] + DH / 2 + 0.3 + AH / 2, tot, AH)]


def _incr_pen(c, k, boxes, segs):
    """把占位矩形 c 加入现有图形时新增的惩罚（只算与 c 有关的部分）"""
    x, y, w, h = c
    pen = 0
    for b in boxes:
        if abs(x - b[0]) < (w + b[2]) / 2 + 0.05 and abs(y - b[1]) < (h + b[3]) / 2 + 0.05:
            pen += W_OVERLAP
    for g in segs:
        if g[4] == k and g[5] == -1:
            continue
        if (max(g[0], g[2]) < x - w / 2 or min(g[0], g[2]) > x + w / 2
                or max(g[1], g[3]) < y - h / 2 or min(g[1], g[3]) > y + h / 2):
            continue
        if _seg_hits_rect(g[0], g[1], g[2], g[3], x, y, w + 0.04, h + 0.04):
            pen += W_HIT
    return pen


def quick_cost(model, P):
    """退火用的快速评价：重叠 + 穿线 + 交叉 + 连线长度 + 画面面积（含联系属性的占位）"""
    ents, dias = base_geometry(model, P)
    boxes = [(x, y, w, h, "e", i) for i, (x, y, w, h) in enumerate(ents)]
    segs, length = [], 0.0
    for k, (r, d) in enumerate(zip(model["rels"], dias)):
        if d is None:
            continue
        boxes.append((d[0], d[1], DW, DH, "d", k))
        for e, _ in r["ends"]:
            segs.append((d[0], d[1], P[e][0], P[e][1], k, e))
            length += math.hypot(d[0] - P[e][0], d[1] - P[e][1])
    for k, (r, d) in enumerate(zip(model["rels"], dias)):
        if d is None or not r["attrs"]:
            continue
        cands = _footprints(d, model["attr_w"][k])
        c = min(cands, key=lambda c: _incr_pen(c, k, boxes, segs))
        boxes.append((c[0], c[1], c[2], c[3], "a", k))
    xs = [b[0] - b[2] / 2 for b in boxes] + [b[0] + b[2] / 2 for b in boxes]
    ys = [b[1] - b[3] / 2 for b in boxes] + [b[1] + b[3] / 2 for b in boxes]
    width = max(xs) - min(xs)
    area = width * (max(ys) - min(ys))
    over = max(0.0, width + 0.16 - model["page_w"]) if model.get("page_w") else 0.0
    return collisions(boxes, segs) + 1.2 * length + 0.25 * area + 30 * over


def anneal(model, cols, rows, sx, sy, seed, iters, deadline=None):
    rng = random.Random(seed)
    cells = [(c, r) for r in range(rows) for c in range(cols)]
    n = len(model["ents"])
    asg = rng.sample(cells, n)

    def pos(a):
        return [(c * sx, r * sy) for c, r in a]

    cost = quick_cost(model, pos(asg))
    best = (cost, list(asg))
    T0, T1 = 60.0, 0.4
    for it in range(iters):
        if deadline is not None and time.monotonic() >= deadline:
            break
        T = T0 * (T1 / T0) ** (it / iters)
        i = rng.randrange(n)
        cell = rng.choice(cells)
        a2 = list(asg)
        if cell in a2:
            j = a2.index(cell)
            if j == i:
                continue
            a2[i], a2[j] = a2[j], a2[i]
        else:
            a2[i] = cell
        c2 = quick_cost(model, pos(a2))
        if c2 < cost or rng.random() < math.exp((cost - c2) / T):
            asg, cost = a2, c2
            if cost < best[0]:
                best = (cost, list(asg))
    return polish(model, best[1], cells, pos, best[0], deadline)


def polish(model, asg, cells, pos, cost, deadline=None):
    """贪心精修：逐个实体试遍所有格子（占用则互换），只要代价下降就接受，直到无改进"""
    asg = list(asg)
    for _ in range(6):
        improved = False
        for i in range(len(asg)):
            for cell in cells:
                if deadline is not None and time.monotonic() >= deadline:
                    return cost, asg
                if cell == asg[i]:
                    continue
                a2 = list(asg)
                if cell in a2:
                    j = a2.index(cell)
                    a2[i], a2[j] = a2[j], a2[i]
                else:
                    a2[i] = cell
                c2 = quick_cost(model, pos(a2))
                if c2 < cost - 1e-9:
                    asg, cost, improved = a2, c2, True
        if not improved:
            break
    return cost, asg


def _attr_candidates(d, widths):
    """联系属性的候选摆法：右/左列、上/下行；每种再配 3 种错位、2 种距离"""
    n = len(widths)
    out = []
    total = sum(widths) + 0.12 * (n - 1)
    x, centers = 0.0, []
    for w in widths:
        centers.append(x + w / 2)
        x += w + 0.12
    for gap in (0.25, 0.5):
        for shift in (0.0, -0.55, 0.55):
            for tag, s in (("R", 1), ("L", -1)):
                out.append([(d[0] + s * (DW / 2 + gap + w / 2), d[1] + shift + (i - (n - 1) / 2) * 0.44, w)
                            for i, w in enumerate(widths)])
            for tag, s in (("U", -1), ("D", 1)):
                y = d[1] + s * (DH / 2 + gap + 0.05 + AH / 2)
                dxs = shift / 0.55 * (total / 2 + 0.3)          # 整行向左/右错开，使其不正对菱形
                out.append([(d[0] - total / 2 + cx + dxs, y, w) for cx, w in zip(centers, widths)])
    return out


def compose(model, P, relation_positions=None):
    """给定实体中心坐标，生成完整场景：自联系菱形、联系属性椭圆、所有连线"""
    ents, dias = base_geometry(model, P)
    pinned = relation_positions or {}
    for index, point in pinned.items():
        if not model["rels"][index]["self"]:
            dias[index] = point
    rels = model["rels"]
    boxes = [(x, y, w, h, "e", i) for i, (x, y, w, h) in enumerate(ents)]
    segs = []
    for k, (r, d) in enumerate(zip(rels, dias)):
        if d is None:
            continue
        boxes.append((d[0], d[1], DW, DH, "d", k))
        for e, _ in r["ends"]:
            segs.append((d[0], d[1], P[e][0], P[e][1], k, e))

    # —— 自联系：菱形放在实体的斜上/斜下方，两条线接到实体上/下边框 ——
    self_info = {}
    for k, r in enumerate(rels):
        if not r["self"]:
            continue
        e = r["ends"][0][0]
        ex, ey, ew, eh = ents[e]
        best = None
        for order, (sxn, syn) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
            d = pinned.get(k, (ex + sxn * (max(ew / 2, 0.3) + 0.55), ey + syn * 0.95))
            pts = [(ex + sxn * 0.25, ey + syn * eh / 2), (ex + sxn * 0.03, ey + syn * eh / 2)]
            nb = boxes + [(d[0], d[1], DW, DH, "d", k)]
            ns = segs + [(d[0], d[1], p[0], p[1], k, e) for p in pts]
            pen = collisions(nb, ns, unchanged=(len(boxes), len(segs))) + 0.01 * order
            if best is None or pen < best[0]:
                best = (pen, d, pts, sxn, syn)
        _, d, pts, sxn, syn = best
        dias[k] = d
        boxes.append((d[0], d[1], DW, DH, "d", k))
        for p in pts:
            segs.append((d[0], d[1], p[0], p[1], k, e))
        self_info[k] = dict(pts=pts, side=sxn, vert=syn)

    # —— 联系自身的属性：在 右/左/上/下 四种摆法中选最不碰撞的 ——
    attrs = []
    for k, r in enumerate(rels):
        if not r["attrs"]:
            continue
        d = dias[k]
        widths = model["attr_w"][k]
        best = None
        for bias, cand in enumerate(_attr_candidates(d, widths)):
            nb = boxes + [(x, y, w, AH, "a", k) for x, y, w in cand]
            ns = segs + [(d[0], d[1], x, y, k, -1) for x, y, w in cand]
            penalty = collisions(nb, ns, unchanged=(len(boxes), len(segs)),
                                 ceiling=best[0] if best is not None else math.inf)
            pen = penalty + 0.002 * bias
            if best is None or pen < best[0]:
                best = (pen, cand)
                if penalty == 0:
                    break
        for (x, y, w), name in zip(best[1], r["attrs"]):
            boxes.append((x, y, w, AH, "a", k))
            segs.append((d[0], d[1], x, y, k, -1))
            attrs.append((len(boxes) - 1, k, name))

    xs = [b[0] - b[2] / 2 for b in boxes] + [b[0] + b[2] / 2 for b in boxes]
    ys = [b[1] - b[3] / 2 for b in boxes] + [b[1] + b[3] / 2 for b in boxes]
    length = sum(math.hypot(g[0] - g[2], g[1] - g[3]) for g in segs)
    return dict(P=P, ents=ents, dias=dias, boxes=boxes, segs=segs, attrs=attrs,
                self_info=self_info, pen=collisions(boxes, segs), length=length,
                area=(max(xs) - min(xs)) * (max(ys) - min(ys)), width=max(xs) - min(xs))


def _anneal_task(args):
    return anneal(*args)


def _run_anneals(tasks, parallel=True):
    """多进程并行跑退火；失败（如受限环境）则退回串行"""
    if parallel and len(tasks) > 1 and (os.cpu_count() or 1) > 1:
        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=min(len(tasks), os.cpu_count() or 1)) as ex:
                return list(ex.map(_anneal_task, tasks))
        except Exception as e:                      # noqa
            print("  （并行失败，改为串行：%s）" % e)
    return [_anneal_task(t) for t in tasks]


def refine_continuous(model, P, seed, iters=500, deadline=None):
    """网格解仍有交叉/穿线时：允许实体小范围离开网格，只接受让碰撞惩罚下降的移动"""
    rng = random.Random(seed)
    P = list(P)

    def pen_of(Q):
        ents, dias = base_geometry(model, Q)
        boxes = [(x, y, w, h, "e", i) for i, (x, y, w, h) in enumerate(ents)]
        segs = []
        for k, (r, d) in enumerate(zip(model["rels"], dias)):
            if d is None:
                continue
            boxes.append((d[0], d[1], DW, DH, "d", k))
            for e, _ in r["ends"]:
                segs.append((d[0], d[1], Q[e][0], Q[e][1], k, e))
        return collisions(boxes, segs)

    cost = quick_cost(model, P)
    pen = pen_of(P)
    for it in range(iters):
        if pen < 1 or (deadline is not None and time.monotonic() >= deadline):
            break
        i = rng.randrange(len(P))
        step = rng.choice((0.25, 0.5, 0.9))
        Q = list(P)
        Q[i] = (P[i][0] + rng.gauss(0, step), P[i][1] + rng.gauss(0, step))
        c2 = quick_cost(model, Q)
        if c2 < cost:                      # 总代价下降才接受（含重叠、穿线、交叉、长度、面积）
            P, cost, pen = Q, c2, pen_of(Q)
    return P


def layout_er(model, page_width=None, effort=1.5, seed=0, time_limit=45.0, parallel=True):
    n = len(model["ents"])
    model["page_w"] = page_width
    maxw = max(model["ent_w"])
    sx = maxw + DW + 0.42
    sy = EH + DH + 0.55
    attribute_count = sum(map(len, model["attr_w"]))
    heavy = not parallel and attribute_count > 160
    if heavy:
        # 联系属性很多时，先给属性簇留位置；完整场景只构造一次。
        sx += min(2.0, attribute_count / 160)
        sy += min(2.0, attribute_count / 160)
    if n == 1:
        return compose(model, [(0.0, 0.0)])
    c0 = max(2, math.ceil(math.sqrt(n * 1.7)))
    shapes = []
    column_counts = (c0, c0 + 1) if n < 6 else (c0, c0 - 1, c0 + 1)
    for cols in column_counts:
        if page_width:
            cols = min(cols, max(2, int((page_width - 0.3 - maxw) // sx) + 1))
        rows = max(2, math.ceil(n / cols) + 1)
        if (cols, rows) not in shapes and cols * rows >= n:
            shapes.append((cols, rows))
    iters = int(1800 * effort)
    nseed = max(1, int(round(2 * effort)))

    def score(sc):                      # 越小越好：碰撞最重，其次连线长度和画面面积
        over = max(0.0, sc["width"] + 0.16 - model["page_w"]) if model.get("page_w") else 0.0
        return sc["pen"] + 1.2 * sc["length"] + 0.6 * sc["area"] + 30 * over

    best = None
    finalists = []
    deadline = time.monotonic() + time_limit
    # Web 版串行搜索需要留出进程启动和绘图的时间。
    search_deadline = deadline if not parallel else None
    for rnd in range(6):                # 最多 6 轮：得到无碰撞布局，或用完时间预算就停止
        tasks = [(model, cols, rows, sx, sy, (seed * 10 + rnd) * 100 + sd, iters, None)
                 for cols, rows in shapes for sd in range(nseed)]
        if search_deadline is not None:
            now = time.monotonic()
            # 不让第一种网格耗尽预算，给其他网格和局部精修留时间。
            share = max(0, search_deadline - now) * 0.75 / len(tasks)
            tasks = [(*task[:-1], now + (i + 1) * share) for i, task in enumerate(tasks)]
        cands = _run_anneals(tasks, parallel=parallel)
        for _, asg in sorted(cands, key=lambda t: t[0])[:1 if heavy else max(3, nseed)]:
            cur = None
            for f in (1.0,) if heavy else (1.0, 1.1, 1.2, 1.32, 1.46):
                P = [(c * sx * f, r * sy * f) for c, r in asg]
                sc = compose(model, P)
                expired = search_deadline is not None and time.monotonic() >= search_deadline
                if sc["pen"] >= 1 and not expired and not heavy:
                    sc2 = compose(model, refine_continuous(model, P, seed + rnd, deadline=search_deadline))
                    if score(sc2) < score(sc):
                        sc = sc2
                if cur is None or score(sc) < score(cur):
                    cur = sc
                if expired or sc["pen"] < 1 or (cur is not sc and f > 1.2):
                    break
            if best is None or score(cur) < score(best):
                best = cur
            if all(cur["P"] != candidate["P"] for candidate in finalists):
                finalists.append(cur)
                finalists.sort(key=score)
                del finalists[3:]
        print("  布局搜索第 %d 轮：当前最优碰撞惩罚 %d" % (rnd + 1, best["pen"]))
        if best["pen"] < 1 or heavy:
            break
        if time.monotonic() >= deadline:
            print("  已达到时间预算 %.0f 秒，采用当前最优布局。" % time_limit)
            break
    return choose_overview_scene(finalists, page_width)


# ============================== 整体 E-R 图：绘制 ==============================
def _path_segments(path):
    return [(*a, *b) for a, b in zip(path, path[1:]) if a != b]


def _path_bends(path):
    segments = _path_segments(path)
    count = 0
    for a, b in zip(segments, segments[1:]):
        ax, ay = a[2] - a[0], a[3] - a[1]
        bx, by = b[2] - b[0], b[3] - b[1]
        if ax * bx + ay * by < 0 or abs(ax * by - ay * bx) > 1e-6 * math.hypot(ax, ay) * math.hypot(bx, by):
            count += 1
    return count


def _edge_port(point, towards, shape):
    dx, dy = towards[0] - point[0], towards[1] - point[1]
    if not (dx or dy):
        return point
    _, _, w, h, kind, _ = shape
    if kind == "d":
        scale = 0.5 / (abs(dx) / w + abs(dy) / h)
    elif kind == "a":
        scale = 0.5 / math.hypot(dx / w, dy / h)
    else:
        scale = rect_radius(dx, dy, w, h)
    return point[0] + scale * dx, point[1] + scale * dy


def _visible_path(points, source, target):
    start = _edge_port(points[0], points[1], source)
    end = _edge_port(points[-1], points[-2], target) if points[-1] == target[:2] else points[-1]
    if len(points) == 2 and math.dist(points[0], start) + math.dist(points[-1], end) >= math.dist(*points):
        return (end, end)
    return (start, *points[1:-1], end)


def _path_crosses(a, b):
    if (max(a[0], a[2]) < min(b[0], b[2]) or max(b[0], b[2]) < min(a[0], a[2])
            or max(a[1], a[3]) < min(b[1], b[3]) or max(b[1], b[3]) < min(a[1], a[3])):
        return False
    if _seg_cross(a, b):
        return True

    def touches_interior(point, line):
        x, y = point
        dx, dy = line[2] - line[0], line[3] - line[1]
        return (abs(dx * (y - line[1]) - dy * (x - line[0])) <= 1e-8
                and (x - line[0]) * (x - line[2]) + (y - line[1]) * (y - line[3]) < -1e-8)

    # 折点落到别的线上也算冲突，共用图形边缘上的同一个接点除外。
    return (a == b or a == (*b[2:], *b[:2])
            or any(touches_interior(point, b) for point in (a[:2], a[2:]))
            or any(touches_interior(point, a) for point in (b[:2], b[2:])))


def _waypoint_near_line(point, line, gap=0.024):
    x, y = point
    ax, ay, bx, by = line
    if not (min(ax, bx) - gap <= x <= max(ax, bx) + gap
            and min(ay, by) - gap <= y <= max(ay, by) + gap):
        return False
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    fraction = min(1, max(0, ((x - ax) * dx + (y - ay) * dy) / length_squared)) if length_squared else 0
    return (x - ax - fraction * dx) ** 2 + (y - ay - fraction * dy) ** 2 < gap * gap


def _routes_conflict(first, second):
    """检查相交和折点净距。真正的图形接线端点可共用。"""
    if len(first) == len(second) == 1:
        return _path_crosses(first[0], second[0])
    if any(_path_crosses(a, b) for a in first for b in second):
        return True
    return (any(_waypoint_near_line(a[2:], b) for a in first[:-1] for b in second)
            or any(_waypoint_near_line(b[2:], a) for b in second[:-1] for a in first))


def _route_crosses_itself(lines):
    return (not lines or any(_path_crosses(a, b) for a, b in zip(lines, lines[1:]))
            or any(_path_crosses(line, earlier) or line[:2] in (earlier[:2], earlier[2:])
               or line[2:] in (earlier[:2], earlier[2:])
               for j, line in enumerate(lines[2:], 2) for earlier in lines[:j - 1]))


def _detour_candidates(start, end, boxes):
    ax, ay = start
    bx, by = end
    length = math.dist(start, end)
    ux, uy = (bx - ax) / length, (by - ay) / length
    for offset in (0.18, -0.18, 0.34, -0.34, 0.56, -0.56, 0.85, -0.85, 1.2, -1.2):
        yield (start, (ax - uy * offset, ay + ux * offset), (bx - uy * offset, by + ux * offset), end)
        yield (start, ((ax + bx) / 2 - uy * offset, (ay + by) / 2 + ux * offset), end)

    corners = {(x + sx * (w / 2 + 0.16), y + sy * (h / 2 + 0.16))
               for x, y, w, h, _, _ in boxes for sx in (-1, 1) for sy in (-1, 1)}
    for point in sorted(corners, key=lambda p: (math.dist(start, p) + math.dist(p, end), p))[:48]:
        yield (start, point, end)

    for axis in (0, 1):
        rails = {point[axis] for point in corners}
        ordered = sorted(rails, key=lambda value: (abs(value - start[axis]) + abs(value - end[axis]), value))
        for value in dict.fromkeys(ordered[:16] + [min(rails), max(rails)]):
            if axis == 0:
                yield (start, (value, ay), (value, by), end)
            else:
                yield (start, (ax, value), (bx, value), end)

    near_start = sorted(corners, key=lambda point: (math.dist(start, point), point))[:16]
    near_end = sorted(corners, key=lambda point: (math.dist(end, point), point))[:16]
    for first in near_start:
        for last in near_end:
            yield (start, first, last, end)


def _overview_edges(scene):
    boxes = [(*map(float, box[:4]), *box[4:]) for box in scene["boxes"]]
    entities = {box[5]: box for box in boxes if box[4] == "e"}
    diamonds = {box[5]: box for box in boxes if box[4] == "d"}
    attributes = {(box[5], box[:2]): box for box in boxes if box[4] == "a"}
    edges = []
    for ax, ay, bx, by, relation, entity in scene["segs"]:
        start, end = (float(ax), float(ay)), (float(bx), float(by))
        target = entities[entity] if entity >= 0 else attributes[relation, end]
        edges.append((start, end, diamonds[relation], target, entity >= 0 and relation not in scene["self_info"]))
    return boxes, edges


def _line_hits_shape(line, shape, padding=0.02):
    cx, cy, w, h, kind, _ = shape
    rx, ry = w / 2 + padding, h / 2 + padding
    ax, ay, bx, by = line
    if ((max(ax, bx) < cx - rx or min(ax, bx) > cx + rx)
            or (max(ay, by) < cy - ry or min(ay, by) > cy + ry)):
        return False
    if kind == "e":
        return _seg_hits_rect(*line, cx, cy, rx * 2, ry * 2)
    x1, y1 = (ax - cx) / rx, (ay - cy) / ry
    x2, y2 = (bx - cx) / rx, (by - cy) / ry
    if kind == "d":
        # 归一化菱形经过坐标变换后成为边长为 2 的正方形。
        return _seg_hits_rect(x1 + y1, x1 - y1, x2 + y2, x2 - y2, 0, 0, 2, 2)
    # 归一化椭圆成为单位圆。检查线段上离圆心最近的点。
    dx, dy = x2 - x1, y2 - y1
    length = dx * dx + dy * dy
    fraction = min(1, max(0, -(x1 * dx + y1 * dy) / length)) if length else 0
    return (x1 + dx * fraction) ** 2 + (y1 + dy * fraction) ** 2 <= 1


def _route_box_hits(lines, boxes, source, target, *, exact=False):
    hits = 0
    for box in boxes:
        if box is source or box is target:
            if exact:
                hits += any(_line_hits_shape(line, box, padding=-0.001) for line in lines)
            continue
        if exact:
            hits += any(_line_hits_shape(line, box) for line in lines)
        else:
            x, y, w, h, _, _ = box
            hits += any(_seg_hits_rect(*line, x, y, w + 0.04, h + 0.04) for line in lines)
    return hits


def route_overview(scene, *, optimize=True):
    """位置确定后，尝试为有碰撞的实体连线找更清楚的折线路径。"""
    boxes, edges = _overview_edges(scene)
    paths = [_visible_path((a, b), source, target) for a, b, source, target, _ in edges]
    if not optimize:
        return paths
    segments = [_path_segments(path) for path in paths]
    complexity = len(boxes) + len(edges)
    trial_budget = max(64, 180_000 // complexity)
    trials_per_edge = max(16, 30_000 // complexity)

    def conflicts(lines, index, source, target):
        hits = _route_box_hits(lines, boxes, source, target)
        crossings = nearby = 0
        for j, route in enumerate(segments):
            if j != index:
                if any(_path_crosses(a, b) for a in lines for b in route):
                    crossings += 1
                elif _routes_conflict(lines, route):
                    nearby += 1
        return hits, crossings, nearby

    for _ in range(2):
        changed = False
        for i, (start, end, source, target, movable) in enumerate(edges):
            if trial_budget <= 0:
                return paths
            if not movable or start == end:
                continue
            baseline = conflicts(segments[i], i, source, target)
            if baseline == (0, 0, 0):
                continue
            best = (*baseline, math.inf)
            max_length = 2.3 * math.dist(start, end) + 1.1
            edge_trials = min(trials_per_edge, trial_budget)
            for points in _detour_candidates(start, end, boxes):
                if edge_trials <= 0:
                    break
                if any(a == b for a, b in zip(points, points[1:])):
                    continue
                length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
                if length > max_length:
                    continue
                if any(_seg_hits_rect(*point, *point, *box[:4]) for point in points[1:-1] for box in (source, target)):
                    continue
                candidate = _visible_path(points, source, target)
                lines = _path_segments(candidate)
                if (any(_seg_hits_rect(*line, *source[:4]) for line in lines[1:])
                        or any(_seg_hits_rect(*line, *target[:4]) for line in lines[:-1])):
                    continue
                edge_trials -= 1
                trial_budget -= 1
                candidate_conflicts = conflicts(lines, i, source, target)
                score = (*candidate_conflicts, length + 0.08 * (len(points) - 2))
                if (candidate_conflicts[0] <= baseline[0] and candidate_conflicts[1:] <= baseline[1:]
                        and candidate_conflicts != baseline and score < best):
                    best = score
                    paths[i], segments[i] = candidate, lines
                    changed = True
        if not changed:
            break
    return paths


def _visibility_detour(start, end, source, target, boxes, occupied, deadline):
    """搜索由图形外侧拐点组成的可见路径，先少交叉，再少绕路。"""
    length_limit = 3.5 * math.dist(start, end) + 2.0
    corners = {(x + sx * (w / 2 + 0.15), y + sy * (h / 2 + 0.15))
               for x, y, w, h, _, _ in boxes for sx in (-1, 1) for sy in (-1, 1)}
    occupied_points = {segment[:2] for segment in occupied} | {segment[2:] for segment in occupied}
    corners = [point for point in corners if math.dist(start, point) + math.dist(point, end) < length_limit
               and all(math.dist(point, other) > 0.045 for other in occupied_points)]
    corners.sort(key=lambda p: (math.dist(start, p) + math.dist(p, end), p))
    points = [start, end, *corners[:56]]
    queue = [(0, 0.0, 0, (0,))]
    best = {0: (0, 0.0)}
    while queue and time.monotonic() < deadline:
        crossings, cost, i, route = heapq.heappop(queue)
        if best[i] != (crossings, cost):
            continue
        if i == 1:
            path = _visible_path(tuple(points[j] for j in route), source, target)
            lines = _path_segments(path)
            if any(_path_crosses(line, earlier) for j, line in enumerate(lines[2:], 2)
                   for earlier in lines[:j - 1]):
                return None
            return path
        a = points[i]
        for j, b in enumerate(points[1:], 1):
            if j in route or a == b:
                continue
            distance = math.dist(a, b)
            next_cost = cost + distance + 0.12
            if next_cost + math.dist(b, end) > length_limit:
                continue
            p = _edge_port(a, b, source) if i == 0 else a
            q = _edge_port(b, a, target) if j == 1 else b
            if p == q or math.dist(a, p) + math.dist(b, q) >= distance:
                continue
            segment = (*p, *q)
            if any(_seg_hits_rect(*segment, box[0], box[1], box[2] + 0.04, box[3] + 0.04)
                   for box in boxes if not (i == 0 and box is source) and not (j == 1 and box is target)):
                continue
            score = (crossings + sum(_path_crosses(segment, other) for other in occupied), next_cost)
            if score < best.get(j, (math.inf, math.inf)):
                best[j] = score
                heapq.heappush(queue, (*score, j, (*route, j)))
    return None


def _refine_overview_routes(scene, paths, deadline):
    boxes, edges = _overview_edges(scene)
    paths = list(paths)
    segments = [_path_segments(path) for path in paths]

    def conflicts(lines, occupied_routes, source, target):
        return (_route_box_hits(lines, boxes, source, target),
                sum(_routes_conflict(lines, route) for route in occupied_routes))

    for _ in range(2):
        troubled = []
        for i, (start, end, source, target, movable) in enumerate(edges):
            if (movable or target[4] == "a") and start != end:
                occupied = [route for j, route in enumerate(segments) if j != i]
                score = conflicts(segments[i], occupied, source, target)
                if score != (0, 0):
                    troubled.append((score, i))
        changed = False
        for _, i in sorted(troubled, reverse=True):
            if time.monotonic() >= deadline:
                return paths
            start, end, source, target, _ = edges[i]
            occupied = [route for j, route in enumerate(segments) if j != i]
            current = conflicts(segments[i], occupied, source, target)
            if current == (0, 0):
                continue
            candidate = _visibility_detour(start, end, source, target, boxes, list(itertools.chain.from_iterable(occupied)),
                                           min(time.monotonic() + 0.4, deadline))
            if candidate is None:
                continue
            lines = _path_segments(candidate)
            if lines and conflicts(lines, occupied, source, target) < current:
                paths[i], segments[i] = candidate, lines
                changed = True
        if not changed:
            break
    return paths


def overview_quality(scene, paths, page_width=None):
    """用即将绘制的折线评分，优先消除遮挡，再比较交叉和尺寸。"""
    boxes, edges = _overview_edges(scene)
    segments = [_path_segments(path) for path in paths]
    overlaps = sum(boxes_overlap(box, other, gap=0.05)
                   for i, box in enumerate(boxes) for other in boxes[:i])
    hits = sum(_route_box_hits(lines, boxes, source, target, exact=True)
               for lines, (_, _, source, target, _) in zip(segments, edges))
    crossings = (sum(_route_crosses_itself(lines) for lines in segments)
                 + sum(_routes_conflict(lines, other) for i, lines in enumerate(segments) for other in segments[:i]))
    length = sum(math.dist(line[:2], line[2:]) for lines in segments for line in lines)
    x0, x1, y0, y1 = _diagram_extents(boxes, paths, [], margin=0)
    width, height = x1 - x0, y1 - y0
    overflow = max(0, width + 0.16 - page_width) if page_width else 0
    return overlaps, hits, crossings, 1.2 * length + 0.6 * width * height + 30 * overflow


def choose_overview_scene(candidates, page_width=None):
    best_scene, best_quality = None, None
    for scene in candidates:
        paths = route_overview(scene)
        overlaps, hits, crossings, fit_cost = overview_quality(scene, paths, page_width)
        bends = sum(map(_path_bends, paths))
        quality = (overlaps, hits, crossings, fit_cost + 2.0 * bends, bends)
        if best_quality is None or quality < best_quality:
            best_scene, best_quality = dict(scene, paths=paths), quality
    if best_quality[0] or best_quality[1] or best_quality[2]:
        overlaps, hits, crossings, *_ = best_quality
        print(f"已比较 {len(candidates)} 个候选布局，所选图仍有 {overlaps} 处图形挤压、"
              f"{hits} 处穿框、{crossings} 处连线冲突。")
    return best_scene


def overview_topology(model):
    """实体、联系和联系属性都入图。自联系用一个无形折点区分两个端点。"""
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(("e", i) for i in range(len(model["ents"])))
    connections = []
    for k, relation in enumerate(model["rels"]):
        diamond = ("d", k)
        for index, (entity, _) in enumerate(relation["ends"]):
            end = ("e", entity)
            chain = (diamond, ("bend", k), end) if relation["self"] and index == 1 else (diamond, end)
            nx.add_path(graph, chain)
            connections.append((k, entity, chain))
        for index, _ in enumerate(relation["attrs"]):
            chain = (diamond, ("a", k, index))
            nx.add_path(graph, chain)
            connections.append((k, -1, chain))
    planar, embedding = nx.check_planarity(graph)
    return embedding if planar else None, connections


def _planar_scene(model, positions, connections):
    shapes, attrs = {}, []
    ents = []
    for i, w in enumerate(model["ent_w"]):
        x, y = positions["e", i]
        ents.append((x, y, w, EH))
        shapes["e", i] = (x, y, w, EH, "e", i)
    for k, relation in enumerate(model["rels"]):
        x, y = positions["d", k]
        shapes["d", k] = (x, y, model["rel_w"][k], DH, "d", k)
        for i, (name, w) in enumerate(zip(relation["attrs"], model["attr_w"][k])):
            if ("a", k, i) not in positions:
                continue
            x, y = positions["a", k, i]
            attrs.append((len(shapes), k, name))
            shapes["a", k, i] = (x, y, w, AH, "a", k)
    paths, segs = [], []
    for relation, entity, chain in connections:
        if chain[-1] not in positions:
            continue
        points = tuple(positions[node] for node in chain)
        paths.append(_visible_path(points, shapes[chain[0]], shapes[chain[-1]]))
        segs.append((*points[0], *points[-1], relation, entity))
    return {"ents": ents, "boxes": list(shapes.values()), "attrs": attrs, "paths": paths, "segs": segs,
            "positions": positions,
            "self_info": {k: {} for k, relation in enumerate(model["rels"]) if relation["self"]}}


def _compact_embedding(model, connections):
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(("e", i) for i in range(len(model["ents"])))
    midpoints = {}
    pairs = set()
    for k, relation in enumerate(model["rels"]):
        endpoints = tuple(sorted(("e", i) for i, _ in relation["ends"]))
        if len(endpoints) == 2 and not relation["self"] and endpoints not in pairs:
            graph.add_edge(*endpoints)
            midpoints["d", k] = endpoints
            pairs.add(endpoints)
    for relation, entity, chain in connections:
        if entity >= 0 and ("d", relation) not in midpoints:
            nx.add_path(graph, chain)
    _, embedding = nx.check_planarity(graph)
    return embedding, midpoints


def _changed_pairs(items, changed):
    if len(changed) == len(items):
        for i, item in enumerate(items):
            for other in items[:i]:
                yield item, other
    else:
        for i in changed:
            for j, other in enumerate(items):
                if i != j and (j < i or j not in changed):
                    yield items[i], other


def _clear_planar_geometry(scene, previous=None):
    """校验图形与连线。若上一版已校验，未移动的图元之间可跳过。"""
    boxes, edges = _overview_edges(scene)
    changed_boxes = set(range(len(boxes)))
    changed_paths = set(range(len(scene["paths"])))
    if (previous is not None and len(boxes) == len(previous["boxes"])
            and len(scene["paths"]) == len(previous["paths"])):
        changed_boxes = {i for i, (box, old) in enumerate(zip(scene["boxes"], previous["boxes"])) if box != old}
        changed_paths = {i for i, (path, old) in enumerate(zip(scene["paths"], previous["paths"])) if path != old}
    if any(boxes_overlap(box, other, gap=0.05) for box, other in _changed_pairs(boxes, changed_boxes)):
        return False
    segments = [_path_segments(path) for path in scene["paths"]]
    moved_boxes = [boxes[i] for i in changed_boxes]
    if any(_route_box_hits(lines, boxes if i in changed_paths else moved_boxes, source, target, exact=True)
           for i, (lines, (_, _, source, target, _)) in enumerate(zip(segments, edges))):
        return False
    return (not any(_route_crosses_itself(segments[i]) for i in changed_paths)
            and not any(_routes_conflict(lines, other)
                        for lines, other in _changed_pairs(segments, changed_paths)))


def _bridge_branches(positions, links):
    """找出能沿一条桥接边整体平移的较小分支。"""
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(positions)
    graph.add_edges_from(links)
    branches = []
    for a, b in list(nx.bridges(graph)):
        graph.remove_edge(a, b)
        left = nx.node_connected_component(graph, a)
        right = nx.node_connected_component(graph, b)
        graph.add_edge(a, b)
        anchor, root, group = (b, a, left) if len(left) <= len(right) else (a, b, right)
        if len(group) > 1:
            branches.append((anchor, root, tuple(sorted(group))))
    return branches


def _pivot_groups(positions, links):
    """找出只经一个节点接入主图的分支，包括闭合的小环。"""
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(positions)
    graph.add_edges_from(links)
    pivots = []
    for anchor in sorted(nx.articulation_points(graph)):
        remaining = set(graph[anchor])
        without_anchor = nx.subgraph_view(graph, filter_node=lambda node: node != anchor)
        pieces = []
        while remaining:
            piece = nx.node_connected_component(without_anchor, min(remaining))
            pieces.append(tuple(sorted(piece)))
            remaining.difference_update(piece)
        pieces.sort(key=lambda piece: (-len(piece), piece))
        pivots.extend((anchor, piece) for piece in pieces[1:] if len(piece) > 1)
    return pivots


def _angled_attribute_rows(center, widths):
    """在两根斜线之间也能放一排属性，椭圆和文字保持水平。"""
    x, y = center
    for distance in (0.85, 1.35, 2.0):
        for i in range(16):
            angle = i * math.tau / 16
            ux, uy = math.cos(angle), math.sin(angle)
            tx, ty = -uy, ux
            spans = [abs(tx) * w + abs(ty) * AH for w in widths]
            offset = -(sum(spans) + 0.12 * (len(spans) - 1)) / 2
            row = []
            for w, span in zip(widths, spans):
                along = offset + span / 2
                row.append((x + ux * distance + tx * along, y + uy * distance + ty * along, w))
                offset += span + 0.12
            yield row


def _attach_planar_attributes(model, positions, connections, deadline):
    scene = _planar_scene(model, positions, connections)
    for k, widths in enumerate(model["attr_w"]):
        if not widths:
            continue
        center = positions["d", k]
        for arrangement in itertools.chain(_attr_candidates(center, widths), _angled_attribute_rows(center, widths)):
            if time.monotonic() >= deadline:
                return None
            updated = dict(positions)
            for i, (x, y, _) in enumerate(arrangement):
                updated["a", k, i] = (x, y)
            trial = _planar_scene(model, updated, connections)
            if _clear_planar_geometry(trial):
                positions, scene = updated, trial
                break
        else:
            # 狭窄的夹角可能容不下一整排，允许属性分别占用不同的扇区。
            for i in sorted(range(len(widths)), key=lambda i: -widths[i]):
                for [(x, y, _)] in _angled_attribute_rows(center, [widths[i]]):
                    if time.monotonic() >= deadline:
                        return None
                    updated = {**positions, ("a", k, i): (x, y)}
                    trial = _planar_scene(model, updated, connections)
                    if _clear_planar_geometry(trial):
                        positions, scene = updated, trial
                        break
                else:
                    return None
    return scene


def _fold_empty_bands(scene, axis):
    """只缩短没有形状或文字的条带；跨过条带的线段随坐标映射弯折。"""
    intervals = sorted((box[axis] - box[axis + 2] / 2 - 0.04,
                        box[axis] + box[axis + 2] / 2 + 0.04)
                       for box in scene["boxes"] + scene["labels"])
    bands = []
    end = intervals[0][1]
    for left, right in intervals[1:]:
        if left - end > 0.42:
            bands.append((end, left, 1 - 0.30 / (left - end)))
        end = max(end, right)
    if not bands:
        return scene

    def transform(point):
        x, y = point
        value = point[axis]
        shift = sum(max(0, min(value, right) - left) * rate for left, right, rate in bands)
        return (x - shift, y) if axis == 0 else (x, y - shift)

    cuts = [coordinate for left, right, _ in bands for coordinate in (left, right)]
    paths = []
    for path in scene["paths"]:
        points = [transform(path[0])]
        for a, b in zip(path, path[1:]):
            low, high = sorted((a[axis], b[axis]))
            if low < high:
                indices = cuts if a[axis] < b[axis] else reversed(cuts)
                for cut in indices:
                    if low < cut < high:
                        t = (cut - a[axis]) / (b[axis] - a[axis])
                        point = (cut, a[1] + t * (b[1] - a[1])) if axis == 0 else (a[0] + t * (b[0] - a[0]), cut)
                        points.append(transform(point))
            points.append(transform(b))
        paths.append(tuple(points))

    candidate = dict(scene,
                     ents=[(*transform(box[:2]), *box[2:]) for box in scene["ents"]],
                     boxes=[(*transform(box[:2]), *box[2:]) for box in scene["boxes"]],
                     segs=[(*transform(seg[:2]), *transform(seg[2:4]), *seg[4:]) for seg in scene["segs"]])
    if "positions" in scene:
        candidate["positions"] = {key: transform(point) for key, point in scene["positions"].items()}
    labels = [(*transform(label[:2]), *label[2:]) for label in scene["labels"]]
    candidate.update(paths=paths, labels=labels)
    if _clear_planar_geometry(candidate) and not _cardinality_conflicts(candidate["boxes"], paths, labels):
        return candidate
    return scene


def _compact_planar_scene(model, scene, connections, page_width, deadline):
    """在已找到的平面图上收紧节点和空白带，每轮保留通过标注检查的版本。"""
    import networkx as nx

    positions = scene["positions"]
    links = [(a, b) for _, _, chain in connections for a, b in zip(chain, chain[1:])]
    branches = _bridge_branches(positions, links)
    neighbors = {node: [] for node in positions}
    for a, b in links:
        neighbors[a].append(b)
        neighbors[b].append(a)
    components = sorted((tuple(sorted(group)) for group in nx.connected_components(nx.Graph(neighbors))),
                        key=lambda group: (-len(group), group))
    groups = {node: [node] for node in positions if node[0] != "a"}
    for node in positions:
        if node[0] == "a":
            groups["d", node[1]].append(node)

    def footprint(width, height):
        # 预览随最长一边缩小，面积相同也优先保留更易读的比例。
        return width * height + 0.25 * max(width, height) ** 2

    def cost(points):
        xs, ys = zip(*points.values())
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        length = sum(math.dist(points[a], points[b]) for a, b in links)
        overflow = max(0, width + 1 - page_width) if page_width else 0
        return footprint(width + 1, height + 0.6) + 1.35 * length + 30 * overflow

    def drawing_cost(drawing, labels):
        left, right, top, bottom = _diagram_extents(drawing["boxes"], drawing["paths"], labels)
        width, height = right - left, bottom - top
        length = sum(math.dist(a, b) for path in drawing["paths"] for a, b in zip(path, path[1:]))
        bends = sum(map(_path_bends, drawing["paths"]))
        overflow = max(0, width - page_width) if page_width else 0
        return footprint(width, height) + 1.35 * length + 12 * bends + 30 * overflow

    value = cost(positions)
    verified = scene
    verified_cost = drawing_cost(scene, scene["labels"])
    x0, x1, y0, y1 = _diagram_extents(scene["boxes"], scene["paths"], scene["labels"])
    coarse = max(x1 - x0, y1 - y0) / 8
    directions = [(math.cos(i * math.pi / 4), math.sin(i * math.pi / 4)) for i in range(8)]

    def try_move(points, candidate_value):
        nonlocal positions, scene, value
        if time.monotonic() >= deadline or candidate_value >= value - 1e-7:
            return False
        trial = _planar_scene(model, points, connections)
        if not _clear_planar_geometry(trial, previous=scene):
            return False
        positions, scene, value = points, trial, candidate_value
        return True

    def checkpoint():
        nonlocal verified, verified_cost
        labels = layout_cardinality_labels(model, scene, scene["paths"])
        candidate_cost = drawing_cost(scene, labels)
        if (candidate_cost < verified_cost and _clear_planar_geometry(scene)
                and not _cardinality_conflicts(scene["boxes"], scene["paths"], labels)):
            verified, verified_cost = dict(scene, labels=labels), candidate_cost
            return True
        return False

    def squeeze_axes(step):
        changed = False
        for axis in (0, 1):
            coordinates = sorted({point[axis] for point in positions.values()})
            bands = list(zip(coordinates, coordinates[1:]))
            for limit in (step, 2 * step, 4 * step):
                mapped = {coordinates[0]: coordinates[0]}
                for left, right in bands:
                    mapped[right] = mapped[left] + min(right - left, limit)
                trial = {key: (mapped[x], y) if axis == 0 else (x, mapped[y])
                         for key, (x, y) in positions.items()}
                if try_move(trial, cost(trial)):
                    changed = True
                    break
            coordinates = sorted({point[axis] for point in positions.values()})
            gaps = sorted(zip(coordinates, coordinates[1:]), key=lambda pair: pair[0] - pair[1])[:6]
            for left, right in gaps:
                if time.monotonic() >= deadline:
                    return changed
                shift = min(step, 0.8 * (right - left))
                trial = dict(positions)
                for key, (x, y) in positions.items():
                    if axis == 0 and x >= right:
                        trial[key] = (x - shift, y)
                    elif axis == 1 and y >= right:
                        trial[key] = (x, y - shift)
                changed = try_move(trial, cost(trial)) or changed
            for factor in (0.8, 0.88, 0.94, 0.98):
                trial = {key: (x * factor, y) if axis == 0 else (x, y * factor)
                         for key, (x, y) in positions.items()}
                if try_move(trial, cost(trial)):
                    changed = True
                    break
        return changed

    def skew_axes():
        # 剪切可以收拢斜着分布的节点，在轴向缩放之前释放空间。
        trials = []
        for factor in (-0.6, -0.3, -0.15, 0.15, 0.3, 0.6):
            for axis in (0, 1):
                trial = {key: (x + factor * y, y) if axis == 0 else (x, y + factor * x)
                         for key, (x, y) in positions.items()}
                trials.append((cost(trial), trial))
        return any(try_move(trial, candidate_value)
                   for candidate_value, trial in sorted(trials, key=lambda move: move[0]))

    def pull_branches(step):
        changed = False
        ranked = sorted(branches, key=lambda branch: -math.dist(positions[branch[0]], positions[branch[1]]))
        for anchor, root, group in ranked[:10]:
            if time.monotonic() >= deadline:
                break
            x, y = positions[root]
            ax, ay = positions[anchor]
            length = math.hypot(ax - x, ay - y)
            if not length:
                continue
            fraction = min(0.65, step / length)
            for amount in (fraction, fraction / 2):
                dx, dy = (ax - x) * amount, (ay - y) * amount
                trial = {**positions, **{key: (positions[key][0] + dx, positions[key][1] + dy) for key in group}}
                if try_move(trial, cost(trial)):
                    changed = True
                    break
        return changed

    def pack_components():
        # 移动独立块时保留内部连线。用其余图元的范围找可以填入的空位。
        changed = False
        for group in components[1:]:
            if time.monotonic() >= deadline:
                break
            outside = set(positions).difference(group)
            xs, ys = zip(*(positions[node] for node in outside))
            gx, gy = zip(*(positions[node] for node in group))
            cx, cy = (min(gx) + max(gx)) / 2, (min(gy) + max(gy)) / 2
            moves = []
            for fx, fy in itertools.product((0, 0.25, 0.5, 0.75, 1), repeat=2):
                dx = min(xs) + fx * (max(xs) - min(xs)) - cx
                dy = min(ys) + fy * (max(ys) - min(ys)) - cy
                trial = {**positions, **{node: (positions[node][0] + dx, positions[node][1] + dy)
                                         for node in group}}
                moves.append((cost(trial), trial))
            for candidate_value, trial in sorted(moves, key=lambda move: move[0]):
                if try_move(trial, candidate_value):
                    changed = True
                    break
        return changed

    def finish():
        drawing = verified
        for axis in (0, 1):
            candidate = _fold_empty_bands(drawing, axis)
            if drawing_cost(candidate, candidate["labels"]) < drawing_cost(drawing, drawing["labels"]):
                drawing = candidate
        return drawing

    if pack_components():
        checkpoint()
    # 先拿到较紧凑的可用图，再做更耗时的逐节点搜索。
    for step in (coarse, coarse / 2):
        pulled = pull_branches(step)
        skewed = skew_axes()
        if (squeeze_axes(step) or pulled or skewed) and not checkpoint():
            scene = verified
            positions = scene["positions"]
            value = cost(positions)

    for fraction in (1, 0.57, 0.36, 0.23, 0.14, 0.086, 0.05, 0.029, 0.017):
        step = coarse * fraction
        for _ in range(3):
            if time.monotonic() >= deadline:
                return finish()
            changed = pull_branches(step)
            for node in sorted(positions, key=lambda key: (-math.hypot(*positions[key]), key)):
                if time.monotonic() >= deadline:
                    break
                x, y = positions[node]
                targets = [(x + step * dx, y + step * dy) for dx, dy in directions]
                if neighbors[node]:
                    cx = sum(positions[key][0] for key in neighbors[node]) / len(neighbors[node])
                    cy = sum(positions[key][1] for key in neighbors[node]) / len(neighbors[node])
                    distance = math.hypot(cx - x, cy - y)
                    if distance:
                        t = min(1, step / distance)
                        targets.append((x + t * (cx - x), y + t * (cy - y)))
                moves = []
                for target in targets:
                    trial = {**positions, node: target}
                    candidate_value = cost(trial)
                    if candidate_value < value:
                        moves.append((candidate_value, trial))
                    if len(groups.get(node, ())) > 1:
                        dx, dy = target[0] - x, target[1] - y
                        trial = dict(trial)
                        for attr in groups[node][1:]:
                            ax, ay = positions[attr]
                            trial[attr] = (ax + dx, ay + dy)
                        candidate_value = cost(trial)
                        if candidate_value < value:
                            moves.append((candidate_value, trial))
                for candidate_value, trial in sorted(moves, key=lambda move: move[0]):
                    if try_move(trial, candidate_value):
                        changed = True
                        break

            if not (squeeze_axes(step) or changed):
                break
            checkpoint()
    return finish()


def _convex_embedding_positions(embedding):
    """把外边界放在椭圆上，内部节点取邻居坐标的平均值。"""
    from networkx.algorithms.planar_drawing import triangulate_embedding
    import numpy as np

    graph, face = triangulate_embedding(embedding, fully_triangulate=False)
    radius = len(face) * 0.7
    boundary = {}
    for i, node in enumerate(face):
        angle = math.tau * i / len(face)
        boundary[node] = (radius * math.cos(angle), 0.78 * radius * math.sin(angle))
    interior_nodes = [node for node in graph if node not in boundary]
    inner = {node: i for i, node in enumerate(interior_nodes)}
    if not inner:
        return boundary
    matrix = np.zeros((len(inner), len(inner)))
    target = np.zeros((len(inner), 2))
    for node, i in inner.items():
        for neighbor in graph[node]:
            matrix[i, i] += 1
            if neighbor in boundary:
                target[i] += boundary[neighbor]
            else:
                matrix[i, inner[neighbor]] -= 1
    return {**boundary, **dict(zip(inner, np.linalg.solve(matrix, target)))}


def _find_planar_seed(model, embedding, compact, midpoints, connections, deadline, page_width=None):
    from networkx.algorithms.planar_drawing import combinatorial_embedding_to_pos

    grid = combinatorial_embedding_to_pos(compact)
    triangulated = combinatorial_embedding_to_pos(compact, fully_triangulate=True)
    variants = [(grid, midpoints, 46, 285), (triangulated, midpoints, 46, 285),
                (combinatorial_embedding_to_pos(embedding), None, 46, 285)]
    large = len(model["ents"]) > 15 or len(model["rels"]) > 30
    if large:
        variants.append((_convex_embedding_positions(compact), midpoints, 90, 2700))
    variants.extend(((grid, midpoints, 90, 2000), (triangulated, midpoints, 90, 2000)))
    if large:
        variants.append((grid, midpoints, 140, 4200))
    best = best_rank = None
    for grid, centers, max_side, max_area in variants:
        found = 0
        for angle in (0, math.pi / 2, math.pi / 6, -math.pi / 6):
            cosine, sine = math.cos(angle), math.sin(angle)
            rotated = {node: (x * cosine - y * sine, x * sine + y * cosine) for node, (x, y) in grid.items()}
            xs, ys = zip(*rotated.values())
            cx = (min(xs) + max(xs)) / 2
            cy = (min(ys) + max(ys)) / 2
            # Test a shorter long axis before committing to a wide grid seed.
            span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
            scales = ((0.62, 1), (1, 1)) if span_x > 1.5 * span_y else ((1, 1),)
            for scale in (0.35, 0.5, 0.7, 1.0, 1.4, 2.0, 2.8, 4.0):
                for fx, fy in scales:
                    sx, sy = scale * fx, scale * fy
                    if time.monotonic() >= deadline:
                        return best
                    width = (max(xs) - min(xs)) * sx + 2
                    height = (max(ys) - min(ys)) * sy + 1
                    if max(width, height) > max_side or width * height > max_area:
                        continue
                    positions = {node: ((x - cx) * sx, (y - cy) * sy) for node, (x, y) in rotated.items()}
                    if centers is not None:
                        for node, (a, b) in centers.items():
                            ax, ay = positions[a]
                            bx, by = positions[b]
                            positions[node] = ((ax + bx) / 2, (ay + by) / 2)
                    scene = _planar_scene(model, positions, connections)
                    paths = scene["paths"]
                    if not _clear_planar_geometry(scene):
                        continue
                    if centers is not None:
                        scene = _attach_planar_attributes(model, positions, connections, deadline)
                        if scene is None:
                            continue
                        paths = scene["paths"]
                    labels = layout_cardinality_labels(model, scene, paths)
                    if _cardinality_conflicts(scene["boxes"], paths, labels):
                        continue
                    x0, x1, y0, y1 = _diagram_extents(scene["boxes"], paths, labels)
                    if max(x1 - x0, y1 - y0) > max_side or (x1 - x0) * (y1 - y0) > max_area:
                        continue
                    scene = dict(scene, labels=labels)
                    score = _planar_readability(scene, page_width)
                    if score is not None:
                        rank = _overview_candidate_rank(score)
                        if best_rank is None or rank < best_rank:
                            best, best_rank = scene, rank
                        found += 1
                    break
                else:
                    continue
                break
        if found:
            break
    return best


def _planar_readability(scene, page_width):
    left, right, top, bottom = _diagram_extents(scene["boxes"], scene["paths"], scene["labels"])
    width, height = right - left, bottom - top
    if max(width, height) > 90 or width * height > 2000:
        return None
    lengths = [sum(math.dist(a, b) for a, b in zip(path, path[1:])) for path in scene["paths"]]
    bends = sum(map(_path_bends, scene["paths"]))
    viewport_span = max(width * 0.75, height)
    # 弯折只有带来足够的尺寸收益才值得保留。
    return (max(0, width - page_width) if page_width else 0, viewport_span + 0.3 * bends,
            viewport_span, bends, max(lengths, default=0), width * height, sum(lengths))


def _needs_compaction(score):
    return score is not None and (score[0] > 0 or score[2] > 10
                                  or (score[5] > 36 and (score[2] > 7 or score[4] > 4)))


def _pack_pivot_groups(model, scene, connections, page_width, deadline):
    """用可旋转的分支填补空白，保留原先已通过校验的结果作下限。"""
    positions = scene["positions"]
    links = [(a, b) for _, _, chain in connections for a, b in zip(chain, chain[1:])]
    pivots = _pivot_groups(positions, links)
    best = _planar_readability(scene, page_width)
    if not pivots or best is None:
        return scene
    model = dict(model, rel_w=[box[2] for box in scene["boxes"] if box[4] == "d"])
    original = scene
    swing_deadline = min(time.monotonic() + 1.5, deadline)

    def improves(score):
        return (score is not None and score < best and score[2] <= best[2]
                and score[3] <= best[3] and score[5] <= best[5])

    def finish():
        if scene is not original and time.monotonic() < deadline:
            tightened = _compact_planar_scene(model, scene, connections, page_width, deadline)
            if improves(_planar_readability(tightened, page_width)):
                return tightened
        return scene

    def estimate(points):
        xs, ys = zip(*points.values())
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        return max(width * 0.75, height), width * height

    for _ in range(3):
        changed = False
        ranked = sorted(pivots, key=lambda item: -max(math.dist(positions[item[0]], positions[node])
                                                      for node in item[1]))
        for anchor, group in ranked[:18]:
            if time.monotonic() >= swing_deadline:
                return finish()
            ax, ay = positions[anchor]
            proposals = []
            for angle in (0, 15, -15, 30, -30, 45, -45, 60, -60, 90, -90, 120, -120, 180):
                radians = math.radians(angle)
                for scale in (1.0, 0.85, 0.7):
                    if angle == 0 and scale == 1.0:
                        continue
                    cosine, sine = math.cos(radians) * scale, math.sin(radians) * scale
                    points = dict(positions)
                    for node in group:
                        x, y = positions[node]
                        dx, dy = x - ax, y - ay
                        points[node] = (ax + dx * cosine - dy * sine, ay + dx * sine + dy * cosine)
                    size = estimate(points)
                    if size[0] <= best[2] and size[1] <= best[5]:
                        proposals.append((size, points))
            for _, points in sorted(proposals, key=lambda item: item[0]):
                if time.monotonic() >= swing_deadline:
                    return finish()
                trial = _planar_scene(model, points, connections)
                if not _clear_planar_geometry(trial, previous=scene):
                    continue
                labels = layout_cardinality_labels(model, trial, trial["paths"])
                trial["labels"] = labels
                score = _planar_readability(trial, page_width)
                if improves(score) and not _cardinality_conflicts(trial["boxes"], trial["paths"], labels):
                    positions, scene, best = points, trial, score
                    changed = True
                    break
        if not changed:
            break
    return finish()


def _alternate_embeddings(embedding):
    import networkx as nx

    original_nodes = list(embedding)
    original_edges = list(nx.Graph(embedding).edges())
    for seed in (1, 4, 2, 3):
        rng = random.Random(seed)
        nodes, edges = list(original_nodes), list(original_edges)
        rng.shuffle(nodes)
        rng.shuffle(edges)
        graph = nx.Graph()
        graph.add_nodes_from(nodes)
        graph.add_edges_from(edges)
        _, alternative = nx.check_planarity(graph)
        yield alternative


def _planar_candidate(model, embedding, connections, page_width, render_deadline):
    compact, midpoints = _compact_embedding(model, connections)
    model = dict(model, rel_w=[max(DW, 1.4 * tw(relation["name"]) + 0.14) for relation in model["rels"]])
    start = time.monotonic()
    search_deadline = min(start + 4.0, render_deadline)
    initial = _find_planar_seed(model, embedding, compact, midpoints, connections,
                                min(start + 2.5, search_deadline), page_width)
    candidates = [initial] if initial is not None else []
    if len(model["ents"]) >= 6 or initial is None:
        for alternative in _alternate_embeddings(compact):
            now = time.monotonic()
            if now >= search_deadline:
                break
            scene = _find_planar_seed(model, embedding, alternative, midpoints, connections,
                                      min(now + 0.9, search_deadline), page_width)
            if scene is not None and all(scene["positions"] != item["positions"] for item in candidates):
                candidates.append(scene)

    best, best_score = None, None
    for scene in candidates:
        score = _planar_readability(scene, page_width)
        if score is not None:
            rank = _overview_candidate_rank(score)
            if best_score is None or rank < best_score:
                best, best_score = scene, rank

    # 给通过校验的方案各留一份压缩时间。超时仍可返回已验证的最好结果。
    compact_deadline = min(time.monotonic() + 6.0, render_deadline)
    candidates = sorted((scene for scene in candidates if _needs_compaction(_planar_readability(scene, page_width))),
                        key=lambda scene: _planar_readability(scene, page_width))
    for index, scene in enumerate(candidates):
        now = time.monotonic()
        if now >= compact_deadline:
            break
        share = (compact_deadline - now) / (len(candidates) - index)
        compacted = _compact_planar_scene(model, scene, connections, page_width, now + share)
        score = _planar_readability(compacted, page_width)
        if score is not None:
            rank = _overview_candidate_rank(score)
            if best_score is None or rank < best_score:
                best, best_score = compacted, rank
    return best


def _overview_candidate_rank(score):
    """整图候选同时比较可读尺寸、最长连线和占用面积。"""
    overflow, fitted_span, _, _, longest, area, _ = score
    return overflow, fitted_span + 0.45 * longest + 0.38 * math.sqrt(area), score


def _reference_cuts(model, connections, deadline):
    """只把见证非平面性的端点改接到引用框，优先尝试一个框即可解决的方案。"""
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(("e", i) for i in range(len(model["ents"])))
    for _, entity, chain in connections:
        if entity >= 0:
            nx.add_path(graph, chain)
    choices = [((k, i), (("d", k), ("e", entity)))
               for k, relation in enumerate(model["rels"]) if not relation["self"]
               for i, (entity, _) in enumerate(relation["ends"])]
    cuts = []
    while time.monotonic() < deadline:
        planar, witness = nx.check_planarity(graph, counterexample=True)
        if planar:
            yield tuple(cuts)
            return
        bridges = {frozenset(edge) for edge in nx.bridges(graph)}
        available = [(cut, edge) for cut, edge in choices
                     if witness.has_edge(*edge) and frozenset(edge) not in bridges]
        if not available:
            return
        found = False
        for cut, edge in available:
            if time.monotonic() >= deadline:
                return
            graph.remove_edge(*edge)
            planar, _ = nx.check_planarity(graph)
            graph.add_edge(*edge)
            if planar:
                found = True
                yield (*cuts, cut)
        if found:
            return
        cut, edge = available[0]
        graph.remove_edge(*edge)
        cuts.append(cut)


def _reference_model(model, cuts):
    entities, widths = list(model["ents"]), list(model["ent_w"])
    relations = list(model["rels"])
    for k, i in cuts:
        relation = relations[k]
        ends = list(relation["ends"])
        entity, card = ends[i]
        name = entities[entity]["name"] + "（引用）"
        ends[i] = (len(entities), card)
        entities.append({"name": name, "reference_to": entity})
        widths.append(max(tw(name) + 0.34, 0.62))
        relations[k] = dict(relation, ends=ends, par_k=0, par_n=1)
    return dict(model, ents=entities, ent_w=widths, rels=relations)


def _pinned_reference_scene(model, cuts, positions, page_width, deadline, relation_positions=None):
    # 只在原实体位置固定时寻找引用框的空位。
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if time.monotonic() >= deadline:
            return None
        points = list(positions)
        for k, i in cuts:
            other = [points[entity] for j, (entity, _) in enumerate(model["rels"][k]["ends"])
                     if j != i and entity < len(points)]
            if not other:
                return None
            x = sum(p[0] for p in other) / len(other)
            y = sum(p[1] for p in other) / len(other)
            distance = max(1.5, model["ent_w"][len(points)] + 0.65)
            points.append((x + dx * distance, y + dy * distance))
        scene = compose(model, points, relation_positions)
        paths = route_overview(scene)
        if overview_quality(scene, paths, page_width)[:3] != (0, 0, 0):
            continue
        labels = layout_cardinality_labels(model, scene, paths)
        if not _cardinality_conflicts(scene["boxes"], paths, labels):
            return dict(scene, paths=paths, labels=labels)
    return None


def _reference_overview(model, connections, page_width, deadline, positions, relation_positions=None):
    best, best_score = None, None
    for cuts in itertools.islice(_reference_cuts(model, connections, deadline), 4):
        now = time.monotonic()
        if not cuts or now >= deadline:
            break
        visual = _reference_model(model, cuts)
        embedding, visual_connections = overview_topology(visual)
        if embedding is None:
            continue
        reserve = 2.5 if positions is None and _needs_compaction(best_score) else 0
        attempt_deadline = min(now + 2.3, deadline - reserve)
        if attempt_deadline <= now:
            break
        if positions is None:
            scene = _planar_candidate(visual, embedding, visual_connections, page_width, attempt_deadline)
        else:
            scene = _pinned_reference_scene(visual, cuts, positions, page_width, attempt_deadline, relation_positions)
        if scene is not None:
            score = _planar_readability(scene, page_width)
            if score is not None and (best_score is None or score < best_score):
                best, best_score = (visual, scene), score
    if best is not None and positions is None and _needs_compaction(best_score) and time.monotonic() < deadline:
        visual, scene = best
        compact_model = dict(visual, rel_w=[box[2] for box in scene["boxes"] if box[4] == "d"])
        _, visual_connections = overview_topology(visual)
        compacted = _compact_planar_scene(compact_model, scene, visual_connections, page_width, deadline)
        score = _planar_readability(compacted, page_width)
        if score is not None and score < best_score and score[2] < best_score[2]:
            best = visual, compacted
    return best


def label_hits_shape(label, shape):
    x, y, w, h, kind, _ = shape
    dx = max(0, abs(label[0] - x) - label[2] / 2 - 0.015) / (w / 2)
    dy = max(0, abs(label[1] - y) - label[3] / 2 - 0.015) / (h / 2)
    if kind == "d":
        return dx + dy < 1
    if kind == "a":
        return dx * dx + dy * dy < 1
    return dx < 1 and dy < 1


def layout_cardinality_labels(model, scene, paths=None):
    """按文字包围盒为每个端点找位置，短线优先。"""
    if paths is None:
        paths = route_overview(scene, optimize=False)
    boxes = scene["boxes"]
    segs = [segment for path in paths for segment in _path_segments(path)]
    relation_paths = [[] for _ in model["rels"]]
    for seg, path in zip(scene["segs"], paths):
        if seg[5] >= 0:
            relation_paths[seg[4]].append(path)
    endpoints = []
    for relation, routes in zip(model["rels"], relation_paths):
        for (_, card), path in zip(relation["ends"], routes):
            (nx, ny), (x, y) = path[-2:]
            span = math.hypot(nx - x, ny - y)
            ux, uy = ((nx - x) / span, (ny - y) / span) if span else (1.0, 0.0)
            endpoints.append((span, x, y, ux, uy, card))

    labels = []
    sizes = {card: text_size(card) for card in {item[-1] for item in endpoints}}
    for span, x, y, ux, uy, card in sorted(endpoints, key=lambda item: item[0]):
        w, h = sizes[card]
        w, h = w + 0.035, h + 0.035
        distances = sorted({min(distance, span * 0.85)
                            for distance in (0.10, 0.16, 0.24, 0.34, 0.48, 0.66, 0.85, 1.1, 1.4, 1.8)})
        offsets = (0.10, 0.14, 0.19, 0.25, 0.34, 0.46, 0.60)
        candidates = sorted(((distance, offset) for distance in distances for offset in offsets),
                            key=lambda item: item[0] + 1.5 * item[1])
        best_score, best = None, None
        for distance, offset in candidates:
            for side in (1, -1):
                lx = x + ux * distance - uy * offset * side
                ly = y + uy * distance + ux * offset * side
                bounds = (lx, ly, w, h)
                score = (sum(label_hits_shape(bounds, box) for box in boxes),
                         sum(boxes_overlap(bounds, label, gap=0.015) for label in labels),
                         sum(_seg_hits_rect(*seg[:4], *bounds) for seg in segs))
                if best_score is None or score < best_score:
                    best_score, best = score, (*bounds, card)
            if best_score == (0, 0, 0):
                break
        labels.append(best)
    return labels


def _cardinality_conflicts(boxes, paths, labels):
    segments = [segment for path in paths for segment in _path_segments(path)]
    return sum(
        any(label_hits_shape(label, box) for box in boxes)
        or any(_seg_hits_rect(*segment, *label[:4]) for segment in segments)
        or any(boxes_overlap(label, other) for j, other in enumerate(labels) if i != j)
        for i, label in enumerate(labels)
    )


def _straighten_overview(model, scene, page_width, quality, deadline):
    boxes, edges = _overview_edges(scene)
    paths = list(scene["paths"])
    segments = [_path_segments(path) for path in paths]
    for i, (start, end, source, target, _) in enumerate(edges):
        if time.monotonic() >= deadline:
            break
        path = paths[i]
        bends = _path_bends(path)
        if not bends or (source[5] in scene["self_info"] and target[4] == "e"):
            continue
        occupied = [route for j, route in enumerate(segments) if j != i]

        def conflicts(lines):
            return (_route_box_hits(lines, boxes, source, target, exact=True),
                    sum(_routes_conflict(lines, route) for route in occupied))

        original = conflicts(segments[i])
        waypoints = path[1:-1]
        attempts = [(), *(waypoints[:j] + waypoints[j + 1:] for j in range(len(waypoints)))]
        for remaining in attempts:
            candidate = _visible_path((start, *remaining, end), source, target)
            lines = _path_segments(candidate)
            if not lines or _path_bends(candidate) >= bends:
                continue
            if _route_crosses_itself(lines):
                continue
            if (any(_seg_hits_rect(*line, *source[:4]) for line in lines[1:])
                    or any(_seg_hits_rect(*line, *target[:4]) for line in lines[:-1])):
                continue
            hits, crossings = conflicts(lines)
            if hits > original[0] or crossings > original[1]:
                continue
            trial_paths = paths.copy()
            trial_paths[i] = candidate
            labels = layout_cardinality_labels(model, scene, trial_paths)
            label_conflicts = _cardinality_conflicts(scene["boxes"], trial_paths, labels)
            if label_conflicts > quality["labelConflicts"]:
                continue
            _, hits, crossings, _ = overview_quality(scene, trial_paths, page_width)
            quality = dict(quality, boxHits=int(hits), lineConflicts=int(crossings), labelConflicts=label_conflicts)
            scene = dict(scene, paths=trial_paths, labels=labels, quality=quality)
            paths, segments[i] = trial_paths, lines
            break
    return scene


def _axis_compaction_targets(scene, axis, factor, deadline):
    """固定另一轴，以线性间隔约束联合移动节点，保持边的左右/上下次序。"""
    boxes, edges = _overview_edges(scene)
    lookup = {box[:2]: i for i, box in enumerate(boxes)}
    if len(lookup) != len(boxes):
        return None
    points = [box[:2] for box in boxes]
    links = []
    for path, (_, _, source, target, _) in zip(scene['paths'], edges):
        route = [lookup[source[:2]]]
        for point in path[1:-1]:
            if point not in lookup:
                lookup[point] = len(points)
                points.append(point)
            route.append(lookup[point])
        route.append(lookup[target[:2]])
        links.extend((a, b) for a, b in zip(route, route[1:]) if a != b)
    other = 1 - axis
    coordinates = [point[axis] for point in points]
    constraints = []

    def constrain(terms, distance):
        combined = {}
        for i, weight in terms:
            combined[i] = combined.get(i, 0) + weight
        terms = [(i, weight) for i, weight in combined.items() if abs(weight) > 1e-10]
        norm = sum(weight * weight for _, weight in terms)
        if norm > 1e-10:
            # 近菱形/椭圆角落的合法线不应被矩形外包框强行推远。
            available = sum(coordinates[i] * weight for i, weight in terms)
            constraints.append((terms, min(distance, available), norm))

    for i, box in enumerate(boxes):
        for j, earlier in enumerate(boxes[:i]):
            if abs(box[other] - earlier[other]) < (box[other + 2] + earlier[other + 2]) / 2 + 0.06:
                sign = 1 if coordinates[i] >= coordinates[j] else -1
                constrain([(i, sign), (j, -sign)], (box[axis + 2] + earlier[axis + 2]) / 2 + 0.06)

    def samples(a, b, value):
        span = points[b][other] - points[a][other]
        if abs(span) < 1e-9:
            return [[(a, 1)], [(b, 1)]]
        t = (value - points[a][other]) / span
        return [[(a, 1 - t), (b, t)]]

    for a, b in links:
        low, high = sorted((points[a][other], points[b][other]))
        for i, box in enumerate(boxes):
            if i in (a, b):
                continue
            radius = box[other + 2] / 2 + 0.025
            lower, upper = max(low, box[other] - radius), min(high, box[other] + radius)
            if lower > upper:
                continue
            levels = ({lower + (upper - lower) * step / 12 for step in range(13)}
                      if box[4] == 'a' else {lower, upper})
            levels.add(min(upper, max(lower, box[other])))
            for value in sorted(levels):
                relative = min(1, abs(value - box[other]) / radius)
                half = box[axis + 2] / 2 + 0.025
                if box[4] == 'd':
                    half *= 1 - relative
                elif box[4] == 'a':
                    half *= math.sqrt(max(0, 1 - relative * relative))
                for terms in samples(a, b, value):
                    distance = coordinates[i] - sum(coordinates[j] * weight for j, weight in terms)
                    sign = 1 if distance >= 0 else -1
                    constrain([(i, sign), *((j, -sign * weight) for j, weight in terms)], half + 0.025)

    for k, (a, b) in enumerate(links):
        for c, d in links[:k]:
            if {a, b} & {c, d}:
                continue
            lower = max(min(points[a][other], points[b][other]), min(points[c][other], points[d][other]))
            upper = min(max(points[a][other], points[b][other]), max(points[c][other], points[d][other]))
            if lower > upper:
                continue
            for value in {lower, upper}:
                for first in samples(a, b, value):
                    for second in samples(c, d, value):
                        terms = first + [(i, -weight) for i, weight in second]
                        distance = sum(coordinates[i] * weight for i, weight in terms)
                        sign = 1 if distance >= 0 else -1
                        constrain([(i, sign * weight) for i, weight in terms], 0.025)

    center = (min(coordinates) + max(coordinates)) / 2
    targets = [center + factor * (value - center) for value in coordinates]
    # Dykstra 投影。联合求解间隔约束，紧挨着的节点可以一起移动。
    corrections = [0.0] * len(constraints)
    for iteration in range(140):
        if time.monotonic() >= deadline:
            break
        largest = 0.0
        for k, (terms, distance, norm) in enumerate(constraints):
            old = corrections[k]
            value = sum(targets[i] * weight for i, weight in terms) + old * norm
            correction = max(0, (distance - value) / norm)
            change = old + correction
            for i, weight in terms:
                targets[i] += change * weight
            corrections[k] = -correction
            largest = max(largest, abs(change))
        if largest < 1e-5:
            break
    return {point: (targets[i], point[1]) if axis == 0 else (point[0], targets[i])
            for i, point in enumerate(points)}


def _squeeze_verified_overview(model, scene, page_width, deadline, *, keep_landscape=False):
    """先收紧空白带，再尝试缩短全图间距，保持形状大小和折点数。"""
    best = _planar_readability(scene, page_width)
    if best is None:
        return scene

    def try_move(transform, *, corner_reduction=False, straighten_index=None):
        nonlocal scene, best
        if time.monotonic() >= deadline:
            return False
        trial = dict(scene,
                     ents=[(*transform(box[:2]), *box[2:]) for box in scene["ents"]],
                     boxes=[(*transform(box[:2]), *box[2:]) for box in scene["boxes"]],
                     segs=[(*transform(seg[:2]), *transform(seg[2:4]), *seg[4:]) for seg in scene["segs"]])
        _, old_edges = _overview_edges(scene)
        _, edges = _overview_edges(trial)
        paths = []
        for index, (path, old_edge, (_, _, source, target, _)) in enumerate(zip(scene["paths"], old_edges, edges)):
            waypoints = () if index == straighten_index else tuple(map(transform, path[1:-1]))
            points = (source[:2], *waypoints, target[:2])
            old_points = (old_edge[2][:2], *path[1:-1], old_edge[3][:2])
            dx, dy = points[0][0] - old_points[0][0], points[0][1] - old_points[0][1]
            if source[4] == "d" and target[4] == "e" and source[5] in scene["self_info"]:
                # 自联系的两个入口由原布局分开。沿用端口在框上的偏移，避免重算时挤到同一点。
                start = (path[0][0] + dx, path[0][1] + dy)
                end = (path[-1][0] + target[0] - old_points[-1][0],
                       path[-1][1] + target[1] - old_points[-1][1])
                moved = (start, *points[1:-1], end)
                lines = _path_segments(moved)
                if (not lines or _route_crosses_itself(lines)
                        or any(_line_hits_shape(line, source, padding=-0.001) for line in lines)
                        or any(_line_hits_shape(line, target, padding=-0.001) for line in lines)):
                    return False
                paths.append(moved)
                continue
            if index != straighten_index and all(
                    math.isclose(x - ox, dx, abs_tol=1e-9) and math.isclose(y - oy, dy, abs_tol=1e-9)
                    for (x, y), (ox, oy) in zip(points, old_points)):
                paths.append(tuple((x + dx, y + dy) for x, y in path))
                continue
            moved = _visible_path(points, source, target)
            lines = _path_segments(moved)
            if (not lines or math.dist(moved[0], moved[-1]) < 0.06
                    or any(_path_crosses(line, previous) for i, line in enumerate(lines[2:], 2)
                           for previous in lines[:i - 1])
                    or any(_line_hits_shape(line, source, padding=0) for line in lines[1:])
                    or any(_line_hits_shape(line, target, padding=0) for line in lines[:-1])):
                return False
            paths.append(moved)
        trial["paths"] = paths
        if not _clear_planar_geometry(trial, previous=scene):
            return False
        labels = layout_cardinality_labels(model, trial, paths)
        if _cardinality_conflicts(trial["boxes"], paths, labels):
            return False
        trial["labels"] = labels
        if keep_landscape:
            left, right, top, bottom = _diagram_extents(trial["boxes"], paths, labels)
            if right - left < OVERVIEW_LANDSCAPE_RATIO * (bottom - top):
                return False
        score = _planar_readability(trial, page_width)
        # 局部移动有时先缩短内部连线，下一轮才有空间收紧画布边缘。
        if (score is None or score[0] > best[0] + 1e-8 or score[2] > best[2] + 1e-8 or score[3] > best[3]
                or score[5] > best[5] + 1e-8):
            return False
        if corner_reduction:
            if (score[4] > best[4] * 1.05 or score[6] > best[6] * 1.03
                    or _empty_corner_cost(trial["boxes"]) >= _empty_corner_cost(scene["boxes"]) - 0.04):
                return False
        elif score[3] == best[3] and score[5] + score[6] >= best[5] + best[6] - 1e-8:
            return False
        if "positions" in scene:
            trial["positions"] = {node: transform(point) for node, point in scene["positions"].items()}
        scene, best = trial, score
        return True

    # 固定端点时拉不直的线，有时只需微移一个节点。
    straighten_deadline = min(deadline, time.monotonic() + 0.75)
    _, edges = _overview_edges(scene)
    for index in range(len(edges)):
        if time.monotonic() >= straighten_deadline:
            break
        path = scene["paths"][index]
        if not _path_bends(path):
            continue
        _, _, source, target, movable = edges[index]
        if not movable:
            continue
        # 沿原绕线路径的第一段微移菱形或实体。
        for node, waypoint in ((source, path[1]), (target, path[-2])):
            origin = node[:2]
            distance = math.dist(origin, waypoint)
            if not distance:
                continue
            dx, dy = (waypoint[0] - origin[0]) / distance, (waypoint[1] - origin[1]) / distance
            for step in (0.15, 0.30, 0.50, 0.75):
                if time.monotonic() >= straighten_deadline:
                    break
                point = (origin[0] + step * dx, origin[1] + step * dy)
                if try_move(lambda current: point if current == origin else current, straighten_index=index):
                    _, edges = _overview_edges(scene)
                    break
            else:
                continue
            break

    if keep_landscape:
        # 一条长的连接边常把整条分支推得很远。把分支一起向接入点平移。
        _, edges = _overview_edges(scene)
        links = []
        for path, (_, _, source, target, _) in zip(scene["paths"], edges):
            points = (source[:2], *path[1:-1], target[:2])
            links.extend(zip(points, points[1:]))
        points = {point: point for edge in links for point in edge}
        branches = _bridge_branches(points, links)
        branches.sort(key=lambda item: -math.dist(item[0], item[1]))
        for anchor, root, group in branches[:24]:
            if time.monotonic() >= deadline:
                break
            distance = math.dist(anchor, root)
            if distance < 1.4:
                break
            branch = set(group)
            for fraction in (0.55, 0.35, 0.18):
                dx = fraction * (anchor[0] - root[0])
                dy = fraction * (anchor[1] - root[1])
                if try_move(lambda point: (point[0] + dx, point[1] + dy) if point in branch else point):
                    # 坐标已经改变，下次从新图重新找分支。
                    break
            else:
                continue
            break

    if best[5] > 22 and time.monotonic() < deadline:
        # 在轴向压缩前尝试把外围分支转入角落空白。整组移动保留内部连线。
        branch_deadline = min(deadline, time.monotonic() + 1.1)
        _, edges = _overview_edges(scene)
        centers = {box[:2]: box[2:4] for box in scene["boxes"]}
        # 折点跟随所属分支，包括连接支点与分支的边。
        links = []
        for path, (_, _, source, target, _) in zip(scene["paths"], edges):
            points = (source[:2], *path[1:-1], target[:2])
            links.extend(zip(points, points[1:]))
        proposals = []
        empty = _empty_corner_cost(scene["boxes"])
        for (ax, ay), branch in _pivot_groups(centers, links):
            if time.monotonic() >= branch_deadline:
                break
            transforms = []
            for degrees, reflection in itertools.product((0, 8, -8, 16, -16, 30, -30, 60, -60, 90, -90, 180), (1, -1)):
                angle = math.radians(degrees)
                cosine, sine = math.cos(angle), math.sin(angle)
                transforms.append({(x, y): (ax + (x - ax) * cosine - reflection * (y - ay) * sine,
                                             ay + (x - ax) * sine + reflection * (y - ay) * cosine) for x, y in branch})
            for dx, dy in itertools.product((-0.65, -0.32, -0.14, 0, 0.14, 0.32, 0.65), repeat=2):
                if dx or dy:
                    transforms.append({(x, y): (x + dx, y + dy) for x, y in branch})
            for moves in transforms:
                boxes = [(*moves.get(point, point), *size) for point, size in centers.items()]
                cost, width, height = _corner_metrics(boxes)
                if (cost < empty - 0.04 and width * height <= best[5]
                        and max(width * 0.75, height) <= best[2]):
                    proposals.append((cost + 0.15 * width * height, moves))
        for _, moves in sorted(proposals, key=lambda item: item[0])[:48]:
            if time.monotonic() >= branch_deadline:
                break
            for fraction in (1, 0.35):
                def move_branch(point):
                    x, y = moves.get(point, point)
                    return point[0] + (x - point[0]) * fraction, point[1] + (y - point[1]) * fraction

                if try_move(move_branch, corner_reduction=True):
                    break
            else:
                continue
            break

    # Rotate the entire connected drawing before squeezing a wide fan.
    left, right, top, bottom = _diagram_extents(scene["boxes"], scene["paths"], scene["labels"])
    if max(right - left, bottom - top) > 1.8 * min(right - left, bottom - top):
        for degrees in (30, -30, 60, -60):
            angle = math.radians(degrees)
            cosine, sine = math.cos(angle), math.sin(angle)
            if try_move(lambda point: (point[0] * cosine - point[1] * sine,
                                       point[0] * sine + point[1] * cosine)):
                break

    for _ in range(3):
        changed = False
        for axis in ((1, 0) if keep_landscape else (0, 1)):
            if time.monotonic() >= deadline:
                return scene
            mapping = _axis_compaction_targets(scene, axis, 0.58, deadline)
            if mapping is None:
                continue
            for fraction in (1, 0.72, 0.45, 0.22, 0.10):
                def move(point):
                    target = mapping.get(point, point)
                    return (point[0] + fraction * (target[0] - point[0]),
                            point[1] + fraction * (target[1] - point[1]))

                if try_move(move):
                    changed = True
                    break
            else:
                # 激进目标会激活另一组约束。独立求解温和目标，保留更多可移动空间。
                conservative = _axis_compaction_targets(scene, axis, 0.90, deadline)
                if conservative is not None and try_move(lambda point: conservative.get(point, point)):
                    changed = True
        if not changed:
            break

    for _ in range(2):
        for axis in (0, 1):
            intervals = sorted((box[axis] - box[axis + 2] / 2, box[axis] + box[axis + 2] / 2)
                               for box in scene["boxes"])
            gaps = []
            end = intervals[0][1]
            for left, right in intervals[1:]:
                if left - end > 0.38:
                    gaps.append((end, left))
                end = max(end, right)
            for left, right in sorted(gaps, key=lambda gap: gap[0] - gap[1])[:4]:
                if time.monotonic() >= deadline:
                    return scene
                for fraction in (1, 0.5):
                    shift = (right - left - 0.28) * fraction

                    def close_gap(point):
                        offset = shift * min(1, max(0, (point[axis] - left) / (right - left)))
                        return (point[0] - offset, point[1]) if axis == 0 else (point[0], point[1] - offset)

                    if try_move(close_gap):
                        # 上一次移动改变了后续空白带的坐标，下轮重新测量。
                        break
                else:
                    continue
                break
    for factor in (0.76, 0.86, 0.94):
        for sx, sy in ((factor, factor), (factor, 1), (1, factor)):
            if time.monotonic() >= deadline:
                return scene
            try_move(lambda point: (point[0] * sx, point[1] * sy))
    # 斜向展开的图可沿一轴错开，再缩短局部长边。
    for skew in (-0.26, 0.26):
        try_move(lambda point: (point[0] + skew * point[1], point[1]))
        try_move(lambda point: (point[0], point[1] + skew * point[0]))

    if best[5] > 30 and time.monotonic() < deadline:
        _, edges = _overview_edges(scene)
        centers = {box[:2]: box[2:4] for box in scene["boxes"]}
        branches = _pivot_groups(centers, [(source[:2], target[:2]) for _, _, source, target, _ in edges])
        proposals = []
        for (ax, ay), branch in branches:
            for angle, scale in ((0, 0.72), (30, 0.85), (-30, 0.85), (60, 0.85), (-60, 0.85),
                                 (90, 0.85), (-90, 0.85)):
                cosine, sine = math.cos(math.radians(angle)) * scale, math.sin(math.radians(angle)) * scale
                moves = {(x, y): (ax + (x - ax) * cosine - (y - ay) * sine,
                                  ay + (x - ax) * sine + (y - ay) * cosine) for x, y in branch}
                trial_boxes = [(*moves.get(point, point), *size) for point, size in centers.items()]
                left = min(x - w / 2 for x, _, w, _ in trial_boxes)
                right = max(x + w / 2 for x, _, w, _ in trial_boxes)
                top = min(y - h / 2 for _, y, _, h in trial_boxes)
                bottom = max(y + h / 2 for _, y, _, h in trial_boxes)
                span = max(0.75 * (right - left), bottom - top)
                area = (right - left) * (bottom - top)
                if span <= best[2] and area < best[5]:
                    proposals.append((area, moves))
        for _, moves in sorted(proposals, key=lambda item: item[0])[:18]:
            if time.monotonic() >= deadline or try_move(lambda point: moves.get(point, point)):
                break

    for _ in range(6):
        _, edges = _overview_edges(scene)
        ranked = sorted(zip(scene["paths"], edges),
                        key=lambda item: -sum(math.dist(a, b) for a, b in zip(item[0], item[0][1:])))
        for path, (_, _, source, target, _) in ranked[:12]:
            if time.monotonic() >= deadline:
                return scene
            if math.dist(path[0], path[-1]) < 0.9:
                break
            for moving, fixed in ((source, target), (target, source)):
                origin = moving[:2]
                dx, dy = fixed[0] - origin[0], fixed[1] - origin[1]
                for x_step, y_step in ((0.25, 0.25), (0.25, 0), (0, 0.25), (0.12, 0.12)):
                    point = (origin[0] + x_step * dx, origin[1] + y_step * dy)
                    if try_move(lambda current: point if current == origin else current):
                        break
                else:
                    continue
                break
            else:
                continue
            # 每轮以当前几何重新计算候选，避免继续用移动前的端点。
            break

    return scene


def _empty_corner_cost(boxes):
    return _corner_metrics(boxes)[0]


def _corner_metrics(boxes):
    """用四角到最近图元的距离评估边缘留白，量纲与画布面积相同。"""
    bounds = [(x - w / 2, x + w / 2, y - h / 2, y + h / 2) for x, y, w, h, *_ in boxes]
    outer = (min(box[0] for box in bounds), max(box[1] for box in bounds),
             min(box[2] for box in bounds), max(box[3] for box in bounds))
    cost = sum(min((box[i] - outer[i]) ** 2 + (box[j] - outer[j]) ** 2 for box in bounds)
               for i in (0, 1) for j in (2, 3))
    return cost, outer[1] - outer[0], outer[3] - outer[2]


def _grouped_overview(model, page_width, group_size=4):
    """按共享实体组成小组。跨组端点用同名引用框，组内连线保持直线。"""
    entities, widths = list(model["ents"]), list(model["ent_w"])
    relations = list(model["rels"])
    rel_widths = [max(DW, 1.4 * tw(relation["name"]) + 0.14) for relation in relations]
    pending = set(range(len(relations)))
    groups = []
    while pending:
        counts = Counter(entity for k in pending for entity in {i for i, _ in relations[k]["ends"]})
        anchor = max(counts, key=lambda entity: (counts[entity], -entity))
        owned = sorted(k for k in pending if any(i == anchor for i, _ in relations[k]["ends"]))
        groups.extend((anchor, owned[i:i + group_size]) for i in range(0, len(owned), group_size))
        pending.difference_update(owned)

    used = {anchor for anchor, _ in groups}
    anchors_seen = set()

    def reference(entity):
        name = entities[entity]["name"] + "（引用）"
        entities.append({"name": name, "reference_to": entity})
        widths.append(max(tw(name) + 0.34, 0.62))
        return len(entities) - 1

    blocks, anchor_links = [], {}
    for anchor, owned in groups:
        left = reference(anchor) if anchor in anchors_seen else anchor
        anchors_seen.add(anchor)
        diamond_left = widths[left] + 0.9
        right_edge = diamond_left + max(rel_widths[k] for k in owned) + 0.9
        height = 0.0
        points = {}
        block_width = right_edge
        for row, k in enumerate(owned):
            relation = relations[k]
            ends = list(relation["ends"])
            anchor_index = next(j for j, (entity, _) in enumerate(ends) if entity == anchor)
            ends[anchor_index] = (left, ends[anchor_index][1])
            leaves = []
            for j, (entity, card) in enumerate(relation["ends"]):
                if j != anchor_index:
                    visual_entity = reference(entity) if entity in used else entity
                    used.add(entity)
                    ends[j] = (visual_entity, card)
                    leaves.append((("e", visual_entity), widths[visual_entity]))
            leaves.extend((("a", k, j), w) for j, w in enumerate(model["attr_w"][k]))
            row_height = len(leaves) * 0.76
            points["d", k] = (diamond_left + rel_widths[k] / 2, height + row_height / 2)
            anchor_links[k] = (left, (row - (len(owned) - 1) / 2) * EH * 0.7 / max(1, len(owned) - 1))
            # 对齐叶节点左边界，确保同一联系的扇形连线按次序展开。
            for j, (node, width) in enumerate(leaves):
                points[node] = (right_edge + width / 2, height + (j + 0.5) * 0.76)
                block_width = max(block_width, right_edge + width)
            height += row_height + 0.22
            relations[k] = dict(relation, ends=ends, self=False)
        points["e", left] = (widths[left] / 2, (height - 0.22) / 2)
        blocks.append((block_width, height, points))

    for i in sorted(set(range(len(model["ents"]))) - used):
        blocks.append((widths[i], EH + 0.22, {("e", i): (widths[i] / 2, EH / 2)}))
    visual = dict(model, ents=entities, ent_w=widths, rels=relations, rel_w=rel_widths)
    _, connections = overview_topology(visual)
    blocks.sort(key=lambda block: -block[1])
    area = sum((w + 0.55) * (h + 0.55) for w, h, _ in blocks)
    best, best_score = None, None
    for scale in (0.9, 1.15, 1.4):
        row_limit = max(max(w for w, _, _ in blocks), math.sqrt(area) * scale)
        x = y = row_height = 0.0
        positions = {}
        for w, h, points in blocks:
            if x and x + w > row_limit:
                x, y, row_height = 0.0, y + row_height + 0.55, 0.0
            positions.update((node, (x + px, y + py)) for node, (px, py) in points.items())
            x += w + 0.55
            row_height = max(row_height, h)
        scene = _planar_scene(visual, positions, connections)
        _, edges = _overview_edges(scene)
        paths = []
        for (_, _, source, target, _), (k, entity, _) in zip(edges, connections):
            anchor, offset = anchor_links[k]
            if entity == anchor:
                paths.append(((source[0] - source[2] / 2, source[1]),
                              (target[0] + target[2] / 2, target[1] + offset)))
            else:
                end = (target[0] - target[2] / 2, target[1])
                paths.append((_edge_port(source[:2], end, source), end))
        scene["paths"] = paths
        if not _clear_planar_geometry(scene):
            continue
        labels = layout_cardinality_labels(visual, scene, scene["paths"])
        if _cardinality_conflicts(scene["boxes"], scene["paths"], labels):
            continue
        scene["labels"] = labels
        score = _planar_readability(scene, page_width)
        if score is not None and (best_score is None or score < best_score):
            best, best_score = scene, score
    if best is not None:
        quality = dict(planar=True, overlaps=0, boxHits=0, lineConflicts=0, labelConflicts=0)
        return dict(best, quality=quality, display_model=visual)
    if group_size > 1:
        return _grouped_overview(model, page_width, group_size // 2)
    return None


def _radial_forest_positions(trees, roots, widths, spacing, aspect, layer, phase):
    """按分支所需宽度分配扇区，逐层向外摆放节点。"""
    positions, offset = {}, 0.0
    for tree, root in zip(trees, roots):
        weights = {}

        def measure(node, parent):
            children = sorted(child for child in tree[node] if child != parent)
            weight = max(widths[node] + 0.20, sum(measure(child, node) for child in children))
            weights[node] = weight
            return weight

        def place(node, parent, angle, sector, radius):
            positions[node] = (aspect * radius * math.cos(angle), radius * math.sin(angle))
            children = sorted(child for child in tree[node] if child != parent)
            total = sum(weights[child] for child in children)
            # 非根节点的出边向外发散，避免大扇区绕回内圈。
            spread = min(sector, 1.5) if parent is not None else sector
            left = angle - spread / 2
            for child in children:
                width = spread * weights[child] / total
                distance = radius + layer if parent is not None else spacing
                place(child, node, left + width / 2, width, distance)
                left += width

        measure(root, None)
        place(root, None, phase, math.tau, 0)
        left = min(positions[node][0] - widths[node] / 2 for node in tree)
        right = max(positions[node][0] + widths[node] / 2 for node in tree)
        for node in tree:
            x, y = positions[node]
            positions[node] = x - left + offset, y
        offset += right - left + 0.6
    return positions


def _connected_overview_fallback(model, page_width, deadline):
    """保留每个连通分量的生成树，仅将成环的端点改接同名叶节点。"""
    import networkx as nx

    components = nx.utils.UnionFind()
    cuts = []
    for k, relation in enumerate(model["rels"]):
        diamond = ("d", k)
        for i, (entity, _) in enumerate(relation["ends"]):
            node = ("e", entity)
            if components[diamond] == components[node]:
                cuts.append((k, i))
            else:
                components.union(diamond, node)
    visual = _reference_model(model, cuts)
    visual["rels"] = [dict(relation, self=False) for relation in visual["rels"]]
    visual["rel_w"] = [max(DW, 1.4 * tw(relation["name"]) + 0.14) for relation in visual["rels"]]
    embedding, connections = overview_topology(visual)
    forest = nx.Graph(embedding)
    widths = {("e", i): width for i, width in enumerate(visual["ent_w"])}
    widths.update({("d", k): width for k, width in enumerate(visual["rel_w"])})
    widths.update({("a", k, i): width for k, attrs in enumerate(visual["attr_w"]) for i, width in enumerate(attrs)})
    trees = [forest.subgraph(nodes) for nodes in nx.connected_components(forest)]
    roots = [min(nx.center(tree)) for tree in trees]
    best, best_score = None, None

    def consider(candidate):
        nonlocal best, best_score
        candidate["labels"] = layout_cardinality_labels(visual, candidate, candidate["paths"])
        if _cardinality_conflicts(candidate["boxes"], candidate["paths"], candidate["labels"]):
            return
        score = _planar_readability(candidate, page_width)
        if score is not None:
            rank = _overview_candidate_rank(score)
            if best_score is None or rank < best_score:
                best, best_score = candidate, rank

    radial = itertools.product((3.5, 4.2, 4.9, 5.6), (1.35, 1.6), (0.9, 1.0), (0, math.pi / 6, math.pi / 3))
    for spacing, aspect, layer, phase in radial:
        if time.monotonic() >= deadline - 0.9:
            break
        positions = _radial_forest_positions(trees, roots, widths, spacing, aspect, layer, phase)
        candidate = _planar_scene(visual, positions, connections)
        if _clear_planar_geometry(candidate):
            consider(candidate)

    layered = itertools.product((0.30, 0.65), (1.20, 1.75, 2.45), ("balanced", "down", "right"))
    for gap, layer, direction in layered:
        if time.monotonic() >= deadline - (1.15 if best is not None else 0):
            break
        horizontal = direction == "right"
        positions, offset = {}, 0.0
        for tree, root in zip(trees, roots):
            def place(node, parent, left, depth, step=1):
                children = sorted(neighbor for neighbor in tree[node] if neighbor != parent)
                right = left
                for child in children:
                    right += place(child, node, right, depth + step, step)
                width = max(right - left, (EH if horizontal else widths[node]) + gap)
                center = left + width / 2
                positions[node] = (depth * layer, center) if horizontal else (center, depth * layer)
                return width

            if direction == "balanced" and tree.degree(root) > 1:
                # 根的相邻分支分别排在两侧，避免所有叶子挤在同一条长边。
                without_root = nx.restricted_view(tree, [root], [])
                branches = sorted(((len(nx.node_connected_component(without_root, node)), node) for node in tree[root]),
                                  key=lambda item: (-item[0], item[1]))
                sides = [[], []]
                loads = [0, 0]
                for size, node in branches:
                    side = 0 if loads[0] <= loads[1] else 1
                    sides[side].append(node)
                    loads[side] += size
                span = widths[root]
                for children, step in zip(sides, (-1, 1)):
                    before = set(positions)
                    width = 0.0
                    for node in children:
                        width += place(node, root, width, step, step)
                    for node in positions.keys() - before:
                        x, y = positions[node]
                        positions[node] = x - width / 2, y
                    span = max(span, width)
                positions[root] = (0, 0)
                for node in tree:
                    x, y = positions[node]
                    positions[node] = x + offset + span / 2, y
                offset += span + gap
            else:
                offset += place(root, None, offset, 0) + gap
        candidate = _planar_scene(visual, positions, connections)
        if not _clear_planar_geometry(candidate):
            # 接近密集的一层时垂直进框，避免斜线擦到相邻图元。
            axis = 0 if horizontal else 1
            boxes, edges = _overview_edges(candidate)
            lead = min(layer * 0.48, max(box[axis + 2] for box in boxes) / 2 + 0.10)
            paths = []
            for _, _, source, target, _ in edges:
                child = max((source, target), key=lambda box: abs(box[axis]))
                parent = target if child is source else source
                point = list(child[:2])
                point[axis] += math.copysign(lead, parent[axis] - child[axis])
                paths.append(_visible_path((source[:2], tuple(point), target[:2]), source, target))
            straight = candidate["paths"]
            # 先只绕开真正挡住连线的图元，其他线保持直连。
            candidate["paths"] = [routed if _route_box_hits(_path_segments(path), boxes, source, target, exact=True)
                                  else path for path, routed, (_, _, source, target, _) in zip(straight, paths, edges)]
            if not _clear_planar_geometry(candidate):
                candidate["paths"] = paths
                if not _clear_planar_geometry(candidate):
                    continue
        consider(candidate)
    if best is not None:
        quality = dict(planar=True, overlaps=0, boxHits=0, lineConflicts=0, labelConflicts=0)
        best = dict(best, display_model=visual, quality=quality)
        best = _straighten_overview(visual, best, page_width, quality, min(deadline, time.monotonic() + 0.4))
        if time.monotonic() < deadline:
            left, right, top, bottom = _diagram_extents(best["boxes"], best["paths"], best["labels"])
            landscape = page_width is None and right - left >= OVERVIEW_LANDSCAPE_RATIO * (bottom - top)
            return _squeeze_verified_overview(visual, best, page_width, deadline, keep_landscape=landscape)
        return best
    return None


def _verify_overview(model, scene, page_width, *, try_planar, render_deadline=math.inf, topology=None,
                     relation_positions=None):
    manual_error = ("当前位置无法保持图形和连线清晰，请把联系菱形移到空白处或恢复自动排版"
                    if relation_positions else "这组实体位置无法保持零交叉，请换个位置或恢复自动排版")
    squeeze_deadline = render_deadline
    if try_planar:
        render_deadline -= 4.8
    embedding, connections = topology if topology is not None else overview_topology(model)
    if embedding is None:
        deadline = min(time.monotonic() + 9.0, render_deadline)
        referenced = _reference_overview(model, connections, page_width, deadline,
                                         None if try_planar else scene["P"], relation_positions)
        if referenced is None:
            if try_planar:
                connected = _connected_overview_fallback(model, page_width, min(squeeze_deadline, time.monotonic() + 3))
                if connected is not None:
                    return connected
            message = ("当前规格在排版时间内未找到可验证的零交叉方案，请缩小业务范围后重试"
                       if try_planar else manual_error)
            raise SpecError(message)
        visual, scene = referenced
        if try_planar and _needs_compaction(_planar_readability(scene, page_width)) and "positions" in scene:
            _, visual_connections = overview_topology(visual)
            scene = _pack_pivot_groups(visual, scene, visual_connections, page_width,
                                      min(time.monotonic() + 3.0, render_deadline))
        quality = {"planar": True, "overlaps": 0, "boxHits": 0, "lineConflicts": 0, "labelConflicts": 0}
        scene = dict(scene, quality=quality, display_model=visual)
        scene = _straighten_overview(visual, scene, page_width, quality,
                                     min(time.monotonic() + 0.8, render_deadline))
        if try_planar:
            scene = _squeeze_verified_overview(visual, scene, page_width, min(time.monotonic() + 4.8, squeeze_deadline))
        return scene
    paths = scene.get("paths")
    if paths is None:
        paths = route_overview(scene)
    labels = layout_cardinality_labels(model, scene, paths)
    overlaps, hits, conflicts, _ = overview_quality(scene, paths, page_width)
    label_conflicts = _cardinality_conflicts(scene["boxes"], paths, labels)
    scene = dict(scene, paths=paths, labels=labels)
    clear = not (overlaps or hits or conflicts or label_conflicts)
    current = _planar_readability(scene, page_width) if clear else None
    needs_layout = current is None or _needs_compaction(current)
    if try_planar and needs_layout:
        planar = _planar_candidate(model, embedding, connections, page_width, render_deadline)
        score = _planar_readability(planar, page_width) if planar is not None else None
        if score is not None and (current is None or (
                _overview_candidate_rank(score) < _overview_candidate_rank(current)
                and score[2] <= current[2] * 1.08 and score[5] <= current[5])):
            scene = (_pack_pivot_groups(model, planar, connections, page_width,
                                        min(time.monotonic() + 3.0, render_deadline))
                     if _needs_compaction(score) else planar)
            paths, labels = scene["paths"], scene["labels"]
            overlaps = hits = conflicts = label_conflicts = 0
    if hits or conflicts:
        deadline = min(time.monotonic() + 3.0, render_deadline)
        if time.monotonic() < deadline:
            refined = _refine_overview_routes(scene, paths, deadline)
            _, new_hits, new_conflicts, _ = overview_quality(scene, refined, page_width)
            if (new_hits, new_conflicts) < (hits, conflicts):
                new_labels = layout_cardinality_labels(model, scene, refined)
                new_label_conflicts = _cardinality_conflicts(scene["boxes"], refined, new_labels)
                if new_label_conflicts <= label_conflicts:
                    hits, conflicts, label_conflicts = new_hits, new_conflicts, new_label_conflicts
                    scene.update(paths=refined, labels=new_labels)
    quality = {"planar": True, "overlaps": int(overlaps), "boxHits": int(hits),
               "lineConflicts": int(conflicts), "labelConflicts": int(label_conflicts)}
    scene = _straighten_overview(model, dict(scene, quality=quality), page_width, quality,
                                 min(time.monotonic() + 0.8, render_deadline))
    if try_planar and "positions" not in scene and not any(
            scene["quality"][key] for key in ("overlaps", "boxHits", "lineConflicts", "labelConflicts")):
        score = _planar_readability(scene, page_width)
        if _needs_compaction(score):
            for axis in (0, 1):
                folded = _fold_empty_bands(scene, axis)
                if folded is scene:
                    continue
                folded = _straighten_overview(model, folded, page_width, folded["quality"],
                                              min(time.monotonic() + 0.4, render_deadline))
                folded_score = _planar_readability(folded, page_width)
                if folded_score is not None and folded_score < score:
                    scene, score = folded, folded_score
    if try_planar and not any(scene["quality"][key]
                              for key in ("overlaps", "boxHits", "lineConflicts", "labelConflicts")):
        scene = _squeeze_verified_overview(model, scene, page_width, min(time.monotonic() + 4.8, squeeze_deadline))
    if any(scene["quality"][key] for key in ("lineConflicts", "boxHits", "overlaps", "labelConflicts")):
        if try_planar:
            connected = _connected_overview_fallback(model, page_width, min(squeeze_deadline, time.monotonic() + 3))
            if connected is not None:
                return connected
        message = ("当前规格在排版时间内未找到可验证的零交叉方案，请缩小业务范围后重试"
                   if try_planar else manual_error)
        raise SpecError(message)
    return scene


def _diagram_extents(boxes, paths, labels, margin=0.08):
    bounds = boxes + labels
    xs = [x + side * w / 2 for x, _, w, *_ in bounds for side in (-1, 1)]
    ys = [y + side * h / 2 for _, y, _, h, *_ in bounds for side in (-1, 1)]
    for path in paths:
        xs.extend(point[0] for point in path)
        ys.extend(point[1] for point in path)
    return min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin


OVERVIEW_LANDSCAPE_RATIO = 1.25


def _transform_overview(scene, transform):
    trial = dict(scene,
                 ents=[(*transform(box[:2]), *box[2:]) for box in scene["ents"]],
                 boxes=[(*transform(box[:2]), *box[2:]) for box in scene["boxes"]],
                 segs=[(*transform(seg[:2]), *transform(seg[2:4]), *seg[4:]) for seg in scene["segs"]])
    _, edges = _overview_edges(trial)
    trial["paths"] = [(_edge_port(source[:2], transform(path[0]), source),
                       *map(transform, path[1:-1]),
                       _edge_port(target[:2], transform(path[-1]), target))
                      for path, (_, _, source, target, _) in zip(scene["paths"], edges)]
    if "positions" in scene:
        trial["positions"] = {node: transform(point) for node, point in scene["positions"].items()}
    return trial


def _ease_overview_spacing(model, scene, page_width, deadline):
    """给拥挤的整体图适度留白，保留节点大小和连线形状。"""
    if time.monotonic() >= deadline:
        return scene

    def crowding(drawing):
        boxes = drawing["boxes"]
        adjacent = sum(boxes_overlap(box, other, gap=0.14)
                       for i, box in enumerate(boxes) for other in boxes[:i])
        short = sum(sum(math.dist(a, b) for a, b in zip(path, path[1:])) < 0.20
                    for path in drawing["paths"])
        return adjacent + short

    original = crowding(scene)
    if original < 2:
        return scene
    best, best_crowding = scene, original
    bends = sum(map(_path_bends, scene["paths"]))
    for scale in (1.04, 1.08, 1.12):
        if time.monotonic() >= deadline:
            break
        trial = _transform_overview(scene, lambda point: (point[0] * scale, point[1] * scale))
        remaining = crowding(trial)
        if remaining >= best_crowding or sum(map(_path_bends, trial["paths"])) > bends:
            continue
        if not _clear_planar_geometry(trial):
            continue
        paths = trial["paths"]
        labels = layout_cardinality_labels(model, trial, paths)
        if _cardinality_conflicts(trial["boxes"], paths, labels):
            continue
        trial["labels"] = labels
        x0, x1, y0, y1 = _diagram_extents(trial["boxes"], paths, labels)
        if (page_width is not None and x1 - x0 > page_width) or _planar_readability(trial, page_width) is None:
            continue
        best, best_crowding = trial, remaining
        if remaining * 2 <= original:
            break
    return best


def _orient_overview_landscape(model, scene, deadline):
    """横向摆放节点和折点，图形、文字保持正向。"""
    left, right, top, bottom = _diagram_extents(scene["boxes"], scene["paths"], scene["labels"])
    if right - left >= OVERVIEW_LANDSCAPE_RATIO * (bottom - top):
        return scene

    best, best_rank = scene, None
    for scale in (1, 1.08, 1.18):
        for cosine, sine in ((0, 1), (0, -1), (0.5, math.sqrt(0.75)), (0.5, -math.sqrt(0.75))):
            if time.monotonic() >= deadline:
                return best

            def orient(point):
                x, y = point
                return scale * (cosine * x - sine * y), scale * (sine * x + cosine * y)

            trial = _transform_overview(scene, orient)
            paths = trial["paths"]
            if not _clear_planar_geometry(trial):
                continue
            labels = layout_cardinality_labels(model, trial, paths)
            if _cardinality_conflicts(trial["boxes"], paths, labels):
                continue
            trial["labels"] = labels
            x0, x1, y0, y1 = _diagram_extents(trial["boxes"], paths, labels)
            score = _planar_readability(trial, None)
            if score is None or x1 - x0 < OVERVIEW_LANDSCAPE_RATIO * (y1 - y0):
                continue
            rank = _overview_candidate_rank(score)
            if best_rank is None or rank < best_rank:
                best, best_rank = trial, rank
        if best_rank is not None:
            break
    return best


def draw_er(model, scene, out, margin=0.08, page_width=None, image_format=None, manual=False,
            canvas_ratio=None):
    boxes = scene["boxes"]
    display = scene.get("display_model", model)
    rels, ENT = display["rels"], display["ents"]
    paths = scene.get("paths")
    if paths is None:
        paths = route_overview(scene)
    labels = scene.get("labels")
    if labels is None:
        labels = layout_cardinality_labels(display, scene, paths)
    x0, x1, y0, y1 = _diagram_extents(boxes, paths, labels, margin)
    Wd, Hd = x1 - x0, y1 - y0
    content_frame = {"x": x0, "y": y0, "width": Wd, "height": Hd}
    if manual and (max(Wd, Hd) > 96 or Wd * Hd > 2200):
        raise SpecError("调整后的画布太大，请把实体移近一些")
    target_width, target_height, render_dpi = _canvas_dimensions(Wd, Hd, image_format, canvas_ratio)
    x0 -= (target_width - Wd) / 2
    y0 -= (target_height - Hd) / 2
    Wd, Hd = target_width, target_height
    x1, y1 = x0 + Wd, y0 + Hd
    fig = plt.figure(figsize=(Wd, Hd), dpi=render_dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.axis("off")
    for path in paths:
        x, y = zip(*path)
        ax.plot(x, y, color="black", lw=LINE_W, zorder=1)
    for x, y, _, _, card in labels:
        ax.text(x, y, card, fontproperties=FP, ha="center", va="center", zorder=3)

    # ---------- 图形 ----------
    for (cx, cy, w, h, kind, key) in boxes:
        if kind == "e":
            style = "--" if "reference_to" in ENT[key] else "-"
            ax.add_patch(Rectangle((cx - w / 2, cy - h / 2), w, h, fc="white", ec="black",
                                   lw=LINE_W, linestyle=style, zorder=4))
            ax.text(cx, cy, ENT[key]["name"], fontproperties=FP, ha="center", va="center", zorder=5)
        elif kind == "d":
            ax.add_patch(Polygon([(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)],
                                 fc="white", ec="black", lw=LINE_W, zorder=4))
            ax.text(cx, cy, rels[key]["name"], fontproperties=FP, ha="center", va="center", zorder=5)
    for bi, k, name in scene["attrs"]:
        cx, cy, w, h, _, _ = boxes[bi]
        ax.add_patch(Ellipse((cx, cy), w, h, fc="white", ec="black", lw=LINE_W, zorder=4))
        ax.text(cx, cy, name, fontproperties=FP, ha="center", va="center", zorder=5)
    fig.savefig(out, format=image_format, dpi=render_dpi, facecolor="white")
    plt.close(fig)
    print("已生成", out, "(%.2f x %.2f 英寸)" % (Wd, Hd))
    if page_width and Wd > page_width:
        print("  注意：该图宽 %.2f 英寸，超过 --page-width %.2f，放进竖版页面会被缩小（字号变小），建议放横版页面。"
              % (Wd, page_width))
    return {
        "x": x0, "y": y0, "width": Wd, "height": Hd,
        "contentFrame": content_frame,
        "quality": scene.get("quality"),
        **({"referenceCount": len(ENT) - len(model["ents"])} if display is not model else {}),
        "entities": [
            {"entity": entity["name"], "x": x, "y": y, "width": w, "height": h}
            for entity, (x, y, w, h) in zip(model["ents"], scene["ents"])
        ],
        "relations": [
            {"index": key, "name": rels[key]["name"], "x": x, "y": y, "width": w, "height": h}
            for x, y, w, h, kind, key in boxes if kind == "d"
        ],
    }


# ============================== 出图入口 ==============================
def safe(s):
    return re.sub(r'[\\/:*?"<>|\s]+', "", s)


def _aligned_binary_overview(model, connections, page_width):
    relations = model["rels"]
    if len(model["ents"]) != 2 or len(relations) != 1 or relations[0]["self"] or len(relations[0]["attrs"]) > 1:
        return None
    diamond_width = max(DW, 1.4 * tw(relations[0]["name"]) + 0.14)
    layout_model = dict(model, rel_w=[diamond_width])
    gap = 0.34
    offset = (DH + EH) / 2 + gap
    positions = {("e", 0): (0, offset), ("e", 1): (0, -offset), ("d", 0): (0, 0)}
    if model["attr_w"][0]:
        positions["a", 0, 0] = ((diamond_width + model["attr_w"][0][0]) / 2 + gap, 0)
    scene = _planar_scene(layout_model, positions, connections)
    if not _clear_planar_geometry(scene):
        return None
    labels = layout_cardinality_labels(model, scene, scene["paths"])
    if _cardinality_conflicts(scene["boxes"], scene["paths"], labels):
        return None
    if page_width is not None:
        left, right, *_ = _diagram_extents(scene["boxes"], scene["paths"], labels)
        if right - left > page_width:
            return None
    return dict(scene, labels=labels, quality=dict(planar=True, overlaps=0, boxHits=0,
                                                    lineConflicts=0, labelConflicts=0))


def layout_overview(model, *, page_width=None, effort=1.5, seed=0, time_limit=45.0,
                    parallel=True, positions=None, render_deadline=math.inf, relation_positions=None):
    model = dict(model, ent_w=[max(tw(e["name"]) + 0.34, 0.62) for e in model["ents"]],
                 attr_w=[[tw(a) + 0.26 for a in r["attrs"]] for r in model["rels"]])
    topology = overview_topology(model)
    if positions is None:
        aligned = _aligned_binary_overview(model, topology[1], page_width)
        if aligned is not None:
            return model, aligned
        scene = {}
        if topology[0] is not None:
            print("正在自动布局整体 E-R 图……")
            if not parallel:
                reserve = 13.8 + min(3.0, len(model["rels"]) / 8)
                time_limit = min(time_limit, max(0, render_deadline - time.monotonic() - reserve))
            scene = layout_er(model, page_width=page_width, effort=effort, seed=seed,
                              time_limit=time_limit, parallel=parallel)
    else:
        scene = compose(model, positions, relation_positions)
        if any(boxes_overlap(entity, other) for i, entity in enumerate(scene["ents"])
               for other in scene["ents"][:i]):
            raise SpecError("实体矩形重叠，请把实体放到空白处")
    landscape = positions is None and page_width is None
    finishing_time = (0.65 if landscape else 0) + (0.60 if positions is None else 0)
    scene = _verify_overview(model, scene, page_width, try_planar=positions is None,
                             render_deadline=render_deadline - finishing_time, topology=topology,
                             relation_positions=relation_positions)
    if landscape:
        scene = _orient_overview_landscape(scene.get("display_model", model), scene,
                                           min(render_deadline, time.monotonic() + 0.65))
    if positions is None and any(map(_path_bends, scene["paths"])):
        scene = _straighten_overview(scene.get("display_model", model), scene, page_width, scene["quality"],
                                     min(render_deadline - 0.25, time.monotonic() + 0.35))
    if positions is None:
        scene = _ease_overview_spacing(scene.get("display_model", model), scene, page_width,
                                       min(render_deadline, time.monotonic() + 0.25))
    if not _clear_planar_geometry(scene) or _cardinality_conflicts(scene["boxes"], scene["paths"], scene["labels"]):
        raise SpecError("最终布局仍有连线或标注冲突，请重新排版")
    return model, scene


def render_spec(model, output_dir=None, *, image_format="png", font=None, dpi=300,
                chapter="1", only=None, page_width=None, effort=1.5, seed=0,
                time_limit=45.0, parallel=True, positions=None, layout_budget=20.0, canvas_ratio=None,
                relation_positions=None):
    """绘制已规范化的规格。未指定目录时，在返回值中提供图片字节。"""
    global DPI, _fig0, _renderer
    render_deadline = math.inf if parallel else time.monotonic() + layout_budget
    DPI = dpi
    init_font(font)
    diagrams = []

    def draw(filename, entity, draw_image, *args, **kwargs):
        destination = os.path.join(output_dir, filename) if output_dir is not None else BytesIO()
        layout = draw_image(*args, destination, image_format=image_format, **kwargs)
        diagram = {"filename": filename, "entity": entity}
        if layout is not None:
            diagram["layout"] = layout
        if isinstance(destination, BytesIO):
            diagram["content"] = destination.getvalue()
            destination.close()
        diagrams.append(diagram)

    try:
        if output_dir is not None:
            os.makedirs(output_dir, exist_ok=True)
        if only != "er":
            for i, e in enumerate(model["ents"], 1):
                filename = f"图{chapter}-{i}_{safe(e['name'])}实体属性图.{image_format}"
                draw(filename, e["name"], draw_entity_fig, e["name"], e["attrs"], canvas_ratio=canvas_ratio)
        if only != "entities":
            model, scene = layout_overview(model, page_width=page_width, effort=effort, seed=seed,
                                           time_limit=time_limit, parallel=parallel, positions=positions,
                                           render_deadline=render_deadline, relation_positions=relation_positions)
            filename = f"图{chapter}-{len(model['ents']) + 1}_整体ER图.{image_format}"
            draw(filename, None, draw_er, model, scene, page_width=page_width, manual=positions is not None,
                 canvas_ratio=canvas_ratio)
        return diagrams
    finally:
        plt.close(_fig0)
        _fig0 = _renderer = None


# ============================== 命令行 ==============================
def build_arg_parser():
    ap = argparse.ArgumentParser(description="通用 E-R 图生成器：自然语言 → 实体属性图 + 整体 E-R 图",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="示例：python er_generator.py \"做一个图书管理系统……\"")
    ap.add_argument("text", nargs="?", help="课题的自然语言描述（也可用 --text-file，或不填进入交互输入）")
    ap.add_argument("--text-file", help="从文本文件读取课题描述")
    ap.add_argument("--spec", help="直接使用 JSON 规格文件（不调用大模型）")
    ap.add_argument("--prompt-only", action="store_true", help="只打印给大模型的提示词，不出图（适合用网页版大模型）")
    ap.add_argument("--out", default="figures", help="输出目录（默认 figures）")
    ap.add_argument("--font", help="字体文件路径（推荐宋体 simsun.ttc）")
    ap.add_argument("--chapter", default="1", help="图号前缀的章号，默认 1 → 图1-1、图1-2 ……")
    ap.add_argument("--format", default="png", choices=["png", "svg", "pdf"], help="输出格式，默认 png")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--page-width", type=float, default=None,
                    help="希望整体 E-R 图不超过的宽度（英寸），竖版 A4 正文约 6.3")
    ap.add_argument("--effort", type=float, default=1.5, help="布局搜索力度，默认 1.5；图很复杂或有交叉时调大（3~5），想更快可调小")
    ap.add_argument("--time-limit", type=float, default=45.0, help="整体 E-R 图布局搜索的时间预算（秒），默认 45")
    ap.add_argument("--seed", type=int, default=0, help="布局随机种子，换一个数可得到不同排布")
    ap.add_argument("--only", choices=["er", "entities"], help="只画整体 E-R 图 / 只画实体属性图")
    ap.add_argument("--provider", choices=["anthropic", "openai"], help="大模型接口类型")
    ap.add_argument("--model", help="模型名")
    ap.add_argument("--base-url", help="接口地址（OpenAI 兼容服务需要）")
    ap.add_argument("--api-key", help="API Key（也可用环境变量）")
    return ap


def read_text(args):
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            return f.read().strip()
    if args.text:
        return args.text.strip()
    print("请输入课题描述（可多行，输入完成后空一行并回车结束）：")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip() and lines:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def main():
    args = build_arg_parser().parse_args()

    if args.prompt_only:
        text = read_text(args) if not args.spec else ""
        print("=" * 20, "系统提示词（system）", "=" * 20)
        print(SYSTEM_PROMPT)
        print("=" * 20, "用户消息（user）", "=" * 20)
        print("请为下面的课题设计 E-R 模型：\n\n" + text)
        return

    if args.spec:
        with open(args.spec, encoding="utf-8") as f:
            raw = json.load(f)
        model = normalize_spec(raw)
    else:
        text = read_text(args)
        if not text:
            sys.exit("没有输入课题描述。")
        try:
            model, raw = spec_from_text(text, args)
        except LLMError as e:
            sys.exit(str(e))
        os.makedirs(args.out, exist_ok=True)
        spec_path = os.path.join(args.out, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        print("已保存规格：", spec_path, "（可手动修改后用 --spec 重画）")

    n = len(model["ents"])
    print("\n课题：%s｜实体 %d 个｜联系 %d 个" % (model["title"] or "（未命名）", n, len(model["rels"])))
    for e in model["ents"]:
        print("  - %s：%s" % (e["name"], "、".join(("[%s]" % a) if pk else a for a, pk in e["attrs"])))
    for r in model["rels"]:
        ends = "—".join("%s(%s)" % (model["ents"][e]["name"], c) for e, c in r["ends"])
        print("  * %s：%s%s" % (r["name"], ends, ("  属性：" + "、".join(r["attrs"])) if r["attrs"] else ""))
    print()

    render_spec(model, args.out, image_format=args.format, font=args.font, dpi=args.dpi,
                chapter=args.chapter, only=args.only, page_width=args.page_width,
                effort=args.effort, seed=args.seed, time_limit=args.time_limit)
    print("\n全部完成，图片在文件夹：", os.path.abspath(args.out))


if __name__ == "__main__":
    main()
