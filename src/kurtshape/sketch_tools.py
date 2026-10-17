"""Native sketch creation and associated Use projections."""
from __future__ import annotations

PERSISTENT_LINE_COMMANDS = frozenset({'Sketcher_CreateLine', 'Sketcher_CreatePolyline'})


def unconsumed_sketches(doc, before=None):
    """Read active native profile/path use, excluding mere sketch references."""
    from . import studio
    sequence = studio.order(doc)
    active = sequence[:studio._cutoff(doc, before)]
    active_names = {obj.Name for obj in active}
    candidates = {obj.Name: obj for obj in active if obj.TypeId == "Sketcher::SketchObject"
                  and not getattr(obj, "KurtShapeInternal", False)}
    consumed = set()
    profile_properties = {"Part::Extrusion": ("Base",), "Part::Revolution": ("Source",),
                          "Part::Loft": ("Sections",), "Part::Sweep": ("Sections", "Spine")}

    def objects(value):
        if hasattr(value, "TypeId"):
            yield value
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from objects(item)

    def profiles(source, visited):
        if source.Name in visited:
            return
        visited.add(source.Name)
        if source.Name in candidates:
            consumed.add(source.Name)
        elif source.TypeId in {"PartDesign::ShapeBinder", "PartDesign::SubShapeBinder"}:
            for linked in objects(source.Support):
                profiles(linked, visited)
        elif source.TypeId == "Sketcher::SketchObject" and getattr(source, "KurtShapeHoleHelper", False):
            # A Hole's internal profile is attached to its binder of the authored sketch.
            for linked in objects(source.AttachmentSupport):
                profiles(linked, visited)

    for consumer in doc.Objects:
        operation = getattr(consumer, "KurtShapeOperationOwner", "") or consumer.Name
        if operation not in active_names:
            continue
        properties = profile_properties.get(consumer.TypeId, ())
        if (consumer.TypeId.startswith("PartDesign::") and not consumer.TypeId.endswith("Python")
                and "Profile" in consumer.PropertiesList):
            properties = ("Profile", "Sections", "Spine")
        for name in properties:
            if name in consumer.PropertiesList:
                for source in objects(getattr(consumer, name)):
                    profiles(source, set())
    return [obj for obj in active if obj.Name in candidates and obj.Name not in consumed]


def show_unconsumed_sketch(sketch):
    """Reveal an accepted unused sketch after native edit visibility cleanup."""
    import FreeCAD as App
    from .bodies import owner
    if sketch is None or not App.GuiUp or sketch not in unconsumed_sketches(sketch.Document):
        return False
    body = owner(sketch.Document, sketch)
    if body is not None and (getattr(body, "KurtShapeInternal", False)
                             or not getattr(body, "KurtShapePartVisible", True)):
        return False
    # Show the container before its child; a Body may propagate Tip visibility.
    # The solid Tip remains untouched when the sketch shares an existing part.
    if body is not None:
        body.ViewObject.Visibility = True
    sketch.ViewObject.Visibility = True
    sketch.ViewObject.Selectable = True
    return True


def restore_sketch_content(sketch, raw):
    """Restore native sketch intent in a valid dependency order.

    FreeCAD's generic object restore applies alphabetical properties without a
    document restoration guard. Constraints must not refer to geometry which
    has not been restored yet. Its null generated shape caches also serialize
    as empty BREP members, which the native BREP reader cannot read. Restore
    native geometry before constraints and rebuild those empty output caches.
    """
    import io
    import xml.etree.ElementTree as ET
    import zipfile

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        root = ET.fromstring(archive.read("Persistence.xml"))
        properties = root.find("Properties")
        # restoreContent creates archived dynamic properties but does not
        # remove ones absent from an older/newer snapshot. A stale support
        # selector would otherwise overwrite the restored native attachment.
        names = {prop.get("name") for prop in properties}
        for name in ("QueryInputs", "QuerySources", "QueryHealth", "QueryResolutionLog"):
            if name in sketch.PropertiesList and name not in names:
                sketch.removeProperty(name)
        removed = set()
        for prop in list(properties):
            if prop.get("name") not in {"Shape", "InternalShape"}:
                continue
            shape = prop.find("Part")
            filename = shape.get("file") if shape is not None else None
            if filename and archive.getinfo(filename).file_size == 0:
                removed.add(filename)
                properties.remove(prop)
                properties.set("Count", str(int(properties.get("Count")) - 1))
        order = {"ExternalGeo": -5, "ExternalGeometry": -4, "Geometry": -3,
                 "Constraints": -2, "ExpressionEngine": 1}
        # Native transient declarations must remain before persistent values.
        properties[:] = sorted(properties, key=lambda prop: -6 if prop.tag == "_Property"
                               else order.get(prop.get("name"), 0))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as destination:
            for entry in archive.infolist():
                if entry.filename not in removed:
                    destination.writestr(entry, ET.tostring(root, encoding="utf-8", xml_declaration=True)
                                         if entry.filename == "Persistence.xml" else archive.read(entry))
    # Clear old constraints through Sketcher before changing geometry, so a
    # smaller snapshot cannot temporarily leave indices pointing past its end.
    sketch.deleteAllConstraints()
    sketch.restoreContent(output.getvalue())
    sketch.touch()


