"""Original icon presentation; command routing and modeling behavior stay native.

icon_for(label, command=None, native=None) returns a cached QIcon. Descriptive
labels take precedence because Move face and Extrude share PartDesign_Pad.
Unmapped native command icons keep their silhouette, alpha and shading, with
color removed. SVG originals scale natively; raster fallbacks are cached at
20–96px for ordinary and high-DPI toolbar requests.

FreeCAD returns a new QIcon (new cacheKey) on every ViewObject.Icon read, so
grayscale copies are keyed by icon_signature (one small raster's pixel hash)
in a bounded LRU: an unchanged native icon maps to one entry however often it
is read, and the copy handed back keeps one cacheKey between refreshes.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
from pathlib import Path
import re

from PySide import QtCore, QtGui

ICON_ROOT = Path(__file__).resolve().parents[2] / "resources" / "icons"
RASTER_SIZES = (20, 24, 32, 40, 48, 60, 64, 80, 96)
ICON_MODES = (QtGui.QIcon.Normal, QtGui.QIcon.Disabled, QtGui.QIcon.Active, QtGui.QIcon.Selected)
SIGNATURE_SIZE = 32
# About 63 unmapped native command icons (sketch/constraint/Part menus;
# measured headless from feature_tools, not confirmed in the GUI shell) are
# grayed when the shell is built; history rows add a few Body/Part/Link
# variants. 128 holds them all with headroom, so a shell rebuild or refresh
# never re-rasterizes, while the worst case stays near 60 MB (9 sizes x 4
# modes, up to 96px ARGB, ~0.47 MB an entry) and most entries are shared with
# live QActions. The per-entry worst case scales with devicePixelRatio: Qt
# rasterizes scalable icons at size x DPR, so an SVG-backed entry is 2-4x
# larger on a high-DPI screen. Before this bound the dict grew by one entry
# per body per refresh.
NATIVE_CACHE_LIMIT = 128

# Prefer labels over command IDs: several native IDs have contextual meanings.
LABEL_ICONS = {
    "sketch": "sketch", "create sketch": "sketch", "edit sketch": "sketch",
    "extrude": "extrude", "pad": "extrude", "remove": "remove", "extrude remove": "remove",
    "remove material": "remove", "revolve": "revolve", "revolve remove": "groove", "groove": "groove",
    "sweep": "sweep", "sweep remove": "sweep-remove", "loft": "loft", "loft remove": "loft-remove",
    "fillet": "fillet", "chamfer": "chamfer", "shell": "shell", "draft": "draft", "move face": "move-face",
    "linear pattern": "linear-pattern", "linear part pattern": "linear-pattern",
    "circular pattern": "circular-pattern", "circular part pattern": "circular-pattern",
    "mirror": "mirror", "mirror parts": "mirror", "boolean": "boolean", "boolean parts": "boolean",
    "split": "split", "split part": "split", "transform": "transform", "transform / copy part": "transform",
    "multiple transforms": "transform", "plane": "plane", "axis": "axis", "point": "point",
    "coordinate system": "coordinate-system", "undo": "undo", "redo": "redo", "save": "save",
    "document": "document-menu", "document menu": "document-menu", "settings": "settings",
    "search": "search", "search tools": "search", "more": "more", "fit": "fit", "normal": "normal",
    "normal to sketch": "normal", "3d": "isometric", "isometric": "isometric", "isometric view": "isometric",
    "rebuild": "rebuild", "check geometry": "check-geometry", "measure": "measure",
    "show planes": "plane", "confirm": "confirm", "finish": "confirm", "finish sketch": "confirm",
    "cancel": "cancel", "cancel sketch": "cancel", "geometry": "geometry-menu",
    "constraints": "constraints-menu", "edit": "edit-menu", "build": "build-menu", "cut": "cut-menu",
    "modify": "modify-menu", "patterns": "patterns-menu", "reference": "reference-menu",
    "shape tools": "shape-tools-menu", "line": "polyline", "single line": "line", "rectangle": "rectangle",
    "circle": "circle", "arc": "arc", "center arc": "arc", "spline": "spline", "dimension": "dimension",
    "trim": "trim", "construction": "construction", "pierce": "pierce", "new": "new-document",
    "open": "open", "export": "export", "recent": "recent", "example": "example", "adopt copy": "adopt-copy",
    "recovery": "recovery", "shortcuts": "shortcuts", "new part": "new-part",
    "create assembly": "assembly", "insert": "insert", "ground": "ground", "fixed": "fixed-joint",
    "revolute": "revolute-joint", "slider": "slider-joint", "move": "transform", "solve": "rebuild",
    "joints": "fixed-joint", "folder": "folder",
}

COMMAND_ICONS = {
    "Sketcher_NewSketch": "sketch", "PartDesign_Pad": "extrude", "PartDesign_Pocket": "remove",
    "PartDesign_Revolution": "revolve", "PartDesign_Groove": "groove",
    "PartDesign_AdditivePipe": "sweep", "PartDesign_SubtractivePipe": "sweep-remove",
    "PartDesign_AdditiveLoft": "loft", "PartDesign_SubtractiveLoft": "loft-remove",
    "PartDesign_Fillet": "fillet", "PartDesign_Chamfer": "chamfer", "PartDesign_Thickness": "shell",
    "PartDesign_Draft": "draft", "PartDesign_LinearPattern": "linear-pattern",
    "PartDesign_PolarPattern": "circular-pattern", "PartDesign_Mirrored": "mirror",
    "PartDesign_MultiTransform": "transform", "PartDesign_Boolean": "boolean", "Part_Slice": "split",
    "Std_TransformManip": "transform", "PartDesign_Plane": "plane", "PartDesign_Line": "axis",
    "PartDesign_Point": "point", "PartDesign_CoordinateSystem": "coordinate-system",
    "Part_Extrude": "extrude", "Part_Revolve": "revolve", "Part_Sweep": "sweep", "Part_Loft": "loft",
    "Part_Boolean": "boolean", "Part_Thickness": "shell", "Std_Undo": "undo", "Std_Redo": "redo",
    "Std_Save": "save", "Std_ViewFitAll": "fit", "Std_ViewTop": "normal", "Std_ViewIsometric": "isometric",
    "Std_Refresh": "rebuild", "Part_CheckGeometry": "check-geometry",
    "Sketcher_CreatePolyline": "polyline", "Sketcher_CreateLine": "line", "Sketcher_CreateRectangle": "rectangle",
    "Sketcher_CreateCircle": "circle", "Sketcher_Create3PointArc": "arc", "Sketcher_CreateArc": "arc",
    "Sketcher_CreateBSpline": "spline", "Sketcher_CreatePoint": "point", "Sketcher_Dimension": "dimension",
    "Sketcher_Trimming": "trim", "Sketcher_ToggleConstruction": "construction",
    "dialog-ok": "confirm", "dialog-cancel": "cancel", "edit-undo": "undo", "edit-redo": "redo",
}

_original_cache = {}
_native_cache = OrderedDict()


def original_icon_name(label, command=None):
    key=re.sub(r"[\s_]+", " ", str(label or "").strip().casefold())
    return LABEL_ICONS.get(key) or COMMAND_ICONS.get(str(command or ""))


def _original(name):
    if name not in _original_cache:
        _original_cache[name] = QtGui.QIcon(str(ICON_ROOT / (name + ".svg")))
    return QtGui.QIcon(_original_cache[name])


def _gray_image(source):
    # Qt 5's native conversion is fast and alpha is restored explicitly.
    if hasattr(QtGui.QImage, "Format_Grayscale8") and hasattr(QtGui.QImage, "Format_Alpha8"):
        alpha=source.convertToFormat(QtGui.QImage.Format_Alpha8)
        result=source.convertToFormat(QtGui.QImage.Format_Grayscale8).convertToFormat(QtGui.QImage.Format_ARGB32)
        result.setAlphaChannel(alpha)
        return result
    result=source.convertToFormat(QtGui.QImage.Format_ARGB32)
    for y in range(result.height()):
        for x in range(result.width()):
            pixel=result.pixel(x,y)
            gray=(QtGui.qRed(pixel)*299+QtGui.qGreen(pixel)*587+QtGui.qBlue(pixel)*114+500)//1000
            result.setPixel(x,y,QtGui.qRgba(gray,gray,gray,QtGui.qAlpha(pixel)))
    return result


def icon_signature(icon):
    """Stable identity of an icon's pixels, independent of its QIcon object.

    One Normal/Off raster at SIGNATURE_SIZE is hashed with its geometry and
    the pixmap sizes each mode carries; equal images read twice give equal
    signatures. Icons that differ only at other sizes are not told apart. An
    icon with no Normal raster falls back to its per-object cacheKey. Only the
    Normal/Off raster at SIGNATURE_SIZE is hashed, so two icons that differ
    only in a Disabled/Selected/Active pixmap of the same sizes, or only at
    other sizes, share one entry; acceptable because FreeCAD ViewProvider
    icons are single pixmaps.
    """
    if icon is None or icon.isNull():
        return None
    image=icon.pixmap(QtCore.QSize(SIGNATURE_SIZE,SIGNATURE_SIZE),QtGui.QIcon.Normal,QtGui.QIcon.Off).toImage()
    modes=tuple(tuple((size.width(),size.height()) for size in icon.availableSizes(mode,QtGui.QIcon.Off))
                for mode in ICON_MODES)
    if image.isNull():
        return ("object",int(icon.cacheKey()),modes)
    digest=hashlib.blake2b(image.constBits(),digest_size=16).digest()
    return (image.width(),image.height(),image.bytesPerLine(),image.format(),
            float(image.devicePixelRatio()),digest,modes)


def grayscale_icon(native):
    """Preserve an existing QIcon's geometry/alpha at useful DPI resolutions."""
    if native is None or native.isNull():
        return QtGui.QIcon()
    key=icon_signature(native)
    cached=_native_cache.get(key)
    if cached is not None:
        _native_cache.move_to_end(key)
        return QtGui.QIcon(cached)
    result=QtGui.QIcon()
    for mode in ICON_MODES:
        for size in RASTER_SIZES:
            source=native.pixmap(QtCore.QSize(size,size),mode,QtGui.QIcon.Off)
            if source.isNull():
                continue
            gray=QtGui.QPixmap.fromImage(_gray_image(source.toImage()))
            result.addPixmap(gray,mode,QtGui.QIcon.Off)
    _native_cache[key]=result
    while len(_native_cache)>NATIVE_CACHE_LIMIT:
        _native_cache.popitem(last=False)
    return QtGui.QIcon(result)


def _command_native(command):
    if not command:
        return None
    try:
        import FreeCADGui as Gui
        metadata=Gui.Command.get(command).getInfo()
        return Gui.getIcon(metadata["pixmap"]) if metadata.get("pixmap") else None
    except (ImportError, AttributeError, KeyError, RuntimeError):
        return None


def icon_for(label, command=None, native=None):
    """Get original presentation or a grayscale native fallback; always usable.

    Supply the native QIcon from Gui.getIcon when already available. Rare
    unmapped commands without any installed icon use a neutral tools glyph,
    rather than forcing a text-only toolbar button.
    """
    name=original_icon_name(label,command)
    if name:
        icon=_original(name)
        if not icon.isNull():
            return icon
    if native is None or native.isNull():
        native=_command_native(command)
    if native is not None and not native.isNull():
        gray=grayscale_icon(native)
        if not gray.isNull():
            return gray
    return _original("tools")


def clear_cache():
    """Release cached QIcon assets when rebuilding the presentation shell."""
    _original_cache.clear()
    _native_cache.clear()
