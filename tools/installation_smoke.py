"""Exercise the installed engine and KurtShape in a disposable headless session."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    session = Path(os.environ["KURTSHAPE_SESSION_DIR"]).resolve()
    if session == ROOT / "runtime" or not session.is_relative_to(ROOT / "runtime" / "installation-check"):
        raise ValueError("Installation check needs its own private session")
    for name in ("FREECAD_USER_HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        if not Path(os.environ[name]).resolve().is_relative_to(session):
            raise ValueError("Environment is not isolated: " + name)
    report = args.report.resolve()
    if not report.is_relative_to(session):
        raise ValueError("Report must be inside the private session")
    result = {"passed": False, "checks": [], "checkout": str(ROOT), "limits": "Headless installation smoke; viewport and mouse interaction require human acceptance."}
    core = None
    try:
        import FreeCAD as App
        import Part
        from kurtshape.core import Controller

        def check(name, condition):
            result["checks"].append({"name": name, "passed": bool(condition)})
            if not condition:
                raise AssertionError(name)

        result["engine"] = {"freecad": App.Version(), "occt": Part.OCC_VERSION, "home": App.getHomePath()}
        check("Pinned FreeCAD / OCCT", App.Version()[:3] == ["1", "1", "4"] and Part.OCC_VERSION == "7.8.1")
        result["source_sha256"] = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "src" / "kurtshape").glob("*.py"))}
        try:
            git = subprocess.run(["git", "-c", "safe.directory=" + str(ROOT), "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            result["checkout_commit"] = git.stdout.strip() if git.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            result["checkout_commit"] = None
        core = Controller()
        check("Portable first-run save location", core.settings.project_directory == ROOT / "projects" and core.settings.roots == {(ROOT / "projects").resolve()})
        core.settings.grant_destination(session / "smoke.FCStd")
        state = None

        def call(op, **kwargs):
            nonlocal state
            request = {"op": op, **kwargs}
            if state and op not in {"new", "open", "capabilities"}:
                request.update(document_id=state["document_id"], expected_revision=state["revision"])
            response = core.dispatch(request)
            if not response["ok"]:
                raise RuntimeError(json.dumps(response))
            if op != "capabilities":
                state = response["result"]
            result["checks"].append({"name": op, "passed": True})
            return response["result"]

        call("capabilities")
        call("new", name="Installation check")
        call("sketch_rectangle", id="Profile", width=20, height=10)
        call("pad", profile="Profile", length=5)
        check("Expected solid volume", abs(state["measurements"]["volume_mm3"] - 1000) < 1e-6)
        call("undo")
        check("Undo removes solid", state["measurements"] is None or state["measurements"]["volume_mm3"] in (None, 0))
        call("redo")
        check("Redo restores solid", abs(state["measurements"]["volume_mm3"] - 1000) < 1e-6)
        call("check_geometry")
        call("save", path=str(session / "smoke.FCStd"))
        doc = core.documents[state["document_id"]]
        App.closeDocument(doc.Name)
        call("open", path=str(session / "smoke.FCStd"))
        check("Save/reopen preserves volume", abs(state["measurements"]["volume_mm3"] - 1000) < 1e-6)
        call("export", path=str(session / "smoke.step"))
        call("export", path=str(session / "smoke.stl"))
        check("Native and export files written", all((session / name).stat().st_size > 0 for name in ("smoke.FCStd", "smoke.step", "smoke.stl")))
        result["passed"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        if core is not None:
            core.close()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"]), "report": str(report), "error": result.get("error")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
