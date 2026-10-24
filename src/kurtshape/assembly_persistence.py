"""Seal the geometry actually restored from a managed native snapshot.

OCCT can renormalize analytic curve frames on *every* BREP read. Hashing a
live shape and then persisting it therefore cannot promise the same hash on
restore. We first verify live embedded seals, serialize normally, and seal the
exact restored serialized shapes in the snapshot's metadata only. Geometry,
topology, placements, and the live document are never rewritten.
"""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


def save_copy(doc, path):
    """Native saveCopy with exact embedded seals; invalid sources stay invalid.

    Also used for recovery/preview/worker snapshots. A failed model must remain
    saveable for recovery, but its mismatching seal must never be blessed.
    """
    from . import assembly
    sources = [obj for obj in doc.Objects if assembly.is_embedded_source(obj)]
    accepted = {}
    for source in sources:
        current = assembly._geometry_fingerprint(source)
        if current == getattr(source, "SourceGeometryFingerprint", ""):
            accepted[source.Name] = current
    doc.saveCopy(str(path))
    if not accepted:
        return
    for name, digest in accepted.items():
        if assembly._geometry_fingerprint(doc.getObject(name)) != digest:
            raise assembly._error("assembly_source_changed", "Embedded source changed during native serialization", feature=name)
    _seal_archive(Path(path), accepted)


def _seal_archive(path, accepted):
    """Read native BREP bytes through the pinned reader, never round floats."""
    import Part
    from .assembly import canonical_brep, _error
    with zipfile.ZipFile(path) as archive:
        entries = [(item, archive.read(item.filename)) for item in archive.infolist()]
    contents = {item.filename: payload for item, payload in entries}
    if len(contents) != len(entries):
        raise _error("assembly_runtime", "Duplicate entries in native snapshot")
    tree = ET.fromstring(contents["Document.xml"])
    objects = {node.get("name"): node for node in tree.findall("./ObjectData/Object")}
    for name, live_digest in accepted.items():
        obj = objects.get(name)
        if obj is None:
            raise _error("assembly_runtime", "Embedded source missing from native snapshot", feature=name)
        seal = obj.find("./Properties/Property[@name='SourceGeometryFingerprint']/String")
        shape_ref = obj.find("./Properties/Property[@name='Shape']/Part")
        if seal is None or seal.get("value") != live_digest or shape_ref is None:
            raise _error("assembly_runtime", "Embedded seal changed during native serialization", feature=name)
        payload = contents.get(shape_ref.get("file"))
        if payload is None:
            raise _error("assembly_runtime", "Embedded BREP missing from native snapshot", feature=name)
        shape = Part.Shape()
        shape.importBrepFromString(payload.decode("utf-8"))
        if shape.isNull() or not shape.isValid():
            raise _error("assembly_runtime", "Embedded BREP could not be restored as valid geometry", feature=name)
        # Same exact digest policy as live validation, including mesh omission
        # and only the transient Checked flag mask. All coordinates are retained.
        restored = canonical_brep(shape.copy(True, False).exportBrepToString())
        seal.set("value", hashlib.sha256(restored.encode("utf-8")).hexdigest())
    contents["Document.xml"] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    stage = path.with_name(path.name + ".sealed")
    try:
        with zipfile.ZipFile(stage, "w") as archive:
            for item, _ in entries:
                archive.writestr(item, contents[item.filename])
        with zipfile.ZipFile(stage) as archive:
            if archive.testzip():
                raise _error("assembly_runtime", "Sealed native snapshot failed ZIP verification")
        stage.replace(path)
    finally:
        if stage.exists():
            stage.unlink()
