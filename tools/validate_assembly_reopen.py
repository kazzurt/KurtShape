"""Reopen the isolated GUI's relocated fixture in a fresh native Python process."""
import json
import hashlib
import os
from pathlib import Path
import sys
import traceback
from kurtshape_evidence import evidence_dir, register_runtime_folder

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = evidence_dir("assembly-workflow")
SESSION = Path(os.environ.get("KURTSHAPE_SESSION_DIR", ROOT / "runtime" / "assembly-fresh-reopen-validation")).resolve()
register_runtime_folder(SESSION)
SESSION.mkdir(parents=True, exist_ok=True)
os.environ["KURTSHAPE_SESSION_DIR"] = str(SESSION)
for name, subfolder in (("FREECAD_USER_HOME", "user-data"), ("TEMP", "temporary"),
                        ("TMP", "temporary"), ("APPDATA", "appdata"),
                        ("LOCALAPPDATA", "localappdata")):
    folder = SESSION / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(folder)
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller
from kurtshape import assembly as assembly_adapter

original_fingerprint = assembly_adapter._geometry_fingerprint


def record_fingerprint(source):
    native_brep = source.Shape.copy(True, False).exportBrepToString()
    digest = hashlib.sha256(native_brep.encode("utf-8")).hexdigest()
    working = REPORT_DIR / "assembly-gui-projects-working"
    working.mkdir(parents=True, exist_ok=True)
    path = working / ("snapshot-fingerprint-headless-" + digest + ".brep")
    if not path.exists():
        path.write_text(native_brep, encoding="utf-8")
    return original_fingerprint(source)


assembly_adapter._geometry_fingerprint = record_fingerprint


def main():
    report = {"passed": False, "method": "Fresh independent bundled native Python process; relocated GUI-produced FCStd; original source path is absent"}
    core = None
    try:
        gui_report = json.loads((REPORT_DIR / "gui-test-result.json").read_text(encoding="utf-8"))
        assert gui_report["passed"], "Complete the assembly GUI recipe first"
        report["fixture"] = gui_report["fixtures"]["relocated"]
        core = Controller()
        response = core.dispatch({"op": "open", "path": gui_report["fixtures"]["relocated"]})
        assert response["ok"], response
        state = response["result"]
        assert state["build_status"] == "valid", state
        assembly = state["assembly"]
        assert len(assembly["instances"]) == 4 and len(assembly["joints"]) == 3
        assert state["measurements"]["solid_count"] == 4
        doc = core.documents[state["document_id"]]
        assert all(doc.getObject(item["id"]).LinkedObject.Document == doc for item in assembly["instances"])
        assert all(not Path(item["source"]["path"]).exists() for item in assembly["instances"])
        report.update(passed=True,
                      checks=["Native reopen restores valid solved assembly", "Four embedded occurrences and three joints survive",
                              "All App::Link sources belong to the reopened document", "Recorded original source path is absent"],
                      assembly=assembly, measurements=state["measurements"], engine=App.Version())
        print("Fresh independent assembly reopen passed:", len(report["checks"]), "checks")
    except Exception:
        report["error"] = traceback.format_exc()
        raise
    finally:
        (REPORT_DIR / "fresh-process-reopen-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if core:
            core.close()
        for name in list(App.listDocuments()):
            App.closeDocument(name)


if __name__ == "__main__":
    main()
