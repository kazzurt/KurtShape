"""Icon audit script from the Fable deep review (2026-10-17). Run from the repository root with the bundled
runtime: runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\pythonw.exe -B <this file>, with
QT_QPA_PLATFORM=offscreen and an isolated FREECAD_USER_HOME/APPDATA/LOCALAPPDATA/TEMP (native_gray.py opens an
offscreen FreeCADGui main window). Outputs land beside the script.
"""
"""Contact sheet of resources/icons/*.svg at 20/40px, Fusion disabled rendering, ink metrics, icon_for mapping.
Read-only against the repository: imports kurtshape modules with bytecode writing disabled.
"""
import sys, os, json, math
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
log = open(os.path.join(OUT, "icons_sheet.log"), "w", encoding="utf-8")


def say(*a):
    print(*a, file=log)
    log.flush()


try:
    from PySide import QtCore, QtGui, QtWidgets
    try:
        from PySide import QtSvg
    except Exception as exc:
        say("QtSvg import failed", exc)
        QtSvg = None
    say("PySide ok", QtCore.qVersion())
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    for _f in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + _f)
    say("formats", [bytes(f).decode() for f in QtGui.QImageReader.supportedImageFormats()])
    from pathlib import Path
    icons = sorted(Path(ROOT, "resources", "icons").glob("*.svg"))
    say("svg count", len(icons))

    def render(path, size, mode=QtGui.QIcon.Normal):
        icon = QtGui.QIcon(str(path))
        pm = icon.pixmap(QtCore.QSize(size, size), mode)
        if pm.isNull() and QtSvg is not None:
            r = QtSvg.QSvgRenderer(str(path))
            img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QtGui.QPainter(img)
            r.render(p)
            p.end()
            pm = QtGui.QPixmap.fromImage(img)
        return pm

    say("QIcon svg engine available:", not QtGui.QIcon(str(icons[0])).pixmap(20, 20).isNull())
    metrics = {}
    for path in icons:
        img = render(path, 20).toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        w, h = img.width(), img.height()
        ink = 0.0
        cover = 0
        minx = miny = 99
        maxx = maxy = -1
        for y in range(h):
            for x in range(w):
                px = img.pixel(x, y)
                a = QtGui.qAlpha(px) / 255.0
                if a > 0.05:
                    cover += 1
                    minx = min(minx, x); maxx = max(maxx, x); miny = min(miny, y); maxy = max(maxy, y)
                    gray = (QtGui.qRed(px) * 299 + QtGui.qGreen(px) * 587 + QtGui.qBlue(px) * 114) / 1000.0
                    ink += a * (1 - gray / 255.0)
        metrics[path.stem] = {"coverage": round(cover / (w * h), 3), "ink": round(ink / (w * h), 3),
                              "bbox": [minx, miny, maxx, maxy], "bbox_w": maxx - minx + 1, "bbox_h": maxy - miny + 1}
    json.dump(metrics, open(os.path.join(OUT, "icon_metrics_20px.json"), "w"), indent=1)
    cols = 4
    cell_w, cell_h = 300, 56
    rows = math.ceil(len(icons) / cols)
    sheet = QtGui.QImage(cols * cell_w, rows * cell_h + 30, QtGui.QImage.Format_ARGB32)
    sheet.fill(QtGui.QColor("#f5f6f7"))
    p = QtGui.QPainter(sheet)
    p.setFont(QtGui.QFont("Segoe UI", 9))
    p.setPen(QtGui.QColor("#2d3338"))
    p.drawText(6, 18, "resources/icons/*.svg - per cell: 20px normal | 20px Fusion-disabled | 20px on hover #edf2f6 | 20px on selection #e6f1fa | 40px  (ink = alpha-weighted darkness at 20px)")
    for i, path in enumerate(icons):
        cx, cy = (i % cols) * cell_w, 30 + (i // cols) * cell_h
        p.drawText(cx + 4, cy + 22, path.stem[:22])
        p.drawText(cx + 4, cy + 40, "ink %.3f cov %.2f" % (metrics[path.stem]["ink"], metrics[path.stem]["coverage"]))
        x = cx + 150
        p.drawPixmap(x, cy + 14, render(path, 20)); x += 28
        p.drawPixmap(x, cy + 14, render(path, 20, QtGui.QIcon.Disabled)); x += 28
        p.fillRect(x - 4, cy + 10, 28, 28, QtGui.QColor("#edf2f6")); p.drawPixmap(x, cy + 14, render(path, 20)); x += 30
        p.fillRect(x - 4, cy + 10, 28, 28, QtGui.QColor("#e6f1fa")); p.drawPixmap(x, cy + 14, render(path, 20)); x += 32
        p.drawPixmap(x, cy + 4, render(path, 40))
    p.end()
    sheet.save(os.path.join(OUT, "icons_contact_sheet.png"))
    grid_cols = 10
    cell = 72
    z = QtGui.QImage(grid_cols * cell, math.ceil(len(icons) / grid_cols) * (cell + 16), QtGui.QImage.Format_ARGB32)
    z.fill(QtGui.QColor("#f5f6f7"))
    p = QtGui.QPainter(z)
    p.setFont(QtGui.QFont("Segoe UI", 7))
    p.setPen(QtGui.QColor("#2d3338"))
    for i, path in enumerate(icons):
        cx, cy = (i % grid_cols) * cell, (i // grid_cols) * (cell + 16)
        pm = render(path, 20).scaled(60, 60, QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation)
        p.drawPixmap(cx + 6, cy + 2, pm)
        p.drawText(cx + 2, cy + cell + 10, path.stem[:14])
    p.end()
    z.save(os.path.join(OUT, "icons_20px_zoom3x.png"))
    order = ["new-part", "sketch", "extrude", "revolve", "sweep", "loft", "fillet", "chamfer", "shell", "draft", "move-face",
             "linear-pattern", "circular-pattern", "mirror", "boolean", "plane", "boolean", "split", "transform", "more",
             "rebuild", "check-geometry", "fit", "normal", "isometric", "plane"]
    sk = ["polyline", "rectangle", "circle", "arc", "spline", "point", "dimension", "trim", "construction", "geometry-menu",
          "constraints-menu", "edit-menu", "pierce", "extrude", "revolve", "normal", "isometric", "confirm", "cancel"]
    strip = QtGui.QImage(30 * max(len(order), len(sk)) + 10, 100, QtGui.QImage.Format_ARGB32)
    strip.fill(QtGui.QColor("#f5f6f7"))
    p = QtGui.QPainter(strip)
    for row, names in enumerate((order, sk)):
        for i, n in enumerate(names):
            p.drawPixmap(5 + i * 30 + 5, 10 + row * 44, render(Path(ROOT, "resources", "icons", n + ".svg"), 20))
    p.end()
    strip.save(os.path.join(OUT, "toolbar_strip_1x.png"))
    strip.scaled(strip.width() * 3, strip.height() * 3, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.FastTransformation).save(os.path.join(OUT, "toolbar_strip_3x.png"))
    from kurtshape import presentation_icons as PI, feature_tools as FT
    rows_out = []
    shell = [("Document menu", None), ("Save", None), ("Help", None), ("Settings", None), ("New part", None), ("Sketch", "Sketcher_NewSketch"),
             ("Extrude", "PartDesign_Pad"), ("Boolean parts", None), ("Split", None), ("Transform", None), ("More", None),
             ("Rebuild", "Std_Refresh"), ("Check geometry", "Part_CheckGeometry"), ("Fit", "Std_ViewFitAll"), ("Normal", "Std_ViewTop"),
             ("3D", "Std_ViewIsometric"), ("Show planes", "PartDesign_Plane"), ("Use", "Sketcher_Projection"), ("Pierce", None),
             ("Finish sketch", None), ("Cancel sketch", None), ("Create Assembly", None), ("Insert", None), ("Ground", None), ("Fixed", None),
             ("Revolute", None), ("Slider", None), ("Move", None), ("Edit", None), ("Solve", None), ("Joints", None), ("Part", None), ("Plane", None),
             ("Recent projects", None), ("Recovery", None), ("Repair leftover helpers", None), ("Undo", None), ("Redo", None)]
    for label, cmd in shell:
        rows_out.append({"where": "shell", "label": label, "command": cmd, "original": PI.original_icon_name(label, cmd)})
    for tool in FT.ALL_TOOLS:
        rows_out.append({"where": tool.category, "label": tool.label, "command": tool.command, "original": PI.original_icon_name(tool.label, tool.command)})
    json.dump(rows_out, open(os.path.join(OUT, "icon_for_resolution.json"), "w"), indent=1)
    fallback = [r for r in rows_out if not r["original"]]
    say("fallback count", len(fallback), "of", len(rows_out))
    for r in fallback:
        say("  FALLBACK", r["where"], "|", r["label"], "|", r["command"])
    dup = {}
    for r in rows_out:
        if r["original"]:
            dup.setdefault(r["original"], []).append(r["label"])
    for k, v in sorted(dup.items()):
        if len(set(v)) > 1:
            say("  SHARED", k, "<-", sorted(set(v)))
    ranked = sorted(metrics.items(), key=lambda kv: kv[1]["ink"])
    say("lightest ink:", [(k, v["ink"]) for k, v in ranked[:8]])
    say("heaviest ink:", [(k, v["ink"]) for k, v in ranked[-8:]])
    say("done")
except Exception:
    import traceback
    traceback.print_exc(file=log)
log.close()
