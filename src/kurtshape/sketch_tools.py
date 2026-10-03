"""Keep native line creation active without changing the user's preferences."""
from __future__ import annotations

PERSISTENT_LINE_COMMANDS = frozenset({'Sketcher_CreateLine', 'Sketcher_CreatePolyline'})


def run_command(command):
    """Activate native line handlers with continuous creation enabled.

    Sketcher snapshots this preference when activating its handler. Restore the
    stored value afterwards so other tools and a user's native FreeCAD setup
    retain their chosen behavior. The handler still ends normally on Escape or
    right-click, and all geometry stays inside the existing sketch edit lease.
    """
    import FreeCAD as App
    import FreeCADGui as Gui
    if command not in PERSISTENT_LINE_COMMANDS:
        Gui.runCommand(command)
        return
    prefs = App.ParamGet('User parameter:BaseApp/Preferences/Mod/Sketcher')
    original = next((value for kind, key, value in prefs.GetContents()
                     if kind == 'Boolean' and key == 'ContinuousCreationMode'), None)
    prefs.SetBool('ContinuousCreationMode', True)
    try:
        Gui.runCommand(command)
    finally:
        if original is None:
            prefs.RemBool('ContinuousCreationMode')
        else:
            prefs.SetBool('ContinuousCreationMode', original)
