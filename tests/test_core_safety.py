"""Regression checks for stale native geometry and copied-document identity."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller


class CoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.initial_names = set(App.listDocuments())
        self.core = Controller()
        self.state = None

    def tearDown(self):
        for name in set(App.listDocuments()) - self.initial_names:
            App.closeDocument(name)

    def operation(self, op, **arguments):
        request = {"op": op, **arguments}
        if op not in {"new", "open", "list_documents"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        result = self.core.dispatch(request)
        self.assertTrue(result["ok"], result)
        self.state = result["result"]
        return self.state

    def plate(self):
        self.operation("new", name="Core safety original plate")
        self.operation("sketch_rectangle", width=20, height=10)
        self.operation("pad", profile="Rectangle", length=6)
        return self.core.documents[self.state["document_id"]]

    def test_native_touched_edit_blocks_current_geometry_and_export_until_rebuild(self):
        doc = self.plate()
        accepted_revision = self.state["revision"]
        accepted_volume = self.state["measurements"]["volume_mm3"]
        doc.Pad.Length = 12
        self.assertIn("Touched", doc.Pad.State)
        state = self.operation("inspect")
        self.assertNotEqual(state["revision"], accepted_revision)
        self.assertEqual(state["build_status"], "needs_rebuild")
        self.assertIsNone(state["measurements"])
        self.assertAlmostEqual(state["retained_geometry_measurements"]["volume_mm3"], accepted_volume, places=7)
        pad = next(feature for feature in state["features"] if feature["id"] == "Pad")
        self.assertEqual(pad["parameters"]["Length"]["value"], 12)
        with tempfile.TemporaryDirectory(prefix="touched-native-export-safety-", dir=ROOT / "validation") as temporary:
            working = Path(temporary).resolve()
            self.assertTrue(working.is_relative_to(ROOT.resolve()))
            path = working / "stale-plate.step"
            response = self.core.dispatch({"op": "export", "path": str(path),
                "document_id": state["document_id"], "expected_revision": state["revision"]})
            self.assertFalse(response["ok"], response)
            self.assertFalse(path.exists())
            rebuilt = self.operation("rebuild")
            self.assertEqual(rebuilt["build_status"], "valid")
            self.assertAlmostEqual(rebuilt["measurements"]["volume_mm3"], 20 * 10 * 12, places=7)

    def test_open_live_relocated_copy_rejects_duplicate_uuid_preserves_original_mapping(self):
        doc = self.plate()
        original_id = self.state["document_id"]
        original_name = doc.Name
        with tempfile.TemporaryDirectory(prefix="duplicate-project-identity-safety-", dir=ROOT / "validation") as temporary:
            working = Path(temporary).resolve()
            self.assertTrue(working.is_relative_to(ROOT.resolve()))
            original_file = working / "original.FCStd"
            copied_file = working / "relocated-copy.FCStd"
            self.operation("save", path=str(original_file))
            shutil.copy2(original_file, copied_file)
            before_open_names = set(App.listDocuments())
            result = self.core.dispatch({"op": "open", "path": str(copied_file)})
            self.assertFalse(result["ok"], result)
            self.assertEqual(result["error"]["code"], "duplicate_document_id")
            self.assertIs(self.core.documents[original_id], doc)
            self.assertEqual(set(App.listDocuments()), before_open_names)
            self.assertEqual(self.operation("inspect")["name"], "Core safety original plate")
            self.assertEqual(self.core.documents[original_id].Name, original_name)
            App.closeDocument(original_name)
            reopened = self.operation("open", path=str(copied_file))
            self.assertEqual(reopened["document_id"], original_id)
            self.assertEqual(reopened["build_status"], "valid")
            opened_doc = self.core.documents[original_id]
            App.closeDocument(opened_doc.Name)

    def test_readonly_export_sidecar_failure_preserves_both_outputs_and_retry_hash(self):
        self.plate()
        with tempfile.TemporaryDirectory(prefix="export-provenance-pair-safety-", dir=ROOT / "validation") as temporary:
            working = Path(temporary).resolve()
            self.assertTrue(working.is_relative_to(ROOT.resolve()))
            path = working / "plate.step"
            sidecar = path.with_suffix(".step.json")
            self.operation("export", path=str(path))
            old_geometry = path.read_bytes()
            old_sidecar = sidecar.read_bytes()
            initial_provenance = json.loads(old_sidecar)
            self.assertEqual(initial_provenance["sha256"], hashlib.sha256(old_geometry).hexdigest())
            self.operation("set_parameter", feature="Pad", parameter="Length", value=12)
            os.chmod(sidecar, stat.S_IREAD)
            try:
                result = self.core.dispatch({"op": "export", "path": str(path),
                    "document_id": self.state["document_id"], "expected_revision": self.state["revision"]})
                self.assertFalse(result["ok"], result)
                self.assertEqual(path.read_bytes(), old_geometry)
                self.assertEqual(sidecar.read_bytes(), old_sidecar)
            finally:
                # Windows read-only files otherwise prevent scoped temp cleanup.
                os.chmod(sidecar, stat.S_IREAD | stat.S_IWRITE)
            self.operation("export", path=str(path))
            new_geometry = path.read_bytes()
            provenance = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertNotEqual(new_geometry, old_geometry)
            self.assertEqual(provenance["sha256"], hashlib.sha256(new_geometry).hexdigest())
            self.assertEqual(provenance["revision"], self.state["revision"])
            exported = Part.read(str(path))
            self.assertTrue(exported.isValid())
            self.assertAlmostEqual(exported.Volume, 20 * 10 * 12, places=7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
