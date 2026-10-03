"""Native geometry, history and rebuild tests for typed reference consumers."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller


class ReferenceToolTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.core = Controller()
        self.state = self.call("new", name="Typed reference consumers")
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="Pad", profile="Plate", length=6)

    def tearDown(self):
        self.core.observer.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        request = dict(op=op, **args)
        if op != "new":
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def top_face(self, obj):
        return "Face" + str(next(index + 1 for index, face in enumerate(obj.Shape.Faces)
                                   if isinstance(face.Surface, Part.Plane) and face.normalAt(0, 0).z > .999))

    def test_fillet_actual_solid_one_step_undo_redo(self):
        baseline = self.doc.Body.Shape.Volume
        undo_before = self.doc.UndoCount
        self.call("fillet", id="EdgeRound", part="Body", edges=[{"feature": "Pad", "subelement": "Edge1"}], radius="1 mm")
        self.assertEqual(self.doc.UndoCount, undo_before + 1)
        self.assertTrue(self.doc.Body.Shape.isValid())
        self.assertLess(self.doc.Body.Shape.Volume, baseline)
        filleted = self.doc.Body.Shape.Volume
        self.call("undo")
        self.assertIsNone(self.doc.getObject("EdgeRound"))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, baseline, places=6)
        self.call("redo")
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, filleted, places=6)

    def test_chamfer_and_failed_fillet_preserve_current_result(self):
        self.call("chamfer", id="EdgeBreak", edges=[{"feature": "Pad", "subelement": "Edge1"}], size="0.5 mm")
        baseline, revision = self.doc.Body.Shape.Volume, self.state["revision"]
        response = self.request("fillet", id="ImpossibleRound", edges=[{"feature": "EdgeBreak", "subelement": "Edge1"}], radius=1000)
        self.assertFalse(response["ok"], response)
        self.assertIsNone(self.doc.getObject("ImpossibleRound"))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, baseline, places=6)
        self.assertEqual(self.core.inspect(self.doc)["revision"], revision)

    def test_through_all_never_silently_builds_a_finite_legacy_pad(self):
        baseline = self.doc.Body.Shape.Volume
        revision, undo_count = self.state["revision"], self.doc.UndoCount
        response = self.request("pad", id="MisleadingThroughAll", profile="Plate", length=30,
                                end_type="through_all")
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "invalid_argument")
        self.assertIsNone(self.doc.getObject("MisleadingThroughAll"))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, baseline)
        self.assertEqual(self.doc.UndoCount, undo_count)
        self.assertEqual(self.core.inspect(self.doc)["revision"], revision)

    def test_shell_removes_face_and_tracks_upstream_depth(self):
        baseline = self.doc.Body.Shape.Volume
        self.call("shell", id="Hollow", faces=[{"feature": "Pad", "subelement": self.top_face(self.doc.Pad)}],
                  thickness=1, reversed=True)
        self.assertTrue(self.doc.Body.Shape.isValid())
        self.assertEqual(len(self.doc.Body.Shape.Solids), 1)
        self.assertLess(self.doc.Body.Shape.Volume, baseline)
        self.call("set_parameter", feature="Pad", parameter="Length", value=8)
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZLength, 8, places=6)
        self.assertTrue(self.doc.Body.Shape.isValid())

    def test_projected_geometry_tracks_source_and_undo_restores_slot(self):
        self.call("create_sketch", id="UseSketch")
        edge_name = "Edge" + str(next(i + 1 for i, edge in enumerate(self.doc.Pad.Shape.Edges)
                                    if abs(edge.BoundBox.ZMin) < 1e-7 and abs(edge.BoundBox.ZLength) < 1e-7
                                    and edge.BoundBox.XLength > 19))
        self.call("project_geometry", sketch="UseSketch", references=[{"feature": "Pad", "subelement": edge_name}])
        self.assertEqual(len(self.doc.UseSketch.ExternalGeometry), 1)
        before = max(geometry.length() for geometry in self.doc.UseSketch.ExternalGeo if hasattr(geometry, "length"))
        self.call("set_parameter", feature="Plate", parameter="Width", value=25)
        after = max(geometry.length() for geometry in self.doc.UseSketch.ExternalGeo if hasattr(geometry, "length"))
        self.assertAlmostEqual(after - before, 5, places=6)
        self.call("undo")
        self.call("undo")
        self.assertEqual(len(self.doc.UseSketch.ExternalGeometry), 0)

    def test_up_to_face_native_end_updates_with_other_part(self):
        self.call("create_body", id="StopBody")
        self.call("sketch_rectangle", id="StopProfile", body="StopBody", width=5, height=5, x=50)
        self.call("pad", id="StopPad", profile="StopProfile", body="StopBody", length=10)
        self.call("sketch_circle", id="RaisedProfile", body="Body", support={"feature": "Pad", "subelement": self.top_face(self.doc.Pad)},
                  x=10, y=6, diameter=4)
        self.call("pad", id="ToFace", profile="RaisedProfile", body="Body", end_type="up_to_face",
                  up_to_face={"feature": "StopPad", "subelement": self.top_face(self.doc.StopPad)})
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMax, 10, places=6)
        self.call("set_parameter", feature="StopPad", parameter="Length", value=12)
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMax, 12, places=6)

    def test_typed_preview_is_disposable_and_stale_commit_rejects(self):
        names, volume, count, revision = set(App.listDocuments()), self.doc.Body.Shape.Volume, self.doc.UndoCount, self.state["revision"]
        preview = self.call("preview", proposal={"op": "fillet", "edges": [{"feature": "Pad", "subelement": "Edge1"}], "radius": 1})
        self.assertTrue(preview["valid"], preview)
        self.assertLess(preview["measurements"]["volume_mm3"], volume)
        self.assertEqual(set(App.listDocuments()), names)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, volume, places=6)
        self.assertEqual(self.doc.UndoCount, count)
        current = self.core.inspect(self.doc)
        self.assertEqual(current["revision"], revision)
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertFalse(self.core.busy)
        self.call("set_parameter", feature="Pad", parameter="Length", value=7)
        response = self.core.dispatch({"op": "fillet", "document_id": self.state["document_id"], "expected_revision": revision,
                                       "edges": [{"feature": "Pad", "subelement": "Edge1"}], "radius": 1})
        self.assertEqual(response["error"]["code"], "stale_revision")


if __name__ == "__main__":
    unittest.main()