def reference_errors(sketch):
    """Report missing native projections even when Sketcher retains their wire."""
    errors = []
    for index, geometry in enumerate(sketch.ExternalGeo[2:], 1):
        if not geometry.hasExtensionOfType("Sketcher::ExternalGeometryExtension"):
            continue
        extension = geometry.getExtensionOfType("Sketcher::ExternalGeometryExtension")
        if extension.testFlag("Missing"):
            errors.append({"feature": sketch.Name, "input": "ExternalEdge" + str(index),
                           "code": "missing_reference", "reference_health": "missing",
                           "message": "Used edge source is missing; repair or remove this sketch reference",
                           "native_reference": extension.Ref})
    if getattr(sketch, "KurtShapeHoleHelper", False):
        # A Hole's bridged profile: bound centres must still exist and sit on their sketch centres.
        from .hole_tools import bridge_errors
        errors.extend(bridge_errors(sketch))
    return errors


def external_links(sketch):
    """Return Sketcher's native external input slots, rather than grouped links.

    PropertyLinkSubList groups consecutive edges from an object in Python,
    while addExternal/delExternal and saved link slots index individual edges.
    """
    return [(source, element) for source, names in sketch.ExternalGeometry for element in names]


def _external_reference(sketch, geometry):
    if not geometry.hasExtensionOfType("Sketcher::ExternalGeometryExtension"):
        return None
    extension = geometry.getExtensionOfType("Sketcher::ExternalGeometryExtension")
    name, separator, element = extension.Ref.partition(".")
    source = sketch.Document.getObject(name) if separator else None
    if source is None or not hasattr(source, "Shape"):
        return None
    element = source.Shape.getElementIndexedName(element)
    return (source, element) if element else None


def _original_reference(sketch, source, element):
    if getattr(source, "KurtShapeUseOwner", "") == sketch.Name:
        links = [(origin, edge) for origin, edges in source.Support for edge in edges if origin]
        return links[0] if len(links) == 1 else None
    return source, element


def external_source(sketch, selection):
    """Resolve an edit-mode ExternalEdgeN back to its original source edge."""
    if not isinstance(selection, str) or not selection.startswith("ExternalEdge"):
        return None
    suffix = selection[len("ExternalEdge"):]
    if not suffix.isdigit():
        return None
    index = int(suffix) + 1
    geometry = sketch.ExternalGeo
    if not 2 <= index < len(geometry):
        return None
    reference = _external_reference(sketch, geometry[index])
    return _original_reference(sketch, *reference) if reference else None


def external_selection(sketch, source, element):
    """Find the projected edit-mode edge without guessing from source slots.

    Native projections can split a curve or collapse an edge to a point. A
    single edge selection is only safe when exactly one projected curve maps
    back to the source. The extension's mapped reference survives topology
    changes and also identifies hidden cross-body binders.
    """
    import Part
    matches = []
    for index, geometry in enumerate(sketch.ExternalGeo[2:], 2):
        if isinstance(geometry, Part.Point):
            continue
        selection = "ExternalEdge" + str(index - 1)
        reference = external_source(sketch, selection)
        if reference and reference[0] == source and reference[1] == element:
            matches.append(selection)
    return matches[0] if len(matches) == 1 else None


