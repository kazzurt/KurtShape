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
                                                "refresh": True, "snapshot_pending": False,
                                                "versions": {}, "shape_versions": {}, "version_clock": 0,
                                                "native_recomputed": False, "recomputed_objects": set()})

    def version(self, doc, name, shape_only=False):
        return self.state(doc)["shape_versions" if shape_only else "versions"].get(name, 0)

    def bump(self, obj, shape=False):
        state = self.state(obj.Document)
        state["version_clock"] += 1
        state["versions"][obj.Name] = state["version_clock"]
        if shape:
            state["shape_versions"][obj.Name] = state["version_clock"]

    def invalidate(self, doc, intent=True, geometry=True):
        state = self.state(doc)
        state["intent_dirty"] |= intent
        state["refresh"] = True
        if geometry:
            state["generation"] += 1
            from . import studio
            studio.native_recomputed(doc)

    def slotChangedObject(self, obj, prop):
        if obj.Name == "KurtShapeProject":
            return
        geometric = prop in {"Shape", "InternalShape", "AddSubShape", "SuppressedShape", "Placement",
                             "LinkPlacement", "LinkedObject", "Group", "Tip"}
        if geometric:
            self.bump(obj, shape=prop in {"Shape", "InternalShape", "AddSubShape", "SuppressedShape", "LinkedObject", "Tip"})
        if prop == "Shape" and getattr(obj, "KurtShapeEmbeddedSource", False):
            # An embedded snapshot has no parametric producer. Replacing its
            # BRep is native intent and must invalidate tokens, not look like
            # an ordinary derived recompute cache update.
            self.state(obj.Document)["assembly_source_changed"] = True
            self.invalidate(obj.Document, intent=True, geometry=True)
            return
        derived = prop in {"Shape", "InternalShape", "AddSubShape", "SuppressedShape", "Proxy", "PlacementList", "Visibility"}
        self.invalidate(obj.Document, intent=not derived,
                        geometry=geometric)

    def slotCreatedObject(self, obj):
        if obj.Name != "KurtShapeProject":
            self.bump(obj, shape=True)
            self.invalidate(obj.Document)

    def slotDeletedObject(self, obj):
        self.slotCreatedObject(obj)
        self.controller.geometry.drop_object(obj.Document, obj.Name)

    def slotChangedDocument(self, doc, prop):
        if prop == "Label":
            self.invalidate(doc, geometry=False)

    def slotRecomputedDocument(self, doc):
        from . import studio
        studio.native_recomputed(doc)
        self.invalidate(doc, intent=False)
        self.state(doc)["native_recomputed"] = True
        if not self.controller.busy and not getattr(App, "GuiUp", False):
            self.state(doc)["snapshot_pending"] = True

    def slotRecomputedObject(self, obj):
        self.state(obj.Document)["recomputed_objects"].add(obj.Name)

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
        self.controller.geometry.drop_document(doc.Name)
        self.controller.unmanaged.pop(doc.Name, None)

    def close(self):
        App.removeDocumentObserver(self)
