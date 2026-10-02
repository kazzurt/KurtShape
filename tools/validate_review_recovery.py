"""Reopen a checkpoint after the controlled GUI crash; preserve its source."""
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller
report_path = ROOT / "validation" / "review-followup" / "recovery-crash.json"
report = json.loads(report_path.read_text())
assert report["passed"], report
manifest = Path(report["checkpoint_manifest"])
os.environ["KURTSHAPE_SESSION_DIR"] = str(manifest.parent.parent)
source = Path(report["original_file"])
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
core = Controller()
response = core.dispatch({"op": "recover", "path": str(manifest)})
assert response["ok"], response
state = response["result"]
doc = core.documents[state["document_id"]]
assert doc.Unfinished.GeometryCount == 1 and state["active_sketch_edit"] == "Unfinished", state
assert abs(doc.Pad.Shape.Volume - 1800) < 1e-6
response = core.dispatch({"op": "finish_sketch_edit", "document_id": state["document_id"], "expected_revision": state["revision"], "cancel": True})
assert response["ok"], response
assert doc.Unfinished.GeometryCount == 0
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
report.update(reopened_checkpoint=True, recovered_unsaved_volume_mm3=doc.Pad.Shape.Volume,
              recovered_draft=True, explicit_cancel_restored_accepted_sketch=True, original_file_unchanged=True,
              original_file_sha256=source_hash, engine={"FreeCAD": App.Version()})
core.close()
App.closeDocument(doc.Name)
saved = App.openDocument(str(source))
assert abs(saved.Pad.Shape.Volume - 1200) < 1e-6
App.closeDocument(saved.Name)
report["saved_project_reopened"] = True
native_files = report.get("native_stable_recovery_files", [])
native_archive = next((Path(item["path"]) for item in native_files if item["path"].lower().endswith(".fcstd")), None)
if native_archive:
    recovered_native = App.openDocument(str(native_archive))
    assert abs(recovered_native.Solid.Shape.Volume - 27) < 1e-6
    report["native_autosave_reopened"] = True
    report["native_autosave_volume_mm3"] = recovered_native.Solid.Shape.Volume
    App.closeDocument(recovered_native.Name)
else:
    report["native_autosave_reopened"] = False
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({key:report[key] for key in ("passed", "reopened_checkpoint", "recovered_draft", "saved_project_reopened", "original_file_unchanged")}))
