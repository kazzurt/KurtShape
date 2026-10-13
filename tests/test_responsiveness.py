"""Interaction accounting, persistent rows and durable idle recovery invariants."""
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape.timing import Timings
from kurtshape.responsiveness import BoundedJsonlWriter, InteractionTrace, SketchStallDiagnostics, install_monitor


class SketchStallDiagnosticsTests(unittest.TestCase):
    def recorder(self, **writer_options):
        folder = support.scratch(self, prefix="sketch-stall-diagnostics-")
        writer = BoundedJsonlWriter(folder / "diagnostics" / "sketch-stalls.jsonl", **writer_options)
        self.addCleanup(writer.close, 2)
        now = [0.0]
        recorder = SketchStallDiagnostics(writer, clock=lambda: now[0], wall_clock=lambda: 1791311332)
        return writer, recorder, now

    def test_threshold_context_survives_tool_end_and_only_plain_metadata_is_saved(self):
        writer, recorder, now = self.recorder()
        recorder.note_event(5, "Sketcher_CreatePolyline", (145, 287), input_event=True)
        now[0] = .524
        recorder.pulse("Sketcher_CreatePolyline")
        self.assertIsNone(writer.thread)
        # The input starts while drawing, but processing the click ends the
        # native command before the delayed pulse finally resumes.
        now[0] = .6
        recorder.note_event(2, "Sketcher_CreatePolyline", (150, 290), input_event=True)
        recorder.note_event(183, counter="cursor_changes")
        recorder.frame_swapped()
        now[0] = 1.05
        recorder.pulse(None, "command_finished", {"cache_hits": 7, "owned": True, "private_path": "example"})
        writer.close(2)
        record = json.loads(writer.path.read_text())
        self.assertEqual(record["event_loop_delay_ms"], 501)
        self.assertEqual(record["native_command"], "Sketcher_CreatePolyline")
        self.assertIsNone(record["current_native_command"])
        self.assertEqual(record["viewport_pointer_px"], [150, 290])
        self.assertEqual(record["last_qt_event_type"], 183)
        self.assertEqual(record["phase"], "command_finished")
        self.assertEqual(record["counters"]["cursor_changes"], 1)
        self.assertEqual(record["counters"]["frame_swaps"], 1)
        self.assertEqual(record["cursor_cache"], {"cache_hits": 7, "owned": True})
        self.assertTrue(record["timestamp_utc"].endswith("+00:00"))
        self.assertNotIn("text", record)
        self.assertNotIn("document", record)

    def test_prior_pulse_context_expires_and_nonsketch_stalls_create_no_file(self):
        writer, recorder, now = self.recorder()
        recorder.pulse("Sketcher_CreateCircle")
        now[0] = 1
        recorder.pulse(None)
        now[0] = 2
        recorder.pulse(None)
        now[0] = 3
        recorder.note_event(6, "PartDesign_Pad", input_event=True)
        recorder.pulse("PartDesign_Pad")
        writer.close(2)
        self.assertEqual(len(writer.path.read_text().splitlines()), 1)
        other, ordinary, clock = self.recorder()
        clock[0] = 10
        ordinary.note_event(6, "private document text", input_event=True)
        ordinary.pulse("private document text", "private path")
        self.assertIsNone(other.thread)
        self.assertFalse(other.path.exists())

    def test_rotation_caps_each_file_and_writes_happen_on_worker(self):
        writer, recorder, now = self.recorder(max_bytes=1200)
        original = writer._write
        threads = []

        def traced_write(record):
            threads.append(threading.get_ident())
            original(record)

        with patch.object(writer, "_write", side_effect=traced_write):
            for index in range(6):
                now[0] += 1
                recorder.pulse("Sketcher_CreateCircle")
                writer.pending.join()
            writer.close(2)
        files = list(writer.path.parent.iterdir())
        self.assertEqual(len(files), 2)
        self.assertTrue(all(item.stat().st_size <= 1200 for item in files))
        self.assertEqual(len(threads), 6)
        self.assertTrue(all(ident != threading.get_ident() for ident in threads))
        self.assertEqual(json.loads(writer.path.read_text().splitlines()[-1])["native_command"], "Sketcher_CreateCircle")

    def test_queue_is_bounded_and_write_failure_does_not_stop_future_reports(self):
        writer, recorder, now = self.recorder(queue_limit=2)
        entered, release = threading.Event(), threading.Event()
        original = writer._write
        calls = [0]

        def held_failure(record):
            calls[0] += 1
            if calls[0] == 1:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("Test did not release diagnostic writer")
                raise OSError("injected disk error")
            original(record)

        with patch.object(writer, "_write", side_effect=held_failure):
            try:
                now[0] = 1
                recorder.pulse("Sketcher_CreatePolyline")
                self.assertTrue(entered.wait(2))
                for _ in range(8):
                    now[0] += 1
                    recorder.pulse("Sketcher_CreatePolyline")
                self.assertEqual(writer.pending.qsize(), 2)
                self.assertEqual(writer.dropped, 6)
                writer.close(0)
            finally:
                release.set()
                writer.close(2)
        self.assertEqual(writer.failures, 1)
        self.assertEqual(len(writer.path.read_text().splitlines()), 2)
        self.assertFalse(writer.submit({}))

    def test_monitor_observes_active_viewer_ancestor_and_qt6_wheel_position(self):
        import FreeCAD  # noqa: F401 -- bundled PySide compatibility module.
        from PySide import QtCore, QtGui

        class QOpenGLWidget(QtGui.QWidget):
            # Exercise actual Qt event delivery without creating an OpenGL
            # context in the suite's offscreen platform.
            frameSwapped = QtCore.Signal()

        app = QtGui.QApplication.instance() or QtGui.QApplication([])
        main, panel = QtGui.QMainWindow(), QtGui.QWidget()
        mdi = QtGui.QMdiArea()
        main.setCentralWidget(mdi)
        panel.main = main
        panel.core = SimpleNamespace(timings=Timings())
        panel.sketch_references = SimpleNamespace(native_tool="Sketcher_CreatePolyline")
        views = []
        monitor = None
        folder = support.scratch(self, prefix="sketch-stall-qt-monitor-")
        try:
            for _ in range(2):
                viewer = QtGui.QWidget()
                layout = QtGui.QVBoxLayout(viewer)
                viewport = QOpenGLWidget()
                layout.addWidget(viewport)
                window = mdi.addSubWindow(viewer)
                window.show()
                views.append((window, viewer, viewport))
            main.show()
            mdi.setActiveSubWindow(views[1][0])
            app.processEvents()
            with patch.dict(os.environ, {"KURTSHAPE_SESSION_DIR": str(folder)}):
                monitor = install_monitor(panel)
            for _, _, viewport in views:
                monitor.watch_view(viewport)
            app.sendEvent(views[0][1], QtCore.QEvent(QtCore.QEvent.CursorChange))
            self.assertEqual(monitor.stalls.counters["cursor_changes"], 0)
            app.sendEvent(views[1][1], QtCore.QEvent(QtCore.QEvent.CursorChange))
            self.assertEqual(monitor.stalls.counters["cursor_changes"], 1)

            wheel = QtGui.QWheelEvent(QtCore.QPointF(13, 24), QtCore.QPointF(37, 50),
                                     QtCore.QPoint(), QtCore.QPoint(0, 120),
                                     QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
                                     QtCore.Qt.NoScrollPhase, False)
            app.sendEvent(views[1][2], wheel)
            self.assertEqual(monitor.stalls.pointer, [13, 24])
            # Multiple GL children share the native viewer ancestors. Keep
            # those mappings until all children are gone, including repeated
            # destroyed callbacks and duplicate cached ancestors.
            sibling = QOpenGLWidget()
            views[1][1].layout().addWidget(sibling)
            monitor.watch_view(sibling)
            first_key, sibling_key = id(views[1][2]), id(sibling)
            sources = monitor.view_sources[first_key]
            self.assertTrue(all(isinstance(item, QtGui.QWidget) for item in sources))
            sources.extend(sources[1:])
            views[1][2].destroyed.connect(lambda *args: monitor.drop_view(first_key))
            sibling.destroyed.connect(lambda *args: monitor.drop_view(sibling_key))
            errors = []
            with patch.object(sys, "excepthook", side_effect=lambda *args: errors.append(args)):
                views[1][2].deleteLater()
                app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
                self.assertNotIn(first_key, monitor.views)
                self.assertEqual(monitor.source_views[id(views[1][1])], {sibling_key})
                # Destroying the common parent destroys its remaining child;
                # drop_view can run both from close and destruction safely.
                views[1][1].deleteLater()
                app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
                monitor.drop_view(first_key)
                monitor.drop_view(sibling_key)
            self.assertEqual(errors, [])
            self.assertNotIn(id(views[1][1]), monitor.source_views)
            monitor.close()
            monitor.close()
            self.assertEqual(monitor.source_views, {})
        finally:
            if monitor is not None:
                monitor.close()
            main.close()
            panel.deleteLater()
            main.deleteLater()
            app.processEvents()


