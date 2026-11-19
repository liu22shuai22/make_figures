"""Fixed inputs for the use-case layout benchmark."""

import json
from pathlib import Path
from random import Random


def spec(title, actors, dependencies=()):
    cases = dict.fromkeys(
        [case for _, _, links in actors for case in links]
        + [case for _, source, target in dependencies for case in (source, target)]
    )
    return {
        "title": title,
        "actors": [{"name": name, "kind": kind} for name, kind, _ in actors],
        "useCases": list(cases),
        "links": [{"actor": name, "useCase": case} for name, _, links in actors for case in links],
        "dependencies": [{"kind": kind, "from": source, "to": target} for kind, source, target in dependencies],
    }


def shuffled(raw, seed):
    rng = Random(seed)
    result = dict(raw)
    for key in ("actors", "useCases", "links", "dependencies"):
        result[key] = list(raw[key])
        rng.shuffle(result[key])
    return result


def four_workflows():
    actors, deps = [], []
    for index in range(4):
        first, second, shared_a, shared_b, shared_c, check = (
            f"业务{index + 1}·{step}" for step in ("申请", "办理", "查询", "撤销", "归档", "核验")
        )
        actors.extend([
            (f"经办员{index + 1}", "primary", [first, shared_a, shared_b, shared_c]),
            (f"审核员{index + 1}", "secondary", [second, shared_b, shared_c, shared_a]),
        ])
        deps.extend([
            ("include", first, check), ("include", second, check), ("extend", shared_a, second),
        ])
    return spec("多组独立业务", actors, deps)


def fixtures():
    library = json.loads(
        (Path(__file__).resolve().parents[1] / "examples" / "library-usecase.json").read_text(encoding="utf-8")
    )
    identity = spec("图书借阅系统", [
        ("读者", "primary", ["续借", "借书", "还书"]),
        ("管理员", "secondary", ["借书", "还书", "核验读者身份"]),
    ], [("include", "借书", "核验读者身份"), ("include", "还书", "核验读者身份")])
    yield "regression", "library", library
    for seed in range(5):
        yield "regression", f"library-order-{seed}", shuffled(library, seed)
    yield "regression", "library-identity", identity
    yield "regression", "library-identity-order-3", shuffled(identity, 3)
    yield "regression", "launch-dependency-fan", spec("航天发射场调度与发射流程系统", [
        ("指挥员", "primary", ["发起发射审批", "下达点火指令"]),
        ("神经监护员", "primary", ["下达点火指令"]),
        ("测控工程师", "primary", ["开启全频段信号监测", "紧急中止任务"]),
        ("雷达阵列", "primary", ["推送雷达数据"]),
        ("遥测传感器", "primary", ["推送遥测数据"]),
        ("国家空域管制中心", "primary", ["申请空域净空"]),
        ("定时守护进程", "primary", ["系统心跳检测"]),
        ("气象卫星系统", "secondary", ["气象条件评估"]),
    ], [
        ("include", "发起发射审批", "燃料加注安全检查"), ("include", "开启全频段信号监测", "设备自检"),
        ("include", "发起发射审批", "气象条件评估"), ("extend", "气象条件评估", "推迟发射预警"),
        ("include", "执行点火流程", "倒计时广播"), ("include", "执行点火流程", "导流槽降温控制"),
        ("include", "执行点火流程", "申请空域净空"), ("extend", "执行点火流程", "紧急点火预案"),
        ("extend", "执行点火流程", "远地点自动启动"), ("include", "系统心跳检测", "日志自动归档"),
    ])
    yield "regression", "four-workflows", four_workflows()

    hotel = spec("酒店入住服务", [
        ("旅客", "primary", ["预约客房", "办理入住", "办理退房", "申请发票"]),
        ("前台", "secondary", ["办理入住", "办理退房", "核验身份", "调整房间"]),
        ("支付网关", "secondary", ["核对支付状态", "办理押金退款"]),
    ], [
        ("include", "办理入住", "核验身份"), ("include", "办理入住", "核对支付状态"),
        ("include", "办理退房", "办理押金退款"), ("extend", "调整房间", "办理入住"),
    ])
    yield "evaluation", "hotel-shared-cases", hotel
    yield "evaluation", "hotel-shared-cases-order-3", shuffled(hotel, 3)
    yield "evaluation", "clinic-dependency-chain", spec("检验结果交付系统", [
        ("检验员", "primary", ["接收检验订单", "提交初步结果", "发布正式报告"]),
        ("临床医生", "secondary", ["接收检验订单", "查看正式报告"]),
        ("消息平台", "secondary", ["投递报告通知"]),
    ], [
        ("include", "提交初步结果", "核对样本编号"), ("include", "核对样本编号", "查询登记信息"),
        ("include", "查询登记信息", "校验检验项目适用范围"), ("include", "发布正式报告", "投递报告通知"),
        ("extend", "暂停发布等待重新核验标本", "发布正式报告"),
    ])
    yield "evaluation", "warehouse-fan", spec("仓储出库系统", [
        ("仓管员", "primary", ["创建出库任务", "申请配送车辆"]),
        ("司机", "secondary", ["确认装车完成"]),
    ], [
        ("include", "创建出库任务", "执行出库检查"),
        ("include", "执行出库检查", "校验库存余额"), ("include", "执行出库检查", "核验货位标签"),
        ("include", "执行出库检查", "检查物品保质期"), ("include", "执行出库检查", "核对装车单据"),
        ("extend", "记录货物异常", "执行出库检查"),
    ])
    # K3,3 is a stress case for reporting unavoidable crossings in a single-view embedding.
    yield "stress", "shared-nonplanar", spec("多岗共用操作", [
        (actor, "primary", ["查询记录", "修改记录", "归档记录"]) for actor in ("柜员", "主管", "审计员")
    ])
    yield "stress", "dense-shared-24-cases", spec("联合业务处理系统", [
        (f"业务岗{actor + 1}", "primary", [f"流程{(actor * 2 + offset) % 24 + 1}处理" for offset in range(4)])
        for actor in range(12)
    ], [
        ("include", f"流程{source + 1}处理", f"流程{target + 1}处理")
        for source in range(12) for target in (source + 1, source + 7)
    ])
