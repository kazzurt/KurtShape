"""Private, one-request admission digest reuse for an observed single target.

The production world_fingerprints function remains an independent oracle for
children and final guards. No BRep string, bytes buffer, restored shape, source
shape or list of shape objects survives admission. A ticket holds one 64-char
digest plus a constant number of existing native/observer references and small
identity values. It is consumed once and is never part of a worker envelope.
"""
from dataclasses import dataclass
import hashlib


@dataclass(slots=True)
class DigestTicket:
    controller: object
    document: object
    target: object
    metadata: object
    state: dict
    index: object
    key: object
    document_name: str
    document_id: str
    name: str
    sha256: str
    consumed: bool = False


def _stale():
    from kurtshape.core import OperationError
    raise OperationError("stale_step_export", "Project changed between STEP admission and capture")


def _pure_current(ticket):
    state, key = ticket.state, ticket.key
    return (ticket.controller.observer.states.get(ticket.document_name) is state
            and state.get("index") is ticket.index
            and ticket.index.document is ticket.document
            and (state.get("instance_id"), state.get("generation"), state.get("change_serial"))
            == (key.instance_id, key.generation, key.serial)
            and ticket.controller.documents.get(ticket.document_id) is ticket.document)


def _require_current(ticket):
    """Native reads followed by independent clock/identity fences.

    The plain observer clock catches an old snapshot_key returned by a
    reentrant/patched reader. Revision is checked independently because the
    observer intentionally excludes ordinary metadata property changes.
    """
    if not _pure_current(ticket):
        _stale()
    core, document = ticket.controller, ticket.document
    if not core._is_open(document) or not _pure_current(ticket):
        _stale()
    if core.snapshot_key(document) != ticket.key or not _pure_current(ticket):
        _stale()
    if document.getObject(ticket.name) is not ticket.target or not _pure_current(ticket):
        _stale()
    from kurtshape.core import METADATA
    if document.getObject(METADATA) is not ticket.metadata or not _pure_current(ticket):
        _stale()
    if ticket.metadata.DocumentId != ticket.document_id or not _pure_current(ticket):
        _stale()
    revision = ticket.metadata.Revision
    if revision != ticket.key.revision or not _pure_current(ticket):
        _stale()


def roundtrip_digest(controller, document, target_ids, key):
    """Return (existing admission verdict, optional one-use digest ticket).

    Multi-target/empty requests use the unchanged admission implementation.
    Single-target native roundtrip operations retain their original ordering
    and broad failure-to-False boundary. Ordinary target fingerprint fields remain
    in the later phase; project identity/revision are read here for binding. Successful but stale admission raises the
    existing stale_step_export error; no newly observed key is adopted.
    """
    from kurtshape.step_export_worker import world_roundtrip_stable
    try:
        names = tuple(target_ids)
    except Exception:
        return False, None
    if len(names) != 1:
        return world_roundtrip_stable(document, names), None
    try:
        import Part
        from kurtshape.assembly import global_shape, canonical_brep
        name = names[0]
        target = document.getObject(name)
        if target is None or target.Document != document:
            return False, None
        original = global_shape(target).copy().exportBrepToString()
        restored = Part.Shape()
        restored.importBrepFromString(original)
        canonical = canonical_brep(original)
        if canonical != canonical_brep(restored.exportBrepToString()):
            return False, None
    except Exception:
        return False, None
    # These detached objects and complete serializations are released before
    # any ordinary fingerprint fields are read. Hash failure merely disables
    # reuse: the unchanged fingerprint path retains its normal exception order.
    try:
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except Exception:
        return True, None
    finally:
        del original, restored, canonical
    if key is None:
        return True, None
    from kurtshape.core import METADATA
    document_name = document.Name
    state = controller.observer.states.get(document_name)
    metadata = document.getObject(METADATA)
    if state is None or metadata is None:
        _stale()
    ticket = DigestTicket(controller, document, target, metadata, state, state["index"], key,
                          document_name, metadata.DocumentId, name, digest)
    _require_current(ticket)
    return True, ticket


def initial_world_fingerprints(controller, document, target_ids, key, ticket):
    """Build the unchanged row from a fresh copy, reusing only its BRep SHA.

    Every ordinary row field retains production read order, including all
    actual map reads and the finite/8-MiB JSON roundtrip. Only the initial BRep
    export/hash is omitted. The independent final world_fingerprints is never
    patched or given this ticket. A consumed/stale/cross-context ticket fails.
    """
    from kurtshape.step_export_worker import world_fingerprints, _json_copy
    if ticket is None:
        return world_fingerprints(document, target_ids)
    if type(ticket) is not DigestTicket or ticket.consumed:
        _stale()
    ticket.consumed = True
    names = tuple(target_ids)
    if (controller is not ticket.controller or document is not ticket.document
            or key != ticket.key or names != (ticket.name,)):
        _stale()
    _require_current(ticket)
    from kurtshape.assembly import global_shape
    from kurtshape.core import _native_value
    target = document.getObject(ticket.name)
    if target is None or target.Document != document:
        raise ValueError("STEP export target is missing")
    if target is not ticket.target:
        _stale()
    shape = global_shape(target).copy()
    rows = [{
        "id": target.Name, "type": target.TypeId,
        "part_id": getattr(target, "KurtShapePartId", target.Name),
        "placement": _native_value(target.Placement),
        "global_placement": _native_value(target.getGlobalPlacement()),
        "brep_sha256": ticket.sha256,
        "element_map": dict(shape.ElementMap), "element_reverse_map": dict(shape.ElementReverseMap),
        "element_map_version": shape.ElementMapVersion, "element_map_size": shape.ElementMapSize,
    }]
    # Preserve ordinary field and JSON errors before the final freshness fence.
    result = _json_copy(rows)
    _require_current(ticket)
    return result
