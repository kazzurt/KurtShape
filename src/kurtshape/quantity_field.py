"""Unbound native quantities: input is staged until the controller applies it."""
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtGui
from .core import number


class QuantityField(QtGui.QWidget):
    def __init__(self, unit="mm"):
        super().__init__()
        self.unit = unit
        self.native = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        self.native.setProperty("unit", unit)
        layout = QtGui.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.native)
        self.setFocusProxy(self.native)

    def lineEdit(self):
        return self.native.findChild(QtGui.QLineEdit)

    def selectAll(self):
        self.lineEdit().selectAll()

    def setRange(self, low, high):
        self.native.setProperty("minimum", low)
        self.native.setProperty("maximum", high)

    def setDecimals(self, value):
        self.native.setProperty("decimals", value)

    def setSuffix(self, suffix):
        self.unit = suffix.strip()
        self.native.setProperty("unit", self.unit)

    def setValue(self, value):
        self.native.setProperty("value", App.Units.Quantity(f"{value} {self.unit}"))

    def value(self):
        return number(self.lineEdit().text(), "value", unit=self.unit)

    def interpretText(self):
        self.setValue(self.value())
