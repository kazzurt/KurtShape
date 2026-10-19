"""Strict native snapshots for validation; never an application idle-path hook.

Only actual Origin/OriginFeatures members may treat native hashCode as an
observation. Their complete serialized content and frame stay authoritative.

Views over a snapshot (contract 3.2 oracles):
- the strict record without ``gui``: paths that must not recompute the source
  (preview, batch preview, headless render, pre-mutation rejections);
- ``content_view``: rejected managed edits and batch rollback, which recompute
  during rollback and so renew raw hashCode leaves and the metadata object's
  touched state while the BRep content stays identical;
- ``gui_invariants``: GUI comparisons, never the raw ``gui.camera``.
"""
import copy
import hashlib
import re


INTRINSIC_TYPES = frozenset({"App::Origin", "App::Line", "App::Plane", "App::Point"})
SHAPE_PROPERTIES = ("Shape", "InternalShape", "AddSubShape", "SuppressedShape")
# Kept literal (equal to kurtshape.core.METADATA) so views stay pure data functions.
PROJECT_METADATA = "KurtShapeProject"
CONTENT_VIEW_MASK = ("gui", "objects[*].shapes[*].hash_code",
                     "objects[name=" + PROJECT_METADATA + "].state",
                     "objects[name=" + PROJECT_METADATA + "].status")
_CAMERA_CLIP = re.compile(r"^\s*(?:nearDistance|farDistance)\s+.*$", re.MULTILINE)


def placement_record(value):
    return {"base": [value.Base.x, value.Base.y, value.Base.z],
            "rotation": list(value.Rotation.Q)}


def _origin_members(objects):
    members = {}
    for owner in objects:
        if "Origin" not in owner.PropertiesList:
            continue
        origin = owner.Origin
        if origin is None or origin.TypeId != "App::Origin":
            continue
        for obj in (origin, *origin.OriginFeatures):
            if obj.Document != owner.Document:
                raise ValueError("Origin member belongs to another native document")
            membership = {"owner": owner.Name, "origin": origin.Name}
            previous = members.get(obj.Name)
            if previous is not None and previous[1] != membership:
                raise ValueError("Ambiguous native Origin ownership")
            members[obj.Name] = (obj, membership)
    return members


def _shape_record(shape, intrinsic):
    # The caller reads the native Shape getter once. Every observation below
    # refers to that same handle, including allocating origin datum getters.
    raw_hash = shape.hashCode()
    null = shape.isNull()
    strict = {"null": null, "placement": placement_record(shape.Placement),
              "brep_sha256": None, "brep_bytes": 0}
    observed = {"hash_code": raw_hash, "raw_brep_sha256": None, "raw_brep_bytes": 0}
    if not intrinsic:
        strict["hash_code"] = raw_hash
    if not null:
        raw = shape.exportBrepToString()
        raw_bytes = raw.encode("utf-8")
        raw_digest = hashlib.sha256(raw_bytes).hexdigest()
        content = raw_bytes
        if intrinsic:
            # Use the existing narrow Checked-cache mask without changing it.
            # Unsupported serialization fails closed rather than losing data.
            from kurtshape.assembly import canonical_brep
            content = canonical_brep(raw).encode("utf-8")
        strict.update(brep_sha256=hashlib.sha256(content).hexdigest(), brep_bytes=len(content))
        observed.update(raw_brep_sha256=raw_digest, raw_brep_bytes=len(raw_bytes))
    return strict, observed


def _gui_record(doc):
    import FreeCAD as App
    if not App.GuiUp:
        return {"available": False, "reason": "Headless native process; GUI state was not observed"}
    import FreeCADGui as Gui
    gui_doc = Gui.getDocument(doc.Name)
    view = gui_doc.activeView()
    return {"available": True, "modified": bool(gui_doc.Modified),
            "camera_available": view is not None,
            "camera": view.getCamera() if view is not None else None,
            "selection": [{"document": item.Object.Document.Name, "object": item.Object.Name,
                           "subelements": list(item.SubElementNames),
                           "points": [[point.x, point.y, point.z] for point in item.PickedPoints]}
                          for item in Gui.Selection.getSelectionEx()]}


