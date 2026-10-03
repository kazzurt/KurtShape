"""Consequential selector/reference behavior in the pinned native runtime."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
import Sketcher
from kurtshape import selectors as query
from kurtshape.core import OperationError


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SelectorAcceptance")
        self.doc.UseHasher = False
        self.doc.UndoMode = 1

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)

    def pad(self, name="Pad", x=0, width=10):
        body = self.doc.addObject("PartDesign::Body", name + "Body")
        sketch = body.newObject("Sketcher::SketchObject", name + "Profile")
        points = [App.Vector(x, 0, 0), App.Vector(x + width, 0, 0),
                  App.Vector(x + width, 20, 0), App.Vector(x, 20, 0)]
        for i, point in enumerate(points):
            sketch.addGeometry(Part.LineSegment(point, points[(i + 1) % 4]), False)
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile, pad.Length = sketch, 5
        self.doc.recompute()
        return body, sketch, pad

    def created(self, feature, cap=None, entity_type="face"):
        selector = {"kind": "created_by", "feature": feature.Name, "entity_type": entity_type}
        if cap:
            selector["cap"] = cap
        return selector

    def test_created_by_excludes_modified_and_preserves_original_creator(self):
        body, profile, pad = self.pad()
        hole = body.newObject("Sketcher::SketchObject", "HoleProfile")
        hole.addGeometry(Part.Circle(App.Vector(5, 10, 0), App.Vector(0, 0, 1), 2), False)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile, pocket.Type, pocket.Reversed = hole, 1, True
        self.doc.recompute()
        original = query.resolve(self.doc, self.created(pad))
        current = query.resolve(self.doc, self.created(pocket))
        self.assertEqual(len(original), 6)
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["summary"]["geometry"], "cylinder")
        self.assertEqual(len(query.resolve(self.doc, self.created(pad, "end"))), 1)
        self.assertEqual(len(query.resolve(self.doc, self.created(pad, "side"))), 4)

    def test_owned_geometry_sets_parallel_closest_and_ties(self):
        body, profile, pad = self.pad()
        all_faces = {"kind": "owned_by", "part": body.Name}
        planes = {"kind": "geometry", "geometry": "plane", "query": all_faces}
        caps = {"kind": "parallel", "direction": [0, 0, 1], "query": planes}
        top = {"kind": "closest", "point": [5, 10, 8], "query": caps}
        self.assertEqual(len(query.resolve(self.doc, planes)), 6)
        self.assertEqual(len(query.resolve(self.doc, caps)), 2)
        self.assertEqual(len(query.resolve(self.doc, top)), 1)
        difference = {"kind": "subtraction", "query": planes, "subtract": caps}
        self.assertEqual(len(query.resolve(self.doc, difference)), 4)
        union = {"kind": "union", "queries": [top, top]}
        self.assertEqual(len(query.resolve(self.doc, union)), 1)
        intersection = {"kind": "intersection", "queries": [planes, caps]}
        self.assertEqual(len(query.resolve(self.doc, intersection)), 2)
        tied = {"kind": "closest", "point": [5, 10, 2.5], "query": caps}
        with self.assertRaisesRegex(OperationError, "several"):
            query.native_reference(self.doc, tied)

    def test_split_faces_are_created_by_original_and_split(self):
        box = self.doc.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 10, 20, 5
        divider = self.doc.addObject("Part::Box", "Divider")
        divider.Length, divider.Width, divider.Height = 2, 30, 10
        divider.Placement.Base = App.Vector(4, -5, -2)
        cut = self.doc.addObject("Part::Cut", "Split")
        cut.Base, cut.Tool = box, divider
        self.doc.recompute()
        prior = query.resolve(self.doc, self.created(box))
        split = query.resolve(self.doc, self.created(cut))
        self.assertEqual(len(prior), 10)
        self.assertEqual(len(split), 8)

    def test_native_boolean_merged_caps_keep_every_creator(self):
        first, a_profile, a = self.pad("First")
        second, b_profile, b = self.pad("Second", x=10)
        result = first.newObject("PartDesign::Boolean", "Merge")
        result.Group = [second]
        result.Type, result.Refine = 0, True
        self.doc.recompute()
        self.assertEqual(len(result.Shape.Faces), 6)
        top = {"kind": "parallel", "direction": [0, 0, 1], "allow_antiparallel": False,
               "query": {"kind": "owned_by", "part": first.Name}}
        merge_top = query.resolve(self.doc, top)
        self.assertEqual(len(merge_top), 1)
        for maker in (a, b, result):
            selected = query.resolve(self.doc, {"kind": "intersection", "queries": [top, self.created(maker)]})
            self.assertEqual(len(selected), 1, maker.Name)

    def test_support_rebinds_before_consumer_and_records_missing(self):
        body, profile, pad = self.pad()
        support = body.newObject("Sketcher::SketchObject", "SupportedSketch")
        support.MapMode = "FlatFace"
        self.doc.openTransaction("Bind support")
        query.bind(support, "support", self.created(pad, "end"))
        query.recompute(self.doc)
        self.doc.commitTransaction()
        self.assertAlmostEqual(support.Placement.Base.z, 5)
        self.assertFalse(query.reference_errors(self.doc))
        self.doc.openTransaction("Resize upstream")
        pad.Length = 8
        query.recompute(self.doc)
        self.doc.commitTransaction()
        self.assertAlmostEqual(support.Placement.Base.z, 8)
        self.assertEqual(json.loads(support.QueryHealth)[0]["status"], "healthy")
        self.doc.undo(); self.doc.recompute()
        self.assertAlmostEqual(support.Placement.Base.z, 5)
        self.doc.redo(); self.doc.recompute()
        self.assertAlmostEqual(support.Placement.Base.z, 8)
        self.doc.openTransaction("Missing upstream")
        inputs = json.loads(support.QueryInputs)
        inputs["support"]["selector"]["feature"] = "DeletedFeature"
        support.QueryInputs = json.dumps(inputs)
        query.recompute(self.doc)
        self.doc.commitTransaction()
        self.assertEqual(query.reference_errors(self.doc)[0]["reference_health"], "missing")
        self.assertEqual(support.AttachmentSupport[0][0], pad)

    def test_bind_ambiguous_rejects_and_save_reopen_preserves_intent(self):
        body, profile, pad = self.pad()
        support = body.newObject("Sketcher::SketchObject", "SupportedSketch")
        support.MapMode = "FlatFace"
        self.doc.openTransaction("Ambiguous")
        with self.assertRaises(OperationError):
            query.bind(support, "support", self.created(pad))
        self.doc.abortTransaction()
        self.doc.openTransaction("Bind")
        query.bind(support, "support", self.created(pad, "end"))
        query.recompute(self.doc)
        self.doc.commitTransaction()
        expected = support.QueryInputs
        directory = ROOT / "validation" / "u2-selectors"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="selector-relocation-", dir=directory) as temporary:
            path = Path(temporary) / "selector-part.FCStd"
            self.doc.saveAs(str(path))
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(str(path))
            self.assertEqual(self.doc.SupportedSketch.QueryInputs, expected)
            self.assertFalse(query.reference_errors(self.doc))

    def test_unknown_history_fails_closed(self):
        with self.assertRaises(OperationError):
            query._decode("#31;:M;CUT;:H1:7,F")
        with self.assertRaises(OperationError):
            query._decode("Face1;:UNKNOWN;:H1:9,F")
        with self.assertRaises(OperationError):
            query._decode("Face1;:T1:5:F")
        for selector in ({"kind": "nth", "index": 0}, {"kind": "created_by", "feature": "Pad", "index": 0},
                         {"feature": "Pad", "subelement": "Face1", "selector": {}},
                         {"kind": "all", "unknown": True}):
            with self.subTest(selector=selector), self.assertRaises(OperationError):
                query.resolve(self.doc, selector)

    def test_shared_profile_makers_have_distinct_creation_identity(self):
        body, profile, pad = self.pad()
        extrusion = self.doc.addObject("Part::Extrusion", "IndependentExtrusion")
        extrusion.Base, extrusion.Dir, extrusion.Solid, extrusion.LengthFwd = profile, (0, 0, 1), True, 7
        self.doc.recompute()
        rows = query.resolve(self.doc, self.created(extrusion, "end"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["feature"], extrusion.Name)
        self.assertAlmostEqual(rows[0]["summary"]["center_mm"][2], 7)
        body.Placement.Base = App.Vector(100, 0, 0)
        extrusion.Placement = App.Placement(App.Vector(40, 0, 0), App.Rotation(App.Vector(1, 0, 0), 90))
        self.doc.recompute()
        rows = query.resolve(self.doc, self.created(extrusion, "end"))
        self.assertEqual(len(rows), 1)
        expected = extrusion.getGlobalPlacement().multVec(App.Vector(5, 10, 7))
        self.assertLess((App.Vector(*rows[0]["summary"]["center_mm"]) - expected).Length, 1e-7)

    def test_adjacency_and_tangent_chain(self):
        body, profile, pad = self.pad()
        top = query.native_reference(self.doc, self.created(pad, "end"))
        adjacent = query.resolve(self.doc, {"kind": "adjacent", "query": top,
                                           "entity_type": "face", "adjacency": "edge"})
        self.assertEqual(len(adjacent), 4)
        tangent = query.resolve(self.doc, {"kind": "tangent", "query": {"feature": pad.Name, "subelement": "Edge1"}})
        self.assertEqual(len(tangent), 1)

    def test_external_rebind_retains_native_constraint_and_mode(self):
        body, profile, pad = self.pad()
        sketch = body.newObject("Sketcher::SketchObject", "UseSketch")
        sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(2, 2, 0)), False)
        sketch.addExternal(pad.Name, "Edge3", False, False)
        sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -3, 1))
        self.doc.recompute()
        self.doc.openTransaction("Bind external")
        query.bind(sketch, "use", {"feature": pad.Name, "subelement": "Edge3"},
                   native_property="ExternalGeometry", mode="external", index=0)
        self.doc.commitTransaction()
        constraints = [constraint.Content for constraint in sketch.Constraints]
        types = list(sketch.ExternalTypes)
        self.doc.openTransaction("Rebind external")
        inputs = json.loads(sketch.QueryInputs)
        inputs["use"]["selector"] = {"feature": pad.Name, "subelement": "Edge6"}
        sketch.QueryInputs = json.dumps(inputs)
        query.recompute(self.doc)
        self.doc.commitTransaction()
        self.assertEqual(sketch.ExternalGeometry[0], (pad, ("Edge6",)))
        self.assertEqual([constraint.Content for constraint in sketch.Constraints], constraints)
        self.assertEqual(list(sketch.ExternalTypes), types)
        self.assertFalse(query.reference_errors(self.doc))

    def test_revolve_loft_sweep_caps(self):
        body, profile, pad = self.pad()
        upper = self.doc.copyObject(profile, False)
        upper.Placement.Base = App.Vector(0, 0, 8)
        loft = self.doc.addObject("Part::Loft", "Loft")
        loft.Sections, loft.Solid = [profile, upper], True
        path = self.doc.addObject("Part::Feature", "Path")
        path.Shape = Part.makeLine(App.Vector(0, 0, 0), App.Vector(0, 0, 9))
        sweep = self.doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections, sweep.Spine, sweep.Solid = [profile], (path, []), True
        revolve = self.doc.addObject("Part::Revolution", "Revolve")
        revolve.Source, revolve.Base, revolve.Axis = profile, App.Vector(), App.Vector(0, 1, 0)
        revolve.Angle, revolve.Solid = 180, True
        self.doc.recompute()
        for feature in (loft, sweep, revolve):
            with self.subTest(feature=feature.Name):
                self.assertEqual(len(query.resolve(self.doc, self.created(feature, "start"))), 1)
                self.assertEqual(len(query.resolve(self.doc, self.created(feature, "end"))), 1)
        self.assertEqual(len(query.resolve(self.doc, self.created(revolve, "side"))), 3)
        self.assertEqual(len(query.resolve(self.doc, self.created(pad, entity_type="edge"))), 12)
        for feature in (loft, sweep, revolve):
            feature.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation(App.Vector(0, 1, 0), 90))
        self.doc.recompute()
        for feature in (loft, sweep, revolve):
            with self.subTest(transformed_feature=feature.Name):
                self.assertEqual(len(query.resolve(self.doc, self.created(feature, "start"))), 1)
                self.assertEqual(len(query.resolve(self.doc, self.created(feature, "end"))), 1)

    def test_unrelated_unsupported_shape_does_not_poison_creator_query(self):
        body, profile, pad = self.pad()
        imported = self.doc.addObject("Part::Feature", "UnsupportedImported")
        imported.Shape = Part.makeBox(2, 2, 2)
        self.doc.recompute()
        self.assertEqual(len(query.resolve(self.doc, self.created(pad))), 6)

    def test_selector_coordinates_include_native_parent_placements(self):
        body, profile, pad = self.pad()
        body.Placement.Base = App.Vector(10, 0, 0)
        container = self.doc.addObject("App::Part", "Container")
        container.addObject(body)
        container.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation(App.Vector(0, 1, 0), 90))
        self.doc.recompute()
        end = query.resolve(self.doc, self.created(pad, "end"))
        self.assertEqual(len(end), 1)
        expected = profile.getGlobalPlacement().multVec(App.Vector(5, 10, 5))
        self.assertLess((App.Vector(*end[0]["summary"]["center_mm"]) - expected).Length, 1e-7)
        normal = profile.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
        selected = query.resolve(self.doc, {"kind": "closest", "point": list(expected + normal * 2),
                                           "query": {"kind": "parallel", "direction": list(normal),
                                                     "query": {"kind": "owned_by", "part": body.Name}}})
        self.assertEqual([row["subelement"] for row in selected], [row["subelement"] for row in end])


if __name__ == "__main__":
    unittest.main()
