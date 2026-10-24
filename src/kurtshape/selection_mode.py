"""Additive click selection in the 3D view (assembly UX item 1).

A plain left click on a face, edge or vertex adds it to the selection, a click
on an element that is already selected removes it, a click on empty space
clears and Shift-click is unchanged. FreeCAD's unified-selection node already
toggles an element when the click carries Ctrl, so a plain click that lands on
geometry is re-sent to the viewer with Ctrl added; empty-space clicks stay
plain and keep the native clear.

A Coin event callback (``addEventCallbackPivy`` + ``setHandled``) cannot do
this: verified in a private native GUI on 2026-10-24 (FreeCAD 1.1.4), the
callback sees only the button press, and the native selection still replaces
the current one after a handled press. A Qt filter on the viewer's
QOpenGLWidget runs before the navigation style for every view, existing and
future, which is why this module filters there (as ``hover_outline`` does).
"""
from __future__ import annotations

import FreeCAD as App

PREFERENCES = "User parameter:KurtShape/Preferences"
KEY = "AdditiveSelection"


def enabled():
    return App.ParamGet(PREFERENCES).GetBool(KEY, True)


def set_enabled(value):
    App.ParamGet(PREFERENCES).SetBool(KEY, bool(value))


def is_viewer_surface(widget):
    """The QOpenGLWidget a View3DInventorViewer paints into."""
    try:
        if widget.metaObject().className() != "QOpenGLWidget":
            return False
        parent = widget.parentWidget()
        return bool(parent) and parent.metaObject().className() == "Gui::View3DInventorViewer"
    except (AttributeError, RuntimeError):
        return False


def native_position(widget, view, point):
    """Qt widget coordinates to the bottom-left pixel coordinates Coin picks with."""
    ratio = widget.devicePixelRatioF()
    return (round(point.x() * ratio), view.getSize()[1] - 1 - round(point.y() * ratio))


def picks_geometry(hit):
    """Whether a getObjectInfo hit names a selectable sub-element (FaceN/EdgeN/VertexN)."""
    return bool(hit) and bool(hit.get("Object")) and bool(hit.get("Component"))


def install(panel):
    """Install the application-wide filter once; returns it (kept by the panel)."""
    from PySide import QtCore, QtGui

    class AdditiveSelection(QtCore.QObject):
        CTRL = QtCore.Qt.ControlModifier
        LEFT = QtCore.Qt.LeftButton

        def __init__(self):
            super().__init__(panel)
            self.panel = panel
            self.rewriting = None  # the widget whose current left press was re-sent with Ctrl
            self.sending = False
            self.rewritten = 0

        def native_owned(self):
            """True when the native click semantics must stay: pickers, sketches, tasks."""
            p = self.panel
            if not enabled():
                return True
            try:
                if (p.pending_sketch or p.selecting_support or p.studio_selection_callback is not None
                        or p.sketch_plane_editor.picking or p.section_view.picking or p.core.busy):
                    return True
                import FreeCADGui as Gui
                gui_doc = Gui.activeDocument()
                if gui_doc is None or gui_doc.getInEdit() or Gui.Control.activeDialog():
                    return True
                for widget in QtGui.QApplication.topLevelWidgets():
                    if widget.isVisible() and widget.objectName() == "KurtShapeAssemblyJointDialog":
                        return True
            except Exception:  # a closing document or a headless session: stay native
                return True
            return False

        def hit(self, widget, point):
            import FreeCADGui as Gui
            gui_doc = Gui.activeDocument()
            view = gui_doc.activeView() if gui_doc else None
            if view is None or not hasattr(view, "getObjectInfo"):
                return None
            try:
                return view.getObjectInfo(native_position(widget, view, point))
            except (RuntimeError, TypeError, ValueError, AttributeError):
                return None

        def resend(self, widget, event):
            point = event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())
            glob = event.globalPosition() if hasattr(event, "globalPosition") else QtCore.QPointF(event.globalPos())
            copy = QtGui.QMouseEvent(event.type(), point, glob, event.button(), event.buttons(),
                                     event.modifiers() | self.CTRL)
            self.sending = True
            try:
                QtGui.QApplication.instance().sendEvent(widget, copy)
            finally:
                self.sending = False
            return True

        def eventFilter(self, watched, event):
            kind = event.type()
            if self.sending or kind not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                                            QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseMove):
                return False
            if not is_viewer_surface(watched):
                return False
            if kind == QtCore.QEvent.MouseMove:
                # A drag that started as a rewritten click keeps its Ctrl until release.
                if self.rewriting is watched and event.buttons() & self.LEFT:
                    return self.resend(watched, event)
                return False
            if event.button() != self.LEFT:
                return False
            if kind == QtCore.QEvent.MouseButtonPress:
                self.rewriting = None
                if event.modifiers() != QtCore.Qt.NoModifier or self.native_owned():
                    return False
                point = event.position() if hasattr(event, "position") else event.pos()
                if not picks_geometry(self.hit(watched, point)):
                    return False  # empty space: the native plain click clears
                self.rewriting = watched
                self.rewritten += 1
                return self.resend(watched, event)
            if self.rewriting is watched:
                if kind == QtCore.QEvent.MouseButtonRelease:
                    self.rewriting = None
                return self.resend(watched, event)
            if kind == QtCore.QEvent.MouseButtonDblClick and event.modifiers() == QtCore.Qt.NoModifier \
                    and not self.native_owned() and picks_geometry(
                        self.hit(watched, event.position() if hasattr(event, "position") else event.pos())):
                # Qt delivers press, release, double-click, release: keep the second click a toggle too.
                self.rewriting = watched
                return self.resend(watched, event)
            return False

        def shutdown(self):
            QtGui.QApplication.instance().removeEventFilter(self)

    controller = AdditiveSelection()
    QtGui.QApplication.instance().installEventFilter(controller)
    return controller
