"""Native invalidation and reference refresh at native recompute boundaries.

Ordinary changes only invalidate caches; selector work runs during recompute.
"""
import FreeCAD as App
from collections import deque
import uuid
from . import document_index

_SHAPES = frozenset({"Shape", "InternalShape", "AddSubShape", "SuppressedShape"})
_METADATA = frozenset({"Label", "Visibility", "QueryHealth", "QueryResolutionLog",
                       "KurtShapePartName", "KurtShapePartColor", "KurtShapePartVisible"})
_DERIVED = _SHAPES | {"Proxy", "PlacementList", "Visibility", "QueryHealth", "QueryResolutionLog"}
_HISTORY_METADATA = {"KurtShapeFeatureOrder", "KurtShapeRollbackIndex", "KurtShapeStudioEnabled"}


class DocumentState:
    def __init__(self, controller):
        self.controller = controller
        self.states = {}
        App.addDocumentObserver(self)

    def state(self, doc):
        state = self.states.get(doc.Name)
        if state is None or state["index"].document != doc:
            state = {"intent_dirty": True, "generation": 0,
                     "refresh": True, "snapshot_pending": False,
                     "versions": {}, "shape_versions": {}, "version_clock": 0,
                     "native_recomputed": False, "recomputed_objects": set(),
                     "instance_id": uuid.uuid4().hex,
                     "intent_versions": {}, "summary_versions": {},
                     "intent_epoch": 0, "summary_epoch": 0,
                     "change_serial": 0, "full_change_serial": 0,
                     "change_log": deque(maxlen=2048),
                     "index": document_index.DocumentIndex(doc)}
            self.states[doc.Name] = state
        document_index.bind(state["index"])
        return state

    def version(self, doc, name, shape_only=False):
        return self.state(doc)["shape_versions" if shape_only else "versions"].get(name, 0)

    def bump(self, obj, shape=False):
        state = self.state(obj.Document)
        state["version_clock"] += 1
        state["versions"][obj.Name] = state["version_clock"]
        if shape:
            state["shape_versions"][obj.Name] = state["version_clock"]

    def _record_change(self, doc, name, prop, *, intent=False, domains=None, full=False):
        state = self.state(doc)
        state["change_serial"] += 1
        serial = state["change_serial"]
        domains = document_index.DERIVED_DOMAINS if domains is None else frozenset(domains)
        state["change_log"].append((serial, name, prop, domains))
        if name:
            state["summary_versions"][name] = serial
            if intent:
                state["intent_versions"][name] = serial
        if full:
            state["intent_epoch"] += 1
            state["summary_epoch"] += 1
            state["full_change_serial"] = serial
        return state

    def changes_since(self, doc, serial):
        """Each consumer owns a cursor; overflow/restore requires full reconciliation."""
        state = self.state(doc)
        journal = state["change_log"]
        full = (serial < state["full_change_serial"] or serial > state["change_serial"]
                or bool(journal and serial < journal[0][0] - 1))
        objects, domains = {}, set()
        for sequence, name, prop, changed_domains in journal:
            if sequence <= serial:
                continue
            domains.update(changed_domains)
            if name:
                objects.setdefault(name, set()).add(prop)
        return {"serial": state["change_serial"], "full": full,
                "objects": {name: frozenset(props) for name, props in objects.items()},
                "domains": frozenset(domains)}

    def invalidate(self, doc, intent=True, geometry=True, changed=None):
        state = self.state(doc)
        state["intent_dirty"] |= intent
        state["refresh"] = True
        if changed is None:
            if intent:
                self._record_change(doc, None, "$invalidate", full=True)
            else:
                state["summary_epoch"] += 1
        if geometry:
            state["generation"] += 1
            from . import studio
            studio.native_recomputed(doc)

    def slotChangedObject(self, obj, prop):
        if obj.Name == "KurtShapeProject":
            if prop in _HISTORY_METADATA:
                state = self._record_change(obj.Document, obj.Name, prop, domains={"history"})
                state["index"].invalidate(domains={"history"})
            return
        structure = prop in {"Group", "Origin", "OriginFeatures"}
        domains = (document_index.DOMAINS if structure else {"topology"} if prop in _SHAPES
                   else {"placement"} if prop in {"Placement", "LinkPlacement"}
                   else {"metadata"} if prop in _METADATA else document_index.DERIVED_DOMAINS)
        embedded_shape = prop == "Shape" and getattr(obj, "KurtShapeEmbeddedSource", False)
        authored = prop not in _DERIVED or embedded_shape
        if prop in {"AddSubShape", "SuppressedShape"}:
            try:
                authored = "Shape" not in obj.getTypeIdOfProperty(prop)
            except (AttributeError, RuntimeError):
                authored = True
        state = self._record_change(obj.Document, obj.Name, prop, intent=authored, domains=domains)
        state["index"].invalidate(structure=structure, domains=domains)
        geometric = prop in _SHAPES | {"Placement", "LinkPlacement", "LinkedObject", "Group", "Tip"}
        if geometric:
            self.bump(obj, shape=prop in _SHAPES | {"LinkedObject", "Tip"})
        if embedded_shape:
            # An embedded snapshot has no parametric producer. Replacing its
            # BRep is native intent and must invalidate tokens, not look like
            # an ordinary derived recompute cache update.
            state["assembly_source_changed"] = True
        self.invalidate(obj.Document, intent=authored, geometry=geometric, changed=obj.Name)

    def slotCreatedObject(self, obj):
        state = self._record_change(obj.Document, obj.Name, "$created",
                                    intent=obj.Name != "KurtShapeProject", domains=document_index.DOMAINS)
        state["index"].invalidate(structure=True)
        if obj.Name != "KurtShapeProject":
            self.bump(obj, shape=True)
            self.invalidate(obj.Document, changed=obj.Name)

    def slotDeletedObject(self, obj):
        state = self._record_change(obj.Document, obj.Name, "$deleted", intent=True, domains=document_index.DOMAINS)
        state["index"].invalidate(structure=True)
        self.bump(obj, shape=True)
        self.invalidate(obj.Document, changed=obj.Name)
        self.controller.geometry.drop_object(obj.Document, obj.Name)

    def slotAppendDynamicProperty(self, obj, prop):
        state = self._record_change(obj.Document, obj.Name, prop, intent=obj.Name != "KurtShapeProject")
        state["index"].invalidate()
        if obj.Name != "KurtShapeProject":
            self.invalidate(obj.Document, geometry=False, changed=obj.Name)

    slotRemoveDynamicProperty = slotAppendDynamicProperty

    def slotChangedDocument(self, doc, prop):
        if prop == "Label":
            self._record_change(doc, None, "Label", domains={"metadata"})
            self.invalidate(doc, geometry=False, changed="")

    def slotRecomputedDocument(self, doc):
        state = self._record_change(doc, None, "$recomputed", domains={"topology"})
        state["index"].invalidate(domains={"topology"})
        state["summary_epoch"] += 1
        self.invalidate(doc, intent=False, changed="")
        state["native_recomputed"] = True
        if not self.controller.busy and not getattr(App, "GuiUp", False):
            self.state(doc)["snapshot_pending"] = True

    def slotRecomputedObject(self, obj):
        state = self._record_change(obj.Document, obj.Name, "$recomputed", domains={"topology"})
        state["index"].invalidate(domains={"topology"})
        state["recomputed_objects"].add(obj.Name)

    def slotCommitTransaction(self, doc):
        state = self._record_change(doc, None, "$commit")
        state["index"].invalidate()
        self.invalidate(doc, intent=False, geometry=False, changed="")
        if not self.controller.busy:
            self.state(doc)["snapshot_pending"] = True

    def slotAbortTransaction(self, doc):
        state = self._record_change(doc, None, "$restore", domains=document_index.DOMAINS, full=True)
        state["index"].invalidate(structure=True)
        self.invalidate(doc, changed="")

    slotUndoDocument = slotAbortTransaction
    slotRedoDocument = slotAbortTransaction

    def slotFinishRestoreDocument(self, doc):
        state = self._record_change(doc, None, "$restore", domains=document_index.DOMAINS, full=True)
        state["index"].invalidate(structure=True)
        self.invalidate(doc, changed="")

    def slotDeletedDocument(self, doc):
        from . import assembly, studio, selectors
        assembly.clear_cache(doc)
        studio.native_recomputed(doc)
        selectors.clear_cache(doc)
        state = self.states.pop(doc.Name, None)
        if state is not None:
            snapshots = getattr(self.controller, "snapshots", None)
            if snapshots is not None:
                snapshots.retire_document(state["instance_id"])
            document_index.unbind(state["index"])
        self.controller.geometry.drop_document(doc.Name)
        self.controller.unmanaged.pop(doc.Name, None)

    def close(self):
        App.removeDocumentObserver(self)
        for state in self.states.values():
            document_index.unbind(state["index"])
        self.states.clear()
