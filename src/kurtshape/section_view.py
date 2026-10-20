"""Section View (Shift+X): a view-only cut through the model with a drag arrow.

Select a face or plane and press Shift+X, or press Shift+X and then click one
(a face in the view, a visible datum plane, or Top/Front/Right in the history).

* A round face (cylinder, cone, torus, sphere, revolved face, or a flat face
  whose outline is one circle) and any other curved face cut through their
  centre, on the origin plane (Top, Front or Right) the camera looks at most
  squarely. A tilted axis keeps that origin-aligned plane through the centre.
* Any other flat face, a datum plane or an origin plane cuts on its own plane.
* The side between the camera and the plane is hidden, so the cut faces the
  viewer. Cut faces are filled in each part's colour with a dark outline.
* A faint outline of the plane and a double arrow at its centre show the cut;
  dragging the arrow slides it along the plane normal. There are no inputs.
* Shift+X again (with nothing new selected) or Escape leaves Section View.

Everything lives in the 3D view's Coin scene: no document object, history row,
transaction, undo step or revision change, and nothing is saved with the file.
The model is clipped with one ``SoClipPlane`` placed just before the viewer's
``ObjectGroup`` (where FreeCAD's own clipping plane goes), so sketch editing in
``EditingRoot`` stays whole; the cut faces, outline and arrow sit before the
clip plane and are never clipped themselves.
"""
from __future__ import annotations

from collections import OrderedDict
import math
import time

import FreeCAD as App
import Part

from . import polygon_fill

ORIGIN_PLANES = (("Top", (0.0, 0.0, 1.0)), ("Front", (0.0, -1.0, 0.0)), ("Right", (1.0, 0.0, 0.0)))
ORIGIN_ROLES = {"XY": "Top", "XZ": "Front", "YZ": "Right"}
PLANE_TYPES = {"App::Plane", "PartDesign::Plane"}
CENTER, PLANE = "center", "plane"
ARROW_PIXELS = 58.0          # half length of the drag arrow on screen (Qt px)
PLANE_MARGIN = 0.08          # the plane outline overhangs the model's box by this fraction
OUTLINE_COLOR = (0.18, 0.20, 0.22)
ARROW_COLOR = (0.93, 0.42, 0.08)           # orange: stands out on blue and grey parts
ARROW_ACTIVE_COLOR = (1.0, 0.62, 0.22)     # under the pointer or dragging
RING_RADIUS = 0.34           # the grab ring around the arrow's centre, in arrow half-lengths
PLANE_COLOR = (0.094, 0.373, 0.647)
LIVE_CAP_BUDGET_S = 0.12     # slower cut-face updates wait for the end of a drag
END_ON_PIXELS = 14.0         # an arrow shorter than this on screen (Qt px) drags with vertical mouse motion
ARROW_HIT_PIXELS = 7.0       # a press this close to the drawn arrow (Qt px) grabs it
MESH_CACHE = 64              # solid meshes kept for later sections (per part, shape and tolerance)
MESH_SLICE_S = 0.15          # meshing work per event-loop turn before the cut faces are complete
WARM_DELAY_MS = 120          # idle pause between meshing the other visible solids, one per turn
PLANE_NUDGE = 2e-6           # a face or plane cut sits this fraction of the model size toward the camera
SYNC_INTERVAL_S = 0.4


# ------------------------------------------------------------------ geometry rules (no GUI)
def _unit(vector):
    vector = App.Vector(vector)
    length = vector.Length
    if not math.isfinite(length) or length < 1e-12:
        raise ValueError("Section View needs a nonzero direction")
    return vector * (1.0 / length)


def closest_origin_plane(view_direction):
    """(name, unit normal) of the origin plane a camera looking along ``view_direction`` faces most squarely."""
    direction = _unit(view_direction)
    best = max(abs(direction.dot(App.Vector(*normal))) for _, normal in ORIGIN_PLANES)
    # Ties (an exact isometric view) keep the first of Top, Front, Right.
    name, normal = next(item for item in ORIGIN_PLANES
                        if abs(direction.dot(App.Vector(*item[1]))) >= best - 1e-9)
    return name, App.Vector(*normal)


def facing_viewer(normal, view_direction):
    """``normal`` or its reverse, whichever points back toward the camera."""
    normal = _unit(normal)
    return -normal if normal.dot(_unit(view_direction)) > 0 else normal


def _project_on_axis(point, axis_point, axis):
    axis = _unit(axis)
    return App.Vector(axis_point) + axis * (App.Vector(point) - App.Vector(axis_point)).dot(axis)


def _axis_middle(face, axis_point, axis):
    """The point of the axis halfway along the face's extent on it (cylinders, cones, revolved faces)."""
    axis, axis_point = _unit(axis), App.Vector(axis_point)
    values = []
    for edge in face.Edges:
        try:
            points = edge.discretize(Number=17)
        except Exception:  # noqa: BLE001 - a degenerate edge (cone apex) has no extent
            continue
        values.extend((point - axis_point).dot(axis) for point in points)
    if not values:
        return _project_on_axis(face.CenterOfMass, axis_point, axis)
    return axis_point + axis * ((min(values) + max(values)) / 2.0)


def circular_outline(face):
    """Centre of a flat face whose outer boundary is one circle (end cap, washer face), else None."""
    tolerance = max(1e-6, 1e-7 * face.BoundBox.DiagonalLength)
    center = radius = None
    for edge in face.OuterWire.Edges:
        curve = edge.Curve
        if not isinstance(curve, Part.Circle):
            return None
        if center is None:
            center, radius = App.Vector(curve.Center), curve.Radius
        elif (curve.Center - center).Length > tolerance or abs(curve.Radius - radius) > tolerance:
            return None
    return center


def _face_normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    return _unit(face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0))


