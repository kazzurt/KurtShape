"""Contract 3.2 operation schemas (F5 section 3.1): one registry, checked against the handlers.

The data tests compare ``operation_schemas`` with ``Controller`` (argument
names, operation classes, enum constants, defaults, anchors). The native tests
run every example on its fixture and prove the declared requirements and
defaults against today's handlers:

* examples succeed (sufficiency);
* dropping a required field makes the request fail even with the generic
  pre-check patched off (a ``missing_required`` rejection there fails the
  test: the patch must reach core's pre-check), and a ``checked_by_handler``
  field gives exactly its declared code (necessity);
* dropping an optional field never leaks ``operation_failed`` except as the
  documented ``x-required-when`` KeyError of that field;
* every envelope-only ``operation_failed`` leak is covered by the generic
  ``REQUIRED``/``ONE_OF`` tables, and the envelope claims (``stale_revision``
  for a missing revision, ``x-ignored`` keys) hold on dispatch;
* each declared ``default`` gives the same signature (response facts plus the
  native model: object rows, rounded shape geometry and native properties) as
  omitting the field, on the schema examples and on a discriminating probe,
  and a wrong value changes that signature (the comparison can see a wrong
  default).

Wiring the pre-check, ``operation_schema`` and capabilities into core is
contract 3.2 unit U2a; this class covers the registry itself.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

import support
import perf_fixture

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import FreeCAD as App
import Part
from kurtshape import operation_schemas as schemas
from kurtshape.core import Controller, OperationError, native_intent
import native_validation_snapshot as nvs


def rounded(value, digits=6):
    if isinstance(value, float):
        return 0.0 if abs(value) < 10 ** -digits else round(value, digits)
    if isinstance(value, dict):
        return {key: rounded(item, digits) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(item, digits) for item in value]
    return value


def outcome(response):
    """Response facts that must agree between two requests the schema declares equivalent."""
    if not response.get("ok"):
        return {"ok": False, "code": response["error"]["code"], "reason": response["error"].get("reason")}
    result = response["result"]
    if "render_id" in result:
        # render_view (contract 3.2 F2): the effective settings and what was drawn; paths, ids and timings vary.
        return {"ok": True, "render": {
            "settings": result["settings"], "images": [[row["view"], row["width"], row["height"]] for row in result["images"]],
            "parts": [row["part"] for row in result["parts"]], "sketches": result["sketches"],
            "highlights": [[row["label"], row["count"], row["rendered_count"]] for row in result["highlights"]],
            "banners": [row["kind"] for row in result["geometry_status"]["banners"]]}}
    if "camera" in result and "applied" in result:
        # set_view (2026-10-20): the effective view, frame and camera.
        return {"ok": True, "view": [result["view"], result["frame"], result["applied"], result["reason"],
                                     rounded(result["camera"], 6)]}
    if "document_id" not in result:
        facts = {"ok": True, "keys": sorted(result)}
        if isinstance(result.get("documents"), list):
            # list_documents: the shape of each row tells full from compact (contract 3.2 detail).
            facts["documents"] = [sorted(row) for row in result["documents"] if isinstance(row, dict)]
        for key in ("candidates", "parts"):
            if isinstance(result.get(key), list):
                # Discovery filters change membership and explicit roles, not
                # the native document. Keep those response facts observable.
                facts[key] = rounded(result[key])
        return facts
    measurements = result.get("measurements") or {}
    studio = result.get("studio") or {}
    assembly = result.get("assembly")
    if assembly:
        assembly = {"instances": [[row["id"], row["name"], row["grounded"], rounded(row["placement"], 5)]
                                  for row in assembly["instances"]],
                    "joints": [[row["id"], row["name"], row["joint_type"], row["first"], row["second"],
                                rounded(row["value"], 5)] for row in assembly["joints"]]}
    features = {}
    for row in result.get("features", []):
        # Full inspect rows: parameters, sketch placement/support, helix and
        # datum-plane frames, reversed flags. Native OutList order varies.
        row = dict(row, dependencies=sorted(row.get("dependencies", ())))
        features[row["id"]] = rounded(row)
    report = copy.deepcopy(result.get("result_report"))
    if isinstance(report, dict):
        report.pop("check_ms", None)  # wall-clock time
    return {"ok": True, "name": result.get("name"), "build_status": result.get("build_status"),
            "build_errors": sorted(error.get("code", "") for error in result.get("build_errors", [])),
            "measurements": rounded({key: measurements.get(key) for key in ("solid_count", "volume_mm3", "area_mm2", "bbox_mm")}, 4),
            "features": features, "result_report": rounded(report, 4),
            "parts": [[part["id"], part["name"], part["visible"], rounded(part["color"])] for part in studio.get("parts", [])],
            "rollback_index": studio.get("rollback_index"), "assembly": assembly,
            "created_feature": result.get("created_feature"), "active_sketch_edit": result.get("active_sketch_edit")}


def shape_signature(shape):
    """Rounded geometry of a native shape: topology counts, size, bounds and sorted vertices.

    Used instead of native_validation_snapshot's BRep text digest, which is not
    reproducible between two identical runs (a shell result's BRep differs by
    one byte) and costs a BRep export per object.
    """
    if shape.isNull():
        return None
    box = shape.BoundBox
    return {"counts": [len(shape.Solids), len(shape.Shells), len(shape.Faces), len(shape.Edges), len(shape.Vertexes)],
            "volume": rounded(shape.Volume, 3), "area": rounded(shape.Area, 3), "length": rounded(shape.Length, 3),
            "bbox": rounded([box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax], 4) if box.isValid() else None,
            "vertices": sorted(rounded([vertex.X, vertex.Y, vertex.Z], 4) for vertex in shape.Vertexes)}


# Native properties that echo the request text or are random per creation;
# the default comparison looks at the model the request built, not its wording.
INTENT_MASK = ("KurtShapeStudioOperation", "Uid")


def native_signature(doc):
    """The native model of ``doc``: per object the content_view row facts (type, label, state,
    placements, group, tip) with shape_signature in place of the BRep digest, plus
    core.native_intent (properties, sketch geometry, construction flags, constraints and
    expressions) without INTENT_MASK."""
    rows = []
    for obj in doc.Objects:
        properties = obj.PropertiesList
        rows.append({"name": obj.Name, "type": obj.TypeId, "label": obj.Label,
                     "state": None if obj.Name == nvs.PROJECT_METADATA else sorted(obj.State),
                     "placement": nvs.placement_record(obj.Placement) if "Placement" in properties else None,
                     "global_placement": nvs.placement_record(obj.getGlobalPlacement())
                                         if obj.TypeId != "App::Link" and hasattr(obj, "getGlobalPlacement") else None,
                     "group": [member.Name for member in obj.Group] if "Group" in properties else None,
                     "tip": obj.Tip.Name if "Tip" in properties and obj.Tip is not None else None,
                     "shape": shape_signature(obj.Shape) if "Shape" in properties else None})
    intent = native_intent(doc)
    for item in intent:
        for key in INTENT_MASK:
            item["properties"].pop(key, None)
    return {"objects": rounded(rows), "intent": json.loads(json.dumps(intent, default=str))}


def in_default_mode(schema, request):
    """Whether a field's declared ``default`` applies to ``request`` (field itself absent)."""
    when = schema.get("x-default-when", {})
    if when.get("present_any") and not set(when["present_any"]) & set(request):
        return False
    if set(when.get("absent", ())) & set(request):
        return False
    return not any(request.get(key) == value for key, value in when.get("not_equal", {}).items())


def free_line(doc):
    """Native step for the pierce probe: a free line (geometry 1) in Target, whose endpoints differ."""
    doc.Target.addGeometry(Part.LineSegment(App.Vector(10, 10, 0), App.Vector(20, 10, 0)))


NATIVE_STEPS = {"free_line": free_line}

