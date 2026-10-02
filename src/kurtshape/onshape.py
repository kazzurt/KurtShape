"""Fail-closed compiler for the DECLARED normalized Onshape-style fixture subset.

This module does not execute FeatureScript, decode topology queries, or claim to
ingest raw BTFeatureListResponse. A capture normalizer preserving the real API's
constraints, planes, configuration and expressions remains future work.

All source validation happens before dispatching even `new`. Native geometry and
source mapping are authored exclusively through the shared operation interface.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
from typing import Any

SCHEMA = "kurtshape.onshape-subset/1"
QUANTITY = "BTMParameterQuantity-147"
ENUM = "BTMParameterEnum-145"
FACTORS_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
LITERAL = re.compile(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+(mm|cm|m|in)\s*\Z")


class ConversionError(ValueError):
    def __init__(self, code, message, path="$", **details):
        super().__init__(message)
        self.diagnostic = {"code": code, "message": message, "path": path, **details}


def reject(code, message, path="$", **details):
    raise ConversionError(code, message, path, **details)


def exact_keys(value, allowed, required, path):
    if not isinstance(value, dict):
        reject("invalid_source", "Expected an object", path)
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown:
        reject("unknown_field", "Unknown inputs may affect geometry; conversion rejected", path,
               fields=sorted(unknown))
    if missing:
        reject("missing_field", "Required source inputs are missing", path, fields=sorted(missing))


def text(value, path):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        reject("invalid_source", "Expected nonempty string of at most 200 characters", path)
    return value


def length_mm(expression, path, positive=False):
    if not isinstance(expression, str) or not (match := LITERAL.fullmatch(expression)):
        reject("unsupported_expression", "Only explicit finite mm/cm/m/in quantity literals are supported", path)
    value = float(match[1]) * FACTORS_MM[match[2]]
    if not math.isfinite(value) or abs(value) > 1e6 or (positive and value <= 0):
        reject("invalid_dimension", "Dimension must be finite, within 1 km, and positive when required", path)
    return value


def parameters(feature, path):
    raw = feature.get("parameters")
    if not isinstance(raw, list):
        reject("invalid_source", "parameters must be a list", path + ".parameters")
    found = {}
    for i, param in enumerate(raw):
        at = path + f".parameters[{i}]"
        if not isinstance(param, dict):
            reject("invalid_source", "Parameter must be an object", at)
        kind = param.get("btType")
        if kind == QUANTITY:
            exact_keys(param, {"btType", "parameterId", "expression"}, {"btType", "parameterId", "expression"}, at)
        elif kind == ENUM:
            exact_keys(param, {"btType", "parameterId", "enumName", "value"}, {"btType", "parameterId", "enumName", "value"}, at)
            text(param["enumName"], at + ".enumName")
            text(param["value"], at + ".value")
        else:
            reject("unsupported_parameter_type", "Only declared quantity and enum parameters are supported", at)
        key = text(param["parameterId"], at + ".parameterId")
        if key in found:
            reject("duplicate_parameter", "Duplicate parameter cannot be resolved safely", at, parameter=key)
        found[key] = (param, at)
    return found


def require_parameters(params, required, path):
    unknown = set(params) - set(required)
    missing = set(required) - set(params)
    if unknown or missing:
        reject("unsupported_parameters", "Parameter set must exactly match the declared subset", path,
               unknown=sorted(unknown), missing=sorted(missing))


def quantity(params, key, positive=False):
    param, path = params[key]
    if param["btType"] != QUANTITY:
        reject("invalid_parameter_type", "Expected a quantity", path)
    return length_mm(param["expression"], path + ".expression", positive)


def enum(params, key, enum_name):
    param, path = params[key]
    if param["btType"] != ENUM or param["enumName"] != enum_name:
        reject("invalid_parameter_type", f"Expected {enum_name} enum", path)
    return param["value"]


def native_id(source_id):
    """Stable bounded ASCII native name, unique even after source-ID sanitizing."""
    stem = re.sub(r"[^A-Za-z0-9_]", "_", source_id)[:40]
    return "OS_" + stem + "_" + hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class ConversionPlan:
    name: str
    operations: tuple[dict[str, Any], ...]
    source_mapping: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]


def compile_document(payload):
    """Validate every feature before returning a plan. Never calls the CAD core."""
    exact_keys(payload, {"schema", "name", "units", "features", "provenance"},
               {"schema", "name", "units", "features", "provenance"}, "$")
    if payload["schema"] != SCHEMA:
        reject("unsupported_representation", "Expected declared normalized fixture schema, not raw API or FeatureScript", "$.schema")
    name = text(payload["name"], "$.name")
    if payload["units"] != "mm":
        reject("unsupported_units", "Normalized output must explicitly use mm; quantity literals retain their own units", "$.units")
    provenance = payload["provenance"]
    exact_keys(provenance, {"kind", "description"}, {"kind", "description"}, "$.provenance")
    if provenance["kind"] != "synthetic_fixture":
        reject("uncaptured_provenance", "This increment accepts development fixtures only; real API capture normalization is not implemented", "$.provenance.kind")
    text(provenance["description"], "$.provenance.description")
    features = payload["features"]
    if not isinstance(features, list) or not 1 <= len(features) <= 100:
        reject("invalid_source", "Expected 1–100 complete ordered features", "$.features")
    operations, mapping, profiles, ids, used_profiles = [], [], {}, set(), set()
    has_solid = False
    for i, feature in enumerate(features):
        at = f"$.features[{i}]"
        if not isinstance(feature, dict):
            reject("invalid_source", "Feature must be an object", at)
        kind = feature.get("featureType")
        common = {"featureId", "name", "featureType", "parameters", "suppressed"}
        if kind == "newSketch":
            exact_keys(feature, common | {"plane", "profile", "centerOn"},
                       common - {"suppressed"} | {"plane", "profile"}, at)
        elif kind == "extrude":
            exact_keys(feature, common | {"entities", "direction"},
                       common - {"suppressed"} | {"entities", "direction"}, at)
        else:
            reject("unsupported_feature", "Feature family is outside the declared subset", at, feature_type=kind)
        if feature.get("suppressed", False) is not False:
            reject("unsupported_suppression", "Suppressed/conditional features require captured configuration evaluation", at + ".suppressed")
        source_id = text(feature["featureId"], at + ".featureId")
        if source_id in ids:
            reject("duplicate_feature", "Source feature IDs must be unique", at + ".featureId")
        ids.add(source_id)
        label = text(feature["name"], at + ".name")
        target_id = native_id(source_id)
        params = parameters(feature, at)
        op = {"id": target_id, "source_feature_id": source_id, "source_feature_name": label}
        if kind == "newSketch":
            if feature["plane"] != "XY":
                reject("unsupported_plane", "Only an explicitly resolved XY datum is supported", at + ".plane")
            profile = feature["profile"]
            if profile == "rectangle":
                if "centerOn" in feature:
                    reject("unsupported_reference", "centerOn is only supported for circles", at + ".centerOn")
                require_parameters(params, {"x", "y", "width", "height"}, at)
                op.update(op="sketch_rectangle", x=quantity(params, "x"), y=quantity(params, "y"),
                          width=quantity(params, "width", True), height=quantity(params, "height", True))
            elif profile == "circle":
                if "centerOn" in feature:
                    reference = feature["centerOn"]
                    if not isinstance(reference, str) or reference not in profiles or profiles[reference]["profile"] != "rectangle":
                        reject("unsupported_reference", "centerOn must reference a preceding declared rectangle sketch", at + ".centerOn")
                    rectangle = profiles[reference]["operation"]
                    if rectangle["x"] != 0 or rectangle["y"] != 0:
                        reject("unsupported_reference", "The core's center dependency requires an origin-anchored rectangle", at + ".centerOn")
                    require_parameters(params, {"diameter"}, at)
                    op.update(op="sketch_circle", diameter=quantity(params, "diameter", True),
                              x=rectangle["width"] / 2, y=rectangle["height"] / 2,
                              center_on=profiles[reference]["native_id"])
                else:
                    require_parameters(params, {"x", "y", "diameter"}, at)
                    op.update(op="sketch_circle", x=quantity(params, "x"), y=quantity(params, "y"),
                              diameter=quantity(params, "diameter", True))
            else:
                reject("unsupported_geometry", "Only a dimensioned rectangle or circle profile is supported", at + ".profile")
            profiles[source_id] = {"profile": profile, "native_id": target_id, "operation": op}
        else:
            if feature["direction"] != "+Z":
                reject("unsupported_direction", "Only explicitly positive-Z extrusions are supported", at + ".direction")
            entities = feature["entities"]
            if not isinstance(entities, list) or len(entities) != 1:
                reject("unsupported_query", "Exactly one explicit sketch-region query is required", at + ".entities")
            query = entities[0]
            exact_keys(query, {"btType", "featureId"}, {"btType", "featureId"}, at + ".entities[0]" )
            if query["btType"] != "BTMIndividualSketchRegionQuery-140":
                reject("unsupported_query", "Compressed/topological/deterministic queries are not interpreted", at + ".entities[0]")
            reference = query["featureId"]
            if not isinstance(reference, str) or reference not in profiles:
                reject("missing_dependency", "Sketch-region reference must name a preceding profile", at + ".entities[0].featureId")
            if reference in used_profiles:
                reject("unsupported_dependency", "The first single-body slice consumes each profile once", at + ".entities[0].featureId")
            if "operationType" not in params or "endBound" not in params:
                reject("missing_parameter", "Extrude needs explicit operationType and endBound", at)
            operation = enum(params, "operationType", "NewBodyOperationType")
            bound = enum(params, "endBound", "BoundingType")
            if operation == "NEW" and bound == "BLIND" and not has_solid:
                require_parameters(params, {"operationType", "endBound", "depth"}, at)
                op.update(op="pad", profile=profiles[reference]["native_id"], length=quantity(params, "depth", True))
                has_solid = True
            elif operation == "REMOVE" and bound == "THROUGH_ALL" and has_solid:
                require_parameters(params, {"operationType", "endBound"}, at)
                op.update(op="pocket", profile=profiles[reference]["native_id"], through_all=True)
            else:
                reject("unsupported_extrude", "Supported: one initial blind NEW, then through-all REMOVE", at,
                       operation=operation, end_bound=bound, has_solid=has_solid)
            used_profiles.add(reference)
        operations.append(op)
        mapping.append({"source_feature_id": source_id, "source_feature_name": label, "native_id": target_id})
    if not has_solid:
        reject("incomplete_part", "Fixture must produce a solid, not only sketches", "$.features")
    if set(profiles) != used_profiles:
        reject("unused_profile", "Complete fixture must consume every declared profile", "$.features", unconsumed=sorted(set(profiles) - used_profiles))
    return ConversionPlan(name, tuple(operations), tuple(mapping), dict(provenance))


def convert_document(payload, controller=None):
    """Preflight first; then construct a new native document through dispatch.

    Unknown/unsupported sources create no document. Runtime build failures return
    the partial document and applied mappings explicitly; no file is saved. Each
    feature is a native transaction. This is not an atomic multi-feature import.
    """
    try:
        plan = compile_document(payload)
    except ConversionError as exc:
        return {"ok": False, "phase": "preflight", "error": exc.diagnostic, "native_mutations": 0}
    if controller is None:
        from .core import Controller
        controller = Controller()
    response = controller.dispatch({"op": "new", "name": plan.name})
    if not response.get("ok"):
        return {"ok": False, "phase": "native_create", "error": response.get("error")}
    state = response["result"]
    applied = []
    for operation, mapping in zip(plan.operations, plan.source_mapping):
        request = {**operation, "document_id": state["document_id"], "expected_revision": state["revision"]}
        response = controller.dispatch(request)
        if not response.get("ok"):
            return {"ok": False, "phase": "native_build", "error": response.get("error"),
                    "failed_source_feature_id": mapping["source_feature_id"], "partial_document": state,
                    "applied_source_mapping": applied, "saved": False}
        state = response["result"]
        applied.append(mapping)
    return {"ok": True, "result": state, "source_mapping": applied, "provenance": plan.provenance,
            "real_example_migration": False, "saved": False}
