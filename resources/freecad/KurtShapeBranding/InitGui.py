# FreeCAD runs this once its main window exists and before the window is shown: the title bar and
# taskbar carry KurtShape's icon and name from the first frame (src/kurtshape/branding.py).
import os
import sys

import FreeCAD
import FreeCADGui


def _apply(os=os, sys=sys, FreeCAD=FreeCAD, FreeCADGui=FreeCADGui):
    root = os.environ.get("KURTSHAPE_ROOT")
    if not root:
        return
    source = os.path.join(root, "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    try:
        from kurtshape import branding
        branding.apply_window_branding(FreeCADGui.getMainWindow())
    except Exception as error:  # ui.start applies the same branding again
        FreeCAD.Console.PrintWarning("KurtShape window branding was not applied: " + repr(error) + "\n")


_apply()
