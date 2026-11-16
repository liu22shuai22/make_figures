"""Generate and check reproducible ERFlow layout cases without a model API."""
import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
import math
from pathlib import Path
import random
from statistics import median
import time


FAMILIES = ("chain", "hub", "cycle", "modules", "bipartite", "parallel", "ternary", "self")
NAMES = (
    "用户", "订单", "退款审核记录", "商品", "库存批次", "商家", "配送任务", "评价", "分类", "活动",
    "仓库", "优惠券领取记录", "地址", "供应商", "质检结果", "工单", "值班班次", "结算账户", "日志", "权限",
)


def make_case(index):
    rng = random.Random(38127 + index)
    family = FAMILIES[index % len(FAMILIES)]
    size = 20 if index < len(FAMILIES) else rng.randint(4, 20)
    names = rng.sample(NAMES, size)
    if family == "hub":
        links = [(0, i) for i in range(1, size)]
    elif family == "modules":
        links = [((i // 4) * 4 if i % 4 else i - 4, i) for i in range(1, size)]
    elif family == "bipartite":
        half = size // 2
        links = [(0, i) for i in range(half, size)] + [(i, half) for i in range(1, half)]
    elif family in ("parallel", "ternary", "self"):
        links = [(rng.randrange(i), i) for i in range(1, size)]
    else:
        links = [(i - 1, i) for i in range(1, size)]
    if family == "cycle":
        links.append((0, size - 1))

    goal = 30 if index < len(FAMILIES) else rng.randint(len(links), min(30, size + 11))
    while len(links) < goal:
        if family == "self":
            node = rng.randrange(size)
            link = (node, node)
        elif family == "parallel":
            link = rng.choice(links[:size - 1])
        elif family == "ternary":
            link = tuple(rng.sample(range(size), 3))
        elif family == "bipartite":
            link = (rng.randrange(size // 2), rng.randrange(size // 2, size))
        elif family == "modules":
            first = rng.randrange(size)
            second = rng.choice([i for i in range(size) if i != first and i // 4 == first // 4]
                                or [max(0, first - 1)])
            link = (first, second)
        else:
            link = tuple(rng.sample(range(size), 2))
        links.append(link)

    relations = [
        {"name": f"{rng.choice(('关联', '审查', '创建', '参与', '记录'))}{i + 1}",
         "entities": [names[j] for j in link],
         "card": rng.choices(("1", "m", "n", "p"), k=len(link)),
         "attrs": rng.sample(("处理时间", "状态", "明细数量", "备注说明"), rng.choices((0, 1, 2, 3), (5, 3, 2, 1))[0])}
        for i, link in enumerate(links)
    ]
    return {"id": f"{family}-{index:05d}", "family": family, "spec": {
        "title": f"{family}-{index:05d}",
        "entities": [{"name": name, "attrs": ["*编号", "名称", "状态"]} for name in names],
        "relations": relations,
    }}


def geometry_metrics(er, scene):
    x0, x1, y0, y1 = er._diagram_extents(scene["boxes"], scene["paths"], scene["labels"])
    area = (x1 - x0) * (y1 - y0)
    lengths = sorted(sum(math.dist(a, b) for a, b in zip(path, path[1:])) for path in scene["paths"])
    return {
        "width": round(x1 - x0, 3), "height": round(y1 - y0, 3),
        "area": round(area, 3),
        "box_fill_percent": round(100 * sum(box[2] * box[3] for box in scene["boxes"]) / area, 2),
        "median_line": round(median(lengths), 3) if lengths else 0,
        "p90_line": round(lengths[math.ceil(0.9 * len(lengths)) - 1], 3) if lengths else 0,
        "bends": sum(map(er._path_bends, scene["paths"])),
    }


def verify_case(case, budget, grouped_only=False):
    import er_generator as er
    from api import validate_web_spec
    from unittest.mock import patch

    spec = case["spec"]
    result = {"id": case["id"], "entities": len(spec["entities"]), "relations": len(spec["relations"])}
    start = time.monotonic()
    original_squeeze = er._squeeze_verified_overview

    def compare(model, scene, page_width, deadline, **options):
        result["before_final_compaction"] = geometry_metrics(er, scene)
        return original_squeeze(model, scene, page_width, deadline, **options)

    try:
        with redirect_stdout(StringIO()), patch.object(er, "_squeeze_verified_overview", compare):
            model = er.normalize_spec(spec, report_isolated=False)
            validate_web_spec(model)
            er.init_font()
            if grouped_only:
                model.update(ent_w=[max(er.tw(e["name"]) + 0.34, 0.62) for e in model["ents"]],
                             attr_w=[[er.tw(a) + 0.26 for a in r["attrs"]] for r in model["rels"]])
                scene = er._grouped_overview(model, None)
                if scene is None:
                    raise er.SpecError("分组方案未通过几何检查")
            else:
                model, scene = er.layout_overview(model, effort=0.5, parallel=False, time_limit=10,
                                                   render_deadline=time.monotonic() + budget)
        overlaps, hits, crossings, _ = er.overview_quality(scene, scene["paths"])
        labels = er._cardinality_conflicts(scene["boxes"], scene["paths"], scene["labels"])
        display = scene.get("display_model", model)
        expected_lines = sum(len(rel["ends"]) + len(rel["attrs"]) for rel in model["rels"])
        expected_labels = sum(len(rel["ends"]) for rel in model["rels"])
        visible_ends = [[(display["ents"][i].get("reference_to", i), card) for i, card in rel["ends"]]
                        for rel in display["rels"]]
        result.update(geometry_metrics(er, scene), crossings=int(crossings), overlaps=int(overlaps),
                      box_hits=int(hits), label_conflicts=int(labels), references=len(display["ents"]) - len(model["ents"]),
                      ok=not (overlaps or hits or crossings or labels) and len(scene["paths"]) == expected_lines
                      and len(scene["labels"]) == expected_labels and visible_ends == [rel["ends"] for rel in model["rels"]])
    except er.SpecError as error:
        result.update(ok=False, error=str(error))
    finally:
        if er._fig0 is not None:
            er.plt.close(er._fig0)
            er._fig0 = er._renderer = None
    result["seconds"] = round(time.monotonic() - start, 2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--count", type=int, default=2000)
    generate.add_argument("--output", type=Path, required=True)
    export = commands.add_parser("export")
    export.add_argument("index", type=int)
    export.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--start", type=int, default=0)
    verify.add_argument("--count", type=int, default=8)
    verify.add_argument("--budget", type=float, default=20)
    verify.add_argument("--grouped-only", action="store_true", help="Check only the grouped layout fallback")
    verify.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.command == "export":
        args.output.write_text(json.dumps(make_case(args.index)["spec"], ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        return 0
    if args.command == "generate":
        with args.output.open("w", encoding="utf-8") as stream:
            for index in range(args.count):
                stream.write(json.dumps(make_case(index), ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"Generated {args.count} cases", flush=True)
        return 0
    failed = 0
    with args.output.open("w", encoding="utf-8") as stream:
        for index in range(args.start, args.start + args.count):
            result = verify_case(make_case(index), args.budget, args.grouped_only)
            line = json.dumps(result, ensure_ascii=False, allow_nan=False)
            stream.write(line + "\n")
            stream.flush()
            print(line, flush=True)
            failed += not result["ok"]
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
