"""Collect final regression and GUI receipts without touching native fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "evidence"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def copy_report(path, name):
    path = Path(path)
    destination = OUTPUT / name
    shutil.copy2(path, destination)
    return {"original": str(path.resolve()), "copy": name,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", required=True)
    parser.add_argument("--gui-summary", required=True, nargs="+")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    native = read(args.native)
    assert native["passed"] and native["source_unchanged"], "Full regression must pass on frozen sources"
    current = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted((ROOT / "src/kurtshape").glob("*.py"))}
    for path, expected in native["source_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    rows = []
    originals = [copy_report(args.native, "full-regression.json")]
    for number, summary in enumerate(args.gui_summary, 1):
        summary_path = Path(summary)
        sources_path = summary_path.parent / "source-hashes-before.json"
        sources = read(sources_path)
        assert set(sources) == {Path(path).name for path in current}, "GUI production source inventory differs"
        for name, expected in sources.items():
            actual = hashlib.sha256((ROOT / "src/kurtshape" / name).read_bytes()).hexdigest()
            assert actual == expected.lower(), "GUI source changed: " + name
        recorded_rows = read(summary_path)
        rows.extend(recorded_rows if isinstance(recorded_rows, list) else [recorded_rows])
        originals.extend((copy_report(summary_path, f"gui-sweep-{number}-summary.json"),
                          copy_report(sources_path, f"gui-sweep-{number}-sources.json")))
    latest = {row["recipe"]: row for row in rows}
    expected_recipes = {
        "interface", "presentation-scheduling", "onshape-workflows", "design-surface",
        "ui-refinement", "sketch-plane-editor", "history-selection", "rollback-history",
        "part-studio", "assembly", "step-import", "assembly-step", "review-recovery",
        "messages", "unused-sketch-visibility", "sketch-edit-state", "sketch-references",
        "extrusion-preview", "bench-gui",
    }
    assert expected_recipes == set(latest), "Final GUI recipe inventory is incomplete or unexpected"
    gui = []
    for recipe, row in latest.items():
        assert row["passed"] and row.get("source_unchanged") is True, recipe
        assert not row.get("diagnostic_matches"), "Review unexpected GUI diagnostics: " + recipe
        receipt = read(row["receipt"])
        expected_exit_codes = (23, -1073740791) if recipe == "review-recovery" else (0,)
        assert receipt["passed"] and receipt["exit_code"] in expected_exit_codes, recipe
        report = read(receipt["report"])
        assert report["passed"], recipe
        native_copy = copy_report(receipt["report"], "gui-" + recipe + ".json")
        receipt_copy = copy_report(row["receipt"], "gui-" + recipe + "-process-receipt.json")
        originals.extend((native_copy, receipt_copy))
        check_count = row.get("checks")
        proof_copy = None
        if recipe == "review-recovery":
            proof = receipt["post_recovery"]
            assert proof["verified"] and read(proof["report"])["passed"], "Recovery reopen proof failed"
            proof_copy = copy_report(proof["report"], "gui-review-recovery-proof.json")
            originals.append(proof_copy)
            check_count = proof["checks"]
        gui.append({"recipe": recipe, "checks": check_count, "passed": True,
                    "report": native_copy["copy"], "receipt": receipt_copy["copy"],
                    "recovery_proof": proof_copy["copy"] if proof_copy else None,
                    "diagnostic_matches": row.get("diagnostic_matches", [])})
    result = {"passed": True, "regression": native["counts"], "gui": gui,
              "gui_recipe_count": len(gui),
              "gui_checks": sum(row["checks"] or 0 for row in gui),
              "production_source_sha256": current, "collected_reports": originals,
              "limits": ["Performance runs have separately recorded source versions and methods.",
                         "Earlier failed diagnostics and original native fixtures remain in runtime; they are not accepted results.",
                         "Hidden GUI correctness checks do not replace the user's hands-on feel assessment."]}
    destination = OUTPUT / "acceptance-summary.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("passed", "regression", "gui_recipe_count", "gui_checks")}))


if __name__ == "__main__":
    main()