def capture_use_sources(sketch):
    """Retain native helper buffers when a sketch edit's commits are grouped."""
    from .bodies import owner
    sources = {source.Name: source for source, names in sketch.ExternalGeometry
               if source and getattr(source, "KurtShapeUseOwner", "") == sketch.Name}
    return [{"name": source.Name, "type": source.TypeId, "body": owner(sketch.Document, source).Name,
             "content": bytes(source.dumpContent())} for source in sources.values()]


def restore_use_sources(doc, sources):
    """Restore associated helpers before restoring the sketch's native buffer."""
    for saved in sources:
        source = doc.getObject(saved["name"])
        if source is None:
            body = doc.getObject(saved["body"])
            tip = body.Tip
            source = body.newObject(saved["type"], saved["name"])
            body.Tip = tip
        source.restoreContent(saved["content"])
        if getattr(source, "ViewObject", None):
            source.ViewObject.Visibility = False


def prune_use_sources(doc, sketch=None):
    """Remove unused adapter-owned binders only at an accepted edit boundary.

    During a sketch lease, hidden sources must survive draft Undo for Redo.
    On Finish or deletion, native containers and project metadata are bookkeeping
    users; every other native incoming link keeps a binder alive.
    """
    from .bodies import owner
    from .core import METADATA
    name = sketch.Name if hasattr(sketch, "Name") else sketch
    unused = []
    for source in doc.Objects:
        if source.TypeId != "PartDesign::ShapeBinder" or not getattr(source, "KurtShapeInternal", False):
            continue
        use_owner = getattr(source, "KurtShapeUseOwner", "")
        if not use_owner or name is not None and use_owner != name:
            continue
        body = owner(doc, source)
        users = [user for user in source.InList if user != body and user.Name != METADATA]
        if not users:
            unused.append(source.Name)
    if unused and not doc.HasPendingTransaction:
        doc.openTransaction("KurtShape: finish unused Use geometry")
    for name in unused:
        doc.removeObject(name)
    return unused


def validate_reference_source(doc, sketch, source):
    """Reject cycles and references to features beyond the sketch's history."""
    from .core import OperationError
    from . import studio
    if source == sketch or sketch in source.OutListRecursive:
        raise OperationError("cyclic_reference", "Sketch references must precede the sketch and cannot depend on it")
    sequence = studio.order(doc)
    source_order = doc.getObject(getattr(source, "KurtShapeOperationOwner", "")) or source
    sketch_order = doc.getObject(getattr(sketch, "KurtShapeOperationOwner", "")) or sketch
    if source_order in sequence and sketch_order in sequence and sequence.index(source_order) >= sequence.index(sketch_order):
        raise OperationError("future_reference", "Sketch references must precede the sketch in feature history", feature=source.Name)


def _use_source(doc, sketch, source, reference, spec):
    from .bodies import owner
    from . import studio, selectors
    from .reference_tools import is_selector, selector_value
    body = owner(doc, sketch)
    if body == owner(doc, source):
        return source, reference["subelement"]
    # Sketcher rejects external geometry in another Body. A native binder in
    # the sketch's Body supplies the permitted, associated local reference.
    # One edge per binder keeps its Edge1 input stable across topology edits.
    binder = body.newObject("PartDesign::ShapeBinder", sketch.Name + "UseSource")
    binder.Support = [(source, [reference["subelement"]])]
    binder.TraceSupport = True
    studio._prop(binder, "App::PropertyBool", "KurtShapeInternal", True)
    studio._prop(binder, "App::PropertyString", "KurtShapeUseOwner", sketch.Name)
    studio._prop(binder, "App::PropertyString", "KurtShapeOperationOwner", sketch.Name)
    if is_selector(spec):
        selectors.bind(binder, "use_source", selector_value(spec), native_property="Support", mode="linksublist")
    doc.recompute([binder])
    if getattr(binder, "ViewObject", None):
        binder.ViewObject.Visibility = False
    return binder, "Edge1"


