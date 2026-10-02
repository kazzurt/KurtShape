"""Cheap native invalidation. Callbacks never hash, validate or rebuild geometry."""
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
        derived = prop in {"Shape", "InternalShape", "Proxy", "PlacementList", "Visibility"}
        self.invalidate(obj.Document, intent=not derived,
                        geometry=prop in {"Shape", "InternalShape"})

    def slotCreatedObject(self, obj):
        if obj.Name != "KurtShapeProject":
            self.invalidate(obj.Document)

    slotDeletedObject = slotCreatedObject

    def slotChangedDocument(self, doc, prop):
        if prop == "Label":
            self.invalidate(doc, geometry=False)

    def slotRecomputedDocument(self, doc):
        self.invalidate(doc, intent=False)
        if not self.controller.busy and not getattr(App, "GuiUp", False):
            self.state(doc)["snapshot_pending"] = True

    def slotCommitTransaction(self, doc):
        self.invalidate(doc, intent=False, geometry=False)
        if not self.controller.busy:
            self.state(doc)["snapshot_pending"] = True

    def slotAbortTransaction(self, doc):
        self.invalidate(doc)

    slotUndoDocument = slotAbortTransaction
    slotRedoDocument = slotAbortTransaction

    def slotDeletedDocument(self, doc):
        self.states.pop(doc.Name, None)
        self.controller.evaluations.pop(doc.Name, None)
        self.controller.unmanaged.pop(doc.Name, None)

    def close(self):
        App.removeDocumentObserver(self)
