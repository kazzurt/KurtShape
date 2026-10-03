"""Bounded native Assembly adapter for the pinned FreeCAD runtime.

Native objects, references, placements and the native solver remain authoritative.
The controller owns transactions, revision checks, exclusive editing and replay.
"""
from contextlib import contextmanager
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import FreeCAD as App
import Part

ROOT = Path(__file__).resolve().parents[2]
NATIVE_PATH = ROOT / "runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/Mod/Assembly"
KINDS = {"fixed": "Fixed", "revolute": "Revolute", "slider": "Slider"}
SOLVER_CODES = {0: "solved", -6: "no grounded instance", -4: "over-constrained",
                -3: "conflicting constraints", -5: "malformed constraints",
                -1: "native solver error", -2: "redundant constraints"}
_SOURCE_GEOMETRY_CACHE = {}


class AssemblyError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def _error(code, message, **details):
    return AssemblyError(code, message, **details)


def _native():
    if str(NATIVE_PATH) not in sys.path:
        sys.path.insert(0, str(NATIVE_PATH))
    import Assembly
    import JointObject
    import Preferences
    if Path(JointObject.__file__).resolve().parent != NATIVE_PATH.resolve():
        raise _error("assembly_runtime", "The pinned native Assembly module is not loaded")
    return JointObject, Preferences


@contextmanager
def _explicit_solve():
    """Disable the bundled joint UI's implicit solves during typed changes."""
    _, preferences = _native()
    settings = preferences.preferences()
    previous = settings.GetBool("SolveInJointCreation", True)
    settings.SetBool("SolveInJointCreation", False)
    try:
        yield
    finally:
        settings.SetBool("SolveInJointCreation", previous)


def assemblies(doc):
    return [obj for obj in doc.Objects if obj.TypeId == "Assembly::AssemblyObject"]


def get(doc, identifier=None):
    values = assemblies(doc)
    if len(values) != 1 or (identifier is not None and values[0].Name != identifier):
        raise _error("missing_assembly", "Choose the document's single KurtShape assembly")
    value = values[0]
    if getattr(value, "KurtShapeAssembly", "") != "1":
        raise _error("unsupported_assembly", "This native assembly is inspectable; its structure is outside this workflow")
    return value


def _id(doc, value, fallback):
    if value is None:
        return fallback
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        raise _error("invalid_id", "Native IDs must begin with a letter and contain letters, digits or underscores")
    if doc.getObject(value):
        raise _error("duplicate_id", "The native object ID already exists", feature=value)
    return value


def _name(value, fallback):
    if value is None:
        return fallback
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise _error("invalid_name", "Use a nonempty name of at most 200 characters")
    return value.strip()


def _property(obj, kind, name, value):
    obj.addProperty(kind, name, "KurtShape Assembly")
    setattr(obj, name, value)
    obj.setEditorMode(name, 1)


def create(doc, identifier=None, name=None):
    if assemblies(doc):
        raise _error("assembly_exists", "This workflow supports one root assembly per document")
    _native()
    native_id = _id(doc, identifier, "Assembly")
    label = _name(name, "Assembly")
    asm = doc.addObject("Assembly::AssemblyObject", native_id)
    asm.Label = label
    asm.Type = "Assembly"
    _property(asm, "App::PropertyString", "KurtShapeAssembly", "1")
    _property(asm, "App::PropertyInteger", "SolverCode", 0)
    _property(asm, "App::PropertyString", "SolverStatus", "empty")
    _property(asm, "App::PropertyString", "SolverStamp", "")
    asm.newObject("Assembly::JointGroup", "Joints")
    asm.SolverStamp = _solved_stamp(asm)
    return asm


def _group(asm):
    values = [obj for obj in asm.Group if obj.TypeId == "Assembly::JointGroup"]
    if len(values) != 1:
        raise _error("unsupported_assembly", "The assembly must contain one native joint group")
    return values[0]


def result_objects(doc):
    values = assemblies(doc)
    return [obj for obj in values[0].Group if obj.TypeId == "App::Link"] if len(values) == 1 else []


def _instance(asm, identifier):
    value = asm.Document.getObject(identifier) if isinstance(identifier, str) else None
    if value not in result_objects(asm.Document):
        raise _error("missing_assembly_instance", "Choose an occurrence in the current assembly")
    return value


def _joint(doc, identifier):
    asm = get(doc)
    value = doc.getObject(identifier) if isinstance(identifier, str) else None
    if value not in _group(asm).Group or not hasattr(value, "JointType") or not safe_object(value):
        raise _error("missing_assembly_joint", "Choose a supported native assembly joint")
    return value


