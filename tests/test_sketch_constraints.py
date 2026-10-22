"""Native line coincidence: solver intent, conflict restoration and Undo."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
import Sketcher
from kurtshape import sketch_constraints
from kurtshape.core import OperationError
from kurtshape.feature_tools import BY_KEY


class SketchConstraintTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("LineCoincidence")
        self.doc.UndoMode = 1
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(10, 0, 0)), False)
        self.sketch.addGeometry(Part.LineSegment(App.Vector(2, 3, 0), App.Vector(8, 6, 0)), False)
        self.doc.recompute()
        self.addCleanup(App.closeDocument, self.doc.Name)

    def selection(self, *names):
        return [SimpleNamespace(Object=self.sketch, SubElementNames=names)]

    def geometry(self):
        return [tuple((p.x, p.y, p.z) for p in (g.StartPoint, g.EndPoint)) for g in self.sketch.Geometry]

    def assert_collinear(self):
        first, second = self.sketch.Geometry
        direction = first.EndPoint - first.StartPoint
        self.assertGreater(direction.Length, 1e-7)
        for point in (second.StartPoint, second.EndPoint):
            self.assertLess(direction.cross(point - first.StartPoint).Length / direction.Length, 1e-7)
        self.assertEqual(self.sketch.solve(), 0)
        for name in ("ConflictingConstraints", "RedundantConstraints", "PartiallyRedundantConstraints", "MalformedConstraints"):
            self.assertEqual(list(getattr(self.sketch, name)), [], name)

    def test_whole_lines_are_collinear_with_free_endpoints_in_either_selection_order(self):
        for names in (("Edge1", "Edge2"), ("Edge2", "Edge1")):
            with self.subTest(order=names):
                self.sketch.deleteAllConstraints()
                self.assertTrue(sketch_constraints.coincident_lines(self.sketch, "Sketcher_ConstrainCoincidentUnified", self.selection(*names)))
                self.assert_collinear()
                self.assertEqual(self.sketch.DoF, 6)
                self.assertEqual(self.sketch.Constraints[0].Type, "Tangent")
                self.assertGreater(self.sketch.getPoint(0, 2).distanceToPoint(self.sketch.getPoint(1, 1)), 1)

    def test_shared_endpoint_adds_only_parallel_equation(self):
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        sketch_constraints.constrain_collinear(self.sketch, 0, 1)
        self.assert_collinear()
        self.assertEqual([c.Type for c in self.sketch.Constraints], ["Coincident", "Parallel"])
        self.assertEqual(self.sketch.DoF, 5)

    def test_parallel_lines_add_only_point_on_object_and_keep_construction(self):
        self.sketch.toggleConstruction(1)
        self.sketch.addConstraint(Sketcher.Constraint("Parallel", 0, 1))
        sketch_constraints.constrain_collinear(self.sketch, 0, 1)
        self.assert_collinear()
        self.assertEqual(self.sketch.Constraints[-1].Type, "PointOnObject")
        self.assertTrue(self.sketch.getConstruction(1))
        self.assertEqual(self.sketch.DoF, 6)

    def test_two_horizontal_lines_add_only_position_equation(self):
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 1))
        sketch_constraints.constrain_collinear(self.sketch, 0, 1)
        self.assert_collinear()
        self.assertEqual(self.sketch.DoF, 5)
        self.assertEqual(self.sketch.Constraints[-1].Type, "PointOnObject")

    def test_horizontal_point_alignments_do_not_stand_in_for_line_parallelism(self):
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0, 1, 1, 1))
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 1, 2, 0, 2))
        self.sketch.solve()
        sketch_constraints.constrain_collinear(self.sketch, 0, 1)
        self.assert_collinear()
        self.assertEqual(self.sketch.Constraints[-1].Type, "Tangent")

    def test_fixed_conflict_restores_geometry_and_constraints(self):
        self.sketch.addConstraint(Sketcher.Constraint("Block", 0))
        self.sketch.addConstraint(Sketcher.Constraint("Block", 1))
        before = self.geometry(), [(c.Type, c.First, c.Second) for c in self.sketch.Constraints]
        with self.assertRaises(OperationError) as error:
            sketch_constraints.constrain_collinear(self.sketch, 0, 1)
        self.assertEqual(error.exception.code, "constraint_conflict")
        self.assertEqual((self.geometry(), [(c.Type, c.First, c.Second) for c in self.sketch.Constraints]), before)
        self.assertEqual(self.sketch.solve(), 0)

    def test_duplicate_constraint_rejects_without_changing_accepted_intent(self):
        sketch_constraints.constrain_collinear(self.sketch, 0, 1)
        before = self.geometry(), self.sketch.ConstraintCount
        with self.assertRaises(OperationError):
            sketch_constraints.constrain_collinear(self.sketch, 0, 1)
        self.assertEqual((self.geometry(), self.sketch.ConstraintCount), before)
        self.assert_collinear()

    def test_native_transaction_undo_redo_and_save_reopen(self):
        import tempfile
        import os
        before = self.geometry()
        self.doc.openTransaction("Coincident lines")
        sketch_constraints.constrain_collinear(self.sketch, 0, 1)
        self.doc.commitTransaction()
        accepted = self.geometry()
        self.doc.undo()
        self.assertEqual(self.sketch.ConstraintCount, 0)
        self.assertEqual(self.geometry(), before)
        self.doc.redo()
        self.assertEqual(self.geometry(), accepted)
        self.assert_collinear()
        with tempfile.TemporaryDirectory(dir=os.environ["KURTSHAPE_SESSION_DIR"]) as folder:
            path = str(Path(folder) / "coincident-lines.FCStd")
            self.doc.saveCopy(path)
            other = App.openDocument(path)
            try:
                self.assertEqual(other.Sketch.Constraints[0].Type, "Tangent")
                self.assertEqual(other.Sketch.solve(), 0)
                self.assertEqual(other.Sketch.DoF, 6)
            finally:
                App.closeDocument(other.Name)

    def test_points_mixed_curves_and_other_commands_defer_to_native_tool(self):
        for command, names in (("Sketcher_ConstrainCoincidentUnified", ("Vertex1", "Vertex4")),
                               ("Sketcher_ConstrainCoincident", ("Edge1", "Vertex4")),
                               ("Sketcher_ConstrainParallel", ("Edge1", "Edge2"))):
            self.assertFalse(sketch_constraints.coincident_lines(self.sketch, command, self.selection(*names)))
        self.assertEqual(self.sketch.ConstraintCount, 0)

    def external_line(self):
        source = self.doc.addObject("Part::Feature", "ReferenceLine")
        source.Shape = Part.makeLine(App.Vector(0, 12, 0), App.Vector(20, 12, 0))
        self.sketch.addExternal(source.Name, "Edge1")
        self.doc.recompute()
        return source

    def test_projected_line_constrains_internal_line_in_either_selection_order(self):
        source = self.external_line()
        original_shape = source.Shape.exportBrepToString()
        references = self.sketch.ExternalGeometry
        for names in (("Edge1", "ExternalEdge1"), ("ExternalEdge1", "Edge1")):
            with self.subTest(order=names):
                self.sketch.deleteAllConstraints()
                self.assertTrue(sketch_constraints.coincident_lines(self.sketch, "Sketcher_ConstrainCoincidentUnified", self.selection(*names)))
                self.assertEqual(self.sketch.solve(), 0)
                self.assertEqual(self.sketch.DoF, 6)  # Other internal line is still free.
                for point in (self.sketch.Geometry[0].StartPoint, self.sketch.Geometry[0].EndPoint):
                    self.assertAlmostEqual(point.y, 12, places=7)
                self.assertEqual(self.sketch.ExternalGeometry, references)
                self.assertEqual(source.Shape.exportBrepToString(), original_shape)
                self.assertEqual(self.sketch.Constraints[0].Second, -3)

    def test_projected_line_conflict_preserves_fixed_geometry_and_source_reference(self):
        source = self.external_line()
        self.sketch.addConstraint(Sketcher.Constraint("Block", 0))
        self.sketch.solve()
        before = self.geometry(), self.sketch.ExternalGeometry, source.Shape.exportBrepToString()
        with self.assertRaises(OperationError):
            sketch_constraints.coincident_lines(self.sketch, "Sketcher_ConstrainCoincidentUnified", self.selection("Edge1", "ExternalEdge1"))
        self.assertEqual((self.geometry(), self.sketch.ExternalGeometry, source.Shape.exportBrepToString()), before)
        self.assertEqual(self.sketch.ConstraintCount, 1)
        self.assertEqual(self.sketch.solve(), 0)

    def test_horizontal_and_vertical_lines_join_matching_projected_lines_without_redundancy(self):
        for axis in ("Horizontal", "Vertical"):
            for names in (("Edge1", "ExternalEdge1"), ("ExternalEdge1", "Edge1")):
                with self.subTest(axis=axis, selection=names):
                    doc = App.newDocument("ProjectedAxisConstraint")
                    try:
                        sketch = doc.addObject("Sketcher::SketchObject", "Sketch")
                        source = doc.addObject("Part::Feature", "Source")
                        transform = (lambda x, y: App.Vector(x, y, 0)) if axis == "Horizontal" else (lambda x, y: App.Vector(y, x, 0))
                        sketch.addGeometry(Part.LineSegment(transform(0, 0), transform(10, 0)), False)
                        sketch.addConstraint(Sketcher.Constraint(axis, 0))
                        source.Shape = Part.makeLine(transform(20, 12), transform(0, 12))
                        sketch.addExternal(source.Name, "Edge1")
                        doc.recompute()
                        original_source = source.Shape.exportBrepToString()
                        original_references = sketch.ExternalGeometry
                        self.assertEqual(sketch.DoF, 3)
                        selection = [SimpleNamespace(Object=sketch, SubElementNames=names)]
                        self.assertTrue(sketch_constraints.coincident_lines(sketch, "Sketcher_ConstrainCoincidentUnified", selection))
                        self.assertEqual(sketch.solve(), 0)
                        self.assertEqual(sketch.DoF, 2)
                        self.assertEqual([c.Type for c in sketch.Constraints], [axis, "PointOnObject"])
                        for point in (sketch.Geometry[0].StartPoint, sketch.Geometry[0].EndPoint):
                            self.assertAlmostEqual(point.y if axis == "Horizontal" else point.x, 12, places=7)
                        for diagnostic in ("ConflictingConstraints", "RedundantConstraints", "PartiallyRedundantConstraints", "MalformedConstraints"):
                            self.assertEqual(list(getattr(sketch, diagnostic)), [], diagnostic)
                        self.assertEqual(sketch.ExternalGeometry, original_references)
                        self.assertEqual(source.Shape.exportBrepToString(), original_source)
                    finally:
                        App.closeDocument(doc.Name)

    def test_two_projected_lines_are_rejected_without_changing_references(self):
        source = self.external_line()
        source.Shape = Part.makeCompound([source.Shape, Part.makeLine(App.Vector(2, 5, 0), App.Vector(10, 7, 0))])
        self.sketch.addExternal(source.Name, "Edge2")
        self.doc.recompute()
        before = self.sketch.ExternalGeometry, source.Shape.exportBrepToString(), self.geometry()
        with self.assertRaises(OperationError):
            sketch_constraints.coincident_lines(self.sketch, "Sketcher_ConstrainCoincidentUnified", self.selection("ExternalEdge1", "ExternalEdge2"))
        self.assertEqual((self.sketch.ExternalGeometry, source.Shape.exportBrepToString(), self.geometry()), before)
        self.assertEqual(self.sketch.ConstraintCount, 0)

    def test_toolbar_coincidence_matches_keyboard_unified_command(self):
        import json
        shortcuts = json.loads((ROOT / "shortcuts.json").read_text())["shortcuts"]
        shortcut = next(item for item in shortcuts if item["id"] == "sketch.coincident")
        self.assertEqual(BY_KEY["sk_coincident"].command, shortcut["native_command"])


if __name__ == "__main__":
    unittest.main()
