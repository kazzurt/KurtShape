"""Native sketch point states and Block colors without solving or changing geometry.

The pinned native renderer colors points by whole-curve state. Its cached
dependency API supplies point states, but returns the start position for end
and center entries too. Single-point geometry remains unambiguous. For curves
with multiple points, active constraints prove fixed endpoints; otherwise an
ambiguous point remains blue. Native errors and highlights retain their colors.
"""
from __future__ import annotations

import time


def _highlighted_elements(sketch):
    import FreeCADGui as Gui
    curves, points = set(), set()
    for selection in [*Gui.Selection.getSelectionEx(), Gui.Selection.getPreselection()]:
        if (getattr(selection, "DocumentName", "") != sketch.Document.Name
                or getattr(selection, "ObjectName", "") != sketch.Name):
            continue
        for name in selection.SubElementNames:
            element = name.lower()
            if element.startswith("edge") and element[4:].isdigit():
                curves.add(int(element[4:]) - 1)
            elif element.startswith("vertex") and element[6:].isdigit():
                try:
                    points.add(tuple(sketch.getGeoVertexIndex(int(element[6:]) - 1)))
                except (IndexError, ValueError, RuntimeError):
                    # Native Undo/Delete can retain a stale selection briefly.
                    continue
    return curves, points


def _slots(geometry):
    kind = geometry.TypeId
    if kind == "Part::GeomPoint":
        return 0, 1
    if kind in {"Part::GeomLineSegment", "Part::GeomBSplineCurve"}:
        return 1, 2
    if kind in {"Part::GeomCircle", "Part::GeomEllipse", "Part::GeomHyperbola", "Part::GeomParabola"}:
        return 1, 1
    if kind.startswith("Part::GeomArcOf"):
        return 1, 3
    return None


def _positions(geometry):
    counts = _slots(geometry)
    if counts is None:
        return ()
    curves, points = counts
    return (3,) if points == 1 and curves else tuple(range(1, points + 1))


def _fixed_points(sketch, facades, constraints, dependencies):
    """Combine cached native diagnosis with proofs for ambiguous point indices."""
    from collections import Counter
    free_counts = Counter(index for index, position in dependencies if position)
    blocked = {constraint.First for constraint in constraints if constraint.Type == "Block" and constraint.IsActive}
    axes = {}
    relations, symmetric = [], []
    def locked(key):
        # Origin and projected external geometry have no movable parameters.
        return {0, 1} if key[0] < 0 else axes.setdefault(key, set())
    for index, facade in enumerate(facades):
        positions = _positions(facade.Geometry)
        if sketch.FullyConstrained or free_counts[index] == 0 or index in blocked:
            for position in positions:
                axes[index, position] = {0, 1}
    for constraint_index, constraint in enumerate(constraints):
        if not constraint.IsActive:
            continue
        first = (constraint.First, constraint.FirstPos)
        second = (constraint.Second, constraint.SecondPos)
        kind = constraint.Type
        if kind == "Coincident":
            relations.append((first, second, {0, 1}))
        elif kind in {"DistanceX", "DistanceY"}:
            if not constraint.Driving or first[1] == 0:
                continue
            axis = 0 if kind == "DistanceX" else 1
            if second[1]:
                relations.append((first, second, {axis}))
            else:
                locked(first).add(axis)
        elif kind in {"Horizontal", "Vertical"}:
            if first[1] and second[1]:
                relations.append((first, second, {1 if kind == "Horizontal" else 0}))
            elif first[0] >= 0 and facades[first[0]].Geometry.TypeId == "Part::GeomLineSegment":
                relations.append(((first[0], 1), (first[0], 2), {1 if kind == "Horizontal" else 0}))
        elif kind == "Symmetric" and first[1] and second[1] and constraint.ThirdPos:
            symmetric.append((first, second, (constraint.Third, constraint.ThirdPos)))
    changed = True
    while changed:
        changed = False
        for first, second, shared in relations:
            known = (locked(first) | locked(second)) & shared
            for key in (first, second):
                before = len(locked(key))
                locked(key).update(known)
                changed |= len(locked(key)) != before
        for points in symmetric:
            for axis in (0, 1):
                if sum(axis in locked(key) for key in points) >= 2:
                    for key in points:
                        before = len(locked(key))
                        locked(key).add(axis)
                        changed |= len(locked(key)) != before
    return {key for key, known in axes.items() if len(known) == 2}