# A non-default value for every declared default whose default is not a boolean
# (a boolean default's wrong value is its negation). On the probe or example
# that runs it, it must change the signature.
_AXIS_X = {"origin": [0, 0, 0], "direction": [1, 0, 0]}
WRONG_VALUES = {
    ("add_rectangle", "x"): 3, ("add_rectangle", "y"): 3, ("sketch_rectangle", "x"): 3, ("sketch_rectangle", "y"): 3,
    ("create_sketch", "plane"): "YZ", ("sketch_circle", "plane"): "YZ", ("sketch_rectangle", "plane"): "YZ",
    ("boolean_parts", "kind"): "intersect",
    ("circular_pattern_parts", "angle"): "180 deg",
    ("circular_pattern_parts", "axis"): {"origin": [40, 15, 0], "direction": [0, 0, 1]},
    ("circular_pattern_parts", "count"): 3, ("linear_pattern_parts", "count"): 3,
    ("linear_pattern_parts", "direction"): [0, 0, 1],
    ("mirror_parts", "normal"): [0, 1, 0], ("mirror_parts", "origin"): [5, 0, 0],
    ("circular_pattern_parts", "operation"): "add", ("linear_pattern_parts", "operation"): "add",
    ("mirror_parts", "operation"): "add",
    # Pattern scopes keep only the parts the copies touch; the probes' copies touch Body and Tool.
    ("circular_pattern_parts", "merge_scope"): ["Body"], ("linear_pattern_parts", "merge_scope"): ["Body"],
    ("mirror_parts", "merge_scope"): ["Body"],
    # Result scopes are used as given; the probes' tools touch Body only.
    ("revolve", "merge_scope"): ["Body", "Tool"], ("sweep", "merge_scope"): ["Body", "Tool"],
    ("loft", "merge_scope"): ["Body", "Tool"], ("extrude_face", "merge_scope"): ["Body", "Tool"],
    ("pad", "merge_scope"): ["Body", "Tool"], ("pocket", "merge_scope"): ["Tool"],
    ("revolve", "operation"): "add", ("sweep", "operation"): "add", ("loft", "operation"): "add",
    ("pad", "operation"): "add", ("pocket", "operation"): "intersect", ("extrude_face", "operation"): "new",
    ("revolve", "angle"): "180 deg", ("revolve", "axis"): _AXIS_X,
    ("pad", "end_type"): "through_all", ("hole", "end_type"): "through_all", ("hole", "point_angle"): "90 deg",
    ("create_helix", "axis"): _AXIS_X, ("create_helix", "handedness"): "left", ("create_helix", "segment_length"): 2,
    ("create_helix", "start_angle"): "90 deg",
    ("create_plane", "angle"): "10 deg", ("create_plane", "base_plane"): "XZ", ("create_plane", "offset"): 3,
    ("pierce", "point"): 2,
    ("transform_part", "rotation"): {"axis": [0, 0, 1], "angle": "90 deg"}, ("transform_part", "translation"): [5, 0, 0],
    ("set_expression", "expression"): "PlateProfile.Constraints.Width / 5",
    ("new", "name"): "Other part", ("create_assembly", "name"): "Other assembly",
    ("inspect", "detail"): "compact", ("list_documents", "detail"): "compact",
    ("render_view", "views"): ["front"], ("render_view", "layout"): "sheet", ("render_view", "size"): [256, 192],
    ("render_view", "parts"): ["Body"], ("render_view", "frame"): "model", ("render_view", "sketches"): "include",
    ("render_view", "quality"): "draft",
    ("set_view", "view"): "front", ("set_view", "frame"): {"center_mm": [10, 10, 3], "width_mm": 12},
}


def wrong_value(op, name, default):
    return WRONG_VALUES[(op, name)] if (op, name) in WRONG_VALUES else not default


_BODY_FRONT = {"kind": "closest", "point": [20, 0, 5], "query": {"kind": "owned_by", "part": "Body", "entity_type": "face"}}
# Discriminating requests for defaults that the schema examples cannot show
# (no dependents for cascade, an unedited sketch for cancel, operation new or a
# one-part plate for merge_scope, nothing to refine, a straight sweep path, a two-
# section loft, a point geometry for pierce, a hole drilled away from the plate).
# Each runs on a fresh fixture after its setup requests (and native step), with the
# field omitted, set to its default and set to its wrong value.
DEFAULT_PROBES = {
    "assembly_final_candidates": {
        "fixture": "studio",
        "setup": [{"op": "pad", "id": "InventoryBoss", "profile": "BossProfile", "length": 15,
                   "operation": "add", "merge_scope": ["Body"]},
                  {"op": "save", "path": "<inventory_source>"}],
        "request": {"op": "assembly_candidates", "path": "<inventory_source>"},
        "fields": ["final_only"]},
    "inventory_history": {
        "fixture": "studio",
        "setup": [{"op": "pad", "id": "InventoryBoss", "profile": "BossProfile", "length": 15,
                   "operation": "add", "merge_scope": ["Body"]}],
        "request": {"op": "part_inventory"}, "fields": ["include_history"]},
    # U5: freezing matters only when the parameter has a consumer.
    "delete_in_use": {
        "fixture": "plate",
        "setup": [{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 60},
                  {"op": "set_expression", "feature": "PlateProfile", "parameter": "Width", "expression": "plate_width"}],
        "request": {"op": "delete_parameter", "name": "plate_width"},
        "fields": ["freeze_consumers"]},
    "revolve_add": {
        "fixture": "studio",
        "setup": [{"op": "sketch_rectangle", "id": "RevProfile", "body": "Body", "plane": "XZ", "x": 0, "y": 0,
                   "width": 5, "height": 12}],
        "request": {"op": "revolve", "id": "RevolveProbe", "profile": "RevProfile", "operation": "add"},
        "fields": ["operation", "merge_scope", "refine"]},
    "sweep_add": {
        "fixture": "studio",
        "setup": [{"op": "create_sketch", "id": "SweepLine", "body": "Body", "plane": "XZ"},
                  {"op": "add_line", "sketch": "SweepLine", "x1": 0, "y1": 5, "x2": 30, "y2": 5},
                  {"op": "sketch_circle", "id": "SweepDisk", "body": "Body", "plane": "YZ", "x": 0, "y": 5, "diameter": 4}],
        "request": {"op": "sweep", "id": "SweepProbe", "profile": "SweepDisk", "path": "SweepLine", "operation": "add"},
        "fields": ["operation", "merge_scope", "refine"]},
    "sweep_helix": {
        "fixture": "studio",
        "setup": [{"op": "create_helix", "id": "SweepCoil", "pitch": 10, "height": 10, "radius": 10},
                  {"op": "sketch_rectangle", "id": "SweepSquare", "body": "Body", "plane": "XZ", "x": 9, "y": -1,
                   "width": 2, "height": 2}],
        "request": {"op": "sweep", "id": "CoilProbe", "profile": "SweepSquare", "path": "SweepCoil"},
        "fields": ["frenet"]},
    "loft_add": {
        "fixture": "studio",
        "setup": [{"op": "sketch_circle", "id": "LoftA", "body": "Body", "x": 20, "y": 15, "diameter": 10},
                  {"op": "create_plane", "id": "LoftMid", "body": "Body", "base_plane": "XY", "offset": 15},
                  {"op": "sketch_circle", "id": "LoftB", "support": {"feature": "LoftMid"}, "x": 20, "y": 15, "diameter": 6},
                  {"op": "create_plane", "id": "LoftTop", "body": "Body", "base_plane": "XY", "offset": 30},
                  {"op": "sketch_circle", "id": "LoftC", "support": {"feature": "LoftTop"}, "x": 20, "y": 15, "diameter": 10}],
        "request": {"op": "loft", "id": "LoftProbe", "sections": ["LoftA", "LoftB", "LoftC"], "operation": "add"},
        "fields": ["operation", "merge_scope", "refine", "ruled"]},
    "extrude_face_studio": {
        "fixture": "studio", "setup": [],
        "request": {"op": "extrude_face", "id": "FaceProbe", "face": _BODY_FRONT, "length": 2},
        "fields": ["merge_scope"]},
    "pocket_refine": {
        # An unrefined Add leaves split coplanar faces on Body; the Remove's refine also refines its inputs.
        "fixture": "studio",
        "setup": [{"op": "pad", "id": "Boss2", "profile": "BossProfile", "length": 15, "operation": "add", "refine": False},
                  {"op": "sketch_circle", "id": "CutProfile", "body": "Body", "x": 5, "y": 5, "diameter": 4}],
        "request": {"op": "pocket", "id": "CutProbe", "profile": "CutProfile", "operation": "remove"},
        "fields": ["refine"]},
    "linear_add": {
        "fixture": "studio", "setup": [],
        "request": {"op": "linear_pattern_parts", "id": "RowProbe", "parts": ["Tool"], "direction": [0, -1, 0],
                    "spacing": 10, "operation": "add"},
        "fields": ["operation", "merge_scope", "include_source"]},
    "circular_add": {
        "fixture": "studio", "setup": [],
        "request": {"op": "circular_pattern_parts", "id": "AroundProbe", "parts": ["Tool"],
                    "axis": {"origin": [45, 10, 0], "direction": [0, 0, 1]}, "angle": "90 deg", "count": 2,
                    "operation": "add"},
        "fields": ["operation", "merge_scope", "include_source"]},
    "mirror_add": {
        "fixture": "studio", "setup": [],
        "request": {"op": "mirror_parts", "id": "MirrorProbe", "parts": ["Tool"], "origin": [0, 10, 0],
                    "normal": [0, 1, 0], "operation": "add"},
        "fields": ["operation", "merge_scope", "include_source"]},
    "finish_cancel": {
        "fixture": "plate",
        "setup": [{"op": "begin_sketch_edit", "feature": "Target"},
                  {"op": "add_circle", "sketch": "Target", "x": 20, "y": 20, "diameter": 5}],
        "request": {"op": "finish_sketch_edit"}, "fields": ["cancel"]},
    "delete_dependent": {
        "fixture": "plate", "setup": [], "request": {"op": "delete_feature", "feature": "HoleProfile"},
        "fields": ["cascade"]},
    "delete_many_dependent": {
        "fixture": "plate", "setup": [], "request": {"op": "delete_features", "features": ["HoleProfile"]},
        "fields": ["cascade"]},
    "delete_occurrence": {
        "fixture": "assembly", "setup": [], "request": {"op": "delete_assembly_object", "feature": "Rotor"},
        "fields": ["cascade"]},
    "pierce_line": {
        "fixture": "plate", "setup": [], "native": "free_line",
        "request": {"op": "pierce", "sketch": "Target", "geometry": 1, "target": "Crossing", "subelement": "Edge1"},
        "fields": ["point"]},
    "close_dirty": {
        # A modified document: without discard the close is refused, so the default is visible.
        "fixture": "plate", "setup": [{"op": "rename_feature", "feature": "Pad", "name": "Renamed plate"}],
        "request": {"op": "close_document"}, "fields": ["discard"]},
    "hole_top": {
        "fixture": "plate",
        "setup": [{"op": "create_plane", "id": "HoleTop", "base_plane": "XY", "offset": 6},
                  {"op": "sketch_circle", "id": "TopCentre", "support": {"feature": "HoleTop"}, "x": 10, "y": 10,
                   "diameter": 6}],
        "request": {"op": "hole", "sketch": "TopCentre", "diameter": 3, "depth": 4},
        "fields": ["reversed", "end_type", "point_angle"]},
    "save_other_project": {
        # Slice A/B U8: the destination holds another project's FCStd, so without overwrite the save is refused.
        "fixture": "plate", "setup": [], "request": {"op": "save", "path": "<other_project_file>"},
        "fields": ["overwrite"]},
}

