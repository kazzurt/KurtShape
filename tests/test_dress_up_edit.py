"""Editing existing Fillet/Chamfer features in place: edges, size, formula, history."""
from pathlib import Path
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller, intent_signature
from kurtshape import reference_tools

PLATE = 20 * 12 * 6


def closest(point, query=None):
    query = query or {"kind": "created_by", "feature": "Pad", "entity_type": "edge"}
    return {"kind": "closest", "point": list(point),
            "query": {"kind": "geometry", "geometry": "line", "query": query}}


def vertical_edge(shape, x, y):
    """Index name of the full-height straight edge at (x, y), or None."""
    for index, edge in enumerate(shape.Edges):
        box = edge.BoundBox
        if (abs(box.XMin - x) < 1e-6 and abs(box.XMax - x) < 1e-6 and abs(box.YMin - y) < 1e-6
                and abs(box.YMax - y) < 1e-6 and abs(box.ZLength - 6) < 1e-6):
            return "Edge%d" % (index + 1)
    return None


class DressUpEditTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="dress-up-edit-")
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
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def plate(self, studio=False):
        self.call("new")
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        if studio:
            self.call("pad", id="Pad", profile="Plate", length=6, operation="new")
        else:
            self.call("pad", id="Pad", profile="Plate", length=6)

    def snapshot(self):
        return intent_signature(self.doc), self.doc.UndoCount, self.core.inspect(self.doc)["revision"]

    def edges_of(self, name):
        feature = self.doc.getObject(name)
        return list(feature.Base[1])

    def test_reopen_reports_current_settings_and_edges_from_the_input(self):
        self.plate()
        self.call("fillet", id="Round", edges=[closest((0, 0, 3))], radius="1.2345678 mm")
        info = reference_tools.describe_dress_up(self.doc, "Round")
        self.assertEqual((info["kind"], info["key"], info["base"]), ("fillet", "radius", "Pad"))
        self.assertEqual(info["value"], {"value": 1.2345678, "expression": None, "native_property": "Radius"})
        self.assertEqual(len(info["edges"]), 1)
        # The bound selector is returned, so an untouched edge stays associative.
        self.assertEqual(info["edges"][0]["reference"], {"selector": closest((0, 0, 3))})
        element = info["edges"][0]["subelement"]
        self.assertEqual(element, vertical_edge(self.doc.Pad.Shape, 0, 0))
        # The completed fillet rounded that edge away; it remains selectable on
        # the feature's input.
        self.assertIsNone(vertical_edge(self.doc.Round.Shape, 0, 0))

    def test_edit_adds_removes_and_replaces_edges_in_one_undo_step(self):
        self.plate()
        self.call("fillet", id="Round", edges=[closest((0, 0, 3))], radius=1)
        one = self.doc.Body.Shape.Volume
        before = self.snapshot()
        self.call("edit_dress_up", feature="Round", edges=[closest((0, 0, 3)), closest((20, 0, 3))])
        self.assertEqual(self.doc.Body.Tip.Name, "Round")
        self.assertEqual(len(self.edges_of("Round")), 2)
        two = self.doc.Body.Shape.Volume
        self.assertAlmostEqual(one - two, PLATE - one, places=6)
        self.assertEqual(self.doc.UndoCount, before[1] + 1)
        self.call("undo")
        self.assertEqual(intent_signature(self.doc), before[0])
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, one, places=6)
        self.call("redo")
        self.assertEqual(len(self.edges_of("Round")), 2)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, two, places=6)
        # Replace with a plain native reference on the input, then remove down
        # to the originally rounded edge again.
        far = vertical_edge(self.doc.Pad.Shape, 20, 12)
        self.call("edit_dress_up", feature="Round", edges=[{"feature": "Pad", "subelement": far}])
        self.assertEqual(self.edges_of("Round"), [far])
        self.assertEqual(reference_tools._edge_inputs(self.doc.Round), {})
        hidden = vertical_edge(self.doc.Pad.Shape, 0, 0)
        self.call("edit_dress_up", feature="Round", edges=[{"feature": "Pad", "subelement": hidden}])
        self.assertEqual(self.edges_of("Round"), [hidden])
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, one, places=6)

    def test_undo_restores_selector_metadata_both_ways(self):
        self.plate()
        plain = vertical_edge(self.doc.Pad.Shape, 0, 0)
        self.call("fillet", id="Round", edges=[{"feature": "Pad", "subelement": plain}], radius=1)
        for edges in ([closest((0, 0, 3)), closest((20, 0, 3))], [{"feature": "Pad", "subelement": plain}]):
            before = self.snapshot()
            self.call("edit_dress_up", feature="Round", edges=edges)
            after = intent_signature(self.doc)
            self.call("undo")
            self.assertEqual(intent_signature(self.doc), before[0])
            self.call("redo")
            self.assertEqual(intent_signature(self.doc), after)

    def test_preview_is_disposable_and_matches_confirm(self):
        self.plate()
        self.call("fillet", id="Round", edges=[closest((0, 0, 3))], radius=1)
        before = self.snapshot()
        names = set(App.listDocuments())
        proposal = {"op": "edit_dress_up", "feature": "Round", "edges": [closest((20, 12, 3)), closest((0, 12, 3))],
                    "radius": 2}
        preview = self.call("preview", proposal=proposal)
        self.assertTrue(preview["valid"], preview)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(set(App.listDocuments()), names)
        self.assertFalse(self.doc.HasPendingTransaction)
        self.call("edit_dress_up", **{key: value for key, value in proposal.items() if key != "op"})
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, preview["measurements"]["volume_mm3"], places=6)
        self.assertAlmostEqual(self.doc.Round.Radius.Value, 2)

    def test_untouched_exact_value_and_formula_are_kept(self):
        self.plate()
        self.call("fillet", id="Round", edges=[closest((0, 0, 3))], radius="1.2345678 mm")
        self.call("edit_dress_up", feature="Round", edges=[closest((0, 0, 3)), closest((20, 0, 3))])
        self.assertEqual(self.doc.Round.Radius.Value, 1.2345678)
        self.call("edit_dress_up", feature="Round", expression="Pad.Length / 4")
        info = reference_tools.describe_dress_up(self.doc, "Round")
        self.assertEqual(info["value"]["expression"], "Pad.Length / 4")
        self.assertAlmostEqual(info["value"]["value"], 1.5)
        self.call("edit_dress_up", feature="Round", edges=[closest((0, 0, 3))])
        self.assertEqual(reference_tools.describe_dress_up(self.doc, "Round")["value"]["expression"], "Pad.Length / 4")
        self.call("set_parameter", feature="Pad", parameter="Length", value=8)
        self.assertAlmostEqual(self.doc.Round.Radius.Value, 2)
        before = self.snapshot()
        response = self.request("edit_dress_up", feature="Round", radius=1)
        self.assertEqual(response["error"]["code"], "expression_driven", response)
        self.assertEqual(self.snapshot(), before)
        self.call("edit_dress_up", feature="Round", expression="", radius="0.75 mm")
        info = reference_tools.describe_dress_up(self.doc, "Round")
        self.assertEqual(info["value"], {"value": 0.75, "expression": None, "native_property": "Radius"})

    def test_invalid_edits_explain_and_change_nothing(self):
        self.plate()
        self.call("fillet", id="Round", edges=[closest((0, 0, 3))], radius=1)
        before = self.snapshot()
        top = next("Face%d" % (i + 1) for i, face in enumerate(self.doc.Pad.Shape.Faces) if face.normalAt(0, 0).z > .99)
        cases = [
            ({"radius": 100}, "build_failed"),
            ({"edges": [closest((0, 0, 3)), closest((0, 0, 3))]}, "invalid_argument"),
            ({"edges": []}, "invalid_argument"),
            ({"edges": [{"feature": "Pad", "subelement": top}]}, None),
            ({"size": 1}, "invalid_argument"),
            ({"expression": "Missing.Length / 2"}, None),
        ]
        for args, code in cases:
            with self.subTest(args=args):
                preview = self.call("preview", proposal=dict(op="edit_dress_up", feature="Round", **args))
                self.assertFalse(preview["valid"], preview)
                response = self.request("edit_dress_up", feature="Round", **args)
                self.assertFalse(response["ok"], response)
                if code:
                    self.assertEqual(response["error"]["code"], code, response)
                self.assertTrue(response["error"]["message"])
                self.assertEqual(self.snapshot(), before)
        response = self.request("edit_dress_up", feature="Pad", radius=1)
        self.assertEqual(response["error"]["code"], "missing_reference")

    def test_downstream_feature_keeps_its_input_after_edit(self):
        self.plate()
        self.call("fillet", id="Round", edges=[closest((0, 0, 3))], radius=1)
        self.call("sketch_circle", id="HoleProfile", x=10, y=6, diameter=4)
        self.call("pocket", id="Hole", profile="HoleProfile", through_all=True)
        self.assertIs(self.doc.Hole.BaseFeature, self.doc.Round)
        self.call("edit_dress_up", feature="Round", edges=[closest((0, 0, 3)), closest((20, 12, 3))], radius=1.5)
        self.assertIs(self.doc.Hole.BaseFeature, self.doc.Round)
        self.assertEqual(self.doc.Body.Tip.Name, "Hole")
        self.assertTrue(self.doc.Body.Shape.isValid())
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, self.doc.Round.Shape.Volume - 3.14159265358979 * 4 * 6, places=4)

    def test_chamfer_size_and_edges(self):
        self.plate()
        self.call("chamfer", id="Bevel", edges=[closest((0, 0, 3))], size=0.5)
        one = self.doc.Body.Shape.Volume
        self.call("edit_dress_up", feature="Bevel", edges=[closest((0, 0, 3)), closest((20, 0, 3))], size="1 mm")
        info = reference_tools.describe_dress_up(self.doc, "Bevel")
        self.assertEqual((info["kind"], info["value"]["value"], len(info["edges"])), ("chamfer", 1.0, 2))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, PLATE - 2 * 6 * 0.5)
        self.call("undo")
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, one, places=6)

    def test_studio_part_edges_resolve_on_the_input_before_the_feature(self):
        self.plate(studio=True)
        part = self.state["studio"]["parts"][0]["id"]
        owned = {"kind": "owned_by", "part": part, "entity_type": "edge"}
        self.call("fillet", id="Round", part=part, edges=[closest((0, 0, 3), owned)], radius=1)
        one = self.doc.Round.Shape.Volume
        # The same part query, evaluated before Round, finds the rounded edge.
        before = self.snapshot()
        preview = self.call("preview", proposal={"op": "edit_dress_up", "feature": "Round",
                                                 "edges": [closest((0, 0, 3), owned), closest((20, 12, 3), owned)]})
        self.assertTrue(preview["valid"], preview)
        self.assertEqual(self.snapshot(), before)
        self.call("edit_dress_up", feature="Round", edges=[closest((0, 0, 3), owned), closest((20, 12, 3), owned)])
        self.assertEqual(len(self.edges_of("Round")), 2)
        self.assertAlmostEqual(one - self.doc.Round.Shape.Volume, PLATE - one, places=6)
        self.assertEqual(self.doc.UndoCount, before[1] + 1)
        self.call("undo")
        self.assertEqual(intent_signature(self.doc), before[0])
        self.call("redo")
        self.assertEqual(len(self.edges_of("Round")), 2)


if __name__ == "__main__":
    unittest.main()
