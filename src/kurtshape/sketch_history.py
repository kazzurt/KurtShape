"""Temporary native visibility at an edited sketch's shared history position."""
from __future__ import annotations

import time

import FreeCAD as App

from . import studio
from .bodies import owner


class HistoricalSketchView:
    """Expose prior native results without changing persisted rollback or Tips.

    Call enter before native setEdit, apply after native setup and managed
    refreshes, and leave after resetEdit plus successful Finish/Cancel. Native
    TempoVis can then do its own setup/cleanup without losing original states.
    """
    def __init__(self, panel=None):
        self.panel = panel
        self.document_name = None
        self.sketch_name = None
        self.original = {}
        self.desired = {}
        self.allowed = set()
        self.dirty = True
        self.next_reconcile = 0.0
        self.presentation_passes = 0
        self.closed = False
        if panel is not None:
            import FreeCADGui as Gui
            Gui.addDocumentObserver(self)
            panel.destroyed.connect(self.close)

    def invalidate(self, *args):
        self.dirty = True

    def slotChangedObject(self, obj, prop):
        if prop != "Visibility" or not self.document_name:
            return
        try:
            obj = getattr(obj, "Object", obj)
            document = getattr(obj, "Document", None)
            name = getattr(obj, "Name", None)
            relevant = document is not None and self.document_name == document.Name and name in self.desired
        except Exception:
            return  # Native provider birth/teardown can have no Object binding.
        if relevant:
            self.invalidate()

    slotInEdit = slotResetEdit = invalidate

    def document(self):
        return App.listDocuments().get(self.document_name) if self.document_name else None

    def enter(self, sketch):
        if (self.document_name, self.sketch_name) == (sketch.Document.Name, sketch.Name):
            return
        self.leave()
        doc = sketch.Document
        self.document_name, self.sketch_name = doc.Name, sketch.Name
        self.original = {obj.Name: bool(obj.ViewObject.Visibility) for obj in doc.Objects
                         if obj.ViewObject and "Visibility" in obj.ViewObject.PropertiesList}
        sequence = studio.order(doc)
        boundary = sequence.index(sketch) if sketch in sequence else len(sequence)
        positions = {obj.Name: index for index, obj in enumerate(sequence)}
        fallback = {obj.Name: index for index, obj in enumerate(doc.Objects)}

        def prior(obj):
            operation = getattr(obj, "KurtShapeOperationOwner", "")
            position = positions.get(operation or obj.Name)
            if position is not None:
                return position < boundary
            return fallback.get(obj.Name, len(fallback)) < fallback.get(sketch.Name, len(fallback))

        prior_shapes = {}
        for obj in doc.Objects:
            if obj == sketch or not prior(obj) or getattr(obj, "KurtShapeInternal", False):
                continue
            self.allowed.add(obj.Name)
            if hasattr(obj, "Shape") and obj.TypeId != "PartDesign::Body" and not obj.Shape.isNull() and obj.Shape.Solids:
                body = owner(doc, obj)
                if body and not getattr(body, "KurtShapeInternal", False):
                    prior_shapes[body.Name] = obj.Name

        # Studio output generations can consume/recreate a logical part. Native
        # history metadata identifies the actual result at the sketch boundary.
        if studio.enabled(doc):
            prior_shapes = {body.Name: tip.Name for body, tip in studio._state(doc, boundary).values() if tip}
            self.allowed.update(prior_shapes.values())
        visible_prior = set(prior_shapes.values())
        from .sketch_tools import unconsumed_sketches
        prior_sketch_bodies = {owner(doc, obj) for obj in unconsumed_sketches(doc, before=sketch)
                               if obj.Name in self.allowed and self.original.get(obj.Name, False)}
        self.desired = {}
        for obj in doc.Objects:
            if obj.Name not in self.original:
                continue
            if obj == sketch:
                visible = True
            elif obj.TypeId == "PartDesign::Body":
                visible = (obj.Name in prior_shapes or obj in prior_sketch_bodies) and bool(getattr(obj, "KurtShapePartVisible", self.original[obj.Name]))
            elif hasattr(obj, "Shape"):
                visible = (obj.Name in visible_prior or self.original[obj.Name]) and obj.Name in self.allowed
                if getattr(obj, "KurtShapeInternal", False):
                    visible = obj.Name in visible_prior
            else:
                visible = self.original[obj.Name]
            self.desired[obj.Name] = bool(visible)
        self.invalidate()
        self.apply()

    def apply(self):
        doc = self.document()
        if not doc:
            return
        now = time.monotonic()
        if not self.dirty and now < self.next_reconcile:
            return
        self.dirty = False
        self.next_reconcile = now + 0.5
        self.presentation_passes += 1
        active = self.panel.active_sketch() if self.panel is not None else None
        for name, visible in self.desired.items():
            obj = doc.getObject(name)
            if obj is not None and obj == active:
                # Sketcher's edit scene draws current solver geometry itself.
                # Showing the ordinary Shape provider alongside it leaves an
                # unselectable outline at the pre-edit position after a drag.
                # With native editing suspended to pick a new support, the
                # ordinary provider is needed again to keep the sketch visible.
                visible = False
            if obj and obj.ViewObject and obj.ViewObject.Visibility != visible:
                obj.ViewObject.Visibility = visible

    def allows_source(self, obj):
        """Reject later source geometry even if selected through another API."""
        if not self.document_name:
            return True
        if obj.Document.Name != self.document_name or obj.Name == self.sketch_name:
            return False
        if obj.TypeId == "PartDesign::Body":
            return bool(obj.Tip and obj.Tip.Name in self.allowed)
        return obj.Name in self.allowed

    def leave(self):
        doc = self.document()
        if doc:
            # Set containers first, then children: native Body visibility may
            # propagate to its Tip while restoring the containing provider.
            objects = [doc.getObject(name) for name in self.original]
            objects.sort(key=lambda obj: bool(obj and obj.TypeId != "PartDesign::Body"))
            for obj in objects:
                if obj and obj.ViewObject and obj.ViewObject.Visibility != self.original[obj.Name]:
                    obj.ViewObject.Visibility = self.original[obj.Name]
        self.document_name = self.sketch_name = None
        self.original, self.desired, self.allowed = {}, {}, set()
        self.invalidate()

    def close(self, *args):
        if self.closed:
            return
        self.closed = True
        self.leave()
        if self.panel is not None:
            import FreeCADGui as Gui
            Gui.removeDocumentObserver(self)