def project_geometry(core, doc, request):
    """Project associated edges as native defining or reference geometry.

    FreeCAD 1.1's defining external geometry participates in the sketch wire,
    so a closed set of used edges is also an editable extrusion profile. The
    native Sketcher owns projection, placement and subsequent source updates.
    """
    from .core import OperationError
    from . import selectors
    from .reference_tools import is_selector, selector_value

    sketch = core._profile(doc, request.get("sketch"))
    defining = request.get("defining", True)
    if not isinstance(defining, bool):
        raise OperationError("invalid_argument", "defining must be boolean")
    specs = request.get("references")
    if not isinstance(specs, list) or not specs or len(specs) > 128:
        raise OperationError("invalid_argument", "Choose one or more edges to use (maximum 128)")
    existing = set()
    for source, element in external_links(sketch):
        if source is None:
            continue
        reference = _original_reference(sketch, source, element)
        if reference:
            existing.add((reference[0].Name, reference[1]))
    pending = []
    promote = set()
    seen = set()
    for spec in specs:
        reference = selectors.native_reference(doc, spec, before=sketch, entity_type="edge")
        source = doc.getObject(reference["feature"])
        validate_reference_source(doc, sketch, source)
        key = (source.Name, reference["subelement"])
        if key in seen:
            raise OperationError("invalid_argument", "The same edge was selected more than once")
        seen.add(key)
        if key not in existing:
            pending.append((spec, reference))
        elif defining:
            promote.add(key)

    initial = bytes(sketch.dumpContent())
    prior_objects = {obj.Name for obj in doc.Objects}
    try:
        for index, geometry in enumerate(sketch.ExternalGeo[2:], 2):
            reference = external_source(sketch, "ExternalEdge" + str(index - 1))
            if reference and (reference[0].Name, reference[1]) in promote:
                extension = geometry.getExtensionOfType("Sketcher::ExternalGeometryExtension")
                if not extension.testFlag("Defining"):
                    # Native toggling retains all constraints and geometry IDs.
                    sketch.toggleConstruction(-index - 1)
        for spec, reference in pending:
            slot = len(external_links(sketch))
            source = doc.getObject(reference["feature"])
            projected, element = _use_source(doc, sketch, source, reference, spec)
            # Reference edges support dimensions/constraints without becoming
            # part of an extrusion profile; explicit Use creates defining edges.
            try:
                sketch.addExternal(projected.Name, element, defining, False)
            except (ValueError, RuntimeError) as exc:
                raise OperationError("invalid_projection", "This edge cannot be projected onto the sketch plane",
                                     reference=reference, reason=str(exc)) from exc
            if projected == source and is_selector(spec):
                selectors.bind(sketch, "use_" + str(slot), selector_value(spec), mode="external", index=slot,
                               defining=defining, intersection=False)
        core._recompute(doc)
        if sketch.solve() != 0:
            raise OperationError("constraint_conflict", "Used geometry conflicts with sketch constraints")
        if {"Invalid", "Error"} & set(sketch.State):
            raise OperationError("invalid_projection", "Used edges could not produce valid sketch geometry",
                                 feature=sketch.Name, status=sketch.getStatusString())
    except Exception:
        # A rejected command within the exclusive sketch edit restores only
        # its sketch buffer. Remove newly authored helpers here as well.
        restore_sketch_content(sketch, initial)
        for obj in list(doc.Objects):
            if obj.Name not in prior_objects and getattr(obj, "KurtShapeUseOwner", "") == sketch.Name:
                doc.removeObject(obj.Name)
        raise
    return None


def run_command(command):
    """Activate native line handlers with continuous creation enabled.

    Sketcher snapshots this preference when activating its handler. Restore the
    stored value afterwards so other tools and a user's native FreeCAD setup
    retain their chosen behavior. The handler still ends normally on Escape or
    right-click, and all geometry stays inside the existing sketch edit lease.
    """
    import FreeCAD as App
    import FreeCADGui as Gui
    if command not in PERSISTENT_LINE_COMMANDS:
        Gui.runCommand(command)
        return
    prefs = App.ParamGet('User parameter:BaseApp/Preferences/Mod/Sketcher')
    original = next((value for kind, key, value in prefs.GetContents()
                     if kind == 'Boolean' and key == 'ContinuousCreationMode'), None)
    prefs.SetBool('ContinuousCreationMode', True)
    try:
        Gui.runCommand(command)
    finally:
        if original is None:
            prefs.RemBool('ContinuousCreationMode')
        else:
            prefs.SetBool('ContinuousCreationMode', original)
