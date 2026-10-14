"""Reopened Extrude/Remove edits read native state and commit like any typed edit."""
import json
from pathlib import Path
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape import extrusion_edit, studio
from kurtshape.core import Controller, intent_signature
from kurtshape.extrusion_preview import ExtrusionEvaluator


class ExtrusionEditTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="extrusion-edit-tests-")
        self.core = Controller()
        self.state = None
        self.previews = []
        self.call("new")

    def tearDown(self):
        for preview in self.previews:
            preview.close()
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        request = dict(op=op, **args)
        if op not in {"new", "open"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def reject(self, code, op, **args):
        """A rejected request must leave intent, revision, history and geometry intact."""
        before = self.invariant()
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        self.assertEqual(self.invariant(), before)
        return response["error"]

    def invariant(self):
        return (intent_signature(self.doc), self.core._meta(self.doc).Revision, self.doc.UndoCount,
                self.doc.RedoCount, self.doc.HasPendingTransaction, round(self.volume(), 6))

    def volume(self):
        parts = studio.current_parts(self.doc) if studio.enabled(self.doc) else [self.doc.Body]
        return sum(part.Shape.Volume for part in parts if not part.Shape.isNull())

    def describe(self, feature):
        return extrusion_edit.public(extrusion_edit.describe(self.doc, feature))

    def preview(self):
        preview = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
        self.previews.append(preview)
        return preview

    def plate(self, length=6):
        self.call("sketch_rectangle", id="BaseProfile", width=20, height=10)
        self.call("pad", id="Pad", profile="BaseProfile", length=length)

    def top(self, feature="Pad", z=6):
        shape = self.doc.getObject(feature).Shape
        return "Face" + str(next(index + 1 for index, face in enumerate(shape.Faces)
                                 if abs(face.CenterOfMass.z - z) < 1e-7 and abs(face.normalAt(0, 0).z - 1) < 1e-7))

    def studio_plate(self):
        self.call("sketch_rectangle", id="BaseProfile", width=20, height=10)
        self.call("pad", id="Plate", profile="BaseProfile", length=6, operation="new")
        self.call("sketch_rectangle", id="BossProfile", width=4, height=4, x=2, y=2, plane="XY")
        self.call("pad", id="Boss", profile="BossProfile", length=9, operation="add")
        self.call("sketch_circle", id="HoleProfile", x=15, y=5, diameter=2, plane="XY")
        self.call("pocket", id="Hole", profile="HoleProfile", length=2, through_all=False,
                  reversed=False, operation="remove")

    def test_reopened_settings_come_from_native_state_not_creation_request(self):
        self.studio_plate()
        recorded = json.loads(self.doc.Boss.KurtShapeStudioOperation)
        self.assertEqual(recorded["length"], 9)
        self.call("set_parameter", feature="Boss", parameter="Length", value=11)
        info = self.describe("Boss")
        self.assertEqual(json.loads(self.doc.Boss.KurtShapeStudioOperation)["length"], 9)
        self.assertAlmostEqual(info["length"]["value"], 11)
        self.assertEqual((info["family"], info["kind"], info["operation"], info["end_type"]),
                         ("studio", "extrude", "add", "blind"))
        self.call("set_expression", feature="Boss", parameter="Length", expression="BaseProfile.Constraints.Width / 2")
        info = self.describe("Boss")
        self.assertEqual(info["length"]["expression"], "BaseProfile.Constraints.Width / 2")
        self.assertAlmostEqual(info["length"]["value"], 10)
        hole = self.describe("Hole")
        self.assertEqual((hole["kind"], hole["operation"], hole["end_type"]), ("remove", "remove", "blind"))
        # Explicit API direction is opposite the studio Remove default.
        self.assertTrue(hole["reversed"])
        self.assertEqual(hole["direction"], "along")

        self.call("new")
        self.plate()
        self.call("set_expression", feature="Pad", parameter="Length", expression="BaseProfile.Constraints.Height * 0.4")
        native = self.describe("Pad")
        self.assertEqual((native["family"], native["end_type"], native["end_types"]), ("partdesign", "blind", ["blind"]))
        self.assertAlmostEqual(native["length"]["value"], 4)
        self.assertEqual(native["length"]["expression"], "BaseProfile.Constraints.Height * 0.4")
        with self.assertRaises(Exception) as caught:
            extrusion_edit.describe(self.doc, "BaseProfile")
        self.assertEqual(caught.exception.code, "unsupported_feature")

    def test_native_edits_commit_once_and_undo_redo_as_one_step(self):
        self.plate()
        self.call("sketch_circle", id="Bore", x=10, y=5, diameter=4, support={"feature": "Pad", "subelement": self.top()})
        self.call("pocket", id="Cut", profile="Bore", through_all=True)
        through_volume = self.volume()
        undo = self.doc.UndoCount
        self.call("edit_extrusion", feature="Pad", length="1/2 in")
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 12.7)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.call("edit_extrusion", feature="Cut", end_type="blind", length=2)
        self.assertEqual(str(self.doc.Cut.Type), "Length")
        self.assertAlmostEqual(self.volume(), 20 * 10 * 12.7 - 3.141592653589793 * 4 * 2)
        self.assertEqual(self.doc.UndoCount, undo + 2)
        self.call("undo")
        self.assertEqual(str(self.doc.Cut.Type), "ThroughAll")
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 12.7)
        self.call("undo")
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 6)
        self.assertAlmostEqual(self.volume(), through_volume)
        self.call("redo")
        self.call("redo")
        self.assertEqual(str(self.doc.Cut.Type), "Length")
        self.assertAlmostEqual(self.doc.Cut.Length.Value, 2)
        self.call("edit_extrusion", feature="Cut", end_type="through_all")
        self.assertEqual(str(self.doc.Cut.Type), "ThroughAll")
        # The unused blind depth stays native; returning to Blind restores it.
        self.assertAlmostEqual(self.doc.Cut.Length.Value, 2)

    def test_failed_and_unsupported_edits_preserve_model_and_conditions(self):
        self.plate()
        self.call("sketch_circle", id="Bore", x=10, y=5, diameter=4, plane="XY")
        self.call("pocket", id="Cut", profile="Bore", through_all=True, reversed=True)
        self.reject("empty_cut", "edit_extrusion", feature="Cut", reversed=False)
        self.assertTrue(self.doc.Cut.Reversed)
        error = self.reject("unsupported_transition", "edit_extrusion", feature="Pad", end_type="through_all")
        self.assertIn("not supported yet", error["message"])
        self.assertEqual(str(self.doc.Pad.Type), "Length")
        self.reject("invalid_argument", "edit_extrusion", feature="Cut", length=3)
        self.reject("invalid_argument", "edit_extrusion", feature="Pad", length="2 s")
        self.reject("invalid_argument", "edit_extrusion", feature="Pad", reversed="yes")
        self.reject("unknown_argument", "edit_extrusion", feature="Pad", operation="new")
        self.reject("unsupported_feature", "edit_extrusion", feature="Bore", length=2)
        self.reject("missing_reference", "edit_extrusion", feature="Missing", length=2)
        stale = self.state["revision"]
        self.call("rename_feature", feature="Pad", name="Plate pad")
        before = self.invariant()
        response = self.core.dispatch({"op": "edit_extrusion", "document_id": self.state["document_id"],
                                       "expected_revision": stale, "feature": "Pad", "length": 9})
        self.assertEqual(response["error"]["code"], "stale_revision")
        self.assertEqual(self.invariant(), before)

    def test_formulas_are_never_silently_discarded(self):
        self.plate()
        self.call("edit_extrusion", feature="Pad", expression="BaseProfile.Constraints.Height / 2")
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 5)
        self.call("set_parameter", feature="BaseProfile", parameter="Height", value=16)
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 8)
        error = self.reject("expression_driven", "edit_extrusion", feature="Pad", length=3)
        self.assertEqual(error["expression"], "BaseProfile.Constraints.Height / 2")
        self.reject("invalid_argument", "edit_extrusion", feature="Pad", expression="import os", length=3)
        self.reject("invalid_expression", "edit_extrusion", feature="Pad", expression="Missing.Constraints.Width")
        self.assertEqual(self.describe("Pad")["length"]["expression"], "BaseProfile.Constraints.Height / 2")
        # A direction-only edit keeps the formula untouched.
        self.call("edit_extrusion", feature="Pad", reversed=True)
        self.assertEqual(self.describe("Pad")["length"]["expression"], "BaseProfile.Constraints.Height / 2")
        self.call("edit_extrusion", feature="Pad", expression=None, length=3)
        info = self.describe("Pad")
        self.assertIsNone(info["length"]["expression"])
        self.assertAlmostEqual(info["length"]["value"], 3)
        self.call("undo")
        self.assertEqual(self.describe("Pad")["length"]["expression"], "BaseProfile.Constraints.Height / 2")

    def test_downstream_references_follow_edit_and_survive_save_reopen(self):
        self.plate()
        top = self.top()
        self.call("sketch_circle", id="Attached", x=10, y=5, diameter=4, support={"feature": "Pad", "subelement": top})
        self.call("pad", id="Boss", profile="Attached", length=2)
        ids = [feature["id"] for feature in self.state["features"]]
        self.call("edit_extrusion", feature="Pad", length=9)
        self.assertEqual([feature["id"] for feature in self.state["features"]], ids)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertAlmostEqual(self.doc.Attached.getGlobalPlacement().Base.z, 9)
        self.assertEqual(self.doc.Attached.AttachmentSupport[0][0].Name, "Pad")
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMax, 11)
        self.call("edit_extrusion", feature="Pad", expression="BaseProfile.Constraints.Width / 4")
        volume = self.volume()
        project = self.folder / "edited-extrusion.FCStd"
        self.call("save", path=str(project))
        App.closeDocument(self.doc.Name)
        response = self.core.dispatch({"op": "open", "path": str(project)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        info = self.describe("Pad")
        self.assertEqual(info["length"]["expression"], "BaseProfile.Constraints.Width / 4")
        self.assertAlmostEqual(info["length"]["value"], 5)
        self.assertAlmostEqual(self.volume(), volume)
        self.assertAlmostEqual(self.doc.Attached.getGlobalPlacement().Base.z, 5)
        self.call("edit_extrusion", feature="Pad", expression=None, length=7)
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMax, 9)

    def test_studio_edits_keep_identity_and_validate_recorded_results(self):
        self.studio_plate()
        order = list(self.state["studio"]["feature_order"])
        before = self.volume()
        self.call("edit_extrusion", feature="Boss", length=12)
        self.assertAlmostEqual(self.doc.BossTool.LengthFwd.Value, 12)
        self.assertAlmostEqual(self.volume(), before + 4 * 4 * 3)
        self.call("edit_extrusion", feature="Hole", length=4)
        before_upstream = self.volume()
        # Upstream edit after later operations consumed this part's output Body.
        self.call("edit_extrusion", feature="Plate", length=3)
        self.assertAlmostEqual(self.doc.Plate.LengthFwd.Value, 3)
        self.assertEqual(self.state["studio"]["feature_order"], order)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertAlmostEqual(self.volume(), 20 * 10 * 3 + 4 * 4 * 9 - 3.141592653589793 * 3)
        self.reject("empty_cut", "edit_extrusion", feature="Hole", reversed=False)
        self.call("sketch_circle", id="Bore", x=5, y=7, diameter=2, plane="XY")
        self.call("pocket", id="Through", profile="Bore", through_all=True, operation="remove")
        through = self.describe("Through")
        self.assertEqual((through["end_type"], through["reverse_editable"], through["reversed"]), ("through_all", False, False))
        self.reject("unsupported_parameter", "edit_extrusion", feature="Through", reversed=True)
        self.reject("unsupported_transition", "edit_extrusion", feature="Through", end_type="blind", length=2)
        for _ in range(3):  # Through, its sketch, then the single upstream edit step
            self.call("undo")
        self.assertAlmostEqual(self.doc.Plate.LengthFwd.Value, 6)
        self.assertAlmostEqual(self.volume(), before_upstream)
        self.call("redo")
        self.assertAlmostEqual(self.doc.Plate.LengthFwd.Value, 3)

    def test_exact_preview_matches_acceptance_without_live_changes(self):
        self.plate()
        self.call("sketch_circle", id="Bore", x=10, y=5, diameter=4, plane="XY")
        self.call("pocket", id="Cut", profile="Bore", through_all=True, reversed=True)
        before = self.invariant()
        preview = self.preview()
        deeper = preview.evaluate({"op": "edit_extrusion", "feature": "Pad", "length": "10 mm"})
        self.assertTrue(deeper.valid, deeper.error)
        self.assertAlmostEqual(deeper.material_shape.Volume, 20 * 10 * 4)
        self.assertFalse(deeper.measurements["edit_removal"])
        blind = preview.evaluate({"op": "edit_extrusion", "feature": "Cut", "end_type": "blind", "length": 2})
        self.assertTrue(blind.valid, blind.error)
        self.assertTrue(blind.measurements["edit_removal"])
        empty = preview.evaluate({"op": "edit_extrusion", "feature": "Cut", "reversed": False})
        self.assertFalse(empty.valid)
        self.assertEqual(empty.error["code"], "empty_cut")
        self.assertEqual(self.invariant(), before)
        preview.close()
        accepted = dict(blind.proposal)
        accepted.pop("op")
        self.call("edit_extrusion", **accepted)
        self.assertAlmostEqual(self.volume(), blind.measurements["volume_mm3"])

    def test_wire_preview_rejects_stale_edit_and_reports_validity(self):
        self.plate()
        response = self.core.dispatch({"op": "preview", "document_id": self.state["document_id"],
                                       "expected_revision": self.state["revision"],
                                       "proposal": {"op": "edit_extrusion", "feature": "Pad", "length": 8}})
        self.assertTrue(response["ok"], response)
        self.assertTrue(response["result"]["valid"], response["result"])
        self.assertAlmostEqual(response["result"]["measurements"]["volume_mm3"], 20 * 10 * 8)
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 6)

    def test_open_profiles_report_free_endpoints(self):
        self.call("create_sketch", id="OpenProfile")
        self.call("add_line", sketch="OpenProfile", x1=0, y1=0, x2=10, y2=0)
        self.call("add_line", sketch="OpenProfile", x1=10, y1=0, x2=10, y2=5)
        before = self.invariant()
        response = self.request("pad", profile="OpenProfile", length=2)
        self.assertEqual(response["error"]["code"], "open_profile", response)
        self.assertEqual(sorted(gap["point_mm"] for gap in response["error"]["open_endpoints"]), [[0.0, 0.0], [10.0, 5.0]])
        self.assertIn("free endpoint", response["error"]["message"])
        self.assertEqual(self.invariant(), before)
        response = self.request("pad", profile="OpenProfile", length=2, operation="new")
        self.assertEqual(response["error"]["code"], "open_profile", response)
        self.assertEqual(self.invariant(), before)
        result = self.preview().evaluate({"op": "pad", "profile": "OpenProfile", "length": 2})
        self.assertEqual(result.error["code"], "open_profile")
        self.call("add_line", sketch="OpenProfile", x1=10, y1=5, x2=0, y2=0)
        self.assertEqual(extrusion_edit.profile_gaps(self.doc.OpenProfile), [])
        self.call("pad", profile="OpenProfile", length=2)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 10 * 5 / 2 * 2)

    def test_near_closed_and_transformed_open_profiles_report_sketch_coordinates(self):
        self.call("create_sketch", id="AlmostClosed")
        for x1, y1, x2, y2 in ((0, 0, 10, 0), (10, 0, 10, 5), (10, 5, 0, 5), (0, 5, 0, 0.0000004)):
            self.call("add_line", sketch="AlmostClosed", x1=x1, y1=y1, x2=x2, y2=y2)
        self.assertFalse(any(wire.isClosed() for wire in self.doc.AlmostClosed.Shape.Wires))
        before = self.invariant()
        response = self.request("pad", profile="AlmostClosed", length=2)
        self.assertEqual(response["error"]["code"], "open_profile", response)
        points = sorted(gap["point_mm"] for gap in response["error"]["open_endpoints"])
        self.assertEqual(len(points), 2)
        self.assertAlmostEqual(points[0][1], 0)
        self.assertAlmostEqual(points[1][1], 0.0000004)
        self.assertEqual(self.invariant(), before)

        self.call("create_body", id="Moved")
        self.doc.Moved.Placement = App.Placement(App.Vector(100, 200, 30), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.call("inspect")
        self.call("create_sketch", body="Moved", id="MovedOpen", plane="XY")
        self.call("add_line", sketch="MovedOpen", x1=1, y1=2, x2=3, y2=4)
        before = self.invariant()
        response = self.request("pad", body="Moved", profile="MovedOpen", length=2)
        self.assertEqual(response["error"]["code"], "open_profile", response)
        self.assertEqual(sorted(gap["point_mm"] for gap in response["error"]["open_endpoints"]), [[1.0, 2.0], [3.0, 4.0]])
        self.assertIn("(1, 2)", response["error"]["message"])
        self.assertEqual(self.invariant(), before)

    def test_signed_formula_depth_reports_actual_direction_and_is_kept(self):
        self.call("sketch_rectangle", id="BaseProfile", width=20, height=10)
        self.call("pad", id="Plate", profile="BaseProfile", length=3, operation="new")
        self.assertEqual(self.describe("Plate")["direction"], "along")
        self.call("edit_extrusion", feature="Plate", expression="-2 mm")
        part = studio.current_parts(self.doc)[0]
        self.assertAlmostEqual(part.Shape.BoundBox.ZMin, -2)
        self.assertAlmostEqual(part.Shape.BoundBox.ZMax, 0)
        info = self.describe("Plate")
        self.assertEqual(info["direction"], "against")
        self.assertEqual(info["length"]["expression"], "-2 mm")
        self.assertTrue(any("negative" in item for item in info["limitations"]))
        # A direction-only edit leaves the signed formula untouched.
        self.call("edit_extrusion", feature="Plate", reversed=True)
        self.assertEqual(self.describe("Plate")["length"]["expression"], "-2 mm")
        self.assertAlmostEqual(studio.current_parts(self.doc)[0].Shape.BoundBox.ZMax, 2)
        self.assertEqual(self.describe("Plate")["direction"], "along")


if __name__ == "__main__":
    unittest.main()
