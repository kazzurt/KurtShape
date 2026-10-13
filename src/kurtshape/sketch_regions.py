"""Transient, unpickable light gray faces for closed defining sketch curves.

MakeInternals persists selectable profile geometry. This drawing layer keeps
the native sketch, solver, selection and that modeling option unchanged.
"""
from __future__ import annotations
import time
import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore
from pivy import coin


def _prune_open_tails(edges):
    """Keep loops when unrelated drawing continues from a boundary vertex."""
    adjacency, endpoints, closed = {}, {}, []
    for index, edge in enumerate(edges):
        if edge.isClosed():
            closed.append(edge)
            continue
        vertices = edge.Vertexes
        if len(vertices) != 2:
            continue
        keys = tuple(tuple(round(coordinate, 7) for coordinate in (vertex.Point.x, vertex.Point.y, vertex.Point.z))
                     for vertex in vertices)
        endpoints[index] = keys
        for key in keys:
            adjacency.setdefault(key, set()).add(index)
    pending = [key for key, values in adjacency.items() if len(values) == 1]
    while pending:
        key = pending.pop()
        if len(adjacency[key]) != 1:
            continue
        index = next(iter(adjacency[key]))
        for vertex in endpoints.pop(index):
            adjacency[vertex].discard(index)
            if len(adjacency[vertex]) == 1:
                pending.append(vertex)
    return closed + [edges[index] for index in endpoints]


def region_faces(sketch):
    edges = []
    for index, geometry in enumerate(sketch.Geometry):
        if not sketch.getConstruction(index):
            try:
                edges.extend(geometry.toShape().Edges)
            except (Part.OCCError, RuntimeError, ValueError):
                continue
    for geometry in sketch.ExternalGeo[2:]:
        if geometry.hasExtensionOfType("Sketcher::ExternalGeometryExtension"):
            extension = geometry.getExtensionOfType("Sketcher::ExternalGeometryExtension")
            if extension.testFlag("Defining") and not extension.testFlag("Missing"):
                try:
                    edges.extend(geometry.toShape().Edges)
                except (Part.OCCError, RuntimeError, ValueError):
                    continue
    wires = []
    closed_edges = _prune_open_tails(edges)
    if not closed_edges:
        return []
    for wire in Part.makeCompound(closed_edges).makeWires("SketchRegions").Wires:
        try:
            if wire.isClosed() and wire.isValid():
                wires.append(wire)
        except (Part.OCCError, RuntimeError, ValueError):
            continue
    if not wires:
        return []
    try:
        return [face for face in Part.makeFace(wires, "Part::FaceMakerBullseye").Faces
                if face.isValid() and face.Area > 1e-10]
    except (Part.OCCError, RuntimeError, ValueError):
        return []


def _visible(sketch, panel):
    if not sketch.ViewObject.Visibility:
        return False
    history = panel.sketch_history
    if (history.document_name == sketch.Document.Name and history.sketch_name
            and sketch.Name != history.sketch_name and sketch.Name not in history.allowed):
        return False
    pending, visited = [sketch], set()
    while pending:
        child = pending.pop()
        for parent in child.InList:
            if parent.Name in visited or parent.TypeId not in {"PartDesign::Body", "App::Part"} or child not in parent.Group:
                continue
            visited.add(parent.Name)
            if not parent.ViewObject.Visibility:
                return False
            pending.append(parent)
    return True


