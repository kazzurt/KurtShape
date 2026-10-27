"""The live measurement readout in the status area (assembly UX item 6).

A right-aligned label of its own (object name ``KurtShapeMeasure``), so
``Panel.notify`` messages never overwrite it. Selection changes schedule one
update after ~80 ms; the geometry is ``measure_readout`` (no Qt there).
"""
from __future__ import annotations

from PySide import QtCore, QtGui

from . import measure_readout

DEBOUNCE_MS = 80
MAX_ELEMENTS = 24


def selection_entries(doc):
    """(object, subelement) pairs of the document's selection; a whole object has subelement ""."""
    import FreeCADGui as Gui
    entries = []
    for entry in Gui.Selection.getSelectionEx(doc.Name):
        for sub in entry.SubElementNames or ("",):
            entries.append((entry.Object, sub))
    return entries


class MeasureLabel:
    def __init__(self, panel):
        self.panel = panel
        self.closed = False
        self.result = None
        self.updates = 0
        self.label = QtGui.QLabel("")
        self.label.setObjectName("KurtShapeMeasure")
        self.label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.label.setToolTip("Measurement of the current selection (global coordinates)")
        panel.main.statusBar().addPermanentWidget(self.label)
        self.timer = QtCore.QTimer(panel)
        self.timer.setSingleShot(True)
        self.timer.setInterval(DEBOUNCE_MS)
        self.timer.timeout.connect(self.update)

    def schedule(self):
        if not self.closed:
            self.timer.start()

    def allowed(self):
        p = self.panel
        return bool(not self.closed and p.state and not p.core.busy and not p.active_sketch())

    def update(self):
        self.updates += 1
        doc = self.panel.document() if self.allowed() else None
        result = None
        if doc is not None:
            entries = selection_entries(doc)
            if 0 < len(entries) <= MAX_ELEMENTS:
                try:
                    result = measure_readout.measure_selection(entries)
                except Exception:  # an element the kernel cannot measure: show nothing rather than fail
                    result = None
        self.result = result
        text = result["text"] if result else ""
        if self.label.text() != text:
            self.label.setText(text)

    def close(self):
        self.timer.stop()
        self.closed = True