def global_shape(obj):
    """Apply source, occurrence and assembly placement exactly once."""
    if obj.TypeId == "App::Link":
        parents = assemblies(obj.Document)
        if len(parents) == 1 and getattr(parents[0], "KurtShapeAssembly", "") == "1" and obj in parents[0].Group and obj.LinkedObject is not None and hasattr(obj.LinkedObject, "Shape"):
            shape = obj.LinkedObject.Shape.copy()
            shape.Placement = parents[0].getGlobalPlacement() * obj.Placement * shape.Placement
        else:
            # Unsupported native documents remain inspectable. Mutation and
            # export gates reject their structure; viewing does not call get().
            shape = obj.Shape.copy()
            shape.Placement = obj.getGlobalPlacement() * obj.Placement.inverse() * shape.Placement
        return shape
    # Preserve the incumbent Part Studio shape behavior exactly.
    return obj.Shape


def _preflight_source(path):
    """Reject scripted FCStd before the native loader can restore a proxy."""
    if not isinstance(path, str):
        raise _error("invalid_assembly_source", "Choose an existing absolute FCStd source file")
    source = Path(path)
    if not source.is_absolute() or source.suffix.lower() != ".fcstd" or not source.is_file():
        raise _error("invalid_assembly_source", "Choose an existing absolute FCStd source file")
    try:
        with zipfile.ZipFile(source) as archive:
            data = archive.read("Document.xml")
            if len(data) > 16 * 1024 * 1024 or b"<!DOCTYPE" in data.upper():
                raise ValueError("Unsupported document XML")
            tree = ET.fromstring(data)
            object_data = {obj.get("name"): obj for obj in tree.findall("./ObjectData/Object")}
            metadata_object = object_data.get("KurtShapeProject")
            def null_proxy(prop):
                python = prop.find("Python")
                if prop.get("name") != "Proxy" or python is None or python.get("module") or python.get("class"):
                    return False
                value = python.get("value", "")
                if python.get("encoded") == "yes":
                    value = base64.b64decode(value, validate=True).decode("utf-8")
                return value in {"", "null"}
            metadata_safe = metadata_object is not None and all(
                "Python" not in prop.get("type", "") or null_proxy(prop)
                for prop in metadata_object.findall("./Properties/Property"))
            if any("Python" in obj.get("type", "") and not
                   (obj.get("name") == "KurtShapeProject" and obj.get("type") == "App::FeaturePython" and metadata_safe)
                   for obj in tree.findall("./Objects/Object")):
                raise _error("unsafe_assembly_source", "Scripted source objects are outside the safe insertion workflow")
            if any("Python" in prop.get("type", "")
                   and not (metadata_safe and prop in metadata_object.findall("./Properties/Property"))
                   for prop in tree.findall(".//Property")):
                raise _error("unsafe_assembly_source", "Scripted source properties are outside the safe insertion workflow")
            if any(obj.get("type", "").startswith(("App::Link", "Assembly::")) for obj in tree.findall("./Objects/Object")):
                raise _error("unsafe_assembly_source", "Insert a native Body or solid source; linked and nested assembly sources are deferred")
            if "GuiDocument.xml" in archive.namelist():
                gui = ET.fromstring(archive.read("GuiDocument.xml"))
                gui_metadata = next((obj for obj in gui.findall(".//ViewProvider") if obj.get("name") == "KurtShapeProject"), None)
                metadata_properties = [] if gui_metadata is None else gui_metadata.findall(".//Property")
                if any("Python" in prop.get("type", "") and not
                       (metadata_safe and prop in metadata_properties and null_proxy(prop))
                       for prop in gui.findall(".//Property")):
                    raise _error("unsafe_assembly_source", "Scripted source view providers are outside the safe insertion workflow")
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as exc:
        raise _error("invalid_assembly_source", "The source is not a readable native FCStd file", reason=str(exc))
    return source


def _source_results(doc):
    bodies = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"]
    members = {obj.Name for body in bodies for obj in body.Group}
    standalone = [obj for obj in doc.Objects if obj.Name not in members and obj not in bodies
                  and obj.TypeId.startswith("Part::") and hasattr(obj, "Shape")
                  and not any(parent.TypeId.startswith(("Part::", "App::Part")) and hasattr(parent, "Shape") for parent in obj.InList)]
    return [obj for obj in bodies + standalone if not obj.Shape.isNull() and obj.Shape.Solids]


