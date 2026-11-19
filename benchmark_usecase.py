"""Measure and compare use-case layout on a fixed set of diagram specifications."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
from statistics import median
from time import perf_counter

import networkx as nx

from benchmarks.usecase_fixtures import fixtures
import er_generator as er
import usecase_generator as uc


def fixture_digest(entries):
    data = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def is_planar(model):
    graph = nx.Graph()
    graph.add_edges_from((("actor", link["actor"]), ("case", link["use_case"])) for link in model["links"])
    graph.add_edges_from((("case", dep["from"]), ("case", dep["to"])) for dep in model["dependencies"])
    return nx.check_planarity(graph)[0]


def measure(group, name, raw):
    model = uc.normalize_usecase_spec(raw)
    uc.validate_usecase_workflow(model)
    counts = {key: len(model[key]) for key in ("actors", "use_cases", "links", "dependencies")}
    result = {"group": group, "id": name, "counts": counts, "graphPlanar": is_planar(model)}
    started = perf_counter()
    try:
        scene = uc.layout_usecase(model)
        seconds = round(perf_counter() - started, 4)
        if any(len(scene[field]) != counts[key] for field, key in (
            ("actors", "actors"), ("use_cases", "use_cases"), ("paths", "links"), ("dep_paths", "dependencies"),
        )):
            raise ValueError("布局返回的图元或连线数量与规格不一致")
        paths = scene["paths"] + [dep["points"] for dep in scene["dep_paths"]]
        bends = [er._path_bends(path) for path in paths]
        x0, y0, x1, y1 = scene["bounds"]
        return dict(result, seconds=seconds, quality=scene["useCaseQuality"], bends=sum(bends),
                    bentLines=sum(bend > 0 for bend in bends), width=round(float(x1 - x0), 3),
                    height=round(float(y1 - y0), 3))
    except (uc.SpecError, ValueError, RuntimeError) as error:
        return dict(result, seconds=round(perf_counter() - started, 4), error=str(error))


def summarize(rows):
    times = sorted(row["seconds"] for row in rows)
    completed = [row for row in rows if "quality" in row]
    clean = [row for row in completed if not any(row["quality"].values())]
    return {
        "runs": len(rows),
        "completed": len(completed),
        "zeroConflicts": len(clean),
        "allStraight": sum(not row["bends"] for row in completed),
        "zeroConflictsAndStraight": sum(not row["bends"] for row in clean),
        "medianSeconds": round(median(times), 4),
        "p95Seconds": times[math.ceil(0.95 * len(times)) - 1],
    }


def compare(baseline, report):
    for key in ("fixtureDigest", "repeats"):
        if baseline.get(key) != report.get(key):
            raise ValueError(f"基准的 {key} 不一致，请使用同一验收集和重复次数")
    if baseline.get("environment") != report["environment"]:
        print("运行环境或字体有变化，请在同一环境重新测量耗时。")
    for group, current in report["summary"].items():
        previous = baseline["summary"][group]
        print(f"{group}: 零冲突 {previous['zeroConflicts']} → {current['zeroConflicts']}，"
              f"全直线且零冲突 {previous['zeroConflictsAndStraight']} → {current['zeroConflictsAndStraight']}，"
              f"P95 {previous['p95Seconds']:.3f}s → {current['p95Seconds']:.3f}s")
    previous_cases = {(row["id"], row["repeat"]): row for row in baseline["cases"]}
    for row in report["cases"]:
        previous = previous_cases[row["id"], row["repeat"]]
        keys = ("quality", "bends", "error")
        if any(previous.get(key) != row.get(key) for key in keys):
            print(f"{row['group']}/{row['id']} [{row['repeat']}] "
                  f"{[previous.get(key) for key in keys]} → {[row.get(key) for key in keys]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="保存按案例和分组统计的 JSON")
    parser.add_argument("--baseline", type=Path, help="与已有 JSON 基准比较")
    parser.add_argument("--repeats", type=int, default=1, help="每个固定输入的重复次数")
    parser.add_argument("--font", help="可选中文字体路径")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats 必须至少为 1")

    entries = list(fixtures())
    digest = fixture_digest(entries)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    if baseline and (baseline.get("fixtureDigest") != digest or baseline.get("repeats") != args.repeats):
        parser.error("基准文件的用例集或重复次数与本次不一致")
    er.init_font(args.font)
    rows = []
    try:
        for repeat in range(args.repeats):
            for group, name, raw in entries:
                row = dict(measure(group, name, raw), repeat=repeat + 1)
                rows.append(row)
                outcome = row.get("error") or f"{row['quality']} · 折点 {row['bends']}"
                print(f"{group}/{name} [{repeat + 1}] {row['seconds']:.3f}s {outcome}", flush=True)
    finally:
        er.plt.close(er._fig0)
        er._fig0 = er._renderer = None
    groups = dict.fromkeys(group for group, _, _ in entries)
    report = {
        "fixtureDigest": digest,
        "repeats": args.repeats,
        "environment": {"system": platform.system(), "machine": platform.machine(),
                        "python": platform.python_version(), "networkx": nx.__version__,
                        "matplotlib": er.matplotlib.__version__, "font": Path(er.FP.get_file() or "").name},
        "layoutSources": {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                          for module in (er, uc)},
        "summary": {group: summarize([row for row in rows if row["group"] == group]) for group in groups},
        "cases": rows,
    }
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if baseline:
        compare(baseline, report)
    else:
        for group, summary in report["summary"].items():
            print(group, summary)
    return int(any("error" in row for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
