"""KurtShape's name, version, window icon, title and loading screen in place of FreeCAD's.

Two entry points:

* ``configure_startup`` runs from ``resources/freecad/KurtShapeBranding/Init.py`` while FreeCAD
  initialises, before it builds any window. It points FreeCAD's own start-up settings at the KurtShape
  icon and loading screen. ``launch-kurtshape.ps1`` passes that folder with ``--module-path``.
* ``apply_window_branding`` runs from the same module's ``InitGui.py`` (main window built, not shown
  yet) and again from ``ui.start``. It sets the icon and keeps the title bar reading
  ``<document> — KurtShape <version>``.

Importing this module needs neither FreeCAD nor Qt.
"""
from __future__ import annotations

from pathlib import Path

from .contract import CONTRACT_REVISION, CONTRACT_VERSION

APP_NAME = "KurtShape"
# The one version KurtShape publishes: the assistant contract (capabilities.contract / contract_revision).
VERSION = str(CONTRACT_VERSION) + "." + str(CONTRACT_REVISION)
ROOT = Path(__file__).resolve().parents[2]
ICON = ROOT / "resources" / "icons" / "kurtshape-dodecahedron.ico"
ICON_IMAGE = ICON.with_suffix(".png")
# FreeCAD looks this name up in its icon folders and adds "_2x" on a scaled display.
SPLASH_NAME = "kurtshape-splash"
SPLASH_FOLDER = "branding"
# FreeCAD lists every string under Preferences/Bitmaps whose name contains "CustomPath" as an icon folder.
ICON_FOLDER_PARAMETER = "CustomPathKurtShapeBranding"
INVISIBLE = "#00000000"

_title_keeper = None


def window_title(document_name=None):
    """Title bar text: the open document, then the application and its version."""
    application = APP_NAME + " " + VERSION
    name = str(document_name or "").strip()
    return name + " — " + application if name else application


def configure_startup(app, session_directory):
    """Point FreeCAD's start-up settings at KurtShape's icon and loading screen.

    ``app`` is the FreeCAD module. The loading screen is drawn into the session folder the first
    time, and again when the version or engine changes. A failure to draw it leaves FreeCAD's own
    loading screen in place; the icon is set either way.
    """
    app.ConfigSet("WindowIcon", ICON.as_posix())
    from .splash import ensure_splash
    folder = ensure_splash(Path(session_directory) / SPLASH_FOLDER, VERSION, app.ConfigGet("ExeVersion"), ICON_IMAGE)
    app.ParamGet("User parameter:BaseApp/Preferences/Bitmaps").SetString(ICON_FOLDER_PARAMETER, str(folder))
    app.ConfigSet("SplashScreen", SPLASH_NAME)
    # The image carries its own name and version: make FreeCAD's overlay text invisible.
    app.ConfigSet("SplashInfoColor", INVISIBLE)
    app.ConfigSet("SplashWarningColor", INVISIBLE)
    return folder


def apply_window_branding(main):
    """Give the application and its main window KurtShape's icon and title. Safe to repeat."""
    from PySide import QtGui
    icon = QtGui.QIcon(str(ICON))
    if not icon.isNull():
        QtGui.QApplication.instance().setWindowIcon(icon)
        main.setWindowIcon(icon)
    return _keeper(main)


def set_document_title(main, document_name):
    """Show ``document_name`` in the title bar and keep it there."""
    _keeper(main).set_document(document_name)


def _keeper(main):
    global _title_keeper
    if _title_keeper is None or _title_keeper.window is not main:
        _title_keeper = _keeper_class()(main)
    return _title_keeper


def _keeper_class():
    from PySide import QtCore

    class TitleKeeper(QtCore.QObject):
        """Restores KurtShape's title whenever FreeCAD rewrites it.

        FreeCAD's main window writes "<view> - FreeCAD <version>" each time the active view changes.
        Setting the title from Python reaches QWidget.setWindowTitle directly, so the text set here
        is shown as written.
        """

        def __init__(self, window):
            super().__init__(window)
            self.window = window
            self.title = window_title()
            window.installEventFilter(self)
            self.apply()

        def set_document(self, document_name):
            self.title = window_title(document_name)
            self.apply()

        def apply(self):
            if self.window.windowTitle() != self.title:
                self.window.setWindowTitle(self.title)

        def eventFilter(self, watched, event):
            if event.type() == QtCore.QEvent.WindowTitleChange:
                self.apply()
            return False

    return TitleKeeper
