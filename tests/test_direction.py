"""One direction vocabulary for pad, pocket and hole; the legacy pad's empty-add check (slice A/B U9, B2).

``direction: "along" | "against"`` names the side of the profile normal the tool runs to. ``reversed``
keeps its per-operation meaning for one release (a legacy Pocket's ``true`` and a studio Remove's
``false`` both cut along the normal; a hole's ``true`` drills along it), and giving both rejects.
Volumes are proved on a 20 x 10 x 6 plate with a 4 mm circle on the top face (normal +Z) or on the
XY plane under the plate (normal +Z, into the plate).
"""
import math
from pathlib import Path
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller, intent_signature

PLATE = 20 * 10 * 6
DISC = math.pi * 2 ** 2  # a 4 mm circle
DEPTH = 2


class DirectionTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="direction-tests-")
        self.core = Controller()
        self.state = None

    def tearDown(self):
        self.core.close()
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
        self.state = response["result"]
        return self.state

    def bodies(self):
        return [obj for obj in self.doc.Objects if obj.TypeId == "PartDesign::Body" and not obj.Shape.isNull()
                and obj.Shape.Solids and not getattr(obj, "KurtShapeInternal", False)]

    def volume(self):
        return sum(body.Shape.Volume for body in self.bodies())

    def invariant(self):
        # RedoCount is left out: outcome() undoes each commit, and any later request (accepted or
        # rejected) opens a native transaction, which drops that redo step (pre-existing FreeCAD behaviour).
        return (intent_signature(self.doc), self.core._meta(self.doc).Revision, self.doc.UndoCount,
                self.doc.HasPendingTransaction, round(self.volume(), 6))

    def plate(self, studio=False):
        self.call("new")
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        if studio:
            self.call("pad", id="Pad", profile="Base", length=6, operation="new")
            feature = self.doc.Pad.KurtShapeOutputTips[0]
            self.part = self.state["studio"]["parts"][0]["id"]
        else:
            self.call("pad", id="Pad", profile="Base", length=6)
            feature, self.part = "Pad", "Body"
        top = "Face" + str(next(index + 1 for index, face in enumerate(self.doc.getObject(feature).Shape.Faces)
                                 if abs(face.CenterOfMass.z - 6) < 1e-7 and face.normalAt(0, 0).z > 0.999))
        self.call("sketch_circle", id="Top", x=10, y=5, diameter=4, support={"feature": feature, "subelement": top})
        self.top = {"feature": feature, "subelement": top}
        self.call("sketch_circle", id="Bottom", x=10, y=5, diameter=4, plane="XY")
        self.assertAlmostEqual(self.volume(), PLATE, places=6)

    def outcome(self, op, **args):
        """``(volume change, z range)`` of a committed request (then undone), or its error."""
        before = self.invariant()
        response = self.request(op, **args)
        if not response["ok"]:
            self.assertEqual(self.invariant(), before, "a rejection leaves the model unchanged")
            return response["error"]
        self.state = response["result"]
        boxes = [body.Shape.BoundBox for body in self.bodies()]
        change = (round(self.volume() - before[4], 6), round(min(box.ZMin for box in boxes), 6),
                  round(max(box.ZMax for box in boxes), 6))
        self.call("undo")
        self.assertAlmostEqual(self.volume(), before[4], places=6)
        return change

    def assert_error(self, outcome, code):
        self.assertIsInstance(outcome, dict, outcome)
        self.assertEqual(outcome["code"], code, outcome)
        return outcome

    # -- pad -----------------------------------------------------------------------------------

    def test_legacy_pad_along_and_against(self):
        self.plate()
        along = self.outcome("pad", id="Up", profile="Top", length=DEPTH, direction="along")
        self.assertEqual(along, (round(DISC * DEPTH, 6), 0, 6 + DEPTH))
        against = self.outcome("pad", id="Down", profile="Bottom", length=DEPTH, direction="against")
        self.assertEqual(against, (round(DISC * DEPTH, 6), -DEPTH, 6))
        # reversed keeps its meaning: false extrudes along, true against.
        self.assertEqual(self.outcome("pad", id="Up", profile="Top", length=DEPTH, reversed=False), along)
        self.assertEqual(self.outcome("pad", id="Down", profile="Bottom", length=DEPTH, reversed=True), against)
        self.assertEqual(self.outcome("pad", id="Up", profile="Top", length=DEPTH), along, "omitted: along")

    def test_up_to_face_pad_inside_material_gets_a_position_hint_without_a_direction(self):
        """direction has no effect on an up-to-face end, so the empty_add names no direction to try."""
        self.plate()
        for extra in ({}, {"direction": "along"}, {"direction": "against"}):
            with self.subTest(extra=extra):
                error = self.assert_error(self.outcome("pad", id="Inside", profile="Bottom", up_to_face=self.top, **extra),
                                          "empty_add")
                self.assertNotIn("try_direction", error)
                self.assertNotIn("direction_used", error)
                self.assertIn("up-to-face", error["hint"])

    def test_legacy_pad_inside_material_rejects_empty_add_with_the_direction_hint(self):
        """U9 item 3: a legacy Pad that adds nothing is rejected, the model unchanged (outcome() checks it)."""
        self.plate()
        for args, used in (({"profile": "Top", "direction": "against"}, "against"),
                           ({"profile": "Bottom", "direction": "along"}, "along"),
                           ({"profile": "Bottom"}, "along"), ({"profile": "Top", "reversed": True}, "against")):
            with self.subTest(args=args):
                error = self.assert_error(self.outcome("pad", id="Inside", length=DEPTH, **args), "empty_add")
                self.assertEqual(error["feature"], "Inside")
                self.assertEqual((error["direction_used"], error["try_direction"]),
                                 (used, "against" if used == "along" else "along"))
                self.assertIn('direction:"' + error["try_direction"] + '"', error["hint"])
                self.assertLess(abs(error["volume_added_mm3"]), 1e-7)
                self.assertAlmostEqual(error["volume_before_mm3"], PLATE, places=6)
        self.assertNotIn("Inside", [obj.Name for obj in self.doc.Objects])

    def test_studio_pad_along_and_against(self):
        self.plate(studio=True)
        along = self.outcome("pad", id="Up", profile="Top", length=DEPTH, direction="along", operation="add")
        self.assertEqual(along, (round(DISC * DEPTH, 6), 0, 6 + DEPTH))
        against = self.outcome("pad", id="Down", profile="Bottom", length=DEPTH, direction="against", operation="add")
        self.assertEqual(against, (round(DISC * DEPTH, 6), -DEPTH, 6))
        self.assertEqual(self.outcome("pad", id="Up", profile="Top", length=DEPTH, reversed=False, operation="add"), along)
        self.assertEqual(self.outcome("pad", id="Down", profile="Bottom", length=DEPTH, reversed=True, operation="add"),
                         against)
        error = self.assert_error(self.outcome("pad", id="Inside", profile="Top", length=DEPTH, direction="against",
                                               operation="add", merge_scope=[self.part]), "empty_add")
        self.assertEqual((error["direction_used"], error["try_direction"]), ("against", "along"))
        self.assertGreater(error["tool_volume_mm3"], 0)

    # -- pocket --------------------------------------------------------------------------------

    def test_legacy_pocket_along_and_against(self):
        self.plate()
        cut = (round(-DISC * DEPTH, 6), 0, 6)
        args = {"length": DEPTH, "through_all": False}
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Top", direction="against", **args), cut)
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Bottom", direction="along", **args), cut)
        # A legacy Pocket's reversed: false cuts against the normal, true along it.
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Top", reversed=False, **args), cut)
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Bottom", reversed=True, **args), cut)
        # Omitted: against, then the other side when that removes nothing; an explicit direction is kept.
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Bottom", **args), cut)
        error = self.assert_error(self.outcome("pocket", id="Air", profile="Top", direction="along", **args), "empty_cut")
        self.assertEqual((error["direction_used"], error["try_direction"]), ("along", "against"))
        self.assertIn('direction:"against"', error["hint"])

    def test_studio_pocket_along_and_against(self):
        self.plate(studio=True)
        cut = (round(-DISC * DEPTH, 6), 0, 6)
        args = {"length": DEPTH, "through_all": False, "operation": "remove", "merge_scope": [self.part]}
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Top", direction="against", **args), cut)
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Bottom", direction="along", **args), cut)
        # A studio Remove's reversed: true cuts against the normal (the default), false along it.
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Top", reversed=True, **args), cut)
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Bottom", reversed=False, **args), cut)
        self.assertEqual(self.outcome("pocket", id="Cut", profile="Top", **args), cut, "omitted: against")
        error = self.assert_error(self.outcome("pocket", id="Air", profile="Top", direction="along", **args), "empty_cut")
        self.assertEqual((error["direction_used"], error["try_direction"]), ("along", "against"))

    # -- hole ----------------------------------------------------------------------------------

    def assert_holes(self, studio):
        self.plate(studio=studio)
        part = {"part": self.part}
        args = {"sketch": "Top", "diameter": 3, "depth": 4, "point_angle": "flat", **part}
        drilled = (round(-math.pi * 1.5 ** 2 * 4, 6), 0, 6)
        self.assertEqual(self.outcome("hole", id="Drill", direction="against", **args), drilled)
        self.assertEqual(self.outcome("hole", id="Drill", reversed=False, **args), drilled)
        self.assertEqual(self.outcome("hole", id="Drill", **args), drilled, "omitted: against")
        bottom = dict(args, sketch="Bottom")
        self.assertEqual(self.outcome("hole", id="Drill", direction="along", **bottom), drilled)
        self.assertEqual(self.outcome("hole", id="Drill", reversed=True, **bottom), drilled)
        error = self.assert_error(self.outcome("hole", id="Air", direction="along", **args), "empty_cut")
        self.assertEqual((error["direction_used"], error["try_direction"]), ("along", "against"))
        self.assertIn('direction:"against"', error["message"])

    def test_legacy_hole_along_and_against(self):
        self.assert_holes(False)

    def test_studio_hole_along_and_against(self):
        self.assert_holes(True)

    # -- the argument --------------------------------------------------------------------------

    def test_direction_and_reversed_together_or_a_bad_value_reject(self):
        self.plate()
        cases = [("pad", {"profile": "Top", "length": DEPTH}), ("pocket", {"profile": "Top", "length": DEPTH, "through_all": False}),
                 ("pocket", {"profile": "Top", "length": DEPTH, "through_all": False, "operation": "remove"}),
                 ("hole", {"sketch": "Top", "diameter": 3, "depth": 4})]
        for op, args in cases:
            with self.subTest(op=op, args=args):
                both = self.assert_error(self.outcome(op, direction="along", reversed=False, **args), "invalid_argument")
                self.assertEqual(both["fields"], ["direction", "reversed"])
                bad = self.assert_error(self.outcome(op, direction="up", **args), "invalid_argument")
                self.assertEqual(bad["fields"], ["direction"])

    def test_preview_and_batch_accept_direction(self):
        self.plate()
        def preview(**proposal):
            response = self.request("preview", proposal=dict(op="pad", profile="Top", length=DEPTH, **proposal))
            self.assertTrue(response["ok"], response)
            return response["result"]
        self.assertTrue(preview(id="Up", direction="along")["accepted"])
        inside = preview(id="Down", direction="against")
        self.assertFalse(inside["accepted"])
        self.assertEqual(inside["error"]["code"], "empty_add", "the preview read agrees with the commit")
        self.call("batch", steps=[{"op": "pad", "id": "Up", "profile": "Top", "length": DEPTH, "direction": "along"}])
        self.assertAlmostEqual(self.volume(), PLATE + DISC * DEPTH, places=6)
        # The recorded native feature carries the translated reversed, not the request's direction.
        self.assertFalse(self.doc.Up.Reversed)

    def test_schema_documents_direction_per_operation(self):
        from kurtshape import operation_schemas as schemas
        for op, omitted in (("pad", "extrudes along"), ("pocket", "cuts against"), ("hole", "drills against")):
            with self.subTest(op=op):
                field = schemas.field_schema(op, "direction")
                self.assertEqual(field["type"], "string")
                self.assertIn("Omitted: " + omitted, field["description"])
                self.assertNotIn("default", field)
                built = schemas.build(Controller)["operations"][op]["request"]["properties"]["direction"]
                self.assertEqual(built["enum"], ["along", "against"])
                self.assertIn("direction", Controller.ARGS[op])


if __name__ == "__main__":
    unittest.main()
