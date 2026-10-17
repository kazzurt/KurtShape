"""Icon audit script from the Fable deep review (2026-10-17). Run from the repository root with the bundled
runtime: runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\pythonw.exe -B <this file>, with
QT_QPA_PLATFORM=offscreen and an isolated FREECAD_USER_HOME/APPDATA/LOCALAPPDATA/TEMP (native_gray.py opens an
offscreen FreeCADGui main window). Outputs land beside the script.
"""
"""Render native FreeCAD command icons in color and through KurtShape's grayscale_icon(), beside originals.
Offscreen FreeCADGui main window in an isolated profile. No document is saved; nothing in the repository is written.
"""
import sys, os, json, traceback
sys.dont_write_bytecode = True
ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[4])
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE
os.makedirs(OUT, exist_ok=True)
BIN = os.path.join(ROOT, "runtime", "freecad-1.1.4", "FreeCAD_1.1.4-Windows-x86_64-py311", "bin")
sys.path.insert(0, BIN)
sys.path.insert(0, os.path.join(os.path.dirname(BIN), "Ext"))
sys.path.insert(0, os.path.join(BIN, "Lib", "site-packages"))
sys.path.insert(0, os.path.join(ROOT, "src"))
log = open(os.path.join(OUT, "native_gray.log"), "w", encoding="utf-8")


def say(*a):
    print(*a, file=log)
    log.flush()


