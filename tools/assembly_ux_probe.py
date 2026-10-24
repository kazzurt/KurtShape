"""Shared harness for the assembly UX GUI recipes (docs/assembly-ux/STATUS.md).

Imported by tools/*-validation.FCMacro run through tools/run_gui_recipe.ps1 on a
private desktop with a fresh profile. Builds fixtures through the production
Panel, never touches user documents and takes no screen captures.
"""
import json
import os
from pathlib import Path
import queue
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore
from PySide6 import QtGui, QtTest, QtWidgets

ROOT = Path(os.environ["KURTSHAPE_ROOT"]).resolve()
SESSION = Path(os.environ["KURTSHAPE_SESSION_DIR"]).resolve()
assert SESSION.is_relative_to(ROOT / "runtime")
assert Path(os.environ["FREECAD_USER_HOME"]).resolve().is_relative_to(SESSION)


class NoSocketTransport:
    def __init__(self, *args):
        self.pending = queue.Queue()

    def tick(self):
        return False

    def close(self):
        pass


class HiddenPopupFilter(QtCore.QObject):
    def eventFilter(self, watched, event):
        if event.type() in {QtCore.QEvent.Polish, QtCore.QEvent.Show} and isinstance(watched, QtWidgets.QWidget) and watched.isWindow():
            watched.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
        return False


class Probe:
    def __init__(self, name, method):
        from kurtshape_evidence import evidence_dir
        from kurtshape import ui
        ui.Bridge = NoSocketTransport
        self.ui = ui
        self.app = QtWidgets.QApplication.instance()
        self.main = Gui.getMainWindow()
        self.main.hide()
        self.main.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
        self.main.resize(1440, 920)
        self.main.show()
        self.hidden = HiddenPopupFilter(self.app)
        self.app.installEventFilter(self.hidden)
        self.output = evidence_dir(name)
        self.report = {"passed": False, "checks": [], "log": [], "method": method,
                       "engine": {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION}}
        self.panel = None
        self.started = time.perf_counter()

    def save(self):
        (self.output / "gui-result.json").write_text(json.dumps(self.report, indent=2, default=str), encoding="utf-8")

    def wait(self, ms=80):
        QtTest.QTest.qWait(ms)

    def check(self, label, condition, detail=None):
        if not condition:
            raise AssertionError(label + (": " + repr(detail) if detail is not None else ""))
        self.report["checks"].append(label)
        self.save()

    def call(self, op, **args):
        result = self.panel.operation(op, **args)
        if not result:
            raise AssertionError(op + ": " + self.panel.message.text())
        self.wait()
        return result

    def source_part(self, name, shape):
        """A plain native FCStd with one Body (safe assembly source); returns its path."""
        path = SESSION / (name + ".FCStd")
        source = App.newDocument(name)
        body = source.addObject("PartDesign::Body", "Body")
        body.newObject("PartDesign::Feature", "BodySolid").Shape = shape
        source.recompute()
        source.saveAs(str(path))
        App.closeDocument(source.Name)
        self.wait(100)
        return path

    def close_active(self):
        App.closeDocument(self.panel.document().Name)
        self.panel.tick()
        self.wait(200)

    def viewport(self):
        from kurtshape.selection_mode import is_viewer_surface
        active = self.main.findChild(QtWidgets.QMdiArea).activeSubWindow()
        return next(w for w in active.findChildren(QtWidgets.QWidget)
                    if is_viewer_surface(w) and w.isVisible() and w.width() > 300)

    def pixel(self, world):
        point = Gui.activeDocument().activeView().getPointOnViewport(App.Vector(*world))
        gl = self.viewport()
        ratio = gl.devicePixelRatioF()
        return QtCore.QPoint(round(point[0] / ratio), gl.height() - 1 - round(point[1] / ratio))

    def move(self, point):
        gl = self.viewport()
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(point), QtCore.QPointF(gl.mapToGlobal(point)),
                                  QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
        self.app.sendEvent(gl, event)
        self.wait(40)

    def click(self, point, modifier=QtCore.Qt.NoModifier):
        self.move(point)
        QtTest.QTest.mouseClick(self.viewport(), QtCore.Qt.LeftButton, modifier, point)
        self.wait(150)

    def frame(self):
        self.panel.isometric()
        self.panel.fit()
        self.wait(300)

    def run(self, body, seconds=300):
        def validate():
            try:
                self.panel = self.ui.start()
                self.panel.recovery_timer.stop()
                self.panel.core.settings.roots = {SESSION}
                body(self)
                self.report["passed"] = True
            except Exception:
                self.report["error"] = traceback.format_exc()
                if self.panel:
                    self.report["status_text"] = self.panel.message.text()
            finally:
                self.report["seconds"] = time.perf_counter() - self.started
                self.report["check_count"] = len(self.report["checks"])
                self.save()
                self.cleanup()

        def timeout():
            if not self.report.get("seconds"):
                self.report["error"] = f"Probe exceeded {seconds} seconds"
                self.save()
                self.cleanup()

        QtCore.QTimer.singleShot(seconds * 1000, timeout)
        QtCore.QTimer.singleShot(1500, validate)

    def cleanup(self):
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        try:
            if self.panel:
                self.panel.shutdown()
            for name in list(App.listDocuments()):
                doc = App.getDocument(name)
                gui_doc = Gui.getDocument(name)
                if gui_doc and gui_doc.getInEdit():
                    gui_doc.resetEdit()
                if doc.HasPendingTransaction:
                    doc.abortTransaction()
                App.closeDocument(name)
        finally:
            self.app.removeEventFilter(self.hidden)
            QtCore.QTimer.singleShot(0, self.app.quit)
