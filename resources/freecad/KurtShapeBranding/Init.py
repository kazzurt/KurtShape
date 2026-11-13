# FreeCAD runs this while it initialises, before it builds any window: launch-kurtshape.ps1 passes this
# folder with --module-path. It points FreeCAD's start-up icon and loading screen at KurtShape's
# (src/kurtshape/branding.py). FreeCAD executes the file with separate global and local names, so the
# work is in one function that receives what it needs as defaults.
import os
import sys

import FreeCAD


def _configure(os=os, sys=sys, FreeCAD=FreeCAD):
    root = os.environ.get("KURTSHAPE_ROOT")
    if not root:
        return
    source = os.path.join(root, "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    try:
        from kurtshape import branding
        branding.configure_startup(FreeCAD, os.environ.get("KURTSHAPE_SESSION_DIR") or os.path.join(root, "runtime"))
    except Exception as error:  # start-up continues with FreeCAD's own loading screen
        FreeCAD.Console.PrintWarning("KurtShape start-up branding was not applied: " + repr(error) + "\n")


_configure()
