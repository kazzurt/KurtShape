"""Per-operation request schemas: the one registry of argument names, types,
units, defaults, required sets and examples (contract 3.2, F5 section 3.1).

Pure data plus small functions. The module imports no kurtshape module at top
level, so any module (core included) can import it without a cycle. Values
owned by other modules (enum tuples, regular expressions, the selector key
table) are named by ``Ref`` and read only when ``build`` renders the schema
document, which happens on demand (the ``operation_schema`` read) and is
cached per controller class. ``missing_arguments`` uses only the import-time
``REQUIRED``/``ONE_OF`` tables and never builds.

Shapes:

* ``DEFS``: shared JSON-schema ``$defs``. They carry type and unit only, never
  a ``default`` and never required-ness.
* ``FIELDS``: shared argument names -> ``{type or $ref, x-unit, description}``.
* ``OPERATIONS[op]``: ``summary``; ``fields`` (every argument name of the op ->
  per-op override, possibly empty; per-op ``default`` values live only here);
  ``required`` (truthful: the request is meaningless without them);
  ``checked_by_handler`` (``{field: code}``: the handler already reports the
  field's absence with that documented code, so the generic pre-check skips
  it); ``requires_one_of`` (groups of alternatives: at least one field of
  each group must be given); ``x-required-when`` (mode-dependent
  requirements, documentation); ``constraints``; ``examples`` with
  ``x-example-fixture`` (``x-example-fixtures`` when examples differ) and
  ``x-example-setup`` requests to run first; ``doc``. Example strings in
  angle brackets are ``EXAMPLE_PLACEHOLDERS``; ``EXAMPLE_FIXTURES`` describes
  the fixtures.

Envelope fields (``op``, ``document_id``, ``expected_revision``, ``request_id``,
``measure``) are derived from the controller's operation classes in ``build``
and are documentation only: the generic check never enforces them.

A field-level ``x-default-when`` says when a mode-dependent ``default``
applies: ``{"present_any": [...]}`` (at least one of these fields is given),
``{"absent": [...]}`` (none of them is given) or ``{"not_equal": {field:
value}}``. ``x-default-id`` documents the ID a created object gets when ``id``
is omitted; it is not a ``default`` (a second unnamed object of the same kind
rejects with ``duplicate_feature``).
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json

SCHEMA_VERSION = 1

# Controller._id (and every typed feature ID) accepts exactly these names
# (re.fullmatch). Anchored so it is also a valid JSON-schema pattern.
FEATURE_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,63}$"
# Assembly object IDs (assembly._id) have no length cap and their own code.
ASSEMBLY_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"
SUBELEMENT_PATTERN = r"^(Face|Edge|Vertex)[1-9][0-9]*$"

ENVELOPE = ("op", "document_id", "expected_revision", "request_id", "measure")
# Matches the early returns of Controller._dispatch; Controller.DOCUMENTLESS_OPS
# (contract 3.2) takes precedence when the class defines it.
DOCUMENTLESS_OPS = frozenset({"capabilities", "list_documents", "request_status", "diagnostics",
                              "assembly_candidates", "operation_schema"})
HISTORY_OPS = frozenset({"undo", "redo", "begin_sketch_edit", "finish_sketch_edit"})
FILE_LIFECYCLE_OPS = frozenset({"save", "export", "adopt"})


class Ref:
    """A value owned by another kurtshape module, read when ``build`` runs.

    ``form``: ``values`` (tuple/list order kept, sets sorted), ``keys`` (dict
    keys in insertion order), ``anchored`` (a re.fullmatch pattern as an
    anchored JSON-schema pattern), ``key_sets`` ({name: sorted keys}) or
    ``scalar`` (a number or string as is). A callable value is called first.
    """

    __slots__ = ("module", "name", "form")

    def __init__(self, module, name, form="values"):
        self.module, self.name, self.form = module, name, form

    @property
    def source(self):
        return self.module + "." + self.name

    def __repr__(self):
        return "Ref(" + self.source + ")"


# Constants that contract 3.2 unit U1 (selectors.schema: U2a) introduces in
# their owning modules. Until a name exists, build() reads these values, which
# equal the literals the handlers use today (test_enums_come_from_code_constants
# pins both). Once the constant exists it always wins; remove an entry then.
TRANSITIONAL = {}
# selectors.schema() is the public accessor (U2a); before it exists the
# private key table it will return is read directly.
TRANSITIONAL_SOURCES = {"selectors.schema": "_SCHEMA"}


def _module(name):
    return importlib.import_module("." + name, __package__ or "kurtshape")


def resolve(ref):
    """The current value of a Ref, in its JSON form."""
    module = _module(ref.module)
    if hasattr(module, ref.name):
        value = getattr(module, ref.name)
    elif ref.source in TRANSITIONAL_SOURCES:
        value = getattr(module, TRANSITIONAL_SOURCES[ref.source])
    elif ref.source in TRANSITIONAL:
        value = TRANSITIONAL[ref.source]
    else:
        raise LookupError("operation_schemas: " + ref.source + " is not defined")
    if callable(value):
        value = value()
    if ref.form == "scalar":
        return value
    if ref.form == "anchored":
        return "^(?:" + value + ")$"
    if ref.form == "keys":
        return list(value)
    if ref.form == "key_sets":
        return {name: sorted(keys) for name, keys in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return list(value)


def _d(name):
    return {"$ref": "#/$defs/" + name}


_DOC = "docs/OPERATION_CONTRACT.md#"
DOC_INTRO = _DOC + "shared-operation-contract"
DOC_30 = _DOC + "contract-30--q03-lightweight-status-and-explicit-checks"
DOC_31 = _DOC + "contract-31--fail-fast-studio-results-typed-helices-and-tight-boxes"
DOC_HISTORICAL = _DOC + "historical-contract-2-additions--october-2-review-follow-up"
DOC_ASSEMBLY = _DOC + "assembly-increment--october-2"
DOC_ASSEMBLY_FOLDERS = _DOC + "instance-folders-assembly-ux-2026-10-24"
DOC_MEASURE = _DOC + "measure-assembly-ux-2026-10-24"
_FOLDER = {"anyOf": [{"type": "string", "maxLength": 2000}, {"type": "null"}],
           "description": "Instance-list folder path such as \"Fasteners/M3\" (created when missing); null or omitted keeps the root"}
DOC_STUDIO = _DOC + "u2-part-studio-and-reference-queries--october-2"
DOC_PATTERNS = _DOC + "pattern-tools"
DOC_PLANES = _DOC + "datum-planes"
DOC_SELECTORS = _DOC + "geometry-references-and-selectors"
DOC_MULTI = _DOC + "multi-edge-references"
DOC_32_BRIDGE = _DOC + "325-identity-schemas-lifecycle-compact-inspect-transport-client"
DOC_32_RENDER = _DOC + "322-model-images"
DOC_32_PARAMETERS = _DOC + "323-parameters"
DOC_32_BATCH = _DOC + "324-atomic-batches-and-preview-accepted"
DOC_SET_VIEW = _DOC + "viewport-camera-set_view-gui-2026-10-20"
_BATCH_STEPS = [{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 62},
                   {"op": "set_expression", "feature": "PlateProfile", "parameter": "Width", "expression": "plate_width"},
                   {"op": "sketch_circle", "id": "BatchSpot", "as": "spot", "x": 10, "y": 10, "diameter": 4},
                   {"op": "add_circle", "sketch": {"$ref": "spot"}, "x": 20, "y": 10, "diameter": 4}]
_RENDER_VIEW = {"anyOf": [{"enum": Ref("render_jobs", "VIEW_NAMES")},
                          {"type": "object", "required": ["direction"], "additionalProperties": False,
                           "properties": {"direction": {"$ref": "#/$defs/direction3"},
                                          "up": {"$ref": "#/$defs/direction3"},
                                          "name": {"type": "string", "minLength": 1, "maxLength": 24}}}]}
_RENDER_HIGHLIGHT = {
    "type": "object", "additionalProperties": False,
    "properties": {"selector": {"description": "A resolve_selector query, including the literal {feature, subelement}"},
                   "input": {"type": "object", "required": ["feature", "name"], "additionalProperties": False,
                             "properties": {"feature": {"type": "string", "minLength": 1}, "name": {"type": "string", "minLength": 1}},
                             "description": "A stored reference input (QueryInputs name, or helper.input) of a feature"},
                   "label": {"type": "string", "minLength": 1, "maxLength": 12,
                             "description": "Printable, unique, no outer spaces; default A, B, C, ... by position"},
                   "note": {"type": "string", "maxLength": 48}},
    "description": "Exactly one of selector or input"}

_QUANTITY = {"anyOf": [{"type": "number"}, {"type": "string"}]}

DEFS = {
    "length": {**_QUANTITY, "x-unit": "mm", "x-max-abs": 1e6,
               "description": "Millimetres: a finite number, or a length quantity string with units and "
                              "arithmetic such as \"1/8 in\" or \"12.7/2\""},
    "positive_length": {**_QUANTITY, "x-unit": "mm", "x-max-abs": 1e6, "x-exclusive-minimum": 0,
                        "description": "Positive millimetres: a number or a length quantity string"},
    "angle": {**_QUANTITY, "x-unit": "rad",
              "description": "Radians: a finite number, or an angle quantity string such as \"90 deg\""},
    "positive_angle": {**_QUANTITY, "x-unit": "rad", "x-exclusive-minimum": 0,
                       "description": "Positive radians, or an angle quantity string such as \"180 deg\""},
    "number": {"type": "number", "description": "Unitless finite number (booleans are not numbers)"},
    "boolean": {"type": "boolean"},
    "vector3": {"type": "array", "items": _d("length"), "minItems": 3, "maxItems": 3, "x-unit": "mm",
                "description": "World [x, y, z] in millimetres"},
    "direction3": {"type": "array", "items": _d("number"), "minItems": 3, "maxItems": 3,
                   "description": "Nonzero [x, y, z] direction; normalized, so it need not be unit length"},
    "point2": {"type": "array", "items": _d("length"), "minItems": 2, "maxItems": 2, "x-unit": "mm",
               "description": "Sketch-local [x, y] in millimetres"},
    "axis": {"type": "object", "properties": {"origin": _d("vector3"), "direction": _d("direction3")},
             "additionalProperties": False,
             "description": "World line {origin, direction}; each key may be omitted (origin [0,0,0], direction [0,0,1])"},
    "feature": {"type": "string", "minLength": 1,
                "description": "Name (stable ID) of an existing native object, as inspect reports it"},
    "new_id": {"type": "string", "pattern": FEATURE_ID_PATTERN,
               "description": "Name for the created native object: an ASCII letter, then up to 63 letters, digits "
                              "or underscores; an existing name rejects with duplicate_feature"},
    "assembly_id": {"type": "string", "pattern": ASSEMBLY_ID_PATTERN,
                    "description": "Name for the created assembly object: an ASCII letter, then letters, digits or "
                                   "underscores (invalid_id otherwise; an existing name rejects with duplicate_id)"},
    "part": {"type": "string", "minLength": 1,
             "description": "Current logical part: its id (inspect studio.parts[].id) or its Body name"},
    "body": {"type": "string", "minLength": 1,
             "description": "PartDesign Body name or logical part id that receives the new work; optional when the "
                            "target, support or profile owns one, or when the document has a single current part "
                            "(ambiguous_body otherwise)"},
    "absolute_path": {"type": "string", "minLength": 1, "description": "Absolute file path"},
    "expression": {"type": "string", "maxLength": 512, "pattern": Ref("extrusion_edit", "EXPRESSION_PATTERN", "anchored"),
                   "description": "Native dimensional formula over named properties and arithmetic, such as "
                                  "\"PlateProfile.Constraints.Width / 10\""},
    "selector": {"type": "object", "required": ["kind"],
                 "x-kinds": Ref("selectors", "schema", "key_sets"),
                 "description": "Authored geometry query; x-kinds lists each kind's allowed keys. Unknown keys "
                                "reject with invalid_selector"},
    "subelement": {"type": "string", "pattern": SUBELEMENT_PATTERN, "description": "Native element name FaceN, EdgeN or VertexN"},
    "native_reference": {"type": "object", "required": ["feature", "subelement"], "additionalProperties": False,
                         "properties": {"feature": _d("feature"), "subelement": _d("subelement")},
                         "description": "Explicit native element of a feature's shape"},
    "selector_reference": {"type": "object", "required": ["selector"], "additionalProperties": False,
                           "properties": {"selector": _d("selector")},
                           "description": "A selector wrapped as {selector: <query>}"},
    "reference": {"anyOf": [_d("native_reference"), _d("selector"), _d("selector_reference")],
                  "description": "One geometry element: {feature, subelement}, a bare selector, or {selector}"},
    "multi_reference": {"type": "object", "required": ["selector", "all"], "additionalProperties": False,
                        "properties": {"selector": _d("selector"), "all": {"const": True}},
                        "description": "Every matching edge of the current part, re-evaluated at each managed rebuild"},
    "support": {"anyOf": [{"type": "object", "required": ["feature"], "additionalProperties": False,
                           "properties": {"feature": _d("feature"),
                                          "subelement": {"type": "string", "pattern": r"^Face[1-9][0-9]*$"}}},
                          _d("selector"), _d("selector_reference")],
                "description": "Planar support: {feature} for a datum plane, {feature, subelement:\"FaceN\"} for a "
                               "planar face of a solid in the same Body, or a face selector"},
    "origin_plane": {"enum": ["XY", "XZ", "YZ"], "description": "Body origin plane"},
    "merge_scope": {"anyOf": [{"const": "auto"},
                              {"type": "array", "items": _d("part"), "minItems": 1, "uniqueItems": True}],
                    "description": "\"auto\" (parts the tool touches; contact counts for Add) or the target parts"},
    "result_operation": {"enum": Ref("studio", "RESULT_OPERATIONS"),
                         "description": "new makes an independent part; add/remove/intersect combine with the merge scope"},
    "color": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 3, "maxItems": 3,
              "description": "RGB, each between 0 and 1"},
    "assembly_reference": {"type": "object", "required": ["instance", "subelement"], "additionalProperties": False,
                           "properties": {"instance": {"type": "string", "description": "Occurrence ID"},
                                          "subelement": {"type": "string", "pattern": r"^((Face|Edge|Vertex)[1-9][0-9]*)?$",
                                                         "description": "\"\" for the occurrence origin, or an analytic "
                                                                        "FaceN, line/circle EdgeN or VertexN"}},
                           "description": "Joint connector on an assembly occurrence"},
}

_PARTS = {"type": "array", "items": _d("part"), "minItems": 1, "uniqueItems": True}

FIELDS = {
    "id": {"$ref": "#/$defs/new_id"},
    "name": {"type": "string", "description": "Visible label (native Label)"},
    "body": _d("body"),
    "part": _d("part"),
    "parts": {**_PARTS, "description": "Distinct current parts"},
    "feature": _d("feature"),
    "features": {"type": "array", "items": _d("feature"), "minItems": 1, "maxItems": 1024, "uniqueItems": True,
                 "description": "Distinct native feature IDs"},
    "sketch": {"$ref": "#/$defs/feature", "description": "Native sketch ID"},
    "profile": {"$ref": "#/$defs/feature", "description": "Native sketch with closed geometry"},
    "path": {"$ref": "#/$defs/absolute_path"},
    "plane": {"$ref": "#/$defs/origin_plane"},
    "support": _d("support"),
    "x": {"$ref": "#/$defs/length", "description": "Sketch-local x"},
    "y": {"$ref": "#/$defs/length", "description": "Sketch-local y"},
    "width": {"$ref": "#/$defs/positive_length"},
    "height": {"$ref": "#/$defs/positive_length"},
    "diameter": {"$ref": "#/$defs/positive_length"},
    "radius": {"$ref": "#/$defs/positive_length"},
    "length": {"$ref": "#/$defs/positive_length", "description": "Blind depth"},
    "size": {"$ref": "#/$defs/positive_length"},
    "thickness": {"$ref": "#/$defs/positive_length"},
    "depth": {"$ref": "#/$defs/positive_length"},
    "spacing": {"$ref": "#/$defs/positive_length", "description": "Distance between neighbouring copies"},
    "pitch": {"$ref": "#/$defs/positive_length", "description": "Rise per turn"},
    "offset": {"$ref": "#/$defs/length", "description": "Signed distance along the finished plane's normal"},
    "distance": {"$ref": "#/$defs/length", "description": "Signed nonzero offset along the face normal"},
    "x1": {"$ref": "#/$defs/length"}, "y1": {"$ref": "#/$defs/length"},
    "x2": {"$ref": "#/$defs/length"}, "y2": {"$ref": "#/$defs/length"},
    "cx": {"$ref": "#/$defs/length", "description": "Arc centre x"},
    "cy": {"$ref": "#/$defs/length", "description": "Arc centre y"},
    "angle": {"$ref": "#/$defs/angle"},
    "start_angle": {"$ref": "#/$defs/angle"},
    "end_angle": {"$ref": "#/$defs/angle"},
    "construction": {"type": "boolean", "description": "Construction geometry stays out of profiles"},
    "closed": {"type": "boolean"},
    "reversed": {"type": "boolean", "description": "Flip the direction"},
    "cascade": {"type": "boolean", "description": "Also delete dependent objects instead of rejecting"},
    "refine": {"type": "boolean", "description": "Native Refine of the result Booleans and input snapshots; pass false for helical cuts"},
    "include_source": {"type": "boolean", "description": "The source parts act (and are consumed) together with their copies"},
    "origin": {"$ref": "#/$defs/vector3"},
    "normal": {"$ref": "#/$defs/direction3"},
    "direction": {"$ref": "#/$defs/direction3"},
    "x_direction": {"$ref": "#/$defs/direction3", "description": "Direction of local +X, projected perpendicular to the normal or axis"},
    "reference_normal": {"$ref": "#/$defs/direction3"},
    "axis": {"$ref": "#/$defs/axis"},
    "operation": {"$ref": "#/$defs/result_operation"},
    "merge_scope": {"$ref": "#/$defs/merge_scope"},
    "count": {"type": "integer", "minimum": 2, "maximum": 100, "description": "Instance count, including the source"},
    "edges": {"type": "array", "minItems": 1, "maxItems": 128,
              "items": {"anyOf": [_d("reference"), _d("multi_reference")]},
              "description": "Edges of the current part: each plain entry resolves to exactly one edge "
                             "(ambiguous_reference otherwise); a multi reference stands for every matching edge"},
    "faces": {"type": "array", "items": _d("reference"), "minItems": 1, "maxItems": 128,
              "description": "Faces of the current part, each resolving to exactly one face"},
    "face": {"$ref": "#/$defs/reference", "description": "One planar face"},
    "up_to_face": {"$ref": "#/$defs/reference", "description": "Face that ends the extrusion"},
    "expression": {"anyOf": [_d("expression"), {"type": "null"}], "description": "Formula, or null to clear it"},
    "parameter": {"type": "string", "minLength": 1,
                  "description": "Parameter name from inspect features[].parameters (a named or indexed sketch "
                                 "dimension, Length, Offset, Angle, Diameter, Depth, Pitch, ...)"},
    "value": {**_QUANTITY, "description": "A number, or a quantity string with units"},
    "index": {"type": "integer", "minimum": 0},
    "color": _d("color"),
    "visible": {"type": "boolean"},
    "targets": {**_PARTS, "description": "Parts that receive the Boolean"},
    "tools": {**_PARTS, "description": "Parts used as tools (consumed unless keep_tools)"},
    "keep_tools": {"type": "boolean"},
    "translation": {"$ref": "#/$defs/vector3"},
    "copy": {"type": "boolean", "description": "Keep the source part and create a new one"},
    "sections": {"type": "array", "items": _d("feature"), "minItems": 2, "description": "Ordered sketch IDs"},
    "ruled": {"type": "boolean"},
    "frenet": {"type": "boolean", "description": "Frenet profile orientation along the path (use true on helices)"},
    "references": {"type": "array", "items": _d("reference"), "minItems": 1, "maxItems": 128,
                   "description": "Edges to project, each resolving to one edge"},
    "defining": {"type": "boolean", "description": "true: projected edges join the profile; false: reference-only geometry"},
    "geometry": {"type": "integer", "minimum": 0, "description": "Zero-based native sketch geometry index"},
    "point": {"enum": [1, 2, 3], "description": "Native point position: 1 start, 2 end, 3 centre"},
    "subelement": {"type": "string", "pattern": r"^Edge[1-9][0-9]*$", "description": "EdgeN of target"},
    "fingerprint": {"type": "string", "description": "SHA-256 content fingerprint from the copy"},
    "owners": {"type": "array", "items": {"type": "string"}, "minItems": 1,
               "description": "Missing operation IDs from orphan_helpers groups"},
    "selector": _d("selector"),
    "request_id": {"type": "string", "minLength": 1, "maxLength": 128},
    "cancel": {"type": "boolean", "description": "Restore the accepted starting sketch instead of finishing"},
    "handedness": {"enum": Ref("modeling_geometry", "HANDEDNESS"), "description": "right turns counter-clockwise seen from the axis tip"},
    "segment_length": {"type": "number", "x-exclusive-minimum": 0, "x-unit": "turns",
                       "description": "Turns per native edge; undivided multi-turn helices give sweep faces OCCT Booleans miss"},
    "base_plane": {"$ref": "#/$defs/origin_plane"},
    "source_feature_id": {"type": "string", "description": "Source-system (Onshape) feature ID stored on the created feature"},
    "source_feature_name": {"type": "string", "description": "Source-system feature name; also the created feature's label"},
    "assembly": {"type": "string", "description": "The document's single KurtShape assembly object (optional)"},
    "instance": {"type": "string", "description": "Assembly occurrence ID"},
    "joint": {"type": "string", "description": "Assembly joint ID"},
    "joint_type": {"enum": Ref("assembly", "KINDS", "keys")},
    "first": _d("assembly_reference"),
    "second": _d("assembly_reference"),
    "center_on": {"$ref": "#/$defs/feature",
                  "description": "Origin-anchored rectangle sketch on the same plane whose centre drives the circle centre"},
}

_SOURCE = {"source_feature_id": {}, "source_feature_name": {}}


def _direction(omitted):
    """B2 (slice A/B U9): the one direction vocabulary of pad, pocket and hole."""
    return {"type": "string", "enum": Ref("studio", "DIRECTIONS"),
            "description": "Side of the profile normal (the sketch's +Z, or a selected face's outward normal) the tool "
                           "runs to. Omitted: " + omitted + ". Replaces reversed, which keeps its own per-operation "
                           "meaning for one release; giving both rejects with invalid_argument"}
_RESULT = {"operation": {"default": "new"}, "merge_scope": {"default": "auto"}, "refine": {"default": True},
           "name": {"description": "Label of a new part (operation new); default from the profile's part or \"Part N\""}}
_UNUSED_NAME = {"description": "Accepted and recorded with the operation; it labels nothing"}
_PATTERN = {"id": {}, "name": _UNUSED_NAME, "body": {},
            "parts": {},
            "operation": {"default": "new"}, "merge_scope": {"default": "auto"},
            "include_source": {"default": False, "description": "true requires operation add or remove"}, **_SOURCE}
_SKETCH_TARGET = {"sketch": {}, "body": {}}
_STUDIO_ID = {"id": {"x-default-id": "StudioFeature"}}
_DEFAULT_AXIS = {"origin": [0, 0, 0], "direction": [0, 0, 1]}

_PLATE_EDGE = {"kind": "closest", "point": [0, 20, 6],
               "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}
_PLATE_TOP = {"kind": "created_by", "feature": "Pad", "entity_type": "face", "cap": "end"}

OPERATIONS = {
    # Reads -----------------------------------------------------------------
    "inspect": {
        "summary": "Read the document: features, parameters, dependencies, build status and measurements",
        "fields": {"detail": {"enum": ["full", "compact"], "default": "full", "x-default-when": {"absent": ["features", "parts"]},
                              "description": "full: every feature row with measurements; compact: the status header, history and "
                                             "part rows, feature rows only for a selection, measurements only when measure is given. "
                                             "features or parts imply compact"},
                   "features": {"type": "array", "items": {"type": "string"}, "uniqueItems": True,
                                "description": "Feature ids whose compact rows to return; unknown ids reject with missing_reference"},
                   "parts": {"type": "array", "items": {"type": "string"}, "uniqueItems": True,
                             "description": "Part ids (or Body names) whose compact rows to return, with the rows of the "
                                            "features they own or output; unknown ids reject with missing_part"}},
        "required": [],
        "constraints": ["detail full together with features or parts rejects with invalid_argument"],
        "examples": [{"op": "inspect"}, {"op": "inspect", "measure": "full"}, {"op": "inspect", "detail": "compact"},
                     {"op": "inspect", "features": ["Pad"]}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "list_documents": {
        "summary": "Inspect every document open in this session",
        "fields": {"detail": {"enum": ["full", "compact"], "default": "full",
                              "description": "full: the full inspection of every open document; compact: one status header "
                                             "row per document with feature_count and part_count"}},
        "required": [],
        "examples": [{"op": "list_documents", "measure": False}, {"op": "list_documents", "detail": "compact"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "capabilities": {
        "summary": "Contract identity, supported operations, measurement levels and limits",
        "fields": {}, "required": [], "examples": [{"op": "capabilities"}], "x-example-fixture": "none",
        "doc": DOC_HISTORICAL},
    "close_document": {
        "summary": "Close an open document; unsaved changes need discard:true, which writes a discard checkpoint first",
        "fields": {"discard": {"type": "boolean", "default": False,
                               "description": "Close although the document has unsaved changes (a managed document is "
                                              "checkpointed first); never-saved documents always need it"}},
        "required": [],
        "constraints": ["Rejects while an editor is open on the document (user_editing), while another open document "
                        "links into it (document_in_use), with unsaved changes and no discard (unsaved_changes), and "
                        "for an unmanaged file with changes even with discard",
                        "Not previewable and not batchable; an identical retry replays the closed result"],
        "examples": [{"op": "close_document"}], "x-example-fixture": "plate", "doc": DOC_32_BRIDGE},
    "operation_schema": {
        "summary": "Argument schemas, defaults, constraints and examples of the operations this build supports",
        "fields": {"operations": {"type": "array", "items": {"type": "string"}, "uniqueItems": True,
                                  "description": "Operation names to return; omitted means every operation"}},
        "required": [],
        "constraints": ["operations must be a list of distinct supported names (invalid_argument with unknown otherwise)",
                        "Read-only and never ledgered; cache the result by its digest"],
        "examples": [{"op": "operation_schema"}, {"op": "operation_schema", "operations": ["pad", "fillet"]}],
        "x-example-fixture": "none", "doc": DOC_32_BRIDGE},
    "render_view": {
        "summary": "Render orthographic PNG images (views, sections, labelled highlights) of the current parts; "
                   "read-only, ledger-tracked",
        "fields": {
            "views": {"type": "array", "items": _RENDER_VIEW, "minItems": 1, "maxItems": Ref("render_jobs", "MAX_VIEWS", "scalar"),
                      "default": ["iso"], "x-default-when": {"absent": ["section"]},
                      "description": "Distinct view names (iso, front, back, right, left, top, bottom, section) or "
                                     "{direction, up?, name?}; [\"section\"] when a section is given, else [\"iso\"]"},
            "layout": {"enum": Ref("render_jobs", "LAYOUTS"), "default": "separate",
                       "description": "separate: one PNG per view; sheet: one PNG tiling 2 to 7 views"},
            "size": {"type": "array", "items": {"type": "integer", "minimum": 128, "maximum": 2048},
                     "minItems": 2, "maxItems": 2, "default": [1024, 768],
                     "x-default-when": {"not_equal": {"layout": "sheet"}},
                     "description": "[width, height] in whole pixels (JSON integers; 320.0 is rejected), at most "
                                    "3145728 pixels; the declared default applies to separate images, a sheet of 2 to "
                                    "4 views also defaults to [1024, 768] and a sheet of 5 to 7 views to [1536, 1152]; "
                                    "sheet tiles must stay at least 320 x 240"},
            "parts": {"anyOf": [{"enum": Ref("render_jobs", "PART_MODES")},
                                {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "uniqueItems": True}],
                      "default": "all",
                      "description": "all, visible (KurtShapePartVisible, else the object's Visibility) or part, "
                                     "result or sketch ids; an unknown id rejects with missing_part"},
            "frame": {"anyOf": [{"enum": Ref("render_jobs", "FRAMES")},
                                {"type": "object", "required": ["center_mm", "width_mm"], "additionalProperties": False,
                                 "properties": {"center_mm": {"$ref": "#/$defs/vector3"},
                                                "width_mm": {"$ref": "#/$defs/positive_length"}}}],
                      "default": "included",
                      "description": "included parts (kept side of a section), the whole model, the rendered "
                                     "highlights, or an explicit window"},
            "highlights": {"type": "array", "items": _RENDER_HIGHLIGHT, "maxItems": Ref("render_jobs", "MAX_HIGHLIGHTS", "scalar"),
                           "description": "Labelled highlights; matches outside the shown geometry are drawn as dashed "
                                          "ghosts and never count as visible"},
            "labels": {"type": "boolean", "default": True, "description": "Highlight labels and legend"},
            "part_labels": {"type": "boolean", "default": False, "description": "Short part tags"},
            "sketches": {"enum": Ref("render_jobs", "SKETCH_MODES"), "default": "auto",
                         "description": "auto draws the included active sketches only when no included part has faces"},
            "section": {"type": "object",
                        "description": "{origin, normal}, {plane: XY|XZ|YZ, offset} (native normals XY +Z, XZ -Y, YZ +X; "
                                       "offset along the normal, as create_plane) or {datum}; removes the material on "
                                       "the +normal side in every view"},
            "edges": {"type": "boolean", "default": True, "description": "BREP feature edges"},
            "quality": {"enum": Ref("render_jobs", "QUALITIES"), "default": "standard",
                        "description": "standard: 2x supersampling up to 1.1 MP; draft: 1x and a doubled tolerance"}},
        "required": [],
        "constraints": ["Read-only and allowed on unmanaged documents; expected_revision is optional and checked when "
                        "given (stale_revision)",
                        "Ledger-tracked: through the bridge request_id is required; on timeout reconcile with "
                        "request_status, or resend with a new request_id (identical settings hit the cache or join "
                        "the running job)",
                        "One render runs at a time; a different request meanwhile gets render_busy {retry_after_ms}",
                        "Not previewable and not batchable"],
        "examples": [{"op": "render_view", "size": [320, 240], "quality": "draft"},
                     {"op": "render_view", "section": {"plane": "XZ", "offset": -20}, "size": [320, 240],
                      "quality": "draft",
                      "highlights": [{"selector": _PLATE_TOP, "label": "A", "note": "pad top face"}]}],
        "x-example-fixture": "plate", "doc": DOC_32_RENDER},
    "set_view": {
        "summary": "Aim the running app's 3D view of the document (orthographic camera); the camera is saved in "
                   "the FCStd and restored on open. Never changes the document; headless reports applied:false",
        "fields": {
            "view": {"anyOf": [{"enum": Ref("gui_view", "VIEW_NAMES")},
                               {"type": "object", "required": ["direction"], "additionalProperties": False,
                                "properties": {"direction": {"$ref": "#/$defs/direction3"},
                                               "up": {"$ref": "#/$defs/direction3"}}}],
                     "default": "iso",
                     "description": "A view name (render_view's directions) or {direction, up?}; the camera looks "
                                    "along direction with up toward the top of the window"},
            "frame": {"anyOf": [{"enum": Ref("gui_view", "FRAMES")},
                                {"type": "object", "required": ["center_mm", "width_mm"], "additionalProperties": False,
                                 "properties": {"center_mm": {"$ref": "#/$defs/vector3"},
                                                "width_mm": {"$ref": "#/$defs/positive_length"}}}],
                      "default": "model",
                      "description": "model: the shown solids and faces with a 5 % margin; or an explicit window "
                                     "whose width_mm spans the window's shorter side"}},
        "required": [],
        "constraints": ["Changes only the GUI camera: the revision, undo history and Modified flag stay; allowed "
                        "on unmanaged documents; expected_revision is optional and checked when given "
                        "(stale_revision)",
                        "Ledger-tracked: through the bridge request_id is required",
                        "Headless (no GUI) the camera is computed and returned with applied:false, reason no_gui",
                        "Refused while a sketch or native feature edit is active (sketch_edit_active)",
                        "Not previewable and not batchable"],
        "examples": [{"op": "set_view", "view": "top"},
                     {"op": "set_view", "view": {"direction": [0, 1, -1], "up": [0, 0, 1]},
                      "frame": {"center_mm": [30, 0, 3], "width_mm": 20}}],
        "x-example-fixture": "plate", "doc": DOC_SET_VIEW},
    "list_parameters": {
        "summary": "The document's model parameters with values, formulas, consumers and the features and parts they affect",
        "fields": {"names": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1,
                             "maxItems": Ref("parameters", "MAX_NAMES", "scalar"), "uniqueItems": True,
                             "description": "Parameter names to return; omitted means every parameter (unknown names "
                                            "reject with missing_parameter)"}},
        "required": [],
        "constraints": ["Read-only; works on unmanaged documents", "Warnings report dangling references and extra sets"],
        "examples": [{"op": "list_parameters"}], "x-example-fixture": "plate", "doc": DOC_32_PARAMETERS},
    "create_parameter": {
        "summary": "Create a model parameter (length, angle or number) with a value, a formula over other parameters, "
                   "or by promoting existing dimensions (bind)",
        "fields": {"name": {"type": "string", "pattern": Ref("parameters", "NAME_PATTERN", "scalar"),
                            "description": "Starts with a lowercase letter, e.g. shaft_diameter; also not a unit, "
                                           "constant, function or attribute of the set (invalid_parameter_name)"},
                   "type": {"enum": Ref("parameters", "TYPE_NAMES"),
                            "description": "length (mm), angle (rad on the wire, stored in degrees) or number; inferred "
                                           "from bind targets, a quantity string or the formula's unit when omitted"},
                   "value": {"anyOf": [{"type": "number"}, {"type": "string"}],
                             "description": "Wire units (mm, rad, unitless) or a quantity string such as \"15 deg\""},
                   "expression": {"type": "string", "maxLength": 512,
                                  "pattern": Ref("parameters", "EXPRESSION_PATTERN", "anchored"),
                                  "description": "Formula over other parameters only (bare or Params.<name>)"},
                   "bind": {"type": "array", "minItems": 1, "maxItems": Ref("parameters", "MAX_BIND", "scalar"),
                            "items": {"type": "object", "required": ["feature", "parameter"], "additionalProperties": False,
                                      "properties": {"feature": {"type": "string", "minLength": 1},
                                                     "parameter": {"type": "string", "minLength": 1}}},
                            "description": "Dimensions (inspect native parameters) to drive by the new parameter; "
                                           "without value or expression they must agree and give the value"}},
        "required": ["name"],
        "constraints": ["At most one of value and expression; one of value, expression or bind",
                        "Bind targets must be driving, not formula-driven, and of the parameter's unit",
                        "One managed rebuild for any number of bind targets"],
        "examples": [{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 60},
                     {"op": "create_parameter", "name": "plate_depth",
                      "bind": [{"feature": "PlateProfile", "parameter": "Height"}]}],
        "x-example-fixture": "plate", "doc": DOC_32_PARAMETERS},
    "edit_parameter": {
        "summary": "Change a parameter's value or formula; dependents rebuild, unchanged consumers are pruned",
        "fields": {"name": {"type": "string", "minLength": 1},
                   "value": {"anyOf": [{"type": "number"}, {"type": "string"}],
                             "description": "New value (wire units or a quantity string); with expression:null it "
                                           "replaces a formula in one step"},
                   "expression": {"anyOf": [{"type": "string", "maxLength": 512,
                                             "pattern": Ref("parameters", "EXPRESSION_PATTERN", "anchored")},
                                            {"type": "null"}],
                                  "description": "New formula, or null to clear it and keep the value"}},
        "required": ["name"],
        "checked_by_handler": {"value": "invalid_argument", "expression": "invalid_argument"},
        "constraints": ["Give value, expression or both with expression:null",
                        "A value on a formula-driven parameter rejects with expression_driven",
                        "On failure error.parameter.accepted holds the restored value and formula"],
        "examples": [{"op": "edit_parameter", "name": "plate_width", "value": 62}],
        "x-example-setup": [{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 60}],
        "x-example-fixture": "plate", "doc": DOC_32_PARAMETERS},
    "rename_parameter": {
        "summary": "Rename a parameter; every consumer formula is rewritten natively and verified",
        "fields": {"name": {"type": "string", "minLength": 1, "description": "Any listed name"},
                   "new_name": {"type": "string", "pattern": Ref("parameters", "NAME_PATTERN", "scalar")}},
        "required": ["name", "new_name"],
        "constraints": ["Not batchable", "A consumer whose value would change or break rejects with rename_failed"],
        "examples": [{"op": "rename_parameter", "name": "plate_width", "new_name": "width"}],
        "x-example-setup": [{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 60}],
        "x-example-fixture": "plate", "doc": DOC_32_PARAMETERS},
    "delete_parameter": {
        "summary": "Delete a parameter; consumers reject unless freeze_consumers keeps their current values",
        "fields": {"name": {"type": "string", "minLength": 1},
                   "freeze_consumers": {"type": "boolean", "default": False,
                                        "description": "Clear the formulas that read it (their values stay)"}},
        "required": ["name"],
        "constraints": ["Not batchable", "With consumers and no freeze: parameter_in_use"],
        "examples": [{"op": "delete_parameter", "name": "plate_width"}],
        "x-example-setup": [{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 60}],
        "x-example-fixture": "plate", "doc": DOC_32_PARAMETERS},
    "batch": {
        "summary": "Run 1-32 modeling steps as one native transaction: one undo step and one revision change, "
                   "or nothing at all when any step or the final result check fails",
        "fields": {"steps": {"type": "array", "minItems": 1, "maxItems": Ref("batch", "MAX_STEPS", "scalar"),
                             "items": {"type": "object", "required": ["op"],
                                       "properties": {"op": {"enum": Ref("batch", "operations")},
                                                      "as": {"type": "string",
                                                             "pattern": Ref("batch", "ALIAS_PATTERN", "scalar")}}},
                             "description": "Each step is a modeling request without envelope fields, plus an optional "
                                            "alias \"as\"; {\"$ref\": alias} stands for that earlier step's created "
                                            "feature and {\"$part\": alias} for its single output part, as whole values"},
                   "label": {"type": "string", "minLength": 1, "maxLength": Ref("batch", "MAX_LABEL", "scalar"),
                             "description": "Names the undo step: KurtShape: batch <label>"}},
        "required": ["steps"],
        "constraints": ["Steps run in order through the single-operation gates; result checks run once before the "
                        "commit, so a later step may repair an earlier one",
                        "A failure names the step (error.batch.step, phase step or final_validation) and rolls "
                        "everything back",
                        "Not batchable: every operation outside MODEL_OPS and capabilities.batch.excluded",
                        "Preview with proposal {op: batch, steps, label?} first; accepted means the commit would succeed"],
        "examples": [{"op": "batch", "label": "plate width", "steps": _BATCH_STEPS}],
        "x-example-fixture": "plate", "doc": DOC_32_BATCH},
    "request_status": {
        "summary": "Status of a bridge request_id in this session's ledger, with its retained response",
        "fields": {"request_id": {"description": "The request ID to look up; omitted reports not_recorded"}},
        "required": [],
        "constraints": ["not_recorded does not prove a request never executed"],
        "examples": [{"op": "request_status", "request_id": "agent-0001"}], "x-example-fixture": "none",
        "doc": DOC_HISTORICAL},
    "preview": {
        "summary": "Evaluate a modeling proposal on a disposable clone; nothing changes",
        "fields": {"proposal": {"type": "object", "required": ["op"],
                                "description": "A modeling request (its op and arguments, no envelope); any MODEL "
                                               "operation except rebuild, or a batch {op: batch, steps, label?}"}},
        "required": ["proposal"], "checked_by_handler": {"proposal": "unsupported_preview"},
        "constraints": ["A read: expected_revision is optional and checked when given (stale_revision); omitted, the "
                        "proposal is evaluated against the current revision, which base_revision reports",
                        "Commit sends the operation afresh against the preview's base revision",
                        "accepted is true exactly when the commit would succeed; a batch proposal is echoed as "
                        "{op, label, step_count} and reports batch_report"],
        "examples": [{"op": "preview", "proposal": {"op": "set_parameter", "feature": "Pad", "parameter": "Length", "value": 8}},
                     {"op": "preview", "proposal": {"op": "batch", "steps": _BATCH_STEPS}}],
        "x-example-fixture": "plate", "doc": DOC_HISTORICAL},
    "diagnostics": {
        "summary": "Bounded timing samples and the checkpoint location",
        "fields": {}, "required": [], "examples": [{"op": "diagnostics"}], "x-example-fixture": "none",
        "doc": DOC_HISTORICAL},
    "assembly_candidates": {
        "summary": "Selectable native solids of an FCStd or STEP source, with final/helper/history roles",
        "fields": {"path": {"description": "Absolute existing source file", "x-suffixes": [".FCStd", ".step", ".stp"]},
                   "final_only": {"type": "boolean", "default": False, "description": "Only current final results; false preserves legacy candidate membership"}},
        "required": ["path"], "checked_by_handler": {"path": "invalid_assembly_source"},
        "examples": [{"op": "assembly_candidates", "path": "<plate_file>"}], "x-example-fixture": "none",
        "doc": DOC_ASSEMBLY},
    "measure": {
        "summary": "Measure 1-24 references in global coordinates: length/area/Ø, distances with ΔX ΔY ΔZ, angles",
        "fields": {"references": {"type": "array", "minItems": 1, "maxItems": 24, "items": {"type": "object"},
                                  "description": "Selectors (each must match one element) or {object, subelement} "
                                                 "native references; an occurrence's subelement is measured where it "
                                                 "sits in the assembly; an omitted subelement measures the whole object"}},
        "required": ["references"], "checked_by_handler": {"references": "invalid_argument"},
        "constraints": ["Read-only; returns {kind, text, values}: the same readout the GUI shows for a selection",
                        "Parallel/perpendicular within 0.5°, coaxial within 1 µm radial; lengths mm, angles degrees"],
        "examples": [{"op": "measure", "references": [_PLATE_TOP]}],
        "x-example-fixture": "plate", "doc": DOC_MEASURE},
    "assembly_instance_source": {
        "summary": "The saved source an occurrence was embedded from: path, kind (fcstd/step), whether it exists and is open",
        "fields": {"assembly": {}, "instance": {"type": "string", "description": "Occurrence id"}},
        "required": ["instance"], "checked_by_handler": {"instance": "missing_assembly_instance"},
        "constraints": ["Read-only; the embedded snapshot's SourcePath is the source of truth",
                        "exists is a file check, not a hash; open_documents lists open documents of that file"],
        "examples": [{"op": "assembly_instance_source", "instance": "Free"}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY_FOLDERS},
    "part_inventory": {
        "summary": "Current usable solids across legacy, studio and assembly documents",
        "fields": {"include_history": {"type": "boolean", "default": False,
                                         "description": "Include helper, historical and embedded-source solids with explicit roles"}},
        "required": [], "examples": [{"op": "part_inventory"}], "x-example-fixture": "plate",
        "doc": DOC_ASSEMBLY},
    "resolve_selector": {
        "summary": "Matched native elements of a selector, with part identity and geometry summaries",
        "fields": {"selector": {}}, "required": ["selector"], "checked_by_handler": {"selector": "invalid_selector"},
        "examples": [{"op": "resolve_selector", "selector": _PLATE_TOP}], "x-example-fixture": "plate",
        "doc": DOC_SELECTORS},
    "check_geometry": {
        "summary": "Explicit cached BRepCheck of current solids, with per-result issues",
        "fields": {"body": {"description": "Current result or logical part to check; omitted checks all"}},
        "required": [],
        "examples": [{"op": "check_geometry"}, {"op": "check_geometry", "body": "Body"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "orphan_helpers": {
        "summary": "Helper groups whose owning studio operation no longer exists",
        "fields": {}, "required": [], "examples": [{"op": "orphan_helpers"}], "x-example-fixture": "plate",
        "doc": DOC_30},

    # Documents -------------------------------------------------------------
    "new": {
        "summary": "New managed document with one empty Body",
        "fields": {"name": {"default": "New part",
                            "description": "Document label (converted to text, truncated to 120 characters)"}},
        "required": [], "examples": [{"op": "new", "name": "Bracket"}], "x-example-fixture": "none",
        "doc": DOC_INTRO},
    "open": {
        "summary": "Open an existing native FCStd file",
        "fields": {"path": {"x-suffixes": [".FCStd"]}}, "required": ["path"],
        "constraints": ["A second copy of a project that is already open rejects (duplicate_document_id)"],
        "examples": [{"op": "open", "path": "<plate_file>"}], "x-example-fixture": "none", "doc": DOC_INTRO},
    "recover": {
        "summary": "Open a verified checkpoint as a new unsaved document",
        "fields": {"path": {"description": "Absolute checkpoint manifest (.json) in the session's project-recovery folder",
                            "x-suffixes": [".json"]}},
        "required": ["path"], "examples": [{"op": "recover", "path": "<recovery_manifest>"}],
        "x-example-fixture": "none", "doc": DOC_HISTORICAL},
    "import_step": {
        "summary": "New managed unsaved document from a STEP file: one Body per solid",
        "fields": {"path": {"description": "Absolute existing STEP file", "x-suffixes": [".step", ".stp"]}},
        "required": ["path"], "checked_by_handler": {"path": "invalid_argument"},
        "examples": [{"op": "import_step", "path": "<step_file>"}], "x-example-fixture": "none", "doc": DOC_30},
    "adopt": {
        "summary": "Save a managed copy of the document under a new path and project identity",
        "fields": {"path": {"description": "Absolute new .FCStd path in a granted project folder", "x-suffixes": [".FCStd"]}},
        "required": ["path"], "constraints": ["The destination must not exist"],
        "examples": [{"op": "adopt", "path": "<project>/adopted.FCStd"}], "x-example-fixture": "plate",
        "doc": DOC_HISTORICAL},
    "save": {
        "summary": "Staged native save with a recovery copy of the previous file",
        "fields": {"path": {"description": "Absolute .FCStd path in a granted project folder. A destination another program "
                                           "holds open (or a read-only one) rejects with save_destination_locked, naming the "
                                           "file and the OS reason; the previous file is kept and the save can be retried",
                            "x-suffixes": [".FCStd"]},
                   # Slice A/B U8 (A8): another project's file is never replaced silently.
                   "overwrite": {"type": "boolean", "default": False,
                                 "description": "Replace an existing FCStd that holds another project (another document_id, or "
                                                "no KurtShape project); without it such a destination rejects with "
                                                "save_destination_other_project. The document's own file and a new path "
                                                "need no flag"}},
        "required": ["path"], "examples": [{"op": "save", "path": "<project>/plate.FCStd"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "export": {
        "summary": "Export current solid results with provenance; requires a current build and valid geometry checks",
        "fields": {"path": {"description": "Absolute path in a granted project folder", "x-suffixes": [".step", ".stp", ".stl"]},
                   "body": {"description": "Export only this current result or part (not for assemblies)"}},
        "required": ["path"],
        "examples": [{"op": "export", "path": "<project>/plate.step"},
                     {"op": "export", "path": "<project>/plate.stl", "body": "Body"}],
        "x-example-fixture": "plate", "doc": DOC_30},

    # History ---------------------------------------------------------------
    "undo": {
        "summary": "Native undo, or one sketch step inside a managed sketch edit",
        "fields": {}, "required": [], "examples": [{"op": "undo"}],
        "x-example-setup": [{"op": "rename_feature", "feature": "Pad", "name": "Plate body"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "redo": {
        "summary": "Native redo, or one sketch step inside a managed sketch edit",
        "fields": {}, "required": [], "examples": [{"op": "redo"}],
        "x-example-setup": [{"op": "rename_feature", "feature": "Pad", "name": "Plate body"}, {"op": "undo"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "begin_sketch_edit": {
        "summary": "Start an exclusive managed edit lease on a sketch",
        "fields": {"feature": {"description": "Sketch to edit"}, "body": {}},
        "required": ["feature"], "examples": [{"op": "begin_sketch_edit", "feature": "Target"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "finish_sketch_edit": {
        "summary": "Finish the managed sketch edit as one history step, or cancel it",
        "fields": {"cancel": {"default": False}}, "required": [],
        "examples": [{"op": "finish_sketch_edit"}],
        "x-example-setup": [{"op": "begin_sketch_edit", "feature": "Target"}],
        "x-example-fixture": "plate", "doc": DOC_30},

    # Sketches --------------------------------------------------------------
    "create_body": {
        "summary": "New native PartDesign Body",
        "fields": {"id": {"x-default-id": "Body"}, "name": {"description": "Label; defaults to the ID"}, **_SOURCE},
        "required": [], "examples": [{"op": "create_body", "id": "Second", "name": "Second part"}],
        "x-example-fixture": "plate", "doc": DOC_HISTORICAL},
    "create_sketch": {
        "summary": "Empty attached native sketch on an origin plane, datum plane or planar face",
        "fields": {"id": {"x-default-id": "Sketch"},
                   "plane": {"default": "XY", "x-default-when": {"absent": ["support"]}},
                   "support": {}, "body": {}, **_SOURCE},
        "required": [], "constraints": ["plane and support are mutually exclusive"],
        "examples": [{"op": "create_sketch", "id": "FrontSketch", "plane": "XZ"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "sketch_rectangle": {
        "summary": "New sketch holding a closed, fully constrained rectangle with Width/Height dimensions",
        "fields": {"id": {"x-default-id": "Rectangle"}, "width": {}, "height": {},
                   "x": {"default": 0, "description": "Lower-left corner x"}, "y": {"default": 0, "description": "Lower-left corner y"},
                   "plane": {"default": "XY", "x-default-when": {"absent": ["support"]}},
                   "support": {}, "body": {}, **_SOURCE},
        "required": ["width", "height"], "constraints": ["plane and support are mutually exclusive"],
        "examples": [{"op": "sketch_rectangle", "id": "Tab", "width": 10, "height": 5, "x": 5, "y": 5, "plane": "XZ"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "sketch_circle": {
        "summary": "New sketch holding a constrained circle",
        "fields": {"id": {"x-default-id": "Circle"}, "x": {"description": "Centre x"}, "y": {"description": "Centre y"},
                   "diameter": {}, "center_on": {},
                   "plane": {"default": "XY", "x-default-when": {"absent": ["support"]}},
                   "support": {}, "body": {}, **_SOURCE},
        "required": ["x", "y", "diameter"],
        "constraints": ["plane and support are mutually exclusive",
                        "center_on needs a nonzero centre and a named origin-anchored rectangle on the same plane"],
        "examples": [{"op": "sketch_circle", "id": "Bore", "x": 10, "y": 3, "diameter": 4, "plane": "XZ"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "add_rectangle": {
        "summary": "Append a constrained rectangle to an existing sketch",
        "fields": {**_SKETCH_TARGET, "width": {}, "height": {},
                   "x": {"default": 0, "description": "Lower-left corner x"}, "y": {"default": 0, "description": "Lower-left corner y"},
                   "construction": {"default": False}},
        "required": ["sketch", "width", "height"],
        "examples": [{"op": "add_rectangle", "sketch": "Target", "width": 4, "height": 3, "x": 10, "y": 10}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "add_circle": {
        "summary": "Append a constrained circle to an existing sketch",
        "fields": {**_SKETCH_TARGET, "x": {"description": "Centre x"}, "y": {"description": "Centre y"}, "diameter": {},
                   "construction": {"default": False}},
        "required": ["sketch", "x", "y", "diameter"],
        "examples": [{"op": "add_circle", "sketch": "Target", "x": 20, "y": 20, "diameter": 5}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "add_line": {
        "summary": "Append a line with driving endpoint coordinates",
        "fields": {**_SKETCH_TARGET, "x1": {}, "y1": {}, "x2": {}, "y2": {}, "construction": {"default": False}},
        "required": ["sketch", "x1", "y1", "x2", "y2"],
        "constraints": ["Endpoints must be distinct",
                        "A non-construction endpoint on a fixed arc endpoint joins it with a native Coincident"],
        "examples": [{"op": "add_line", "sketch": "Target", "x1": 10, "y1": 30, "x2": 25, "y2": 30}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "add_arc": {
        "summary": "Append a fully constrained counter-clockwise circular arc",
        "fields": {**_SKETCH_TARGET, "cx": {}, "cy": {},
                   "radius": {"description": "Centre form"}, "start_angle": {"description": "Centre form"},
                   "end_angle": {"description": "Centre form"},
                   "x1": {"description": "Endpoint form: start x"}, "y1": {"description": "Endpoint form: start y"},
                   "x2": {"description": "Endpoint form: end x"}, "y2": {"description": "Endpoint form: end y"},
                   "construction": {"default": False}},
        "required": ["sketch", "cx", "cy"], "checked_by_handler": {"cx": "invalid_argument", "cy": "invalid_argument"},
        "x-required-when": {"radius": "centre form (no x1/y1/x2/y2 given)",
                            "start_angle": "centre form (no x1/y1/x2/y2 given)",
                            "end_angle": "centre form (no x1/y1/x2/y2 given)",
                            "x1": "endpoint form", "y1": "endpoint form", "x2": "endpoint form", "y2": "endpoint form"},
        "constraints": ["Give exactly one form: radius/start_angle/end_angle or x1/y1/x2/y2",
                        "Sweep is nonzero and below 360 deg; endpoint radii agree within 1e-6 mm"],
        "examples": [{"op": "add_arc", "sketch": "Target", "cx": 20, "cy": -10, "radius": 5, "start_angle": 0,
                      "end_angle": "90 deg"},
                     {"op": "add_arc", "sketch": "Target", "cx": 0, "cy": 20, "x1": 5, "y1": 20, "x2": 0, "y2": 25}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "add_polyline": {
        "summary": "Append connected line segments joined by native coincidences",
        "fields": {**_SKETCH_TARGET,
                   "points": {"type": "array", "items": _d("point2"), "minItems": 2, "maxItems": 1000,
                              "description": "Vertices [[x, y], ...]; do not repeat the first point (use closed)"},
                   "closed": {"default": False, "description": "Add the closing segment (needs 3 or more points)"},
                   "construction": {"default": False}},
        "required": ["sketch", "points"], "checked_by_handler": {"points": "invalid_argument"},
        "examples": [{"op": "add_polyline", "sketch": "Target", "points": [[30, 30], [40, 30], [40, 40]], "closed": True}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "set_sketch_support": {
        "summary": "Replace a sketch's support, keeping its local geometry, constraints and expressions",
        "fields": {**_SKETCH_TARGET, "plane": {}, "support": {}},
        "required": ["sketch"],
        "checked_by_handler": {"plane": "invalid_argument", "support": "invalid_argument"},
        "constraints": ["Exactly one of plane or support"],
        "examples": [{"op": "set_sketch_support", "sketch": "Target", "plane": "XZ"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "pierce": {
        "summary": "Coincide a sketch point with the crossing of a curve edge and the sketch plane",
        "fields": {**_SKETCH_TARGET, "geometry": {},
                   "point": {"default": 1},
                   "target": {"anyOf": [_d("feature"), _d("selector"), _d("selector_reference")],
                              "description": "Feature owning the crossing edge, or an edge selector"},
                   "subelement": {}},
        "required": ["sketch", "geometry", "target"],
        "x-required-when": {"subelement": "target is a feature ID (a selector target supplies it)"},
        "constraints": ["The curve crosses the sketch plane at exactly one point (ambiguous_intersection)",
                        "Same Body, upstream of the sketch"],
        "examples": [{"op": "pierce", "sketch": "Target", "geometry": 0, "point": 1, "target": "Crossing",
                      "subelement": "Edge1"}],
        "x-example-fixture": "plate", "doc": DOC_HISTORICAL},
    "project_geometry": {
        "summary": "Project associated edges into a sketch as defining or reference geometry",
        "fields": {**_SKETCH_TARGET, "references": {}, "defining": {"default": True}},
        "required": ["sketch", "references"], "checked_by_handler": {"references": "invalid_argument"},
        "examples": [{"op": "project_geometry", "sketch": "Target",
                      "references": [{"kind": "closest", "point": [60, 20, 0],
                                      "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}]}],
        "x-example-fixture": "plate", "doc": DOC_STUDIO},

    # Extrusions and edits ----------------------------------------------------
    "pad": {
        "summary": "Extrude (native Pad, or a studio result with operation/merge_scope)",
        "fields": {"id": {"x-default-id": "Pad", "description": "Default Pad (legacy) or Extrude (studio)"},
                   "profile": {}, "face": {"description": "Planar face to extrude (studio path only)"},
                   "length": {},
                   "direction": _direction("extrudes along the normal (studio through_all: both ways)"),
                   "reversed": {"default": False, "description": "Legacy for direction (one release): true extrudes "
                                                                 "against the profile normal"},
                   "end_type": {"enum": Ref("extrusion_edit", "END_TYPES"), "default": "blind",
                                "x-default-when": {"absent": ["up_to_face"]},
                                "description": "through_all needs the studio path; ignored when up_to_face is given"},
                   "up_to_face": {"description": "Face that ends the extrusion; given, it selects the up-to-face end"},
                   "operation": {"default": "new", "x-default-when": {"present_any": ["merge_scope"]},
                                 "description": "Omitted with merge_scope also omitted: the legacy native Pad path"},
                   "merge_scope": {"default": "auto", "x-default-when": {"present_any": ["operation"]}},
                   "refine": {"default": True, "x-default-when": {"present_any": ["operation", "merge_scope"]},
                              "description": "Studio path only; a legacy Pad rejects refine"},
                   "name": {"description": "Label of a new part (studio operation new)"},
                   "body": {}, **_SOURCE},
        "required": [], "requires_one_of": [["profile", "face"]],
        "x-required-when": {"length": "blind end (end_type blind, the default) without up_to_face",
                            "up_to_face": "end_type up_to_face"},
        "constraints": ["profile and face are mutually exclusive",
                        "up_to_face selects the up-to-face end; end_type is then ignored",
                        "face, end_type through_all and refine need operation or merge_scope (the studio path)",
                        "direction and reversed are mutually exclusive (invalid_argument)",
                        "A legacy Pad must add material (empty_add, with hint, direction_used and try_direction) and "
                        "leave one valid solid in its Body",
                        "A studio Add whose tool touches no part of an auto merge_scope rejects with empty_merge_scope "
                        "(hint, try_direction, tool_volume_mm3)"],
        "examples": [{"op": "pad", "id": "Boss", "profile": "BossProfile", "length": 10},
                     {"op": "pad", "id": "BossExtrude", "profile": "BossProfile", "length": 15, "operation": "add"},
                     {"op": "pad", "id": "BossPart", "profile": "BossProfile", "length": 15, "merge_scope": ["Body"]}],
        "x-example-fixtures": ["plate", "studio", "studio"],
        "x-example-fixture": "plate", "doc": DOC_STUDIO},
    "pocket": {
        "summary": "Remove (native Pocket, or a studio result with operation/merge_scope)",
        "fields": {"id": {"x-default-id": "Pocket", "description": "Default Pocket (legacy) or Remove (studio)"},
                   "profile": {}, "face": {"description": "Planar face to cut from (studio path only)"},
                   "length": {"description": "Blind depth (with through_all false)"},
                   "through_all": {"type": "boolean", "default": True, "x-default-when": {"absent": ["up_to_face"]}},
                   "direction": _direction("cuts against the normal; a legacy Pocket then tries along it when "
                                           "that removes nothing (an explicit direction is kept); a studio through-all "
                                           "cut runs both ways"),
                   "reversed": {"description": "Legacy for direction (one release), with opposite meanings: a legacy "
                                               "Pocket's true cuts along the profile normal, a studio Remove's false "
                                               "does. Omitted: cut against the sketch normal; a legacy Pocket then "
                                               "tries the other direction when that removes nothing. An explicit "
                                               "value is kept"},
                   "end_type": {"enum": Ref("extrusion_edit", "END_TYPES"),
                                "description": "up_to_face, or through_all; through_all:true (the default) also cuts through all"},
                   "up_to_face": {"description": "Face that ends the cut; given, it selects the up-to-face end"},
                   "operation": {"default": "remove", "x-default-when": {"present_any": ["merge_scope"]},
                                 "description": "Omitted with merge_scope also omitted: the legacy native Pocket path"},
                   "merge_scope": {"default": "auto", "x-default-when": {"present_any": ["operation"]}},
                   "refine": {"default": True, "x-default-when": {"present_any": ["operation", "merge_scope"]},
                              "description": "Studio path only; a legacy Pocket rejects refine"},
                   "name": {"description": "Label of a new part (studio operation new)"},
                   "body": {}, **_SOURCE},
        "required": [], "requires_one_of": [["profile", "face"]],
        "x-required-when": {"length": "blind cut (through_all false, end_type not through_all, no up_to_face)",
                            "up_to_face": "end_type up_to_face"},
        "constraints": ["profile and face are mutually exclusive",
                        "up_to_face selects the up-to-face end; end_type and through_all are then ignored",
                        "face and refine need operation or merge_scope",
                        "direction and reversed are mutually exclusive (invalid_argument)",
                        "Must remove material (empty_cut, with hint, direction_used and try_direction) and keep one "
                        "connected solid",
                        "A studio Remove whose tool touches no part of an auto merge_scope rejects with "
                        "empty_merge_scope (hint, try_direction, tool_volume_mm3)"],
        "examples": [{"op": "pocket", "id": "Recess", "profile": "BossProfile", "through_all": False, "length": 3},
                     {"op": "pocket", "id": "BossCut", "profile": "BossProfile", "operation": "remove"},
                     {"op": "pocket", "id": "BossHole", "profile": "BossProfile", "merge_scope": ["Body"]}],
        "x-example-fixtures": ["plate", "studio", "studio"],
        "x-example-fixture": "plate", "doc": DOC_STUDIO},
    "edit_extrusion": {
        "summary": "Edit an Extrude/Remove in place: depth, depth formula, direction, end condition",
        "fields": {"feature": {"description": "Pad, Pocket or studio Extrude/Remove"},
                   "length": {}, "expression": {"description": "Depth formula, or null to clear it"},
                   "reversed": {}, "end_type": {"enum": Ref("extrusion_edit", "END_TYPES"),
                                                "description": "Omitted: the current end condition"},
                   "body": {}},
        "required": ["feature"], "checked_by_handler": {"feature": "missing_reference"},
        "constraints": ["length and a non-null expression are mutually exclusive",
                        "Depth applies only to a blind end", "A formula-driven depth rejects length (expression_driven)"],
        "examples": [{"op": "edit_extrusion", "feature": "Pad", "length": 8}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "set_parameter": {
        "summary": "Set a driving dimension or numeric feature parameter",
        "fields": {"feature": {}, "parameter": {},
                   "value": {"x-unit-from": "parameter",
                             "description": "New value in the parameter's unit (inspect parameters[].unit): mm or rad"},
                   "body": {}},
        "required": ["feature", "parameter", "value"],
        "constraints": ["Expression-driven and reference parameters reject numeric replacement (expression_driven)"],
        "examples": [{"op": "set_parameter", "feature": "Pad", "parameter": "Length", "value": 8}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "set_expression": {
        "summary": "Set or clear a native dimensional formula",
        "fields": {"feature": {}, "parameter": {},
                   "expression": {"default": None, "description": "Formula; null or omitted clears it"},
                   "body": {}},
        "required": ["feature", "parameter"],
        "examples": [{"op": "set_expression", "feature": "Pad", "parameter": "Length",
                      "expression": "PlateProfile.Constraints.Width / 10"}],
        "x-example-fixture": "plate", "doc": DOC_HISTORICAL},
    "duplicate_feature": {
        "summary": "Copy a sketch, Pad or Pocket in its Body, keeping links",
        "fields": {"feature": {}, "fingerprint": {}, "body": {}},
        "required": ["feature"],
        "examples": [{"op": "duplicate_feature", "feature": "PlateProfile"}],
        "x-example-fixture": "plate", "doc": DOC_HISTORICAL},
    "rename_feature": {
        "summary": "Change a feature's, Body's or assembly object's label, keeping its ID",
        "fields": {"feature": {}, "name": {"minLength": 1, "maxLength": 120, "description": "New label, 1 to 120 printable characters"},
                   "body": {}},
        "required": ["feature", "name"],
        "examples": [{"op": "rename_feature", "feature": "Pad", "name": "Plate body"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "delete_feature": {
        "summary": "Delete one feature; dependents need cascade",
        "fields": {"feature": {}, "cascade": {"default": False}, "body": {}},
        "required": ["feature"], "examples": [{"op": "delete_feature", "feature": "Pocket"}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "delete_features": {
        "summary": "Delete a validated set of features in one transaction",
        "fields": {"features": {}, "cascade": {"default": False}, "body": {}},
        "required": ["features"], "checked_by_handler": {"features": "invalid_argument"},
        "constraints": ["Unselected dependents reject with dependent_features unless cascade"],
        "examples": [{"op": "delete_features", "features": ["Pocket", "HoleProfile"]}],
        "x-example-fixture": "plate", "doc": DOC_30},
    "repair_orphan_helpers": {
        "summary": "Remove unconsumed leftover helper groups in one undoable transaction",
        "fields": {"owners": {"description": "Groups to repair; omitted repairs every repairable group"}, "body": {}},
        "required": [], "constraints": ["Nothing to repair rejects with no_orphans"],
        "examples": [], "x-example-fixture": "plate", "doc": DOC_30},
    "rebuild": {
        "summary": "Touch native modeling features and recompute",
        "fields": {}, "required": [], "examples": [{"op": "rebuild"}], "x-example-fixture": "plate", "doc": DOC_30},

    # Part Studio -------------------------------------------------------------
    "revolve": {
        "summary": "Revolve a sketch profile into a studio result",
        "fields": {**_STUDIO_ID, "profile": {},
                   "axis": {"anyOf": [_d("axis"), _d("reference")], "default": _DEFAULT_AXIS,
                            "description": "World {origin, direction}, or one straight edge reference"},
                   "angle": {"$ref": "#/$defs/positive_angle", "default": "360 deg"},
                   **_RESULT, "body": {}, **_SOURCE},
        "required": ["profile"],
        "examples": [{"op": "revolve", "id": "Ring", "profile": "RingProfile", "angle": "180 deg"}],
        "x-example-fixture": "studio", "doc": DOC_STUDIO},
    "sweep": {
        "summary": "Sweep a sketch profile along a path into a studio result",
        "fields": {**_STUDIO_ID, "profile": {},
                   "path": {"anyOf": [_d("feature"), _d("reference")],
                            "description": "Native curve feature (sketch, create_helix ID) or one edge reference"},
                   "frenet": {"default": False}, **_RESULT, "body": {}, **_SOURCE},
        "required": ["profile", "path"], "checked_by_handler": {"path": "missing_reference"},
        "examples": [{"op": "sweep", "id": "Rail", "profile": "SweepProfile", "path": "PathSketch"}],
        "x-example-fixture": "studio", "doc": DOC_STUDIO},
    "loft": {
        "summary": "Loft through ordered sketch sections into a studio result",
        "fields": {**_STUDIO_ID, "sections": {}, "ruled": {"default": False}, "closed": {"default": False},
                   **_RESULT, "body": {}, **_SOURCE},
        "required": ["sections"], "checked_by_handler": {"sections": "invalid_argument"},
        "examples": [{"op": "loft", "id": "Taper", "sections": ["LoftLower", "LoftUpper"]}],
        "x-example-fixture": "studio", "doc": DOC_STUDIO},
    "boolean_parts": {
        "summary": "Union, subtract or intersect independent parts",
        "fields": {**_STUDIO_ID, "name": _UNUSED_NAME,
                   "targets": {}, "tools": {},
                   "kind": {"enum": Ref("studio", "BOOLEAN_KINDS"), "default": "union"},
                   "keep_tools": {"default": False}, "body": {}, **_SOURCE},
        "required": ["targets", "tools"],
        "checked_by_handler": {"targets": "invalid_argument", "tools": "invalid_argument"},
        "constraints": ["targets and tools are disjoint"],
        "examples": [{"op": "boolean_parts", "id": "Joined", "targets": ["Body"], "tools": ["Tool"], "kind": "subtract"}],
        "x-example-fixture": "studio", "doc": DOC_STUDIO},
    "split_part": {
        "summary": "Split a part by a plane into two editable parts",
        "fields": {**_STUDIO_ID, "name": _UNUSED_NAME,
                   "part": {},
                   "plane": {"type": "object", "additionalProperties": False,
                             "properties": {"origin": _d("vector3"), "normal": _d("direction3")},
                             "description": "World {origin, normal}; omitted keys are [0,0,0] and [0,0,1]"},
                   "face": {"description": "Planar face reference"},
                   "sketch": {"description": "Sketch whose plane splits the part"},
                   "body": {}, **_SOURCE},
        "required": ["part"],
        "checked_by_handler": {"part": "missing_part", "plane": "invalid_argument", "face": "invalid_argument",
                               "sketch": "invalid_argument"},
        "constraints": ["Exactly one of plane, face or sketch"],
        "examples": [{"op": "split_part", "id": "Halves", "part": "Body", "plane": {"origin": [20, 0, 0], "normal": [1, 0, 0]}}],
        "x-example-fixture": "studio", "doc": DOC_STUDIO},
    "transform_part": {
        "summary": "Move, rotate or copy a part",
        "fields": {**_STUDIO_ID, "name": {"description": "Label of the result"}, "part": {},
                   "translation": {"default": [0, 0, 0]},
                   "rotation": {"type": "object", "additionalProperties": False,
                                "properties": {"axis": _d("direction3"), "angle": _d("angle")},
                                "default": {"axis": [0, 0, 1], "angle": 0}},
                   "coordinate_system": {"type": "object", "required": ["origin", "x", "y", "z"], "additionalProperties": False,
                                         "properties": {"origin": _d("vector3"), "x": _d("direction3"),
                                                        "y": _d("direction3"), "z": _d("direction3")},
                                         "description": "Proper orthonormal frame applied after translation/rotation"},
                   "copy": {"default": False}, "body": {}, **_SOURCE},
        "required": ["part"], "checked_by_handler": {"part": "missing_part"},
        "examples": [{"op": "transform_part", "id": "Moved", "part": "Tool", "translation": [0, 40, 0]}],
        "x-example-fixture": "studio", "doc": DOC_STUDIO},
    "delete_part": {
        "summary": "Consume a current part in history (undo restores it)",
        "fields": {**_STUDIO_ID, "name": _UNUSED_NAME,
                   "part": {}, "body": {}, **_SOURCE},
        "required": ["part"], "checked_by_handler": {"part": "missing_part"},
        "examples": [{"op": "delete_part", "id": "RemoveTool", "part": "Tool"}],
        "x-example-fixture": "studio", "doc": DOC_STUDIO},
    "linear_pattern_parts": {
        "summary": "Linear copies of parts, optionally combined with a merge scope",
        "fields": {**_PATTERN, "id": {"x-default-id": "StudioFeature"}, "count": {"default": 2},
                   "direction": {"default": [1, 0, 0]}, "spacing": {}},
        "required": ["parts", "spacing"],
        "checked_by_handler": {"parts": "invalid_argument", "spacing": "invalid_argument"},
        "examples": [{"op": "linear_pattern_parts", "id": "Row", "parts": ["Tool"], "direction": [0, 1, 0], "spacing": 40}],
        "x-example-fixture": "studio", "doc": DOC_PATTERNS},
    "circular_pattern_parts": {
        "summary": "Rotated copies of parts about an axis",
        "fields": {**_PATTERN, "id": {"x-default-id": "StudioFeature"}, "count": {"default": 2},
                   "axis": {"default": _DEFAULT_AXIS},
                   "angle": {"$ref": "#/$defs/positive_angle", "default": "360 deg",
                             "description": "Total angle; a full turn excludes the coincident last instance"}},
        "required": ["parts"], "checked_by_handler": {"parts": "invalid_argument"},
        "examples": [{"op": "circular_pattern_parts", "id": "Around", "parts": ["Tool"], "count": 3}],
        "x-example-fixture": "studio", "doc": DOC_PATTERNS},
    "mirror_parts": {
        "summary": "Mirrored copies of parts",
        "fields": {**_PATTERN, "id": {"x-default-id": "StudioFeature"},
                   "plane": {"$ref": "#/$defs/reference", "description": "One planar face or datum plane reference"},
                   "origin": {"default": [0, 0, 0], "x-default-when": {"absent": ["plane"]}},
                   "normal": {"default": [1, 0, 0], "x-default-when": {"absent": ["plane"]}}},
        "required": ["parts"], "checked_by_handler": {"parts": "invalid_argument"},
        "constraints": ["plane excludes origin and normal"],
        "examples": [{"op": "mirror_parts", "id": "Mirrored", "parts": ["Tool"], "origin": [0, 0, 0], "normal": [1, 0, 0]}],
        "x-example-fixture": "studio", "doc": DOC_PATTERNS},
    "rollback": {
        "summary": "Move the history rollback bar; later features are held",
        "fields": {"index": {"description": "Zero-based position between 0 and the feature count"}, "body": {}},
        "required": ["index"], "checked_by_handler": {"index": "invalid_argument"},
        "examples": [{"op": "rollback", "index": 1}], "x-example-fixture": "studio", "doc": DOC_STUDIO},
    "set_part_appearance": {
        "summary": "Part name, visibility and colour (visibility never removes a part from export)",
        "fields": {"part": {}, "name": {"minLength": 1, "maxLength": 120, "description": "Part name, 1 to 120 printable characters"},
                   "visible": {}, "color": {}, "body": {}},
        "required": ["part"], "checked_by_handler": {"part": "missing_part"},
        "examples": [{"op": "set_part_appearance", "part": "Tool", "color": [0.8, 0.2, 0.2]}],
        "x-example-fixture": "studio", "doc": DOC_STUDIO},

    # Reference consumers -------------------------------------------------------
    "fillet": {
        "summary": "Native fillet on edges of the current part",
        "fields": {"id": {"x-default-id": "Fillet"}, "part": {}, "edges": {}, "radius": {}, "body": {}, **_SOURCE},
        "required": ["edges", "radius"],
        "checked_by_handler": {"edges": "invalid_argument", "radius": "invalid_argument"},
        "constraints": ["An implausible kernel volume rejects with invalid_geometry"],
        "examples": [{"op": "fillet", "id": "EdgeRound", "edges": [_PLATE_EDGE], "radius": 1}],
        "x-example-fixture": "plate", "doc": DOC_MULTI},
    "chamfer": {
        "summary": "Native equal-distance chamfer on edges of the current part",
        "fields": {"id": {"x-default-id": "Chamfer"}, "part": {}, "edges": {}, "size": {}, "body": {}, **_SOURCE},
        "required": ["edges", "size"],
        "checked_by_handler": {"edges": "invalid_argument", "size": "invalid_argument"},
        "examples": [{"op": "chamfer", "id": "EdgeBevel", "edges": [_PLATE_EDGE], "size": 1}],
        "x-example-fixture": "plate", "doc": DOC_MULTI},
    "shell": {
        "summary": "Native thickness (shell) removing the selected faces",
        "fields": {"id": {"x-default-id": "Shell"}, "part": {}, "faces": {}, "thickness": {},
                   "reversed": {"default": False}, "body": {}, **_SOURCE},
        "required": ["faces", "thickness"],
        "checked_by_handler": {"faces": "invalid_argument", "thickness": "invalid_argument"},
        "examples": [{"op": "shell", "id": "Hollow", "faces": [_PLATE_TOP], "thickness": 1}],
        "x-example-fixture": "plate", "doc": DOC_STUDIO},
    "edit_dress_up": {
        "summary": "Change the edges, size or formula of an existing fillet or chamfer in place",
        "fields": {"feature": {"description": "Existing Fillet or Chamfer"}, "edges": {},
                   "radius": {"description": "Fillets only"}, "size": {"description": "Chamfers only"},
                   "expression": {"description": "Radius/size formula; null or \"\" clears it"}, "body": {}},
        "required": ["feature"], "checked_by_handler": {"feature": "missing_reference"},
        "constraints": ["A value and a non-empty formula are mutually exclusive"],
        "examples": [{"op": "edit_dress_up", "feature": "EdgeRound", "radius": 2}],
        "x-example-setup": [{"op": "fillet", "id": "EdgeRound", "edges": [_PLATE_EDGE], "radius": 1}],
        "x-example-fixture": "plate", "doc": DOC_MULTI},
    "hole": {
        "summary": "Native PartDesign Hole at a sketch's circles and points",
        "fields": {"id": {"x-default-id": "Hole, Hole001, ...", "description": "Default: the first free Hole name"},
                   "part": {}, "sketch": {"description": "Sketch whose non-construction circles and points are centres"},
                   "diameter": {}, "depth": {"description": "Full-diameter depth to the start of the drill point"},
                   "end_type": {"enum": Ref("hole_tools", "END_TYPES"), "default": "blind"},
                   "point_angle": {"anyOf": [_d("angle"), {"const": "flat"}], "default": "118 deg",
                                   "x-default-when": {"not_equal": {"end_type": "through_all"}},
                                   "description": "Included drill-point angle, 1 to 179 deg; 0 or \"flat\" for a flat bottom"},
                   "direction": _direction("drills against the normal"),
                   "reversed": {"default": False, "description": "Legacy for direction (one release): true drills along "
                                                                 "the sketch normal instead of against it"},
                   "counterbore": {"type": "object", "required": ["diameter", "depth"], "additionalProperties": False,
                                   "properties": {"diameter": _d("positive_length"), "depth": _d("positive_length")}},
                   "countersink": {"type": "object", "required": ["diameter"], "additionalProperties": False,
                                   "properties": {"diameter": _d("positive_length"),
                                                  "angle": {"$ref": "#/$defs/angle", "description": "Included angle, default \"90 deg\""}}},
                   "body": {}, **_SOURCE},
        "required": ["sketch", "diameter"],
        "checked_by_handler": {"sketch": "missing_reference", "diameter": "invalid_argument"},
        "x-cut-args": Ref("hole_tools", "CUT_ARGS", "key_sets"),
        "x-required-when": {"depth": "end_type blind (the default)"},
        "constraints": ["through_all takes no depth or point_angle", "At most one of counterbore or countersink",
                        "direction and reversed are mutually exclusive (invalid_argument)",
                        "Must remove material (empty_cut, with hint, direction_used and try_direction)",
                        "A depth beyond the native through-all length rejects with maximum_depth"],
        "examples": [{"op": "hole", "sketch": "BossProfile", "diameter": 3, "depth": 4, "reversed": True}],
        "x-example-fixture": "plate", "doc": DOC_STUDIO},
    "create_plane": {
        "summary": "Native datum plane: offset, point-normal, three-point or line-angle",
        "fields": {"id": {"x-default-id": "Plane"}, "name": {}, "body": {},
                   "offset": {"default": 0},
                   "base_plane": {"default": "XY",
                                  "x-default-when": {"absent": ["support", "origin", "normal", "x_direction", "points",
                                                                "axis", "reference_normal", "angle"]}},
                   "support": {"description": "Offset mode: datum plane, planar face reference or face selector"},
                   "origin": {"description": "Point-normal mode"}, "normal": {"description": "Point-normal mode"},
                   "x_direction": {"description": "Point-normal mode; default world +X projected into the plane"},
                   "points": {"type": "array", "items": _d("vector3"), "minItems": 3, "maxItems": 3,
                              "description": "Three-point mode: origin, a point on +X, a point on the +Y side"},
                   "axis": {"anyOf": [_d("axis"), _d("reference")], "description": "Line-angle mode: line or straight edge"},
                   "reference_normal": {"description": "Line-angle mode: plane normal at angle 0"},
                   "angle": {"default": 0, "x-default-when": {"present_any": ["axis", "reference_normal"]},
                             "description": "Line-angle mode: signed turn about the line"},
                   **_SOURCE},
        "required": [],
        "x-modes": Ref("modeling_geometry", "PLANE_MODES", "keys"),
        "x-required-when": {"origin": "point-normal mode", "normal": "point-normal mode", "points": "three-point mode",
                            "axis": "line-angle mode", "reference_normal": "line-angle mode"},
        "constraints": ["Fields of two modes reject with invalid_argument (modes)", "support excludes base_plane"],
        "examples": [{"op": "create_plane", "id": "MidPlane", "origin": [0, 20, 0], "normal": [0, 1, 0]},
                     {"op": "create_plane", "id": "TopPlane", "base_plane": "XY", "offset": 6},
                     {"op": "create_plane", "id": "Slope", "points": [[0, 0, 6], [60, 0, 6], [0, 40, 10]]},
                     {"op": "create_plane", "id": "Hinged", "axis": {"origin": [0, 0, 6], "direction": [0, 1, 0]},
                      "reference_normal": [0, 0, 1], "angle": "30 deg"}],
        "x-example-fixture": "plate", "doc": DOC_PLANES},
    "extrude_face": {
        "summary": "Extrude one planar face into a studio result",
        "fields": {"id": {"x-default-id": "ExtrudeFace"}, "name": {}, "face": {}, "length": {},
                   "reversed": {"description": "Default false, or true for operation remove"},
                   "operation": {"default": "add"}, "merge_scope": {"default": "auto"}, "refine": {"default": True},
                   "body": {}, **_SOURCE},
        "required": ["face", "length"], "checked_by_handler": {"length": "invalid_argument"},
        "examples": [{"op": "extrude_face", "id": "Raise", "face": _PLATE_TOP, "length": 2}],
        "x-example-fixture": "plate", "doc": DOC_STUDIO},
    "move_face": {
        "summary": "Offset parallel planar faces of a part",
        "fields": {"id": {"x-default-id": "MoveFace"}, "name": {}, "part": {}, "faces": {}, "distance": {},
                   "body": {}, **_SOURCE},
        "required": ["faces", "distance"],
        "checked_by_handler": {"faces": "invalid_argument", "distance": "invalid_argument"},
        "constraints": ["Walls must be perpendicular planes or cylinders parallel to the face normal"],
        "examples": [{"op": "move_face", "id": "Thicken", "faces": [_PLATE_TOP], "distance": 1}],
        "x-example-fixture": "plate", "doc": DOC_STUDIO},
    "create_helix": {
        "summary": "Native top-level helix for sweep paths",
        "fields": {"id": {"x-default-id": "Helix"}, "name": {}, "pitch": {}, "height": {}, "radius": {},
                   "axis": {"default": _DEFAULT_AXIS},
                   "x_direction": {"description": "Start direction; default world +X projected perpendicular to the axis"},
                   "start_angle": {"default": 0}, "handedness": {"default": "right"},
                   "segment_length": {"default": 1}, **_SOURCE},
        "required": ["pitch", "height", "radius"],
        "checked_by_handler": {"pitch": "invalid_argument", "height": "invalid_argument", "radius": "invalid_argument"},
        "constraints": ["At most 1000 turns and 1000 edges", "No body: Part curves stay outside Bodies"],
        "examples": [{"op": "create_helix", "id": "Coil", "pitch": 5, "height": 20, "radius": 10}],
        "x-example-fixture": "plate", "doc": DOC_31},

    # Assembly --------------------------------------------------------------
    "create_assembly": {
        "summary": "Create the document's native assembly and joint group",
        "fields": {"id": {"$ref": "#/$defs/assembly_id", "x-default-id": "Assembly"},
                   "name": {"maxLength": 200, "default": "Assembly"},
                   "folder": {**_FOLDER, "description": "An empty instance-list folder path to create with the assembly"}},
        "required": [], "constraints": ["One assembly per document"],
        "examples": [{"op": "create_assembly", "id": "Assembly", "name": "Plate assembly"}],
        "x-example-fixture": "plate", "doc": DOC_ASSEMBLY},
    "insert_assembly_part": {
        "summary": "Embed a source solid snapshot and add one occurrence (the first is grounded)",
        "fields": {"assembly": {}, "path": {"description": "Absolute FCStd or STEP source", "x-suffixes": [".FCStd", ".step", ".stp"]},
                   "source_id": {"type": "string", "description": "Body or solid ID from assembly_candidates"},
                   "id": {"$ref": "#/$defs/assembly_id", "x-default-id": "Instance"},
                   "name": {"maxLength": 200, "description": "Label; defaults to the source label"},
                   "folder": _FOLDER},
        "required": ["path", "source_id"],
        "checked_by_handler": {"path": "invalid_assembly_source", "source_id": "missing_assembly_source_part"},
        "examples": [{"op": "insert_assembly_part", "path": "<plate_file>", "source_id": "Body", "id": "Extra"}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY},
    "refresh_assembly_part": {
        "summary": "Refresh an occurrence from a saved source without replacing its identity or placement",
        "fields": {"assembly": {}, "instance": {},
                   "path": {"description": "Saved FCStd/STEP source; omitted uses the recorded source path", "x-suffixes": [".FCStd", ".step", ".stp"]},
                   "source_id": {"type": "string", "description": "Saved native source ID; omitted uses the recorded source object"},
                   "shared": {"enum": ["instance", "all"], "description": "Required when multiple occurrences share the snapshot: copy-on-write for one, or refresh every user"},
                   "folder": {**_FOLDER, "description": "Also move the refreshed occurrence into this folder path"}},
        "required": ["instance"], "checked_by_handler": {"instance": "missing_assembly_instance"},
        "constraints": ["Native transaction validates before commit and rolls back on failure",
                        "Preserves occurrence identity, appearance, placement and grounding; changed joint subelements or connector frames reject",
                        "Changing saved source placement does not move existing occurrences"],
        "examples": [{"op": "refresh_assembly_part", "instance": "Free", "shared": "instance"}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY},
    "ground_assembly_instance": {
        "summary": "Make one occurrence the grounded reference and solve",
        "fields": {"assembly": {}, "instance": {}},
        "required": ["instance"], "checked_by_handler": {"instance": "missing_assembly_instance"},
        "examples": [{"op": "ground_assembly_instance", "instance": "Free"}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY},
    "create_assembly_joint": {
        "summary": "Native joint between two occurrences, then solve",
        "fields": {"assembly": {}, "joint_type": {}, "first": {}, "second": {},
                   "id": {"$ref": "#/$defs/assembly_id", "x-default-id": "FixedJoint, RevoluteJoint or SliderJoint"},
                   "name": {"maxLength": 200, "description": "Label; default \"<Type> joint\""}},
        "required": ["joint_type", "first", "second"],
        "checked_by_handler": {"joint_type": "invalid_assembly_joint_type", "first": "invalid_assembly_reference",
                               "second": "invalid_assembly_reference"},
        "examples": [{"op": "create_assembly_joint", "id": "FreeFix", "joint_type": "fixed",
                      "first": {"instance": "Base", "subelement": ""}, "second": {"instance": "Free", "subelement": ""}}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY},
    "edit_assembly_joint": {
        "summary": "Change a joint's references, type or label and solve",
        "fields": {"assembly": {}, "joint": {}, "joint_type": {"description": "Omitted: unchanged"},
                   "first": {"description": "Omitted: unchanged"}, "second": {"description": "Omitted: unchanged"},
                   "name": {"maxLength": 200, "description": "Omitted: unchanged"}},
        "required": ["joint"], "checked_by_handler": {"joint": "missing_assembly_joint"},
        "examples": [{"op": "edit_assembly_joint", "joint": "Hinge", "name": "Main hinge"}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY},
    "move_assembly_joint": {
        "summary": "Set a revolute or slider joint coordinate and solve",
        "fields": {"assembly": {}, "joint": {},
                   "value": {"anyOf": [{"type": "number"}, {"type": "string"}],
                             "x-unit-from": {"revolute": "deg", "slider": "mm"}, "x-max-abs": 1e7,
                             "description": "Revolute degrees (unlike other angles) or slider millimetres; a number "
                                            "or a quantity string"}},
        "required": ["joint", "value"],
        "checked_by_handler": {"joint": "missing_assembly_joint", "value": "invalid_assembly_motion"},
        "constraints": ["Fixed joints have no motion (fixed_joint)"],
        "examples": [{"op": "move_assembly_joint", "joint": "Hinge", "value": 30}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY},
    "move_assembly_instance": {
        "summary": "Place a free occurrence and solve",
        "fields": {"assembly": {}, "instance": {},
                   "position_mm": {"type": "array", "minItems": 3, "maxItems": 3, "x-unit": "mm",
                                   "items": {**_QUANTITY, "x-unit": "mm", "x-max-abs": 1e7},
                                   "description": "Assembly-frame [x, y, z] in millimetres (numbers or length quantity "
                                                  "strings, each within 1e7 mm)"},
                   "rotation_xyzw": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
                                     "description": "Nonzero quaternion; omitted keeps the current rotation"}},
        "required": ["instance", "position_mm"],
        "checked_by_handler": {"instance": "missing_assembly_instance", "position_mm": "invalid_assembly_motion"},
        "constraints": ["Grounded or jointed occurrences move through joints (assembly_motion_locked)"],
        "examples": [{"op": "move_assembly_instance", "instance": "Free", "position_mm": [100, 0, 0]}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY},
    "delete_assembly_object": {
        "summary": "Remove a joint or occurrence; dependent joints need cascade",
        "fields": {"assembly": {}, "feature": {"description": "Joint or occurrence ID"}, "cascade": {"default": False}},
        "required": ["feature"], "checked_by_handler": {"feature": "unsupported_assembly_delete"},
        "examples": [{"op": "delete_assembly_object", "feature": "Hinge"}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY},
    "set_assembly_folders": {
        "summary": "Replace the instance-list folder tree (presentation metadata only)",
        "fields": {"assembly": {},
                   "folders": {"type": "array", "maxItems": 500,
                               "items": {"anyOf": [{"type": "object"}, {"type": "string"}]},
                               "description": "Folder tree [{name, children:[...]}]; a string is a shorthand path "
                                              "(\"Fasteners/M3\"). Names are non-empty, without '/', distinct among siblings"},
                   "membership": {"type": "object",
                                  "description": "Instance id → folder path (null = root). Omitted keeps current "
                                                 "memberships whose folder still exists"}},
        "required": ["folders"], "checked_by_handler": {"folders": "invalid_assembly_folders"},
        "constraints": ["Stored as JSON on the assembly (KurtShapeInstanceFolders); solver, export and occurrence order are unchanged",
                        "One undoable transaction; instances not in membership show at the root"],
        "examples": [{"op": "set_assembly_folders", "folders": [{"name": "Fasteners", "children": [{"name": "M3", "children": []}]},
                                                                 "Frame"], "membership": {"Free": "Fasteners/M3"}}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY_FOLDERS},
    "move_assembly_instances": {
        "summary": "Move occurrences into an instance-list folder (created when missing) or back to the root",
        "fields": {"assembly": {},
                   "instances": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string"},
                                 "description": "Occurrence ids"},
                   "folder": {**_FOLDER, "description": "Folder path such as \"Fasteners/M3\"; null moves to the root"}},
        "required": ["instances"], "checked_by_handler": {"instances": "missing_assembly_instance"},
        "constraints": ["Presentation metadata only; revision-checked and undoable like every assembly mutation"],
        "examples": [{"op": "move_assembly_instances", "instances": ["Free"], "folder": "Fasteners/M3"}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY_FOLDERS},
    "solve_assembly": {
        "summary": "Explicit solve of the current assembly intent",
        "fields": {"assembly": {}}, "required": [], "examples": [{"op": "solve_assembly"}],
        "x-example-fixture": "assembly", "doc": DOC_ASSEMBLY},
}

# Example fixtures (x-example-fixture). Each is built by the recipe requests
# (envelope omitted) plus the stated native steps; <plate_file> is the saved
# plate fixture. Examples of an op run on a fresh copy of its fixture, after
# its x-example-setup requests.
EXAMPLE_FIXTURES = {
    "none": {"description": "No document is needed; nothing is open"},
    "plate": {
        "description": "Legacy single-Body plate: a 60 x 40 x 6 mm Pad with a through Pocket of 8 mm diameter, "
                       "plus unconsumed sketches BossProfile (6 mm circle at 10, 10 on XY), Crossing (a line on XZ "
                       "crossing the XY plane at x 2) and Target (XY, holding one free native point at 4, 0 as "
                       "geometry 0, added outside typed operations because no typed sketch-point operation exists)",
        "recipe": [{"op": "new", "name": "Plate fixture"},
                   {"op": "sketch_rectangle", "id": "PlateProfile", "width": 60, "height": 40},
                   {"op": "pad", "id": "Pad", "profile": "PlateProfile", "length": 6},
                   {"op": "sketch_circle", "id": "HoleProfile", "x": 30, "y": 20, "diameter": 8, "center_on": "PlateProfile"},
                   {"op": "pocket", "id": "Pocket", "profile": "HoleProfile"},
                   {"op": "sketch_circle", "id": "BossProfile", "x": 10, "y": 10, "diameter": 6},
                   {"op": "create_sketch", "id": "Crossing", "plane": "XZ"},
                   {"op": "add_line", "sketch": "Crossing", "x1": 2, "y1": -5, "x2": 2, "y2": 5},
                   {"op": "create_sketch", "id": "Target"}],
        "native_steps": ["Target.addGeometry(Part.Point(Vector(4, 0, 0)))"]},
    "studio": {
        "description": "Part Studio with parts Body (40 x 30 x 10 block) and Tool (10 mm cube at x 35..45, y 10..20, "
                       "overlapping it), plus unconsumed sketches BossProfile, RingProfile (XZ rectangle at x 60), "
                       "PathSketch (line along +X at y -20), SweepProfile (YZ circle at the path start), LoftLower "
                       "and LoftUpper (on datum plane LoftPlane, 20 mm above XY)",
        "recipe": [{"op": "new", "name": "Studio fixture"},
                   {"op": "sketch_rectangle", "id": "BaseProfile", "width": 40, "height": 30},
                   {"op": "pad", "id": "BaseExtrude", "profile": "BaseProfile", "length": 10, "operation": "new"},
                   {"op": "create_body", "id": "Tool", "name": "Tool"},
                   {"op": "sketch_rectangle", "id": "ToolProfile", "body": "Tool", "x": 35, "y": 10, "width": 10, "height": 10},
                   {"op": "pad", "id": "ToolExtrude", "profile": "ToolProfile", "body": "Tool", "length": 10, "operation": "new"},
                   {"op": "sketch_circle", "id": "BossProfile", "body": "Body", "x": 20, "y": 15, "diameter": 8},
                   {"op": "sketch_rectangle", "id": "RingProfile", "body": "Body", "plane": "XZ", "x": 60, "y": 0,
                    "width": 4, "height": 5},
                   {"op": "create_sketch", "id": "PathSketch", "body": "Body"},
                   {"op": "add_line", "sketch": "PathSketch", "x1": 0, "y1": -20, "x2": 30, "y2": -20},
                   {"op": "sketch_circle", "id": "SweepProfile", "body": "Body", "plane": "YZ", "x": -20, "y": 0, "diameter": 4},
                   {"op": "create_plane", "id": "LoftPlane", "body": "Body", "base_plane": "XY", "offset": 20},
                   {"op": "sketch_circle", "id": "LoftLower", "body": "Body", "x": 0, "y": 60, "diameter": 10},
                   {"op": "sketch_circle", "id": "LoftUpper", "support": {"feature": "LoftPlane"}, "x": 0, "y": 60, "diameter": 6}]},
    "assembly": {
        "description": "Assembly of three occurrences of the plate fixture's Body: Base (grounded), Rotor (revolute "
                       "joint Hinge to Base) and Free (unconstrained)",
        "recipe": [{"op": "new", "name": "Assembly fixture"},
                   {"op": "create_assembly", "id": "Assembly", "name": "Fixture assembly"},
                   {"op": "insert_assembly_part", "path": "<plate_file>", "source_id": "Body", "id": "Base"},
                   {"op": "insert_assembly_part", "path": "<plate_file>", "source_id": "Body", "id": "Rotor"},
                   {"op": "insert_assembly_part", "path": "<plate_file>", "source_id": "Body", "id": "Free"},
                   {"op": "create_assembly_joint", "id": "Hinge", "joint_type": "revolute",
                    "first": {"instance": "Base", "subelement": ""}, "second": {"instance": "Rotor", "subelement": ""}}]},
}
EXAMPLE_PLACEHOLDERS = {
    "<document_id>": "document_id of the fixture document",
    "<revision>": "its current revision",
    "<project>": "an empty folder inside a granted project folder",
    "<plate_file>": "the plate fixture saved as an FCStd file that is not open",
    "<step_file>": "the plate fixture exported as STEP",
    "<recovery_manifest>": "a forced checkpoint manifest of the plate fixture in the session's project-recovery folder",
}

# Slice A/B U6 (B1): every mutating operation (model, assembly, create, save/export/adopt, history,
# batch) takes ``detail`` for the shape of its response. The reads keep their own argument sets
# (inspect and list_documents own a ``detail``), the view operations and close_document return no
# inspection. The exclusion list mirrors Controller.READ_OPS, VIEW_OPS and LIFECYCLE_OPS; it is pinned
# by CompactResponseTests.test_schema_offers_detail_on_every_mutation_and_batch.
RESPONSE_DETAIL = {"enum": ["full", "compact"],
                   "description": "Shape of the response: compact gives the status header (the list_documents row) "
                                  "with created_feature, batch_report and the request's reports (about 1 KB); full "
                                  "gives the full inspection with operations and last_failed_attempt; omitted gives "
                                  "the full inspection without those two blocks"}
NO_RESPONSE_DETAIL = frozenset({"inspect", "list_documents", "capabilities", "request_status", "preview", "diagnostics",
                                "assembly_candidates", "resolve_selector", "check_geometry", "orphan_helpers",
                                "operation_schema", "list_parameters", "render_view", "set_view", "close_document",
                                "part_inventory", "assembly_instance_source", "measure"})
for _op, _entry in OPERATIONS.items():
    if _op not in NO_RESPONSE_DETAIL:
        _entry["fields"].setdefault("detail", RESPONSE_DETAIL)

# Import-time tables for the generic pre-check: no build needed.
REQUIRED = {op: tuple(field for field in entry["required"] if field not in entry.get("checked_by_handler", {}))
            for op, entry in OPERATIONS.items()}
ONE_OF = {op: tuple(tuple(group) for group in entry.get("requires_one_of", ())) for op, entry in OPERATIONS.items()}


def missing_arguments(op, request):
    """Generic-required fields absent or null in ``request``; O(required), never builds.

    Returns ``(absent, groups)``: absent unconditional fields in declaration
    order, and each ``requires_one_of`` group of which no field is given.
    """
    absent = [field for field in REQUIRED.get(op, ()) if request.get(field) is None]
    groups = [list(group) for group in ONE_OF.get(op, ()) if all(request.get(field) is None for field in group)]
    return absent, groups


def arg_names(op):
    """Argument names of ``op`` (envelope excluded); ARGS for operations added in contract 3.2."""
    return frozenset(OPERATIONS[op]["fields"])


# ---------------------------------------------------------------------------
# Rendering

_TYPE_KEYS = ("type", "$ref", "anyOf", "oneOf", "allOf", "const")
_BUILT = {}


def _render(value):
    """Deep copy with every Ref resolved; a Ref under key K adds x-K-source."""
    if isinstance(value, Ref):
        return resolve(value)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result[key] = _render(item)
            if isinstance(item, Ref):
                result["x-" + key.removeprefix("x-") + "-source"] = item.source
        return result
    if isinstance(value, (list, tuple)):
        return [_render(item) for item in value]
    return copy.deepcopy(value)


def field_schema(op, name):
    """The merged (unrendered) schema of one argument of ``op``."""
    override = OPERATIONS[op]["fields"][name]
    base = FIELDS.get(name, {})
    if any(key in override for key in _TYPE_KEYS):
        base = {key: value for key, value in base.items() if key not in _TYPE_KEYS and key != "enum"}
    return {**base, **override}


def _classes(controller_cls):
    def members(name, fallback=frozenset()):
        return frozenset(getattr(controller_cls, name, fallback))
    try:
        batchable = frozenset(getattr(_module("batch"), "OPS", ()))
    except ImportError:
        batchable = frozenset()
    return {"ops": members("OPS"), "read": members("READ_OPS"), "create": members("CREATE_OPS"),
            "model": members("MODEL_OPS"), "assembly": members("ASSEMBLY_OPS"), "view": members("VIEW_OPS"),
            "lifecycle": members("LIFECYCLE_OPS"), "documentless": members("DOCUMENTLESS_OPS", DOCUMENTLESS_OPS),
            "batch": batchable}


def _kind(op, classes):
    if op in classes["read"]:
        return "read"
    if op in classes["view"]:
        return "view"
    if op == "batch":
        return "batch"
    if op in classes["create"]:
        return "create"
    if op in classes["assembly"]:
        return "assembly"
    if op in classes["model"]:
        return "modeling"
    if op in FILE_LIFECYCLE_OPS or op in classes["lifecycle"]:
        return "lifecycle"
    if op in HISTORY_OPS:
        return "history"
    return "other"


def envelope_requirements(op, classes):
    """(document_id required, expected_revision required, request_id tracked) for ``op``.

    Every non-read, non-create operation needs the current revision; view
    operations (render_view, F2) and preview (a read, slice A/B U6) take it
    optionally and check it when given.
    """
    document = op not in classes["create"] and op not in classes["documentless"]
    revision = op not in classes["read"] | classes["create"] | classes["view"]
    tracked = op not in classes["read"]
    return document, revision, tracked


def _envelope(op, classes):
    document, revision, tracked = envelope_requirements(op, classes)
    properties = {
        "op": {"const": op},
        "document_id": {"type": "string", "description": "Document UUID from inspect or list_documents"},
        "expected_revision": {"type": "string", "x-missing-code": "stale_revision",
                              "description": "Current revision; a stale or missing value rejects with stale_revision"},
        "measure": {"enum": [False, True, "full"], "default": True,
                    "description": "Measurement level of the returned inspection; explicit null rejects"},
    }
    if not document:
        properties["document_id"]["x-ignored"] = True
    if op in classes["view"] or op == "preview":
        # View ops (render_view) and preview are read-only: the revision is optional, but checked when given.
        properties["expected_revision"] = {"type": "string", "x-mismatch-code": "stale_revision",
                                         "description": "Optional; when given it must equal the current revision "
                                                        "(stale_revision otherwise)"}
    elif not revision:
        properties["expected_revision"] = {"type": "string", "x-ignored": True}
    if op not in OPERATIONS or "request_id" not in OPERATIONS[op]["fields"]:
        properties["request_id"] = {"type": "string", "minLength": 1, "maxLength": 128}
        if tracked:
            properties["request_id"].update({"x-bridge-only": True,
                                             "description": "Required through the bridge for retry identity; "
                                                            "optional headless"})
        else:
            properties["request_id"]["x-ignored"] = True
    required = ["op"] + (["document_id"] if document else []) + (["expected_revision"] if revision else [])
    return properties, required


def _example(op, example, classes):
    document, revision, _ = envelope_requirements(op, classes)
    rendered = {"op": example.get("op", op)}
    if document:
        rendered["document_id"] = "<document_id>"
    if revision:
        rendered["expected_revision"] = "<revision>"
    rendered.update({key: value for key, value in example.items() if key != "op"})
    return copy.deepcopy(rendered)


def _operation(op, classes):
    entry = OPERATIONS[op]
    properties, required = _envelope(op, classes)
    for name in sorted(entry["fields"]):
        properties[name] = _render(field_schema(op, name))
    body = {
        "kind": _kind(op, classes), "summary": entry["summary"],
        "undoable": op in classes["model"] or op in classes["assembly"] or (op == "batch" and op in classes["ops"]),
        "preview": op in classes["model"] - {"rebuild"} or op == "batch",
        "batch": op in classes["batch"],
        "request": {"type": "object", "additionalProperties": False,
                    "required": required + [field for field in entry["required"] if field not in required],
                    "properties": properties},
        "requires_one_of": [list(group) for group in entry.get("requires_one_of", ())],
        "checked_by_handler": dict(entry.get("checked_by_handler", {})),
        "x-required-when": dict(entry.get("x-required-when", {})),
        "constraints": list(entry.get("constraints", ())),
        "examples": [_example(op, example, classes) for example in entry["examples"]],
        "x-example-fixture": entry["x-example-fixture"],
        "doc": entry["doc"],
    }
    body.update(_render({key: value for key, value in entry.items() if key.startswith("x-") and key not in body}))
    return body


def canonical(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(document):
    return hashlib.sha256(canonical({key: value for key, value in document.items() if key != "digest"})
                          .encode("utf-8")).hexdigest()


def build(controller_cls):
    """The full schema document for the operations of ``controller_cls`` (cached).

    Returns ``{schema_version, $defs, operations, x-example-fixtures,
    x-example-placeholders, digest}``; ``digest`` is the SHA-256 of the
    canonical JSON of everything else. Operations without an OPERATIONS entry
    raise KeyError: every op needs a schema. The result is the shared cache:
    callers must not mutate it; ``select`` returns a new top-level dict to decorate.
    """
    cached = _BUILT.get(controller_cls)
    if cached is not None:
        return cached
    classes = _classes(controller_cls)
    missing = sorted(classes["ops"] - set(OPERATIONS))
    if missing:
        raise KeyError("No operation schema for: " + ", ".join(missing))
    document = {"schema_version": SCHEMA_VERSION, "$defs": _render(DEFS),
                "operations": {op: _operation(op, classes) for op in sorted(classes["ops"])},
                "x-example-fixtures": _render(EXAMPLE_FIXTURES),
                "x-example-placeholders": dict(EXAMPLE_PLACEHOLDERS)}
    document["digest"] = digest(document)
    _BUILT[controller_cls] = document
    return document


def select(document, operations=None):
    """``document`` restricted to ``operations`` (all when None), as a new top-level dict.

    The caller may add or replace top-level keys of the result (contract,
    contract_revision, ...) without touching the cached build. Nested values
    are shared with the cache and must not be mutated. A non-string name raises
    TypeError and an unknown name KeyError; the operation_schema read validates
    its argument (a list of distinct strings) before calling this.
    """
    if operations is None:
        return dict(document)
    names = list(operations)
    invalid = [name for name in names if not isinstance(name, str)]
    if invalid:
        raise TypeError("Operation names must be strings: " + repr(invalid))
    unknown = [name for name in names if name not in document["operations"]]
    if unknown:
        raise KeyError(unknown)
    return {**document, "operations": {name: document["operations"][name] for name in names}}
