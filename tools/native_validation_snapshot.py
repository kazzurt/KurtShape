"""Strict native snapshots for validation; never an application idle-path hook.

Only actual Origin/OriginFeatures members may treat native hashCode as an
observation. Their complete serialized content and frame stay authoritative.
"""
import hashlib


INTRINSIC_TYPES = frozenset({"App::Origin", "App::Line", "App::Plane", "App::Point"})
SHAPE_PROPERTIES = ("Shape", "InternalShape", "AddSubShape", "SuppressedShape")


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