@contextmanager
def _source_document(path):
    source = _preflight_source(path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    doc = None
    try:
        with tempfile.TemporaryDirectory(prefix="kurtshape-assembly-source-") as temporary:
            copy = Path(temporary) / "assembly-source.FCStd"
            shutil.copyfile(source, copy)
            if hashlib.sha256(copy.read_bytes()).hexdigest() != before:
                raise _error("assembly_source_changed", "The source changed while it was read")
            doc = App.openDocument(str(copy), True)
            if doc is None:
                raise _error("invalid_assembly_source", "The native engine could not open the source")
            if any(("Proxy" in obj.PropertiesList or obj.TypeId.endswith("Python"))
                   and not (obj.Name == "KurtShapeProject" and obj.TypeId == "App::FeaturePython" and obj.Proxy is None)
                   or any(link.Document != doc for link in obj.OutList) for obj in doc.Objects):
                raise _error("unsafe_assembly_source", "The source contains scripted objects or external document references")
            # Native restore can touch ordinary Bodies or metadata. Recompute
            # only this disposable copy to settle native restore behavior.
            doc.recompute()
            if any(set(obj.State) & {"Invalid", "Error"} for obj in doc.Objects):
                raise _error("invalid_assembly_source", "Save a valid recomputed source before inserting it")
            yield doc, source, before
            if hashlib.sha256(source.read_bytes()).hexdigest() != before:
                raise _error("assembly_source_changed", "The source changed during insertion")
    finally:
        if doc is not None and doc.Name in App.listDocuments():
            App.closeDocument(doc.Name)
        if active and active in App.listDocuments():
            App.setActiveDocument(active)


def candidates(path):
    with _source_document(path) as (doc, source, digest):
        values = [{"id": obj.Name, "name": obj.Label, "type": obj.TypeId,
                   "solid_count": len(obj.Shape.Solids)} for obj in _source_results(doc)]
        if not values:
            raise _error("empty_assembly_source", "This saved source contains no final solid Body or Part result")
        return values


def insert(doc, request):
    asm = get(doc, request.get("assembly"))
    native_id = _id(doc, request.get("id"), "Instance")
    with _source_document(request.get("path", "")) as (source_doc, path, digest):
        values = _source_results(source_doc)
        source_id = request.get("source_id")
        selected = next((obj for obj in values if obj.Name == source_id), None)
        if selected is None:
            raise _error("missing_assembly_source_part", "Choose an explicit Body or solid ID from assembly_candidates")
        if not selected.Shape.isValid():
            raise _error("invalid_assembly_source", "The chosen native source solid is invalid")
        label = _name(request.get("name"), selected.Label)
        # One embedded snapshot is shared by repeated occurrences of the same
        # saved source revision. Later source edits require explicit reinsertion.
        embedded = next((obj for obj in doc.Objects if getattr(obj, "KurtShapeEmbeddedSource", False)
                         and obj.SourceSHA256 == digest and obj.SourceObject == source_id), None)
        if embedded is None:
            shape = selected.Shape.copy()
            source_placement = selected.getGlobalPlacement() * selected.Placement.inverse() * shape.Placement
            shape.Placement = App.Placement()
            embedded = doc.addObject("Part::Feature", "EmbeddedPart")
            embedded.Label = "Embedded source: " + selected.Label
            embedded.Shape = shape
            _property(embedded, "App::PropertyBool", "KurtShapeEmbeddedSource", True)
            _property(embedded, "App::PropertyString", "SourcePath", str(path))
            _property(embedded, "App::PropertyString", "SourceSHA256", digest)
            _property(embedded, "App::PropertyString", "SourceObject", source_id)
            _property(embedded, "App::PropertyPlacement", "SourcePlacement", source_placement)
            _property(embedded, "App::PropertyString", "SourceGeometryFingerprint", _geometry_fingerprint(embedded))
            if embedded.ViewObject:
                embedded.ViewObject.Visibility = False
        instance = asm.newObject("App::Link", native_id)
        instance.setLink(embedded)
        instance.Label = label
        instance.Placement = asm.getGlobalPlacement().inverse() * embedded.SourcePlacement
        if instance.ViewObject:
            instance.ViewObject.Visibility = True
        if len(result_objects(doc)) == 1:
            ground(doc, instance.Name)
        solve(doc)
        return instance


def ground(doc, identifier, assembly=None):
    asm = get(doc, assembly)
    instance = _instance(asm, identifier)
    native, _ = _native()
    group = _group(asm)
    old = [obj for obj in group.Group if hasattr(obj, "ObjectToGround")]
    if old:
        old[0].ObjectToGround = instance
        for redundant in old[1:]:
            doc.removeObject(redundant.Name)
    else:
        joint = group.newObject("App::FeaturePython", "GroundedInstance")
        native.GroundedJoint(joint, instance)
        if App.GuiUp:
            native.ViewProviderGroundedJoint(joint.ViewObject)
    solve(doc)


def _reference(asm, value):
    if not isinstance(value, dict) or set(value) != {"instance", "subelement"}:
        raise _error("invalid_assembly_reference", "A reference requires only instance and subelement")
    instance = _instance(asm, value.get("instance"))
    element = value.get("subelement")
    if not isinstance(element, str) or (element and not re.fullmatch(r"(Face|Edge|Vertex)[1-9][0-9]*", element)):
        raise _error("invalid_assembly_reference", "Select an occurrence origin, FaceN, EdgeN or VertexN")
    if element:
        try:
            selected = instance.Shape.getElement(element)
            if selected.isNull():
                raise ValueError("Null element")
            if element.startswith("Face") and selected.Surface.TypeId not in {"Part::GeomPlane", "Part::GeomCylinder", "Part::GeomCone", "Part::GeomSphere", "Part::GeomTorus"}:
                raise ValueError("Use an analytic face, a line/circle edge or a vertex")
            if element.startswith("Edge") and selected.Curve.TypeId not in {"Part::GeomLine", "Part::GeomCircle"}:
                raise ValueError("Use a line/circle edge, an analytic face or a vertex")
        except Exception as exc:
            raise _error("invalid_assembly_reference", "This occurrence does not have a supported selected subelement", reason=str(exc))
    return [instance, [element, element]]


def _reference_info(value):
    if not value or value[0] is None:
        return None
    return {"instance": value[0].Name, "subelement": value[1][0] if value[1] else ""}


def _set_references(joint, first, second):
    if first[0] == second[0]:
        raise _error("invalid_assembly_reference", "A joint must connect two different occurrences")
    # Do not use setJointConnectors' presolve/undoSolve side effects. The native
    # proxy derives both connector frames and the native solver moves the parts.
    with _explicit_solve():
        joint.Reference1 = first
        joint.Reference2 = second
        joint.Proxy.updateJCSPlacements(joint)


def create_joint(doc, request):
    asm = get(doc, request.get("assembly"))
    kind = request.get("joint_type")
    if kind not in KINDS:
        raise _error("invalid_assembly_joint_type", "Choose fixed, revolute or slider")
    native_id = _id(doc, request.get("id"), KINDS[kind] + "Joint")
    label = _name(request.get("name"), KINDS[kind] + " joint")
    first = _reference(asm, request.get("first"))
    second = _reference(asm, request.get("second"))
    if first[0] == second[0]:
        raise _error("invalid_assembly_reference", "A joint must connect two different occurrences")
    native, _ = _native()
    with _explicit_solve():
        joint = _group(asm).newObject("App::FeaturePython", native_id)
        native.Joint(joint, native.JointTypes.index(KINDS[kind]))
        joint.Label = label
        _set_references(joint, first, second)
        if App.GuiUp:
            native.ViewProviderJoint(joint.ViewObject)
    solve(doc)
    return joint


def edit_joint(doc, request):
    asm = get(doc)
    joint = _joint(doc, request.get("joint"))
    kind = request.get("joint_type", str(joint.JointType).lower())
    if kind not in KINDS:
        raise _error("invalid_assembly_joint_type", "Choose fixed, revolute or slider")
    first = _reference(asm, request.get("first", _reference_info(joint.Reference1)))
    second = _reference(asm, request.get("second", _reference_info(joint.Reference2)))
    label = _name(request.get("name"), joint.Label)
    with _explicit_solve():
        joint.JointType = KINDS[kind]
        _set_references(joint, first, second)
        joint.Label = label
    solve(doc)


def _joint_value(asm, joint):
    if str(joint.JointType) == "Fixed":
        return None
    first = asm.getGlobalPlacement() * joint.Reference1[0].Placement * joint.Placement1
    second = asm.getGlobalPlacement() * joint.Reference2[0].Placement * joint.Placement2
    relative = first.inverse() * second
    return relative.Rotation.getYawPitchRoll()[0] if str(joint.JointType) == "Revolute" else relative.Base.z


def _number(value, unit):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise _error("invalid_assembly_motion", "Enter a finite angle or distance")
    try:
        quantity = App.Units.Quantity(str(value))
        expected = App.Units.Quantity("1 " + unit).Unit
        if quantity.Unit != expected and quantity.Unit != App.Units.Quantity("1").Unit:
            raise ValueError("Wrong units")
        result = float(quantity.Value)
        if not math.isfinite(result) or abs(result) > 1e7:
            raise ValueError("Out of range")
        return result
    except Exception:
        raise _error("invalid_assembly_motion", "Enter a finite value in " + unit)


def _component(asm, initial, omitted=None):
    """Traverse current native references; never store a parallel model."""
    members = {initial}
    changed = True
    while changed:
        changed = False
        for joint in _group(asm).Group:
            if joint == omitted or not hasattr(joint, "JointType") or joint.Suppressed:
                continue
            if not joint.Reference1 or not joint.Reference2:
                continue
            a, b = joint.Reference1[0], joint.Reference2[0]
            if a in members or b in members:
                before = len(members)
                members.update((a, b))
                changed |= len(members) != before
    return members


def move_joint(doc, identifier, value):
    asm = get(doc)
    joint = _joint(doc, identifier)
    if joint.Suppressed:
        raise _error("suppressed_joint", "This native joint is suppressed; unsuppress or edit it before joint movement")
    kind = str(joint.JointType)
    if kind == "Fixed":
        raise _error("fixed_joint", "A fixed joint has no permitted movement; edit or remove it")
    requested = _number(value, "deg" if kind == "Revolute" else "mm")
    grounds = {obj.ObjectToGround for obj in _group(asm).Group if hasattr(obj, "ObjectToGround")}
    first, second = joint.Reference1[0], joint.Reference2[0]
    first_component = _component(asm, first, joint)
    second_component = _component(asm, second, joint)
    if first_component & second_component or (first_component & grounds and second_component & grounds):
        raise _error("assembly_motion_locked", "Other joints lock this movement; edit or remove the conflicting joint")
    local_first = first.Placement * joint.Placement1
    local_second = second.Placement * joint.Placement2
    relative = App.Placement(App.Vector(0, 0, requested), App.Rotation()) if kind == "Slider" else App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), requested))
    if second_component & grounds:
        moving = first_component
        delta = (local_second * relative.inverse()) * local_first.inverse()
    else:
        moving = second_component
        delta = (local_first * relative) * local_second.inverse()
    for instance in moving:
        instance.Placement = delta * instance.Placement
    solve(doc)
    actual = _joint_value(asm, joint)
    difference = (actual - requested + 180) % 360 - 180 if kind == "Revolute" else actual - requested
    if abs(difference) > 1e-5:
        raise _error("assembly_motion_rejected", "The solver could not retain the requested coordinate", requested=requested, actual=actual)