def face_target(face):
    """What a selected face asks of Section View, in world coordinates.

    ``{"kind": "center", "center": point}``: cut through ``point`` on the origin
    plane facing the camera (round and other curved faces, circular flat faces).
    ``{"kind": "plane", "origin": point, "normal": n}``: cut on the face's plane.
    """
    surface = face.Surface
    center_of_mass = App.Vector(face.CenterOfMass)
    if isinstance(surface, Part.Plane):
        center = circular_outline(face)
        if center is not None:
            return {"kind": CENTER, "center": center, "round": True}
        return {"kind": PLANE, "origin": center_of_mass, "normal": _face_normal(face)}
    if isinstance(surface, (Part.Cylinder, Part.Cone)):
        return {"kind": CENTER, "center": _axis_middle(face, surface.Center, surface.Axis), "round": True}
    if isinstance(surface, Part.SurfaceOfRevolution):
        return {"kind": CENTER, "center": _axis_middle(face, surface.Location, surface.Direction), "round": True}
    if isinstance(surface, (Part.Toroid, Part.Sphere)):
        return {"kind": CENTER, "center": App.Vector(surface.Center), "round": True}
    # Other curved faces (fillet blends, splines): through the face's centre.
    return {"kind": CENTER, "center": center_of_mass, "round": False}


def plane_target(placement, label):
    """A datum or origin plane: cut on it (its local Z is the normal)."""
    placement = App.Placement(placement)
    return {"kind": PLANE, "origin": App.Vector(placement.Base),
            "normal": _unit(placement.Rotation.multVec(App.Vector(0, 0, 1))), "label": label,
            "recenter": True}


def recentered(origin, normal, box):
    """The point of the plane (origin, normal) nearest the centre of ``box``: where the arrow belongs."""
    normal = _unit(normal)
    center = App.Vector(box.Center)
    return center - normal * (center - App.Vector(origin)).dot(normal)


def section_plane(target, view_direction):
    """The cut for ``target`` seen along ``view_direction``: origin, viewer-facing unit normal, label."""
    if target["kind"] == CENTER:
        name, normal = closest_origin_plane(view_direction)
        return {"origin": App.Vector(target["center"]), "normal": facing_viewer(normal, view_direction),
                "label": name + " plane"}
    return {"origin": App.Vector(target["origin"]), "normal": facing_viewer(target["normal"], view_direction),
            "label": target.get("label") or "face plane"}


def offset_text(offset):
    value = 0.0 if abs(offset) < 0.005 else offset
    return "%+.2f mm" % value


def status_text(label, offset):
    return "Section View · %s · %s · drag the arrow · Shift+X or Esc exits" % (label, offset_text(offset))


PICK_TEXT = "Section View · click a face or plane · Esc cancels"


def plane_axes(normal):
    """Two in-plane unit axes (u, v) with u x v = normal; u follows the world axis least along the normal."""
    normal = _unit(normal)
    axes = [App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)]
    pick = min(axes, key=lambda axis: abs(axis.dot(normal)))
    u = _unit(pick - normal * pick.dot(normal))
    return u, normal.cross(u)


def plane_rectangle(box, point, normal, margin=PLANE_MARGIN):
    """Corners (relative to ``point``) of the plane outline covering ``box`` projected onto the plane."""
    u, v = plane_axes(normal)
    corners = [App.Vector(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax)
               for z in (box.ZMin, box.ZMax)]
    us = [(corner - point).dot(u) for corner in corners]
    vs = [(corner - point).dot(v) for corner in corners]
    pad = margin * max(box.DiagonalLength, 1e-6)
    u0, u1, v0, v1 = min(us) - pad, max(us) + pad, min(vs) - pad, max(vs) + pad
    return [u * a + v * b for a, b in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]