class NativeSketchColors:
    def __init__(self, panel):
        import FreeCAD as App
        import FreeCADGui as Gui
        self.panel = panel
        self.signature = None
        self.targets = ()
        self.writes = 0
        self.mapping_reads = self.scene_searches = self.color_passes = 0
        self.sketch = self.scene = None
        self.nodes = {}
        self.node_versions = ()
        self.mapping_dirty = self.bindings_dirty = True
        self.next_reconcile = 0.0
        self.closed = False
        App.addDocumentObserver(self)
        Gui.addDocumentObserver(self)

    def invalidate(self, *args):
        self.mapping_dirty = self.bindings_dirty = True

    def slotChangedObject(self, obj, prop):
        try:
            obj = getattr(obj, "Object", obj)
        except Exception:
            return  # A native ViewProvider can notify before Object is bound.
        if self.sketch is not None and obj == self.sketch:
            self.invalidate()

    def slotRecomputedDocument(self, doc):
        if self.sketch is not None and self.sketch.Document == doc:
            self.invalidate()

    slotUndoDocument = slotRedoDocument = slotAbortTransaction = slotRecomputedDocument
    slotInEdit = slotResetEdit = invalidate

    def slotDeletedObject(self, obj):
        try:
            obj = getattr(obj, "Object", obj)
        except Exception:
            return  # The App observer owns cleanup after a provider detaches.
        if obj == self.sketch:
            self._reset()

    def slotDeletedDocument(self, doc):
        doc = getattr(doc, "Document", doc)
        if self.sketch is not None and self.sketch.Document == doc:
            self._reset()

    def _reset(self):
        self.signature = None
        self.targets = ()
        self.sketch = self.scene = None
        self._release_bindings()
        self.invalidate()
        self.next_reconcile = 0.0

    def _release_bindings(self):
        # Native edit managers can remove their scene before the next tick.
        # Keep cached material pointers alive until our binding is replaced.
        for node in self.nodes.values():
            if node is not None:
                node.unref()
        self.nodes = {}
        self.node_versions = ()

    def close(self):
        if self.closed:
            return
        import FreeCAD as App
        import FreeCADGui as Gui
        self.closed = True
        App.removeDocumentObserver(self)
        Gui.removeDocumentObserver(self)
        self._reset()

    def _mapping(self, sketch):
        self.mapping_reads += 1
        constraints = sketch.Constraints
        active_blocks = {constraint.First for constraint in constraints
                         if constraint.Type == "Block" and constraint.IsActive}
        facades = sketch.GeometryFacadeList
        states = tuple((facade.Geometry.TypeId, facade.GeometryLayerId,
                        facade.Construction, str(facade.InternalType), facade.Blocked)
                       for facade in facades)
        constraint_states = tuple((constraint.Type, constraint.First, constraint.FirstPos,
                                   constraint.Second, constraint.SecondPos, constraint.Third,
                                   constraint.ThirdPos, constraint.IsActive, constraint.Driving, constraint.Value)
                                  for index, constraint in enumerate(constraints))
        dependencies = tuple(sketch.getGeometryWithDependentParameters())
        signature = (sketch.Document.Name, sketch.Name, states, constraint_states, dependencies, sketch.FullyConstrained)
        if signature == self.signature:
            return self.targets
        self.signature = signature
        fixed_points = _fixed_points(sketch, facades, constraints, dependencies)
        curves, points, targets = {}, {}, []
        for index, facade in enumerate(facades):
            counts = _slots(facade.Geometry)
            # Native layer zero is the standard internal geometry layer. Other
            # layer/group implementations require their own native Coin map.
            if counts is None or facade.GeometryLayerId != 0:
                self.targets = ()
                return self.targets
            sublayer = 1 if facade.Construction else 0
            internal = str(facade.InternalType) not in {"None", "0"}
            if internal:
                # Internal alignment has its own native color policy. Avoid
                # assuming the pinned manager's unexposed sublayer ordinal.
                sublayer = "internal"
            curve_count, point_count = counts
            curve_start = curves.get(sublayer, 0)
            point_start = points.get(0, 0)
            if facade.Blocked and index in active_blocks and not internal:
                targets.extend(("CurvesMaterials" + str(sublayer), offset, index, 0) for offset in
                               range(curve_start, curve_start + curve_count))
            targets.extend(("PointsMaterials_0", point_start + local, index, position,
                            (0.0, 0.0, 0.0) if (index, position) in fixed_points else (0.0, 0.0, 1.0))
                           for local, position in enumerate(_positions(facade.Geometry)))
            curves[sublayer] = curve_start + curve_count
            points[0] = point_start + point_count
        self.targets = tuple(targets)
        return self.targets

    def apply(self):
        if self.closed:
            return
        sketch = self.panel.active_sketch()
        if sketch is None:
            if self.sketch is not None:
                self._reset()
            return
        import FreeCADGui as Gui
        import FreeCAD as App
        from pivy import coin
        scene = Gui.activeDocument().activeView().getSceneGraph()
        now = time.monotonic()
        if sketch != self.sketch or scene != self.scene:
            self._reset()
            self.sketch, self.scene = sketch, scene
        if now >= self.next_reconcile:
            # Native edit managers can replace their private Coin nodes without
            # a document property signal. Rebind conservatively twice a second,
            # not on each 25 ms panel tick.
            self.invalidate()
            self.next_reconcile = now + 0.5
        if self.mapping_dirty:
            self.targets = self._mapping(sketch)
            self.mapping_dirty = False
        targets = self.targets
        if not targets:
            if self.nodes:
                self._release_bindings()
            return
        if self.bindings_dirty:
            self._release_bindings()
            for name in dict.fromkeys(target[0] for target in targets):
                search = coin.SoSearchAction()
                search.setName(name)
                search.setInterest(coin.SoSearchAction.ALL)
                search.apply(scene)
                self.scene_searches += 1
                paths = search.getPaths()
                node = paths[0].getTail() if paths.getLength() == 1 else None
                if node is not None:
                    node.ref()
                self.nodes[name] = node
            self.bindings_dirty = False
            self.node_versions = ()
        # Coin changes a node's ID after field notifications, including native
        # selection/solver recoloring. This constant-size check preserves native
        # highlight responsiveness without scanning geometry or every color.
        versions = tuple((name, node.getNodeId() if node is not None else None)
                         for name, node in self.nodes.items())
        if versions == self.node_versions:
            return
        self.color_passes += 1
        selected_curves, selected_points = _highlighted_elements(sketch)
        packed = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("ConstrainedIcoColor")
        coincident_color = tuple(((packed >> shift) & 255) / 255.0 for shift in (24, 16, 8))
        invalid = ("Invalid" in sketch.State or any(getattr(sketch, name, ()) for name in
                   ("ConflictingConstraints", "RedundantConstraints", "MalformedConstraints", "PartiallyRedundantConstraints")))
        for target in targets:
            name, offset, index, position = target[:4]
            wanted = target[4] if len(target) == 5 else (0.0, 0.0, 0.0)
            if (position == 0 and index in selected_curves) or (index, position) in selected_points:
                continue
            node = self.nodes[name]
            if node is None or offset >= node.diffuseColor.getNum():
                continue
            color = tuple(node.diffuseColor[offset].getValue())
            candidates = ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0)) + ((coincident_color,) if position else ())
            ordinary = any(max(abs(a-b) for a, b in zip(color, candidate)) < .0001 for candidate in candidates)
            if ordinary and not invalid and color != wanted:
                node.diffuseColor.set1Value(offset, wanted)
                self.writes += 1
        self.node_versions = tuple((name, node.getNodeId() if node is not None else None)
                                   for name, node in self.nodes.items())