def move_instance(doc, request):
    asm = get(doc, request.get("assembly"))
    instance = _instance(asm, request.get("instance"))
    if any(instance in (getattr(joint, "ObjectToGround", None),
                       joint.Reference1[0] if hasattr(joint, "Reference1") and joint.Reference1 else None,
                       joint.Reference2[0] if hasattr(joint, "Reference2") and joint.Reference2 else None)
           for joint in _group(asm).Group):
        raise _error("assembly_motion_locked", "Use joint movement for constrained occurrences; grounded occurrences cannot move")
    values = request.get("position_mm")
    if not isinstance(values, list) or len(values) != 3:
        raise _error("invalid_assembly_motion", "position requires three millimeter coordinates")
    position = App.Vector(*[_number(value, "mm") for value in values])
    rotation = request.get("rotation_xyzw")
    if rotation is not None:
        if not isinstance(rotation, list) or len(rotation) != 4 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in rotation) or sum(value * value for value in rotation) < 1e-12:
            raise _error("invalid_assembly_motion", "rotation requires four finite nonzero quaternion coordinates")
        orientation = App.Rotation(*rotation)
    else:
        orientation = instance.Placement.Rotation
    instance.Placement = App.Placement(position, orientation)
    solve(doc)


def remove(doc, identifier, cascade=False):
    asm = get(doc)
    obj = doc.getObject(identifier) if isinstance(identifier, str) else None
    group = _group(asm)
    if obj in result_objects(doc):
        dependent = [joint for joint in group.Group if obj == getattr(joint, "ObjectToGround", None)
                     or obj in [ref[0] for ref in (getattr(joint, "Reference1", None), getattr(joint, "Reference2", None)) if ref]]
        meaningful = [joint for joint in dependent if hasattr(joint, "JointType")]
        if meaningful and not cascade:
            raise _error("assembly_dependency", "The occurrence has dependent joints; remove them or choose cascade", dependents=[j.Name for j in meaningful])
        was_grounded = any(hasattr(joint, "ObjectToGround") for joint in dependent)
        for joint in dependent:
            doc.removeObject(joint.Name)
        source = obj.LinkedObject
        doc.removeObject(obj.Name)
        if not any(value.LinkedObject == source for value in result_objects(doc)):
            doc.removeObject(source.Name)
        remaining = result_objects(doc)
        if was_grounded and remaining:
            ground(doc, remaining[0].Name)
    elif obj in group.Group and hasattr(obj, "JointType") and safe_object(obj):
        doc.removeObject(obj.Name)
    else:
        raise _error("unsupported_assembly_delete", "Choose a supported joint or occurrence")
    solve(doc)