class InteractionTimingTests(unittest.TestCase):
    def test_long_stalls_are_retained_and_phases_are_not_interchangeable(self):
        now = [10.0]
        timings = Timings()
        trace = InteractionTrace(timings, clock=lambda: now[0])
        first = trace.begin()
        now[0] += 8
        trace.mark(first, "ui_updated")
        self.assertEqual(timings.report()["input_to_ui_updated"]["worst_ms"], 8000)
        self.assertNotIn("input_to_frame_swapped", timings.report())
        second = trace.begin()
        now[0] += .02
        trace.mark(first, "frame_swapped")
        trace.mark(first, "frame_swapped")
        self.assertEqual(len(timings.samples["input_to_frame_swapped"]), 1)
        self.assertEqual(second["phases"], {})
        self.assertAlmostEqual(first["phases"]["frame_swapped"], 8020)

    def test_command_retains_identity_when_another_input_arrives(self):
        now = [0.0]
        timings = Timings()
        trace = InteractionTrace(timings, clock=lambda: now[0], limit=3)
        with trace.command("pad") as operation:
            now[0] = 1.0
            pointer = trace.begin("pointer")
            now[0] = 7.0
        self.assertEqual(operation["phases"]["command_finished"], 7000)
        self.assertEqual(pointer["phases"], {})
        for _ in range(10):
            trace.begin()
        self.assertEqual(len(trace.report()), 3)


class HistoryModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import FreeCAD  # noqa: F401 — installs the bundled PySide compatibility module.
        from PySide import QtGui
        cls.app = QtGui.QApplication.instance() or QtGui.QApplication([])

    def test_rows_survive_edits_and_reorders_without_stale_style_or_selection(self):
        from PySide import QtCore, QtGui
        from kurtshape.history_model import HistoryModel
        tree = QtGui.QTreeWidget()
        model = HistoryModel(tree)
        try:
            rows = [{"key": "a", "text": "A", "italic": True, "color": "#888888",
                     "data": {QtCore.Qt.UserRole: "a"}},
                    {"key": "b", "text": "B", "data": {QtCore.Qt.UserRole: "b"}}]
            model.reconcile("doc1", rows)
            first, second = model.items["a"], model.items["b"]
            tree.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
            tree.setCurrentItem(second)
            first.setSelected(True)
            second.setSelected(True)
            model.reconcile("doc1", [rows[1], {"key": "a", "text": "A edited", "data": {QtCore.Qt.UserRole: "a"}}])
            self.assertIs(model.items["a"], first)
            self.assertIs(model.items["b"], second)
            self.assertTrue(first.isSelected())
            self.assertTrue(second.isSelected())
            self.assertIs(tree.currentItem(), second)
            self.assertFalse(first.font(0).italic())
            self.assertEqual(first.foreground(0), QtGui.QBrush())
            self.assertEqual(model.created, 2)
            self.assertIs(tree.topLevelItem(0), second)
            model.reconcile("doc1", [{"key": "a", "text": "A"}])
            self.assertEqual(tree.topLevelItemCount(), 1)
            model.reconcile("doc2", [{"key": "a", "text": "Different document"}])
            self.assertEqual(model.created, 3)
            self.assertEqual(model.items["a"].text(0), "Different document")
        finally:
            tree.deleteLater()

    def test_nested_rows_survive_insertion_and_old_subtrees_are_removed(self):
        from PySide import QtGui
        from kurtshape.history_model import HistoryModel
        tree = QtGui.QTreeWidget()
        model = HistoryModel(tree)
        try:
            model.reconcile("doc", [{"key": "origin", "text": "Origin", "expand_new": True,
                                     "children": [{"key": "xy", "text": "Top"}]}])
            child = model.items["xy"]
            self.assertTrue(model.items["origin"].isExpanded())
            model.reconcile("doc", [{"key": "origin", "text": "Origin",
                                     "children": [{"key": "xz", "text": "Front"}, {"key": "xy", "text": "Top"}]}])
            self.assertIs(model.items["xy"], child)
            model.reconcile("doc", [{"key": "feature", "text": "Pad"}])
            self.assertEqual(set(model.items), {"feature"})
            self.assertEqual(tree.topLevelItemCount(), 1)
        finally:
            tree.deleteLater()


