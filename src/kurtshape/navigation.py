"""Native SolidWorks navigation and view-independent sketch coordinates.

The built-in navigation class handles orbit/pan/zoom in both modeling and
Sketcher edit mode.  Only double-middle fit needs a Qt supplement.
"""
from __future__ import annotations

import math
import FreeCAD as App

SOLIDWORKS_STYLE = 'Gui::SolidWorksNavigationStyle'
NAVIGATION_STYLES = (
    ('SolidWorks', SOLIDWORKS_STYLE), ('CAD', 'Gui::CADNavigationStyle'),
    ('Blender', 'Gui::BlenderNavigationStyle'), ('Gesture', 'Gui::GestureNavigationStyle'),
    ('Maya', 'Gui::MayaGestureNavigationStyle'), ('OpenCascade', 'Gui::OpenCascadeNavigationStyle'),
    ('Inventor', 'Gui::InventorNavigationStyle'), ('OpenSCAD', 'Gui::OpenSCADNavigationStyle'),
    ('Revit', 'Gui::RevitNavigationStyle'), ('Siemens NX', 'Gui::SiemensNXNavigationStyle'),
    ('TinkerCAD', 'Gui::TinkerCADNavigationStyle'), ('Touchpad', 'Gui::TouchpadNavigationStyle'),
)
_double_middle_filter = None


def selected_style():
    configured = App.ParamGet('User parameter:KurtShape/Preferences').GetString('NavigationStyle', SOLIDWORKS_STYLE)
    return configured if configured in {style for _, style in NAVIGATION_STYLES} else SOLIDWORKS_STYLE


def set_navigation_style(style):
    if style not in {value for _, value in NAVIGATION_STYLES}:
        raise ValueError('Choose a supported mouse navigation style')
    import FreeCADGui as Gui
    settings = App.ParamGet('User parameter:KurtShape/Preferences')
    previous = selected_style()
    views = [Gui.getDocument(name).activeView() for name in App.listDocuments() if Gui.getDocument(name)]
    previous_views = [(view, view.getNavigationType()) for view in views]
    settings.SetString('NavigationStyle', style)
    try:
        for view in views:
            apply_navigation(view)
        apply_navigation()
        App.saveParameter()
    except Exception:
        settings.SetString('NavigationStyle', previous)
        App.ParamGet('User parameter:BaseApp/Preferences/View').SetString('NavigationStyle', previous)
        for view, old_style in previous_views:
            view.setNavigationType(old_style)
        raise


def _active_view(view=None):
    if view is not None:
        return view
    import FreeCADGui as Gui
    document = Gui.activeDocument()
    return document.activeView() if document else None


def apply_navigation(view=None):
    """Apply the user's style, defaulting to verified SolidWorks controls.

    Wheel forward zooms out, as in default SolidWorks.  Rotation uses a
    picked scene point, falling back to the window focal plane on empty space.
    Safe before a document exists; call again for each new/opened native view.
    """
    prefs = App.ParamGet('User parameter:BaseApp/Preferences/View')
    style = selected_style()
    flags = [('UseNavigationAnimations', False, True), ('UseSpinningAnimations', False, False)]
    if style == SOLIDWORKS_STYLE:
        flags.extend([('InvertZoom', False, True), ('ZoomAtCursor', True, True)])
    for key, value, default in flags:
        if prefs.GetBool(key, default) != value:
            prefs.SetBool(key, value)
    if style == SOLIDWORKS_STYLE and prefs.GetInt('RotationMode', 0) != 1:
        prefs.SetInt('RotationMode', 1)
    # Native styles read some navigation preferences when instantiated.
    if prefs.GetString('NavigationStyle', '') != style:
        prefs.SetString('NavigationStyle', style)
    allow_sketch_3d()
    view = _active_view(view)
    if view is not None:
        if view.getNavigationType() != style:
            view.setNavigationType(style)
        if view.getNavigationType() != style:
            raise RuntimeError('The chosen mouse navigation style is unavailable.')
    _install_double_middle_fit()
    return style


def _install_double_middle_fit():
    global _double_middle_filter
    if _double_middle_filter is not None:
        return
    from PySide import QtCore, QtGui
    import FreeCADGui as Gui

    class DoubleMiddleFit(QtCore.QObject):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.suppress_release = None

        def eventFilter(self, watched, event):
            if selected_style() != SOLIDWORKS_STYLE:
                self.suppress_release = None
                return False
            event_type = event.type()
            if event_type not in (QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseButtonRelease):
                return False
            if event.button() != QtCore.Qt.MiddleButton:
                return False
            if event_type == QtCore.QEvent.MouseButtonRelease and watched is self.suppress_release:
                self.suppress_release = None
                return True
            if event_type != QtCore.QEvent.MouseButtonDblClick or event.modifiers() != QtCore.Qt.NoModifier:
                return False
            if not isinstance(watched, QtGui.QWidget) or watched.metaObject().className() != 'QOpenGLWidget':
                return False
            parent = watched.parentWidget()
            if not parent or parent.metaObject().className() != 'Gui::View3DInventorViewer':
                return False
            # Keep the second press/release out of Coin's pivot-click path.
            self.suppress_release = watched
            view = _active_view()
            if view is not None:
                view.fitAll()
            return True

    _double_middle_filter = DoubleMiddleFit()
    QtGui.QApplication.instance().installEventFilter(_double_middle_filter)


