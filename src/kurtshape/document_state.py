"""Native invalidation and reference refresh at native recompute boundaries.

Ordinary changes only invalidate caches; selector work runs during recompute.
"""
import FreeCAD as App


class DocumentState:
    def __init__(self, controller):
        self.controller = controller
        self.states = {}
        App.addDocumentObserver(self)

    def state(self, doc):
        return self.states.setdefault(doc.Name, {"intent_dirty": True, "generation": 0,
                                                "refresh": True, "snapshot_pending": False})

    def invalidate(self, doc, intent=True, geometry=True):
        state = self.state(doc)
        state["intent_dirty"] |= intent
        state["refresh"] = True
        if geometry:
            state["generation"] += 1

    def slotChangedObject(self, obj, prop):
        if obj.Name == "KurtShapeProject":
            return
        if prop == "Shape" and getattr(obj, "KurtShapeEmbeddedSource", False):
            # An embedded snapshot has no parametric producer. Replacing its
            # BRep is native intent and must invalidate tokens, not look like
            # an ordinary derived recompute cache update.
            self.state(obj.Document)["assembly_source_changed"] = True
            self.invalidate(obj.Document, intent=True, geometry=True)
            return
        derived = prop in {"Shape", "InternalShape", "Proxy", "PlacementList", "Visibility"}
        self.invalidate(obj.Document, intent=not derived,
                        geometry=prop in {"Shape", "InternalShape", "Placement", "LinkPlacement", "LinkedObject", "Group"})

    def slotCreatedObject(self, obj):
        if obj.Name != "KurtShapeProject":
            self.invalidate(obj.Document)

    slotDeletedObject = slotCreatedObject

    def slotChangedDocument(self, doc, prop):
        if prop == "Label":
            self.invalidate(doc, geometry=False)

    def slotRecomputedDocument(self, doc):
        from . import studio
        studio.native_recomputed(doc)
        self.invalidate(doc, intent=False)
        if not self.controller.busy and not getattr(App, "GuiUp", False):
            self.state(doc)["snapshot_pending"] = True

    def slotRecomputedObject(self, obj):
        meta = obj.Document.getObject("KurtShapeProject")
        if not self.controller.busy and meta and self.controller.documents.get(meta.DocumentId) == obj.Document:
            from . import selectors
            selectors.native_recomputed(obj)

    def slotCommitTransaction(self, doc):
        self.invalidate(doc, intent=False, geometry=False)
        if not self.controller.busy:
            self.state(doc)["snapshot_pending"] = True

    def slotAbortTransaction(self, doc):
        self.invalidate(doc)

    slotUndoDocument = slotAbortTransaction
    slotRedoDocument = slotAbortTransaction

    def slotDeletedDocument(self, doc):
        from . import assembly, studio, selectors
        assembly.clear_cache(doc)
        studio.native_recomputed(doc)
        selectors.clear_cache(doc)
        self.states.pop(doc.Name, None)
        self.controller.evaluations.pop(doc.Name, None)
        self.controller.unmanaged.pop(doc.Name, None)

    def close(self):
        App.removeDocumentObserver(self)
