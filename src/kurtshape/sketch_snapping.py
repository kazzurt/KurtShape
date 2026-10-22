"""Scoped native snapping settings for a managed sketch edit.

Sketcher derives coincidence from its native point preselection. Nearby curves
can win native ray picking over origin, endpoint and center markers. Give the
original native markers pick priority and retain Sketcher's own constraint
creation; no proxy points, geometry movement, or per-mouse-move solver work.
"""
from __future__ import annotations

import math


SKETCH_PICK_RADIUS = 9.0
_SUBPIXEL_TIE = .1  # framebuffer pixels; avoid precision-sized gaps at a bisector.
_PREFERENCES = "User parameter:BaseApp/Preferences/"


class SketchSnapping:
    def __init__(self, param_get=None):
        if param_get is None:
            import FreeCAD as App
            param_get = App.ParamGet
        self._param_get = param_get
        self._saved = []
        self._sketch = None
        self._origin = None
        self._points = []
        self._viewer = None
        self._renderer = None
        self._pick_path = None
        self._pick_widget = None
        self._pick_radius = None
        self._applied_radius = None
        self._curve_coordinates = {}
        self._midpoint_guard = None
        self._block_midpoint = False

    def begin(self, sketch, pixel_ratio=1.0):
        """Enable native point/axis snaps until this managed edit ends."""
        if self._sketch is sketch:
            return
        self.restore()
        self._sketch = sketch
        try:
            for group, kind, key, value in (
                # FreeCAD's picker aperture is in framebuffer pixels, whereas
                # pointer distances in Qt and the UI are logical pixels.
                ("View", "Float", "PickRadius", SKETCH_PICK_RADIUS * pixel_ratio),
                ("Mod/Sketcher/Snap", "Bool", "Snap", True),
                ("Mod/Sketcher/Snap", "Bool", "SnapToObjects", True),
            ):
                prefs = self._param_get(_PREFERENCES + group)
                contents = {key: value for _, key, value in (prefs.GetContents() or ())}
                original = contents.get(key)
                if key == "PickRadius":
                    value = max(value, prefs.GetFloat(key, 5.0))
                self._saved.append((prefs, kind, key, original, value))
                getattr(prefs, "Set" + kind)(key, value)
            for key in ("Autoconstraints", "AvoidRedundant"):
                view = sketch.ViewObject
                original = getattr(view, key)
                self._saved.append((view, None, key, original, True))
                setattr(view, key, True)
        except Exception:
            self.restore()
            raise

    def before_native(self, command):
        """Prioritize native origin, endpoints and centers while drawing.

        In an oblique view a ray can hit an axis closer to the camera even
        directly over a point. Coin's native on-top pick style resolves
        that ambiguity without moving the marker or authoring a constraint.
        Selecting, dimensioning and editing keep their native point order.
        """
        self._restore_markers()
        if not self._sketch or not (command or "").startswith("Sketcher_Create"):
            return
        import FreeCADGui as Gui
        from pivy import coin
        view = Gui.getDocument(self._sketch.Document.Name).activeView()
        # Search once at activation, never on pointer movement or idle ticks.
        # Native PointSetN includes internal and converted geometry. Keep each
        # original marker so Sketcher retains its vertex IDs and constraints.
        search = coin.SoSearchAction()
        search.setType(coin.SoPointSet.getClassTypeId(), True)
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(view.getSceneGraph())
        markers = []
        paths = search.getPaths()
        for index in range(paths.getLength()):
            path = paths[index]
            name = str(path.getTail().getName())
            if path.getLength() >= 2 and (name == "OriginPointSet"
                    or name.startswith("PointSet") and name[8:].isdigit()):
                markers.append((path.getNode(path.getLength() - 2), path.getTail(), name))
        try:
            for parent, marker, name in markers:
                nodes = self._prioritize(parent, marker, name == "OriginPointSet")
                if name == "OriginPointSet":
                    self._origin = nodes
                else:
                    self._points.append(nodes)
            self._prepare_picker(view)
        except Exception:
            self._restore_markers()
            raise

    @staticmethod
    def _prioritize(parent, marker, origin):
        from pivy import coin
        wrapper = coin.SoSeparator()
        wrapper.setName("KurtShapeNativeOriginPickPriority" if origin else "KurtShapeNativePointPickPriority")
        style = coin.SoPickStyle()
        style.style = coin.SoPickStyle.SHAPE_ON_TOP
        wrapper.addChild(style)
        wrapper.addChild(marker)
        # Native resetEdit can discard its scene before adapter cleanup runs.
        # Keep the three nodes alive until restoration, even when detached.
        for item in (parent, marker, wrapper):
            item.ref()
        try:
            parent.replaceChild(marker, wrapper)
        except Exception:
            for item in (wrapper, marker, parent):
                item.unref()
            raise
        return parent, marker, wrapper

    def _prepare_picker(self, view):
        from pivy import coin
        self._viewer = view.getViewer()
        self._renderer = self._viewer.getSoRenderManager()
        self._pick_radius = self._viewer.getPickRadius()
        self._applied_radius = self._pick_radius
        self._pick_widget = view.graphicsView()
        search = coin.SoSearchAction()
        search.setName("Sketch_EditRoot")
        search.setInterest(coin.SoSearchAction.FIRST)
        search.apply(self._renderer.getSceneGraph())
        path = search.getPath()
        if path is not None:
            self._pick_path = path.copy()
            self._pick_path.ref()
            # These native arrays are updated in place when a continuous line
            # commits. Keep their nodes, not a snapshot of their coordinates.
            search = coin.SoSearchAction()
            search.setType(coin.SoCoordinate3.getClassTypeId(), True)
            search.setInterest(coin.SoSearchAction.ALL)
            search.apply(self._pick_path)
            paths = search.getPaths()
            self._curve_coordinates = {str(paths[i].getTail().getName())[16:]: paths[i].getTail()
                                       for i in range(paths.getLength())
                                       if str(paths[i].getTail().getName()).startswith("CurvesCoordinate")}

    @staticmethod
    def _capture_radius(distances, full_radius, keys=None):
        """Keep the nearest group inside the aperture, excluding farther ones."""
        if keys is None:
            keys = distances
        candidates = sorted((distance, index, key) for index, (distance, key) in enumerate(zip(distances, keys))
                            if math.isfinite(distance) and distance <= full_radius + .001)
        if not candidates:
            return full_radius
        closest, _, nearest_key = candidates[0]
        required = max(distance for distance, _, key in candidates if key == nearest_key)
        # Truly coincident points remain a native tie. Only a farther marker
        # requires a smaller aperture; a lone point keeps the full capture area.
        farther = next((distance for distance, _, key in candidates
                        if key != nearest_key and distance > closest + _SUBPIXEL_TIE), None)
        if farther is None or farther <= required + _SUBPIXEL_TIE:
            return full_radius
        return min(full_radius, required + min(.1, (farther - required) / 2))

    def _nearest_radius(self, point):
        from pivy import coin
        viewport = self._renderer.getViewportRegion()
        pick = coin.SoRayPickAction(viewport)
        pick.setPoint(coin.SbVec2s(*point))
        pick.setRadius(self._pick_radius)
        pick.setPickAll(True)
        # Applying the cached path retains preceding camera/placement state,
        # but does not ray-pick support solids or other model geometry.
        pick.apply(self._pick_path)
        hits = pick.getPickedPointList()
        size = viewport.getViewportSizePixels()
        origin = viewport.getViewportOriginPixels()
        volume = self._renderer.getCamera().getViewVolume(viewport.getViewportAspectRatio())
        distances = []
        keys = []
        self._block_midpoint = False
        curve = None
        for index in range(hits.getLength()):
            hit = hits[index]
            name = str(hit.getPath().getTail().getName())
            if name != "OriginPointSet" and not (name.startswith("PointSet") and name[8:].isdigit()):
                if curve is None and name.startswith("CurvesLineSet") and name[13:].isdigit():
                    curve = hit
                continue
            screen = volume.projectToScreen(hit.getPoint())
            distances.append(math.hypot(screen[0] * size[0] + origin[0] - point[0],
                                        screen[1] * size[1] + origin[1] - point[1]))
            # Native marker coordinates share sketch-local XY. Origin and
            # coincident centers can use different presentation Z offsets;
            # in an oblique view those are slightly different screen points.
            # Keep every marker of the same sketch point inside the aperture.
            local = hit.getObjectPoint()
            keys.append((float(local[0]), float(local[1])))
        # The engine's line-midpoint capture is 5% of the *model length*.
        # A long line can therefore pin the endpoint dozens of screen pixels
        # away from the mouse. The same threshold also creates a Symmetric
        # auto-constraint on click. Veto both outside the ordinary aperture,
        # while allowing nearby native point markers to retain priority.
        if not any(distance <= self._pick_radius + .001 for distance in distances) and curve is not None:
            self._block_midpoint = self._oversized_midpoint(curve, point, volume, size, origin)
        return self._capture_radius(distances, self._pick_radius, keys)

    def _oversized_midpoint(self, hit, point, volume, size, origin):
        from pivy import coin
        node = hit.getPath().getTail()
        coordinates = self._curve_coordinates.get(str(node.getName())[13:])
        detail = hit.getDetail()
        if (coordinates is None or not node.isOfType(coin.SoLineSet.getClassTypeId())
                or detail is None or detail.getTypeId() != coin.SoLineDetail.getClassTypeId()):
            return False
        detail = coin.cast(detail, "SoLineDetail")
        part = detail.getPartIndex()
        if part < 0 or part >= node.numVertices.getNum() or node.numVertices[part] != 2:
            return False  # Curved polylines retain their own native behavior.
        first, second = detail.getPoint0().getCoordinateIndex(), detail.getPoint1().getCoordinateIndex()
        if min(first, second) < 0 or max(first, second) >= coordinates.point.getNum():
            return False
        start, end = coordinates.point[first], coordinates.point[second]
        midpoint = (start + end) * .5
        delta = hit.getObjectPoint() - midpoint
        if math.hypot(delta[0], delta[1]) >= (end - start).length() * .05:
            return False
        world = hit.getObjectToWorld().multVecMatrix(midpoint)
        screen = volume.projectToScreen(world)
        return math.hypot(screen[0] * size[0] + origin[0] - point[0],
                          screen[1] * size[1] + origin[1] - point[1]) > self._pick_radius

    def _guard_midpoint(self, block):
        if not block:
            if self._midpoint_guard is not None:
                prefs, snap, view, auto = self._midpoint_guard
                self._midpoint_guard = None
                if not prefs.GetBool("SnapToObjects", True):
                    prefs.SetBool("SnapToObjects", snap)
                try:
                    if not view.Autoconstraints:
                        view.Autoconstraints = auto
                except (AttributeError, ReferenceError, RuntimeError):
                    pass  # Native resetEdit/deletion may precede our cleanup.
            return
        if self._midpoint_guard is None and self._sketch is not None:
            prefs = self._param_get(_PREFERENCES + "Mod/Sketcher/Snap")
            view = self._sketch.ViewObject
            self._midpoint_guard = (prefs, prefs.GetBool("SnapToObjects", True), view, view.Autoconstraints)
            prefs.SetBool("SnapToObjects", False)
            view.Autoconstraints = False

    def _set_radius(self, radius):
        if self._viewer is not None and radius != self._applied_radius:
            self._viewer.setPickRadius(radius)
            self._applied_radius = radius

    def _reset_radius(self):
        if self._viewer is not None and self._pick_radius is not None:
            try:
                if abs(self._viewer.getPickRadius() - self._applied_radius) < .0001:
                    self._set_radius(self._pick_radius)
            except (ReferenceError, RuntimeError):
                pass

    def event(self, watched, event):
        """Resolve nearby native markers before native hover/click processing."""
        if self._pick_path is None:
            return False
        from PySide import QtCore, QtGui
        kind = event.type()
        if kind in (QtCore.QEvent.Leave, QtCore.QEvent.WindowDeactivate,
                    QtCore.QEvent.Hide, QtCore.QEvent.Close, QtCore.QEvent.Wheel):
            self._reset_radius()
            self._guard_midpoint(False)
            return False
        if kind not in (QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonPress,
                        QtCore.QEvent.MouseButtonRelease):
            return False
        if (not isinstance(watched, QtGui.QWidget)
                or watched.metaObject().className() != "QOpenGLWidget"
                or self._pick_widget is None
                or not (watched is self._pick_widget or self._pick_widget.isAncestorOf(watched))):
            return False
        if event.buttons() & (QtCore.Qt.MiddleButton | QtCore.Qt.RightButton):
            self._reset_radius()
            self._guard_midpoint(False)
            return False
        # Match Quarter/Mouse.cpp: round to Qt's logical integer event position,
        # flip Y there, THEN scale/truncate into Coin's framebuffer coordinates.
        position = event.pos()
        ratio = watched.devicePixelRatioF()
        point = (int(position.x() * ratio), int((watched.height() - position.y() - 1) * ratio))
        try:
            current = self._viewer.getPickRadius()
            if abs(current - self._applied_radius) >= .0001:
                # A native preference change belongs to its owner, not us.
                self._pick_radius = self._applied_radius = current
            self._set_radius(self._nearest_radius(point))
            self._guard_midpoint(self._block_midpoint)
        except (ReferenceError, RuntimeError):
            self._reset_radius()
            self._guard_midpoint(False)
        return False

    def sync_tool(self, command):
        """Clear priority after Escape/right-click without traversing the scene."""
        if not (command or "").startswith("Sketcher_Create"):
            self._restore_markers()

    def _restore_markers(self):
        self._guard_midpoint(False)
        self._reset_radius()
        if self._pick_path is not None:
            self._pick_path.unref()
        self._pick_path = self._viewer = self._renderer = self._pick_widget = None
        self._pick_radius = self._applied_radius = None
        self._curve_coordinates = {}
        self._block_midpoint = False
        nodes = self._points + ([self._origin] if self._origin is not None else [])
        self._points = []
        self._origin = None
        for parent, marker, wrapper in reversed(nodes):
            try:
                if parent.findChild(wrapper) >= 0:
                    parent.replaceChild(wrapper, marker)
            except (ReferenceError, RuntimeError):
                pass
            finally:
                for item in (wrapper, marker, parent):
                    item.unref()

    def restore(self):
        """Restore the previous native settings, including absent preferences."""
        self._restore_markers()
        saved, self._saved = self._saved, []
        self._sketch = None
        for target, kind, key, original, applied in reversed(saved):
            try:
                if kind is None:
                    if getattr(target, key) == applied:
                        setattr(target, key, original)
                elif getattr(target, "Get" + kind)(key) == applied:
                    if original is None:
                        getattr(target, "Rem" + kind)(key)
                    else:
                        getattr(target, "Set" + kind)(key, original)
            except (AttributeError, ReferenceError, RuntimeError):
                # A deleted sketch's view provider can already be invalid.
                continue
