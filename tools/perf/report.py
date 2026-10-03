"""Summarize benchmark samples and evaluate confirmed performance regressions."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

BUDGET_PATH = Path(__file__).with_name("budgets.json")


def metric_value(report, name):
    value = report.get("timings", {}).get(name, {})
    samples = value.get("samples", [])
    numbers = [value.get("median"), value.get("p95"), value.get("worst"), *samples] if isinstance(samples, list) else []
    if not numbers or any(isinstance(item, bool) or not isinstance(item, (int, float)) or
                          not math.isfinite(item) or item < 0 for item in numbers):
        return None, 0
    return value["median"], len(samples)


def evaluate_budgets(report, phase="phase0", best=None, confirmation=None):
    policy = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
    fixture = report.get("fixture", {})
    if fixture.get("kind") != "plate" or fixture.get("holes", 0) < policy["minimum_plate_holes"]:
        return {"evaluated": False, "failed": False,
                "reason": "Plate budgets require at least 60 holes; studio budget is established after Q03", "metrics": []}
    metrics = []
    for name, target in policy[phase].items():
        current, count = metric_value(report, name)
        baseline, best_count = metric_value(best or {}, name)
        repeated, confirmation_count = metric_value(confirmation or {}, name)
        regression_limit = baseline * policy["regression_factor"] + policy["regression_slack_ms"] if baseline is not None else None
        exceeds_target = current is not None and current > target
        suspected = exceeds_target and regression_limit is not None and current > regression_limit
        confirmed = suspected and repeated is not None and repeated > target and repeated > regression_limit
        metrics.append({"name": name, "median_ms": current, "target_ms": target,
                        "best_ms": baseline, "regression_limit_ms": regression_limit,
                        "target_open": exceeds_target, "confirmation_ms": repeated,
                        "suspected_regression": suspected, "failed": confirmed,
                        "available": current is not None, "samples": count,
                        "best_samples": best_count, "confirmation_samples": confirmation_count})
    reasons = []
    if not all(item["available"] for item in metrics):
        reasons.append("Required metric unavailable or nonfinite")
    if any(item["available"] and item["samples"] < 5 for item in metrics):
        reasons.append("Insufficient samples: thresholds require at least five samples per metric")
    for label, other in (("Best baseline", best), ("Confirmation", confirmation)):
        if other is None:
            continue
        other_fixture = other.get("fixture", {})
        if (other_fixture.get("kind"), other_fixture.get("holes")) != (fixture.get("kind"), fixture.get("holes")):
            reasons.append(label + " fixture does not match the current plate")
        if any(metric_value(other, name)[0] is None or metric_value(other, name)[1] < 5 for name in policy[phase]):
            reasons.append(label + " needs finite required metrics with at least five samples")
    if confirmation is not None and report.get("run_id") and confirmation.get("run_id") == report["run_id"]:
        reasons.append("Confirmation must come from an independent second run")
    if reasons:
        for item in metrics:
            item.update(suspected_regression=False, failed=False)
        return {"evaluated": False, "phase": phase, "failed": False, "reason": "; ".join(reasons), "metrics": metrics}
    return {"evaluated": True, "phase": phase, "failed": any(item["failed"] for item in metrics),
            "reason": "Failure requires target and best × 1.2 + 5 ms exceeded on two runs", "metrics": metrics}


def markdown(report, budgets):
    lines = ["| Metric | Median ms | P95 ms | Worst ms | Samples |", "|---|---:|---:|---:|---:|"]
    for name, values in sorted(report.get("timings", {}).items()):
        if metric_value(report, name)[0] is None:
            lines.append(f"| {name} | unavailable | | | 0 |")
        else:
            lines.append(f"| {name} | {values['median']:.3f} | {values['p95']:.3f} | {values['worst']:.3f} | {len(values['samples'])} |")
    for name, section in report.get("sections", {}).items():
        if section["status"] != "ok":
            lines.append(f"\n{name}: unavailable — {section.get('error', 'no measurements')}")
    lines.append("\n" + budgets["reason"])
    for item in budgets["metrics"]:
        status = ("unavailable" if not item["available"] else "insufficient samples" if item["samples"] < 5
                  else "comparison unavailable" if not budgets["evaluated"] else "FAIL" if item["failed"]
                  else "confirm regression" if item["suspected_regression"] else "open target" if item["target_open"] else "within target")
        lines.append(f"- {item['name']}: {status}; target {item['target_ms']} ms")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--phase", choices=("phase0", "phase1"), default="phase0")
    parser.add_argument("--best", "--baseline", dest="best", help="Comparable best-so-far baseline report")
    parser.add_argument("--confirm", help="Independent second run confirming a suspected regression")
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8-sig"))
    best = json.loads(Path(args.best).read_text(encoding="utf-8-sig")) if args.best else None
    confirmation = json.loads(Path(args.confirm).read_text(encoding="utf-8-sig")) if args.confirm else None
    budgets = evaluate_budgets(report, args.phase, best, confirmation)
    print(markdown(report, budgets))
    return 1 if args.enforce and budgets["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