# Application-level transactions an example leaves open after its document is
# closed natively. SchemaRunner.fresh closes them; test_examples_execute_on_fixtures
# pins the set, so a fix or a new leak is noticed.
KNOWN_TRANSACTION_LEAKS = {
    # Pre-existing defect (contract 3.2 N4 record in SHARING_STATUS, for §3.2.7): core._adopt opens the
    # clone's transaction with Document.openTransaction and commits it, but the application's active
    # transaction stays open after every document is closed. (The begin_sketch_edit example's open
    # managed edit is no leak: closing its document ends that transaction.)
    ("adopt", "KurtShape: adopt native copy"),
}


# Handler sites of the enums U1 named as module constants (TRANSITIONAL held their
# values before): (module, function, argument, declared defaults of that argument at
# the site). Once the constant exists the site must compare against it by name.
TRANSITIONAL_SITES = {
    "studio.RESULT_OPERATIONS": [("studio", "_result_operation", "operation", {"new", "remove"}),
                                 ("studio", "handle", "operation", {"new"})],
    "studio.BOOLEAN_KINDS": [("studio", "handle", "kind", {"union"})],
    "hole_tools.END_TYPES": [("hole_tools", "handle", "end_type", {"blind"})],
    "modeling_geometry.HANDEDNESS": [("modeling_geometry", "_create_helix", "handedness", {"right"})],
}


def handler_enum_site(module_name, function, field):
    """In ``function`` of a kurtshape module: the string-literal sets ``field`` is checked
    against (``field not in {...}``), the constant defaults of ``field = req.get("field", default)``,
    and the dotted names of constants it is checked against (``field not in NAME``)."""
    tree = ast.parse((ROOT / "src" / "kurtshape" / (module_name + ".py")).read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == function]
    if len(functions) != 1:
        raise AssertionError(f"{module_name}.{function}: expected one definition, found {len(functions)}")

    def constants(node):
        if isinstance(node, ast.Constant):
            return {node.value}
        if isinstance(node, ast.IfExp):
            return constants(node.body) | constants(node.orelse)
        return {ast.dump(node)}
    checked, defaults, named = [], set(), set()
    for node in ast.walk(functions[0]):
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == field
                and len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn))
                and isinstance(node.comparators[0], (ast.Name, ast.Attribute))):
            target = node.comparators[0]
            named.add(target.id if isinstance(target, ast.Name) else ast.unparse(target))
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == field
                and len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn))
                and isinstance(node.comparators[0], (ast.Set, ast.Tuple, ast.List))
                and all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.comparators[0].elts)):
            checked.append({item.value for item in node.comparators[0].elts})
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == field and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "get"
                and len(node.value.args) == 2 and isinstance(node.value.args[0], ast.Constant)
                and node.value.args[0].value == field):
            defaults |= constants(node.value.args[1])
    return checked, defaults, named


def conforms(value, schema, defs):
    """Minimal JSON-schema check of a declared default against its rendered field schema."""
    if "$ref" in schema:
        if not conforms(value, defs[schema["$ref"].rsplit("/", 1)[1]], defs):
            return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if "anyOf" in schema and not any(conforms(value, branch, defs) for branch in schema["anyOf"]):
        return False
    kind = schema.get("type")
    checks = {"string": lambda: isinstance(value, str), "boolean": lambda: isinstance(value, bool),
              "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
              "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
              "array": lambda: isinstance(value, list), "object": lambda: isinstance(value, dict),
              "null": lambda: value is None}
    if kind is not None and not checks[kind]():
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"] or "maximum" in schema and value > schema["maximum"]:
            return False
        if "x-exclusive-minimum" in schema and value <= schema["x-exclusive-minimum"]:
            return False
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            return False
        if "items" in schema and not all(conforms(item, schema["items"], defs) for item in value):
            return False
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            return False
        if set(schema.get("required", ())) - set(value):
            return False
        if not all(conforms(item, properties[key], defs) for key, item in value.items() if key in properties):
            return False
    return True


def slug(heading):
    """GitHub-style heading anchor."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


class SchemaRunner:
    """Run schema requests on fresh copies of the example fixtures with one Controller."""

    def __init__(self, core, folder, files):
        self.core, self.folder, self.files = core, Path(folder), dict(files)
        self.files["<inventory_source>"] = self.folder / "inventory-source-with-history.FCStd"
        self.state = None
        self.initial_documents = set(App.listDocuments())
        self.leaked_transactions = []  # (op of the last dispatched request, transaction name)
        self.last_op = None
        self.classes = schemas._classes(type(core))

    def substitute(self, value):
        if isinstance(value, str) and value.startswith("<"):
            if value.startswith("<project>"):
                project = self.folder / ("project-" + uuid.uuid4().hex[:8])
                project.mkdir()
                return str(project) + value[len("<project>"):]
            if value == "<other_project_file>":
                # Slice A/B U8: a fresh copy of the studio fixture (another project) for save's overwrite probe.
                project = self.folder / ("project-" + uuid.uuid4().hex[:8])
                project.mkdir()
                target = project / "other-project.FCStd"
                shutil.copy2(self.files["fixture:studio"], target)
                return str(target)
            if value in self.files:
                return str(self.files[value])
            raise KeyError("Undocumented example placeholder " + value)
        if isinstance(value, dict):
            return {key: self.substitute(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.substitute(item) for item in value]
        return value

    def request(self, raw, measure=False):
        request = self.substitute(copy.deepcopy(raw))
        document, revision, _ = schemas.envelope_requirements(request["op"], self.classes)
        if self.state is not None:
            if document:
                request.setdefault("document_id", self.state["document_id"])
            if revision:
                request.setdefault("expected_revision", self.state["revision"])
        request.setdefault("measure", measure)
        return request

    def dispatch(self, raw, measure=False):
        request = self.request(raw, measure)
        self.last_op = request["op"]
        response = self.core.dispatch(request)
        if response.get("ok") and isinstance(response.get("result"), dict) and "revision" in response["result"]:
            self.state = response["result"]
        return request, response

    def must(self, raw):
        request, response = self.dispatch(raw)
        if not response.get("ok"):
            raise AssertionError("Fixture step failed: " + json.dumps(request, default=str)[:600] + " -> "
                                 + json.dumps(response, default=str)[:1500])
        return response["result"]

    def close_documents(self):
        for name in set(App.listDocuments()) - self.initial_documents:
            App.closeDocument(name)
        self.state = None
        # An example can leave FreeCAD's application-level active transaction
        # open after its document closes (KNOWN_TRANSACTION_LEAKS); the next
        # opened document would then report a pending transaction. Each run
        # starts without one; the leak is recorded with the op that left it.
        active = App.getActiveTransaction()
        if active:
            self.leaked_transactions.append((self.last_op, active[0]))
            App.closeActiveTransaction()

    def fresh(self, fixture, setup=(), native=None):
        self.close_documents()
        if fixture != "none":
            response = self.core.dispatch({"op": "open", "path": str(self.files["fixture:" + fixture]), "measure": False})
            if not response.get("ok"):
                raise AssertionError("Fixture open failed: " + json.dumps(response, default=str)[:1500])
            self.state = response["result"]
        if native:
            # A documented native step outside typed operations, as in the plate fixture.
            doc = self.document()
            NATIVE_STEPS[native](doc)
            doc.recompute()
            if doc.HasPendingTransaction:
                doc.commitTransaction()
            self.state = self.core.inspect(doc, measure=False)
        for step in setup:
            self.must(step)

    def document(self):
        return self.core.documents[self.state["document_id"]]

    def build_fixtures(self):
        """Build the documented fixtures and save them; returns {placeholder or fixture: path}."""
        folder = self.folder / "fixtures"
        folder.mkdir(exist_ok=True)
        recipes = schemas.EXAMPLE_FIXTURES
        self.close_documents()
        for step in recipes["plate"]["recipe"]:
            self.must(step)
        doc = self.document()
        # The documented native step: a free sketch point for pierce.
        doc.Target.addGeometry(Part.Point(App.Vector(4, 0, 0)))
        doc.recompute()
        if doc.HasPendingTransaction:
            doc.commitTransaction()
        self.state = self.core.inspect(doc, measure=False)
        plate = folder / "plate.FCStd"
        self.must({"op": "save", "path": str(plate)})
        self.files.update({"<plate_file>": plate, "fixture:plate": plate})
        step = folder / "plate.step"
        self.must({"op": "export", "path": str(step)})
        self.files["<step_file>"] = step
        for name in ("studio", "assembly"):
            self.close_documents()
            for request in recipes[name]["recipe"]:
                self.must(request)
            path = folder / (name + ".FCStd")
            self.must({"op": "save", "path": str(path)})
            self.files["fixture:" + name] = path
        self.close_documents()
        return dict(self.files)

    def recovery_manifest(self):
        self.fresh("plate")
        manifest = self.core.checkpoint(self.document(), force=True)
        self.files["<recovery_manifest>"] = manifest
        self.close_documents()
        return manifest

    def examples(self, op):
        entry = schemas.OPERATIONS[op]
        fixtures = entry.get("x-example-fixtures") or [entry["x-example-fixture"]] * len(entry["examples"])
        return list(zip(entry["examples"], fixtures))

    def run(self, op, example, fixture, drop=(), extra=None, measure=False, setup=None, native=None):
        """Fresh fixture, the op's x-example-setup (or ``setup``), then the example with fields dropped or replaced."""
        self.fresh(fixture, schemas.OPERATIONS[op].get("x-example-setup", ()) if setup is None else setup, native)
        raw = {key: value for key, value in example.items() if key not in drop}
        raw.update(extra or {})
        return self.dispatch(raw, measure)

    def signature(self, response):
        """outcome() plus, for a success, the native model the request left (native_signature)."""
        facts = {"response": outcome(response)}
        if response.get("ok") and self.state is not None and self.state["document_id"] in self.core.documents:
            # close_document leaves no document to sign; its response facts stand alone.
            facts["native"] = native_signature(self.document())
        return facts