def safe_object(obj):
    """Allow only this structure and exact installed joint/view-provider classes."""
    doc = obj.Document
    values = assemblies(doc)
    if len(values) != 1 or getattr(values[0], "KurtShapeAssembly", "") != "1":
        return False
    asm = values[0]
    def ordinary(value):
        return (not any("Python" in value.getTypeIdOfProperty(key) for key in value.PropertiesList)
                and not value.TypeId.endswith("Python")
                and (not value.ViewObject or getattr(value.ViewObject, "Proxy", None) is None)
                and not any(link.Document != doc for link in value.OutList))
    if obj == asm or obj.TypeId == "Assembly::JointGroup" and obj in asm.Group:
        return ordinary(obj)
    if obj.TypeId == "Part::Feature" and getattr(obj, "KurtShapeEmbeddedSource", False):
        return (ordinary(obj) and not obj.OutList and all(hasattr(obj, name) for name in
                ("SourcePath", "SourceSHA256", "SourceObject", "SourcePlacement", "SourceGeometryFingerprint")))
    if obj.TypeId == "App::Link" and obj in asm.Group:
        source = obj.LinkedObject
        return (ordinary(obj) and obj.ElementCount == 0 and source is not None and source.Document == doc
                and source.TypeId == "Part::Feature" and getattr(source, "KurtShapeEmbeddedSource", False)
                and safe_object(source))
    if obj.TypeId != "App::FeaturePython":
        return False
    try:
        native, _ = _native()
        if obj not in _group(asm).Group or type(obj.Proxy) not in {native.Joint, native.GroundedJoint}:
            return False
        if any("Python" in obj.getTypeIdOfProperty(key) and key != "Proxy" for key in obj.PropertiesList):
            return False
        if obj.ViewObject and obj.ViewObject.Proxy is not None and type(obj.ViewObject.Proxy) not in {native.ViewProviderJoint, native.ViewProviderGroundedJoint}:
            return False
        if type(obj.Proxy) == native.GroundedJoint:
            return obj.ObjectToGround in result_objects(doc)
        return (str(obj.JointType) in KINDS.values()
                and not any(link.Document != doc for link in obj.OutList))
    except Exception:
        return False


