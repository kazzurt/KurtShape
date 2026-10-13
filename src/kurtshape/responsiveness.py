"""Bounded interaction traces and idle scheduling; no native model mutations.

UI update, paint-event delivery and OpenGL frame swap are separate milestones.
A frame swap is not a measurement of physical display presentation.
"""
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import re
import threading
import time


class BoundedJsonlWriter:
    """Rare diagnostic writes run off the UI thread with bounded memory and disk."""
    def __init__(self, path, max_bytes=1024 * 1024, queue_limit=8):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.pending = queue.Queue(maxsize=max(1, queue_limit))
        self.stopping = threading.Event()
        self.thread = None
        self.dropped = self.failures = 0

    def submit(self, record):
        if self.stopping.is_set():
            return False
        try:
            self.pending.put_nowait(record)
        except queue.Full:
            self.dropped += 1
            return False
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="kurtshape-sketch-diagnostics", daemon=True)
            try:
                self.thread.start()
            except RuntimeError:
                self.thread = None
                self.failures += 1
                return False
        return True

    def _run(self):
        while not self.stopping.is_set() or not self.pending.empty():
            try:
                record = self.pending.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                self._write(record)
            except Exception:
                # Diagnostics must never interrupt modeling or expose a path
                # through an exception report. A later record can still succeed.
                self.failures += 1
            finally:
                self.pending.task_done()

    def _write(self, record):
        raw = (json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        if len(raw) > self.max_bytes:
            self.dropped += 1
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        size = self.path.stat().st_size if self.path.exists() else 0
        if size and size + len(raw) > self.max_bytes:
            self.path.replace(self.path.with_name(self.path.stem + ".previous.jsonl"))
        with self.path.open("ab") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())

    def close(self, timeout=.25):
        self.stopping.set()
        if self.thread is not None:
            # Do not make app shutdown wait indefinitely on a failing drive.
            self.thread.join(timeout)


class SketchStallDiagnostics:
    """Plain-value snapshots only; this helper and its worker never query Qt."""
    COUNTERS = ("input_events", "cursor_changes", "paint_events", "frame_swaps")
    CURSOR_COUNTERS = ("cursor_events", "cache_hits", "cache_misses", "pushes", "changes", "restores",
                       "cache_size", "owned", "deferred_release")
    PHASES = {"command_started", "command_finished", "ui_updated", "paint_event",
              "frame_swapped", "preview_provisional", "preview_ready", "superseded_before_frame"}

    def __init__(self, writer, clock=time.perf_counter, wall_clock=time.time, threshold_ms=500):
        self.writer, self.clock, self.wall_clock = writer, clock, wall_clock
        self.threshold_ms = threshold_ms
        self.last_tick = clock()
        self.command_at_tick = self.last_input_command = None
        self.last_input_at = float("-inf")
        self.last_event_type = self.pointer = None
        self.counters = dict.fromkeys(self.COUNTERS, 0)

    @staticmethod
    def command(value):
        return value if isinstance(value, str) and re.fullmatch(r"Sketcher_Create[A-Za-z0-9_]{1,64}", value) else None

    def note_event(self, event_type, command=None, pointer=None, input_event=False, counter=None):
        self.last_event_type = int(getattr(event_type, "value", event_type))
        if pointer is not None:
            self.pointer = [int(pointer[0]), int(pointer[1])]
        if input_event:
            self.last_input_command = self.command(command)
            self.last_input_at = self.clock()
            self.counters["input_events"] += 1
        if counter in self.counters:
            self.counters[counter] += 1

    def frame_swapped(self):
        self.counters["frame_swaps"] += 1

    def pulse(self, command=None, phase=None, cursor_counters=None):
        now = self.clock()
        delay = max(0.0, (now - self.last_tick) * 1000 - 25)
        current_command = self.command(command)
        input_command = self.last_input_command if self.last_input_at >= self.last_tick else None
        stalled_command = current_command or input_command or self.command_at_tick
        record = None
        if delay >= self.threshold_ms and stalled_command:
            record = {"schema": 1,
                      "timestamp_utc": datetime.fromtimestamp(self.wall_clock(), timezone.utc).isoformat(),
                      "event_loop_delay_ms": round(delay, 3),
                      "native_command": stalled_command,
                      "current_native_command": current_command,
                      "last_input_native_command": input_command,
                      "last_qt_event_type": self.last_event_type,
                      "viewport_pointer_px": list(self.pointer) if self.pointer is not None else None,
                      "phase": phase if phase in self.PHASES else None,
                      "counters": dict(self.counters),
                      "cursor_cache": {key: max(0, min(value, (1 << 63) - 1))
                                       for key, value in (cursor_counters or {}).items()
                                       if key in self.CURSOR_COUNTERS and isinstance(value, int)},
                      "dropped_records": self.writer.dropped,
                      "write_failures": self.writer.failures}
            self.writer.submit(record)
        self.last_tick, self.command_at_tick = now, current_command
        self.counters = dict.fromkeys(self.COUNTERS, 0)
        return delay