class RecoverySchedulingTests(unittest.TestCase):
    def setUp(self):
        import FreeCAD as App
        from kurtshape.core import Controller
        self.App = App
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="responsive-recovery-")
        self.core = Controller()
        response = self.core.dispatch({"op": "new", "name": "Idle recovery test", "measure": False})
        self.assertTrue(response["ok"], response)
        self.doc = self.core.documents[response["result"]["document_id"]]

    def tearDown(self):
        self.core.close()
        for name in set(self.App.listDocuments()) - self.names:
            self.App.closeDocument(name)

    def test_async_publication_is_serialized_and_forced_checkpoint_remains_durable(self):
        store = self.core.recovery
        initial = self.core.checkpoint(self.doc, force=True)
        self.assertEqual(store.snapshot_count, 1)
        initial_revision = store.read(initial)[1]["revision"]
        store.last.clear()
        self.doc.Label = "Captured before later edit"
        entered, release = threading.Event(), threading.Event()
        publish = store._publish
        worker_threads = []

        def blocked_publish(stage, path, record):
            worker_threads.append(threading.get_ident())
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Test failed to release file publication")
            return publish(stage, path, record)

        with patch.object(store, "_publish", side_effect=blocked_publish):
            try:
                self.assertIsNone(self.core.checkpoint(self.doc, background=True))
                self.assertEqual(store.snapshot_count, 2)
                self.assertTrue(entered.wait(5))
                self.assertEqual(len(store.pending), 1)
                self.assertEqual(json.loads(initial.read_text())["revision"], initial_revision)
                # An in-flight checkpoint is neither advertised as durable nor
                # overwritten by repeated idle timer calls.
                self.assertIsNone(self.core.checkpoint(self.doc, background=True))
                self.doc.Label = "Newer forced revision"
            finally:
                release.set()
            final = self.core.checkpoint(self.doc, force=True)
        self.assertEqual(store.pending, {})
        self.assertNotEqual(worker_threads[0], threading.get_ident())
        self.assertEqual(store.read(final)[1]["name"], "Newer forced revision")
        previous = final.with_suffix(".previous.json")
        self.assertEqual(store.read(previous)[1]["name"], "Captured before later edit")

    def test_read_waits_for_publication_before_verifying_native_draft_pair(self):
        store = self.core.recovery
        manifest = self.core.checkpoint(self.doc, force=True)
        store.last.clear()
        self.doc.Label = "New recovery snapshot"
        entered, release, read_started, read_done = (threading.Event() for _ in range(4))
        publish = store._publish
        result = []

        def held_publish(stage, path, record):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Publication test was not released")
            return publish(stage, path, record)

        def read_pair():
            read_started.set()
            try:
                result.append(store.read(manifest))
            finally:
                read_done.set()

        with patch.object(store, "_publish", side_effect=held_publish):
            self.core.checkpoint(self.doc, background=True)
            self.assertTrue(entered.wait(5))
            reader = threading.Thread(target=read_pair)
            reader.start()
            try:
                self.assertTrue(read_started.wait(5))
                self.assertFalse(read_done.wait(.05), "Recovery read escaped while the native pair was being replaced")
            finally:
                release.set()
                reader.join(5)
        self.assertTrue(read_done.is_set())
        self.assertEqual(result[0][1]["name"], "New recovery snapshot")
        self.assertEqual(store.pending, {})

    def test_background_failure_keeps_previous_pair_and_is_reported(self):
        store = self.core.recovery
        original = self.core.checkpoint(self.doc, force=True)
        snapshot, record = store.read(original)
        source = snapshot.read_bytes()
        store.last.clear()
        entered, release = threading.Event(), threading.Event()

        def fail(stage, path, saved):
            entered.set()
            release.wait(5)
            raise OSError("injected publication failure")

        with patch.object(store, "_publish", side_effect=fail):
            try:
                self.core.checkpoint(self.doc, background=True)
                self.assertTrue(entered.wait(5))
            finally:
                release.set()
            with self.assertRaisesRegex(RuntimeError, "injected publication failure"):
                store.close()
        self.assertEqual(store.pending, {})
        self.assertEqual(store.read(original)[1], record)
        self.assertEqual(snapshot.read_bytes(), source)

    def test_old_failed_publication_does_not_block_fresh_forced_capture(self):
        store = self.core.recovery
        entered, release = threading.Event(), threading.Event()
        publish = store._publish
        attempts = [0]

        def first_fails(stage, path, record):
            attempts[0] += 1
            if attempts[0] == 1:
                entered.set()
                release.wait(5)
                raise OSError("older background checkpoint failed")
            return publish(stage, path, record)

        with patch.object(store, "_publish", side_effect=first_fails):
            self.core.checkpoint(self.doc, background=True)
            self.assertTrue(entered.wait(5))
            self.doc.Label = "Emergency checkpoint"
            release.set()
            fresh = self.core.checkpoint(self.doc, force=True)
        self.assertEqual(store.read(fresh)[1]["name"], "Emergency checkpoint")
        with self.assertRaisesRegex(RuntimeError, "older background checkpoint failed"):
            store.poll()