def snapshot_document(doc, core):
    """Read strict document/content invariants and separate datum observations.

    No inspection, validity computation, recompute, native registration, event
    processing, cleaning or copying occurs. The caller owns the document and
    captures snapshots outside measured operation intervals.
    """
    from kurtshape.core import METADATA, intent_signature
    # _meta() can create native project metadata. Read only already-existing
    # registration, and reject unknown documents before any Shape getter.
    meta = core.unmanaged.get(doc.Name)
    if meta is None:
        meta = doc.getObject(METADATA)
    if meta is None:
        raise ValueError("Native snapshot requires existing document registration")
    try:
        revision = meta.Revision
    except AttributeError as exc:
        raise ValueError("Existing document registration has no Revision") from exc
    objects = list(doc.Objects)
    members = _origin_members(objects)
    rows, observations = [], {}
    for obj in objects:
        membership = members.get(obj.Name)
        intrinsic = (obj.TypeId in INTRINSIC_TYPES and membership is not None
                     and membership[0] == obj)
        row = {"name": obj.Name, "type_id": obj.TypeId, "label": obj.Label,
               "state": list(obj.State), "status": obj.getStatusString(),
               "intrinsic_origin_member": intrinsic,
               "origin_membership": membership[1] if intrinsic else None,
               "role": obj.Role if "Role" in obj.PropertiesList else None,
               "tip": obj.Tip.Name if "Tip" in obj.PropertiesList and obj.Tip is not None else None,
               "group": [member.Name for member in obj.Group] if "Group" in obj.PropertiesList else None,
               "origin_features": [member.Name for member in obj.OriginFeatures]
                                  if "OriginFeatures" in obj.PropertiesList else None,
               "placement": placement_record(obj.Placement) if "Placement" in obj.PropertiesList else None,
               "global_placement": placement_record(obj.getGlobalPlacement())
                                   if obj.TypeId != "App::Link" and hasattr(obj, "getGlobalPlacement") else None,
               "shapes": {}}
        for prop in SHAPE_PROPERTIES:
            native_property = prop in obj.PropertiesList
            if not native_property and prop != "Shape":
                continue
            if native_property:
                shape = getattr(obj, prop)
            else:
                # Some intrinsic datums expose Shape as a computed getter,
                # rather than a persisted property. Do not read it via hasattr
                # first, which would allocate a second unrelated native handle.
                try:
                    shape = getattr(obj, prop)
                except AttributeError:
                    continue
            facts, raw = _shape_record(shape, intrinsic)
            facts["native_property"] = native_property
            facts["property_status"] = list(obj.getPropertyStatus(prop)) if native_property else None
            row["shapes"][prop] = facts
            if intrinsic:
                observations.setdefault(obj.Name, {})[prop] = raw
        # Explicit absence distinguishes Origin containers without Shape from
        # a null native Shape, while every extra shape property stays compared.
        row["shape_present"] = "Shape" in row["shapes"]
        rows.append(row)
    strict = {"name": doc.Name, "label": doc.Label, "filename": doc.FileName,
              "revision": revision, "intent_sha256": intent_signature(doc),
              "use_hasher": bool(doc.UseHasher), "undo_mode": doc.UndoMode,
              "undo_count": doc.UndoCount, "redo_count": doc.RedoCount,
              "undo_names": list(doc.UndoNames), "redo_names": list(doc.RedoNames),
              "pending_transaction": bool(doc.HasPendingTransaction), "objects": rows,
              "gui": _gui_record(doc)}
    return {"strict": strict, "observations": observations,
            "policy": "Only exact native Origin-owned intrinsic types exclude raw hashCode; "
                      "their full BRep masks only the verified Checked cache bit. "
                      "Every model hash and full raw BRep remains strict."}


