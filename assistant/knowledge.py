"""Product FAQ knowledge (migrated from frontend keyword table)."""
from __future__ import annotations

from .types import Locale

_FAQ: dict[Locale, list[dict[str, object]]] = {
    "zh": [
        {
            "keys": ["开始", "怎么用", "入门", "如何", "流程", "start", "how", "begin"],
            "answer": (
                "三步就够：① 点「开始绘图」用自然语言描述系统；② 在工作台核对实体、联系和基数；"
                "③ 排版后下载 PNG 或 SVG。也可以先点「体验示例」看选课系统怎么出图。"
            ),
        },
        {
            "keys": ["还能改", "能改吗", "怎么改", "如何编辑", "怎么编辑", "怎么微调", "怎么拖", "edit", "change", "drag"],
            "answer": (
                "能改。生成结果是表单不是死图：加字段、改主键、调基数、拖动布局都可以，"
                "改完重新排版即可，不用重写描述。"
            ),
        },
        {
            "keys": ["导出", "下载", "糊", "png", "svg", "word", "export", "download", "blurry"],
            "answer": "贴进 Word 用 PNG，按当前画布出图；要打印或继续放大用 SVG，矢量放大不失真。两种格式都在预览区一键下载。",
        },
        {
            "keys": ["语义沙", "物质", "未来", "人工智能", "ai", "semantic sand", "sand"],
            "answer": (
                "「语义沙」是 ERFlow 对 AI × E-R 的想象：描述像沙粒一样被聚成可编辑的结构——"
                "节点是实体，细丝是联系，还能继续生长和改写。你现在用的工作台，就是把这句话落成可用的工具。"
            ),
        },
        {
            "keys": ["多大", "上限", "多少", "实体", "联系", "limit", "max", "size"],
            "answer": "单个系统最多 24 个实体、40 条联系，每个实体或联系最多 12 个属性。超出时工作台会说明原因。",
        },
        {
            "keys": ["保存", "上传", "隐私", "本地", "save", "privacy", "upload", "local"],
            "answer": "描述只用于当次生成，不写入数据库；规格与图默认只在你浏览器里。用量页只统计请求数和 token，不保留原文。",
        },
        {
            "keys": ["sgi", "通向"],
            "answer": "「通向SGI」是 ERFlow 的品牌去向。需要外链时，把目标网址配进站点配置即可。",
        },
        {
            "keys": ["登录", "注册", "账号", "login", "sign in", "register", "account"],
            "answer": "生成与排版需要登录。欢迎页右上角可进入登录；未登录时仍可浏览介绍，并先体验页面说明。",
        },
    ],
    "en": [
        {
            "keys": ["开始", "怎么用", "入门", "如何", "流程", "start", "how", "begin"],
            "answer": (
                "Three steps: ① Start drawing and describe your system; ② Review entities, relations, "
                "and cardinality; ③ Lay out and download PNG/SVG. Or try the course sample first."
            ),
        },
        {
            "keys": ["还能改", "能改吗", "怎么改", "如何编辑", "怎么编辑", "怎么微调", "怎么拖", "edit", "change", "drag"],
            "answer": (
                "Yes. You edit forms, not a dead image — add fields, change keys, tweak cardinality, "
                "drag layout, then re-layout."
            ),
        },
        {
            "keys": ["导出", "下载", "糊", "png", "svg", "word", "export", "download", "blurry"],
            "answer": "Use PNG for Word; use SVG for print or further scaling. Both download under the preview.",
        },
        {
            "keys": ["语义沙", "物质", "未来", "人工智能", "ai", "semantic sand", "sand"],
            "answer": (
                "“Semantic Sand” is ERFlow’s take on AI × E-R: description grains gather into editable "
                "structure — nodes as entities, threads as relations — that you can keep reshaping."
            ),
        },
        {
            "keys": ["多大", "上限", "多少", "实体", "联系", "limit", "max", "size"],
            "answer": (
                "Up to 24 entities and 40 relations per system; up to 12 attributes each. "
                "The workbench explains when you exceed them."
            ),
        },
        {
            "keys": ["保存", "上传", "隐私", "本地", "save", "privacy", "upload", "local"],
            "answer": (
                "Descriptions are for that generation only and aren’t stored in a database. "
                "Specs and figures stay in your browser. Usage counts requests and tokens, not the raw text."
            ),
        },
        {
            "keys": ["sgi", "通向"],
            "answer": "“To SGI” is ERFlow’s brand direction. Configure an external URL in site settings when you need a link.",
        },
        {
            "keys": ["登录", "注册", "账号", "login", "sign in", "register", "account"],
            "answer": (
                "Generation and layout need sign-in. Use the top-right on the welcome page. "
                "You can still browse without signing in."
            ),
        },
    ],
}

_SCOPE = {
    "zh": (
        "这个问题不在语义沙当前能力范围内。"
        "我可以回答：怎么开始、能不能改图、怎么导出、系统上限、语义沙是什么、登录与隐私；"
        "也可以受控检索公开百科（例如「什么是 UML」）；"
        "在工作台里还可以帮你改 E-R 基数或检查模型。"
        "敏感时政与有害内容仍会拒绝。"
    ),
    "en": (
        "That’s outside Semantic Sand’s current scope. "
        "I can help with getting started, editing, export, limits, what Semantic Sand is, sign-in and privacy; "
        "controlled encyclopedia lookup (e.g. “What is UML?”); "
        "and on the workbench, E-R cardinality edits or model checks. "
        "Sensitive politics and harmful content are still refused."
    ),
}

_EMPTY = {
    "zh": "可以说说你想了解的：怎么开始、能不能改图、怎么导出，或「语义沙」是什么。",
    "en": "Ask about getting started, editing, export, or what Semantic Sand is.",
}


def lookup_faq(message: str, locale: Locale) -> str | None:
    text = message.strip().lower()
    if not text:
        return None
    for item in _FAQ.get(locale) or _FAQ["zh"]:
        keys = item["keys"]
        assert isinstance(keys, list)
        if any(str(key).lower() in text for key in keys):
            return str(item["answer"])
    return None


def scope_refuse(locale: Locale) -> str:
    return _SCOPE.get(locale) or _SCOPE["zh"]


def empty_prompt(locale: Locale) -> str:
    return _EMPTY.get(locale) or _EMPTY["zh"]
