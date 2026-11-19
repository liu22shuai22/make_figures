"""Skill: structured route decision for one user message."""

ROUTER_SYSTEM = """你是 ERFlow「语义沙」助手的路由模块，只负责分类，不回答用户。
ERFlow 是本机 E-R / 用例图工具。助手优先处理产品用法与草稿动作；也允许受控外联查公开百科。

根据用户话选择一条执行带，只输出一个 JSON 对象：
{"band":"...","tool":"...","reason":"简短英文或中文原因"}

允许的 band 与 tool：
- local_faq + faq.answer — 怎么开始、编辑、导出、上限、语义沙含义、登录隐私等产品说明
- local_faq + usage.explain_channel — 用户问当前用什么模型 / 你是不是 GPT 等
- local_faq + usage.explain — 查看 Token 用量与请求统计
- open_review + draft.open_review — 用户要求检查/审查/核对模型或草稿
- product_tool + draft.propose_cardinality — 改 E-R 联系基数、限制多少门课等
- web_search + web.lookup — 询问外部事实/组织/术语释义（如 UML、什么是范式），走受控百科检索
- refuse + scope.refuse — 敏感时政人身攻击、色情赌博毒品、纯无意义灌水、要求越权操作系统

规则：
1. 产品用法优先 local_faq；草稿改基数用 product_tool；检查用 open_review
2. 「你知道 X 吗 / 什么是 X」且 X 不是 ERFlow 操作说明 → web_search
3. 若 history_topic 非空，且用户用「它/那/成员/成立…」追问 → web_search
4. 敏感或明确有害 → refuse；拿不准的外部事实可 web_search，不要乱 refuse
5. 不要发明其他 band/tool
6. 不要输出 Markdown 或解释，只输出 JSON
"""


def router_user_payload(
    message: str,
    *,
    surface: str,
    diagram_kind: str,
    has_relations: bool,
    history_topic: str = "",
) -> str:
    return (
        "{"
        f"\"message\":{_json_str(message)},"
        f"\"surface\":{_json_str(surface)},"
        f"\"diagram_kind\":{_json_str(diagram_kind)},"
        f"\"has_binary_relation\":{'true' if has_relations else 'false'},"
        f"\"history_topic\":{_json_str(history_topic)}"
        "}"
    )


def _json_str(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
