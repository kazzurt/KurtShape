"""Native neutral-geometry import, modeling and atomic publication gates."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, intent_signature, measurements, OperationError


class StepImportTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.temporary = tempfile.TemporaryDirectory(prefix="step-import-native-", dir=ROOT / "runtime")
        self.folder = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"KURTSHAPE_SESSION_DIR": str(self.folder)})
        self.environment.start()
        self.core = Controller()
        self.state = self.call("new")["result"]
        self.call("sketch_rectangle", id="ExistingSketch", width=10, height=10)
        self.call("pad", profile="ExistingSketch", length=5)

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)
        self.environment.stop()
        self.temporary.cleanup()

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **args):
        request = {"op": op, **args}
        if op not in self.core.CREATE_OPS | {"capabilities", "request_status"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response

    def fixture(self, name="solid.STP", shape=None):
        path = self.folder / name
        (shape if shape is not None else Part.makeBox(10, 20, 30, App.Vector(4, 5, 6))).exportStep(str(path))
        return path

    def test_real_three_solid_parts_preserve_geometry_source_and_native_roundtrip(self):
        for filename in ("Dodec pipe mount.step", "Dodec Hub Conformal.step"):
            with self.subTest(filename=filename):
                path = ROOT.parents[1] / "Onshape examples" / filename
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                expected = measurements(Part.read(str(path)))
                self.call("import_step", path=str(path))
                self.assertTrue(self.state["managed"])
                self.assertIsNone(self.state["native_file"])
                self.assertEqual(self.state["build_status"], "valid")
                self.assertEqual(len(self.state["import_source"]["body_ids"]), 3)
                self.assertEqual(self.state["measurements"]["solid_count"], 3)
                for metric in ("volume_mm3", "area_mm2"):
                    self.assertAlmostEqual(self.state["measurements"][metric], expected[metric], delta=abs(expected[metric])*1e-10)
                for key in ("min", "max", "size"):
                    for actual, wanted in zip(self.state["measurements"]["bbox_mm"][key], expected["bbox_mm"][key]):
                        self.assertAlmostEqual(actual, wanted, places=7)
                self.assertTrue(all(body["measurements"]["solid_count"] == 1 for body in self.state["bodies"]))
                self.assertFalse(any(f["type"] == "Sketcher::SketchObject" for f in self.state["features"]))
                imported = self.doc
                provenance = self.state["import_source"]
                native = self.folder / (path.stem + ".FCStd")
                self.call("save", path=str(native))
                App.closeDocument(imported.Name)
                self.call("open", path=str(native))
                self.assertEqual(self.state["import_source"], provenance)
                self.assertEqual(self.state["measurements"]["solid_count"], 3)
                self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], expected["volume_mm3"], places=6)
                exported = self.folder / (path.stem + "-roundtrip.step")
                self.call("export", path=str(exported))
                self.assertEqual(len(Part.read(str(exported)).Solids), 3)
                self.assertEqual(json.loads(exported.with_suffix(".step.json").read_text())["import_source"], provenance)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_imported_base_accepts_native_sketch_and_pad_then_undo(self):
        self.call("import_step", path=str(self.fixture(shape=Part.makeBox(10, 10, 5))))
        self.call("sketch_rectangle", id="Extension", width=10, height=10)
        self.call("pad", profile="Extension", length=8)
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 800)
        self.call("undo")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 500)
        self.assertIsNotNone(self.doc.getObject("ImportedSolid"))

    def test_mixed_reference_and_surface_only_geometry_are_retained(self):
        face = Part.makePlane(2, 3, App.Vector(30, 0, 0))
        shape = Part.makeCompound([Part.makeBox(2, 3, 4), face])
        self.call("import_step", path=str(self.fixture("mixed.step", shape)))
        self.assertEqual(self.state["measurements"]["solid_count"], 1)
        self.assertEqual(len(self.state["import_source"]["reference_ids"]), 1)
        self.assertEqual(len(self.doc.getObject(self.state["import_source"]["reference_ids"][0]).Shape.Faces), 1)
        self.call("import_step", path=str(self.fixture("surface.step", face)))
        self.assertEqual(self.state["build_status"], "sketch_only")
        self.assertEqual(self.state["import_source"]["body_ids"], [])
        self.assertEqual(len(self.state["import_source"]["reference_ids"]), 1)
        self.call("save", path=str(self.folder / "surface.FCStd"))

    def test_invalid_inputs_and_failed_publication_leave_current_project_intact(self):
        current = self.doc
        before = (intent_signature(current), self.state["revision"], current.UndoCount, current.RedoCount, current.FileName)
        names = set(App.listDocuments())
        broken = self.folder / "broken.step"
        broken.write_text("This is not a STEP file")
        cases = [({}, "invalid_argument"), ({"path": "relative.step"}, "invalid_argument"),
                 ({"path": str(self.folder / "missing.step")}, "missing_file"),
                 ({"path": str(self.folder / "bad.txt")}, "invalid_format"),
                 ({"path": str(broken)}, "step_import_failed"),
                 ({"path": str(broken), "execute": "anything"}, "unknown_argument")]
        for args, code in cases:
            response = self.core.dispatch({"op": "import_step", **args})
            self.assertFalse(response["ok"], response)
            self.assertEqual(response["error"]["code"], code, response)
        valid = self.fixture()
        with patch.object(self.core, "attach", side_effect=OperationError("test_publication_failure", "Injected native attachment failure")):
            response = self.core.dispatch({"op": "import_step", "path": str(valid)})
            self.assertEqual(response["error"]["code"], "test_publication_failure")
        self.assertEqual(set(App.listDocuments()), names)
        self.assertEqual(App.activeDocument(), current)
        self.assertEqual((intent_signature(current), self.core.inspect(current)["revision"], current.UndoCount, current.RedoCount, current.FileName), before)
        self.assertEqual(len(self.core.documents), 1)

    def test_empty_shape_and_source_changed_are_rejected_before_new_document(self):
        path = self.fixture()
        names = set(App.listDocuments())
        with patch("kurtshape.core.Part.read", return_value=Part.Shape()):
            response = self.core.dispatch({"op": "import_step", "path": str(path)})
            self.assertEqual(response["error"]["code"], "empty_step")
        def changed_file(raw):
            path.write_text("Changed while read")
            return Part.makeBox(1, 1, 1)
        with patch("kurtshape.core.Part.read", side_effect=changed_file):
            response = self.core.dispatch({"op": "import_step", "path": str(path)})
            self.assertEqual(response["error"]["code"], "source_changed")
        self.assertEqual(set(App.listDocuments()), names)

    def test_request_replay_does_not_create_duplicate_import_and_explicit_reimport_does(self):
        path = self.fixture()
        old = self.doc
        old_signature = intent_signature(old)
        request = {"op": "import_step", "path": str(path), "request_id": str(uuid.uuid4())}
        first = self.core.dispatch(request)
        self.assertTrue(first["ok"], first)
        names = set(App.listDocuments())
        self.assertEqual(self.core.dispatch(request), first)
        self.assertEqual(set(App.listDocuments()), names)
        self.call("import_step", path=str(path))
        self.assertNotEqual(self.state["document_id"], first["result"]["document_id"])
        self.assertEqual(intent_signature(old), old_signature)

    def test_import_rejects_active_lease_and_busy_operations(self):
        path = self.fixture()
        self.call("begin_sketch_edit", feature="ExistingSketch")
        response = self.core.dispatch({"op": "import_step", "path": str(path)})
        self.assertEqual(response["error"]["code"], "sketch_edit_active")
        self.call("finish_sketch_edit", cancel=True)
        self.core.busy = True
        response = self.core.dispatch({"op": "import_step", "path": str(path)})
        self.assertEqual(response["error"]["code"], "busy")
        self.assertTrue(self.core.busy)
        self.core.busy = False
        self.assertIn("import_step", self.call("capabilities")["result"]["operations"])


if __name__ == "__main__":
    unittest.main()