def parameter_record(doc):
    """The document's marked parameter set read natively (C32): {name: [type id, value, formula]} or None."""
    for obj in doc.Objects:
        try:
            if not obj.isDerivedFrom("App::VarSet") or not obj.getPropertyByName("KurtShapeParameterSet"):
                continue
        except Exception:
            continue
        record = {}
        formulas = {path.lstrip("."): text for path, text in obj.ExpressionEngine}
        for name in obj.PropertiesList:
            if name in {"ExpressionEngine", "Label", "Label2", "Visibility"} or name.startswith("KurtShape"):
                continue
            value = obj.getPropertyByName(name)
            record[name] = [obj.getTypeIdOfProperty(name), float(value.Value if hasattr(value, "Value") else value),
                            formulas.get(name)]
        return {"id": obj.Name, "label": obj.Label, "parameters": record}
    return None


def strict_record(snapshot):
    """Accept a snapshot_document() result or its strict record."""
    if not isinstance(snapshot, dict):
        raise TypeError("Expected a snapshot_document() result or its strict record")
    record = snapshot.get("strict", snapshot) if "objects" not in snapshot else snapshot
    if not isinstance(record, dict) or not isinstance(record.get("objects"), list):
        raise ValueError("Snapshot has no strict object rows")
    return record


def without_gui(snapshot):
    """The strict record without the raw GUI record (camera, selection, Modified)."""
    view = copy.deepcopy(strict_record(snapshot))
    view.pop("gui", None)
    return view


def content_view(snapshot):
    """The strict record minus exactly the CONTENT_VIEW_MASK fields.

    Drops ``gui``, every row's ``shapes.*.hash_code`` (raw native hashCode leaves
    change on every recompute) and the KurtShapeProject row's ``state`` and
    ``status`` (a managed rollback recomputes and touches it). BRep digests and
    sizes, placements, other rows' states, revision, intent hash and undo/redo
    names stay compared. The input is never modified.
    """
    view = without_gui(snapshot)
    for row in view["objects"]:
        for facts in row.get("shapes", {}).values():
            facts.pop("hash_code", None)
        if row.get("name") == PROJECT_METADATA:
            row.pop("state", None)
            row.pop("status", None)
    return view


def normalise_camera(text):
    """An Inventor camera string with its nearDistance/farDistance lines blanked.

    The clipping distances follow the scene bounds, not the user's view, so a
    recompute may move them; every other camera field (type, position,
    orientation, focal distance, height) is kept verbatim. Empty input gives None.
    """
    return _CAMERA_CLIP.sub("", text) if text else None


def gui_invariants(doc):
    """GUI state a request must leave alone, comparable across ticks.

    Records the active App/Gui document names, each object's ViewObject
    Visibility, the GUI Modified flag, the camera with its nearDistance and
    farDistance lines removed (they follow the scene bounds), the selection with
    sub-elements and picked points, the object in edit and the active task
    dialog. Headless processes report ``available: False``.
    """
    import FreeCAD as App
    if not App.GuiUp:
        return {"available": False, "reason": "Headless native process; GUI state was not observed"}
    import FreeCADGui as Gui
    gui_doc = Gui.getDocument(doc.Name)
    active_gui = Gui.activeDocument()
    active_app = App.ActiveDocument
    view = gui_doc.activeView() if gui_doc is not None else None
    camera = view.getCamera() if view is not None and hasattr(view, "getCamera") else None
    in_edit = gui_doc.getInEdit() if gui_doc is not None else None
    dialog = Gui.Control.activeDialog()
    visibility = {}
    for obj in doc.Objects:
        view_object = getattr(obj, "ViewObject", None)
        if view_object is not None:
            visibility[obj.Name] = bool(view_object.Visibility)
    return {"available": True,
            "active_document": active_app.Name if active_app is not None else None,
            "active_gui_document": active_gui.Document.Name if active_gui is not None else None,
            "modified": bool(gui_doc.Modified) if gui_doc is not None else None,
            "visibility": visibility,
            "camera": normalise_camera(camera),
            "selection": [{"document": item.Object.Document.Name, "object": item.Object.Name,
                           "subelements": list(item.SubElementNames),
                           "points": [[point.x, point.y, point.z] for point in item.PickedPoints]}
                          for item in Gui.Selection.getSelectionEx("*")],
            "in_edit": in_edit.Object.Name if in_edit is not None and hasattr(in_edit, "Object") else None,
            "active_dialog": bool(dialog)}