class SolidMesh:
    """A closed triangle mesh of one solid, cut by planes quickly enough to follow a drag.

    OCCT's exact ``slice`` takes about half a second on a part like Shell M, so the
    cut faces come from the solid's tessellation instead (pure Python: the GUI
    process keeps numpy out). Faces carry their own copies of shared edge points, so
    coincident vertices are merged first; a cut then walks only the triangles in the
    slab around the plane and chains their crossing edges into closed loops.
    """

    def __init__(self, solid, tolerance):
        points, facets = solid.tessellate(tolerance)
        box = solid.BoundBox
        quantum = 1e-7 * max(box.DiagonalLength, 1.0)
        index, merged, remap = {}, [], []
        for point in points:
            key = (round(point.x / quantum), round(point.y / quantum), round(point.z / quantum))
            found = index.get(key)
            if found is None:
                found = index[key] = len(merged)
                merged.append((point.x, point.y, point.z))
            remap.append(found)
        self.points = merged
        self.triangles = [(remap[a], remap[b], remap[c]) for a, b, c in facets
                          if remap[a] != remap[b] and remap[b] != remap[c] and remap[a] != remap[c]]
        self.box = box
        self._direction = None

    def _prepare(self, normal):
        """Project the vertices on ``normal`` and bucket the triangles into slabs along it."""
        key = (round(normal.x, 12), round(normal.y, 12), round(normal.z, 12))
        if self._direction == key:
            return
        nx, ny, nz = normal.x, normal.y, normal.z
        proj = [x * nx + y * ny + z * nz for x, y, z in self.points]
        low, high = min(proj, default=0.0), max(proj, default=0.0)
        count = max(16, min(1024, len(self.triangles) // 48))
        step = (high - low) / count or 1.0
        bins, wide = [[] for _ in range(count)], []
        for number, (a, b, c) in enumerate(self.triangles):
            pa, pb, pc = proj[a], proj[b], proj[c]
            first = int((min(pa, pb, pc) - low) / step)
            last = min(count - 1, int((max(pa, pb, pc) - low) / step))
            if last - first > 8:
                wide.append(number)  # long along the normal (cylinder walls seen end on)
            else:
                for slab in range(first, last + 1):
                    bins[slab].append(number)
        self._direction, self._proj = key, proj
        self._low, self._step, self._bins, self._wide = low, step, bins, wide

    def loops(self, normal, distance):
        """Closed polylines where the plane ``normal . p = distance`` cuts the mesh."""
        self._prepare(normal)
        proj, points, triangles = self._proj, self.points, self.triangles
        slab = int((distance - self._low) / self._step)
        if slab < 0 or slab >= len(self._bins):
            return []
        crossing, links = {}, {}

        def cross(i, j):
            key = (i, j) if i < j else (j, i)
            if key not in crossing:
                di, dj = proj[i] - distance, proj[j] - distance
                t = di / (di - dj)
                pi, pj = points[i], points[j]
                crossing[key] = (pi[0] + (pj[0] - pi[0]) * t, pi[1] + (pj[1] - pi[1]) * t,
                                 pi[2] + (pj[2] - pi[2]) * t)
            return key

        for number in self._bins[slab] + self._wide:
            a, b, c = triangles[number]
            sa, sb, sc = proj[a] >= distance, proj[b] >= distance, proj[c] >= distance
            if sa == sb == sc:
                continue
            ends = [cross(i, j) for i, j, si, sj in ((a, b, sa, sb), (b, c, sb, sc), (c, a, sc, sa)) if si != sj]
            first, second = ends
            links.setdefault(first, []).append(second)
            links.setdefault(second, []).append(first)
        loops, seen = [], set()
        for start in links:
            if start in seen:
                continue
            chain, previous, current, closed = [start], None, start, False
            seen.add(start)
            while True:
                options = [key for key in links[current] if key != previous]
                if len(links[current]) != 2 or not options:
                    break  # an open or branching chain: not a cap boundary
                following = options[0]
                if following == start:
                    closed = True
                    break
                if following in seen:
                    break
                seen.add(following)
                chain.append(following)
                previous, current = current, following
            if closed and len(chain) >= 3:
                line = []
                for key in chain:
                    point = crossing[key]
                    if not line or any(abs(point[k] - line[-1][k]) > 1e-12 for k in range(3)):
                        line.append(point)
                if len(line) >= 3:
                    loops.append(line)
        return loops


def fill_loops(loops, origin, normal, tolerance):
    """Triangles filling closed loops that lie in the plane (origin, normal), holes by nesting.

    Returns (points, triangles, outlines) in world coordinates. Loops are thinned
    (points within a quarter of ``tolerance`` of their chord dropped) and filled by
    ear clipping; overlapping loops of different solids belong in separate calls.
    """
    origin, (u, v) = App.Vector(origin), plane_axes(normal)
    ox, oy, oz = origin.x, origin.y, origin.z
    rings = []
    for loop in loops:
        ring = [((x - ox) * u.x + (y - oy) * u.y + (z - oz) * u.z, (x - ox) * v.x + (y - oy) * v.y + (z - oz) * v.z)
                for x, y, z in loop]
        ring = polygon_fill.simplify(ring, 0.25 * tolerance)
        if len(ring) >= 3 and abs(polygon_fill.polygon_area(ring)) > 0:
            rings.append(ring)

    def world(a, b):
        return (ox + u.x * a + v.x * b, oy + u.y * a + v.y * b, oz + u.z * a + v.z * b)

    points, triangles = [], []
    for group in polygon_fill.regions(rings):
        members = [rings[i] for i in group]
        base = len(points)
        for ring in members:
            points.extend(world(a, b) for a, b in ring)
        triangles.extend((base + i, base + j, base + k) for i, j, k in polygon_fill.triangulate(members))
    outlines = [[world(a, b) for a, b in ring + ring[:1]] for ring in rings]
    return points, triangles, outlines


def cut_face(mesh, origin, normal, tolerance):
    """(points, triangles, outlines) of the cut through one meshed solid, or empty lists."""
    normal = _unit(normal)
    distance = normal.dot(App.Vector(origin))
    box = mesh.box
    sides = [normal.dot(App.Vector(x, y, z)) - distance for x in (box.XMin, box.XMax)
             for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
    if min(sides) > 0 or max(sides) < 0:
        return [], [], []
    loops = mesh.loops(normal, distance)
    return fill_loops(loops, origin, normal, tolerance) if loops else ([], [], [])


def cap_color(color):
    """Cut-face colour: exactly the colour of the body being cut (drawn unshaded, with a dark outline)."""
    return tuple(float(channel) for channel in color[:3])


def part_color(obj):
    """The colour the view draws a result in (Body, Part feature or assembly occurrence).

    The view object's appearance comes first (a link's own override, then the
    object's ShapeAppearance / ShapeColor); KurtShape's stored part colour is the
    fallback for an object without a view.
    """
    for candidate in (obj, getattr(obj, "LinkedObject", None)):
        if candidate is None:
            continue
        view = getattr(candidate, "ViewObject", None)
        if view is not None:
            if candidate is obj and getattr(view, "OverrideMaterial", False):
                try:
                    return tuple(float(c) for c in view.ShapeMaterial.DiffuseColor[:3])
                except Exception:  # noqa: BLE001
                    pass
            properties = view.PropertiesList
            if "ShapeAppearance" in properties:
                try:
                    return tuple(float(c) for c in view.ShapeAppearance[0].DiffuseColor[:3])
                except Exception:  # noqa: BLE001
                    pass
            if "ShapeColor" in properties:
                return tuple(float(c) for c in view.ShapeColor[:3])
        if "KurtShapePartColor" in getattr(candidate, "PropertiesList", ()):
            return tuple(float(c) for c in candidate.KurtShapePartColor[:3])
    return (0.78, 0.80, 0.84)


def _result_visible(obj):
    if "KurtShapePartVisible" in getattr(obj, "PropertiesList", ()):
        return bool(obj.KurtShapePartVisible) and bool(getattr(obj, "Visibility", True))
    view = getattr(obj, "ViewObject", None)
    return bool(view.Visibility) if view is not None else bool(getattr(obj, "Visibility", True))


def _part_key(obj):
    """What a result's cut faces depend on: its shape, world placement, visibility and colour."""
    from . import selectors
    source = selectors.result_source(obj)
    try:
        linked = getattr(source, "LinkedObject", None) if source.TypeId == "App::Link" else source
        shape_key = linked.Shape.hashCode() if linked is not None and hasattr(linked, "Shape") else None
        placement = tuple(source.getGlobalPlacement().toMatrix().A)
    except Exception:  # noqa: BLE001
        shape_key = placement = None
    return (obj.Name, _result_visible(obj), shape_key, placement, part_color(obj))


def visible_parts(doc):
    """[{obj, shape, color, key, solids}] for every visible current result of ``doc``, in world coordinates."""
    from .bodies import results
    from . import selectors
    parts = []
    for obj in results(doc):
        if not _result_visible(obj):
            continue
        try:
            shape = selectors.world_shape(selectors.result_source(obj))
        except Exception:  # noqa: BLE001 - nothing to cut for a result without a shape
            continue
        if shape is None or shape.isNull():
            continue
        solids = shape.Solids
        parts.append({"obj": obj, "shape": shape, "color": part_color(obj), "key": _part_key(obj),
                      "solids": solids, "boxes": [solid.BoundBox for solid in solids]})
    return parts


def parts_signature(doc):
    """Cheap fingerprint of what the cut faces depend on (shapes, placements, visibility, colours)."""
    from .bodies import results
    return tuple(_part_key(obj) for obj in results(doc))


def selection_target(obj, subelement, plane_label=None):
    """Section target for one selected native object and subelement name, or None.

    Faces resolve through ``Part.getShape`` so assembly occurrences and Body
    paths arrive in world coordinates; planes through their global placement.
    """
    sub = subelement or ""
    leaf = sub.rsplit(".", 1)[-1]
    if leaf.startswith("Face"):
        face = Part.getShape(obj, sub, needSubElement=True)
        if face.isNull() or face.ShapeType != "Face":
            face = face.Faces[0] if not face.isNull() and len(face.Faces) == 1 else None
        return face_target(face) if face is not None else None
    if leaf:
        return None  # an edge or a vertex
    plane = obj.getSubObject(sub, retType=1) if sub else obj
    if plane is None or plane.TypeId not in PLANE_TYPES:
        return None
    # retType 3: the plane's placement accumulated along the selected path (Body, container, link).
    placement = obj.getSubObject(sub, retType=3) if sub else plane.getGlobalPlacement()
    return plane_target(placement, plane_label or plane_name(plane))


def plane_name(plane):
    role = str(getattr(plane, "Role", "") or plane.Name)
    for key, name in ORIGIN_ROLES.items():
        if role.startswith(key + "_Plane"):
            return name + " plane"
    return plane.Label


# ------------------------------------------------------------------ the 3D view
class SectionView:
    """Shift+X controller owned by the Panel; one section at a time, in one 3D view."""

    def __init__(self, panel=None):
        self.panel = panel
        self.picking = False
        self.pick_document = None
        self.state = None
        self._last_sync = 0.0
        self._mouse = None
        self._meshes = OrderedDict()

    # -- status -------------------------------------------------------------
    @property
    def active(self):
        return self.state is not None

    def _notify(self, message):
        panel = self.panel
        if panel is not None and hasattr(panel, "notify"):
            panel.notify(message)

    def _feedback(self, text):
        panel = self.panel
        if panel is not None and hasattr(panel, "task_feedback"):
            panel.task_feedback(text)
        elif panel is None:
            try:
                import FreeCADGui as Gui
                Gui.getMainWindow().statusBar().showMessage(text, 8000)
            except Exception:  # noqa: BLE001
                pass

    def status_text(self):
        """The persistent status-bar line while Section View owns the active document, else None."""
        doc = App.ActiveDocument
        if self.picking and doc is not None and doc.Name == self.pick_document:
            return PICK_TEXT
        if self.state is not None and doc is not None and doc.Name == self.state["document"]:
            return status_text(self.state["label"], self.state["offset"])
        return None

    # -- entry points ---------------------------------------------------------
    def toggle(self):
        """Shift+X: start on the selection, move to a new selection, or leave."""
        import FreeCADGui as Gui
        doc = App.ActiveDocument
        if doc is None or Gui.ActiveDocument is None:
            self._notify("Open a document to use Section View.")
            return False
        if self.state is not None and self.state["document"] != doc.Name:
            self.exit(quiet=True)
        found = self._selected_target(doc)
        if found is None:
            if self.state is not None:
                return self.exit()
            if self.picking:
                return self.cancel_pick()
            if self._has_selection(doc):
                self._notify("Section View needs a face or a plane · select one, or press Shift+X with nothing selected")
                return False
            return self.begin_pick(doc)
        target, key = found
        return self.start(doc, target, key)

    def begin_pick(self, doc):
        self.picking = True
        self.pick_document = doc.Name
        self._feedback(PICK_TEXT)
        return True

    def cancel_pick(self):
        if not self.picking:
            return False
        self.picking = False
        self.pick_document = None
        self._restore_status()
        self._notify("Section View canceled")
        return True

    def selection_pick(self, document, object_name, subelement):
        """SelectionObserver hook: in pick mode, a clicked face or plane starts the section."""
        if not self.picking or document != self.pick_document:
            return False
        doc = App.listDocuments().get(document)
        obj = doc.getObject(object_name) if doc is not None else None
        if obj is None:
            return False
        try:
            target = selection_target(obj, subelement)
        except Exception:  # noqa: BLE001
            target = None
        if target is None:
            self._notify("Section View needs a face or a plane")
            return True
        from PySide import QtCore
        key = (document, object_name, subelement or "")
        # Leave the native selection callback before changing the scene and selection.
        QtCore.QTimer.singleShot(0, lambda: self.start(doc, target, key))
        return True

    def history_pick(self, key, plane_object=None):
        """History-row hook: in pick mode, Top/Front/Right or a datum plane row starts the section."""
        if not self.picking or plane_object is None or plane_object.TypeId not in PLANE_TYPES:
            return False
        doc = plane_object.Document
        if doc.Name != self.pick_document:
            return False
        target = plane_target(plane_object.getGlobalPlacement(), plane_name(plane_object))
        return self.start(doc, target, ("history", doc.Name, plane_object.Name))

    def cancel(self):
        """Escape: leave pick mode first, then Section View itself."""
        if self.cancel_pick():
            return True
        doc = App.ActiveDocument
        if self.state is not None and doc is not None and doc.Name == self.state["document"]:
            return self.exit()
        return False

    def _has_selection(self, doc):
        import FreeCADGui as Gui
        return bool(Gui.Selection.getSelectionEx(doc.Name, 0))

    def _selected_target(self, doc):
        import FreeCADGui as Gui
        # Resolve-mode 0 keeps the top-level object and full subname, so links and
        # Body paths resolve in world coordinates through Part.getShape.
        for selected in Gui.Selection.getSelectionEx(doc.Name, 0):
            names = list(selected.SubElementNames) or [""]
            for sub in names:
                try:
                    target = selection_target(selected.Object, sub)
                except Exception:  # noqa: BLE001
                    target = None
                if target is not None:
                    return target, (doc.Name, selected.ObjectName, sub)
        return None

    # -- lifecycle --------------------------------------------------------------
    def start(self, doc, target, key=None):
        """Show the cut for ``target`` in ``doc``'s active 3D view."""
        import FreeCADGui as Gui
        if App.listDocuments().get(doc.Name) is not doc:
            return False
        gui_document = Gui.getDocument(doc.Name)
        view = gui_document.activeView() if gui_document is not None else None
        if view is None or not hasattr(view, "getSceneGraph"):
            self._notify("Section View needs a 3D view")
            return False
        self.picking = False
        self.pick_document = None
        if self.state is not None:
            self._remove_nodes()
            self.state = None
        try:
            plane = section_plane(target, view.getViewDirection())
        except ValueError:
            self._notify("Section View could not orient the plane")
            return False
        self.state = {"document": doc.Name, "doc": doc, "view": view, "target": target, "key": key,
                      "origin": plane["origin"], "normal": plane["normal"], "label": plane["label"],
                      "offset": 0.0, "parts": None, "signature": None, "dragging": False,
                      "drag_start": 0.0, "scale": 1.0, "cap_seconds": 0.0, "cap_pending": False}
        try:
            self._build_nodes()
            self._refresh_parts()
            self._update_plane(caps=False)
        except Exception:
            self._remove_nodes()
            self.state = None
            raise
        Gui.Selection.clearSelection()
        self._feedback(status_text(self.state["label"], 0.0))
        view.redraw()
        self._schedule_caps(delay=30)  # after the first paint, so the cut shows at once
        return True

    def exit(self, quiet=False):
        if self.state is None:
            return False
        self._remove_nodes()
        view = self.state.get("view")
        self.state = None
        try:
            view.redraw()
        except Exception:  # noqa: BLE001 - the native view was already closed
            pass
        if not quiet:
            self._restore_status()
            self._notify("Section View off")
        return True

    def shutdown(self):
        self.picking = False
        self.exit(quiet=True)

    def _restore_status(self):
        panel = self.panel
        if panel is not None and hasattr(panel, "restore_status"):
            panel.restore_status()

    def sync(self):
        """Panel tick: drop a closed view, follow model changes, keep the arrow's screen size."""
        if self.picking and App.listDocuments().get(self.pick_document) is None:
            self.picking = False
            self.pick_document = None
        state = self.state
        if state is None:
            return
        if App.listDocuments().get(state["document"]) is not state["doc"] or not self._view_alive():
            # The view is gone with its scene graph; only forget our references.
            self.state = None
            return
        now = time.monotonic()
        if now - self._last_sync < SYNC_INTERVAL_S or state["dragging"]:
            return
        self._last_sync = now
        self._rescale()
        try:
            signature = parts_signature(state["doc"])
        except Exception:  # noqa: BLE001
            return
        if signature != state["signature"]:
            state["warming"] = False  # new or changed parts: mesh them in idle time again
            self._refresh_parts()
            self._update_plane()

    def _view_alive(self):
        try:
            self.state["view"].getCameraNode()
            return True
        except Exception:  # noqa: BLE001
            return False

    # -- Coin scene ---------------------------------------------------------------
    def _build_nodes(self):
        from pivy import coin
        state = self.state
        view = state["view"]
        root = view.getSceneGraph()
        index = self._object_group_index(root)
        clip = coin.SoClipPlane()
        clip.setName("KurtShapeSectionClip")
        overlay = coin.SoSeparator()
        overlay.setName("KurtShapeSectionView")
        caps = coin.SoSeparator()
        caps.setName("KurtShapeSectionCaps")
        overlay.addChild(caps)
        plane_node, plane_transform, plane_coords, plane_fill = self._plane_nodes()
        overlay.addChild(plane_node)
        arrow, arrow_transform, arrow_look = self._arrow_nodes()
        overlay.addChild(arrow)
        root.insertChild(clip, index)
        root.insertChild(overlay, index)
        state.update(root=root, clip=clip, overlay=overlay, caps=caps, plane_transform=plane_transform,
                     plane_coords=plane_coords, plane_fill=plane_fill, arrow_transform=arrow_transform,
                     arrow_look=arrow_look, camera_sensor=None)
        self._watch_camera()

    @staticmethod
    def _object_group_index(root):
        names = [root.getChild(i).getName().getString() for i in range(root.getNumChildren())]
        if "ObjectGroup" in names:
            return names.index("ObjectGroup")
        if "EditingRoot" in names:
            return names.index("EditingRoot") + 1
        return 0

    def _remove_nodes(self):
        state = self.state or {}
        sensor = state.get("camera_sensor")
        if sensor is not None:
            try:
                sensor.detach()
            except Exception:  # noqa: BLE001
                pass
        state["camera_sensor"] = None
        root = state.get("root")
        for name in ("overlay", "clip"):
            node = state.get(name)
            if root is None or node is None:
                continue
            try:
                if root.findChild(node) >= 0:
                    root.removeChild(node)
            except (RuntimeError, ReferenceError):
                pass  # The native view was already destroyed.
        for name in ("root", "overlay", "clip", "caps", "arrow_look"):
            state[name] = None

    def _plane_nodes(self):
        from pivy import coin
        node = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        node.addChild(pick)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        node.addChild(light)
        transform = coin.SoTransform()
        node.addChild(transform)
        coords = coin.SoCoordinate3()
        node.addChild(coords)
        style = coin.SoDrawStyle()
        style.lineWidth = 1.5
        style.linePattern = 0xF0F0
        node.addChild(style)
        material = coin.SoMaterial()
        material.diffuseColor.setValue(*PLANE_COLOR)
        node.addChild(material)
        outline = coin.SoLineSet()
        outline.numVertices.setValue(5)
        node.addChild(outline)
        # The translucent fill shows only while dragging, so it never veils the cut.
        fill = coin.SoSwitch()
        fill.whichChild = coin.SO_SWITCH_NONE
        fill_group = coin.SoSeparator()
        fill_material = coin.SoMaterial()
        fill_material.diffuseColor.setValue(*PLANE_COLOR)
        fill_material.transparency = 0.86
        fill_group.addChild(fill_material)
        offset = coin.SoPolygonOffset()
        offset.factor = 1.0
        offset.units = 1.0
        fill_group.addChild(offset)
        face = coin.SoFaceSet()
        face.numVertices.setValue(4)
        fill_group.addChild(face)
        fill.addChild(fill_group)
        node.addChild(fill)
        return node, transform, coords, fill

    def _arrow_nodes(self):
        """The drag arrow: drawn over the model, never picked (the panel's event filter drags it)."""
        from pivy import coin
        node = coin.SoAnnotation()  # drawn over the model so the arrow is never buried
        node.setName("KurtShapeSectionArrow")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        node.addChild(pick)
        transform = coin.SoTransform()
        node.addChild(transform)
        look = coin.SoSwitch()  # 0: resting, 1: under the pointer or dragging
        look.addChild(self._arrow_geometry(ARROW_COLOR))
        look.addChild(self._arrow_geometry(ARROW_ACTIVE_COLOR))
        look.whichChild = 0
        node.addChild(look)
        return node, transform, look

    @staticmethod
    def _arrow_geometry(color):
        """A double arrow along local X, one unit from its centre to each tip, and a ring in the cut plane.

        Face on, the arrow points at the camera and shrinks to a dot; the ring then
        still shows where to grab (drag up or down to move the cut).
        """
        from pivy import coin
        group = coin.SoSeparator()
        material = coin.SoMaterial()
        material.diffuseColor.setValue(*color)
        material.emissiveColor.setValue(*(channel * 0.35 for channel in color))
        group.addChild(material)
        turn = coin.SoRotation()  # Coin cylinders and cones run along Y
        turn.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 1, 0), coin.SbVec3f(1, 0, 0)))
        group.addChild(turn)
        shaft = coin.SoCylinder()
        shaft.radius = 0.04
        shaft.height = 1.44
        group.addChild(shaft)
        for sign in (1.0, -1.0):
            head = coin.SoSeparator()
            place = coin.SoTransform()
            place.translation.setValue(0, sign * 0.84, 0)
            if sign < 0:
                place.rotation.setValue(coin.SbRotation(coin.SbVec3f(1, 0, 0), math.pi))
            head.addChild(place)
            cone = coin.SoCone()
            cone.bottomRadius = 0.13
            cone.height = 0.32
            head.addChild(cone)
            group.addChild(head)
        hub = coin.SoSphere()
        hub.radius = 0.08
        group.addChild(hub)
        ring = coin.SoSeparator()
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        ring.addChild(light)
        style = coin.SoDrawStyle()
        style.lineWidth = 2.5
        ring.addChild(style)
        steps = 48
        circle = [(0.0, RING_RADIUS * math.cos(2 * math.pi * k / steps), RING_RADIUS * math.sin(2 * math.pi * k / steps))
                  for k in range(steps + 1)]
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(circle), circle)
        ring.addChild(coords)
        line = coin.SoLineSet()
        line.numVertices.setValue(len(circle))
        ring.addChild(line)
        group.insertChild(ring, 1)  # before the Y-to-X turn: the ring lies across local X
        return group

    def _watch_camera(self):
        from pivy import coin
        state = self.state
        try:
            camera = state["view"].getCameraNode()
            sensor = coin.SoNodeSensor(self._camera_changed, None)
            sensor.attach(camera)
            state["camera_sensor"] = sensor
            state["camera"] = camera
        except Exception:  # noqa: BLE001 - the panel tick still rescales
            state["camera_sensor"] = None
            state["camera"] = None

    def _camera_changed(self, *args):
        if self.state is not None and not self.state["dragging"]:
            self._rescale()

    # -- placement of the plane, arrow and clip ---------------------------------------
    def point(self):
        state = self.state
        return state["origin"] + state["normal"] * state["offset"]

    def _pixel_size(self, point):
        """World length of one screen pixel at ``point`` for the view's current camera."""
        from pivy import coin
        view = self.state["view"]
        camera = view.getCameraNode()
        if self.state.get("camera") is not camera and self.state.get("camera_sensor") is not None:
            self.state["camera_sensor"].detach()
            self.state["camera_sensor"].attach(camera)
            self.state["camera"] = camera
        width, height = (max(1, int(value)) for value in view.getSize())
        if camera.isOfType(coin.SoOrthographicCamera.getClassTypeId()):
            extent = camera.height.getValue()
        else:
            position = App.Vector(*camera.position.getValue().getValue())
            depth = max((point - position).dot(_unit(view.getViewDirection())), 1e-6)
            extent = 2.0 * depth * math.tan(camera.heightAngle.getValue() / 2.0)
        # ADJUST_CAMERA: the camera's extent spans the shorter viewport side.
        return extent / min(width, height) if width < height else extent / height

    def _rescale(self):
        state = self.state
        if state is None or state["dragging"]:
            return
        try:
            import FreeCADGui as Gui
            ratio = Gui.getMainWindow().devicePixelRatioF()
            scale = ARROW_PIXELS * ratio * self._pixel_size(self.point())
        except Exception:  # noqa: BLE001
            return
        if math.isfinite(scale) and scale > 0 and abs(scale - state["scale"]) > 1e-9 * max(scale, 1.0):
            state["scale"] = scale
            state["arrow_transform"].scaleFactor.setValue(scale, scale, scale)

    def _update_plane(self, caps=True):
        from pivy import coin
        state = self.state
        point, normal = self.point(), state["normal"]
        clip = coin.SbPlane(coin.SbVec3f(*(-normal)), coin.SbVec3f(*point))
        state["clip"].plane.setValue(clip)  # keeps the far side: the cut faces the camera
        state["plane_transform"].translation.setValue(*point)
        state["arrow_transform"].translation.setValue(*point)
        state["arrow_transform"].rotation.setValue(coin.SbRotation(coin.SbVec3f(1, 0, 0), coin.SbVec3f(*normal)))
        self._rescale()
        if caps:
            self._update_caps()

    def _refresh_parts(self):
        state = self.state
        doc = state["doc"]
        state["parts"] = visible_parts(doc)
        state["signature"] = parts_signature(doc)
        box = App.BoundBox()
        for part in state["parts"]:
            box.add(part["shape"].BoundBox)
        if not box.isValid():
            box = App.BoundBox(-10, -10, -10, 10, 10, 10)
        state["box"] = box
        state["tolerance"] = max(0.005, box.DiagonalLength * 4e-4)
        if state["target"].get("recenter") and not state.get("recentered"):
            # A datum or origin plane: keep the plane, put the arrow over the model.
            state["origin"] = recentered(state["origin"], state["normal"], box)
            state["recentered"] = True
        if state["target"]["kind"] == PLANE and not state.get("nudged"):
            # A cut lying exactly on a model face would flicker; keep that face whole.
            state["origin"] = state["origin"] + state["normal"] * (PLANE_NUDGE * max(box.DiagonalLength, 1.0))
            state["nudged"] = True
        corners = plane_rectangle(box, state["origin"], state["normal"])
        corners = corners + corners[:1]
        state["plane_coords"].point.setValues(0, len(corners), [tuple(c) for c in corners])

    def _mesh_key(self, part, index):
        return (self.state["document"], part["key"], index, self.state["tolerance"])

    def _mesh(self, part, index):
        """The cached mesh of one solid of a part (built on first use, kept across sections)."""
        key = self._mesh_key(part, index)
        mesh = self._meshes.get(key)
        if mesh is None:
            mesh = SolidMesh(part["solids"][index], self.state["tolerance"])
            self._meshes[key] = mesh
            while len(self._meshes) > MESH_CACHE:
                self._meshes.popitem(last=False)
        else:
            self._meshes.move_to_end(key)
        return mesh

    @staticmethod
    def _crosses(box, point, normal):
        sides = [normal.dot(App.Vector(x, y, z) - point) for x in (box.XMin, box.XMax)
                 for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
        return min(sides) <= 0 <= max(sides)

    @property
    def caps_ready(self):
        """True once every solid the cut crosses has its cut face drawn (meshes are built lazily)."""
        return self.state is not None and not self.state["cap_pending"] and self.state.get("caps_complete", False)

    def _update_caps(self, build=True):
        """Fill the cut faces of every visible solid the plane crosses, in its part's colour.

        A solid is meshed the first time a cut crosses it (Shell M about 0.2 s, a large
        assembly about 2 s in all). Missing meshes are built a slice at a time between
        paints, so the cut shows at once and its faces fill in part by part. A drag
        passes ``build=False``: it never meshes in a mouse event (that would stutter);
        a solid not meshed yet stays open until the drag ends.
        """
        from pivy import coin
        state = self.state
        began = time.perf_counter()
        point, normal, tolerance = self.point(), state["normal"], state["tolerance"]
        crossed = [(part, index) for part in state["parts"] or ()
                   for index, box in enumerate(part["boxes"]) if self._crosses(box, point, normal)]
        missing = [item for item in crossed if self._mesh_key(*item) not in self._meshes]
        setup = 0.0
        while build and missing and (setup == 0.0 or time.perf_counter() - began < MESH_SLICE_S):
            built = time.perf_counter()
            self._mesh(*missing.pop(0))
            setup += time.perf_counter() - built
        caps = state["caps"]
        caps.removeAllChildren()
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        caps.addChild(light)
        offset = coin.SoPolygonOffset()  # caps win over model faces lying on the cut plane
        offset.factor = -1.0
        offset.units = -1.0
        caps.addChild(offset)
        failures, filled = 0, 0
        outlines = []
        cut_by_part = {}
        for part, index in crossed:
            mesh = self._meshes.get(self._mesh_key(part, index))
            if mesh is None:
                continue  # still to be meshed: a later slice draws it
            prepared = time.perf_counter()
            mesh._prepare(normal)  # once per cut direction: setup, not live cost
            setup += time.perf_counter() - prepared
            try:
                cut = cut_face(mesh, point, normal, tolerance)
            except Exception:  # noqa: BLE001 - an uncapped solid still shows its clipped walls
                failures += 1
                continue
            points, triangles = cut_by_part.setdefault(id(part), (part, [], []))[1:]
            base = len(points)
            points.extend(cut[0])
            triangles.extend((base + a, base + b, base + c) for a, b, c in cut[1])
            outlines.extend(cut[2])
        for part, points, triangles in cut_by_part.values():
            if not triangles:
                continue
            filled += 1
            group = coin.SoSeparator()
            material = coin.SoMaterial()
            material.diffuseColor.setValue(*cap_color(part["color"]))
            group.addChild(material)
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), points)
            group.addChild(coords)
            face_set = coin.SoIndexedFaceSet()
            indices = [value for triangle in triangles for value in (*triangle, -1)]
            face_set.coordIndex.setValues(0, len(indices), indices)
            group.addChild(face_set)
            caps.addChild(group)
        if outlines:
            lines = coin.SoSeparator()
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            lines.addChild(pick)
            material = coin.SoMaterial()
            material.diffuseColor.setValue(*OUTLINE_COLOR)
            lines.addChild(material)
            style = coin.SoDrawStyle()
            style.lineWidth = 1.5
            lines.addChild(style)
            flat = [p for line in outlines for p in line]
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(flat), flat)
            lines.addChild(coords)
            line_set = coin.SoLineSet()
            line_set.numVertices.setValues(0, len(outlines), [len(line) for line in outlines])
            lines.addChild(line_set)
            caps.addChild(lines)
        state["cap_failures"] = failures
        state["cap_parts"] = filled
        state["setup_seconds"] = state.get("setup_seconds", 0.0) + setup
        if not missing:
            # Meshing and per-direction setup happen once; the live budget is about the cut itself.
            state["cap_seconds"] = time.perf_counter() - began - setup
        if not build:
            state["caps_complete"] = not missing and not state["cap_pending"]
            return
        if missing:
            state["cap_pending"], state["caps_complete"] = True, False
            self._later(state, 0, self._update_caps)
            return
        state["cap_pending"], state["caps_complete"] = False, True
        if not state.get("warming"):
            state["warming"] = True
            self._later(state, WARM_DELAY_MS, self._warm_step)

    def _later(self, state, delay, step):
        """Run ``step`` after ``delay`` ms while ``state`` is still the section; never during a drag."""
        from PySide import QtCore

        def run():
            if self.state is not state:
                return
            if state["dragging"]:
                QtCore.QTimer.singleShot(WARM_DELAY_MS, run)
                return
            step()
        QtCore.QTimer.singleShot(delay, run)

    def _warm_step(self):
        """Idle time after the cut faces are complete: mesh the other visible solids one at a time.

        Then a drag into a part the cut did not cross at first fills it live too.
        Skipped when the parts have more solids than the mesh cache keeps.
        """
        state = self.state
        solids = [(part, index) for part in state["parts"] or () for index in range(len(part["solids"]))]
        if len(solids) > MESH_CACHE:
            return
        if state["cap_pending"]:
            self._later(state, WARM_DELAY_MS, self._warm_step)
            return
        for part, index in solids:
            if self._mesh_key(part, index) not in self._meshes:
                self._mesh(part, index)._prepare(state["normal"])
                self._later(state, WARM_DELAY_MS, self._warm_step)
                return
        for part, index in solids:
            self._meshes[self._mesh_key(part, index)]._prepare(state["normal"])
        state["warm"] = True

    # -- dragging -------------------------------------------------------------------
    # The panel's application event filter sees every mouse event before the 3D view.
    # A left press on the arrow (hit-tested on screen) starts a drag; the press, moves
    # and release are then consumed, so neither selection nor any navigation style acts
    # on them. The offset follows the mouse along the arrow's on-screen direction, or,
    # when the arrow points at the camera (a cut seen face on), vertical motion: up
    # pulls the cut toward you.
    def event(self, watched, event):
        """Panel event filter hook; True consumes the event."""
        state = self.state
        if state is None:
            return False
        from PySide import QtCore
        kind = event.type()
        if kind not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                        QtCore.QEvent.MouseButtonRelease):
            return False
        try:
            if watched.metaObject().className() != "QOpenGLWidget":
                return False
            doc = App.ActiveDocument
            if doc is None or doc.Name != state["document"]:
                return False
            position = event.position() if hasattr(event, "position") else event.pos()
            x, y = float(position.x()), float(position.y())
            left = QtCore.Qt.LeftButton
            if state["dragging"]:
                if kind == QtCore.QEvent.MouseMove:
                    if event.buttons() & left:
                        self._drag_to(x, y)
                    else:
                        self._drag_end()
                elif kind == QtCore.QEvent.MouseButtonRelease and event.button() == left:
                    self._drag_to(x, y)
                    self._drag_end()
                return True
            over = self.over_arrow(watched, x, y)
            if (kind == QtCore.QEvent.MouseButtonPress and event.button() == left and over
                    and not (event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier
                                                  | QtCore.Qt.AltModifier))):
                self._drag_begin(watched, x, y)
                return True
            if kind == QtCore.QEvent.MouseMove and not event.buttons():
                self._hover(over)
        except Exception:  # noqa: BLE001 - never break the viewer's own input
            return False
        return False

    @staticmethod
    def _logical(device_point, widget):
        """A viewport point from FreeCAD (device pixels, y up) in the widget's Qt coordinates."""
        ratio = widget.devicePixelRatioF()
        return float(device_point[0]) / ratio, widget.height() - 1 - float(device_point[1]) / ratio

    def _screen(self, widget, point):
        return self._logical(self.state["view"].getPointOnViewport(point), widget)

    def over_arrow(self, widget, x, y):
        """True when Qt point (x, y) of ``widget`` is on the drawn arrow."""
        state = self.state
        point, reach = self.point(), state["normal"] * state["scale"]
        ax, ay = self._screen(widget, point - reach)
        bx, by = self._screen(widget, point + reach)
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length2))
        distance = math.hypot(x - (ax + t * dx), y - (ay + t * dy))
        if distance <= ARROW_HIT_PIXELS:
            return True
        # The ring around the centre (seen face on, the only visible part of the handle).
        cx, cy = self._screen(widget, point)
        return math.hypot(x - cx, y - cy) <= RING_RADIUS * ARROW_PIXELS + ARROW_HIT_PIXELS / 2

    def _hover(self, over):
        look = self.state["arrow_look"]
        wanted = 1 if over else 0
        if look.whichChild.getValue() != wanted:
            look.whichChild = wanted

    def _drag_begin(self, widget, x, y):
        from pivy import coin
        state = self.state
        point = self.point()
        start = self._screen(widget, point)
        tip = self._screen(widget, point + state["normal"] * state["scale"])
        state.update(dragging=True, drag_start=state["offset"], drag_mouse=(x, y),
                     drag_axis=(tip[0] - start[0], tip[1] - start[1]),
                     drag_pixel=self._pixel_size(point) * widget.devicePixelRatioF())
        state["plane_fill"].whichChild = coin.SO_SWITCH_ALL
        state["arrow_look"].whichChild = 1

    def drag_delta(self, dx, dy):
        """World offset change for a mouse move of (dx, dy) Qt pixels (y down) during a drag."""
        state = self.state
        ax, ay = state["drag_axis"]
        length2 = ax * ax + ay * ay
        if length2 >= END_ON_PIXELS * END_ON_PIXELS:
            return (dx * ax + dy * ay) / length2 * state["scale"]
        return -dy * state["drag_pixel"]  # end on: moving up pulls the cut toward the camera

    def _drag_to(self, x, y):
        state = self.state
        start = state["drag_mouse"]
        state["offset"] = self.clamp(state["drag_start"] + self.drag_delta(x - start[0], y - start[1]))
        self._move_clip_and_plane()
        # The cut faces move with the cut in this same event. Drawn a frame later, a cut moving
        # toward the camera would show the solid's hollow inside for that frame (flicker).
        if state["cap_seconds"] <= LIVE_CAP_BUDGET_S:
            self._update_caps(build=False)
        else:  # slow cut faces: hide them until the drag ends rather than show stale ones
            state["caps"].removeAllChildren()
        self._feedback(status_text(state["label"], state["offset"]))

    def _drag_end(self):
        from pivy import coin
        state = self.state
        state["dragging"] = False
        state["plane_fill"].whichChild = coin.SO_SWITCH_NONE
        state["arrow_look"].whichChild = 0
        self._update_plane(caps=True)
        self._feedback(status_text(state["label"], state["offset"]))

    def clamp(self, offset):
        """Keep the cut within the shown parts (plus a little), so it can never be dragged away."""
        state = self.state
        box, origin, normal = state["box"], state["origin"], state["normal"]
        values = [(App.Vector(x, y, z) - origin).dot(normal) for x in (box.XMin, box.XMax)
                  for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
        margin = 0.02 * box.DiagonalLength
        return min(max(float(offset), min(values) - margin), max(values) + margin)

    def _move_clip_and_plane(self):
        from pivy import coin
        state = self.state
        point = self.point()
        state["clip"].plane.setValue(coin.SbPlane(coin.SbVec3f(*(-state["normal"])), coin.SbVec3f(*point)))
        state["plane_transform"].translation.setValue(*point)
        state["arrow_transform"].translation.setValue(*point)

    def _schedule_caps(self, delay=15):
        state = self.state
        if state["cap_pending"]:
            return
        state["cap_pending"] = True

        def run():
            if state["cap_pending"]:
                self._update_caps()
        self._later(state, delay, run)

    # -- programmatic offset (tests and future keyboard nudges) ----------------------
    def set_offset(self, offset):
        """Move the cut to ``offset`` mm along its viewer-facing normal from where it started."""
        if self.state is None:
            return False
        self.state["offset"] = self.clamp(offset)
        self._update_plane(caps=True)
        self._feedback(status_text(self.state["label"], self.state["offset"]))
        return True
