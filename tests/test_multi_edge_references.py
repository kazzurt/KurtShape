"""Multi edge references: one {selector, all:true} entry stands for every matching edge.

Fixture: plate 40x20x6 (Pad) with two bosses of height 4 (BossPad): r=3 at
(10, 10) and r=5 at (28, 10). The r=3 query matches the small boss's top and
base circles.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, intent_signature
from kurtshape import reference_tools, selectors


def owned(part="Body"):
    return {"kind": "owned_by", "part": part, "entity_type": "edge"}


def circles(radius, part="Body"):
    return {"kind": "geometry", "geometry": "circle", "radius": radius, "query": owned(part)}


def top_circles():
    return {"kind": "geometry", "geometry": "circle",
            "query": {"kind": "created_by", "feature": "BossPad", "entity_type": "edge", "cap": "end"}}


def every(selector):
    return {"selector": selector, "all": True}


def closest(point, part="Body", geometry="line"):
    return {"kind": "closest", "point": list(point), "query": {"kind": "geometry", "geometry": geometry, "query": owned(part)}}


class MultiEdgeReferenceTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="multi-edge-references-")
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
        request = {"op": op, "measure": False, **args}
        if op not in {"new", "open"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def bosses(self):
        self.call("new", name="Multi edge references")
        self.call("sketch_rectangle", id="Plate", width=40, height=20)
        self.call("pad", id="Pad", profile="Plate", length=6)
        self.call("sketch_circle", id="Bosses", body="Body", support={"kind": "created_by", "feature": "Pad", "cap": "end"},
                  x=10, y=10, diameter=6)
        self.call("add_circle", sketch="Bosses", x=28, y=10, diameter=10)
        self.call("pad", id="BossPad", profile="Bosses", body="Body", length=4)

    def inputs(self, name="Round"):
        return json.loads(self.doc.getObject(name).QueryInputs)

    def health(self, name="Round"):
        return {entry["input"]: entry for entry in json.loads(self.doc.getObject(name).QueryHealth)}

    def assert_healthy(self, name="Round"):
        self.assertTrue(all(entry["status"] == "healthy" for entry in self.health(name).values()), self.health(name))
        self.assertFalse(selectors.reference_errors(self.doc))

    def base_edges(self, name="Round"):
        base, names = self.doc.getObject(name).Base
        return base, list(names)

    def radii(self, name="Round"):
        base, names = self.base_edges(name)
        values = []
        for element in names:
            curve = base.Shape.getElement(element).Curve
            values.append(round(curve.Radius, 9) if isinstance(curve, Part.Circle) else None)
        return values

    def vertical_at(self, name, element, x, y):
        obj = self.doc.getObject(name)
        shape = obj.Base[0].Shape if obj.TypeId in reference_tools.DRESS_UP else obj.Shape
        box = shape.getElement(element).BoundBox
        return (abs(box.XMin - x) < 1e-6 and abs(box.XMax - x) < 1e-6 and abs(box.YMin - y) < 1e-6
                and abs(box.YMax - y) < 1e-6 and box.ZLength > 5)

    def snapshot(self):
        return (intent_signature(self.doc), self.doc.UndoCount, self.core.inspect(self.doc)["revision"],
                sorted(obj.Name for obj in self.doc.Objects))

    def circle_edge(self, obj, radius, center):
        for index, edge in enumerate(obj.Shape.Edges):
            curve = edge.Curve
            if (isinstance(curve, Part.Circle) and abs(curve.Radius - radius) < 1e-6
                    and (curve.Center - App.Vector(*center)).Length < 1e-6):
                return "Edge%d" % (index + 1)
        raise AssertionError("no circle r=%s at %s on %s" % (radius, center, obj.Name))

    def geometry(self, name="Round"):
        """(radius, center) of each Base edge, or ("line", bounds) for other edges."""
        base, names = self.base_edges(name)
        rows = []
        for element in names:
            edge = base.Shape.getElement(element)
            if isinstance(edge.Curve, Part.Circle):
                rows.append((round(edge.Curve.Radius, 6), tuple(round(value, 6) for value in edge.Curve.Center)))
            else:
                box = edge.BoundBox
                rows.append(("line", tuple(round(value, 6) for value in (box.XMin, box.YMin, box.ZMin,
                                                                        box.XMax, box.YMax, box.ZMax))))
        return rows

    def distinct_references(self, name="Round"):
        """What the edit panel resends: each describe_dress_up reference once, in row order."""
        references = []
        for row in reference_tools.describe_dress_up(self.doc, name)["edges"]:
            if row["reference"] not in references:
                references.append(row["reference"])
        return references

    def test_fillet_rounds_every_match_like_listing_each_edge(self):
        self.bosses()
        names, undo, unrounded = set(App.listDocuments()), self.doc.UndoCount, self.doc.Body.Shape.Volume
        matches = sorted(row["subelement"] for row in self.call("resolve_selector", selector=circles(3))["matches"])
        self.assertEqual(len(matches), 2)
        preview = self.call("preview", proposal={"op": "fillet", "edges": [every(circles(3))], "radius": 0.5}, measure=True)
        self.assertTrue(preview["valid"], preview)
        self.assertEqual(set(App.listDocuments()), names)
        with patch.object(selectors, "_detail", side_effect=AssertionError("Consumers must not build detailed summaries")):
            self.call("fillet", id="Round", edges=[every(circles(3))], radius=0.5)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        base, elements = self.base_edges()
        self.assertEqual(base.Name, "BossPad")
        self.assertEqual(self.radii(), [3, 3])
        self.assertEqual(sorted(elements), matches)
        info = self.inputs()["edges_0"]
        self.assertEqual((info["mode"], info["many"], info["selector"], info["slots"]),
                         (selectors.GROUP_MODE, True, circles(3), [0, 1]))
        self.assertEqual(info["resolved"], [{"feature": "BossPad", "subelement": element} for element in elements])
        self.assertEqual(self.health()["edges_0"], {"input": "edges_0", "status": "healthy", "count": 2})
        self.assert_healthy()
        self.assertEqual(self.state["build_status"], "valid")
        volume = self.doc.Body.Shape.Volume
        self.assertAlmostEqual(preview["measurements"]["volume_mm3"], volume, places=6)
        self.assertNotAlmostEqual(volume, unrounded, places=3)
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Round"))
        self.call("fillet", id="Listed", edges=[{"feature": "BossPad", "subelement": element} for element in elements],
                  radius=0.5)
        self.assertNotIn("QueryInputs", self.doc.Listed.PropertiesList)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, volume, places=6)

    def test_parameter_edits_grow_and_shrink_the_native_base(self):
        self.bosses()
        self.call("fillet", id="Round", edges=[every(circles(3))], radius=0.5)
        two = self.base_edges()[1]
        self.call("add_circle", sketch="Bosses", x=35, y=5, diameter=6)
        four = self.base_edges()[1]
        self.assertEqual(self.radii(), [3, 3, 3, 3])
        self.assertEqual(self.health()["edges_0"]["count"], 4)
        self.assertEqual(self.inputs()["edges_0"]["slots"], [0, 1, 2, 3])
        log = json.loads(self.doc.Round.QueryResolutionLog)
        self.assertEqual(log[-1]["input"], "edges_0")
        self.assertEqual(len(log[-1]["resolved"]), 4)
        self.assert_healthy()
        self.call("rebuild")
        self.assertEqual(self.base_edges()[1], four)
        self.call("set_parameter", feature="Bosses", parameter="Diameter_3", value=4)
        self.assertEqual(self.radii(), [3, 3])
        self.assertEqual(self.inputs()["edges_0"]["slots"], [0, 1])
        self.assert_healthy()
        self.assertEqual(len(self.doc.Body.Shape.Solids), 1)
        shrunk = self.doc.Body.Shape.Volume
        self.call("undo")
        self.assertEqual(self.base_edges()[1], four)
        self.assert_healthy()
        self.call("undo")  # the rebuild step
        self.assertEqual(self.base_edges()[1], four)
        self.call("undo")
        self.assertEqual(self.base_edges()[1], two)
        self.assertEqual(self.inputs()["edges_0"]["slots"], [0, 1])
        self.assert_healthy()
        for _ in range(3):
            self.call("redo")
        self.assertEqual(self.radii(), [3, 3])
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, shrunk, places=6)
        self.assert_healthy()

    def test_mixed_literal_single_and_multi_entries_keep_order_without_duplicates(self):
        self.bosses()
        corner = next(f"Edge{i + 1}" for i in range(len(self.doc.BossPad.Shape.Edges))
                      if self.vertical_at("BossPad", f"Edge{i + 1}", 0, 0))
        far = next(f"Edge{i + 1}" for i in range(len(self.doc.BossPad.Shape.Edges))
                   if self.vertical_at("BossPad", f"Edge{i + 1}", 40, 0))
        circle = sorted(row["subelement"] for row in self.call("resolve_selector", selector=circles(3))["matches"])[0]
        edges = [{"feature": "BossPad", "subelement": corner}, closest((40, 20, 3)), every(circles(3)),
                 {"feature": "BossPad", "subelement": circle}, {"feature": "BossPad", "subelement": far}]
        self.call("fillet", id="Round", edges=edges, radius=0.5)
        names = self.base_edges()[1]
        self.assertEqual(len(names), 5)
        self.assertEqual(names[0], corner)
        self.assertTrue(self.vertical_at("Round", names[1], 40, 20))
        self.assertEqual(self.radii()[2:4], [3, 3])
        self.assertEqual(names[4], far)
        inputs = self.inputs()
        self.assertEqual(sorted(inputs), ["edges_0", "edges_1", "edges_2", "edges_3", "edges_4"])
        self.assertTrue(inputs["edges_0"]["literal"] and inputs["edges_3"]["literal"] and inputs["edges_4"]["literal"])
        self.assertEqual([inputs[name]["slots"] for name in sorted(inputs)], [[0], [1], [2, 3], [], [4]])
        self.assertFalse(inputs["edges_1"]["many"])
        self.assert_healthy()
        # The multi entry grows in the middle; the trailing literal follows it.
        self.call("add_circle", sketch="Bosses", x=35, y=5, diameter=6)
        names = self.base_edges()[1]
        self.assertEqual(len(names), 7)
        self.assertEqual(names[0], corner)
        self.assertTrue(self.vertical_at("Round", names[1], 40, 20))
        self.assertEqual(self.radii()[2:6], [3, 3, 3, 3])
        self.assertTrue(self.vertical_at("Round", names[6], 40, 0))
        self.assertEqual(self.inputs()["edges_4"]["slots"], [6])
        self.assertEqual(self.inputs()["edges_3"]["slots"], [])
        self.assert_healthy()
        # describe_dress_up round-trips: one reference per entry, as the panel keeps them,
        # including the literal whose edge the multi entry already includes.
        rows = reference_tools.describe_dress_up(self.doc, "Round")["edges"]
        self.assertEqual(len(rows), 8)
        self.assertEqual((rows[6]["subelement"], rows[6]["reference"]),
                         (None, {"feature": "BossPad", "subelement": self.inputs()["edges_3"]["selector"]["subelement"]}))
        references = self.distinct_references()
        self.assertEqual(len(references), 5)
        self.assertEqual(references[2], every(circles(3)))
        before = intent_signature(self.doc)
        self.call("edit_dress_up", feature="Round", edges=references)
        self.assertEqual(self.base_edges()[1], names)
        self.assertEqual(sorted(self.inputs()), ["edges_0", "edges_1", "edges_2", "edges_3", "edges_4"])
        self.assert_healthy()
        self.call("undo")
        self.assertEqual(intent_signature(self.doc), before)

    def test_overlapping_multi_entries_keep_each_edge_once(self):
        self.bosses()
        self.call("fillet", id="Round", edges=[every(circles(3)), every(top_circles())], radius=0.5)
        self.assertEqual(sorted(self.radii()), [3, 3, 5])
        inputs = self.inputs()
        self.assertEqual((inputs["edges_0"]["slots"], inputs["edges_1"]["slots"]), ([0, 1], [2]))
        self.assertEqual(self.health()["edges_1"]["count"], 2)
        self.assert_healthy()
        # The label counts the query's matches, not the slots left after de-duplication.
        labels = [row["label"] for row in reference_tools.describe_dress_up(self.doc, "Round")["edges"]]
        self.assertTrue(labels[2].endswith("(one of 2 query matches)"), labels)
        self.assertTrue(labels[0].endswith("(one of 2 query matches)"), labels)

    def test_adjacency_intersection_names_every_rim_edge(self):
        self.bosses()
        faces = {"kind": "owned_by", "part": "Body"}
        rims = {"kind": "intersection", "queries": [
            {"kind": "adjacent", "entity_type": "edge",
             "query": {"kind": "geometry", "geometry": "cylinder", "radius": 5, "query": faces}},
            {"kind": "adjacent", "entity_type": "edge", "query": {"kind": "geometry", "geometry": "plane", "query": faces}}]}
        expected = sorted(row["subelement"] for row in self.call("resolve_selector", selector=circles(5))["matches"])
        self.call("fillet", id="Round", edges=[every(rims)], radius=0.5)
        self.assertEqual(sorted(self.base_edges()[1]), expected)
        self.assertEqual(self.radii(), [5, 5])
        self.assert_healthy()

    def test_chamfer_and_edit_dress_up_with_a_multi_entry(self):
        self.bosses()
        self.call("chamfer", id="Bevel", edges=[every(top_circles())], size=0.5)
        self.assertEqual(sorted(self.radii("Bevel")), [3, 5])
        info = reference_tools.describe_dress_up(self.doc, "Bevel")
        self.assertEqual([row["reference"] for row in info["edges"]], [every(top_circles())] * 2)
        self.assert_healthy("Bevel")
        self.call("undo")
        self.call("fillet", id="Round", edges=[closest((0, 0, 3))], radius=1)
        self.assertEqual(self.inputs()["edges_0"]["mode"], "linksub_index")
        before = self.snapshot()
        self.call("edit_dress_up", feature="Round", edges=[closest((0, 0, 3)), every(circles(3))], radius=0.5)
        self.assertEqual(self.doc.UndoCount, before[1] + 1)
        names = self.base_edges()[1]
        self.assertTrue(self.vertical_at("Round", names[0], 0, 0))
        self.assertEqual(self.radii()[1:], [3, 3])
        self.assertEqual({name: info["mode"] for name, info in self.inputs().items()},
                         {"edges_0": selectors.GROUP_MODE, "edges_1": selectors.GROUP_MODE})
        self.assert_healthy()
        grouped = intent_signature(self.doc)
        self.call("undo")
        self.assertEqual(intent_signature(self.doc), before[0])
        self.assertEqual(self.inputs()["edges_0"]["mode"], "linksub_index")
        self.call("redo")
        self.assertEqual(intent_signature(self.doc), grouped)
        self.call("add_circle", sketch="Bosses", x=35, y=5, diameter=6)
        self.assertEqual(self.radii()[1:], [3, 3, 3, 3])
        self.assert_healthy()
        # Editing back to single references leaves the per-slot binding only.
        self.call("edit_dress_up", feature="Round", edges=[closest((0, 0, 3))])
        self.assertEqual(len(self.base_edges()[1]), 1)
        self.assertEqual({name: info["mode"] for name, info in self.inputs().items()}, {"edges_0": "linksub_index"})
        self.assert_healthy()

    def test_save_reopen_and_rebuild_keep_the_group(self):
        self.bosses()
        corner = closest((0, 0, 3))
        self.call("fillet", id="Round", edges=[corner, every(circles(3))], radius=0.5)
        names, inputs = self.base_edges()[1], self.inputs()
        with tempfile.TemporaryDirectory(prefix="multi-edge-reopen-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "multi-edge.FCStd"
            self.call("save", path=str(path))
            App.closeDocument(self.doc.Name)
            self.call("open", path=str(path))
            self.assertEqual(self.base_edges()[1], names)
            self.assertEqual(self.inputs(), inputs)
            self.assert_healthy()
            self.assertEqual(self.state["build_status"], "valid")
            self.call("rebuild")
            self.assertEqual(self.base_edges()[1], names)
            self.assert_healthy()
            self.call("add_circle", sketch="Bosses", x=35, y=5, diameter=6)
            self.assertEqual(self.radii()[1:], [3, 3, 3, 3])
            self.assert_healthy()

    def test_failed_multi_fillet_rolls_back_and_studio_rollback_keeps_it(self):
        self.bosses()
        before = self.snapshot()
        response = self.request("fillet", id="Round", edges=[every(circles(3))], radius=50)
        self.assertFalse(response["ok"], response)
        self.assertIn(response["error"]["code"], {"build_failed", "invalid_geometry"})
        self.assertEqual(self.snapshot(), before)
        # A studio part: every vertical edge is one multi entry.
        self.call("new", name="Multi edge studio")
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="Pad", profile="Plate", length=6, operation="new")
        part = self.state["studio"]["parts"][0]["id"]
        vertical = {"kind": "parallel", "direction": [0, 0, 1], "query": owned(part)}
        self.call("fillet", id="Round", part=part, edges=[every(vertical)], radius=1)
        self.assertEqual(len(self.base_edges()[1]), 4)
        self.assert_healthy()
        volume = self.doc.Round.Shape.Volume
        order = self.state["studio"]["feature_order"]
        self.call("rollback", index=order.index("Round"))
        self.assertTrue(next(row for row in self.state["features"] if row["id"] == "Round")["rolled_back"])
        self.call("rollback", index=len(order))
        self.assertEqual(len(self.base_edges()[1]), 4)
        self.assertAlmostEqual(self.doc.Round.Shape.Volume, volume, places=6)
        self.assert_healthy()

    def test_multi_entry_matching_nothing_is_missing_and_blocks_export(self):
        self.bosses()
        self.call("fillet", id="Round", edges=[every(circles(3))], radius=0.5)
        names = self.base_edges()[1]
        revision = self.state["revision"]
        rejected = self.request("set_parameter", feature="Bosses", parameter="Diameter", value=4)
        self.assertFalse(rejected["ok"], rejected)
        self.assertEqual(rejected["error"]["code"], "build_failed")
        self.assertIn("edges_0", json.dumps(rejected["error"]))
        self.assertEqual(self.call("inspect")["revision"], revision)
        self.assertEqual(self.base_edges()[1], names)
        self.assert_healthy()
        # A native edit outside a managed transaction leaves no r=3 circle.
        self.doc.openTransaction("Native boss edit")
        self.doc.Bosses.setDatum("Diameter", App.Units.Quantity("4 mm"))
        with patch.object(selectors, "recompute", side_effect=AssertionError("Observer must not start a nested rebuild")):
            self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertEqual(self.state["build_status"], "failed")
        self.assertEqual(self.health()["edges_0"]["status"], "missing")
        self.assertEqual(self.base_edges()[1], names)
        with tempfile.TemporaryDirectory(prefix="multi-edge-missing-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "missing-multi.step"
            response = self.request("export", path=str(path))
            self.assertFalse(response["ok"], response)
            self.assertEqual(response["error"]["code"], "build_failed")
            self.assertFalse(path.exists())
        response = self.request("rebuild")
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "build_failed")
        self.assertEqual(self.base_edges()[1], names)
        self.call("set_parameter", feature="Bosses", parameter="Diameter", value=6)
        self.assertEqual(self.radii(), [3, 3])
        self.assert_healthy()

    def test_native_edit_that_adds_matches_waits_for_managed_rebuild(self):
        self.bosses()
        self.call("fillet", id="Round", edges=[closest((0, 0, 3)), every(circles(3))], radius=0.5)
        names = self.base_edges()[1]
        self.doc.openTransaction("Native boss edit")
        self.doc.Bosses.setDatum("Diameter_2", App.Units.Quantity("6 mm"))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertEqual(self.state["build_status"], "failed")
        health = self.health()
        self.assertEqual((health["edges_1"]["status"], health["edges_1"]["code"]), ("missing", "pending_selector_resolution"))
        self.assertEqual(self.base_edges()[1], names)
        self.call("rebuild")
        self.assertTrue(self.vertical_at("Round", self.base_edges()[1][0], 0, 0))
        self.assertEqual(self.radii()[1:], [3, 3, 3, 3])
        self.assertEqual(self.inputs()["edges_1"]["slots"], [1, 2, 3, 4])
        self.assert_healthy()
        self.assertEqual(self.state["build_status"], "valid")

    def test_rejections_change_nothing(self):
        self.bosses()
        self.call("fillet", id="Existing", edges=[closest((0, 0, 3))], radius=1)
        cases = [
            ([{"feature": "BossPad", "subelement": "Edge1", "all": True}], "invalid_argument"),
            ([dict(circles(3), all=True)], "invalid_argument"),
            ([{"selector": circles(3), "all": "yes"}], "invalid_argument"),
            ([{"selector": circles(3), "all": 1}], "invalid_argument"),
            ([{"selector": circles(3), "all": None}], "invalid_argument"),
            ([{"selector": {"feature": "BossPad", "subelement": "Edge1"}, "all": True}], "invalid_argument"),
            ([{"selector": "Edge1", "all": True}], "invalid_argument"),
            ([{"selector": circles(3), "all": True, "every": True}], "unknown_argument"),
            ([every(circles(7))], "missing_reference"),
            ([every({"kind": "owned_by", "part": "Body"})], "missing_reference"),
            ([every(circles(3)), {"selector": circles(5)}], "ambiguous_reference"),
            ([every(circles(3)), {"feature": "Missing", "subelement": "Edge1"}], "missing_reference"),
            # Single wrappers in a multi list are as strict as the multi wrapper itself.
            ([every(circles(3)), {"selector": closest((0, 0, 3)), "foo": 1}], "unknown_argument"),
            ([every(circles(3)), {"selector": top_circles(), "All": True}], "unknown_argument"),
            ([{"selector": top_circles(), "All": True}, every(circles(3))], "unknown_argument"),
            ([every(circles(3)), {"kind": "owned_by", "selector": closest((0, 0, 3))}], "unknown_argument"),
            ([every(circles(3)), {"feature": "BossPad", "subelement": "Edge1", "foo": 1}], "invalid_selector"),
            # Without a multi entry the per-slot path is unchanged.
            ([{"selector": closest((0, 0, 3)), "foo": 1}], "invalid_selector"),
        ]
        before = self.snapshot()
        for edges, code in cases:
            for op, args in (("fillet", {"radius": 0.5}), ("chamfer", {"size": 0.5}),
                             ("edit_dress_up", {"feature": "Existing"})):
                with self.subTest(op=op, edges=edges):
                    response = self.request(op, edges=edges, **args)
                    self.assertFalse(response["ok"], response)
                    self.assertEqual(response["error"]["code"], code, response)
                    self.assertTrue(response["error"]["message"])
                    self.assertEqual(self.snapshot(), before)
        # all:false is the plain single selector.
        self.call("fillet", id="Single", edges=[{"selector": closest((40, 20, 3)), "all": False}], radius=1)
        info = self.inputs("Single")["edges_0"]
        self.assertEqual((info["mode"], info["selector"]), ("linksub_index", closest((40, 20, 3))))
        typo = self.request("fillet", edges=[every(circles(3)), {"selector": top_circles(), "All": True}], radius=0.5)
        self.assertEqual((typo["error"]["code"], typo["error"].get("fields")), ("unknown_argument", ["All"]), typo)

    def test_deduplicated_literal_keeps_its_edge_through_renumbering(self):
        """A literal the multi entry already includes owns no slot but stays tracked.

        Adding a boss renumbers the small boss's top rim; resizing that boss then
        drops it from the r=3 query, and the literal must re-enter Base as that rim,
        not as whatever edge now has its old index.
        """
        self.bosses()
        rim = self.circle_edge(self.doc.BossPad, 3, (10, 10, 10))
        self.call("fillet", id="Round", edges=[every(circles(3)), {"feature": "BossPad", "subelement": rim}], radius=0.5)
        literal = self.inputs()["edges_1"]
        self.assertEqual(literal["slots"], [])
        self.assertEqual(self.base_edges()[1][literal["element_slot"]], rim)
        self.assertTrue(literal["mapped"])
        self.call("add_circle", sketch="Bosses", x=35, y=5, diameter=6)
        renumbered = self.circle_edge(self.doc.BossPad, 3, (10, 10, 10))
        self.assertNotEqual(renumbered, rim)
        literal = self.inputs()["edges_1"]
        self.assertEqual((literal["selector"]["subelement"], literal["slots"]), (renumbered, []))
        self.assertEqual(self.base_edges()[1][literal["element_slot"]], renumbered)
        self.assert_healthy()
        self.call("set_parameter", feature="Bosses", parameter="Diameter", value=8)
        self.assertEqual(self.geometry(), [(3, (35, 5, 6)), (3, (35, 5, 10)), (4, (10, 10, 10))])
        self.assertEqual(self.inputs()["edges_1"]["slots"], [2])
        self.assert_healthy()
        self.assertEqual(self.state["build_status"], "valid")
        self.call("undo")
        self.assertEqual(sorted(self.radii()), [3, 3, 3, 3])
        self.assertEqual(self.inputs()["edges_1"]["slots"], [])
        self.assert_healthy()
        # Once the native list no longer has the recorded layout, the mapped name decides.
        self.doc.openTransaction("Native list and boss edit")
        corner = next(f"Edge{i + 1}" for i in range(len(self.doc.BossPad.Shape.Edges))
                      if self.vertical_at("BossPad", f"Edge{i + 1}", 0, 0))
        self.doc.Round.Base = (self.doc.BossPad, self.base_edges()[1] + [corner])
        self.doc.Bosses.setDatum("Diameter", App.Units.Quantity("8 mm"))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertEqual(self.state["build_status"], "failed")
        self.call("rebuild")
        self.assertEqual(self.geometry(), [(3, (35, 5, 6)), (3, (35, 5, 10)), (4, (10, 10, 10))])
        self.assert_healthy()
        # A mapped name that no longer resolves is missing, never an old index.
        info = dict(self.inputs()["edges_1"], mapped="g999;SKT;:H1,E", slots=[])
        info.pop("element_slot", None)
        self.assertIsNone(selectors.literal_element(self.doc.BossPad, info, self.base_edges()[1], False))

    def test_deduplicated_single_selector_survives_the_edit_round_trip(self):
        self.bosses()
        self.call("add_circle", sketch="Bosses", x=35, y=5, diameter=6)
        single = closest((13, 10, 10), geometry="circle")
        self.call("fillet", id="Round", edges=[every(circles(3)), single], radius=0.5)
        self.assertEqual((self.inputs()["edges_1"]["slots"], len(self.base_edges()[1])), ([], 4))
        rows = reference_tools.describe_dress_up(self.doc, "Round")["edges"]
        self.assertEqual([row["subelement"] is None for row in rows], [False] * 4 + [True])
        self.assertEqual(rows[4]["reference"], {"selector": single})
        references = self.distinct_references()
        self.assertEqual(references, [every(circles(3)), {"selector": single}])
        # The panel always resends edges, also for a radius-only edit.
        self.call("edit_dress_up", feature="Round", edges=references, radius=0.45)
        self.assertEqual(sorted(self.inputs()), ["edges_0", "edges_1"])
        self.assertEqual(self.inputs()["edges_1"]["slots"], [])
        self.call("set_parameter", feature="Bosses", parameter="Diameter", value=8)
        self.assertEqual(self.geometry(), [(3, (35, 5, 6)), (3, (35, 5, 10)), (4, (10, 10, 10))])
        self.assertEqual(self.inputs()["edges_1"]["slots"], [2])
        self.assert_healthy()
        # A literal the query already includes round-trips the same way.
        self.call("undo")
        self.call("undo")
        rim = self.circle_edge(self.doc.BossPad, 3, (10, 10, 10))
        self.call("edit_dress_up", feature="Round", edges=[every(circles(3)), {"feature": "BossPad", "subelement": rim}])
        self.assertEqual(self.distinct_references(), [every(circles(3)), {"feature": "BossPad", "subelement": rim}])
        self.call("edit_dress_up", feature="Round", edges=self.distinct_references(), radius=0.4)
        self.assertTrue(self.inputs()["edges_1"]["literal"])
        self.assert_healthy()
        # A literal whose edge is gone is left out with a note, never resent as a stale index.
        with patch.object(selectors, "literal_element", return_value=None):
            info = reference_tools.describe_dress_up(self.doc, "Round")
        self.assertEqual([row["reference"] for row in info["edges"]], [every(circles(3))] * 4)
        self.assertTrue(any("no longer exists" in note for note in info["limitations"]), info["limitations"])

    def test_blocked_group_reports_only_the_unhealthy_member(self):
        self.bosses()
        small_top = {"kind": "geometry", "geometry": "circle", "radius": 3,
                     "query": {"kind": "created_by", "feature": "BossPad", "entity_type": "edge", "cap": "end"}}
        self.call("fillet", id="Round", edges=[every(circles(5)), {"selector": small_top}], radius=0.5)
        names, before, geometry = self.base_edges()[1], self.snapshot(), self.geometry()
        rejected = self.request("add_circle", sketch="Bosses", x=35, y=5, diameter=6)
        self.assertFalse(rejected["ok"], rejected)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.base_edges()[1], names)
        # The same state from a native edit: a second r=3 top rim makes edges_1 ambiguous.
        self.doc.openTransaction("Native boss edit")
        self.doc.Bosses.addGeometry(Part.Circle(App.Vector(35, 5, 0), App.Vector(0, 0, 1), 3), False)
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertEqual(self.state["build_status"], "failed")
        self.assertEqual(self.health()["edges_1"]["status"], "ambiguous")
        self.assertEqual(self.health()["edges_0"]["status"], "healthy")
        self.assertEqual(self.geometry(), geometry)
        errors = [error for error in self.state["build_errors"] if error.get("feature") == "Round"]
        self.assertEqual({error.get("input") for error in errors}, {"edges_1"}, errors)
        rebuilt = self.request("rebuild")
        self.assertFalse(rebuilt["ok"], rebuilt)
        self.assertEqual({error["input"] for error in selectors.reference_errors(self.doc) if error["feature"] == "Round"},
                         {"edges_1"})
        self.assertNotIn("run a managed rebuild", json.dumps(rebuilt["error"]))
        self.assertEqual(self.geometry(), geometry)


if __name__ == "__main__":
    unittest.main()