try:
    import FreeCAD as App
    import FreeCADGui as Gui
    say("FreeCAD", App.Version()[:3])
    Gui.showMainWindow()
    from PySide import QtCore, QtGui, QtWidgets
    app = QtWidgets.QApplication.instance()
    say("app", app is not None, QtCore.qVersion(), "dpr", app.devicePixelRatio())
    app.setStyle("Fusion")
    for _f in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + _f)
    for wb in ("PartDesignWorkbench", "SketcherWorkbench", "PartWorkbench"):
        try:
            Gui.activateWorkbench(wb)
            say("activated", wb)
        except Exception as exc:
            say("workbench failed", wb, exc)
    from kurtshape import presentation_icons as PI, feature_tools as FT
    from pathlib import Path
    ICONS = Path(ROOT, "resources", "icons")
    # (label, command, original-for-comparison)
    probes = [
        ("Use", "Sketcher_Projection", "pierce"), ("Hole", "PartDesign_Hole", "remove"), ("Helical sweep", "PartDesign_AdditiveHelix", "sweep"),
        ("Additive primitives", "PartDesign_CompPrimitiveAdditive", "extrude"), ("Shape binder", "PartDesign_ShapeBinder", "plane"),
        ("Offset surface", "Part_Offset", "shell"), ("Intersect shapes", "Part_Section", "boolean"),
        ("Coincident", "Sketcher_ConstrainCoincident", "point"), ("Tangent", "Sketcher_ConstrainTangent", "arc"),
        ("Horizontal", "Sketcher_ConstrainHorizontal", "line"), ("Equal", "Sketcher_ConstrainEqual", "dimension"),
        ("Slot", "Sketcher_CreateSlot", "rectangle"), ("Regular polygon", "Sketcher_CreateRegularPolygon", "circle"),
        ("Center rectangle", "Sketcher_CreateRectangle_Center", "rectangle"), ("Extend", "Sketcher_Extend", "trim"),
        ("Mirror geometry", "Sketcher_Symmetry", "mirror"), ("Sketch fillet", "Sketcher_CreateFillet", "fillet"),
        ("Pad (history)", "PartDesign_Pad", "extrude"), ("Pocket (history)", "PartDesign_Pocket", "remove"),
        ("Fillet (history)", "PartDesign_Fillet", "fillet"), ("Sketch (history)", "Sketcher_NewSketch", "sketch"),
        ("Body (parts)", "PartDesign_Body", "isometric"), ("Part Extrude (history)", "Part_Extrude", "extrude"),
    ]
    results = []

    def ink(pm):
        img = pm.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        total = 0.0
        cover = 0
        for y in range(img.height()):
            for x in range(img.width()):
                px = img.pixel(x, y)
                a = QtGui.qAlpha(px) / 255.0
                if a > 0.05:
                    cover += 1
                    gray = (QtGui.qRed(px) * 299 + QtGui.qGreen(px) * 587 + QtGui.qBlue(px) * 114) / 1000.0
                    total += a * (1 - gray / 255.0)
        n = img.width() * img.height()
        return round(total / n, 3), round(cover / n, 3)

    def original(name, size):
        return QtGui.QIcon(str(ICONS / (name + ".svg"))).pixmap(QtCore.QSize(size, size))

    cell_h = 60
    sheet = QtGui.QImage(900, 40 + cell_h * len(probes), QtGui.QImage.Format_ARGB32)
    sheet.fill(QtGui.QColor("#f5f6f7"))
    p = QtGui.QPainter(sheet)
    p.setFont(QtGui.QFont("Segoe UI", 9))
    p.setPen(QtGui.QColor("#2d3338"))
    p.drawText(6, 18, "native color 20 | KurtShape grayscale_icon 20 | gray disabled 20 | gray 40 | original comparator 20 | original 40   (ink = alpha-weighted darkness)")
    for i, (label, cmd, comp) in enumerate(probes):
        cy = 40 + i * cell_h
        native = PI._command_native(cmd)
        if native is None or native.isNull():
            try:
                native = Gui.getIcon(FT._NATIVE_PIXMAPS.get(cmd, cmd))
            except Exception as exc:
                say("getIcon failed", cmd, exc)
                native = None
        if native is None or native.isNull():
            p.drawText(6, cy + 24, label + " | " + cmd + " | NO NATIVE ICON")
            results.append({"label": label, "command": cmd, "native": False})
            continue
        gray = PI.grayscale_icon(native)
        color20 = native.pixmap(QtCore.QSize(20, 20))
        gray20 = gray.pixmap(QtCore.QSize(20, 20))
        gray20d = gray.pixmap(QtCore.QSize(20, 20), QtGui.QIcon.Disabled)
        gray40 = gray.pixmap(QtCore.QSize(40, 40))
        o20, o40 = original(comp, 20), original(comp, 40)
        gi, gc = ink(gray20)
        oi, oc = ink(o20)
        ci, cc = ink(color20)
        results.append({"label": label, "command": cmd, "native": True, "gray_ink": gi, "gray_cover": gc,
                        "original": comp, "original_ink": oi, "original_cover": oc, "color_ink": ci,
                        "sizes": [s.width() for s in gray.availableSizes()]})
        p.drawText(6, cy + 24, label[:22])
        p.drawText(6, cy + 40, "gray ink %.3f  vs %s ink %.3f" % (gi, comp, oi))
        x = 280
        p.drawPixmap(x, cy + 16, color20); x += 40
        p.drawPixmap(x, cy + 16, gray20); x += 40
        p.drawPixmap(x, cy + 16, gray20d); x += 40
        p.drawPixmap(x, cy + 6, gray40); x += 60
        p.drawPixmap(x, cy + 16, o20); x += 40
        p.drawPixmap(x, cy + 6, o40)
    p.end()
    sheet.save(os.path.join(OUT, "native_gray_vs_original.png"))
    sheet.scaled(sheet.width() * 2, sheet.height() * 2, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.FastTransformation).save(os.path.join(OUT, "native_gray_vs_original_2x.png"))
    json.dump(results, open(os.path.join(OUT, "native_gray_metrics.json"), "w"), indent=1)
    # Which catalog commands actually fall back at runtime (installed command set)
    catalog = FT.available_catalog()
    runtime_rows = []
    for tool in catalog["all"]:
        name = PI.original_icon_name(tool.label, tool.command)
        runtime_rows.append({"label": tool.label, "command": tool.command, "category": tool.category, "original": name})
    json.dump(runtime_rows, open(os.path.join(OUT, "runtime_catalog_icon_resolution.json"), "w"), indent=1)
    say("installed catalog tools", len(catalog["all"]), "fallback", sum(1 for r in runtime_rows if not r["original"]))
    say("done")
except Exception:
    traceback.print_exc(file=log)
log.close()
os._exit(0)
