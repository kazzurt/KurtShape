"""Compare pinned A/B performance runs with the contract 3.2 acceptance rules (verification spec §4.4).

Each side is one or more run_ab.py result folders (run-summary.json, bench-*.json,
supplement.json). Samples of the same metric are pooled per side (ABBA: two A runs
and two B runs give 10 samples each at --repeat 5), then:

(a) no regression: suspected when pooled median(B) > factor x pooled median(A) + slack
    (1.2 and 5 ms, budgets.json's values). Call families whose pooled A median is
    over 1 s compare overhead_ms (dispatch total minus native recompute) instead.
(b) bounded increase: for --bounded metrics (families where validation was added)
    the limit also allows the B side's result-check time per operation: the family's
    summed studio._check_result ms divided by its pooled B sample count.
(c) exact counts: per-family BRepCheck, result-check, exact-box and native-recompute
    counters must be identical in every run of a side (deterministic) and equal
    across sides. A documented intended change is let through per counter with
    --count-allow COUNTER:FAMILY, FAMILY being the counter key the probe records
    (call families keep the metric's _ms suffix, e.g. studio.edit_extrusion_add_ms;
    timed families drop it, e.g. drill.helix_upstream_edit). Native recompute counts follow C34: B above A is
    always blocking, B below A only when listed (e.g.
    --count-allow native_recomputes_by_family:plate.set_expression_upstream_ms).
    Families only the B side measures (new 3.2 families) are listed, not compared.

Which samples are pooled (integration §2, verification §4.1/§4.4(a)):
- A step whose system_busy_pct_all_cores exceeds --max-busy (32 %) is discarded,
  per step, not per run folder; --keep-over-gate pools it anyway for diagnosis and
  then the comparison can no longer pass.
- A step that exited non-zero, has no busy record or no report, and every step of a
  run whose run-summary or supplement says source_unchanged:false, is discarded.
- A folder without run-summary.json has no load-gate record and is discarded.
- Each side must hold one src/kurtshape tree, recorded by every pooled run; the A
  tree must equal --expect-a-tree (the frozen 3.1 tree by default; 'any' skips it).
- Supplements must have run the same fixtures, and every step both sides measured
  must pool the same number of runs per side: re-run a discarded step and add its
  folder. Any of these makes the comparison invalid (passed false).

A suspected metric is only confirmed when a second ABBA of that family also exceeds;
record both comparisons.

Usage (system or bundled Python, no FreeCAD import):
  python tools/perf/compare_ab.py --a A1 --a A2 --b B1 --b B2 --out compare.json
      [--bounded studio.edit_extrusion_add_ms ...]
      [--count-allow brepcheck_calls_by_family:studio.edit_extrusion_add_ms ...]
      [--factor 1.2] [--slack-ms 5] [--long-ms 1000] [--max-busy 32]
      [--expect-a-tree <sha256>|any] [--expect-b-tree <sha256>] [--keep-over-gate]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import sys

COUNTERS = ("brepcheck_calls_by_family", "result_check_calls_by_family",
            "tight_box_calls_by_family", "native_recomputes_by_family")
RECOMPUTES = "native_recomputes_by_family"
# The frozen contract 3.1 tree in runtime/bench/f31 (integration plan U0, SHA256SUMS.txt).
FROZEN_31_TREE = "dbb163f9d2fd8ccdd139caac291a602036f85af111506025c8639323958e8c11"
DEFAULT_MAX_BUSY = 32.0


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def parse_count_allow(items):
    """'COUNTER:FAMILY' strings -> {(counter, family)}. Allowances are per counter, never per family."""
    allowed = set()
    for item in items or ():
        counter, separator, family = str(item).partition(":")
        if not separator or counter not in COUNTERS or not family:
            raise ValueError(f"--count-allow takes COUNTER:FAMILY with COUNTER one of {', '.join(COUNTERS)}; "
                             f"got {item!r}")
        allowed.add((counter, family))
    return allowed


def step_report(folder, step):
    return Path(folder) / ("supplement.json" if step == "supplement" else f"bench-{step}.json")


def bench_samples(path, step):
    """{metric: {"samples": [...], "overhead": None}} from one bench_core report."""
    out = {}
    for name, value in (load(path).get("timings") or {}).items():
        if isinstance(value, dict) and isinstance(value.get("samples"), list):
            out[f"bench:{step}:{name}"] = {"samples": [float(x) for x in value["samples"]], "overhead": None}
    return out


def probe_samples(data):
    out = {}
    for name, value in (data.get("metrics") or {}).items():
        overhead = value.get("overhead_ms")
        out["probe:" + name] = {"samples": [float(x) for x in value.get("samples", [])],
                                "overhead": [float(x) for x in overhead["samples"]] if isinstance(overhead, dict) else None}
    counts = {name: data.get(name) or {} for name in COUNTERS}
    return out, counts, data.get("studio_result_check_ms_by_family") or {}


def same_path(a, b):
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def read_run(folder, *, max_busy, keep_over_gate):
    """Load one run folder and decide, step by step, which reports may be pooled."""
    folder = Path(folder)
    run = {"folder": str(folder), "tree": None, "affinity": None, "busy_pct": {}, "over_load_gate": [],
           "kept_steps": [], "pooled_over_gate": [], "discarded": [], "problems": [], "source_unchanged": None,
           "fixtures": None, "families_32_unmeasured": [], "unlisted_reports": []}
    pooled = {"metrics": {}, "counts": None, "check_ms": {}}
    summary_path = folder / "run-summary.json"
    if not summary_path.is_file():
        run["discarded"].append({"step": "*", "reasons": ["no run-summary.json (no load-gate or source record)"]})
        return run, pooled
    summary = load(summary_path)
    run["affinity"] = summary.get("affinity")
    run["source_unchanged"] = summary.get("source_unchanged")
    trees = {"run-summary": summary.get("src_kurtshape_tree_sha256")}
    supplement = None
    if (folder / "supplement.json").is_file():
        supplement = load(folder / "supplement.json")
        source = supplement.get("source") or {}
        trees["supplement"] = source.get("src_kurtshape_tree_sha256")
        if source.get("loaded_from") and source.get("source_root") and not same_path(
                source["loaded_from"], Path(source["source_root"]) / "src" / "kurtshape"):
            run["problems"].append(f"supplement loaded kurtshape from {source['loaded_from']}, "
                                   f"not from its source_root {source['source_root']}")
        run["fixtures"] = supplement.get("fixtures")
        run["families_32_unmeasured"] = sorted(supplement.get("families_32_unmeasured") or ())
    known = {value for value in trees.values() if value}
    if len(known) > 1:
        run["problems"].append("run-summary and supplement name different src trees: " + json.dumps(trees))
    run["tree"] = trees["run-summary"] or trees.get("supplement")
    for step, record in sorted((summary.get("steps") or {}).items()):
        busy = record.get("system_busy_pct_all_cores")
        run["busy_pct"][step] = busy
        over = busy > max_busy if busy is not None else bool(record.get("over_load_gate"))
        reasons = []
        if over:
            run["over_load_gate"].append(step)
            if not keep_over_gate:
                reasons.append(f"system busy {busy}% over the {max_busy:g}% load gate")
        elif busy is None:
            reasons.append("no system busy record")
        if record.get("exit") not in (0, None):
            reasons.append(f"step exited {record.get('exit')}")
        if summary.get("source_unchanged") is False:
            reasons.append("run-summary source_unchanged false")
        report = step_report(folder, step)
        if not report.is_file():
            reasons.append(f"report {report.name} missing")
        elif step == "supplement" and supplement is not None and supplement.get("source_unchanged") is False:
            reasons.append("supplement source_unchanged false")
        if reasons:
            run["discarded"].append({"step": step, "reasons": reasons})
            continue
        run["kept_steps"].append(step)
        if over:
            run["pooled_over_gate"].append(step)
        if step == "supplement":
            metrics, counts, check_ms = probe_samples(supplement)
            pooled["counts"], pooled["check_ms"] = counts, check_ms
        else:
            metrics = bench_samples(report, step)
        pooled["metrics"].update(metrics)
    listed = {step_report(folder, step).name for step in (summary.get("steps") or {})}
    run["unlisted_reports"] = sorted(path.name for path in folder.glob("bench-*.json")
                                     if "-attempt" not in path.stem and path.name not in listed)
    return run, pooled


def side(folders, *, max_busy=DEFAULT_MAX_BUSY, keep_over_gate=False):
    pooled, counts, check_ms, runs = {}, [], {}, []
    for folder in folders:
        run, data = read_run(folder, max_busy=max_busy, keep_over_gate=keep_over_gate)
        runs.append(run)
        for name, value in data["metrics"].items():
            target = pooled.setdefault(name, {"samples": [], "overhead": [], "has_overhead": value["overhead"] is not None})
            target["samples"] += value["samples"]
            if value["overhead"] is not None:
                target["overhead"] += value["overhead"]
            else:
                target["has_overhead"] = False
        if data["counts"] is not None:
            counts.append({"folder": str(folder), **data["counts"]})
        for family, values in data["check_ms"].items():
            check_ms.setdefault(family, []).extend(float(x) for x in values)
    return pooled, counts, check_ms, runs


def family_of(metric):
    """'probe:studio.edit_extrusion_add_ms' -> 'studio.edit_extrusion_add_ms' (probe families use metric names)."""
    return metric.split(":", 1)[1] if metric.startswith("probe:") else None


def family_keys(name):
    """Counter/check-ms keys a probe metric may be recorded under (call families use the metric name,
    timed families such as drill.helix_upstream_edit drop the _ms suffix)."""
    if not name:
        return ()
    return (name, name[:-3]) if name.endswith("_ms") else (name,)


def validity(a_runs, b_runs, *, expect_a_tree, expect_b_tree):
    """Reasons the pooled comparison is not a §4.4 acceptance result (empty when valid)."""
    reasons = []
    for label, runs, expected in (("A", a_runs, expect_a_tree), ("B", b_runs, expect_b_tree)):
        pooled_runs = [run for run in runs if run["kept_steps"]]
        for run in runs:
            reasons += [f"{label} {run['folder']}: {problem}" for problem in run["problems"]]
            if run["pooled_over_gate"]:
                reasons.append(f"{label} {run['folder']}: over-gate steps pooled (--keep-over-gate): "
                               + ", ".join(run["pooled_over_gate"]))
        if not pooled_runs:
            reasons.append(f"{label}: no run has a step that may be pooled")
            continue
        trees = sorted({run["tree"] for run in pooled_runs if run["tree"]})
        unknown = [run["folder"] for run in pooled_runs if not run["tree"]]
        if unknown:
            reasons.append(f"{label}: no src tree recorded by " + ", ".join(unknown))
        if len(trees) > 1:
            reasons.append(f"{label}: pooled runs come from {len(trees)} src trees: " + ", ".join(trees))
        if expected and trees and trees != [expected]:
            reasons.append(f"{label}: src tree {', '.join(trees)} is not the expected {expected}")
    fixtures = {json.dumps(run["fixtures"]) for run in a_runs + b_runs
                if run["fixtures"] is not None and "supplement" in run["kept_steps"]}
    if len(fixtures) > 1:
        reasons.append("supplements ran different fixtures: " + ", ".join(sorted(fixtures)))
    # Pool equal numbers of runs per step (ABBA): a discarded step is re-run and its folder added.
    coverage = {}
    for label, runs in (("A", a_runs), ("B", b_runs)):
        for run in runs:
            listed = set(run["busy_pct"]) | {item["step"] for item in run["discarded"] if item["step"] != "*"}
            for step in listed:
                entry = coverage.setdefault(step, {"A_listed": 0, "B_listed": 0, "A_pooled": 0, "B_pooled": 0})
                entry[label + "_listed"] += 1
                entry[label + "_pooled"] += step in run["kept_steps"]
    for step, entry in sorted(coverage.items()):
        if entry["A_listed"] and entry["B_listed"] and entry["A_pooled"] != entry["B_pooled"]:
            reasons.append(f"step {step}: A pools {entry['A_pooled']} run(s), B pools {entry['B_pooled']}; "
                           "re-run the discarded step and add its folder")
    return reasons, coverage


def compare_counts(a_counts, b_counts, a_metrics, count_allow):
    """Rule (c): deterministic counters, per counter and family."""
    rows = []
    for label, runs in (("A", a_counts), ("B", b_counts)):
        for run in runs[1:]:
            for counter in COUNTERS:
                expected, actual = runs[0].get(counter, {}), run.get(counter, {})
                for family in sorted(set(expected) | set(actual)):
                    if expected.get(family, 0) != actual.get(family, 0):
                        rows.append({"kind": "nondeterministic", "side": label, "folder": run["folder"],
                                     "reference_folder": runs[0]["folder"], "counter": counter, "family": family,
                                     "reference": expected.get(family, 0), "actual": actual.get(family, 0),
                                     "allowed": False, "rule": "counters must be identical in every run of a side"})
    only_b = []
    if a_counts and b_counts:
        a_ref, b_ref = a_counts[0], b_counts[0]
        a_families = {family for counter in COUNTERS for family in a_ref.get(counter, {})}
        a_families |= {key for metric in a_metrics for key in family_keys(family_of(metric))}
        b_families = {family for counter in COUNTERS for family in b_ref.get(counter, {})}
        only_b = sorted(b_families - a_families)
        for counter in COUNTERS:
            for family in sorted(a_families):
                a_value, b_value = a_ref.get(counter, {}).get(family, 0), b_ref.get(counter, {}).get(family, 0)
                if a_value == b_value:
                    continue
                listed = (counter, family) in count_allow
                if counter == RECOMPUTES and b_value > a_value:
                    allowed, rule = False, "C34: native recompute counts must not exceed A"
                elif counter == RECOMPUTES:
                    allowed, rule = listed, "C34: a native recompute decrease passes only when documented (--count-allow)"
                else:
                    allowed, rule = listed, "documented change (--count-allow COUNTER:FAMILY)"
                rows.append({"kind": "cross_side", "folder": b_ref["folder"], "reference_folder": a_ref["folder"],
                             "counter": counter, "family": family, "reference": a_value, "actual": b_value,
                             "direction": "increase" if b_value > a_value else "decrease",
                             "allowed": allowed, "rule": rule})
    return rows, only_b


def compare(a_folders, b_folders, *, factor=1.2, slack_ms=5.0, long_ms=1000.0, bounded=(), count_allow=(),
            max_busy=DEFAULT_MAX_BUSY, keep_over_gate=False, expect_a_tree=FROZEN_31_TREE, expect_b_tree=None):
    allow = parse_count_allow(count_allow)
    expect_a_tree = None if expect_a_tree in ("", "any") else expect_a_tree
    expect_b_tree = None if expect_b_tree in ("", "any") else expect_b_tree
    a, a_counts, _, a_runs = side(a_folders, max_busy=max_busy, keep_over_gate=keep_over_gate)
    b, b_counts, b_check_ms, b_runs = side(b_folders, max_busy=max_busy, keep_over_gate=keep_over_gate)
    invalid, coverage = validity(a_runs, b_runs, expect_a_tree=expect_a_tree, expect_b_tree=expect_b_tree)
    rows = []
    for metric in sorted(set(a) & set(b)):
        if not a[metric]["samples"] or not b[metric]["samples"]:
            continue
        a_median, b_median = statistics.median(a[metric]["samples"]), statistics.median(b[metric]["samples"])
        basis = "total"
        if a_median > long_ms and a[metric]["has_overhead"] and b[metric]["has_overhead"] and a[metric]["overhead"] and b[metric]["overhead"]:
            basis = "overhead"
            a_value, b_value = statistics.median(a[metric]["overhead"]), statistics.median(b[metric]["overhead"])
        else:
            a_value, b_value = a_median, b_median
        allowance = 0.0
        rule = "a"
        name = family_of(metric)
        if name in bounded:
            rule = "b"
            checks = next((b_check_ms[key] for key in family_keys(name) if key in b_check_ms), [])
            allowance = sum(checks) / max(1, len(b[metric]["samples"]))
        limit = factor * a_value + slack_ms + allowance
        rows.append({"metric": metric, "rule": rule, "basis": basis, "A": round(a_value, 3), "B": round(b_value, 3),
                     "A_samples": len(a[metric]["samples"]), "B_samples": len(b[metric]["samples"]),
                     "check_allowance_ms": round(allowance, 3), "limit": round(limit, 3),
                     "ratio": round(b_value / a_value, 3) if a_value else None, "suspected": b_value > limit})
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    count_rows, families_only_b = compare_counts(a_counts, b_counts, a, allow)
    # Long families: native-recompute counts must not change unless a documented decrease (§4.4(a), C34).
    long_families = {key for row in rows if row["basis"] == "overhead" for key in family_keys(family_of(row["metric"]))}
    long_count_differences = [row for row in count_rows if row["counter"] == RECOMPUTES and row["family"] in long_families]
    suspected = [row for row in rows if row["suspected"]]
    blocking_counts = [row for row in count_rows if not row["allowed"]]
    used = {(row["counter"], row["family"]) for row in count_rows if row["allowed"]}
    warnings = sorted({f"{run['folder']}: contract 3.2 families available but not measured: "
                       + ", ".join(run["families_32_unmeasured"]) for run in a_runs + b_runs if run["families_32_unmeasured"]})
    warnings += [f"{run['folder']}: source_unchanged not recorded (report predates the check)"
                 for run in a_runs + b_runs if run["kept_steps"] and run["source_unchanged"] is None]
    passed = (not invalid and not suspected and not blocking_counts
              and all(row["allowed"] for row in long_count_differences))
    return {"A": [str(x) for x in a_folders], "B": [str(x) for x in b_folders],
            "rules": {"factor": factor, "slack_ms": slack_ms, "long_ms": long_ms, "bounded": sorted(bounded),
                      "count_allow": sorted(f"{counter}:{family}" for counter, family in allow),
                      "max_busy_pct": max_busy, "keep_over_gate": keep_over_gate,
                      "expect_a_tree": expect_a_tree, "expect_b_tree": expect_b_tree},
            "valid": not invalid, "invalid_reasons": invalid, "step_coverage": coverage,
            "runs": {"A": a_runs, "B": b_runs},
            "discarded": [{"side": label, "folder": run["folder"], **item}
                          for label, runs in (("A", a_runs), ("B", b_runs)) for run in runs for item in run["discarded"]],
            "trees": {"A": sorted({run["tree"] for run in a_runs if run["tree"]}),
                      "B": sorted({run["tree"] for run in b_runs if run["tree"]})},
            "metrics": len(rows), "suspected": len(suspected), "suspected_rows": suspected,
            "counts_equal": not count_rows, "count_differences": count_rows,
            "blocking_count_differences": blocking_counts,
            "long_family_recompute_count_differences": long_count_differences,
            "unused_count_allowances": sorted(f"{counter}:{family}" for counter, family in allow - used),
            "count_families_only_in_B": families_only_b,
            "only_in_A": only_a, "only_in_B": only_b, "warnings": warnings,
            "passed": passed,
            "rows": rows}


def table(report):
    lines = [f"{'metric':58} {'rule':4} {'basis':8} {'A':>10} {'B':>10} {'limit':>10} {'ratio':>6}  flag"]
    for row in report["rows"]:
        lines.append(f"{row['metric'][:58]:58} {row['rule']:4} {row['basis']:8} {row['A']:10.1f} {row['B']:10.1f} "
                     f"{row['limit']:10.1f} {row['ratio'] if row['ratio'] is not None else '-':>6}  "
                     f"{'SUSPECTED' if row['suspected'] else ''}")
    lines.append(f"metrics {report['metrics']}, suspected {report['suspected']}, counts_equal {report['counts_equal']}, "
                 f"valid {report['valid']}, passed {report['passed']}")
    for reason in report["invalid_reasons"]:
        lines.append("INVALID " + reason)
    for item in report["discarded"]:
        lines.append(f"DISCARDED {item['side']} {item['folder']} {item['step']}: " + "; ".join(item["reasons"]))
    for row in report["count_differences"]:
        lines.append(("COUNT " if not row["allowed"] else "COUNT (allowed) ") + json.dumps(row))
    for warning in report["warnings"]:
        lines.append("WARNING " + warning)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", action="append", required=True, help="A-side run folder (repeatable)")
    parser.add_argument("--b", action="append", required=True, help="B-side run folder (repeatable)")
    parser.add_argument("--out", help="JSON report path")
    parser.add_argument("--table", help="text table path")
    parser.add_argument("--bounded", action="append", default=[], help="rule (b) probe metric, e.g. studio.rebuild_ms")
    parser.add_argument("--count-allow", action="append", default=[], metavar="COUNTER:FAMILY",
                        help="documented count change for one counter of one family, e.g. "
                             "brepcheck_calls_by_family:studio.edit_extrusion_add_ms")
    parser.add_argument("--factor", type=float, default=1.2)
    parser.add_argument("--slack-ms", type=float, default=5.0)
    parser.add_argument("--long-ms", type=float, default=1000.0)
    parser.add_argument("--max-busy", type=float, default=DEFAULT_MAX_BUSY,
                        help="load gate in percent of all cores; steps above it are discarded")
    parser.add_argument("--keep-over-gate", action="store_true",
                        help="pool over-gate steps anyway (diagnosis only: the comparison cannot pass)")
    parser.add_argument("--expect-a-tree", default=FROZEN_31_TREE,
                        help="required A-side src/kurtshape tree (default: the frozen 3.1 tree; 'any' skips it)")
    parser.add_argument("--expect-b-tree", help="required B-side src/kurtshape tree")
    args = parser.parse_args(argv)
    try:
        allow = parse_count_allow(args.count_allow)
    except ValueError as exc:
        parser.error(str(exc))
    report = compare(args.a, args.b, factor=args.factor, slack_ms=args.slack_ms, long_ms=args.long_ms,
                     bounded=set(args.bounded), count_allow=[f"{c}:{f}" for c, f in allow],
                     max_busy=args.max_busy, keep_over_gate=args.keep_over_gate,
                     expect_a_tree=None if args.expect_a_tree in ("", "any") else args.expect_a_tree,
                     expect_b_tree=args.expect_b_tree or None)
    text = table(report)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.table:
        Path(args.table).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
