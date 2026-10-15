"""Edge-only picking while a feature dialog collects edges.

A native selection gate decides both selection and preselection, so faces,
sketches and ineligible parts neither select nor highlight. KurtShape's own
face-boundary hover overlay is suppressed for the same period. Ending the
session always removes the gate and restores ordinary picking.
"""
from __future__ import annotations

from . import hover_outline


def _element(sub):
    return (sub or "").split(".")[-1]


def _target(obj, sub):
    """The object that owns the picked element, for full or resolved paths."""
    if obj is not None and sub and "." in sub:
        try:
            resolved = obj.getSubObject(sub, retType=1)
        except Exception:
            resolved = None
        if resolved is not None:
            return resolved
    return obj


class EdgeGate:
    """Native SelectionGate protocol: allow(document, object, subname)."""

    def __init__(self, document_name, eligible, purpose):
        self.document_name = document_name
        self.eligible = eligible
        self.purpose = purpose
        self.reason = ""
        self.checks = 0

    def allow(self, doc, obj, sub):
        self.checks += 1
        try:
            if doc is None or obj is None or doc.Name != self.document_name:
                self.reason = "Pick edges in the document being edited"
                return False
            element = _element(sub)
            if not element.startswith("Edge"):
                self.reason = "Only edges can be picked for " + self.purpose
                return False
            target = _target(obj, sub)
            message = self.eligible(target)
            if message:
                self.reason = message
                return False
            self.reason = ""
            return True
        except Exception:  # A gate must never raise into native picking.
            self.reason = "This geometry cannot be picked for " + self.purpose
            return False


class EdgePicking:
    """One active edge-only picking session at a time."""

    def __init__(self):
        self.gate = None
        self.feedback = None
        self._filter = None

    @property
    def active(self):
        return self.gate is not None

    def start(self, document, eligible, purpose, feedback=None):
        import FreeCADGui as Gui
        self.end()
        self.gate = EdgeGate(document.Name, eligible, purpose)
        self.feedback = feedback
        Gui.Selection.addSelectionGate(self.gate)
        hover_outline.suppress_faces(True)
        self._install_feedback()
        return self.gate

    def end(self):
        if self.gate is None:
            return False
        import FreeCADGui as Gui
        self.gate = None
        self.feedback = None
        try:
            Gui.Selection.removeSelectionGate()
        finally:
            hover_outline.suppress_faces(False)
            self._remove_feedback()
        return True

    def _install_feedback(self):
        from PySide import QtCore, QtGui
        session = self

        class ClickFeedback(QtCore.QObject):
            """After a viewport click, report why the picked geometry was refused."""
            def eventFilter(self, watched, event):
                if (event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton
                        and isinstance(watched, QtGui.QWidget) and watched.metaObject().className() == "QOpenGLWidget"
                        and session.gate is not None):
                    session.gate.reason = ""
                    QtCore.QTimer.singleShot(0, session._report)
                return False

        self._filter = ClickFeedback()
        QtGui.QApplication.instance().installEventFilter(self._filter)

    def _remove_feedback(self):
        if self._filter is not None:
            from PySide import QtGui
            QtGui.QApplication.instance().removeEventFilter(self._filter)
            self._filter.deleteLater()
            self._filter = None

    def _report(self):
        gate, feedback = self.gate, self.feedback
        if gate is not None and feedback is not None and gate.reason:
            feedback(gate.reason)
