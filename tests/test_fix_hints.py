"""Fix-hint error payloads (slice A/B U9, B3): every hint is a structured field, provoked headless.

``missing_reference`` echoes the selector and lists its nearest ``candidates`` with resolve_selector
summaries; ``missing_part`` lists ``current_parts`` (ids and names); ``path_outside_workspace`` lists
the allowed ``roots`` and a ``remedy``; ``unsupported_operation`` offers ``did_you_mean``; a studio
Remove into air (``empty_cut``) and a Remove touching no part of an auto scope (``empty_merge_scope``)
name the direction to try beside ``tool_volume_mm3``.
"""
from pathlib import Path
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller, intent_signature
from kurtshape import selectors


class FixHintTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="fix-hint-tests-")
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
        if op != "new" and self.state is not None:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def invariant(self):
        return (intent_signature(self.doc), self.core._meta(self.doc).Revision, self.doc.UndoCount,
                self.doc.RedoCount, self.doc.HasPendingTransaction)

    def reject(self, code, op, **args):
        before = self.invariant() if self.state is not None else None
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        if before is not None:
            self.assertEqual(self.invariant(), before)
        return response["error"]

    def plate(self, studio=False):
        self.call("new")
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        if studio:
            self.call("pad", id="Pad", profile="Base", length=6, operation="new", name="Plate")
            feature = self.doc.Pad.KurtShapeOutputTips[0]
        else:
            self.call("pad", id="Pad", profile="Base", length=6)
            feature = "Pad"
        top = "Face" + str(next(index + 1 for index, face in enumerate(self.doc.getObject(feature).Shape.Faces)
                                 if abs(face.CenterOfMass.z - 6) < 1e-7 and face.normalAt(0, 0).z > 0.999))
        self.call("sketch_circle", id="Top", x=10, y=5, diameter=4, support={"feature": feature, "subelement": top})

    def test_missing_reference_echoes_the_selector_and_lists_the_nearest_candidates(self):
        self.plate()
        # The plate has no cylinder: the closest-point query over cylinders matches nothing.
        selector = {"kind": "closest", "point": [10, 5, 6],
                    "query": {"kind": "geometry", "geometry": "cylinder", "query": {"kind": "owned_by", "part": "Body"}}}
        error = self.reject("missing_reference", "create_sketch", id="OnCylinder", support=selector)
        self.assertEqual(error["selector"], selector)
        candidates = error["candidates"]
        self.assertTrue(1 <= len(candidates) <= selectors.CANDIDATE_LIMIT, candidates)
        for row in candidates:
            self.assertEqual(row["entity_type"], "face")
            self.assertLessEqual({"feature", "subelement", "entity_type", "part", "summary", "distance_mm"}, set(row))
            self.assertIn("point_mm", row["summary"])
        # Ranked by distance to the selector's point: the top face holds it.
        nearest = candidates[0]
        self.assertAlmostEqual(nearest["distance_mm"], 0, places=6)
        self.assertEqual(nearest["summary"]["geometry"], "plane")
        self.assertAlmostEqual(nearest["summary"]["normal"][2], 1, places=6)
        self.assertEqual([row["distance_mm"] for row in candidates], sorted(row["distance_mm"] for row in candidates))
        # The candidate is usable as is: a literal reference to it succeeds.
        self.call("create_sketch", id="OnTop", support={"feature": nearest["feature"], "subelement": nearest["subelement"]})

    def test_missing_literal_support_face_echoes_it_and_lists_that_features_faces(self):
        self.plate()
        support = {"feature": "Pad", "subelement": "Face999"}
        error = self.reject("missing_reference", "create_sketch", id="OnNothing", support=support)
        self.assertEqual(error["message"], "Selected face does not exist")
        self.assertEqual(error["selector"], support)
        self.assertTrue(1 <= len(error["candidates"]) <= selectors.CANDIDATE_LIMIT, error["candidates"])
        for row in error["candidates"]:
            self.assertEqual((row["feature"], row["entity_type"]), ("Pad", "face"))
            self.assertIn("geometry", row["summary"])

    def test_missing_reference_candidates_rank_geometry_parameters(self):
        self.plate()
        self.call("pocket", id="Bore", profile="Top")
        # A 3 mm radius matches no circle (the bore's edges are 2 mm): the 2 mm circles come first.
        selector = {"kind": "geometry", "geometry": "circle", "radius": 3,
                    "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}
        error = self.reject("missing_reference", "fillet", id="Round", edges=[selector], radius=0.5)
        self.assertEqual(error["selector"], selector)
        self.assertTrue(error["candidates"])
        self.assertEqual(error["candidates"][0]["entity_type"], "edge")
        self.assertEqual(error["candidates"][0]["summary"]["geometry"], "circle")
        self.assertAlmostEqual(error["candidates"][0]["summary"]["radius_mm"], 2, places=6)

    def test_missing_part_lists_current_parts(self):
        self.plate(studio=True)
        parts = [{"id": row["id"], "name": row["name"]} for row in self.state["studio"]["parts"]]
        self.assertTrue(parts)
        error = self.reject("missing_part", "set_part_appearance", part="Plat", visible=True)
        self.assertEqual(error["part"], "Plat")
        self.assertEqual(error["current_parts"], parts)
        # The compact inspection keeps parts as the unknown ids and adds the same list.
        error = self.reject("missing_part", "inspect", parts=["Nope"])
        self.assertEqual(error["parts"], ["Nope"])
        self.assertEqual(error["current_parts"], parts)
        # A body that names no part (missing_body) carries them too.
        error = self.reject("missing_body", "hole", part="Nope", sketch="Top", diameter=2, depth=2)
        self.assertEqual(error["current_parts"], parts)

    def test_path_outside_workspace_lists_roots_and_the_headless_remedy(self):
        self.plate()
        folder = support.ungranted_scratch(self, self.core.settings.roots, prefix="fix-hint-outside-")
        path = folder / "outside.FCStd"
        error = self.reject("path_outside_workspace", "save", path=str(path))
        self.assertEqual(error["path"], str(path.resolve()))
        self.assertEqual(error["roots"], sorted(str(root) for root in self.core.settings.roots))
        remedy = error["remedy"]
        self.assertEqual(set(remedy), {"app", "headless", "settings_json", "project_roots_line", "hidden_app"})
        self.assertEqual(remedy["settings_json"], str(self.core.settings.path))
        self.assertTrue(remedy["project_roots_line"].startswith('"project_roots": ['))
        self.assertIn(str(folder.resolve()).replace("\\", "\\\\"), remedy["project_roots_line"])
        self.assertIn('-ProjectRoot "' + str(folder.resolve()) + '"', remedy["hidden_app"])
        self.assertIn("project_roots", remedy["headless"])
        self.assertFalse(path.exists())
        error = self.reject("path_outside_workspace", "export", path=str(folder / "outside.step"))
        self.assertEqual(error["roots"], sorted(str(root) for root in self.core.settings.roots))

    def test_unknown_operation_offers_did_you_mean(self):
        for name, expected in (("pda", "pad"), ("pocekt", "pocket"), ("sketch_rect", "sketch_rectangle"),
                               ("Inspect", "inspect")):
            with self.subTest(op=name):
                error = self.reject("unsupported_operation", name)
                self.assertEqual(error["message"], "Unknown operation")
                self.assertEqual(error["op"], name)
                self.assertIn(expected, error["did_you_mean"])
                self.assertLessEqual(len(error["did_you_mean"]), 3)
                self.assertLessEqual(set(error["did_you_mean"]), set(Controller.OPS))
        self.assertEqual(self.reject("unsupported_operation", "zzzzqqq")["did_you_mean"], [])
        error = self.core.dispatch(["not", "a", "request"])
        self.assertEqual(error["error"], {"code": "unsupported_operation", "message": "Unknown operation"})
        error = self.reject("invalid_argument", "operation_schema", operations=["pockett", "pad"])
        self.assertEqual(error["unknown"], ["pockett"])
        self.assertIn("pocket", error["did_you_mean"]["pockett"])

    def test_studio_remove_into_air_names_the_direction_to_try(self):
        self.plate(studio=True)
        part = self.state["studio"]["parts"][0]["id"]
        args = {"profile": "Top", "length": 2, "through_all": False, "operation": "remove", "direction": "along"}
        # The part is in the scope but the tool runs up into air: empty_cut.
        error = self.reject("empty_cut", "pocket", id="Air", merge_scope=[part], **args)
        self.assertEqual((error["direction_used"], error["try_direction"]), ("along", "against"))
        self.assertIn('direction:"against"', error["hint"])
        self.assertGreater(error["tool_volume_mm3"], 0)
        # The same with reversed (a studio Remove's false is along): same hint, same vocabulary.
        legacy = dict(args, reversed=False)
        del legacy["direction"]
        error = self.reject("empty_cut", "pocket", id="Air", merge_scope=[part], **legacy)
        self.assertEqual((error["direction_used"], error["try_direction"]), ("along", "against"))
        # Following the hint succeeds.
        self.call("pocket", id="Cut", merge_scope=[part], **dict(args, direction=error["try_direction"]))
        self.assertLess(self.state["result_report"]["volume_delta_mm3"], 0)
        # An auto scope the tool touches nowhere (a profile beside the plate): empty_merge_scope with the
        # same direction fields and the tool volume.
        self.call("sketch_circle", id="Beside", x=60, y=5, diameter=4, plane="XY")
        error = self.reject("empty_merge_scope", "pocket", id="Miss", **dict(args, profile="Beside"))
        self.assertEqual((error["direction_used"], error["try_direction"]), ("along", "against"))
        self.assertIn('direction:"against"', error["hint"])
        self.assertGreater(error["tool_volume_mm3"], 0)

    def test_through_all_remove_hint_names_the_profile_position(self):
        self.plate(studio=True)
        self.call("sketch_circle", id="Far", x=60, y=5, diameter=4, plane="XY")
        error = self.reject("empty_merge_scope", "pocket", id="Miss", profile="Far", operation="remove")
        self.assertNotIn("try_direction", error)
        self.assertIn("both ways", error["hint"])
        self.assertGreater(error["tool_volume_mm3"], 0)


if __name__ == "__main__":
    unittest.main()
