"""Publish this accepted native design milestone without altering its raw evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "validation" / "onshape-design"
RUNS = {
    "design": "runtime/ci-gui/design-surface/run-4771821a72834a6992f0d72e820a179a",
    "refinement": "runtime/ci-gui/ui-refinement/run-7d07fff02ae64991accfefa181c111ab",
    "messages": "runtime/ci-gui/messages/run-c822e19c23cb4452a1743b42e2b8fab0",
    "workflows": "runtime/ci-gui/onshape-workflows/run-be6598f6d7f2406bb8037ee33afd4896",
    "part_studio": "runtime/ci-gui/part-studio/run-d71317eb7e5b4567b2dc11385dc755a8",
    "native": "runtime/test-tmp/checks-20261004-214235-19192",
}
REPORTS = {
    "design": ("evidence/onshape-design/gui-result.json", "gui-result.json"),
    "refinement": ("evidence/ui-refinement/gui-refinement.json", "ui-refinement.json"),
    "messages": ("evidence/messages-behavior/gui-result.json", "messages.json"),
    "workflows": ("evidence/onshape-workflows/gui-result.json", "modeling-workflows.json"),
    "part_studio": ("evidence/u2-part-model/gui-result.json", "part-studio.json"),
    "native": ("evidence/checks/native.json", "native-regression.json"),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def main():
    reports = {}
    copied = []
    for name, (raw, target) in REPORTS.items():
        path = ROOT / RUNS[name] / raw
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        if report.get("passed") is not True:
            raise RuntimeError(f"Acceptance report is not passing: {path}")
        reports[name] = report
    contrast_path = DESTINATION / "contrast-contract.json"
    contrast = json.loads(contrast_path.read_text(encoding="utf-8"))
    if contrast.get("passed") is not True:
        raise RuntimeError("Contrast report is not passing")
    for required in (ROOT / "DESIGN.md", ROOT / ".impeccable" / "design.json"):
        if not required.is_file():
            raise RuntimeError(f"Final design documentation is missing: {required}")
    json.loads((ROOT / ".impeccable" / "design.json").read_text(encoding="utf-8-sig"))

    differences = []
    for name, before in reports["native"]["source_sha256"].items():
        after = digest(ROOT / name)
        if before.lower() != after:
            differences.append({"path": name, "native_run_sha256": before, "final_sha256": after})
    if [item["path"] for item in differences] != ["src/kurtshape/ui.py"]:
        raise RuntimeError(f"Unexpected source drift since native acceptance: {differences}")

    DESTINATION.mkdir(parents=True, exist_ok=True)

    def copy(source, name):
        target = DESTINATION / name
        shutil.copyfile(source, target)
        if digest(source) != digest(target):
            raise RuntimeError(f"Evidence copy changed bytes: {source}")
        copied.append({"path": relative(target), "raw_path": relative(source), "sha256": digest(target)})

    for name, (raw, target) in REPORTS.items():
        copy(ROOT / RUNS[name] / raw, target)
    copy(ROOT / RUNS["native"] / "evidence/checks/junit.xml", "native-junit.xml")
    for name in ("design", "refinement", "messages"):
        copy(ROOT / RUNS[name] / "recipe-result.json", f"{name}-run.json")
    for capture in reports["design"]["screens"]:
        copy(ROOT / RUNS["design"] / "evidence/onshape-design" / capture["file"], capture["file"])

    source_paths = list((ROOT / "src/kurtshape").glob("*.py"))
    source_paths += list((ROOT / "resources/icons").glob("*.svg"))
    source_paths += [ROOT / path for path in (
        "tools/design-surface-validation.FCMacro", "tools/ui-refinement-validation.FCMacro",
        "tools/messages-validation.FCMacro", "tools/u2-part-model-gui-validation.FCMacro",
        "tools/onshape-workflows-validation.FCMacro", "tools/run_gui_recipe.ps1",
        "tools/theme-presentation-contract.py", "tools/generate-presentation-icons.py",
        "DESIGN.md", ".impeccable/design.json", "launch-kurtshape.ps1",
    )]
    sources = {relative(path): digest(path) for path in sorted(source_paths)}
    launcher = ROOT.parent / "KurtShape-design-update.cmd"
    sources["../KurtShape-design-update.cmd"] = digest(launcher)
    reference = ROOT / "docs/onshape-design-audit/onshape-reference/onshape-user-workspace-2026-10-04.png"
    expected_reference = "4e47a76fb24b43040e98a24de8662a6ae7797df649717114e74657eaab2e1f11"
    if digest(reference) != expected_reference:
        raise RuntimeError("Preserved user reference changed")

    manifest = {
        "schema_version": 1,
        "milestone": "Approved Onshape-inspired native presentation execution",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_head": "559e034de3522c325423057b048f955405c522af",
        "working_tree_changes": "Completed modeling upgrades plus presentation changes; uncommitted source identified by hashes",
        "engine": reports["native"]["engine"],
        "launch": {"path": str(launcher), "session_root": "runtime/design-workspace", "print_only_verified": True},
        "reference": {"path": relative(reference), "sha256": digest(reference), "pixel_size": [1909, 913], "transformed": False},
        "source_sha256": sources,
        "native_regression": {"counts": reports["native"]["counts"], "source_unchanged_during_run": reports["native"]["source_unchanged"]},
        "source_differences_after_native_run": differences,
        "difference_explanation": "Only two UI recovery labels changed after the frozen native run. Final design/refinement/messages recipes exercise this final UI; native model implementation hashes are identical.",
        "gui_check_counts": {name: len(report["checks"]) for name, report in reports.items() if name != "native"},
        "contrast_check_count": len(contrast["checks"]),
        "raw_runs": RUNS,
        "copied_evidence": copied,
        "contrast_evidence": {"path": relative(contrast_path), "sha256": digest(contrast_path)},
        "capture_method": reports["design"]["method"],
        "client_sizes": reports["design"]["client_sizes"],
        "screens": reports["design"]["screens"],
        "fresh_finish_review": {
            "initial_full_review": "One material P1: preview verdict below initial form scroll viewport",
            "correction": "Persistent copyable verdict outside scrollable fields; Confirm/Cancel retained in fixed header",
            "bounded_verdict": "Resolved; ship within the reviewed scope",
            "corrected_states_reviewed": ["fillet-invalid-1440.png", "fillet-valid-1440.png", "extrude-invalid-1440.png", "extrude-valid-1440.png"],
            "scope": "Same fresh reviewer scored the listed P1 only; not a renewed whole-surface audit",
        },
        "limits": [reports["design"]["limits"], "Only actual 150% scaling tested; no 100%, 125% or 200% acceptance", "No performance improvement, long-history or full screen-reader acceptance claimed", "Earlier workflow/Part Studio recipes predate the persistent footer; the final design recipe verifies that correction"],
    }
    target = ROOT / "docs/onshape-design-audit/EXECUTION-EVIDENCE.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Published {len(copied)} byte-identical evidence files and {len(sources)} source hashes")
    print(f"Native source drift: {[item['path'] for item in differences]}")
    print(target)


if __name__ == "__main__":
    main()
