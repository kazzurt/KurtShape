"""Slice A/B U6 (A2): one managed recompute per sketch Finish, grouped or not; draft preservation on
build failure; grouped Finish after FreeCAD's undo stack saturated; the raised undo-step preference."""
from pathlib import Path
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import core as core_module
from kurtshape.core import Controller

EVENTS = ("native_recompute", "selector_evaluation", "managed_rebuild", "result_validation", "inspection")
PREFERENCES = "User parameter:BaseApp/Preferences/Document"


class FinishRecomputeTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="finish-recompute-tests-")
        self.core = Controller()
        self.state = None
        self.call("new", name="Finish recompute")

    def tearDown(self):
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

    def captured(self, op, **args):
        """Dispatch ``op`` and return (response, timing events by label) the way the perf audit's probe did."""
        # Native commands rotate the revision at the next sync: read it first, as the GUI does.
        self.state = self.core.inspect(self.doc, False)
        events = {name: [] for name in EVENTS}
        record = self.core.timings.record

        def capture(label, milliseconds):
            if label in events:
                events[label].append(milliseconds)
            record(label, milliseconds)
        self.core.timings.record = capture
        try:
            response = self.request(op, **args)
        finally:
            self.core.timings.record = record
        return response, {name: len(values) for name, values in events.items()}

    def finish(self, **args):
        response, counts = self.captured("finish_sketch_edit", **args)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return counts

    def native_command(self, sketch, index):
        """One native Sketcher command inside the lease: its own transaction, committed."""
        self.doc.openTransaction("Native construction line %d" % index)  # commits the pending lease step first
        sketch.addGeometry(Part.LineSegment(App.Vector(30 + index, 0, 0), App.Vector(30 + index, 5, 0)), True)
        self.doc.commitTransaction()

    def padded_profile(self):
        self.call("sketch_rectangle", id="Profile", width=20, height=10)
        self.call("pad", id="Pad", profile="Profile", length=6)
        self.assertEqual(self.state["build_status"], "valid")
        return self.doc.getObject("Profile")

    # 1. One managed recompute per Finish ---------------------------------------------

    def test_ungrouped_finish_runs_one_managed_recompute(self):
        self.padded_profile()
        undo = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Profile")
        self.call("add_line", sketch="Profile", x1=30, y1=0, x2=35, y2=0, construction=True)
        counts = self.finish()
        self.assertEqual((counts["native_recompute"], counts["selector_evaluation"], counts["managed_rebuild"]), (1, 1, 1),
                         counts)
        self.assertEqual(counts["inspection"], 1, "the response is the one inspection")
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(self.doc.UndoNames[0], "KurtShape: edit " + self.doc.Profile.Label)
        self.assertIsNone(self.state["active_sketch_edit"])
        self.assertEqual(self.doc.Profile.GeometryCount, 5)
        self.assertEqual(self.state["build_status"], "valid")

    def test_grouped_finish_runs_one_managed_recompute_and_is_one_undo_step(self):
        sketch = self.padded_profile()
        undo = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Profile")
        self.native_command(sketch, 0)
        self.native_command(sketch, 1)
        # The lease step (its revision stamp) plus the two native commands are three native steps.
        self.assertEqual(self.doc.UndoCount, undo + 3, list(self.doc.UndoNames)[:4])
        counts = self.finish()
        self.assertEqual((counts["native_recompute"], counts["selector_evaluation"], counts["managed_rebuild"]), (1, 1, 1),
                         counts)
        self.assertEqual(counts["inspection"], 1)
        self.assertEqual(self.doc.UndoCount, undo + 1, "the grouped Finish is one undo step")
        self.assertEqual(self.doc.UndoNames[0], "KurtShape: edit " + sketch.Label)
        self.assertEqual(sketch.GeometryCount, 6)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertIsNone(self.state["active_sketch_edit"])
        self.call("undo")
        self.assertEqual(sketch.GeometryCount, 4, "one undo removes both native commands")
        self.assertEqual(self.state["build_status"], "valid")
        self.call("redo")
        self.assertEqual(sketch.GeometryCount, 6)

    def test_new_sketch_grouped_with_its_creation_runs_one_recompute(self):
        self.call("create_sketch", id="Fresh", plane="XY")
        undo = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Fresh")
        sketch = self.doc.getObject("Fresh")
        self.native_command(sketch, 0)
        self.native_command(sketch, 1)
        counts = self.finish()
        self.assertEqual((counts["native_recompute"], counts["selector_evaluation"]), (1, 1), counts)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertTrue(self.doc.UndoNames[0].startswith(core_module.SKETCH_CREATE_CONTENT), self.doc.UndoNames[0])
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Fresh"), "the first Finish of a new sketch undoes with its creation")

    # 2. Draft preservation on build failure --------------------------------------------

    def test_grouped_finish_build_failure_keeps_the_lease_and_the_draft(self):
        sketch = self.padded_profile()
        undo = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Profile")
        # Two native commands that break the profile the Pad needs.
        self.doc.openTransaction("Native delete 1")
        sketch.delGeometry(3)
        self.doc.commitTransaction()
        self.doc.openTransaction("Native delete 2")
        sketch.delGeometry(2)
        self.doc.commitTransaction()
        self.assertEqual(sketch.GeometryCount, 2)
        response, counts = self.captured("finish_sketch_edit")
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "build_failed", response["error"])
        # The lease and the draft survive; the sketch still shows the broken draft.
        inspection = self.core.inspect(self.doc, False)
        self.state = inspection
        self.assertEqual(inspection["active_sketch_edit"], "Profile")
        self.assertEqual(sketch.GeometryCount, 2, "the draft is preserved")
        self.assertTrue(self.doc.HasPendingTransaction, "the lease continues in a native transaction")
        self.assertGreaterEqual(self.doc.UndoCount, undo, "accepted history below the lease is untouched")
        # Cancel restores the accepted profile and the valid Pad.
        self.call("finish_sketch_edit", cancel=True)
        self.assertEqual(sketch.GeometryCount, 4)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertIsNone(self.state["active_sketch_edit"])
        self.assertAlmostEqual(self.doc.getObject("Pad").Shape.Volume, 20 * 10 * 6)

    def test_finish_after_a_regrouped_failure_counts_only_the_commits_since(self):
        sketch = self.padded_profile()
        undo = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Profile")
        removed = [(sketch.Geometry[index].StartPoint, sketch.Geometry[index].EndPoint) for index in (2, 3)]
        self.doc.openTransaction("Native delete 1")
        sketch.delGeometry(3)
        self.doc.commitTransaction()
        self.doc.openTransaction("Native delete 2")
        sketch.delGeometry(2)
        self.doc.commitTransaction()
        response, _ = self.captured("finish_sketch_edit")
        self.assertEqual(response["error"]["code"], "build_failed", response)
        # Close the profile again with two more native commands, then Finish: one undo step above the
        # accepted history, nothing below it undone.
        for index, (start, end) in enumerate(removed):
            self.doc.openTransaction("Native restore %d" % index)
            sketch.addGeometry(Part.LineSegment(start, end), False)
            self.doc.commitTransaction()
        counts = self.finish()
        self.assertEqual((counts["native_recompute"], counts["selector_evaluation"]), (1, 1), counts)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertIsNone(self.state["active_sketch_edit"])
        self.assertEqual(sketch.GeometryCount, 4)
        self.assertEqual(self.doc.UndoCount, undo + 1, list(self.doc.UndoNames)[:5])
        self.assertAlmostEqual(self.doc.getObject("Pad").Shape.Volume, 20 * 10 * 6)
        self.call("undo")
        self.assertEqual(sketch.GeometryCount, 4, "the accepted rectangle is back")
        self.assertIsNotNone(self.doc.getObject("Pad"), "the undo did not reach the Pad's creation")
        self.assertEqual(self.state["build_status"], "valid")

    def test_native_undo_inside_the_lease_keeps_the_pre_lease_edit(self):
        """Review finding: Std_Undo inside the lease lowers UndoCount but not the commit count."""
        sketch = self.padded_profile()
        self.call("set_parameter", feature="Pad", parameter="Length", value=7)
        accepted = list(self.doc.UndoNames)[:3]
        undo = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Profile")
        self.native_command(sketch, 0)
        self.native_command(sketch, 1)
        self.doc.undo()  # a native undo inside the lease (Std_Undo)
        self.assertEqual(sketch.GeometryCount, 5)
        counts = self.finish()
        self.assertEqual((counts["native_recompute"], counts["selector_evaluation"]), (1, 1), counts)
        self.assertEqual(float(self.doc.getObject("Pad").Length), 7.0, "the pre-lease edit survives")
        self.assertEqual(sketch.GeometryCount, 5)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(self.doc.UndoNames[0], "KurtShape: edit " + sketch.Label)
        self.assertEqual(list(self.doc.UndoNames)[1:4], accepted, "nothing below the lease was undone")
        self.assertIsNone(self.state["active_sketch_edit"])
        self.call("undo")
        self.assertEqual((sketch.GeometryCount, float(self.doc.getObject("Pad").Length)), (4, 7.0))

    def test_native_redo_inside_the_lease_is_counted_too(self):
        sketch = self.padded_profile()
        self.call("set_parameter", feature="Pad", parameter="Length", value=7)
        accepted = list(self.doc.UndoNames)[:3]
        undo = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Profile")
        self.native_command(sketch, 0)
        self.native_command(sketch, 1)
        self.doc.undo()
        self.doc.redo()  # Std_Redo inside the lease: the second command is back
        self.assertEqual(sketch.GeometryCount, 6)
        counts = self.finish()
        self.assertEqual((counts["native_recompute"], counts["selector_evaluation"]), (1, 1), counts)
        self.assertEqual(float(self.doc.getObject("Pad").Length), 7.0)
        self.assertEqual(sketch.GeometryCount, 6)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(list(self.doc.UndoNames)[1:4], accepted)
        self.call("undo")
        self.assertEqual((sketch.GeometryCount, float(self.doc.getObject("Pad").Length)), (4, 7.0))
        # More native undos than lease steps cross the checkpoint: the Finish is refused, nothing is undone.
        self.call("redo")
        self.call("begin_sketch_edit", feature="Profile")
        self.native_command(sketch, 2)
        self.doc.undo()
        self.doc.undo()
        self.doc.undo()  # beyond the lease's steps
        response, _ = self.captured("finish_sketch_edit")
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "sketch_history_changed", response["error"])

    def test_ungrouped_finish_build_failure_keeps_the_lease_and_the_draft(self):
        sketch = self.padded_profile()
        self.call("begin_sketch_edit", feature="Profile")
        sketch.delGeometry(3)  # inside the pending lease transaction, no native commit
        response, _ = self.captured("finish_sketch_edit")
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "build_failed", response["error"])
        self.state = self.core.inspect(self.doc, False)
        self.assertEqual(self.state["active_sketch_edit"], "Profile")
        self.assertEqual(sketch.GeometryCount, 3)
        self.call("finish_sketch_edit", cancel=True)
        self.assertEqual(sketch.GeometryCount, 4)
        self.assertEqual(self.state["build_status"], "valid")

    # 3. Undo saturation ------------------------------------------------------------------

    def saturate(self):
        """27 one-step operations: a headless App.Document keeps FreeCAD's built-in cap of 20."""
        sketch = self.padded_profile()
        for index in range(25):
            self.call("rename_feature", feature="Pad", name="Pad %d" % index)
        self.assertEqual(self.doc.UndoCount, 20)
        return sketch

    def test_saturated_finish_after_a_native_undo_inside_the_lease(self):
        """Review finding: at the cap a native undo made the old UndoCount guard refuse the Finish."""
        sketch = self.saturate()
        self.call("begin_sketch_edit", feature="Profile")
        for index in range(3):
            self.native_command(sketch, index)
        self.doc.undo()  # Std_Undo inside the lease: UndoCount drops below the checkpoint's 20
        self.assertEqual((self.doc.UndoCount, sketch.GeometryCount), (19, 6))
        counts = self.finish()
        self.assertEqual((counts["native_recompute"], counts["selector_evaluation"]), (1, 1), counts)
        self.assertIsNone(self.state["active_sketch_edit"])
        self.assertEqual(sketch.GeometryCount, 6)
        self.assertEqual(self.doc.UndoNames[0], "KurtShape: edit " + sketch.Label, list(self.doc.UndoNames)[:4])
        self.assertEqual(self.doc.UndoNames[1], "KurtShape: rename_feature")
        self.assertEqual(self.doc.getObject("Pad").Label, "Pad 24")
        self.call("undo")
        self.assertEqual((sketch.GeometryCount, self.doc.getObject("Pad").Label), (4, "Pad 24"))

    def test_saturated_cancel_after_a_native_undo_keeps_the_accepted_history(self):
        sketch = self.saturate()
        self.call("begin_sketch_edit", feature="Profile")
        self.native_command(sketch, 0)
        self.native_command(sketch, 1)
        self.doc.undo()
        self.assertEqual(self.doc.UndoCount, 19)
        self.state = self.core.inspect(self.doc, False)
        self.call("finish_sketch_edit", cancel=True)
        self.assertIsNone(self.state["active_sketch_edit"])
        self.assertEqual(sketch.GeometryCount, 4, "the accepted rectangle is back")
        self.assertEqual(self.state["build_status"], "valid")
        self.assertEqual(self.doc.UndoNames[0], core_module.SKETCH_CANCEL_BOUNDARY, list(self.doc.UndoNames)[:4])
        self.assertEqual(self.doc.UndoNames[1], "KurtShape: rename_feature")
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertEqual(self.doc.getObject("Pad").Label, "Pad 24")
        self.call("undo")  # steps over the boundary: the last rename
        self.assertEqual((sketch.GeometryCount, self.doc.getObject("Pad").Label), (4, "Pad 23"))

    def test_grouped_finish_after_more_than_twenty_operations_is_one_undo_step(self):
        sketch = self.saturate()
        saturated = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Profile")
        self.native_command(sketch, 0)
        self.native_command(sketch, 1)
        self.native_command(sketch, 2)
        counts = self.finish()
        self.assertEqual((counts["native_recompute"], counts["selector_evaluation"]), (1, 1), counts)
        self.assertIsNone(self.state["active_sketch_edit"], "the sketch is finished")
        self.assertEqual(sketch.GeometryCount, 7)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertEqual(self.doc.UndoNames[0], "KurtShape: edit " + sketch.Label, list(self.doc.UndoNames)[:4])
        self.assertEqual(self.doc.UndoNames[1], "KurtShape: rename_feature", list(self.doc.UndoNames)[:4])
        self.assertLessEqual(self.doc.UndoCount, saturated, "the stack did not grow past FreeCAD's cap")
        self.call("undo")
        self.assertEqual(sketch.GeometryCount, 4, "one undo removes all three native commands")
        self.assertEqual(self.doc.getObject("Pad").Label, "Pad 24", "the undo did not reach the earlier operations")
        self.call("redo")
        self.assertEqual(sketch.GeometryCount, 7)

    def test_controller_raises_the_undo_step_preference(self):
        group = App.ParamGet(PREFERENCES)
        previous = group.GetInt("MaxUndoSize", 0)
        self.addCleanup(group.SetInt, "MaxUndoSize", previous)
        self.assertGreaterEqual(core_module.UNDO_STEPS, 100)
        self.assertGreaterEqual(group.GetInt("MaxUndoSize", 0), core_module.UNDO_STEPS, "set when the controller started")
        group.SetInt("MaxUndoSize", 20)
        core_module.ensure_undo_steps()
        self.assertEqual(group.GetInt("MaxUndoSize", 0), core_module.UNDO_STEPS, "a lower value is raised")
        group.SetInt("MaxUndoSize", core_module.UNDO_STEPS + 50)
        core_module.ensure_undo_steps()
        self.assertEqual(group.GetInt("MaxUndoSize", 0), core_module.UNDO_STEPS + 50, "a higher value is kept")
        # The preference is read when a GUI document is created; a headless App.Document keeps FreeCAD's
        # built-in cap, which the grouped-Finish test above covers.
        self.assertFalse(hasattr(self.doc, "UndoLimit"))


if __name__ == "__main__":
    unittest.main()