def refs(value, path=""):
    """Every Ref in a data structure, with its location."""
    if isinstance(value, schemas.Ref):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from refs(item, path + "/" + str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from refs(item, path + "/" + str(index))


def placeholders(value):
    if isinstance(value, str) and value.startswith("<"):
        yield value.split("/")[0] if value.startswith("<project>") else value
    elif isinstance(value, dict):
        for item in value.values():
            yield from placeholders(item)
    elif isinstance(value, list):
        for item in value:
            yield from placeholders(item)


class OperationSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = perf_fixture.FixtureOwner(cls.__module__ + "." + cls.__name__ + ".schema_fixtures")
        cls.addClassCleanup(cls.owner.close)
        with perf_fixture.preserved_environment():
            folder = support.isolated_session(cls.owner, prefix="operation-schema-fixtures-")
            core = Controller()
            runner = SchemaRunner(core, folder, {})
            try:
                cls.files = runner.build_fixtures()
            finally:
                runner.close_documents()
                core.close()

    def setUp(self):
        self.folder = support.isolated_session(self, prefix="operation-schema-native-")
        self.names = set(App.listDocuments())
        self.core = Controller()
        self.addCleanup(self._close)
        self.runner = SchemaRunner(self.core, self.folder, self.files)

    def _close(self):
        try:
            self.runner.close_documents()
            if App.getActiveTransaction():
                App.closeActiveTransaction()
        finally:
            for name in set(App.listDocuments()) - self.names:
                App.closeDocument(name)
            self.core.close()

    def built(self):
        return schemas.build(Controller)

    # Registry data ---------------------------------------------------------------
    def test_every_operation_has_a_schema_matching_its_arguments(self):
        self.assertEqual(set(schemas.OPERATIONS), set(Controller.OPS))
        built = self.built()
        self.assertEqual(set(built["operations"]), set(Controller.OPS))
        for op in sorted(Controller.OPS):
            with self.subTest(op=op):
                entry = schemas.OPERATIONS[op]
                arguments = set(Controller.ARGS[op])
                self.assertEqual(schemas.arg_names(op), arguments)
                properties = built["operations"][op]["request"]["properties"]
                self.assertEqual(set(properties), set(schemas.ENVELOPE) | arguments)
                for key in ("required", "checked_by_handler", "x-required-when"):
                    self.assertLessEqual(set(entry.get(key, ())), arguments, key)
                self.assertLessEqual({field for group in entry.get("requires_one_of", ()) for field in group}, arguments)
                for name in arguments:
                    schema = schemas.field_schema(op, name)
                    self.assertTrue(any(key in schema for key in schemas._TYPE_KEYS + ("enum",)),
                                    f"{op}.{name} has no type")
                    self.assertTrue(name in schemas.FIELDS or any(key in entry["fields"][name] for key in schemas._TYPE_KEYS + ("enum",)),
                                    f"{op}.{name} needs a FIELDS entry or a complete per-op field")
                if entry["required"] or entry.get("requires_one_of"):
                    self.assertTrue(entry["examples"], "an op with required fields needs an example")
                self.assertTrue(entry["summary"])

    def test_examples_use_declared_fields_fixtures_and_placeholders(self):
        built = self.built()
        for op in sorted(schemas.OPERATIONS):
            entry = schemas.OPERATIONS[op]
            with self.subTest(op=op):
                self.assertIn(entry["x-example-fixture"], schemas.EXAMPLE_FIXTURES)
                if "x-example-fixtures" in entry:
                    self.assertEqual(len(entry["x-example-fixtures"]), len(entry["examples"]))
                    self.assertLessEqual(set(entry["x-example-fixtures"]), set(schemas.EXAMPLE_FIXTURES))
                for example in entry["examples"]:
                    self.assertEqual(example["op"], op)
                    self.assertLessEqual(set(example), schemas.arg_names(op) | set(schemas.ENVELOPE))
                    self.assertFalse(set(entry["required"]) - set(example), "examples carry every required field")
                    for group in schemas.ONE_OF[op]:
                        self.assertTrue(set(group) & set(example))
                    self.assertLessEqual(set(placeholders(example)), set(schemas.EXAMPLE_PLACEHOLDERS))
                for step in entry.get("x-example-setup", ()):
                    self.assertIn(step["op"], Controller.OPS)
                    self.assertLessEqual(set(step), schemas.arg_names(step["op"]) | {"op"})
                rendered = built["operations"][op]["examples"]
                document, revision, _ = schemas.envelope_requirements(op, schemas._classes(Controller))
                for raw, example in zip(entry["examples"], rendered):
                    expected = dict(raw)
                    if document:
                        expected["document_id"] = "<document_id>"
                    if revision:
                        expected["expected_revision"] = "<revision>"
                    self.assertEqual(example, expected)
        for name, fixture in schemas.EXAMPLE_FIXTURES.items():
            for step in fixture.get("recipe", ()):
                self.assertIn(step["op"], Controller.OPS, name)
                self.assertLessEqual(set(step), schemas.arg_names(step["op"]) | {"op"}, name)
                self.assertLessEqual(set(placeholders(step)), set(schemas.EXAMPLE_PLACEHOLDERS), name)

    def test_schema_module_has_no_top_level_kurtshape_imports(self):
        tree = ast.parse(Path(schemas.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                self.assertFalse(node.level or (node.module or "").startswith("kurtshape"), ast.dump(node))
            if isinstance(node, ast.Import):
                self.assertFalse(any(alias.name.startswith("kurtshape") for alias in node.names), ast.dump(node))
        # missing_arguments reads only import-time tables, and a dispatch never builds the document.
        with patch.dict(schemas._BUILT, clear=True):
            self.assertEqual(schemas.missing_arguments("revolve", {}), (["profile"], []))
            self.assertEqual(schemas._BUILT, {})
            response = self.core.dispatch({"op": "new", "name": "No build"})
            self.assertTrue(response["ok"], response)
            response = self.core.dispatch({"op": "inspect", "document_id": response["result"]["document_id"]})
            self.assertTrue(response["ok"], response)
            self.assertEqual(schemas._BUILT, {})

    def test_enums_come_from_code_constants(self):
        sources = {}
        for name, data in (("DEFS", schemas.DEFS), ("FIELDS", schemas.FIELDS), ("OPERATIONS", schemas.OPERATIONS)):
            for path, ref in refs(data, name):
                sources.setdefault(ref.source, []).append((path, ref))
        # Later contract 3.2 units add their own constants (render, parameter and batch limits);
        # every source, old or new, must resolve to its owning module's value.
        expected = {"studio.RESULT_OPERATIONS", "studio.BOOLEAN_KINDS", "extrusion_edit.END_TYPES", "hole_tools.END_TYPES",
                    "modeling_geometry.HANDEDNESS", "modeling_geometry.PLANE_MODES", "assembly.KINDS", "hole_tools.CUT_ARGS",
                    "extrusion_edit.EXPRESSION_PATTERN", "selectors.schema"}
        self.assertLessEqual(expected, set(sources))
        for source, uses in sorted(sources.items()):
            module_name, attribute = source.split(".")
            module = schemas._module(module_name)
            with self.subTest(source=source):
                ref = uses[0][1]
                if hasattr(module, attribute):
                    value = getattr(module, attribute)
                    value = value() if callable(value) else value
                    if source in schemas.TRANSITIONAL:
                        self.assertEqual(tuple(value), schemas.TRANSITIONAL[source], "U1 constant must keep the handler values")
                    if source in TRANSITIONAL_SITES:
                        # The constant exists (U1): each handler site compares its argument against
                        # that constant by name, keeps no literal copy, and keeps its default.
                        for site_module, function, field, default in TRANSITIONAL_SITES[source]:
                            with self.subTest(site=(site_module, function, field)):
                                checked, defaults, named = handler_enum_site(site_module, function, field)
                                self.assertIn(attribute, {name.rsplit(".", 1)[-1] for name in named}, named)
                                self.assertNotIn(set(value), checked, "literal copy of the constant left at the site")
                                self.assertEqual(defaults, default)
                    if ref.form == "keys":
                        self.assertEqual(schemas.resolve(ref), list(value))
                    elif ref.form == "anchored":
                        self.assertEqual(schemas.resolve(ref), "^(?:" + value + ")$")
                    elif ref.form == "scalar":
                        self.assertEqual(schemas.resolve(ref), value)
                    elif ref.form == "key_sets":
                        self.assertEqual(schemas.resolve(ref), {kind: sorted(keys) for kind, keys in sorted(value.items())})
                    else:
                        self.assertEqual(set(schemas.resolve(ref)), set(value))
                elif source in schemas.TRANSITIONAL_SOURCES:
                    fallback = getattr(module, schemas.TRANSITIONAL_SOURCES[source])
                    self.assertEqual(schemas.resolve(ref), {kind: sorted(keys) for kind, keys in sorted(fallback.items())})
                else:
                    # Before U1 names it, the transitional tuple equals the literal each handler
                    # site checks its argument against (``value not in {...}``), and that argument
                    # defaults to the declared default (``value = req.get(field, default)``).
                    self.assertIn(source, schemas.TRANSITIONAL)
                    self.assertIn(source, TRANSITIONAL_SITES)
                    for site_module, function, field, default in TRANSITIONAL_SITES[source]:
                        with self.subTest(site=(site_module, function, field)):
                            checked, defaults, _ = handler_enum_site(site_module, function, field)
                            self.assertIn(set(schemas.TRANSITIONAL[source]), checked)
                            self.assertEqual(defaults, default)
                    self.assertEqual(schemas.resolve(ref), list(schemas.TRANSITIONAL[source]))
        for source in TRANSITIONAL_SITES:
            module_name, attribute = source.split(".")
            self.assertTrue(source in schemas.TRANSITIONAL or hasattr(schemas._module(module_name), attribute), source)
        built = self.built()
        pad = built["operations"]["pad"]["request"]["properties"]
        self.assertEqual(pad["end_type"]["x-enum-source"], "extrusion_edit.END_TYPES")
        self.assertEqual(pad["end_type"]["enum"], list(schemas._module("extrusion_edit").END_TYPES))
        joint = built["operations"]["create_assembly_joint"]["request"]["properties"]["joint_type"]
        self.assertEqual(joint["enum"], list(schemas._module("assembly").KINDS))
        self.assertEqual(built["$defs"]["result_operation"]["x-enum-source"], "studio.RESULT_OPERATIONS")
        self.assertEqual(set(built["$defs"]["selector"]["x-kinds"]), set(schemas._module("selectors")._SCHEMA))

    def test_envelope_requirements_follow_operation_classes(self):
        built = self.built()
        documentless = getattr(Controller, "DOCUMENTLESS_OPS", schemas.DOCUMENTLESS_OPS)
        view = getattr(Controller, "VIEW_OPS", frozenset())
        kinds = {"inspect": "read", "preview": "read", "new": "create", "import_step": "create", "pad": "modeling",
                 "rebuild": "modeling", "create_assembly": "assembly", "save": "lifecycle", "export": "lifecycle",
                 "adopt": "lifecycle", "undo": "history", "begin_sketch_edit": "history", "finish_sketch_edit": "history"}
        for op in sorted(Controller.OPS):
            with self.subTest(op=op):
                schema = built["operations"][op]
                request = schema["request"]
                self.assertFalse(request["additionalProperties"])
                self.assertEqual(request["properties"]["op"], {"const": op})
                self.assertEqual(request["required"][0], "op")
                self.assertEqual("document_id" in request["required"],
                                 op not in Controller.CREATE_OPS and op not in documentless)
                # Slice A/B U6: preview is a read; its revision is optional and checked when given.
                self.assertEqual("expected_revision" in request["required"],
                                 op not in Controller.READ_OPS | Controller.CREATE_OPS | view)
                self.assertNotIn("request_id", request["required"])
                self.assertNotIn("measure", request["required"])
                self.assertEqual(request["properties"]["measure"]["enum"], [False, True, "full"])
                if op != "request_status":
                    self.assertEqual(request["properties"]["request_id"].get("x-bridge-only", False),
                                     op not in Controller.READ_OPS)
                # Contract 3.2 U6: a batch is previewable and one undo step, outside MODEL_OPS.
                self.assertEqual(schema["preview"], op in Controller.MODEL_OPS - {"rebuild"} | {"batch"})
                self.assertEqual(schema["undoable"], op in Controller.MODEL_OPS | Controller.ASSEMBLY_OPS | {"batch"})
                if op in kinds:
                    self.assertEqual(schema["kind"], kinds[op])
                self.assertNotEqual(schema["kind"], "other")
                self.assertEqual(set(request["required"]) - {"op", "document_id", "expected_revision"},
                                 set(schemas.OPERATIONS[op]["required"]))

    def test_build_is_canonical_cached_and_digest_stable(self):
        with patch.dict(schemas._BUILT, clear=True):
            first = schemas.build(Controller)
            self.assertIs(schemas.build(Controller), first)
            text = schemas.canonical(first)
            self.assertNotIn("Ref(", text)
            self.assertEqual(first["schema_version"], schemas.SCHEMA_VERSION)
            self.assertEqual(first["digest"], hashlib.sha256(schemas.canonical(
                {key: value for key, value in first.items() if key != "digest"}).encode("utf-8")).hexdigest())
            schemas._BUILT.clear()
            again = schemas.build(Controller)
            self.assertIsNot(again, first)
            self.assertEqual(schemas.canonical(again), text)
        subset = schemas.select(self.built(), ["fillet", "pad"])
        self.assertEqual(list(subset["operations"]), ["fillet", "pad"])
        self.assertEqual(subset["digest"], self.built()["digest"])
        with self.assertRaises(KeyError):
            schemas.select(self.built(), ["fillet", "no_such_operation"])
        for names in ([["fillet"]], [None], ["fillet", 5]):
            with self.assertRaises(TypeError):
                schemas.select(self.built(), names)
        # The operation_schema read decorates the selection (contract, contract_revision);
        # neither form may hand out the cached build itself.
        cached = self.built()
        text = schemas.canonical(cached)
        for names in (None, ["fillet"]):
            selection = schemas.select(cached, names)
            self.assertIsNot(selection, cached)
            selection["contract"] = 3
            selection["digest"] = "decorated"
            selection.pop("$defs")
        self.assertIs(self.built(), cached)
        self.assertEqual(schemas.canonical(cached), text)
        self.assertEqual(cached["digest"], schemas.digest(cached))

    def test_feature_id_pattern_matches_controller_id_rule(self):
        doc = App.newDocument("SchemaIds")
        self.addCleanup(App.closeDocument, doc.Name)
        names = ["A", "a1", "Pad_2", "Z" + "9" * 63, "Z" + "9" * 64, "_x", "1a", "", "a-b", "a b", "a\n",
                 "\N{LATIN CAPITAL LETTER A WITH DIAERESIS}b", "x" * 64, "x" * 65]
        for name in names:
            with self.subTest(name=name):
                accepted = re.fullmatch(schemas.FEATURE_ID_PATTERN, name) is not None
                try:
                    self.core._id(doc, {"id": name}, "Fallback")
                    controller_accepts = True
                except OperationError as exc:
                    self.assertEqual(exc.code, "invalid_argument")
                    controller_accepts = False
                self.assertEqual(accepted, controller_accepts)
        for value in (5, None, ["A"]):
            with self.assertRaises(OperationError):
                self.core._id(doc, {"id": value}, "Fallback")
        self.assertEqual(schemas.DEFS["new_id"]["pattern"], schemas.FEATURE_ID_PATTERN)

    def test_missing_arguments_uses_import_time_tables(self):
        self.assertEqual(schemas.missing_arguments("pad", {}), ([], [["profile", "face"]]))
        self.assertEqual(schemas.missing_arguments("pad", {"profile": None}), ([], [["profile", "face"]]))
        self.assertEqual(schemas.missing_arguments("pad", {"face": {"feature": "Pad", "subelement": "Face1"}}), ([], []))
        self.assertEqual(schemas.missing_arguments("revolve", {"profile": None}), (["profile"], []))
        self.assertEqual(schemas.missing_arguments("set_parameter", {"feature": "Pad"}), (["parameter", "value"], []))
        self.assertEqual(schemas.missing_arguments("set_expression", {"feature": "Pad", "parameter": "Length"}), ([], []))
        self.assertEqual(schemas.missing_arguments("add_arc", {"sketch": "S"}), ([], []))
        self.assertEqual(schemas.missing_arguments("hole", {}), ([], []))
        self.assertEqual(schemas.missing_arguments("request_status", {}), ([], []))
        self.assertEqual(schemas.missing_arguments("no_such_operation", {}), ([], []))
        for op, entry in schemas.OPERATIONS.items():
            self.assertEqual(set(schemas.REQUIRED[op]), set(entry["required"]) - set(entry.get("checked_by_handler", {})))
            self.assertFalse(set(schemas.REQUIRED[op]) & set(entry.get("x-required-when", {})), op)

    def test_no_property_is_required_and_defaulted(self):
        def has_key(value, key):
            if isinstance(value, dict):
                return key in value or any(has_key(item, key) for item in value.values())
            if isinstance(value, (list, tuple)):
                return any(has_key(item, key) for item in value)
            return False
        self.assertFalse(has_key(schemas.DEFS, "default"))
        self.assertFalse(has_key(schemas.FIELDS, "default"))
        self.assertFalse(any("required" in field for field in schemas.FIELDS.values()))
        for op, entry in schemas.OPERATIONS.items():
            for name in entry["fields"]:
                schema = schemas.field_schema(op, name)
                with self.subTest(op=op, field=name):
                    if "default" in schema:
                        self.assertNotIn(name, entry["required"])
                        self.assertFalse(any(name in group for group in entry.get("requires_one_of", ())))
                        self.assertNotIn(name, entry.get("x-required-when", {}))
                    when = schema.get("x-default-when", {})
                    self.assertLessEqual(set(when), {"present_any", "absent", "not_equal"})
                    self.assertTrue(not when or "default" in schema)
                    mentioned = set(when.get("present_any", ())) | set(when.get("absent", ())) | set(when.get("not_equal", {}))
                    self.assertLessEqual(mentioned, schemas.arg_names(op))
        # Every declared default is a valid value of its rendered field schema (enum, type, bounds).
        built = self.built()
        for op, operation in built["operations"].items():
            for name, field in operation["request"]["properties"].items():
                if "default" in field:
                    with self.subTest(op=op, default=name):
                        self.assertTrue(conforms(field["default"], {key: value for key, value in field.items()
                                                                    if key != "default"}, built["$defs"]),
                                        (field["default"], field))
        self.assertFalse(conforms("sideways", built["operations"]["pad"]["request"]["properties"]["end_type"], built["$defs"]))
        self.assertFalse(conforms(1, built["operations"]["pad"]["request"]["properties"]["refine"], built["$defs"]))
        # An explicit null expression clears a formula, so it is never required (C3).
        for op in ("set_expression", "edit_extrusion", "edit_dress_up"):
            entry = schemas.OPERATIONS[op]
            self.assertNotIn("expression", entry["required"])
            self.assertFalse(any("expression" in group for group in entry.get("requires_one_of", ())))

    def test_doc_anchors_name_contract_headings(self):
        text = (ROOT / "docs" / "OPERATION_CONTRACT.md").read_text(encoding="utf-8")
        anchors = {slug(line.lstrip("#")) for line in text.splitlines() if line.startswith("#")}
        for op, entry in schemas.OPERATIONS.items():
            with self.subTest(op=op):
                document, anchor = entry["doc"].split("#")
                self.assertEqual(document, "docs/OPERATION_CONTRACT.md")
                self.assertIn(anchor, anchors)

    # Native behaviour -----------------------------------------------------------
    def test_examples_execute_on_fixtures(self):
        self.runner.recovery_manifest()
        self.runner.leaked_transactions.clear()
        for op in sorted(schemas.OPERATIONS):
            for index, (example, fixture) in enumerate(self.runner.examples(op)):
                with self.subTest(op=op, example=index):
                    request, response = self.runner.run(op, example, fixture)
                    self.assertTrue(response["ok"], json.dumps({"request": request, "response": response}, default=str)[:2000])
        self.runner.close_documents()
        # Exactly the known application-transaction leaks; a fix or a new leak must update the record.
        self.assertEqual(set(self.runner.leaked_transactions), KNOWN_TRANSACTION_LEAKS)

    def test_required_fields_are_necessary_leave_one_out(self):
        # With the generic pre-check patched off (core calls it through this
        # module once contract 3.2 U2a lands; the sentinel test pins that), the
        # handler alone must reject. A missing_required rejection here means the
        # patch did not reach the pre-check, which would make this proof vacuous.
        not_patched = ("generic pre-check not patched off: core must call operation_schemas.missing_arguments "
                       "through the module attribute")

        def handler_rejects(response, message):
            self.assertFalse(response["ok"], message)
            self.assertNotEqual(response["error"].get("reason"), "missing_required", not_patched)
        with patch.object(schemas, "missing_arguments", return_value=([], [])):
            for op in sorted(schemas.OPERATIONS):
                entry = schemas.OPERATIONS[op]
                for index, (example, fixture) in enumerate(self.runner.examples(op)):
                    for field in sorted(set(example) & set(entry["required"])):
                        with self.subTest(op=op, example=index, field=field):
                            request, response = self.runner.run(op, example, fixture, drop=(field,))
                            handler_rejects(response, f"{op} succeeded without required {field}")
                            if field in entry.get("checked_by_handler", {}):
                                self.assertEqual(response["error"]["code"], entry["checked_by_handler"][field], response)
                    for group in entry.get("requires_one_of", ()):
                        if set(group) & set(example):
                            with self.subTest(op=op, example=index, group=group):
                                request, response = self.runner.run(op, example, fixture, drop=tuple(group))
                                handler_rejects(response, f"{op} succeeded without any of {group}")
                    for field, code in sorted(entry.get("checked_by_handler", {}).items()):
                        if field in example and field not in entry["required"]:
                            with self.subTest(op=op, example=index, handler_field=field):
                                request, response = self.runner.run(op, example, fixture, drop=(field,))
                                handler_rejects(response, f"{op} succeeded without {field}")
                                self.assertEqual(response["error"]["code"], code, response)

    def test_generic_precheck_is_called_through_the_module_attribute(self):
        """Patching operation_schemas.missing_arguments reaches core's generic pre-check, or core has none yet.

        The leave-one-out proof patches the module attribute; a core that bound the
        function by name (``from .operation_schemas import missing_arguments``) or
        inlined REQUIRED would ignore the patch and turn that proof vacuous.
        """
        self.runner.fresh("plate")
        _, unpatched = self.runner.dispatch({"op": "rename_feature", "feature": "Pad"})  # generic-required name absent
        self.assertFalse(unpatched["ok"], unpatched)
        wired = unpatched["error"].get("reason") == "missing_required"
        sentinel = (["__probe__"], [])
        self.runner.fresh("plate")
        with patch.object(schemas, "missing_arguments", return_value=sentinel) as probe:
            _, response = self.runner.dispatch({"op": "rename_feature", "feature": "Pad", "name": "Plate body"})
        if wired:
            self.assertEqual(unpatched["error"].get("fields"), ["name"], unpatched)
            self.assertGreaterEqual(probe.call_count, 1, "core's pre-check did not call the patched module attribute")
            self.assertFalse(response["ok"], "core's pre-check ignored the patched missing_arguments")
            self.assertEqual((response["error"]["code"], response["error"].get("reason"), response["error"].get("fields")),
                             ("invalid_argument", "missing_required", ["__probe__"]), response)
        else:
            # Before contract 3.2 U2a nothing calls the pre-check: the handler reports the
            # missing field itself and the valid request succeeds under the sentinel.
            self.assertEqual(probe.call_count, 0)
            self.assertTrue(response["ok"], response)

    def test_optional_fields_never_trip_the_generic_check(self):
        for op in sorted(schemas.OPERATIONS):
            entry = schemas.OPERATIONS[op]
            grouped = {field for group in entry.get("requires_one_of", ()) for field in group}
            for index, (example, fixture) in enumerate(self.runner.examples(op)):
                for field in sorted(set(example) - {"op"} - set(entry["required"]) - grouped
                                    - set(entry.get("checked_by_handler", {}))):
                    with self.subTest(op=op, example=index, field=field):
                        request, response = self.runner.run(op, example, fixture, drop=(field,))
                        if response["ok"]:
                            continue
                        error = response["error"]
                        self.assertNotEqual(error.get("reason"), "missing_required", response)
                        conditional = (error["code"] == "operation_failed" and error["message"] == repr(field)
                                       or error.get("reason") == "missing_conditional")
                        if conditional:
                            self.assertIn(field, entry.get("x-required-when", {}),
                                          f"{op}.{field} is required in some form; document it in x-required-when")
                        else:
                            self.assertNotEqual(error["code"], "operation_failed", response)

    def test_generic_required_covers_every_envelope_only_leak(self):
        """Envelope-only requests: REQUIRED/ONE_OF name exactly the ops that leak operation_failed today."""
        log = Path(os.environ["KURTSHAPE_SESSION_DIR"]) / "kurtshape.log"

        def tracebacks():
            return log.read_text(encoding="utf-8").count("Traceback") if log.exists() else 0
        for op in sorted(schemas.OPERATIONS):
            entry = schemas.OPERATIONS[op]
            fixture = (entry.get("x-example-fixtures") or [entry["x-example-fixture"]])[0]
            with self.subTest(op=op):
                self.runner.fresh(fixture, entry.get("x-example-setup", ()))
                before = tracebacks()
                request, response = self.runner.dispatch({"op": op})
                absent, groups = schemas.missing_arguments(op, request)
                error = {} if response["ok"] else response["error"]
                if absent or groups:
                    # Before U2a the handler leaked operation_failed with a traceback; the
                    # contract 3.2 generic pre-check reports missing_required and logs nothing.
                    self.assertEqual((error.get("code"), error.get("reason")), ("invalid_argument", "missing_required"), response)
                    self.assertEqual(error.get("fields"), list(absent or groups[0]), response)
                    self.assertEqual(tracebacks(), before, "the pre-check logs no traceback")
                else:
                    self.assertNotEqual(error.get("code"), "operation_failed", response)
                    if not response["ok"] and entry.get("checked_by_handler"):
                        self.assertIn(error["code"], set(entry["checked_by_handler"].values()), response)

    def test_envelope_claims_hold_on_dispatch(self):
        """A missing expected_revision gives stale_revision exactly where the schema requires it,
        and bogus values for x-ignored envelope keys leave the example's outcome unchanged."""
        self.runner.recovery_manifest()
        built = self.built()
        for op in sorted(schemas.OPERATIONS):
            examples = self.runner.examples(op)
            if not examples:
                continue
            example, fixture = examples[0]
            request_schema = built["operations"][op]["request"]
            properties = request_schema["properties"]
            with self.subTest(op=op, check="example"):
                _, baseline = self.runner.run(op, example, fixture)
                self.assertTrue(baseline["ok"], baseline)
                expected = outcome(baseline)
            with self.subTest(op=op, check="expected_revision omitted"):
                self.runner.fresh(fixture, schemas.OPERATIONS[op].get("x-example-setup", ()))
                request = self.runner.request(example)
                request.pop("expected_revision", None)
                response = self.core.dispatch(request)
                if "expected_revision" in request_schema["required"]:
                    self.assertEqual(properties["expected_revision"]["x-missing-code"], "stale_revision")
                    self.assertEqual(response.get("error", {}).get("code"), "stale_revision", response)
                else:
                    # View ops take the revision optionally and check it when given (contract 3.2 F2).
                    self.assertTrue(properties["expected_revision"].get("x-ignored")
                                    or properties["expected_revision"].get("x-mismatch-code") == "stale_revision")
                    self.assertEqual(outcome(response), expected)
            if properties["expected_revision"].get("x-mismatch-code"):
                with self.subTest(op=op, check="expected_revision mismatch"):
                    self.runner.fresh(fixture, schemas.OPERATIONS[op].get("x-example-setup", ()))
                    request = self.runner.request(example)
                    request["expected_revision"] = "not-the-revision"
                    response = self.core.dispatch(request)
                    self.assertEqual(response.get("error", {}).get("code"), "stale_revision", response)
            for key in ("document_id", "expected_revision", "request_id"):
                if properties[key].get("x-ignored"):
                    with self.subTest(op=op, check="ignored " + key):
                        self.runner.fresh(fixture, schemas.OPERATIONS[op].get("x-example-setup", ()))
                        request = self.runner.request(example)
                        request[key] = "ignored-" + key
                        self.assertEqual(outcome(self.core.dispatch(request)), expected)

    # Contract 3.2 U2a wiring (F5 §9.2) ---------------------------------------------
    def test_operation_schema_is_on_demand_read_only_and_digest_stable(self):
        self.runner.fresh("plate")
        doc = self.runner.document()
        meta = self.core._meta(doc)
        revision, undo = meta.Revision, doc.UndoCount
        capabilities = self.core.dispatch({"op": "capabilities"})["result"]
        with patch.dict(schemas._BUILT, clear=True):
            response = self.core.dispatch({"op": "operation_schema", "operations": ["pad", "fillet"], "request_id": "schema-1"})
            self.assertTrue(response["ok"], response)
            result = response["result"]
            self.assertEqual(list(result["operations"]), ["pad", "fillet"])
            self.assertEqual((result["contract"], result["contract_revision"], result["schema_version"]), (3, 2, schemas.SCHEMA_VERSION))
            self.assertEqual(result["digest"], capabilities["schemas"]["digest"])
            self.assertEqual(result["digest"], schemas.build(Controller)["digest"])
            self.assertIn("$defs", result)
            self.assertIs(schemas._BUILT[Controller], schemas.build(Controller), "built once, then cached")
            everything = self.core.dispatch({"op": "operation_schema"})["result"]
            self.assertEqual(set(everything["operations"]), set(Controller.OPS))
            self.assertEqual(everything["digest"], result["digest"])
            self.assertEqual(result["operations"]["pad"], everything["operations"]["pad"])
        self.assertEqual((meta.Revision, doc.UndoCount), (revision, undo))
        self.assertEqual(self.core.ledger.status("schema-1")["status"], "not_recorded", "a read is never ledgered")
        self.assertIn("operation_schema", Controller.READ_OPS)
        self.assertIn("operation_schema", Controller.DOCUMENTLESS_OPS)
        self.assertIn("operation_schema", Controller.QUIET_OPS)

    def test_unknown_schema_names_reject(self):
        for operations, detail in ((["pad", "no_such_operation"], {"unknown": ["no_such_operation"]}),
                                   ("pad", {}), (["pad", "pad"], {}), ([5], {}), ({"op": "pad"}, {})):
            with self.subTest(operations=operations):
                response = self.core.dispatch({"op": "operation_schema", "operations": operations})
                self.assertFalse(response["ok"], response)
                self.assertEqual(response["error"]["code"], "invalid_argument")
                self.assertEqual(response["error"]["fields"], ["operations"])
                for key, value in detail.items():
                    self.assertEqual(response["error"][key], value)
        response = self.core.dispatch({"op": "operation_schema", "operations": None})
        self.assertTrue(response["ok"], "an explicit null means every operation")
        self.assertEqual(set(response["result"]["operations"]), set(Controller.OPS))

    def test_capabilities_report_build_schemas_and_read_operations(self):
        import os
        from kurtshape import build_identity
        capabilities = self.core.dispatch({"op": "capabilities"})["result"]
        build = capabilities["build"]
        self.assertEqual(build["pid"], os.getpid())
        self.assertTrue(build["id"].startswith("src-"))
        self.assertRegex(build["source_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(build["source_sha256"], build_identity.snapshot()["sha256"])
        self.assertEqual(build["source_dir"], str(ROOT / "src" / "kurtshape"))
        self.assertIn(build["git"]["state"], {"pending", "ready", "unavailable"})
        self.assertIn("matches_loaded", build["on_disk"])
        self.assertEqual(capabilities["read_operations"], sorted(Controller.READ_OPS))
        self.assertEqual(capabilities["non_mutating_operations"], sorted(Controller.NON_MUTATING_OPS))
        self.assertEqual(capabilities["schemas"], {"operation": "operation_schema", "schema_version": schemas.SCHEMA_VERSION,
                                                   "digest": schemas.build(Controller)["digest"],
                                                   "operation_count": len(Controller.OPS)})
        self.assertEqual(capabilities["request_size_limit_bytes"], 65536)
        diagnostics = self.core.dispatch({"op": "diagnostics"})["result"]
        self.assertEqual(diagnostics["build"]["source_sha256"], build["source_sha256"])
        # Export provenance names the build that wrote the file, constant for the process.
        self.runner.fresh("plate")
        path = self.folder / "provenance-probe.stl"
        self.core.settings.roots.add(self.folder)
        _, response = self.runner.dispatch({"op": "export", "path": str(path)})
        self.assertTrue(response["ok"], response)
        sidecar = json.loads(path.with_suffix(".stl.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["kurtshape_build"], build_identity.provenance())
        self.assertEqual(sidecar["kurtshape_build"]["source_sha256"], build["source_sha256"])
        self.assertEqual(self.core._step_export_provenance(self.runner.document(), [], "step")["kurtshape_build"],
                         build_identity.provenance())

    def test_non_string_document_id_is_unknown_document(self):
        self.runner.fresh("plate")
        for value in (["a"], {"id": "a"}, 5, 2.5, True, None):
            with self.subTest(document_id=repr(value)):
                response = self.core.dispatch({"op": "inspect", "document_id": value})
                self.assertFalse(response["ok"], response)
                self.assertEqual(response["error"]["code"], "unknown_document")
        response = self.core.dispatch({"op": "inspect"})
        self.assertEqual(response["error"]["code"], "unknown_document")

    def test_conditional_missing_fields_report_invalid_argument(self):
        log = Path(os.environ["KURTSHAPE_SESSION_DIR"]) / "kurtshape.log"

        def tracebacks():
            return log.read_text(encoding="utf-8").count("Traceback") if log.exists() else 0
        cases = [
            # legacy pad without length: the handler reads req["length"]
            ({"op": "pad", "id": "Boss", "profile": "BossProfile"}, "missing_conditional", ["length"]),
            # legacy pocket without length for a blind cut
            ({"op": "pocket", "id": "Cut", "profile": "BossProfile", "through_all": False}, "missing_conditional", ["length"]),
            # a face without a studio result field never reaches the legacy profile lookup
            ({"op": "pad", "id": "Boss", "face": {"feature": "Pad", "subelement": "Face6"}, "length": 2},
             "missing_conditional", ["operation", "merge_scope"]),
            # a plain pierce target needs its subelement
            ({"op": "pierce", "sketch": "Target", "geometry": 0, "target": "Crossing"}, "missing_conditional", ["subelement"]),
            # partial sketch_circle: diameter is generic-required
            ({"op": "sketch_circle", "id": "Partial", "x": 1, "y": 2}, "missing_required", ["diameter"]),
        ]
        for request, reason, fields in cases:
            with self.subTest(op=request["op"], fields=fields):
                self.runner.fresh("plate")
                before = tracebacks()
                invariant = (self.core._meta(self.runner.document()).Revision, self.runner.document().UndoCount,
                             sorted(obj.Name for obj in self.runner.document().Objects))
                _, response = self.runner.dispatch(request)
                self.assertFalse(response["ok"], response)
                self.assertEqual(response["error"]["code"], "invalid_argument", response)
                self.assertEqual(response["error"]["reason"], reason, response)
                self.assertEqual(response["error"]["fields"], fields, response)
                self.assertEqual(tracebacks(), before, "a missing field is not an internal error")
                self.assertEqual((self.core._meta(self.runner.document()).Revision, self.runner.document().UndoCount,
                                  sorted(obj.Name for obj in self.runner.document().Objects)), invariant)
        # Both add_arc forms keep the handler's own invalid_argument message.
        for request in ({"op": "add_arc", "sketch": "Target", "radius": 2, "start_angle": 0, "end_angle": 1},
                        {"op": "add_arc", "sketch": "Target", "cx": 0, "cy": 0, "radius": 2}):
            with self.subTest(op="add_arc", request=request):
                self.runner.fresh("plate")
                before = tracebacks()
                _, response = self.runner.dispatch(request)
                self.assertFalse(response["ok"], response)
                self.assertEqual(response["error"]["code"], "invalid_argument")
                self.assertNotEqual(response["error"].get("reason"), "missing_required")
                self.assertEqual(tracebacks(), before)

    def test_missing_field_net_rewrites_only_omitted_arguments(self):
        net = self.core._missing_field_error
        rewritten = net(KeyError("length"), "pad", {"op": "pad", "profile": "Base"})
        self.assertEqual((rewritten.code, rewritten.details["fields"], rewritten.details["reason"]),
                         ("invalid_argument", ["length"], "missing_conditional"))
        self.assertIsNone(net(KeyError("length"), "pad", {"op": "pad", "profile": "Base", "length": 5}), "present")
        self.assertIsNone(net(KeyError("nonsense"), "pad", {"op": "pad"}), "not an argument of pad")
        self.assertIsNone(net(KeyError(3), "pad", {"op": "pad"}), "non-string key")
        self.assertIsNone(net(ValueError("length"), "pad", {"op": "pad"}), "not a KeyError")
        self.assertIsNone(net(KeyError("length"), "no_such_op", {"op": "no_such_op"}), "unknown op")
        self.assertIsNone(net(KeyError("length"), "pad", None), "no request")

    def test_preview_missing_fields_report_valid_false_without_clone(self):
        import tempfile
        self.runner.fresh("plate")
        doc = self.runner.document()
        revision = self.core._meta(doc).Revision
        documents = set(App.listDocuments())
        with patch.object(tempfile, "TemporaryDirectory", side_effect=AssertionError("a clone was made")):
            _, response = self.runner.dispatch({"op": "preview", "proposal": {"op": "pad", "id": "Boss", "length": 3}})
        self.assertTrue(response["ok"], response)
        preview = response["result"]
        self.assertFalse(preview["valid"])
        self.assertFalse(preview["accepted"])
        self.assertEqual(preview["error"]["code"], "invalid_argument")
        self.assertEqual(preview["error"]["reason"], "missing_required")
        self.assertEqual(preview["error"]["fields"], ["profile", "face"], "the one-of group profile|face is named whole")
        self.assertTrue(preview["error"]["one_of"])
        self.assertIsNone(preview["build_status"])
        self.assertEqual(preview["build_errors"], [])
        self.assertIsNone(preview["measurements"])
        self.assertTrue(preview["discarded"])
        self.assertEqual(set(App.listDocuments()), documents)
        self.assertEqual(self.core._meta(doc).Revision, revision)
        # A conditional miss inside the clone is reported the same way, after the clone ran.
        _, response = self.runner.dispatch({"op": "preview", "proposal": {"op": "pad", "id": "Boss", "profile": "BossProfile"}})
        self.assertTrue(response["ok"], response)
        self.assertFalse(response["result"]["accepted"])
        self.assertEqual((response["result"]["error"]["code"], response["result"]["error"]["reason"], response["result"]["error"]["fields"]),
                         ("invalid_argument", "missing_conditional", ["length"]))
        self.assertEqual(set(App.listDocuments()), documents)

    def test_unchanged_optional_cases(self):
        self.runner.fresh("plate")
        response = self.core.dispatch({"op": "request_status"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["status"], "not_recorded")
        _, response = self.runner.dispatch({"op": "set_expression", "feature": "PlateProfile", "parameter": "Height",
                                            "expression": "PlateProfile.Constraints.Width / 2"})
        self.assertTrue(response["ok"], response)
        self.assertAlmostEqual(self.runner.document().PlateProfile.Constraints[self._constraint_index("PlateProfile", "Height")].Value, 30)
        _, response = self.runner.dispatch({"op": "set_expression", "feature": "PlateProfile", "parameter": "Height"})
        self.assertTrue(response["ok"], "an omitted expression clears the formula")
        self.assertEqual([path for path, _ in self.runner.document().PlateProfile.ExpressionEngine], [])
        request = self.runner.request({"op": "rename_feature", "feature": "Pad", "name": "Plate body"})
        request.pop("expected_revision")
        self.assertEqual(self.core.dispatch(request)["error"]["code"], "stale_revision")

    def _constraint_index(self, sketch, name):
        for index, constraint in enumerate(self.runner.document().getObject(sketch).Constraints):
            if constraint.Name == name:
                return index
        raise AssertionError(name)

    def test_up_to_face_selects_the_end(self):
        """Given up_to_face, pad ignores end_type and pocket ignores end_type and through_all (no length needed)."""
        top = {"kind": "closest", "point": [20, 15, 10], "query": {"kind": "owned_by", "part": "Body", "entity_type": "face"}}
        cases = [({"op": "pad", "id": "UpTo", "profile": "BossProfile", "up_to_face": top, "operation": "new"},
                  [{"end_type": "through_all"}, {"end_type": "blind"}]),
                 ({"op": "pocket", "id": "UpToCut", "profile": "BossProfile", "up_to_face": top, "operation": "remove"},
                  [{"end_type": "through_all"}, {"through_all": False}, {"through_all": True}])]
        for request, variants in cases:
            _, base = self.runner.run(request["op"], request, "studio", setup=(), measure=True)
            self.assertTrue(base["ok"], base)
            expected = self.runner.signature(base)
            for extra in variants:
                with self.subTest(op=request["op"], extra=extra):
                    _, response = self.runner.run(request["op"], request, "studio", extra=extra, setup=(), measure=True)
                    self.assertEqual(self.runner.signature(response), expected)

    def declared_defaults(self):
        """{(op, field): merged field schema} for every declared default."""
        return {(op, name): schemas.field_schema(op, name) for op in sorted(schemas.OPERATIONS)
                for name in sorted(schemas.OPERATIONS[op]["fields"]) if "default" in schemas.field_schema(op, name)}

    def default_probes(self, declared):
        """{(op, field): probe} from DEFAULT_PROBES, checked: declared, in the default's mode, one per default."""
        probes = {}
        for probe_name, probe in DEFAULT_PROBES.items():
            op = probe["request"]["op"]
            for name in probe["fields"]:
                self.assertIn((op, name), declared, probe_name)
                rest = {key: value for key, value in probe["request"].items() if key != name}
                self.assertTrue(in_default_mode(declared[(op, name)], rest), (probe_name, name))
                self.assertNotIn((op, name), probes, "one probe per default")
                probes[(op, name)] = probe
        return probes

    def verify_defaults(self, operations=None):
        """Run the default checks (as subtests) for ``operations`` (all when None).

        Returns (declared, succeeded, detected): the declared defaults checked, those with a
        pair in which both requests succeeded, and those whose wrong value changed the signature.
        """
        declared = {key: schema for key, schema in self.declared_defaults().items()
                    if operations is None or key[0] in operations}
        probes = self.default_probes(self.declared_defaults())
        succeeded, detected = set(), set()
        for (op, name), schema in sorted(declared.items()):
            default, wrong = schema["default"], wrong_value(op, name, schema["default"])
            cases = [("example %d" % index, example, fixture, None, None)
                     for index, (example, fixture) in enumerate(self.runner.examples(op))
                     if in_default_mode(schema, {key: value for key, value in example.items() if key != name})]
            if (op, name) in probes:
                probe = probes[(op, name)]
                cases.append(("probe", probe["request"], probe["fixture"], probe["setup"], probe.get("native")))

            def run(case, extra):
                _, request, fixture, setup, native = case
                _, response = self.runner.run(op, request, fixture, drop=(name,), extra=extra, measure=True,
                                              setup=setup, native=native)
                return response, self.runner.signature(response)
            omitted_by_case = {}
            for case in cases:
                with self.subTest(op=op, field=name, case=case[0], check="explicit default equals omission"):
                    explicit, explicit_facts = run(case, {name: default})
                    omitted, omitted_facts = run(case, None)
                    omitted_by_case[case[0]] = (case, omitted, omitted_facts)
                    self.assertEqual(explicit_facts, omitted_facts)
                    if explicit["ok"] and omitted["ok"]:
                        succeeded.add((op, name))
            with self.subTest(op=op, field=name, check="a wrong value changes the signature"):
                self.assertNotEqual(default, wrong)
                order = ["probe"] if (op, name) in probes else [case[0] for case in cases]
                for label in order:
                    if label not in omitted_by_case:
                        continue
                    case, omitted, omitted_facts = omitted_by_case[label]
                    altered, altered_facts = run(case, {name: wrong})
                    if altered_facts != omitted_facts and (omitted["ok"] or altered["ok"]):
                        detected.add((op, name))
                        break
        return declared, succeeded, detected

    def test_declared_defaults_match_handler_behavior(self):
        """Every declared default is what omission does, and the comparison could see a wrong one.

        For each declared default, on every schema example in the default's mode and on its
        DEFAULT_PROBES request, the request with the field set to the default and the request
        without it give the same signature (outcome() plus the native model). Two identical
        rejections agree, but some pair must succeed. On the probe (or else the schema examples
        in mode, in order) the WRONG_VALUES value must change the signature, with the omitted
        or the wrong request succeeding.
        """
        all_declared = self.declared_defaults()
        self.assertGreaterEqual(len(all_declared), 80)
        self.assertEqual(sorted(set(WRONG_VALUES) - set(all_declared)), [], "WRONG_VALUES names undeclared defaults")
        self.assertEqual(sorted(key for key, schema in all_declared.items()
                                if not isinstance(schema["default"], bool) and key not in WRONG_VALUES), [],
                         "every non-boolean default needs a WRONG_VALUES entry")
        declared, succeeded, detected = self.verify_defaults()
        self.assertEqual(set(declared), set(all_declared))
        self.assertEqual(sorted(set(declared) - succeeded), [], "defaults never exercised by a succeeding request")
        self.assertEqual(sorted(set(declared) - detected), [], "defaults whose wrong value the signature cannot see")

if __name__ == "__main__":
    unittest.main()