class InteractionTrace:
    def __init__(self, timings, clock=time.perf_counter, limit=256):
        self.timings, self.clock = timings, clock
        self.entries = deque(maxlen=limit)
        self.current = None
        self.serial = 0

    def begin(self, kind="input"):
        self.serial += 1
        entry = {"id": self.serial, "kind": kind, "started": self.clock(), "phases": {}}
        self.entries.append(entry)
        self.current = entry
        return entry

    def mark(self, entry, phase):
        if entry is None or phase in entry["phases"]:
            return
        elapsed = max(0.0, (self.clock() - entry["started"]) * 1000)
        entry["phases"][phase] = elapsed
        self.timings.record("input_to_" + phase, elapsed)

    @contextmanager
    def command(self, name):
        # A command has its own identity even if nested Qt processing delivers
        # another physical input before it finishes.
        origin = self.current
        entry = self.begin("command:" + name)
        if origin is not None and origin["kind"] in {"key", "pointer"}:
            entry["input_id"] = origin["id"]
            entry["started"] = origin["started"]
        self.mark(entry, "command_started")
        started = self.clock()
        try:
            yield entry
        except Exception:
            entry["outcome"] = "error"
            raise
        finally:
            self.mark(entry, "command_finished")
            self.timings.record("command_" + name, (self.clock() - started) * 1000)

    def report(self):
        return [{key: (dict(value) if key == "phases" else value)
                 for key, value in entry.items() if key != "started"} for entry in self.entries]


