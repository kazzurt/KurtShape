"""Native preview results must match acceptance without changing live intent."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller, intent_signature
from kurtshape.extrusion_preview import ExtrusionEvaluator


class ExtrusionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.temporary = tempfile.TemporaryDirectory(prefix="extrusion-preview-tests-", dir=ROOT / "runtime")
        self.environment = patch.dict(os.environ, {"KURTSHAPE_SESSION_DIR": self.temporary.name})
        self.environment.start()
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
        self.environment.stop()
        self.temporary.cleanup()

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

    def preview(self):
        preview = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
        self.previews.append(preview)
        return preview

    def invariant(self):
        return (intent_signature(self.doc), self.core.identifier(self.doc), self.core._meta(self.doc).Revision,
                self.doc.UndoCount, self.doc.RedoCount, self.doc.HasPendingTransaction, self.doc.FileName,
                tuple(App.listDocuments()), tuple(self.core.documents), tuple(self.core.observer.states),
                tuple(self.core.evaluations), App.activeDocument().Name,
                json.dumps(self.core._meta(self.doc).SourceMapping))

    def plate(self):
        self.call("sketch_rectangle", id="BaseProfile", width=20, height=10)
        self.call("pad", profile="BaseProfile", length=6)

    def top(self):
        return "Face" + str(next(index + 1 for index, face in enumerate(self.doc.Pad.Shape.Faces)
                                 if abs(face.CenterOfMass.z - 6) < 1e-7))

    def test_initial_pad_quantity_reverse_cache_and_cancel_are_disposable(self):
        self.call("sketch_rectangle", id="Profile", width=20, height=10)
        baseline = self.invariant()
        preview = self.preview()
        first = preview.evaluate(dict(op="pad", profile="Profile", length="1/8 in", reversed=False))
        self.assertTrue(first.valid, first.error)
        self.assertAlmostEqual(first.shape.Volume, 20 * 10 * 3.175)
        self.assertAlmostEqual(first.material_shape.Volume, first.shape.Volume)
        self.assertAlmostEqual(first.shape.BoundBox.ZMin, 0)
        reverse = preview.evaluate(dict(op="pad", profile="Profile", length=3.175, reversed=True))
        self.assertTrue(reverse.valid, reverse.error)
        self.assertAlmostEqual(reverse.shape.BoundBox.ZMin, -3.175)
        cached = preview.evaluate(dict(op="pad", profile="Profile", length=3.175, reversed=False))
        self.assertTrue(cached.cached)
        self.assertEqual(preview.evaluations, 2)
        self.assertEqual(self.invariant(), baseline)
        folder = preview._snapshot.parent
        preview.close()
        self.assertFalse(folder.exists())
        self.assertEqual(self.invariant(), baseline)

    def test_attached_pad_and_blind_through_all_pockets_match_actual_acceptance(self):
        self.plate()
        self.call("sketch_circle", id="Attached", x=10, y=5, diameter=4,
                  support={"feature": "Pad", "subelement": self.top()})
        baseline = self.invariant()
        preview = self.preview()
        add = preview.evaluate(dict(op="pad", profile="Attached", length=2, reversed=False))
        self.assertTrue(add.valid, add.error)
        self.assertAlmostEqual(add.shape.Volume - 1200, 3.141592653589793 * 4 * 2)
        self.assertAlmostEqual(add.material_shape.Volume, add.shape.Volume - 1200)
        blind = preview.evaluate(dict(op="pocket", profile="Attached", length=2, through_all=False, reversed=False))
        self.assertTrue(blind.valid, blind.error)
        through = preview.evaluate(dict(op="pocket", profile="Attached", through_all=True, reversed=False, length="bad input"))
        self.assertTrue(through.valid, through.error)
        self.assertAlmostEqual(through.material_shape.Volume, 3.141592653589793 * 4 * 6)
        self.assertLess(through.shape.Volume, blind.shape.Volume)
        invalid_direction = preview.evaluate(dict(op="pocket", profile="Attached", through_all=True, reversed=True))
        self.assertFalse(invalid_direction.valid)
        self.assertEqual(invalid_direction.error["code"], "empty_cut")
        self.assertEqual(self.invariant(), baseline)
        preview.close()
        self.call("pocket", id="Accepted", **{key: value for key, value in blind.proposal.items() if key != "op"})
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, blind.shape.Volume)
        self.assertEqual(self.doc.UndoCount, baseline[3] + 1)
        self.assertAlmostEqual(self.doc.Accepted.Length.Value, 2)

    def test_origin_plane_pocket_follows_default_direction_and_reversed_changes(self):
        self.plate()
        self.call("sketch_circle", id="BottomCut", x=10, y=5, diameter=4)
        baseline = self.invariant()
        preview = self.preview()
        automatic = preview.evaluate(dict(op="pocket", profile="BottomCut", length=2, through_all=False))
        self.assertTrue(automatic.valid, automatic.error)
        explicit = preview.evaluate(dict(op="pocket", profile="BottomCut", length=2, through_all=False, reversed=True))
        self.assertTrue(explicit.valid, explicit.error)
        self.assertAlmostEqual(automatic.shape.Volume, explicit.shape.Volume)
        opposite = preview.evaluate(dict(op="pocket", profile="BottomCut", length=2, through_all=False, reversed=False))
        self.assertFalse(opposite.valid)
        self.assertEqual(self.invariant(), baseline)

    def test_second_body_preview_uses_profile_owner_and_world_placement(self):
        self.plate()
        self.call("create_body", id="Housing")
        self.call("sketch_rectangle", body="Housing", id="SecondProfile", width=4, height=5, plane="YZ")
        self.doc.Housing.Placement.Base = App.Vector(40, 0, 0)
        self.doc.recompute()
        self.call("inspect")
        baseline = self.invariant()
        preview = self.preview()
        result = preview.evaluate(dict(op="pad", profile="SecondProfile", length=3))
        self.assertTrue(result.valid, result.error)
        self.assertEqual(result.body_id, "Housing")
        self.assertAlmostEqual(result.shape.Volume, 60)
        self.assertAlmostEqual(result.shape.BoundBox.XMin, 40)
        self.assertAlmostEqual(result.shape.BoundBox.XMax, 43)
        self.assertEqual(self.invariant(), baseline)
        mismatch = preview.evaluate(dict(op="pad", body="Body", profile="SecondProfile", length=3))
        self.assertFalse(mismatch.valid)
        self.assertEqual(mismatch.error["code"], "cross_body_reference")
        self.assertEqual(self.invariant(), baseline)

    def test_bad_text_missing_profile_open_geometry_and_stale_task_keep_live_model(self):
        self.call("create_sketch", id="OpenProfile")
        self.call("add_line", sketch="OpenProfile", x1=0, y1=0, x2=10, y2=0)
        baseline = self.invariant()
        preview = self.preview()
        for proposal, code in [
            (dict(op="pad", profile="OpenProfile", length="2 s"), "invalid_argument"),
            (dict(op="pad", profile="OpenProfile", length=-2), "invalid_argument"),
            (dict(op="pad", profile="Missing", length=2), "missing_reference"),
            (dict(op="pad", profile="OpenProfile", length=2), "build_failed"),
            (dict(op="pad", profile="OpenProfile", length=2, reversed="yes"), "invalid_argument"),
        ]:
            result = preview.evaluate(proposal)
            self.assertFalse(result.valid, proposal)
            self.assertEqual(result.error["code"], code, result.error)
            self.assertEqual(self.invariant(), baseline)
        self.call("rename_feature", feature="OpenProfile", name="Changed")
        after_change = self.invariant()
        result = preview.evaluate(dict(op="pad", profile="OpenProfile", length=2))
        self.assertEqual(result.error["code"], "stale_revision")
        self.assertEqual(self.invariant(), after_change)


if __name__ == "__main__":
    unittest.main(verbosity=2)