class SketchRegionFill:
    COLOR = (0.92, 0.92, 0.92)

    def __init__(self, panel):
        self.panel = panel
        self.entries = {}
        self.scene = self.document_name = None
        self.closed = False
        self.builds = self.scene_writes = 0
        self.build_attempts = self.discarded_builds = 0
        self.rebuilding = False
        self.scene_generation = 0
        self.membership_scans = self.presentation_passes = 0
        self.sketches = ()
        self.membership_dirty = self.presentation_dirty = True
        self.active_name = None
        self.dragging = None
        self.next_reconcile = 0.0
        self.timer = QtCore.QTimer(panel)
        self.timer.setSingleShot(True)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._rebuild)
        App.addDocumentObserver(self)
        Gui.addDocumentObserver(self)

    def invalidate(self, *args):
        self.presentation_dirty = True

    slotInEdit = slotResetEdit = invalidate

    def _hide(self, entry):
        if entry.get("shown") and entry.get("node") is not None:
            entry["node"].whichChild = coin.SO_SWITCH_NONE
            entry["shown"] = False
            self.scene_writes += 1

    def _mark_dirty(self, entry):
        entry["dirty"] = True
        entry["generation"] = entry.get("generation", 0) + 1
        self._hide(entry)

    def event(self, watched, event):
        """Native dragging uses solver coordinates until the button is released.

        Geometry property observers cannot update a mesh during that interval.
        Hide its last committed fill rather than drawing a phantom old region,
        and wait until native release has published geometry before rebuilding.
        """
        kind = event.type()
        if kind == QtCore.QEvent.MouseMove and event.buttons() & QtCore.Qt.LeftButton:
            if watched.metaObject().className() != "QOpenGLWidget":
                return
            sketch = self.panel.active_sketch()
            if sketch is None:
                return
            key = (sketch.Document.Name, sketch.Name)
            if self.dragging != key:
                self.dragging = key
                entry = self.entries.get(key)
                if entry is not None:
                    self._hide(entry)
                self.invalidate()
        elif self.dragging is not None and (kind in {QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.WindowDeactivate}
                or (kind == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape)):
            entry = self.entries.get(self.dragging)
            self.dragging = None
            if entry is not None:
                self._mark_dirty(entry)
            self.invalidate()
            self.timer.start(80)

    def slotCreatedObject(self, obj):
        try:
            obj = getattr(obj, "Object", obj)
        except Exception:
            return  # The provider may not have its native Object binding yet.
        if obj.TypeId == "Sketcher::SketchObject":
            self.membership_dirty = True
        self.invalidate()

    def slotChangedObject(self, obj, prop):
        try:
            obj = getattr(obj, "Object", obj)
        except Exception:
            return
        if obj.TypeId == "Sketcher::SketchObject" and prop in {"Geometry", "Shape", "ExternalGeo", "ExternalGeometry"}:
            entry = self.entries.get((obj.Document.Name, obj.Name))
            if entry is not None:
                self._mark_dirty(entry)
            self.invalidate()
        elif prop in {"Visibility", "Placement", "Group", "Tip", "LinkPlacement", "LinkedObject"}:
            self.invalidate()

    def slotUndoDocument(self, doc):
        self.membership_dirty = True
        self.invalidate()
        for (document, name), entry in self.entries.items():
            if document == doc.Name:
                self._mark_dirty(entry)

    slotRedoDocument = slotAbortTransaction = slotUndoDocument

    def slotDeletedObject(self, obj):
        try:
            obj = getattr(obj, "Object", obj)
        except Exception:
            return  # The App observer still receives the native object.
        self.membership_dirty = True
        self.invalidate()
        self._drop((obj.Document.Name, obj.Name))

    def slotDeletedDocument(self, doc):
        doc = getattr(doc, "Document", doc)
        self.membership_dirty = True
        self.invalidate()
        for key in list(self.entries):
            if key[0] == doc.Name:
                self._drop(key)

    def _drop(self, key):
        entry = self.entries.pop(key, None)
        if entry is not None:
            self._remove(entry)

    def _remove(self, entry):
        if self.scene is not None and entry.get("node") is not None:
            try:
                if self.scene.findChild(entry["node"]) >= 0:
                    self.scene.removeChild(entry["node"])
                    self.scene_writes += 1
            except (RuntimeError, ReferenceError):
                pass
        entry["node"] = None

    def _clear_scene(self):
        self.scene_generation += 1
        self.timer.stop()
        for entry in self.entries.values():
            self._remove(entry)
        self.scene = None

    def _node(self, entry):
        switch = coin.SoSwitch()
        switch.setName("KurtShapeSketchRegionFill")
        switch.whichChild = coin.SO_SWITCH_NONE
        group = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        group.addChild(pick)
        depth = coin.SoDepthBuffer()
        depth.getField("write").setValue(False)
        depth.getField("function").setValue(coin.SoDepthBuffer.LESS)
        group.addChild(depth)
        transform = coin.SoMatrixTransform()
        group.addChild(transform)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        group.addChild(light)
        material = coin.SoMaterial()
        material.diffuseColor.setValue(*self.COLOR)
        group.addChild(material)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        group.addChild(hints)
        points = coin.SoCoordinate3()
        group.addChild(points)
        faces = coin.SoIndexedFaceSet()
        group.addChild(faces)
        switch.addChild(group)
        entry.update(node=switch, transform=transform, points=points, triangles=faces, placed=None, shown=False)
        self.scene.addChild(switch)
        self.scene_writes += 1

    def apply(self):
        if self.closed:
            return
        gui, doc = Gui.activeDocument(), App.ActiveDocument
        if not gui or not doc:
            if self.scene is not None:
                self._clear_scene()
            return
        scene = gui.activeView().getSceneGraph()
        if scene != self.scene:
            self._clear_scene()
            self.scene = scene
            self.invalidate()
        if self.document_name != doc.Name:
            self.membership_dirty = True
            self.invalidate()
        self.document_name = doc.Name
        active = self.panel.active_sketch()
        active_name = active.Name if active is not None else None
        if active_name != self.active_name:
            self.active_name = active_name
            self.dragging = None
            self.invalidate()
        now = time.monotonic()
        if now >= self.next_reconcile:
            # Safety reconciliation for native providers which change display
            # without exposing a property event. Ordinary ticks do no scans.
            self.membership_dirty = True
            self.invalidate()
            self.next_reconcile = now + 0.5
        if not self.presentation_dirty and not self.membership_dirty:
            return
        self.presentation_dirty = False
        self.presentation_passes += 1
        if self.membership_dirty:
            self.sketches = tuple(obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject")
            self.membership_scans += 1
            self.membership_dirty = False
        for sketch in self.sketches:
            entry = self.entries.setdefault((doc.Name, sketch.Name), {"dirty": True, "mesh": None, "node": None})
            visible = sketch == active or _visible(sketch, self.panel)
            if visible and entry["mesh"] is not None and entry["node"] is None:
                self._node(entry)
                self._write_mesh(entry)
            if entry["node"] is not None:
                shown = bool(visible and not entry["dirty"] and self.dragging != (doc.Name, sketch.Name)
                             and entry["mesh"] and entry["mesh"][1])
                if entry["shown"] != shown:
                    entry["node"].whichChild = coin.SO_SWITCH_ALL if shown else coin.SO_SWITCH_NONE
                    entry["shown"] = shown
                    self.scene_writes += 1
                if visible:
                    placement = sketch.getGlobalPlacement()
                    # Native solid faces use polygon offset; stay on the exact
                    # sketch plane. Strict LESS preserves coplanar line pixels.
                    offset = 0.0
                    signature = (tuple(placement.Matrix.A), offset)
                    if signature != entry["placed"]:
                        matrix = (placement * App.Placement(App.Vector(0, 0, offset), App.Rotation())).Matrix
                        # Coin multiplies row vectors; FreeCAD uses columns.
                        values = matrix.A
                        entry["transform"].matrix.setValue(coin.SbMatrix(*(values[column * 4 + row]
                            for row in range(4) for column in range(4))))
                        entry["placed"] = signature
                        self.scene_writes += 1
            if visible and entry["dirty"] and self.dragging != (doc.Name, sketch.Name) and not self.timer.isActive():
                self.timer.start(80)

    def _write_mesh(self, entry):
        vertices, triangles = entry["mesh"]
        entry["points"].point.setValues(0, len(vertices), vertices)
        entry["points"].point.setNum(len(vertices))
        indices = [value for triangle in triangles for value in (*triangle, -1)]
        entry["triangles"].coordIndex.setValues(0, len(indices), indices)
        entry["triangles"].coordIndex.setNum(len(indices))
        self.scene_writes += 1

    def _next_dirty(self, doc, active):
        active_key = (doc.Name, active.Name) if active is not None else None
        keys = [active_key] if active_key in self.entries else []
        keys.extend(key for key in self.entries if key != active_key and key[0] == doc.Name)
        for key in keys:
            entry = self.entries[key]
            if not entry["dirty"] or key == self.dragging:
                continue
            sketch = doc.getObject(key[1])
            if sketch is not None and (sketch == active or _visible(sketch, self.panel)):
                return key, entry, sketch
        return None

    def _rebuild(self):
        # A native geometry call cannot be preempted. Bound each turn to one
        # sketch and yield to input before working on another dirty sketch.
        if self.closed or self.rebuilding:
            return
        if self.panel.core.busy:
            self.timer.start(80)
            return
        doc = App.ActiveDocument
        if not doc or doc.Name != self.document_name:
            return
        active = self.panel.active_sketch()
        pending = self._next_dirty(doc, active)
        if pending is None:
            return
        key, entry, sketch = pending
        generation = entry.get("generation", 0)
        scene_generation, scene = self.scene_generation, self.scene
        self.rebuilding = True
        started = time.perf_counter()
        self.build_attempts += 1
        try:
            try:
                faces = region_faces(sketch)
            except (Part.OCCError, RuntimeError, ValueError):
                # A temporarily invalid drawing must clear its old fill and
                # wait for another geometry change, rather than retry on tick.
                faces = []
            vertices, triangles = [], []
            for face in faces:
                try:
                    points, indices = face.tessellate(0.1)
                except (Part.OCCError, RuntimeError, ValueError):
                    continue
                start = len(vertices)
                vertices.extend((point.x, point.y, point.z) for point in points)
                triangles.extend(tuple(start + index for index in triangle) for triangle in indices)
            area = sum(face.Area for face in faces)
            elapsed = (time.perf_counter() - started) * 1000
            self.panel.core.timings.record("sketch_region_build", elapsed)
            gui, current = Gui.activeDocument(), self.panel.active_sketch()
            if (self.closed or App.ActiveDocument != doc or self.entries.get(key) is not entry
                    or entry.get("generation", 0) != generation or self.dragging == key
                    or self.scene_generation != scene_generation or self.scene != scene
                    or not gui or gui.activeView().getSceneGraph() != scene
                    or doc.getObject(key[1]) != sketch
                    or (sketch != current and not _visible(sketch, self.panel))):
                self.discarded_builds += 1
            else:
                entry.update(mesh=(vertices, triangles), dirty=False, region_count=len(faces),
                             area=area, build_ms=elapsed)
                self.builds += 1
                if entry["node"] is None:
                    self._node(entry)
                self._write_mesh(entry)
        finally:
            self.rebuilding = False
        self.invalidate()
        self.apply()
        if not self.closed and App.ActiveDocument == doc:
            if self._next_dirty(doc, self.panel.active_sketch()) is not None:
                self.timer.start(16)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        self._clear_scene()
        self.entries.clear()
        self.sketches = ()
        App.removeDocumentObserver(self)
        Gui.removeDocumentObserver(self)
