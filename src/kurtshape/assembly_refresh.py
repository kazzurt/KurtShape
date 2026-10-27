"""Transactional, explicit refresh of saved assembly source snapshots.

The Controller owns rollback and revision publication. No external source is
modified and no occurrence object or joint is deleted/recreated.
"""
from types import SimpleNamespace

import FreeCAD as App

from . import assembly


def rollback_state(doc):
    """Native connector frames can round-trip by an ulp during aborted recompute."""
    asm = assembly.get(doc)
    values = []
    for obj in assembly.result_objects(doc) + list(assembly._group(asm).Group):
        fields = {key: getattr(obj, key).copy() for key in ("Placement", "Placement1", "Placement2")
                  if key in obj.PropertiesList}
        values.append((obj.Name, fields, "Touched" in obj.State, _appearance(obj)))
    return values


def restore_rollback(doc, state):
    # The native transaction already restored geometry and references. Restore
    # the accepted frame values after its recompute, without a second solve.
    # This avoids turning 4.0 into 3.9999999999999996 on a rejected request.
    with assembly._explicit_solve():
        for name, fields, touched, appearance in state:
            obj = doc.getObject(name)
            for key, value in fields.items():
                setattr(obj, key, value)
            _restore_appearance(obj, appearance)
            if not touched:
                obj.purgeTouched()


def _appearance(obj):
    view = obj.ViewObject
    if not view:
        return {}
    # Read native values (including Material) rather than serializing a second
    # model. Per-face assignments have no safe mapping after topology changes;
    # retain the exact assignment and reject if FreeCAD cannot restore it.
    names = ("Visibility", "ShapeColor", "LineColor", "PointColor", "Transparency",
             "ShapeMaterial", "LineMaterial", "PointMaterial", "DiffuseColor",
             "ShapeAppearance", "LineColorArray", "PointColorArray", "MaterialList",
             "OverrideColorList", "OverrideMaterialList", "Lighting",
             "LinkMaterial", "OverrideMaterial", "DrawStyle", "DisplayMode",
             "LineWidth", "PointSize")
    return {key: getattr(view, key) for key in names if key in view.PropertiesList}


def _appearance_value(value):
    if isinstance(value, (tuple, list)):
        return [_appearance_value(item) for item in value]
    if hasattr(value, "DiffuseColor"):
        return {key: _appearance_value(getattr(value, key)) for key in
                ("AmbientColor", "DiffuseColor", "EmissiveColor", "SpecularColor", "Shininess", "Transparency")}
    return value


def _restore_appearance(obj, values):
    if obj.ViewObject:
        for key, value in values.items():
            # Material equality compares Python wrapper identity; compare its
            # native appearance fields. Gratuitous App::Link material setters
            # create a new override list even when no appearance changed.
            if _appearance_value(getattr(obj.ViewObject, key)) != _appearance_value(value):
                setattr(obj.ViewObject, key, value)


def _connector_seals(asm, affected):
    seals = []
    for joint in assembly._group(asm).Group:
        if not hasattr(joint, "JointType"):
            continue
        for index in (1, 2):
            ref = getattr(joint, "Reference" + str(index))
            if not ref or ref[0] not in affected:
                continue
            info = assembly._reference_info(ref)
            element = info["subelement"]
            shape = ref[0].LinkedObject.Shape.getElement(element) if element else None
            seals.append((joint, index, info, None if shape is None else
                          assembly._geometry_fingerprint(SimpleNamespace(Shape=shape)),
                          getattr(joint, "Placement" + str(index)).copy()))
    return seals


def _check_connectors(asm, seals):
    for joint, index, info, seal, frame in seals:
        ref = assembly._reference(asm, info)
        element = info["subelement"]
        if element:
            shape = ref[0].LinkedObject.Shape.getElement(element)
            if assembly._geometry_fingerprint(SimpleNamespace(Shape=shape)) != seal:
                raise assembly.AssemblyError(
                    "assembly_refresh_reference_changed",
                    "A referenced subelement changed; explicitly edit the joint before refreshing",
                    joint=joint.Name, reference=index, instance=info["instance"], subelement=element)
        with assembly._explicit_solve():
            joint.Proxy.updateJCSPlacements(joint)
        if not getattr(joint, "Placement" + str(index)).isSame(frame, 1e-7):
            raise assembly.AssemblyError("assembly_refresh_reference_changed",
                                         "A joint connector frame changed during source refresh",
                                         joint=joint.Name, reference=index)


def _check_reference_geometry(shape, seals):
    # Reject a changed topological reference before touching the actual link
    # graph. FaceN existing in the new shape does not establish its identity.
    for joint, index, info, seal, frame in seals:
        element = info["subelement"]
        if not element:
            continue
        try:
            current = assembly._geometry_fingerprint(SimpleNamespace(Shape=shape.getElement(element)))
        except Exception:
            current = None
        if current != seal:
            raise assembly.AssemblyError("assembly_refresh_reference_changed",
                                         "A referenced subelement changed; explicitly edit the joint before refreshing",
                                         joint=joint.Name, reference=index,
                                         instance=info["instance"], subelement=element)


