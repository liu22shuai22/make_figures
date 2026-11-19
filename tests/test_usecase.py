import base64
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
import numpy as np

import er_generator as er
import usecase_generator as uc
from api import render_request_body, render_usecase_in_worker, worker_script


LIBRARY = Path(__file__).resolve().parents[1] / "examples" / "library-usecase.json"


def make_spec(title, associations, dependencies):
    names = dict.fromkeys([
        *(case for _, cases in associations for case in cases),
        *(name for _, start, end in dependencies for name in (start, end)),
    ])
    return {
        "title": title,
        "actors": [{"name": actor, "kind": "primary" if i == 0 else "secondary"}
                   for i, (actor, _) in enumerate(associations)],
        "useCases": [{"name": case} for case in names],
        "links": [{"actor": actor, "useCase": case} for actor, cases in associations for case in cases],
        "dependencies": [{"kind": kind, "from": start, "to": end} for kind, start, end in dependencies],
    }


class UseCaseTests(unittest.TestCase):
    def test_compaction_removes_empty_bands_without_geometry_conflicts(self):
        model = uc.normalize_usecase_spec(make_spec("Independent tasks", [
            ("Reader", ["Query"]), ("Operator", ["Publish"]), ("Auditor", ["Check"]),
        ], []))
        er.init_font()
        try:
            positions = {"Reader": (-5, 0), "Query": (0, 0),
                         "Operator": (-5, 10), "Publish": (0, 10),
                         "Auditor": (-5, 20), "Check": (0, 20)}
            original = uc._usecase_candidate(model, positions, route=False)
            uc._finish_usecase_scene(model, original)
            compact = uc._compact_usecase_scene(model, original)
            self.assertFalse(any(compact["useCaseQuality"].values()))
            def area(scene):
                x, y, right, bottom = scene["bounds"]
                return (right - x) * (bottom - y)
            self.assertLess(area(compact), area(original) * 0.7)
            self.assertTrue(all(len(path) == 2 for path in compact["paths"]))
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_shared_roles_with_dependencies_stay_straight(self):
        from benchmarks.usecase_fixtures import spec, shuffled
        raw = spec("智慧城市交通指挥系统",[
        ("城市大脑AI系统","primary",["生成绿波带预案"]),
        ("120急救系统","primary",["触发紧急避让","推送救护车位置"]),
        ("交通信号灯硬件","secondary",["切换绿灯","执行绿波带放行","中断信号灯状态"]),
        ("普通交警","primary",["录入违章罚单","发起恶劣天气应急预案","手动控制路口红绿灯","登录"]),
        ("指挥中心调度员","primary",["手动控制路口红绿灯","登录","下达交通管制指令","确认绿波带预案"])],
        [("include","录入违章罚单","调取车辆档案"),("include","触发紧急避让","切换绿灯"),("include","触发紧急避让","中断信号灯状态"),("include","执行绿波带放行","中断信号灯状态"),("include","下达交通管制指令","全城广播")])
        er.init_font()
        try:
            for source in (raw, shuffled(raw, 7)):
                model = uc.normalize_usecase_spec(source)
                scene = uc.layout_usecase(model)
                self.assertFalse(any(scene["useCaseQuality"].values()), scene["useCaseQuality"])
                paths = [*scene["paths"], *(dep["points"] for dep in scene["dep_paths"])]
                self.assertTrue(all(er._path_bends(path) == 0 for path in paths))
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_automatic_geometry_is_invariant_to_spec_order(self):
        from benchmarks.usecase_fixtures import shuffled

        raw = json.loads(LIBRARY.read_text(encoding="utf-8"))

        def geometry(spec):
            model = uc.normalize_usecase_spec(spec)
            scene = uc.layout_usecase(model)
            actors = [a["name"] for a in model["actors"]]
            cases = [c["name"] for c in model["use_cases"]]
            return (scene["system"], scene["bounds"],
                    {actors[i]: box for i, *box in scene["actors"]},
                    dict(zip(cases, scene["use_cases"], strict=True)),
                    {(actors[e["actor"]], cases[e["use_case"]]): path
                     for e, path in zip(model["links"], scene["paths"], strict=True)},
                    {(cases[e["from"]], cases[e["to"]], e["kind"]): path
                     for e, path in zip(model["dependencies"], scene["dep_paths"], strict=True)})

        er.init_font()
        try:
            original = geometry(raw)
            for seed in range(5):
                with self.subTest(seed=seed):
                    self.assertEqual(original, geometry(shuffled(raw, seed)))
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_geometry_counts_are_serializable_with_numpy_coordinates(self):
        raw = make_spec("Test", [("Reader", ["Borrow", "Return"])], [])
        model = uc.normalize_usecase_spec(raw)
        er.init_font()
        try:
            coords = {"Reader": (-2, 0), "Borrow": (0, 0), "Return": (np.float64(0), np.float64(0.3))}
            scene = uc._usecase_candidate(model, coords, route=False)
            uc._finish_usecase_scene(model, scene)
            self.assertEqual(scene["useCaseQuality"]["overlaps"], 1)
            self.assertTrue(all(type(count) is int for count in scene["useCaseQuality"].values()))
            json.dumps(scene["useCaseQuality"])
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_generated_spec_validates_connectivity_and_cycles(self):
        spec = make_spec("Test", [("Reader", ["Borrow", "Renew"])], [("include", "Borrow", "Validate")])
        spec["reviewNotes"] = ["Confirm whether renewal requires identity verification."]
        _, parsed = uc._parse_generated_usecase(json.dumps(spec))
        self.assertEqual(parsed["reviewNotes"], spec["reviewNotes"])
        self.assertEqual(parsed["dependencies"], spec["dependencies"])

        compact = dict(spec, useCases=["Borrow", "Renew", "Validate"],
                       links=[["Reader", "Borrow"], ["Reader", "Renew"]],
                       dependencies=[["include", "Borrow", "Validate"]])
        _, expanded = uc._parse_generated_usecase(json.dumps(compact))
        self.assertEqual(expanded, parsed)
        compact["links"] = [["Reader"]]
        with self.assertRaisesRegex(er.SpecError, "links"):
            uc._parse_generated_usecase(json.dumps(compact))

        isolated = dict(spec, useCases=[*spec["useCases"], {"name": "Orphan"}])
        with self.assertRaisesRegex(er.SpecError, "Orphan"):
            uc._parse_generated_usecase(json.dumps(isolated))

        cycle = dict(spec, dependencies=[*spec["dependencies"], {"kind": "include", "from": "Validate", "to": "Borrow"}])
        with self.assertRaisesRegex(er.SpecError, "include"):
            uc._parse_generated_usecase(json.dumps(cycle))

    def test_generated_dependency_can_restore_an_omitted_use_case(self):
        draft = {
            "title": "电商购物系统",
            "actors": [{"name": "买家", "kind": "primary"}],
            "useCases": ["在线支付", "查询订单"],
            "links": [["买家", "在线支付"], ["买家", "查询订单"]],
            "dependencies": [["include", "在线支付", "验证支付密码"]],
        }
        _, spec = uc._parse_generated_usecase(json.dumps(draft))
        self.assertEqual(spec["useCases"], [
            {"name": "在线支付"}, {"name": "查询订单"}, {"name": "验证支付密码"},
        ])
        self.assertEqual(spec["dependencies"], [
            {"kind": "include", "from": "在线支付", "to": "验证支付密码"},
        ])
        self.assertEqual(len(spec["links"]), 2)
        manual = dict(spec, useCases=spec["useCases"][:-1])
        with self.assertRaisesRegex(er.SpecError, "验证支付密码"):
            uc.normalize_usecase_spec(manual)
        invalid = dict(draft, dependencies=[["include", "提交订单", "验证支付密码"]])
        with self.assertRaisesRegex(er.SpecError, "提交订单"):
            uc._parse_generated_usecase(json.dumps(invalid))

        result = render_usecase_in_worker({"spec": spec, "format": "png", "aspect": "auto"})
        self.assertTrue(result["overview"]["url"].startswith("data:image/png;base64,"))

    def test_usecase_review_checks_structure_before_business_semantics(self):
        from fastapi import HTTPException
        from api import UseCaseReviewRequest, assistant_review_usecase

        draft = make_spec("请假审批", [("部门经理", ["审批请假"])],
                          [("include", "审批请假", "部门经理")])
        draft["useCases"] = [{"name": "审批请假"}]
        with self.assertRaises(HTTPException) as failure:
            assistant_review_usecase(UseCaseReviewRequest(text="部门经理审批请假。", spec=draft))
        self.assertEqual(failure.exception.status_code, 422)
        self.assertIn("包含参与者「部门经理」", failure.exception.detail)

    def test_usecase_review_requires_a_verbatim_evidence_quote(self):
        from model_review import parse_usecase_review

        text = "员工提交请假。部门经理审批请假。"
        finding = {
            "kind": "responsibility", "disposition": "issue", "evidence": "部门经理审批请假",
            "message": "审批职责分配有误", "suggestion": "将部门经理关联到审批请假。",
        }
        result = parse_usecase_review(json.dumps({"findings": [finding]}), text)
        self.assertEqual(result[0].model_dump(), finding)
        self.assertEqual(parse_usecase_review('{"findings":[]}', text), [])
        finding["evidence"] = "人事主管审批请假"
        with self.assertRaisesRegex(er.SpecError, "原文中不存在"):
            parse_usecase_review(json.dumps({"findings": [finding]}), text)

    def test_library_stays_straight_and_exports_in_both_formats(self):
        raw = json.loads(LIBRARY.read_text(encoding="utf-8"))
        er.init_font()
        try:
            model = uc.normalize_usecase_spec(raw)
            scene = uc.layout_usecase(model)
            self.assertEqual(len(scene["paths"]), 7)
            self.assertEqual(len(scene["dep_paths"]), 2)
            self.assertFalse(any(scene["useCaseQuality"].values()))
            self.assertTrue(all(len(path) == 2 for path in scene["paths"]))
            self.assertTrue(all(len(dep["points"]) == 2 for dep in scene["dep_paths"]))
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

        for fmt in ("png", "svg"):
            with self.subTest(format=fmt):
                result = render_usecase_in_worker({"spec": raw, "format": fmt, "aspect": "16:9"})
                image = base64.b64decode(result["overview"]["url"].split(",", 1)[1])
                if fmt == "png":
                    width, height = struct.unpack(">II", image[16:24])
                    self.assertEqual(width * 9, height * 16)
                else:
                    width, height = map(float, ET.fromstring(image).attrib["viewBox"].split()[2:])
                    self.assertAlmostEqual(width / height, 16 / 9, places=6)

    def test_library_identity_check_linked_to_librarian_stays_straight(self):
        spec = make_spec("图书借阅系统", [
            ("读者", ["续借", "借书", "还书"]),
            ("管理员", ["借书", "还书", "核验读者身份"]),
        ], [("include", "借书", "核验读者身份"), ("include", "还书", "核验读者身份")])
        er.init_font()
        try:
            for cases in (spec["useCases"], list(reversed(spec["useCases"]))):
                model = uc.normalize_usecase_spec(dict(spec, useCases=cases))
                scene = uc.layout_usecase(model)
                self.assertFalse(any(scene["useCaseQuality"].values()), scene["useCaseQuality"])
                self.assertEqual(len(scene["paths"]), 6)
                self.assertEqual(len(scene["dep_paths"]), 2)
                self.assertTrue(all(len(path) == 2 for path in scene["paths"]))
                self.assertTrue(all(len(dep["points"]) == 2 for dep in scene["dep_paths"]))
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_candidate_search_preserves_routes_and_does_not_worsen_geometry(self):
        fixtures = [
            make_spec("售后", [
                ("买家", ["申请退款", "查询进度", "撤销申请"]),
                ("客服", ["审核申请", "查询进度", "处理申诉"]),
                ("支付平台", ["执行退款"]),
            ], [("include", "申请退款", "验证订单"), ("include", "审核申请", "验证订单")]),
            make_spec("请假审批", [
                ("员工", ["提交请假", "查询进度", "撤回请假"]),
                ("主管", ["审批请假", "查询进度", "填写意见"]),
                ("人事", ["归档记录", "查询进度"]),
            ], [("include", "提交请假", "核算余额"), ("include", "审批请假", "核算余额"),
                ("extend", "填写意见", "审批请假")]),
            make_spec("共享审批", [
                ("发起人", ["提交申请", "查询记录", "撤回申请", "补充材料", "确认收件"]),
                ("审核员", ["查询记录", "复核材料", "确认收件", "审批申请", "通知结果"]),
                ("归档员", ["查询记录", "归档申请", "审批申请", "复核材料"]),
            ], [("include", "提交申请", "校验申请"), ("include", "审批申请", "校验申请"),
                ("include", "复核材料", "校验申请"), ("include", "通知结果", "生成通知"),
                ("include", "归档申请", "写入档案")]),
        ]
        er.init_font()
        try:
            for raw in fixtures:
                with self.subTest(title=raw["title"]):
                    model = uc.normalize_usecase_spec(raw)
                    before = uc._usecase_candidate(model, route=False)
                    after = uc.layout_usecase(model)
                    expected = uc._finish_usecase_scene(model, before)
                    actual = uc._finish_usecase_scene(model, after)
                    self.assertLessEqual(actual, expected)
                    self.assertEqual(len(after["paths"]), len(model["links"]))
                    self.assertEqual(len(after["dep_paths"]), len(model["dependencies"]))
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_store_keeps_shared_use_cases_visible_with_straight_links(self):
        raw = make_spec("电商购物系统", [
            ("系统管理员", ["处理异常订单", "审核卖家资质"]),
            ("卖家", ["订单发货", "下架商品", "修改商品信息", "发布新商品", "登录系统", "申请退款"]),
            ("买家", ["登录系统", "查看订单状态", "在线支付", "提交订单", "加入购物车",
                    "浏览商品详情", "搜索商品", "注册账号"]),
        ], [("include", "在线支付", "验证支付密码")])
        for actor in raw["actors"]:
            actor["kind"] = "primary"
        worker = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(worker_script)],
            input=render_request_body(raw, "png", kind="usecase"),
            capture_output=True, timeout=30,
        )
        self.assertEqual(worker.returncode, 0, worker.stderr.decode("utf-8", errors="replace"))
        result = json.loads(worker.stdout)
        self.assertTrue(result["overview"]["url"].startswith("data:image/png;base64,"))
        quality = result["layout"]["useCaseQuality"]
        self.assertFalse(any(quality.values()), quality)
        model = uc.normalize_usecase_spec(raw)
        er.init_font()
        try:
            scene = uc.layout_usecase(model)
            self.assertEqual(len(scene["paths"]), len(raw["links"]))
            self.assertEqual(len(scene["dep_paths"]), len(raw["dependencies"]))
            self.assertTrue(all(len(path) == 2 for path in scene["paths"]))
            self.assertTrue(all(len(dep["points"]) == 2 for dep in scene["dep_paths"]))
            x0, y0, x1, y1 = scene["bounds"]
            self.assertGreaterEqual(x1 - x0, y1 - y0)
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_store_spreads_mixed_roles_with_a_busy_buyer(self):
        raw = make_spec("电商购物系统", [
            ("买家", ["搜索商品", "浏览商品详情", "加入购物车", "提交订单", "在线支付",
                    "查看订单状态", "申请退款", "注册账号", "登录"]),
            ("卖家", ["登录", "发布新商品", "修改商品信息", "下架商品", "订单发货"]),
            ("系统管理员", ["审核卖家资质", "处理异常订单"]),
        ], [("include", "在线支付", "验证支付密码")])
        raw["actors"][1]["kind"] = "primary"
        er.init_font()
        try:
            model = uc.normalize_usecase_spec(raw)
            scene = uc.layout_usecase(model)
            self.assertFalse(any(scene["useCaseQuality"].values()), scene["useCaseQuality"])
            self.assertTrue(all(len(path) == 2 for path in scene["paths"]))
            self.assertTrue(all(len(dep["points"]) == 2 for dep in scene["dep_paths"]))
            system_x, _, system_width, _ = scene["system"]
            actor_xs = [box[1] for box in scene["actors"]]
            self.assertLess(min(actor_xs), system_x)
            self.assertGreater(max(actor_xs), system_x + system_width)
            x0, y0, x1, y1 = scene["bounds"]
            self.assertGreaterEqual(x1 - x0, y1 - y0)
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_dependency_fan_uses_straight_lines_without_crossings(self):
        spec = make_spec("航天发射场调度与发射流程系统", [
            ("指挥员", ["发起发射审批", "下达点火指令"]),
            ("神经监护员", ["下达点火指令"]),
            ("测控工程师", ["开启全频段信号监测", "紧急中止任务"]),
            ("雷达阵列", ["推送雷达数据"]),
            ("遥测传感器", ["推送遥测数据"]),
            ("国家空域管制中心", ["申请空域净空"]),
            ("定时守护进程", ["系统心跳检测"]),
            ("气象卫星系统", ["气象条件评估"]),
        ], [
            ("include", "发起发射审批", "燃料加注安全检查"),
            ("include", "开启全频段信号监测", "设备自检"),
            ("include", "发起发射审批", "气象条件评估"),
            ("extend", "气象条件评估", "推迟发射预警"),
            ("include", "执行点火流程", "倒计时广播"),
            ("include", "执行点火流程", "导流槽降温控制"),
            ("include", "执行点火流程", "申请空域净空"),
            ("extend", "执行点火流程", "紧急点火预案"),
            ("extend", "执行点火流程", "远地点自动启动"),
            ("include", "系统心跳检测", "日志自动归档"),
        ])
        for actor in spec["actors"][:-1]:
            actor["kind"] = "primary"
        model = uc.normalize_usecase_spec(spec)
        er.init_font()
        try:
            scene = uc.layout_usecase(model)
            self.assertFalse(any(scene["useCaseQuality"].values()), scene["useCaseQuality"])
            self.assertEqual(len(scene["dep_paths"]), len(spec["dependencies"]))
            self.assertTrue(all(len(dep["points"]) == 2 for dep in scene["dep_paths"]))
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_disconnected_workflows_keep_all_links_and_avoid_crossings(self):
        associations, dependencies = [], []
        for group in range(4):
            tasks = [f"Task {group * 6 + i}" for i in range(6)]
            first, shared_a, second, shared_b, shared_c, check = tasks
            associations.extend([
                (f"Role {group * 2}", [first, shared_a, shared_c, shared_b]),
                (f"Role {group * 2 + 1}", [second, shared_b, shared_c, shared_a]),
            ])
            dependencies.extend([
                ("include", first, check), ("include", second, check), ("extend", shared_a, second),
            ])
        model = uc.normalize_usecase_spec(make_spec("Complex workflow", associations, dependencies))
        er.init_font()
        try:
            scene = uc.layout_usecase(model)
            self.assertEqual(len(scene["actors"]), 8)
            self.assertEqual(len(scene["use_cases"]), 24)
            self.assertEqual(len(scene["paths"]), 32)
            self.assertEqual(len(scene["dep_paths"]), 12)
            self.assertFalse(any(scene["useCaseQuality"].values()), scene["useCaseQuality"])
            sx, _, sw, _ = scene["system"]
            self.assertTrue(all(x + w / 2 < sx or x - w / 2 > sx + sw for _, x, _, w, _ in scene["actors"]))
        finally:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None

    def test_manual_positions_are_preserved_by_render_worker(self):
        raw = json.loads(LIBRARY.read_text(encoding="utf-8"))
        raw["positions"] = {
            "读者": [-1.42, 2.79], "管理员": [6.92, 2.79],
            "借书": [2.10, 1.26], "还书": [1.99, 2.43],
            "查询馆藏": [1.4, 3.6], "验证身份": [3.625, 2.185], "续借": [1.4, 4.77],
        }
        result = render_usecase_in_worker({"spec": raw, "format": "svg", "aspect": "auto"})
        actual = {node["entity"]: [node["x"], node["y"]] for node in result["layout"]["entities"]}
        self.assertEqual(raw["positions"], actual)
