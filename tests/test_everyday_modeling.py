"""Predictable default directions for Extrude (outward) and Cut (inward)."""
from pathlib import Path
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller
from kurtshape.extrusion_preview import ExtrusionEvaluator

FACES = {"top": (0, 0, 1), "bottom": (0, 0, -1), "side": (1, 0, 0), "back": (0, 1, 0)}
PLATE = 20 * 10 * 6


class EverydayModelingDirectionTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="everyday-modeling-tests-")
        self.core = Controller()
        self.state = None

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **args):
        request = dict(op=op, **args)
        if op != "new":
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def plate(self, placement=None, studio=False):
        self.call("new")
        if placement is not None:
            self.doc.Body.Placement = placement
            self.doc.recompute()
            self.call("inspect")
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        if studio:
            self.call("pad", id="Pad", profile="Base", length=6, operation="new")
        else:
            self.call("pad", id="Pad", profile="Base", length=6)

    def face(self, feature, normal):
        shape = self.doc.getObject(feature).Shape
        for index, face in enumerate(shape.Faces):
            u, v = face.Surface.parameter(face.CenterOfMass)
            if (face.normalAt(u, v) - App.Vector(*normal)).Length < 1e-6:
                return "Face%d" % (index + 1), face
        raise AssertionError("no face with normal %s" % (normal,))

    def face_sketch(self, name, normal, feature=None):
        # A studio face belongs to the operation's recorded output tip.
        feature = feature or (self.doc.Pad.KurtShapeOutputTips[0] if "KurtShapeOutputTips" in self.doc.Pad.PropertiesList else "Pad")
        subelement, face = self.face(feature, normal)
        self.call("create_sketch", id=name, support={"feature": feature, "subelement": subelement})
        center = self.doc.getObject(name).Placement.inverse().multVec(face.CenterOfMass)
        self.call("add_rectangle", sketch=name, width=2, height=2, x=center.x - 1, y=center.y - 1)
        return subelement

    def change(self, evaluator, proposal):
        result = evaluator.evaluate(proposal)
        self.assertTrue(result.valid, (proposal, result.error))
        return round(result.shape.Volume - PLATE, 6)

    def assert_defaults(self, studio, proposals):
        for label, normal in FACES.items():
            name = "S" + label
            self.face_sketch(name, normal)
            evaluator = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
            self.addCleanup(evaluator.close)
            extrude, cut = proposals(name)
            self.assertAlmostEqual(self.change(evaluator, extrude), 4, msg=label + " extrude outward")
            self.assertAlmostEqual(self.change(evaluator, cut), -4, msg=label + " cut inward")
            # A deliberate Reverse is respected: the solid goes into the
            # material, adds nothing, and the preview says so.
            flipped = evaluator.evaluate(dict(extrude, reversed=not extrude.get("reversed", False)))
            if studio:  # the studio preview shows the tool; the part is unchanged
                self.assertTrue(flipped.valid, flipped.error)
                self.assertAlmostEqual(flipped.shape.Volume, PLATE, msg=label)
            else:
                self.assertEqual((flipped.valid, flipped.error["code"]), (False, "empty_preview"), label)

    def test_native_pad_and_pocket_defaults_on_every_face(self):
        self.plate()
        self.assert_defaults(False, lambda name: (
            {"op": "pad", "profile": name, "length": 1, "reversed": False},
            {"op": "pocket", "profile": name, "length": 1, "through_all": False}))

    def test_studio_add_and_cut_defaults_on_every_face(self):
        self.plate(studio=True)
        # The GUI sends reversed=True for a default Studio Cut (into material).
        self.assert_defaults(True, lambda name: (
            {"op": "pad", "profile": name, "length": 1, "reversed": False, "operation": "add", "merge_scope": "auto"},
            {"op": "pocket", "profile": name, "length": 1, "through_all": False, "reversed": True,
             "operation": "remove", "merge_scope": "auto"}))

    def test_direct_face_extrusion_defaults(self):
        self.plate()
        evaluator = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
        self.addCleanup(evaluator.close)
        for label, normal in FACES.items():
            subelement, face = self.face("Pad", normal)
            ref = {"feature": "Pad", "subelement": subelement}
            add = self.change(evaluator, {"op": "extrude_face", "face": ref, "length": 1, "reversed": False,
                                          "operation": "add", "merge_scope": "auto"})
            cut = self.change(evaluator, {"op": "extrude_face", "face": ref, "length": 1, "reversed": True,
                                          "operation": "remove", "merge_scope": "auto"})
            self.assertAlmostEqual(add, face.Area, msg=label)
            self.assertAlmostEqual(cut, -face.Area, msg=label)

    def test_placed_rotated_body_native_defaults(self):
        self.plate(App.Placement(App.Vector(30, 10, 5), App.Rotation(App.Vector(1, 1, 0), 50)))
        self.assert_defaults(False, lambda name: (
            {"op": "pad", "profile": name, "length": 1, "reversed": False},
            {"op": "pocket", "profile": name, "length": 1, "through_all": False}))

    def test_placed_rotated_body_studio_preview_matches_confirm(self):
        """Studio output faces are global: a rotated part has no +Z top face.

        The earlier expected failure searched for a global +Z face and never
        reached the preview. Each rotated face previews validly, and Confirm
        produces exactly the previewed solid.
        """
        rotation = App.Rotation(App.Vector(1, 1, 0), 50)
        self.plate(App.Placement(App.Vector(30, 10, 5), rotation), studio=True)
        for label, normal in FACES.items():
            turned = rotation.multVec(App.Vector(*normal))
            self.face_sketch("S" + label, (turned.x, turned.y, turned.z))
        for label in FACES:
            for operation, op, reverse, delta in (("add", "pad", False, 4), ("remove", "pocket", True, -4)):
                proposal = {"op": op, "profile": "S" + label, "length": 1, "reversed": reverse,
                            "operation": operation, "merge_scope": "auto"}
                if op == "pocket":
                    proposal["through_all"] = False
                evaluator = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
                try:
                    self.assertAlmostEqual(self.change(evaluator, proposal), delta, msg=label + " " + operation)
                    previewed = evaluator.evaluate(proposal).shape.Volume
                finally:
                    evaluator.close()
                names = {obj.Name for obj in self.doc.Objects}
                self.call(op, **{key: value for key, value in proposal.items() if key != "op"})
                created = [obj for obj in self.doc.Objects
                           if obj.Name not in names and "KurtShapeOutputTips" in obj.PropertiesList]
                self.assertEqual(len(created), 1, label + " " + operation)
                committed = self.doc.getObject(created[0].KurtShapeOutputTips[0]).Shape.Volume
                self.assertAlmostEqual(committed, previewed, places=6, msg=label + " " + operation)
                self.call("undo")


if __name__ == "__main__":
    unittest.main()