def refresh(doc, request):
    asm = assembly.get(doc, request.get("assembly"))
    instance = assembly._instance(asm, request.get("instance"))
    old_source = instance.LinkedObject
    if not assembly.safe_object(old_source):
        raise assembly.AssemblyError("invalid_assembly", "Refresh requires a supported embedded solid source")
    shared = [obj for obj in assembly.result_objects(doc) if obj.LinkedObject == old_source]
    policy = request.get("shared")
    if policy not in {None, "instance", "all"}:
        raise assembly.AssemblyError("invalid_argument", "shared must be instance or all")
    if policy is None and len(shared) > 1:
        raise assembly.AssemblyError("assembly_refresh_shared_source",
                                     "Choose shared:instance or shared:all for this shared embedded source",
                                     instances=[obj.Name for obj in shared], embedded_source=old_source.Name)
    affected = shared if policy == "all" else [instance]
    placements = {obj.Name: obj.Placement.copy() for obj in assembly.result_objects(doc)}
    appearances = {obj.Name: _appearance(obj) for obj in affected}
    source_appearance = _appearance(old_source)
    seals = _connector_seals(asm, affected)
    source_path = request.get("path", old_source.SourcePath)
    source_id = request.get("source_id", old_source.SourceObject)
    previous_digest = old_source.SourceSHA256
    previous_source_name = old_source.Name
    with assembly._source_document(source_path) as (source_doc, path, digest):
        selected = next((obj for obj in assembly._source_results(source_doc) if obj.Name == source_id), None)
        if selected is None:
            raise assembly.AssemblyError("missing_assembly_source_part", "Choose a saved Body or solid ID from assembly_candidates")
        shape = selected.Shape.copy()
        if shape.isNull() or not shape.Solids or not shape.isValid():
            raise assembly.AssemblyError("invalid_assembly_source", "The saved replacement must contain valid solid geometry")
        source_placement = selected.getGlobalPlacement() * selected.Placement.inverse() * shape.Placement
        shape.Placement = App.Placement()
        shape = assembly._as_saved(shape)
        if not shape.isValid():
            raise assembly.AssemblyError("invalid_assembly_source", "The replacement failed native serialization validation")
        _check_reference_geometry(shape, seals)
        # Updating a single user of a shared source is copy-on-write. Keeping
        # the link object retains grounding, joint references and its appearance.
        replacement = old_source
        if len(affected) != len(shared):
            replacement = doc.addObject("Part::Feature", "EmbeddedPart")
            replacement.Label = "Embedded source: " + selected.Label
            assembly._property(replacement, "App::PropertyBool", "KurtShapeEmbeddedSource", True)
            for kind, key, value in (("App::PropertyString", "SourcePath", str(path)),
                                     ("App::PropertyString", "SourceSHA256", digest),
                                     ("App::PropertyString", "SourceObject", source_id),
                                     ("App::PropertyPlacement", "SourcePlacement", source_placement),
                                     ("App::PropertyString", "SourceGeometryFingerprint", "")):
                assembly._property(replacement, kind, key, value)
            if replacement.ViewObject:
                replacement.ViewObject.Visibility = False
        replacement.Shape = shape
        _restore_appearance(replacement, source_appearance)
        replacement.SourcePath = str(path)
        replacement.SourceSHA256 = digest
        replacement.SourceObject = source_id
        replacement.SourcePlacement = source_placement
        replacement.SourceGeometryFingerprint = assembly._geometry_fingerprint(replacement)
        for obj in affected:
            if obj.LinkedObject != replacement:
                obj.setLink(replacement)
            obj.Placement = placements[obj.Name]
            _restore_appearance(obj, appearances[obj.Name])
        doc.recompute()
        _check_connectors(asm, seals)
        assembly.solve(doc)
        moved = [obj.Name for obj in assembly.result_objects(doc)
                 if not obj.Placement.isSame(placements[obj.Name], 1e-7)]
        if moved:
            raise assembly.AssemblyError("assembly_refresh_placement_changed",
                                         "Refreshing this source would move assembly occurrences", instances=moved)
        errors = assembly.validation_errors(doc)
        if errors:
            raise assembly.AssemblyError("invalid_assembly", "The refreshed assembly failed validation", features=errors)
    return {"instance": instance.Name, "instances": [obj.Name for obj in affected],
            "shared": policy or "instance", "previous_embedded_source": previous_source_name,
            "embedded_source": replacement.Name, "previous_source_sha256": previous_digest,
            "source_sha256": digest, "source_path": str(path), "source_id": source_id,
            "preserved_joint_references": len(seals), "placement_preserved": True}