def _geometry_fingerprint(source):
    # Display triangulation is transient and can differ between GUI and a fresh
    # headless process. Hash a native copy with geometry retained and mesh
    # omitted; never clean or otherwise mutate the authoritative source shape.
    canonical = source.Shape.copy(True, False)
    return hashlib.sha256(canonical_brep(canonical.exportBrepToString()).encode("utf-8")).hexdigest()


def canonical_brep(payload):
    """Ignore only native validation cache flags, retaining geometry/topology.

    OCCT 7.8.1 TopTools_ShapeSet writes seven TShape flags in this order:
    Free, Modified, Checked, Orientable, Closed, Infinite, Convex. The Checked
    bit records whether a native validity algorithm has visited that topology,
    and differs in fresh GUI/headless restore. It is not modeling intent.
    Restrict the mask to the TShapes section's standalone seven-bit flag rows;
    leave all geometry, tolerances, topology, locations and other flags intact.
    """
    match = re.search(r"(?m)^TShapes [0-9]+\r?$", payload)
    if match is None:
        raise _error("assembly_runtime", "Unsupported native BRep fingerprint serialization")
    return payload[:match.end()] + re.sub(r"(?m)(\r?\n\r?\n)([01]{2})[01]([01]{4})(\r?)$",
                                         r"\g<1>\g<2>0\g<3>\g<4>", payload[match.end():])


def clear_cache(doc):
    """Drop native geometry seals when the controller closes a document."""
    for key in list(_SOURCE_GEOMETRY_CACHE):
        if key[0] == doc.Name:
            _SOURCE_GEOMETRY_CACHE.pop(key, None)


def _source_fingerprints(doc, sources, generation):
    """Serialize embedded BReps once at an observer generation boundary."""
    key = (doc.Name, id(doc))
    cached = _SOURCE_GEOMETRY_CACHE.get(key)
    names = tuple(sorted((source.Name, getattr(source, "SourceGeometryFingerprint", "")) for source in sources))
    if generation is None or cached is None or cached[0] != generation or cached[1] != names:
        values = {source.Name: _geometry_fingerprint(source) for source in sources}
        if generation is not None:
            _SOURCE_GEOMETRY_CACHE[key] = (generation, names, values)
        return values
    return cached[2]


def validation_errors(doc, generation=None):
    values = assemblies(doc)
    if not values:
        return []
    errors = []
    try:
        asm = get(doc)
        group = _group(asm)
        instances = result_objects(doc)
        sources = {obj.LinkedObject for obj in instances if obj.LinkedObject is not None}
        if not safe_object(asm) or not safe_object(group):
            errors.append({"feature": asm.Name, "message": "Unsupported Python property, proxy, view provider or external reference"})
        allowed = {asm, group, asm.Origin, *asm.Origin.OriginFeatures, *instances, *group.Group}
        if any(obj not in allowed for obj in asm.Group):
            errors.append({"feature": asm.Name, "message": "Unsupported nested or additional native assembly child"})
        for obj in instances:
            if not safe_object(obj) or obj.Scale != 1.0 or not obj.ScaleVector.isEqual(App.Vector(1, 1, 1), 1e-9):
                errors.append({"feature": obj.Name, "message": "Unsupported occurrence link, external source or scale"})
        for source in sources:
            if not safe_object(source):
                errors.append({"feature": source.Name, "message": "Unsupported embedded source proxy or references"})
            if source.Placement.isSame(App.Placement(), 1e-9) is False:
                errors.append({"feature": source.Name, "message": "Embedded source placement must remain identity"})
        current_fingerprints = _source_fingerprints(doc, sources, generation)
        for source in sources:
            if current_fingerprints.get(source.Name) != getattr(source, "SourceGeometryFingerprint", ""):
                errors.append({"feature": source.Name, "message": "Embedded source geometry changed; reinsert the saved source instead"})
        grounds = [obj for obj in group.Group if hasattr(obj, "ObjectToGround")]
        if instances and (len(grounds) != 1 or not safe_object(grounds[0])):
            errors.append({"feature": asm.Name, "message": "Choose exactly one grounded occurrence"})
        for joint in group.Group:
            if not safe_object(joint):
                errors.append({"feature": joint.Name, "message": "Unsupported native joint proxy or reference"})
            elif hasattr(joint, "JointType"):
                if any(getattr(joint, key, False) for key in ("EnableLengthMin", "EnableLengthMax", "EnableAngleMin", "EnableAngleMax")):
                    errors.append({"feature": joint.Name, "message": "Native joint limits are outside this first Assembly workflow"})
                for ref in (joint.Reference1, joint.Reference2):
                    try:
                        _reference(asm, _reference_info(ref))
                    except Exception:
                        errors.append({"feature": joint.Name, "message": "Broken or unsupported joint reference"})
                if joint.Reference1 and joint.Reference2 and joint.Reference1[0] == joint.Reference2[0]:
                    errors.append({"feature": joint.Name, "message": "Joint references the same occurrence twice"})
        if getattr(asm, "SolverCode", 0) != 0:
            errors.append({"feature": asm.Name, "message": "Native solver: " + SOLVER_CODES.get(asm.SolverCode, str(asm.SolverCode))})
        if getattr(asm, "SolverStamp", "") != _solved_stamp(asm):
            errors.append({"feature": asm.Name, "message": "Assembly intent changed since its accepted solve; solve again"})
    except Exception as exc:
        errors.append({"feature": values[0].Name, "message": str(exc)})
    return errors