def allow_sketch_3d(sketch=None, view=None, camera=None):
    """Keep model context and the chosen 3D camera during native sketch edits.

    Native Sketcher supports orbit without a separate unlock preference. It
    normally turns the camera normal on entry. Capture view.getCamera() before
    setEdit and pass it here afterwards to retain the previous 3D view. Native
    navigation animation is disabled by apply_navigation for immediate entry.
    """
    preferences = App.ParamGet('User parameter:BaseApp/Preferences/Mod/Sketcher/General')
    for key, default in [('ForceOrtho', True), ('RestoreCamera', True), ('SectionView', False)]:
        if preferences.GetBool(key, default):
            preferences.SetBool(key, False)
    if sketch is not None:
        for key in ('ForceOrtho', 'RestoreCamera', 'SectionView'):
            if key in sketch.ViewObject.PropertiesList and getattr(sketch.ViewObject, key):
                setattr(sketch.ViewObject, key, False)
    view = _active_view(view)
    if camera is not None and view is not None:
        view.setCamera(camera)
    return True


def _placement(sketch_or_placement):
    if hasattr(sketch_or_placement, 'getGlobalPlacement'):
        return sketch_or_placement.getGlobalPlacement()
    return getattr(sketch_or_placement, 'Placement', sketch_or_placement)


def _set_orientation_keeping_focus(view, rotation):
    # Using Coin here keeps size, focal point, and native sketch edit state.
    from pivy import coin
    camera = view.getCameraNode()
    distance = float(camera.focalDistance.getValue())
    position = App.Vector(*camera.position.getValue().getValue())
    old_rotation = view.getCameraOrientation()
    focus = position - old_rotation.multVec(App.Vector(0, 0, distance))
    new_position = focus + rotation.multVec(App.Vector(0, 0, distance))
    camera.orientation.setValue(coin.SbRotation(*rotation.Q))
    camera.position.setValue(new_position.x, new_position.y, new_position.z)
    return True


def normal_to_sketch(sketch, view=None):
    """Look along a sketch's local normal, preserving zoom and edit mode."""
    view = _active_view(view)
    if view is None or sketch is None:
        return False
    return _set_orientation_keeping_focus(view, _placement(sketch).Rotation)


def view_isometric_keep_sketch(view=None):
    """Show a deterministic isometric orientation without leaving Sketcher."""
    view = _active_view(view)
    if view is None:
        return False
    rotation = App.Rotation(App.Vector(1, 1, 0), App.Vector(-1, 1, 2),
                            App.Vector(1, -1, 1), 'ZXY')
    return _set_orientation_keeping_focus(view, rotation)


def intersect_sketch_plane(ray_origin, ray_direction, sketch_or_placement):
    """Return local sketch coordinates for a world ray, or None if edge-on.

    This is an infinite plane intersection: the coordinate stays correct in
    perspective/orthographic cameras, after orbit, and on translated/tilted
    sketch planes. Nearly parallel rays are rejected rather than making huge
    or non-finite sketch geometry.
    """
    placement = _placement(sketch_or_placement)
    values = tuple(ray_origin) + tuple(ray_direction)
    if not all(math.isfinite(value) for value in values):
        return None
    length = ray_direction.Length
    if length <= 1e-15:
        return None
    normal = placement.Rotation.multVec(App.Vector(0, 0, 1))
    denominator = normal.dot(ray_direction)
    if abs(denominator) <= length * 1e-7:
        return None
    distance = normal.dot(placement.Base - ray_origin) / denominator
    world = ray_origin + ray_direction * distance
    local = placement.inverse().multVec(world)
    if not all(math.isfinite(value) for value in local):
        return None
    return App.Vector(local.x, local.y, 0)


def sketch_plane_point(view, position, sketch_or_placement):
    """Project Coin/FreeCAD pixel coordinates onto the sketch plane.

    Coordinates are viewport pixels with bottom-left origin, the convention of
    native addEventCallback and getPointOnViewport. Qt top-left coordinates
    must first be flipped by the viewport height.
    """
    origin, end = view.projectPointToLine(int(position[0]), int(position[1]))
    return intersect_sketch_plane(origin, end - origin, sketch_or_placement)
