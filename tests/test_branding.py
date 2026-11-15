"""KurtShape's own icon, title bar and loading screen (src/kurtshape/branding.py, splash.py).

Nothing here starts FreeCAD's GUI. The start-up hook is exercised with a stand-in FreeCAD module, the
title keeper with an offscreen Qt main window, and the launcher only through ``-PrintOnly``.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape import branding, splash
from kurtshape.contract import CONTRACT_REVISION, CONTRACT_VERSION

MODULE = ROOT / "resources" / "freecad" / "KurtShapeBranding"
LAUNCHER = ROOT / "launch-kurtshape.ps1"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
POWERSHELL = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden"]


class FakeParameters:
    def __init__(self):
        self.strings = {}

    def SetString(self, name, value):
        self.strings[name] = value


class FakeApp:
    """The part of the FreeCAD module the start-up hook uses."""

    def __init__(self):
        self.config = {"ExeVersion": "1.1.4", "SplashScreen": "freecadsplash", "SplashInfoColor": "#000000"}
        self.groups = {}

    def ConfigGet(self, key):
        return self.config.get(key, "")

    def ConfigSet(self, key, value):
        self.config[key] = value

    def ParamGet(self, path):
        return self.groups.setdefault(path, FakeParameters())


class BrandingTests(unittest.TestCase):
    def test_title_names_the_document_then_kurtshape_and_its_version(self):
        version = str(CONTRACT_VERSION) + "." + str(CONTRACT_REVISION)
        self.assertEqual(branding.VERSION, version)
        self.assertEqual(branding.window_title(), "KurtShape " + version + "[*]")
        self.assertEqual(branding.window_title("  "), "KurtShape " + version + "[*]")
        self.assertEqual(branding.window_title("femur-tracking-array"),
                         "femur-tracking-array[*] — KurtShape " + version)
        self.assertNotIn("FreeCAD", branding.window_title("part"))

    def test_icon_assets_exist(self):
        self.assertTrue(branding.ICON.is_file())
        self.assertTrue(branding.ICON_IMAGE.is_file())

    def test_splash_is_drawn_once_per_version_at_both_scales(self):
        from PIL import Image
        folder = support.scratch(self, "branding-splash-") / "branding"
        self.assertEqual(splash.ensure_splash(folder, "3.2", "1.1.4", branding.ICON_IMAGE), folder)
        small, large = folder / "kurtshape-splash.png", folder / "kurtshape-splash_2x.png"
        with Image.open(small) as image:
            self.assertEqual((image.size, image.mode), ((splash.WIDTH, splash.HEIGHT), "RGBA"))
            # Rounded card: the corners are transparent, the middle is opaque.
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertEqual(image.getpixel((splash.WIDTH // 2, splash.HEIGHT // 2))[3], 255)
        with Image.open(large) as image:
            self.assertEqual(image.size, (splash.WIDTH * 2, splash.HEIGHT * 2))
        self.assertEqual(json.loads((folder / "splash.json").read_text(encoding="utf-8")),
                         {"generator": splash.GENERATOR, "version": "3.2", "engine": "1.1.4"})
        written = (small.stat().st_mtime_ns, large.stat().st_mtime_ns)
        with patch.object(splash, "render", side_effect=AssertionError("a current splash was redrawn")):
            splash.ensure_splash(folder, "3.2", "1.1.4", branding.ICON_IMAGE)
        self.assertEqual((small.stat().st_mtime_ns, large.stat().st_mtime_ns), written)
        # A new version, or a missing file, draws again.
        before = small.read_bytes()
        splash.ensure_splash(folder, "3.3", "1.1.4", branding.ICON_IMAGE)
        self.assertNotEqual(small.read_bytes(), before)
        large.unlink()
        splash.ensure_splash(folder, "3.3", "1.1.4", branding.ICON_IMAGE)
        self.assertTrue(large.is_file())
        self.assertEqual([path.name for path in folder.glob("*.writing.png")], [])

    def test_startup_hook_points_freecad_at_the_kurtshape_icon_and_splash(self):
        session = support.scratch(self, "branding-startup-")
        app = FakeApp()
        folder = branding.configure_startup(app, session)
        self.assertEqual(folder, session / branding.SPLASH_FOLDER)
        self.assertTrue((folder / (branding.SPLASH_NAME + ".png")).is_file())
        self.assertTrue((folder / (branding.SPLASH_NAME + "_2x.png")).is_file())
        self.assertEqual(Path(app.config["WindowIcon"]), branding.ICON)
        # A bare name: FreeCAD resolves it in its icon folders and chooses the _2x file on a scaled display.
        self.assertEqual(app.config["SplashScreen"], branding.SPLASH_NAME)
        self.assertEqual(app.config["SplashInfoColor"], "#00000000")
        self.assertEqual(app.config["SplashWarningColor"], "#00000000")
        bitmaps = app.groups["User parameter:BaseApp/Preferences/Bitmaps"].strings
        self.assertEqual(bitmaps, {branding.ICON_FOLDER_PARAMETER: str(folder)})
        self.assertIn("CustomPath", branding.ICON_FOLDER_PARAMETER)

    def test_startup_hook_sets_the_icon_even_when_the_splash_cannot_be_drawn(self):
        app = FakeApp()
        with patch.object(splash, "ensure_splash", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                branding.configure_startup(app, support.scratch(self, "branding-failed-"))
        self.assertEqual(Path(app.config["WindowIcon"]), branding.ICON)
        self.assertEqual(app.config["SplashScreen"], "freecadsplash")
        self.assertEqual(app.config["SplashInfoColor"], "#000000")

    def test_module_files_run_the_way_freecad_executes_them(self):
        """FreeCAD execs Init.py / InitGui.py with separate globals and locals; module-level names are
        then invisible inside comprehensions and nested functions unless bound as defaults."""
        calls = []
        freecad = types.ModuleType("FreeCAD")
        freecad.Console = types.SimpleNamespace(PrintWarning=calls.append)
        freecad_gui = types.ModuleType("FreeCADGui")
        freecad_gui.getMainWindow = lambda: "main-window"
        stand_in = types.SimpleNamespace(configure_startup=lambda app, session: calls.append(("startup", app, session)),
                                         apply_window_branding=lambda main: calls.append(("window", main)))
        session = str(support.scratch(self, "branding-module-"))
        with patch.dict(sys.modules, {"FreeCAD": freecad, "FreeCADGui": freecad_gui}), \
                patch.dict(os.environ, {"KURTSHAPE_ROOT": str(ROOT), "KURTSHAPE_SESSION_DIR": session}), \
                patch.object(sys, "path", list(sys.path)), \
                patch("kurtshape.branding.configure_startup", stand_in.configure_startup), \
                patch("kurtshape.branding.apply_window_branding", stand_in.apply_window_branding):
            for name in ("Init.py", "InitGui.py"):
                source = (MODULE / name).read_text(encoding="utf-8")
                exec(compile(source, str(MODULE / name), "exec"), {"__name__": "__main__"}, {})
        self.assertEqual(calls, [("startup", freecad, session), ("window", "main-window")])
        # Without KURTSHAPE_ROOT (a plain FreeCAD given this module path) the files do nothing.
        calls.clear()
        environment = {key: value for key, value in os.environ.items() if key != "KURTSHAPE_ROOT"}
        with patch.dict(sys.modules, {"FreeCAD": freecad, "FreeCADGui": freecad_gui}), \
                patch.dict(os.environ, environment, clear=True):
            for name in ("Init.py", "InitGui.py"):
                exec(compile((MODULE / name).read_text(encoding="utf-8"), name, "exec"), {"__name__": "__main__"}, {})
        self.assertEqual(calls, [])

    def test_module_reports_a_failure_instead_of_stopping_startup(self):
        warnings = []
        freecad = types.ModuleType("FreeCAD")
        freecad.Console = types.SimpleNamespace(PrintWarning=warnings.append)

        def fail(app, session):
            raise RuntimeError("no Pillow")

        with patch.dict(sys.modules, {"FreeCAD": freecad}), \
                patch.dict(os.environ, {"KURTSHAPE_ROOT": str(ROOT)}), \
                patch.object(sys, "path", list(sys.path)), \
                patch("kurtshape.branding.configure_startup", fail):
            exec(compile((MODULE / "Init.py").read_text(encoding="utf-8"), "Init.py", "exec"), {"__name__": "__main__"}, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("no Pillow", warnings[0])

    def test_launcher_passes_the_branding_module_to_freecad(self):
        empty = support.scratch(self, "branding-launcher-")
        result = subprocess.run(POWERSHELL + ["-File", str(LAUNCHER), "-PrintOnly", "-RuntimeRoot", str(empty),
                                              "-SessionRoot", str(empty)], cwd=str(ROOT), capture_output=True,
                                text=True, creationflags=NO_WINDOW, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        arguments = json.loads(result.stdout)["arguments"]
        self.assertIn("--module-path", arguments)
        folder = Path(arguments[arguments.index("--module-path") + 1].strip('"'))
        self.assertEqual(folder, MODULE)
        self.assertTrue((folder / "Init.py").is_file())
        self.assertTrue((folder / "InitGui.py").is_file())
        # The macro stays the last argument: FreeCAD opens trailing file arguments.
        self.assertTrue(arguments[-1].strip('"').endswith("KurtShape.FCMacro"))

    def test_title_and_icon_survive_freecad_rewriting_the_title(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import FreeCAD  # noqa: F401  # provides the bundled PySide compatibility module
        from PySide import QtGui
        app = QtGui.QApplication.instance() or QtGui.QApplication([])
        previous_icon = QtGui.QIcon(app.windowIcon())
        self.addCleanup(app.setWindowIcon, previous_icon)
        self.addCleanup(setattr, branding, "_title_keeper", branding._title_keeper)
        main = QtGui.QMainWindow()
        self.addCleanup(main.deleteLater)
        main.setWindowTitle("FreeCAD 1.1.4")
        keeper = branding.apply_window_branding(main)
        version = branding.VERSION
        self.assertEqual(main.windowTitle(), "KurtShape " + version + "[*]")
        self.assertFalse(main.windowIcon().isNull())
        self.assertEqual(main.windowIcon().pixmap(32, 32).toImage(),
                         QtGui.QIcon(str(branding.ICON)).pixmap(32, 32).toImage())
        self.assertIs(branding.apply_window_branding(main), keeper)
        branding.set_document_title(main, "bracket")
        self.assertEqual(main.windowTitle(), "bracket[*] — KurtShape " + version)
        # What FreeCAD's main window does when the active view changes.
        main.setWindowTitle("[*] bracket - FreeCAD 1.1.4")
        self.assertEqual(main.windowTitle(), "bracket[*] — KurtShape " + version)
        branding.set_document_title(main, "housing")
        main.setWindowTitle("FreeCAD 1.1.4")
        self.assertEqual(main.windowTitle(), "housing[*] — KurtShape " + version)
        # A different main window gets its own keeper.
        other = QtGui.QMainWindow()
        self.addCleanup(other.deleteLater)
        self.assertIsNot(branding.apply_window_branding(other), keeper)
        self.assertEqual(other.windowTitle(), "KurtShape " + version + "[*]")

    def test_title_keeps_qt_modified_placeholder_without_native_warnings(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import FreeCAD  # noqa: F401
        from PySide import QtCore, QtGui
        app = QtGui.QApplication.instance() or QtGui.QApplication([])
        self.addCleanup(setattr, branding, "_title_keeper", branding._title_keeper)
        main = QtGui.QMainWindow()
        self.addCleanup(main.deleteLater)
        messages = []
        previous_handler = QtCore.qInstallMessageHandler(lambda kind, context, text: messages.append(text))
        try:
            branding.apply_window_branding(main)
            for name in ("bracket", "", "housing"):
                branding.set_document_title(main, name)
                self.assertIn("[*]", main.windowTitle())
                for modified in (True, False, True):
                    main.setWindowModified(modified)
                    main.setWindowTitle("[*] native title - FreeCAD 1.1.4")
                    app.processEvents()
                    self.assertIn("[*]", main.windowTitle())
                    self.assertEqual(main.isWindowModified(), modified)
                    self.assertIn("KurtShape " + branding.VERSION, main.windowTitle())
            self.assertFalse([text for text in messages if "QWidget::setWindowModified" in text], messages)
        finally:
            QtCore.qInstallMessageHandler(previous_handler)


if __name__ == "__main__":
    unittest.main()
