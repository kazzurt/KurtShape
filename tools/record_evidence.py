"""Package reviewed regression, benchmark and GUI reports with provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess

from kurtshape_evidence import ROOT, evidence_dir


def git_output(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def checks_for(report):
    if isinstance(report.get("checks"), list):
        return report["checks"]
    if "suites" in report:
        return [{"name": suite["name"], "passed": suite["passed"],
                 "counts": suite["counts"], "source_unchanged": suite["source_unchanged"],
                 "rejected_skips": suite.get("rejected_skips", [])}
                for suite in report["suites"]]
    return [{"name": "reported checks", "count": report.get("checks"),
             "passed": report.get("passed", False)}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--from", dest="test_report", required=True)
    parser.add_argument("--bench")
    parser.add_argument("--gui")
    parser.add_argument("--files", nargs="*", help="Increment paths used for the diff hash")
    parser.add_argument("--write-evidence", action="store_true",
                        help="Explicitly opt in to tracked validation reports")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.slug):
        parser.error("--slug must be a descriptive folder name without path separators")
    if args.write_evidence:
        os.environ["KURTSHAPE_WRITE_EVIDENCE"] = "1"
    base_commit = git_output("rev-parse", "HEAD").decode("ascii").strip()
    diff = git_output("diff", "HEAD", "--", *(args.files or []))
    diff_sha256 = hashlib.sha256(diff).hexdigest()
    destination = evidence_dir("2026-10-03-upgrade/" + args.slug)
    for name, path in (("native-tests", args.test_report), ("benchmark", args.bench), ("gui", args.gui)):
        if not path:
            continue
        report = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        packaged = {"passed": report.get("passed", False), "checks": checks_for(report),
                    "method": report.get("method", report.get("recipe", name)),
                    "engine": report.get("engine", {}), "base_commit": base_commit,
                    "worktree_diff_sha256": diff_sha256,
                    "timings": report.get("timings", {"median": None, "p95": None,
                                                         "worst": None, "samples": []}),
                    "limits": report.get("limits", ""),
                    "ci": {"status": "not_run", "reason": "push not authorized", "run_url": None}}
        if name == "benchmark":
            packaged["hardware"] = report.get("hardware") or {
                "processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
                "logical_processors": os.cpu_count(), "platform": platform.platform()}
        if "counts" in report:
            packaged["counts"] = report["counts"]
        if "suites" in report:
            packaged["suites"] = [{key: suite[key] for key in
                                  ("name", "passed", "counts", "seconds", "source_unchanged")}
                                  for suite in report["suites"]]
        packaged["input_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        output = destination / (name + ".json")
        output.write_text(json.dumps(packaged, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