def _solved_stamp(asm):
    def placement(value):
        return [round(number, 8) for number in list(value.Base) + list(value.Rotation.Q)]
    values = [["assembly", placement(asm.Placement)]]
    for obj in result_objects(asm.Document):
        values.append([obj.Name, obj.LinkedObject.Name if obj.LinkedObject else None,
                       placement(obj.Placement), bool(obj.LinkTransform), obj.Scale, list(obj.ScaleVector)])
    for joint in _group(asm).Group:
        if hasattr(joint, "ObjectToGround"):
            values.append([joint.Name, joint.ObjectToGround.Name if joint.ObjectToGround else None])
        elif hasattr(joint, "JointType"):
            values.append([joint.Name, str(joint.JointType), _reference_info(joint.Reference1),
                           _reference_info(joint.Reference2), bool(joint.Suppressed),
                           placement(joint.Placement1), placement(joint.Placement2),
                           placement(joint.Offset1), placement(joint.Offset2),
                           bool(joint.Detach1), bool(joint.Detach2),
                           [bool(getattr(joint, key, False)) for key in ("EnableLengthMin", "EnableLengthMax", "EnableAngleMin", "EnableAngleMax")],
                           [float(getattr(joint, key, 0)) for key in ("LengthMin", "LengthMax", "AngleMin", "AngleMax")]])
    return json.dumps(values, separators=(",", ":"), sort_keys=True)


def _solution_residuals(asm, grounds):
    """Check the native solver's result; never compute an alternative solution."""
    failures = []
    for obj, original in grounds.items():
        if not obj.Placement.isSame(original, 1e-6):
            failures.append({"feature": obj.Name, "message": "The grounded occurrence moved"})
    for joint in _group(asm).Group:
        if not hasattr(joint, "JointType") or joint.Suppressed:
            continue
        first = joint.Reference1[0].Placement * joint.Placement1
        second = joint.Reference2[0].Placement * joint.Placement2
        relative = first.inverse() * second
        kind = str(joint.JointType)
        if kind == "Fixed":
            distance = relative.Base.Length
            angle = relative.Rotation.Angle
        elif kind == "Revolute":
            distance = relative.Base.Length
            z = relative.Rotation.multVec(App.Vector(0, 0, 1))
            angle = z.cross(App.Vector(0, 0, 1)).Length
        else:
            distance = math.hypot(relative.Base.x, relative.Base.y)
            angle = relative.Rotation.Angle
        if distance > 1e-5 or angle > 1e-6:
            failures.append({"feature": joint.Name, "message": "Native solution does not satisfy the joint",
                             "translation_residual_mm": distance, "rotation_residual_rad": angle})
    return failures


def solve(doc):
    if not assemblies(doc):
        return None
    asm = get(doc)
    instances = result_objects(doc)
    errors = validation_errors(doc)
    # Previous solver failure is diagnostic state, not a structural blocker.
    errors = [error for error in errors if not error["message"].startswith("Native solver:")
              and not error["message"].startswith("Assembly intent changed")]
    if errors:
        raise _error("invalid_assembly", "The native assembly structure or references are invalid", features=errors)
    if not instances:
        asm.SolverCode = 0
        asm.SolverStatus = "empty"
        asm.SolverStamp = _solved_stamp(asm)
        return 0
    grounds = {joint.ObjectToGround: joint.ObjectToGround.Placement.copy()
               for joint in _group(asm).Group if hasattr(joint, "ObjectToGround")}
    with _explicit_solve():
        # Native joints first derive connector frames, then native Assembly
        # computes placements. A nonzero return is never treated as success.
        for joint in _group(asm).Group:
            if hasattr(joint, "JointType"):
                joint.Proxy.updateJCSPlacements(joint)
        # Resolve newly created native link/joint membership before asking the
        # C++ solver for its explicit status. Otherwise a fresh joint can be
        # absent from the native cached assembly on the first solve call.
        doc.recompute()
        result = int(asm.solve(False))
    asm.SolverCode = result
    asm.SolverStatus = SOLVER_CODES.get(result, "native solver error " + str(result))
    if result != 0:
        raise _error("assembly_solver_failed", "Native Assembly solver: " + asm.SolverStatus,
                     native_code=result, assembly=asm.Name)
    residuals = _solution_residuals(asm, grounds)
    if residuals:
        asm.SolverCode = -5
        asm.SolverStatus = "native solution has unresolved joint residuals"
        raise _error("assembly_solver_failed", "Native Assembly did not satisfy every requested joint",
                     native_code=result, residuals=residuals, assembly=asm.Name)
    asm.SolverStamp = _solved_stamp(asm)
    return result