def install_monitor(panel):
    from PySide import QtCore, QtGui

    class Monitor(QtCore.QObject):
        def __init__(self):
            super().__init__(panel)
            self.trace = InteractionTrace(panel.core.timings)
            self.last_activity = time.perf_counter()
            session = Path(os.environ.get("KURTSHAPE_SESSION_DIR", str(Path(__file__).resolve().parents[2] / "runtime")))
            self.stall_writer = BoundedJsonlWriter(session / "diagnostics" / "sketch-stalls.jsonl")
            self.stalls = SketchStallDiagnostics(self.stall_writer)
            self.pending_frames = {}
            self.views = {}
            self.view_windows = {}
            self.view_sources = {}
            self.source_views = {}
            self.mdi = panel.main.findChild(QtGui.QMdiArea)
            self.closed = False
            self.timer = QtCore.QTimer(self)
            self.timer.setInterval(25)
            self.timer.timeout.connect(self.pulse)
            self.timer.start()
            self.app = QtGui.QApplication.instance()
            self.app.installEventFilter(self)

        def pulse(self):
            entry = self.trace.current
            phase = next(reversed(entry["phases"]), None) if entry is not None else None
            cursor = getattr(panel, "sketch_cursor", None)
            delay = self.stalls.pulse(self.native_command(), phase, getattr(cursor, "counters", None))
            panel.core.timings.record("event_loop_delay", delay)

        def native_command(self):
            references = getattr(panel, "sketch_references", None)
            return getattr(references, "native_tool", None)

        def is_idle(self, seconds=2.0):
            return time.perf_counter() - self.last_activity >= seconds

        def ui_updated(self, entry=None):
            entry = self.trace.current if entry is None else entry
            self.trace.mark(entry, "ui_updated")
            key = self.active_view_key()
            if entry is not None and key is not None:
                prior = self.pending_frames.get(key)
                if prior is not None and prior is not entry:
                    prior["outcome"] = "superseded_before_frame"
                    self.trace.mark(prior, "superseded_before_frame")
                self.pending_frames[key] = entry

        def active_view_key(self):
            window = self.mdi.activeSubWindow() if self.mdi is not None else None
            if window is None:
                return None
            for widget in window.findChildren(QtGui.QWidget):
                if widget.metaObject().className() == "QOpenGLWidget" and widget.isVisible():
                    self.watch_view(widget)
                    return id(widget)
            return None

        def watch_view(self, widget):
            key = id(widget)
            if key in self.views or not hasattr(widget, "frameSwapped"):
                return
            self.views[key] = widget
            # FreeCAD changes the inherited cursor on the viewer ancestor,
            # not necessarily on QOpenGLWidget. Cache the short widget chain
            # once, so cursor/input events never search the UI or scene graph.
            # Keep the wrappers alive: native parentWidget() wrappers may
            # otherwise be transient and Python can recycle their id()s
            # during this very walk.
            sources, parent = [widget], widget.parentWidget()
            while parent is not None and not isinstance(parent, QtGui.QMdiSubWindow):
                sources.append(parent)
                parent = parent.parentWidget()
            self.view_windows[key] = parent
            self.view_sources[key] = sources if parent is not None else [widget]
            for source in {id(item) for item in self.view_sources[key]}:
                self.source_views.setdefault(source, set()).add(key)
            widget.frameSwapped.connect(lambda: self.frame_swapped(key))
            widget.destroyed.connect(lambda *args: self.drop_view(key))

        def active_event_view(self, watched):
            candidates = self.source_views.get(id(watched), ())
            if not candidates or self.mdi is None:
                return None
            window = self.mdi.activeSubWindow()
            for key in candidates:
                widget = self.views.get(key)
                if widget is not None and self.view_windows.get(key) is window and widget.isVisible():
                    return widget
            return None

        def drop_view(self, key):
            # Pop this ownership record before releasing any Qt wrappers;
            # destruction can re-enter through another connected callback.
            sources = self.view_sources.pop(key, ())
            entry = self.pending_frames.pop(key, None)
            if entry is not None:
                entry["outcome"] = "view_closed_before_frame"
            for source in {id(item) for item in sources}:
                candidates = self.source_views.get(source)
                if candidates is None:
                    continue
                candidates.discard(key)
                if not candidates:
                    self.source_views.pop(source, None)
            self.views.pop(key, None)
            self.view_windows.pop(key, None)

        def frame_swapped(self, key):
            # Ignore swaps from a hidden/non-active viewer. A document switch
            # must not make an old document's paint count as current feedback.
            widget = self.views.get(key)
            if widget is not None and widget.isVisible() and key == self.active_view_key():
                self.stalls.frame_swapped()
                self.trace.mark(self.pending_frames.pop(key, None), "frame_swapped")

        def eventFilter(self, watched, event):
            kind = event.type()
            if kind in {QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress,
                        QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove, QtCore.QEvent.Wheel}:
                self.last_activity = time.perf_counter()
                pointer = None
                if kind != QtCore.QEvent.KeyPress and isinstance(watched, QtGui.QWidget):
                    viewport = self.active_event_view(watched)
                    if viewport is not None:
                        # Qt 6 QWheelEvent has position(), but no pos().
                        point = event.position().toPoint() if hasattr(event, "position") else event.pos()
                        if watched is not viewport:
                            point = viewport.mapFrom(watched, point)
                        pointer = (point.x(), point.y())
                self.stalls.note_event(kind, self.native_command(), pointer, input_event=True)
            if kind == QtCore.QEvent.CursorChange and self.active_event_view(watched) is not None:
                self.stalls.note_event(kind, counter="cursor_changes")
            if kind in {QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.Wheel}:
                self.trace.begin("key" if kind == QtCore.QEvent.KeyPress else "pointer")
            if kind in {QtCore.QEvent.Paint, QtCore.QEvent.Show} and isinstance(watched, QtGui.QWidget):
                if watched.metaObject().className() == "QOpenGLWidget":
                    self.watch_view(watched)
                    if kind == QtCore.QEvent.Paint and id(watched) == self.active_view_key():
                        self.stalls.note_event(kind, counter="paint_events")
                        self.trace.mark(self.pending_frames.get(id(watched)), "paint_event")
            return False

        def close(self):
            if self.closed:
                return
            self.closed = True
            self.pulse()
            self.timer.stop()
            self.app.removeEventFilter(self)
            for key in tuple(self.views):
                self.drop_view(key)
            self.stall_writer.close()

    return Monitor()
