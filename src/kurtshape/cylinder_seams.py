"""Hide cylindrical parameter seams in native edge display and picking.

Only Coin line indices change; BRep geometry and EdgeN identities stay intact.
A seam keeps a collapsed two-point polyline slot: no line along the surface,
and native selection/highlight indices of following edges do not shift. Native visual
rebuilds are observed so edits, tessellation changes and linked occurrences keep
the same presentation. No periodic document scans or model mutations.
"""
from __future__ import annotations

import FreeCAD as App


def seam_indices(shape):
    """One-based indices of actual seams on cylindrical faces (not cut edges)."""
    import Part
    seams = {}
    for face in shape.Faces:
        if isinstance(face.Surface, Part.Cylinder):
            for edge in face.Edges:
                if edge.isSeam(face):
                    seams.setdefault(edge.hashCode(), []).append(edge)
    return {i for i, edge in enumerate(shape.Edges, 1)
            if any(edge.isSame(seam) for seam in seams.get(edge.hashCode(), ()))}


def masked_indices(indices, seams, edge_count):
    """Keep every native line slot, collapsing seams to their first endpoint.

    Coin skips one-point lines when assigning pick indices; two identical
    points retain the original EdgeN without drawing a segment along the face.
    """
    if indices.count(-1) != edge_count or not indices or indices[-1] != -1:
        return indices  # Unknown native layout: preserve it rather than mislabel picks.
    result, edge, first = [], 1, True
    for index in indices:
        if index == -1:
            result.append(index)
            edge, first = edge + 1, True
        elif edge not in seams or first:
            result.append(index)
            if edge in seams:
                result.append(index)
            first = False
    return result


def edge_nodes(root):
    from pivy import coin
    search = coin.SoSearchAction()
    search.setType(coin.SoType.fromName("SoBrepEdgeSet"))
    search.setInterest(coin.SoSearchAction.ALL)
    search.setSearchingAll(True)
    search.apply(root)
    return list({node.getNodeId(): node for node in
                 (path.getTail() for path in search.getPaths())}.values())


def _set_indices(node, indices):
    node.coordIndex.setNum(len(indices))
    if indices:
        node.coordIndex.setValues(0, indices)


class CylinderSeams:
    def __init__(self, panel):
        import FreeCADGui as Gui
        from PySide import QtCore
        self.pending = {}
        self.entries = {}
        self.closed = False
        self.updates = 0
        self.timer = QtCore.QTimer(panel)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.flush)
        App.addDocumentObserver(self)
        Gui.addDocumentObserver(self)
        for doc in App.listDocuments().values():
            self.queue_document(doc)

    def queue(self, obj, geometry=False):
        if self.closed:
            return
        try:
            obj = getattr(obj, "Object", obj)
            if not obj.isDerivedFrom("Part::Feature") or obj.TypeId == "Sketcher::SketchObject":
                return
            key = (obj.Document.Name, obj.Name)
            self.pending[key] = (obj, geometry or self.pending.get(key, (None, False))[1])
            if not self.timer.isActive():
                self.timer.start(0)
        except (RuntimeError, ReferenceError, AttributeError):
            pass  # Provider not bound yet, or object being deleted.

    def queue_document(self, doc):
        doc = getattr(doc, "Document", doc)
        for obj in doc.Objects:
            self.queue(obj, True)

    slotFinishRestoreDocument = slotUndoDocument = slotRedoDocument = slotAbortTransaction = queue_document

    def slotCreatedObject(self, obj):
        self.queue(obj, True)

    def slotChangedObject(self, obj, prop):
        if prop in {"Shape", "Tip"}:
            self.queue(obj, True)
        elif prop in {"Visibility", "DisplayMode", "Deviation", "AngularDeflection"}:
            self.queue(obj)

    def slotRecomputedObject(self, obj):
        self.queue(obj, True)

    def _drop(self, key, restore=False):
        entry = self.entries.pop(key, None)
        if entry:
            for node, sensor, original, masked in entry["nodes"]:
                sensor.detach()
                if restore and list(node.coordIndex.getValues()) == masked:
                    _set_indices(node, original)

    def slotDeletedObject(self, obj):
        try:
            obj = getattr(obj, "Object", obj)
            key = (obj.Document.Name, obj.Name)
            self.pending.pop(key, None)
            self._drop(key)
        except (RuntimeError, ReferenceError, AttributeError):
            pass

    def slotDeletedDocument(self, doc):
        doc = getattr(doc, "Document", doc)
        for key in list(self.entries.keys() | self.pending.keys()):
            if key[0] == doc.Name:
                self.pending.pop(key, None)
                self._drop(key)

    def flush(self):
        from pivy import coin
        pending, self.pending = self.pending, {}
        for key, (obj, geometry) in pending.items():
            try:
                entry = self.entries.get(key)
                if entry is None or geometry:
                    shape = obj.Shape
                    seams, count = seam_indices(shape), len(shape.Edges)
                else:
                    seams, count = entry["seams"], entry["count"]
                if not seams:
                    self._drop(key, restore=True)
                    continue
                nodes = edge_nodes(obj.ViewObject.RootNode)
                previous = {row[0]: row for row in entry["nodes"]} if entry else {}
                rows = []
                for node in nodes:
                    current = list(node.coordIndex.getValues())
                    old = previous.pop(node, None)
                    if old:
                        old[1].detach()
                    original = old[2] if old and current == old[3] else current
                    masked = masked_indices(original, seams, count)
                    if current != masked:
                        _set_indices(node, masked)
                        self.updates += 1
                    sensor = coin.SoFieldSensor(lambda *_args, target=obj: self.queue(target), None)
                    sensor.attach(node.coordIndex)
                    rows.append((node, sensor, original, masked))
                for row in previous.values():
                    row[1].detach()
                self.entries[key] = {"seams": seams, "count": count, "nodes": rows}
            except (RuntimeError, ReferenceError, AttributeError, ValueError, TypeError) as exc:
                self._drop(key, restore=True)
                App.Console.PrintWarning("Cylinder seam display: %s\n" % exc)

    def close(self):
        import FreeCADGui as Gui
        self.closed = True
        self.timer.stop()
        App.removeDocumentObserver(self)
        Gui.removeDocumentObserver(self)
        self.pending.clear()
        for key in list(self.entries):
            self._drop(key, restore=True)
