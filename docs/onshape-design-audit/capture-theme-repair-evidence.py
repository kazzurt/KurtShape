"""Publish the saved dark-theme repair milestone without changing raw inputs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "validation/onshape-theme-repair"
RUNS = {
    "theme": "runtime/ci-gui/theme-startup/run-c826992ba5ed4776a6e9fd8110294a1f",
    "design": "runtime/ci-gui/design-surface/run-b3ecff7f2813424c91a3b3fa37373c11",
    "messages": "runtime/ci-gui/messages/run-5caaded4cf324541af3b5b17675c82e7",
    "refinement": "runtime/ci-gui/ui-refinement/run-715fae7ca55147318d4393896ffe33c6",
}
REPORTS = {
    "theme": ("evidence/theme-startup/gui-result.json", "theme-startup.json"),
    "design": ("evidence/onshape-design/gui-result.json", "design-surface.json"),
    "messages": ("evidence/messages-behavior/gui-result.json", "messages.json"),
    "refinement": ("evidence/ui-refinement/gui-refinement.json", "ui-refinement.json"),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    reports = {name: json.loads((ROOT / RUNS[name] / pair[0]).read_text(encoding="utf-8-sig"))
               for name, pair in REPORTS.items()}
    assert all(report["passed"] is True for report in reports.values())
    baseline = json.loads((ROOT / "docs/onshape-design-audit/EXECUTION-EVIDENCE.json").read_text())
    current_sources = {path.relative_to(ROOT).as_posix(): digest(path)
                       for path in sorted((ROOT / "src/kurtshape").glob("*.py"))}
    changes = [name for name, value in current_sources.items() if value != baseline["source_sha256"].get(name)]
    assert sorted(changes) == ["src/kurtshape/theme.py", "src/kurtshape/workspace_preferences.py"], changes
    extra = ["tools/theme-startup-validation.FCMacro", "tools/run_gui_recipe.ps1",
             "DESIGN.md", ".impeccable/design.json", "docs/onshape-design-audit/THEME-REPAIR.md"]
    current_sources.update({name: digest(ROOT / name) for name in extra})
    DESTINATION.mkdir(parents=True, exist_ok=True)
    copied = []

    def copy(raw, name):
        target = DESTINATION / name
        shutil.copyfile(raw, target)
        assert digest(raw) == digest(target)
        copied.append({"path": target.relative_to(ROOT).as_posix(),
                       "raw_path": raw.relative_to(ROOT).as_posix(), "sha256": digest(target)})

    for name, (raw, published) in REPORTS.items():
        copy(ROOT / RUNS[name] / raw, published)
        copy(ROOT / RUNS[name] / "recipe-result.json", name + "-run.json")
    for capture in reports["theme"]["screens"]:
        copy(ROOT / RUNS["theme"] / "evidence/theme-startup" / capture["file"], capture["file"])
    for name in ("model-workspace-1440.png", "hover-label-below-1440.png", "sketch-editor-1440.png"):
        copy(ROOT / RUNS["design"] / "evidence/onshape-design" / name, name)
    engine = ROOT / "runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311"
    packs = {name: digest(engine / "data/Gui/PreferencePacks" / name / (name + ".cfg"))
             for name in ("FreeCAD Dark", "FreeCAD Light")}
    manifest = {
        "schema_version": 1, "milestone": "Saved dark native appearance compatibility repair",
        "recorded_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": current_sources,
        "source_changes_from_execution": changes, "model_engine_source_unchanged_from_execution": True,
        "baseline_execution_manifest_sha256": digest(ROOT / "docs/onshape-design-audit/EXECUTION-EVIDENCE.json"),
        "raw_runs": RUNS, "copied_evidence": copied, "bundled_preference_pack_sha256": packs,
        "check_counts": {name: len(report["checks"]) for name, report in reports.items()},
        "refinement_scope": "106 checks precede the final report-only rehighlight addition; theme/design/messages exercise final repair source",
        "theme_snapshots": reports["theme"]["snapshots"], "screens": reports["theme"]["screens"],
        "minimum_retained_report_contrast": min(item["contrast"] for item in reports["theme"]["retained_native_report_formats"]),
        "native_report_format_colors": sorted({item["foreground"] for item in reports["theme"]["retained_native_report_formats"]}),
        "review": {"finding": "Retained native warning layouts remained pale despite new report colors",
                   "correction": "Verified native QSyntaxHighlighter.rehighlight after preference changes, retaining native severity metadata",
                   "bounded_verdict": "P2 resolved; ship within this bounded repair scope"},
        "limits": [reports["theme"]["limits"], "Actual scaling 150%; other DPI settings untested",
                   "Sketch capture demonstrates Tasks/chrome; sketch text recovery is preference contrast evidence, not rendered dimension acceptance",
                   "User's existing process retains its old code until save/close/relaunch; no live user window inspected or changed"],
    }
    target = ROOT / "docs/onshape-design-audit/THEME-REPAIR-EVIDENCE.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Published {len(copied)} unchanged evidence files; {len(current_sources)} source/document hashes")
    print(manifest["check_counts"])
    print(f"Retained native report contrast minimum: {manifest['minimum_retained_report_contrast']:.3f}:1")


if __name__ == "__main__":
    main()