def inspect(doc):
    if not assemblies(doc):
        return None
    asm = assemblies(doc)[0]
    supported = getattr(asm, "KurtShapeAssembly", "") == "1" and len(assemblies(doc)) == 1
    if not supported:
        return {"id": asm.Name, "name": asm.Label, "supported": False,
                "solver_status": "unsupported native assembly", "instances": [], "joints": []}
    try:
        group = _group(asm)
    except AssemblyError:
        return {"id": asm.Name, "name": asm.Label, "supported": False,
                "solver_status": "unsupported native assembly", "instances": [], "joints": []}
    grounds = {obj.ObjectToGround for obj in group.Group if hasattr(obj, "ObjectToGround")}
    instances = result_objects(doc)
    joints = []
    for joint in group.Group:
        if not hasattr(joint, "JointType"):
            continue
        first, second = _reference_info(getattr(joint, "Reference1", None)), _reference_info(getattr(joint, "Reference2", None))
        try:
            value = _joint_value(asm, joint)
        except Exception:
            value = None
        joints.append({"id": joint.Name, "name": joint.Label, "joint_type": str(joint.JointType).lower(),
                       "first": first, "second": second, "references": [first, second], "value": value,
                       "suppressed": bool(getattr(joint, "Suppressed", False)),
                       "detached": [bool(getattr(joint, "Detach1", False)), bool(getattr(joint, "Detach2", False))],
                       "offsets": [{"base": list(getattr(joint, key, App.Placement()).Base),
                                    "rotation": list(getattr(joint, key, App.Placement()).Rotation.Q)} for key in ("Offset1", "Offset2")],
                       "unit": "deg" if str(joint.JointType) == "Revolute" else "mm" if str(joint.JointType) == "Slider" else None})
    try:
        status = getattr(asm, "SolverStatus", "unverified") if getattr(asm, "SolverStamp", "") == _solved_stamp(asm) else "needs solve"
        source_cache = _SOURCE_GEOMETRY_CACHE.get((doc.Name, id(doc)))
        if source_cache and any(source_cache[2].get(obj.LinkedObject.Name) != getattr(obj.LinkedObject, "SourceGeometryFingerprint", "") for obj in instances if obj.LinkedObject):
            status = "embedded source geometry changed"
    except Exception:
        status = "unsupported or broken native assembly"
    return {"id": asm.Name, "name": asm.Label, "supported": True,
            "solver_status": status,
            "solver_code": getattr(asm, "SolverCode", None),
            "source_policy": "embedded solid snapshots; no external dependencies or automatic updates",
            "instances": [{"id": obj.Name, "name": obj.Label, "grounded": obj in grounds,
                           "placement": {"base": list(obj.Placement.Base), "rotation": list(obj.Placement.Rotation.Q)},
                           "source": {"path": getattr(obj.LinkedObject, "SourcePath", ""),
                                      "sha256": getattr(obj.LinkedObject, "SourceSHA256", ""),
                                      "object": getattr(obj.LinkedObject, "SourceObject", "")},
                           "embedded_source": obj.LinkedObject.Name if obj.LinkedObject else None,
                           "connected_to_ground": bool(asm.isPartConnected(obj))} for obj in instances],
            "joints": joints,
            "disconnected_count": sum(not asm.isPartConnected(obj) for obj in instances)}


def handle(doc, request):
    op = request["op"]
    if op == "create_assembly":
        return create(doc, request.get("id"), request.get("name")).Name
    if op == "insert_assembly_part":
        return insert(doc, request).Name
    if op == "ground_assembly_instance":
        return ground(doc, request.get("instance"), request.get("assembly"))
    if op == "create_assembly_joint":
        return create_joint(doc, request).Name
    if op == "edit_assembly_joint":
        return edit_joint(doc, request)
    if op == "move_assembly_joint":
        return move_joint(doc, request.get("joint"), request.get("value"))
    if op == "move_assembly_instance":
        return move_instance(doc, request)
    if op == "delete_assembly_object":
        return remove(doc, request.get("feature"), request.get("cascade", False))
    if op == "solve_assembly":
        return solve(doc)
    raise _error("unknown_operation", "Unknown Assembly operation")
