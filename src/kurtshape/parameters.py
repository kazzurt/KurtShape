"""Contract 3.2 F3a: model parameters in one native ``App::VarSet`` per document.

The set (Name = Label = ``Params``, hidden marker ``KurtShapeParameterSet``) sits at
the top level and holds every parameter as a typed dynamic property: ``length``
(App::PropertyDistance, mm), ``angle`` (App::PropertyAngle, stored in exact degrees)
and ``number`` (App::PropertyFloat). FreeCAD expressions are the only evaluator and
the FCStd the only copy of values, formulas and dependencies; this module validates,
binds, attributes and verifies, it never stores a second model.

Entry points used by the Controller (all on the owner thread):

* ``handle(core, doc, req)`` -- create/edit/rename/delete_parameter inside the
  dispatch transaction; reports go to ``core._reports`` (``parameter_report``,
  ``changed_inputs`` and ``parameter_context`` for error attribution).
* ``prepare_expression`` / ``set_native_expression`` -- the one validator and setter
  every formula path uses (set_expression, edit_extrusion, edit_dress_up, Hole, bind).
* ``verify_applied(core, doc, changed_inputs)`` -- after the step's recompute: the
  native value took the formula's value, helix limits, the Hole re-check.
* ``observe_names(core, doc)`` -- in ``Controller.sync``: silent native renames,
  shadowing names (``invalid_parameter_set``).
* ``rows`` / ``compact_rows`` / ``set_block`` / ``list_result`` -- inspect and
  list_parameters payloads; ``capabilities()``.

Pruning (``apply_change``): FreeCAD dependencies are object level, so recomputing
after a parameter edit would rebuild every consumer of the set. Consumers whose
evaluated inputs did not change and that were not touched before the request are
``purgeTouched()`` after ``doc.recompute([set])``; ``KURTSHAPE_FULL_PARAMETER_RECOMPUTE=1``
turns that off (the oracle).
"""
from __future__ import annotations

import math
import os
import re

import FreeCAD as App

SET_NAME = "Params"
MARKER = "KurtShapeParameterSet"
GROUP = "Parameters"
METADATA = "KurtShapeProject"
STATIC = frozenset({"ExpressionEngine", "Label", "Label2", "Visibility"})
NAME_PATTERN = r"^[a-z][A-Za-z0-9_]{0,63}$"
TYPES = {"length": "App::PropertyDistance", "angle": "App::PropertyAngle", "number": "App::PropertyFloat"}
TYPE_NAMES = tuple(TYPES)
NATIVE_TYPES = {"App::PropertyDistance": "length", "App::PropertyLength": "length", "App::PropertyAngle": "angle",
                "App::PropertyFloat": "number"}
WIRE_UNITS = {"length": "mm", "angle": "rad", "number": ""}
NATIVE_UNITS = {"length": "mm", "angle": "deg", "number": ""}
# Shared formula alphabet (replaces the two copies in extrusion_edit and reference_tools): adds ',' for
# two-argument functions and '^'; no '<', '#' or quotes, so no label or cross-document reference.
EXPRESSION_PATTERN = r"[A-Za-z0-9_ .,+*/^()\[\]-]+"
MAX_EXPRESSION = 512
MAX_BIND = 64
MAX_NAMES = 256
MAX_ABS = 1e6
MAX_DEGREES = 360.0
TOLERANCE = 1e-9
OPS = frozenset({"create_parameter", "edit_parameter", "rename_parameter", "delete_parameter"})
READ_OPS = frozenset({"list_parameters"})
def _batchable():
    """Parameter ops a batch may run: derived from batch.EXCLUDED, the one hand-kept list (F4 D8)."""
    from . import batch
    return sorted(OPS - set(batch.EXCLUDED))
FULL_RECOMPUTE_ENV = "KURTSHAPE_FULL_PARAMETER_RECOMPUTE"
_QUALIFIED = re.compile(r"(?:<<([^>]*)>>|\b([A-Za-z_]\w*))\s*\.\s*([A-Za-z_]\w*)")
_BARE = re.compile(r"(?<![\w.<>])([A-Za-z_]\w*)(?!\s*[.(\w])")
_IDENT = re.compile(r"(?<![\w.])([A-Za-z_]\w*)")


def _error(code, message, **details):
    from .core import OperationError
    return OperationError(code, message, **details)


def capabilities():
    return {"scope": "document", "set_id": SET_NAME, "types": dict(WIRE_UNITS), "native_units": {"angle": "deg"},
            "name_pattern": NAME_PATTERN, "operations": sorted(OPS | READ_OPS), "batchable": _batchable(),
            "bindable": "the native_parameters rows of inspect (sketch dimensions, Length, Offset, Angle, helix "
                        "Pitch/Height/Radius, Radius, Size, Thickness, Hole Diameter/Depth/PointAngle)",
            "pruning": os.environ.get(FULL_RECOMPUTE_ENV) != "1"}


# --------------------------------------------------------------------------- the set

def _index(doc):
    from . import document_index
    return document_index.get(doc)


def sets(doc):
    """(marked, unmarked) VarSets in document order; the first marked set is authoritative."""
    index = _index(doc)
    cached = index.derived.get("parameter_set") if index is not None else None
    if cached is None:
        marked, other = [], []
        for obj in doc.Objects:
            try:
                if not obj.isDerivedFrom("App::VarSet"):
                    continue
            except Exception:
                continue
            try:
                flagged = bool(obj.getPropertyByName(MARKER))
            except Exception:
                flagged = False
            (marked if flagged else other).append(obj.Name)
        cached = (tuple(marked), tuple(other))
        if index is not None:
            index.derived["parameter_set"] = cached
    marked = [doc.getObject(name) for name in cached[0]]
    other = [doc.getObject(name) for name in cached[1]]
    return [obj for obj in marked if obj is not None], [obj for obj in other if obj is not None]


def parameter_set(doc):
    marked = sets(doc)[0]
    return marked[0] if marked else None


def is_set(obj):
    try:
        return obj.isDerivedFrom("App::VarSet")
    except Exception:
        return False


def create_set(doc):
    """The set, created in the caller's transaction when missing (Name and Label ``Params``)."""
    vs = parameter_set(doc)
    if vs is not None:
        return vs
    vs = doc.addObject("App::VarSet", SET_NAME)
    vs.Label = vs.Name
    vs.addProperty("App::PropertyBool", MARKER, "KurtShape")
    vs.setEditorMode(MARKER, 2)
    setattr(vs, MARKER, True)
    _invalidate(doc)
    return vs


def _invalidate(doc):
    index = _index(doc)
    if index is not None:
        index.derived.pop("parameter_set", None)
        index.derived.pop("parameter_usage", None)


def names(vs):
    return sorted((name for name in vs.PropertiesList if name not in STATIC and not name.startswith("KurtShape")),
                  key=str.lower)


def kind(vs, name):
    return NATIVE_TYPES.get(vs.getTypeIdOfProperty(name), "unsupported")


def native_value(vs, name):
    value = vs.getPropertyByName(name)
    return float(value.Value if hasattr(value, "Value") else value)


def wire_value(vs, name):
    value = native_value(vs, name)
    return math.radians(value) if kind(vs, name) == "angle" else value


def expression_of(obj, path):
    for item_path, text in getattr(obj, "ExpressionEngine", []):
        if item_path.lstrip(".") == path.lstrip("."):
            return text
    return None


def reads(vs, text, own=False):
    """Parameter names a formula reads: set-qualified tokens, plus bare names inside the set's own formulas."""
    found = set()
    labels = {vs.Name, vs.Label}
    for match in _QUALIFIED.finditer(text or ""):
        qualifier = match.group(1) if match.group(1) is not None else match.group(2)
        if qualifier in labels:
            found.add(match.group(3))
    if own:
        known = set(names(vs))
        found |= {token for token in _BARE.findall(text or "") if token in known}
    return found


def qualify(vs, target, text):
    """Bare parameter names in a consumer formula become ``Params.<name>`` (unambiguous: names are lowercase-first)."""
    if vs is None:
        return text
    known = set(names(vs))
    own = set(target.PropertiesList)
    qualified = {match.span() for match in _QUALIFIED.finditer(text)}

    def replace(match):
        token = match.group(1)
        inside = any(start <= match.start() < end for start, end in qualified)
        return vs.Name + "." + token if token in known and token not in own and not inside else token
    return _BARE.sub(replace, text)


# --------------------------------------------------------------------------- names

def _expression_argument(expression, field="expression"):
    if expression is not None and not isinstance(expression, str):
        raise _error("invalid_argument", field + " must be a formula string or null", fields=[field])


def check_name(vs, name, current=None):
    """Section 4 rules 1-5 (rule 6 is ``self_check`` after adding or renaming)."""
    if not isinstance(name, str) or not re.fullmatch(NAME_PATTERN, name):
        raise _error("invalid_parameter_name", "A parameter name must start with a lowercase letter, e.g. shaft_diameter, "
                     "then up to 63 letters, digits or underscores", name=name, reason="format")
    if name in STATIC or name.lower().startswith("kurtshape"):
        raise _error("invalid_parameter_name", "That name is reserved", name=name, reason="reserved")
    existing = next((item for item in names(vs) if item.lower() == name.lower() and item != current), None)
    if existing is not None:
        raise _error("duplicate_parameter", "A parameter with that name already exists", name=name, existing=existing)
    if hasattr(vs, name):
        raise _error("invalid_parameter_name", "That name is an attribute of the parameter set", name=name,
                     reason="reserved_attribute")
    try:
        vs.evalExpression(name)
    except Exception as exc:  # FreeCAD raises a plain RuntimeError or a ParserError
        message = str(exc)
        if "not found" not in message:
            reason = "unit" if "Parser" in type(exc).__name__ or "unit" in message.lower() else "expression_token"
            raise _error("invalid_parameter_name", "That name is a unit or an expression keyword", name=name,
                         reason=reason) from None
    else:
        raise _error("invalid_parameter_name", "That name is a constant of the expression language", name=name,
                     reason="constant")
    try:
        vs.evalExpression(name + "(1)")
    except Exception as exc:
        if "Unknown function" not in str(exc) and "not found" not in str(exc):
            raise _error("invalid_parameter_name", "That name is a function of the expression language", name=name,
                         reason="function") from None
    else:
        raise _error("invalid_parameter_name", "That name is a function of the expression language", name=name,
                     reason="function")


def self_check(vs, name):
    """Rule 6: ``Params.<name>`` evaluates to the property itself."""
    try:
        value = vs.evalExpression(vs.Name + "." + name)
    except Exception:
        value = None
    expected = native_value(vs, name)
    actual = float(value.Value if hasattr(value, "Value") else value) if value is not None else None
    if actual is None or abs(actual - expected) > TOLERANCE * max(1.0, abs(expected)):
        raise _error("invalid_parameter_name", "That name cannot be referenced in formulas", name=name, reason="reserved")


# --------------------------------------------------------------------------- values and formulas

def _snap(degrees):
    rounded = round(degrees, 9)
    return rounded if abs(degrees - rounded) <= 1e-12 * max(1.0, abs(degrees)) else degrees


def parse_value(value, kind_name, native_type=None):
    """A wire value (number or quantity string) as the native stored value (mm, deg or float)."""
    from .core import number
    if kind_name == "length":
        result = float(number(value, "value", unit="mm"))
        if abs(result) > MAX_ABS:
            raise _error("invalid_argument", "value must be within 1e6 mm", fields=["value"])
        if native_type == "App::PropertyLength" and result < 0:
            raise _error("invalid_argument", "This natively typed length cannot be negative", fields=["value"])
        return result
    if kind_name == "angle":
        if isinstance(value, str):
            try:
                quantity = App.Units.Quantity(value)
            except Exception:
                raise _error("invalid_argument", "value requires an angle such as \"15 deg\"", fields=["value"]) from None
            if quantity.Unit == App.Units.Quantity("1 deg").Unit:
                degrees = float(quantity.getValueAs("deg"))
            elif quantity.Unit == App.Units.Quantity(1).Unit:
                degrees = _snap(math.degrees(quantity.Value))
            else:
                raise _error("invalid_argument", "value requires an angle such as \"15 deg\"", fields=["value"])
        else:
            degrees = _snap(math.degrees(float(number(value, "value", unit="rad"))))
        if not math.isfinite(degrees) or abs(degrees) > MAX_DEGREES + TOLERANCE:
            raise _error("invalid_argument", "An angle parameter is limited to -360..360 degrees", fields=["value"],
                         allowed_range_rad=[-2 * math.pi, 2 * math.pi])
        return degrees
    if isinstance(value, str):
        try:
            quantity = App.Units.Quantity(value)
        except Exception:
            raise _error("invalid_argument", "value requires a number", fields=["value"]) from None
        if quantity.Unit != App.Units.Quantity(1).Unit:
            raise _error("unit_mismatch", "A number parameter takes a unitless value", expected_unit="",
                         actual_unit=quantity.Unit.Type or "1", fields=["value"])
        result = float(quantity.Value)
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error("invalid_argument", "value requires a number", fields=["value"])
    else:
        result = float(value)
    if not math.isfinite(result) or abs(result) > MAX_ABS:
        raise _error("invalid_argument", "value must be finite and within 1e6", fields=["value"])
    return result


def _unit_type(value):
    if not hasattr(value, "Unit"):
        return ""
    if value.Unit == App.Units.Quantity(1).Unit:
        return ""
    if value.Unit == App.Units.Quantity("1 mm").Unit:
        return "mm"
    if value.Unit == App.Units.Quantity("1 deg").Unit:
        return "rad"
    return value.Unit.Type or str(value.Unit)


def prepare_expression(doc, target, expression, unit, *, own=False, field="expression"):
    """Validate and evaluate a formula for ``target``; returns (stored text, value in wire units).

    ``unit`` is the target's wire unit ("mm", "rad" or ""); ``own`` marks the parameter set's own
    formulas (bare names resolve natively there and are never rewritten).
    """
    if not isinstance(expression, str) or not expression.strip() or len(expression) > MAX_EXPRESSION:
        raise _error("invalid_argument", "A formula is a non-empty string of at most 512 characters", fields=[field])
    if not re.fullmatch(EXPRESSION_PATTERN, expression):
        bad = next((char for char in expression if not re.fullmatch(EXPRESSION_PATTERN, char)), "?")
        raise _error("invalid_argument", "Use a dimensional formula with named properties and arithmetic; "
                     + repr(bad) + " is not allowed", fields=[field])
    if any(token.startswith("_") for token in _IDENT.findall(expression)):
        raise _error("invalid_expression", "Formulas cannot read pseudo-objects", expression=expression,
                     reason="pseudo_object")
    vs = parameter_set(doc)
    if vs is not None and vs.Label != vs.Name:
        for match in _QUALIFIED.finditer(expression):
            if match.group(2) == vs.Label:
                raise _error("invalid_expression", "Refer to parameters by their id, " + vs.Name + ".<name>",
                             expression=expression, reason="label_reference", hint=vs.Name + "." + match.group(3))
    text = expression if own else qualify(vs, target, expression)
    try:
        value = target.evalExpression(text)
    except Exception as exc:
        reason = (str(exc).strip().splitlines() or ["invalid"])[0][:200]
        raise _error("invalid_expression", "Formula cannot be evaluated: " + reason, expression=text,
                     reason=reason) from None
    actual = _unit_type(value)
    if not (actual == unit or unit == "mm" and actual == ""):
        hint = {"mm": "a length (append \"* 1 mm\" to a unitless value)", "rad": "an angle (append \"* 1 deg\")",
                "": "a unitless number (remove units)"}[unit]
        raise _error("unit_mismatch", "Formula has the wrong unit for this target; it needs " + hint,
                     expected_unit=unit, actual_unit=actual or "1", expression=text, hint=hint)
    native = float(value.getValueAs("deg")) if unit == "rad" else float(value.Value if hasattr(value, "Value") else value)
    if not math.isfinite(native) or abs(native) > MAX_ABS or (own and unit == "rad" and abs(native) > MAX_DEGREES + TOLERANCE):
        raise _error("invalid_expression", "Formula value is out of range", expression=text, reason="range")
    return text, (math.radians(native) if unit == "rad" else native)


def set_native_expression(target, path, text):
    try:
        target.setExpression(path, text)
    except Exception as exc:
        message = str(exc)
        if "cycl" in message.lower():
            raise _error("expression_cycle", "Formula would create a dependency cycle", expression=text) from None
        raise _error("invalid_expression", "Formula was refused: " + (message.splitlines() or [""])[0][:200],
                     expression=text, reason=(message.splitlines() or [""])[0][:200]) from None


# --------------------------------------------------------------------------- bindable targets

def target(doc, feature_name, parameter):
    """The native target of a public (feature, parameter): {feature, object, native, path, aliases, info}."""
    from .core import native_parameters
    feature = doc.getObject(feature_name) if isinstance(feature_name, str) and feature_name else None
    if feature is None:
        raise _error("missing_reference", "Feature ID does not exist", feature=feature_name)
    rows = native_parameters(feature)
    if not isinstance(parameter, str) or parameter not in rows:
        raise _error("unsupported_parameter", "Choose an editable parameter reported by inspect",
                     target={"feature": feature_name, "parameter": parameter})
    info = rows[parameter]
    native = doc.getObject(info["native_feature"]) if info.get("native_feature") else feature
    if native.TypeId == "Sketcher::SketchObject":
        if not native.Constraints[info["constraint_index"]].Driving:
            raise _error("unsupported_parameter", "This parameter is not a supported driving dimension",
                         target={"feature": feature_name, "parameter": parameter})
        path = f"Constraints.{info['name']}" if info.get("name") else f"Constraints[{info['constraint_index']}]"
        aliases = {path, f"Constraints[{info['constraint_index']}]"}
        if info.get("name"):
            aliases.add(f"Constraints.{info['name']}")
    else:
        path = info.get("native_property", parameter)
        aliases = {path}
    return {"feature": feature, "native": native, "path": path, "aliases": aliases, "info": info,
            "parameter": parameter, "unit": info["unit"]}


def current_value(doc, feature_name, parameter):
    from .core import native_parameters
    feature = doc.getObject(feature_name)
    return native_parameters(feature)[parameter]["value"] if feature is not None else None


def driving_expression(spec):
    native = spec["native"]
    return next((text for path, text in native.ExpressionEngine if path.lstrip(".") in spec["aliases"]), None)


# --------------------------------------------------------------------------- consumers and records

def _consumer_objects(vs):
    return [obj for obj in vs.InList if obj.Name != METADATA and obj is not vs]


def consumers(doc, vs):
    """({name: [entry]}, dangling) for every set-reading formula of the set's users (and the set's own formulas)."""
    known = set(names(vs))
    usage, dangling = {name: [] for name in known}, []
    for obj in _consumer_objects(vs):
        for path, text in getattr(obj, "ExpressionEngine", []):
            for name in sorted(reads(vs, text)):
                entry = _attribute(doc, obj, path, text)
                if name in known:
                    usage[name].append(entry)
                else:
                    dangling.append(dict(entry, name=name))
    for path, text in getattr(vs, "ExpressionEngine", []):
        for name in sorted(reads(vs, text, own=True)):
            if name in usage:
                usage[name].append({"parameter_of_set": path.lstrip("."), "path": path, "expression": text})
    return usage, dangling


def _attribute(doc, obj, path, text):
    """Public (feature, parameter) of a native formula entry."""
    from .core import native_parameters
    from . import hole_tools
    owner_name = getattr(obj, "KurtShapeOperationOwner", "") or ""
    representative = doc.getObject(owner_name) if owner_name else None
    if representative is None:
        representative = doc.getObject(hole_tools.public_name(obj)) or obj
    parameter = None
    try:
        for name, info in native_parameters(representative).items():
            native_name = info.get("native_feature") or representative.Name
            if native_name != obj.Name:
                continue
            aliases = {info.get("native_property", name)}
            if "constraint_index" in info:
                aliases |= {f"Constraints[{info['constraint_index']}]"}
                if info.get("name"):
                    aliases.add(f"Constraints.{info['name']}")
            if path.lstrip(".") in aliases:
                parameter = name
                break
    except Exception:
        parameter = None
    return {"feature": representative.Name, "native_feature": obj.Name, "parameter": parameter,
            "path": path, "expression": text}


def _evaluate(obj, text):
    try:
        value = obj.evalExpression(text)
    except Exception as exc:
        return ("error", (str(exc).splitlines() or [""])[0][:200])
    try:
        return ("value", float(value.Value if hasattr(value, "Value") else value))
    except Exception:
        return ("error", "not a number")


def records(doc, vs):
    """{(object, path): ("value", native float) | ("error", message)} for every set-reading formula."""
    result = {}
    for obj in _consumer_objects(vs):
        for path, text in getattr(obj, "ExpressionEngine", []):
            if reads(vs, text):
                result[(obj.Name, path)] = _evaluate(obj, text)
    for name in names(vs):
        result[(vs.Name, "=" + name)] = ("value", native_value(vs, name)) if kind(vs, name) != "unsupported" else ("error", "")
    return result


def apply_change(core, doc, vs, mutate, previous=None, hole_intents=None):
    """Run ``mutate`` and settle the set; returns (changed_inputs, changed_parameters, pruned, before, after).

    ``previous`` gives wire values of bind targets that had no formula before; ``hole_intents``
    their Holes' dimensions before the change (consumers already reading the set are snapshotted here).
    """
    from . import hole_tools, studio
    previous = previous or {}
    pre = {obj.Name for obj in _consumer_objects(vs) if "Touched" in obj.State}
    before = records(doc, vs)
    holes = {obj.Name: hole_tools._intent(obj) for obj in _consumer_objects(vs)
             if obj.TypeId == "PartDesign::Hole" and studio.is_active(obj)}
    holes.update(hole_intents or {})
    before_values = {name: (kind(vs, name), native_value(vs, name)) for name in names(vs)
                     if kind(vs, name) != "unsupported"}
    mutate()
    vs = parameter_set(doc) or vs
    doc.recompute([vs])
    after = records(doc, vs)
    changed_inputs, changed_objects = [], set()
    for key, record in after.items():
        obj_name, path = key
        if obj_name == vs.Name or record == before.get(key):
            continue
        obj = doc.getObject(obj_name)
        text = expression_of(obj, path)
        entry = _attribute(doc, obj, path, text)
        unit = _public_unit(doc, entry)
        current = _wire(obj, path, record, unit)
        old = before.get(key)
        entry.update(previous=_wire(obj, path, old, unit) if old else previous.get(key), current=current,
                     rebound=bool(old and old[0] == "error" and record[0] == "value"))
        if obj_name in holes:
            entry["hole_intent"] = holes[obj_name]
        changed_inputs.append(entry)
        changed_objects.add(obj_name)
    after_values = {name: (kind(vs, name), native_value(vs, name)) for name in names(vs)
                    if kind(vs, name) != "unsupported"}
    changed_parameters = []
    for name in sorted(set(before_values) | set(after_values), key=str.lower):
        old, new = before_values.get(name), after_values.get(name)
        if old != new and old is not None and new is not None:
            convert = math.radians if new[0] == "angle" else float
            changed_parameters.append({"name": name, "previous": convert(old[1]), "current": convert(new[1])})
    precheck(doc, changed_inputs)
    pruned = []
    if os.environ.get(FULL_RECOMPUTE_ENV) != "1":
        # Only objects whose dependence on the set is a recorded formula are proven unaffected; any other
        # link to the set (a property link, a Python feature) keeps its native rebuild.
        formula_owners = {key[0] for key in before} | {key[0] for key in after}
        for obj in _consumer_objects(vs):
            if (obj.Name in pre or obj.Name in changed_objects or obj.Name not in formula_owners
                    or "Touched" not in obj.State):
                continue
            obj.purgeTouched()
            pruned.append(obj.Name)
    _invalidate(doc)
    return changed_inputs, changed_parameters, sorted(pruned), before, after


def _public_unit(doc, entry):
    """The wire unit of a formula entry's public parameter ("mm", "rad", ""), or None when it has none."""
    from .core import native_parameters
    feature = doc.getObject(entry.get("feature") or "")
    if feature is None or not entry.get("parameter"):
        return None
    try:
        return native_parameters(feature)[entry["parameter"]].get("unit")
    except Exception:
        return None


def _wire(obj, path, record, unit=None):
    """A native record value in the target's wire units (radians for angle properties).

    Formula values of angles are degrees whatever the property type stores (a studio revolve's
    float ``Angle`` among them), so a known public ``unit`` decides first.
    """
    if not record or record[0] != "value":
        return None
    value = record[1]
    if unit is not None:
        return math.radians(value) if unit == "rad" else value
    try:
        clean = path.lstrip(".")
        if obj.TypeId == "Sketcher::SketchObject" and clean.startswith("Constraints"):
            index = None
            if clean.startswith("Constraints["):
                index = int(clean[len("Constraints["):].split("]")[0])
            else:
                name = clean.split(".", 1)[1]
                index = next(i for i, c in enumerate(obj.Constraints) if c.Name == name)
            return math.radians(value) if obj.Constraints[index].Type == "Angle" else value
        prop = clean.split(".", 1)[0]
        type_id = obj.getTypeIdOfProperty(prop)
        return math.radians(value) if "Angle" in type_id else value
    except Exception:
        return value


# --------------------------------------------------------------------------- verification

def precheck(doc, changed_inputs):
    """Bound native work before the step's recompute: a helix that would get too many turns is refused first.

    FreeCAD builds every turn eagerly, so the helix limits apply to the values the formulas evaluated to,
    before any rebuild (``verify_applied`` checks them again afterwards).
    """
    from . import modeling_geometry
    pending = {}
    for entry in changed_inputs or ():
        native = doc.getObject(entry.get("native_feature", ""))
        if native is not None and native.TypeId == "Part::Helix" and entry.get("current") is not None:
            pending.setdefault(native.Name, {})[entry["path"].lstrip(".")] = entry["current"]
    for name, values in pending.items():
        helix = doc.getObject(name)
        segment = helix.SegmentLength
        modeling_geometry.check_helix_size(values.get("Pitch", helix.Pitch.Value), values.get("Height", helix.Height.Value),
                                           float(getattr(segment, "Value", segment)))


def verify_applied(core, doc, changed_inputs):
    """After the step's recompute: native values took their formulas' values; helix limits; the Hole re-check."""
    if not changed_inputs:
        return
    from . import hole_tools, modeling_geometry, studio
    holes = {}
    for entry in changed_inputs:
        native = doc.getObject(entry.get("native_feature", ""))
        if native is None or not studio.is_active(native) or entry.get("current") is None:
            continue
        if native.TypeId == "PartDesign::Hole":
            group = holes.setdefault(native.Name, {"hole": native, "before": entry.get("hole_intent"), "edited": set()})
            group["edited"].add(entry["path"].lstrip("."))
            continue
        unit = _public_unit(doc, entry)
        if entry.get("parameter") and entry.get("feature"):
            actual = current_value(doc, entry["feature"], entry["parameter"])
        else:
            actual = _wire(native, entry["path"], _evaluate_property(native, entry["path"]))
        # The formula's value now, after the step's recompute (an input it reads may have been rebuilt
        # since ``current`` was evaluated); ``current`` stays what the report shows.
        text = entry.get("expression") or expression_of(native, entry["path"])
        expected = _wire(native, entry["path"], _evaluate(native, text), unit) if text else entry["current"]
        if expected is None:
            expected = entry["current"]
        if actual is None or abs(actual - expected) > TOLERANCE * max(1.0, abs(expected)):
            raise _error("parameter_not_applied", "The native value did not take the formula's value",
                         feature=entry.get("feature"), parameter=entry.get("parameter"), path=entry["path"],
                         expected=expected, actual=actual)
        if native.TypeId == "Part::Helix":
            segment = native.SegmentLength
            modeling_geometry.check_helix_size(native.Pitch.Value, native.Height.Value,
                                               float(getattr(segment, "Value", segment)))
    for group in holes.values():
        hole_tools.recheck(core, doc, group["hole"], group["before"] or hole_tools._intent(group["hole"]),
                           group["edited"])


def _evaluate_property(obj, path):
    try:
        value = obj
        for part in path.lstrip(".").split("."):
            value = getattr(value, part)
        return ("value", float(value.Value if hasattr(value, "Value") else value))
    except Exception:
        return None


# --------------------------------------------------------------------------- names observed in sync

def observe_names(core, doc):
    """Silent native renames re-key intent; type-level attribute names make the set unusable."""
    vs = parameter_set(doc)
    state = core.observer.state(doc)
    if vs is None:
        state.pop("parameter_names", None)
        return
    current = tuple(names(vs))
    attributes = set(dir(type(vs)))
    shadowing = sorted(name for name in current if name in attributes)
    if shadowing:
        raise _error("invalid_parameter_set", "A parameter name hides an attribute of the parameter set; rename it in "
                     "the FreeCAD property editor", names=shadowing, hint="rename it in the FreeCAD property editor")
    known = state.get("parameter_names")
    if known is not None and known != current and not core.busy:
        core.observer.note_intent_change(vs)
        _invalidate(doc)
    state["parameter_names"] = current


# --------------------------------------------------------------------------- read payloads

def _status(vs, name):
    # A failed recompute leaves the set Touched *and* Invalid: name the failing formula first.
    if {"Invalid", "Error"} & set(vs.State):
        text = expression_of(vs, name)
        if text is not None:
            outcome = _evaluate(vs, text)
            if outcome[0] == "error":
                return "invalid", outcome[1]
    if "Touched" in vs.State:
        return "needs_rebuild", None
    return "valid", None


def compact_row(vs, name, used_by_count=None):
    kind_name = kind(vs, name)
    status, error = _status(vs, name)
    native_type = vs.getTypeIdOfProperty(name)
    row = {"name": name, "type": kind_name, "unit": WIRE_UNITS.get(kind_name), "value": None, "native_value": None,
           "native_unit": NATIVE_UNITS.get(kind_name), "expression": expression_of(vs, name),
           "expression_ref": vs.Name + "." + name, "native_type": native_type, "status": status, "error": error}
    if kind_name != "unsupported":
        row["native_value"] = native_value(vs, name)
        row["value"] = wire_value(vs, name)
    if used_by_count is not None:
        row["used_by_count"] = used_by_count
    return row


def usage(doc, names_wanted=None):
    """{name: [used_by rows]} of the document's parameters (C27; backs list_parameters and the panel adapter)."""
    vs = parameter_set(doc)
    if vs is None:
        return {}
    found, _ = consumers(doc, vs)
    return {name: rows for name, rows in found.items() if names_wanted is None or name in names_wanted}


def usage_rows(doc, names_wanted):
    """{name: list_parameters row} for the wanted names, without a dispatch (the panel's lazy usage read)."""
    vs = parameter_set(doc)
    if vs is None:
        return {}
    found, _ = consumers(doc, vs)
    return {name: full_row(doc, vs, name, found) for name in names(vs) if name in names_wanted}


def usage_counts(doc, vs):
    """{name: consumer count}, cached per document change (index.derived["parameter_usage"])."""
    index = _index(doc)
    cached = index.derived.get("parameter_usage") if index is not None else None
    if cached is None or cached[0] != vs.Name:
        usage, _ = consumers(doc, vs)
        cached = (vs.Name, {name: len(entries) for name, entries in usage.items()})
        if index is not None:
            index.derived["parameter_usage"] = cached
    return cached[1]


def set_block(doc):
    """inspect.parameter_set: {id, label, state, error} or None."""
    vs = parameter_set(doc)
    if vs is None:
        return None
    error = None
    if {"Invalid", "Error"} & set(vs.State):
        for name in names(vs):
            status, message = _status(vs, name)
            if status == "invalid":
                error = {"name": name, "message": message}
                break
        if error is None:
            error = {"name": None, "message": vs.getStatusString()}
    state = "invalid" if error else ("needs_rebuild" if "Touched" in vs.State else "valid")
    return {"id": vs.Name, "label": vs.Label, "state": state, "error": error}


def other_sets(doc):
    marked, other = sets(doc)
    rows = [{"id": obj.Name, "label": obj.Label, "names": names(obj), "marked": True} for obj in marked[1:]]
    rows += [{"id": obj.Name, "label": obj.Label, "names": names(obj), "marked": False} for obj in other]
    return rows


def compact_rows(doc):
    vs = parameter_set(doc)
    if vs is None:
        return []
    counts = usage_counts(doc, vs)
    return [compact_row(vs, name, counts.get(name, 0)) for name in names(vs)]


def for_features(doc, features):
    """{feature: [parameter names its formulas read]} for compact feature rows (uses_parameters)."""
    vs = parameter_set(doc)
    if vs is None:
        return {}
    result = {}
    helpers = {}
    for item in doc.Objects:
        owner_name = getattr(item, "KurtShapeOperationOwner", "")
        if owner_name:
            helpers.setdefault(owner_name, []).append(item)
    for name in features:
        obj = doc.getObject(name)
        if obj is None:
            continue
        objects = [obj] + [item for item in helpers.get(name, []) if item is not obj]
        read = set()
        for item in objects:
            for _, text in getattr(item, "ExpressionEngine", []):
                read |= reads(vs, text)
        if read:
            result[name] = sorted(read, key=str.lower)
    return result


def affects(doc, vs, entries):
    """Public features (studio order) and current parts downstream of the given consumer entries."""
    from . import studio
    from .bodies import owner
    seen, stack = set(), [doc.getObject(entry["native_feature"]) for entry in entries if entry.get("native_feature")]
    stack = [obj for obj in stack if obj is not None]
    while stack:
        obj = stack.pop()
        if obj.Name in seen or obj.Name == METADATA or is_set(obj):
            continue
        seen.add(obj.Name)
        for user in obj.InList:
            if user.TypeId == "PartDesign::Body" and user.Tip is not None and user.Tip.Name != obj.Name:
                continue
            stack.append(user)
    representatives = set()
    for name in seen:
        obj = doc.getObject(name)
        owner_name = getattr(obj, "KurtShapeOperationOwner", "") or ""
        representatives.add(owner_name if owner_name and doc.getObject(owner_name) else name)
    ordered = [obj.Name for obj in studio.order(doc)]
    features = [name for name in ordered if name in representatives] if ordered else sorted(representatives)
    current = {studio.part_id(body): body for body in studio.current_parts(doc) or []}
    parts = set()
    for name in seen | representatives:
        obj = doc.getObject(name)
        if obj is None:
            continue
        parts |= set(getattr(obj, "KurtShapeOutputParts", []) or [])
        body = owner(doc, obj)
        if body is not None and not getattr(body, "KurtShapeInternal", False):
            parts.add(studio.part_id(body))
    return {"features": features, "parts": sorted(part for part in parts if part in current)}


def full_row(doc, vs, name, usage):
    row = compact_row(vs, name, len(usage.get(name, [])))
    own = expression_of(vs, name)
    row["depends_on"] = sorted(reads(vs, own, own=True) - {name}, key=str.lower) if own else []
    row["used_by_parameters"] = sorted((entry["parameter_of_set"] for entry in usage.get(name, [])
                                        if "parameter_of_set" in entry), key=str.lower)
    row["used_by"] = [dict(entry) for entry in usage.get(name, []) if "parameter_of_set" not in entry]
    closure, frontier = {name}, [name]
    while frontier:
        current = frontier.pop()
        for entry in usage.get(current, []):
            dependent = entry.get("parameter_of_set")
            if dependent and dependent not in closure:
                closure.add(dependent)
                frontier.append(dependent)
    reached = [entry for parameter in closure for entry in usage.get(parameter, []) if "parameter_of_set" not in entry]
    row["affects"] = affects(doc, vs, reached)
    return row


def list_result(core, doc, req):
    meta = core._meta(doc)
    wanted = req.get("names")
    vs = parameter_set(doc)
    available = names(vs) if vs is not None else []
    if wanted is not None:
        if (not isinstance(wanted, list) or not 1 <= len(wanted) <= MAX_NAMES
                or not all(isinstance(item, str) for item in wanted) or len(set(wanted)) != len(wanted)):
            raise _error("invalid_argument", "names must be a list of 1 to 256 distinct parameter names", fields=["names"])
        missing = [item for item in wanted if item not in available]
        if missing:
            raise _error("missing_parameter", "Unknown parameter", names=missing, available=available[:50])
    warnings, rows = [], []
    if vs is not None:
        usage, dangling = consumers(doc, vs)
        rows = [full_row(doc, vs, name, usage) for name in (wanted or available)]
        warnings = [dict(entry, code="dangling_reference") for entry in dangling]
    warnings += [{"code": "extra_parameter_set", "id": row["id"]} for row in other_sets(doc) if row["marked"]]
    return {"document_id": meta.DocumentId, "revision": meta.Revision, "parameter_set": set_block(doc),
            "other_parameter_sets": other_sets(doc), "warnings": warnings, "parameters": rows}


# --------------------------------------------------------------------------- mutations

def _require(doc, name):
    vs = parameter_set(doc)
    available = names(vs) if vs is not None else []
    if not isinstance(name, str) or name not in available:
        raise _error("missing_parameter", "Unknown parameter", names=[name], available=available[:50])
    return vs


def _context(core, name, operation):
    core._reports["parameter_context"] = {"name": name, "operation": operation}


def handle(core, doc, req):
    op = req["op"]
    if op == "create_parameter":
        return _create(core, doc, req)
    if op == "edit_parameter":
        return _edit(core, doc, req)
    if op == "rename_parameter":
        return _rename(core, doc, req)
    return _delete(core, doc, req)


def _bind_specs(doc, bind):
    if bind is None:
        return []
    if (not isinstance(bind, list) or not 1 <= len(bind) <= MAX_BIND
            or not all(isinstance(item, dict) and set(item) == {"feature", "parameter"}
                       and all(isinstance(item[key], str) and item[key] for key in item) for item in bind)):
        raise _error("invalid_argument", "bind is a list of 1 to 64 {feature, parameter} targets", fields=["bind"])
    pairs = [(item["feature"], item["parameter"]) for item in bind]
    if len(set(pairs)) != len(pairs):
        raise _error("invalid_argument", "bind targets must be distinct", fields=["bind"])
    specs = []
    for feature, parameter in pairs:
        spec = target(doc, feature, parameter)
        current = driving_expression(spec)
        if current is not None:
            raise _error("expression_driven", "That dimension is already driven by a formula",
                         target={"feature": feature, "parameter": parameter}, expression=current)
        specs.append(spec)
    return specs


def _create(core, doc, req):
    name, kind_name = req.get("name"), req.get("type")
    _context(core, name, "create_parameter")
    _expression_argument(req.get("expression"))
    if kind_name is not None and (not isinstance(kind_name, str) or kind_name not in TYPES):
        raise _error("invalid_argument", "type must be length, angle or number", fields=["type"])
    if "value" in req and req.get("expression") is not None:
        raise _error("invalid_argument", "Give a value or an expression, not both", fields=["value", "expression"])
    specs = _bind_specs(doc, req.get("bind"))
    if kind_name is None and specs:
        units = {spec["unit"] for spec in specs}
        if len(units) != 1:
            raise _error("unit_mismatch", "Bind targets mix lengths and angles", expected_unit=sorted(units)[0],
                         actual_unit=sorted(units)[-1])
        kind_name = {"mm": "length", "rad": "angle"}[units.pop()]
    if kind_name is None and isinstance(req.get("value"), str):
        try:
            unit = App.Units.Quantity(req["value"]).Unit
        except Exception:
            unit = None
        kind_name = ("length" if unit == App.Units.Quantity("1 mm").Unit else
                     "angle" if unit == App.Units.Quantity("1 deg").Unit else None)
    vs_existing = parameter_set(doc)
    if kind_name is None and isinstance(req.get("expression"), str):
        try:
            # Other parameters are read through the set; a literal formula needs none.
            value = (vs_existing.evalExpression(req["expression"]) if vs_existing is not None
                     else App.Units.Quantity(req["expression"]))
            unit = _unit_type(value)
        except Exception:
            unit = None
        kind_name = {"mm": "length", "rad": "angle", "": "number"}.get(unit)
    if kind_name is None:
        raise _error("invalid_argument", "Give type (length, angle or number); it cannot be inferred", fields=["type"],
                     hint="give type")
    for spec in specs:
        if WIRE_UNITS[kind_name] != spec["unit"]:
            raise _error("unit_mismatch", "A " + kind_name + " parameter cannot drive this target",
                         expected_unit=spec["unit"], actual_unit=WIRE_UNITS[kind_name] or "1",
                         target={"feature": spec["feature"].Name, "parameter": spec["parameter"]})
    if "value" not in req and req.get("expression") is None:
        if not specs:
            raise _error("invalid_argument", "Give a value, an expression or bind targets", fields=["value"])
        values = [spec["info"]["value"] for spec in specs]
        if any(abs(value - values[0]) > TOLERANCE * max(1.0, abs(values[0])) for value in values):
            raise _error("bind_values_differ", "The bind targets have different values; give a value",
                         targets=[{"feature": spec["feature"].Name, "parameter": spec["parameter"], "value": value}
                                  for spec, value in zip(specs, values)])
        stored = _snap(math.degrees(values[0])) if kind_name == "angle" else values[0]
    elif "value" in req:
        stored = parse_value(req["value"], kind_name)
    else:
        stored = None
    from . import hole_tools
    hole_intents = {spec["native"].Name: hole_tools._intent(spec["native"]) for spec in specs
                    if spec["native"].TypeId == "PartDesign::Hole"}
    vs = create_set(doc)
    check_name(vs, name)
    previous = {}
    bound = []

    def mutate():
        vs.addProperty(TYPES[kind_name], name, GROUP)
        _invalidate(doc)
        if stored is not None:
            setattr(vs, name, stored)
        else:
            _apply_own_formula(doc, vs, name, req["expression"], kind_name)
        self_check(vs, name)
        for spec in specs:
            text, _ = prepare_expression(doc, spec["native"], vs.Name + "." + name, spec["unit"])
            previous[(spec["native"].Name, "." + spec["path"])] = spec["info"]["value"]
            previous[(spec["native"].Name, spec["path"])] = spec["info"]["value"]
            set_native_expression(spec["native"], spec["path"], text)
            bound.append({"feature": spec["feature"].Name, "native_feature": spec["native"].Name,
                          "parameter": spec["parameter"], "path": spec["path"], "expression": text})
    changed, changed_parameters, pruned, _, _ = apply_change(core, doc, vs, mutate, previous, hole_intents)
    core._reports["changed_inputs"] = changed
    core._reports["created_parameter"] = name
    core._reports["parameter_report"] = {"operation": "create_parameter", "name": name,
                                         "row": compact_row(vs, name, usage_counts(doc, vs).get(name, 0)),
                                         "bound": bound, "changed_inputs": _public(changed),
                                         "rebound": _public([entry for entry in changed if entry.get("rebound")]),
                                         "pruned": pruned}
    return None


def _public(entries):
    """changed_inputs rows as reported (internal Hole snapshots stay internal)."""
    return [{key: value for key, value in entry.items() if key != "hole_intent"} for entry in entries]


def _apply_own_formula(doc, vs, name, expression, kind_name):
    for match in _QUALIFIED.finditer(expression or ""):
        qualifier = match.group(1) if match.group(1) is not None else match.group(2)
        if qualifier not in {vs.Name} and qualifier not in set(names(vs)):
            raise _error("invalid_expression", "A parameter formula can only read parameters", expression=expression,
                         reason="reads " + qualifier)
    text, _ = prepare_expression(doc, vs, expression, WIRE_UNITS[kind_name], own=True)
    set_native_expression(vs, name, text)
    if [obj for obj in vs.OutList if obj.Name != vs.Name]:
        raise _error("invalid_expression", "A parameter formula can only read parameters", expression=expression,
                     reason="reads a feature")


def _edit(core, doc, req):
    name = req.get("name")
    _context(core, name, "edit_parameter")
    _expression_argument(req.get("expression"))
    vs = _require(doc, name)
    kind_name = kind(vs, name)
    if kind_name == "unsupported":
        raise _error("unsupported_parameter", "This natively added parameter type cannot be edited; rename or delete it",
                     name=name, native_type=vs.getTypeIdOfProperty(name))
    has_value, has_expression = "value" in req and req["value"] is not None, "expression" in req
    expression = req.get("expression")
    if not has_value and not has_expression:
        raise _error("invalid_argument", "Give a value or an expression", fields=["value", "expression"])
    if has_value and expression is not None:
        raise _error("invalid_argument", "Give a value or an expression, not both", fields=["value", "expression"])
    current = expression_of(vs, name)
    if has_value and current is not None and not has_expression:
        raise _error("expression_driven", "This parameter is driven by a formula; clear it with expression:null",
                     name=name, expression=current)
    stored = parse_value(req["value"], kind_name, vs.getTypeIdOfProperty(name)) if has_value else None
    report_previous = {"value": wire_value(vs, name), "expression": current}

    def mutate():
        if has_expression and expression is None:
            set_native_expression(vs, name, None)
        elif has_expression:
            _apply_own_formula(doc, vs, name, expression, kind_name)
        if stored is not None:
            setattr(vs, name, stored)
    changed, changed_parameters, pruned, _, _ = apply_change(core, doc, vs, mutate)
    core._reports["changed_inputs"] = changed
    core._reports["parameter_report"] = {
        "operation": "edit_parameter", "name": name, "previous": report_previous,
        "current": {"value": wire_value(vs, name), "expression": expression_of(vs, name)},
        "changed_parameters": changed_parameters, "changed_inputs": _public(changed),
        "affected": affects(doc, vs, changed), "pruned": pruned}
    return None


def _rename(core, doc, req):
    name, new_name = req.get("name"), req.get("new_name")
    _context(core, name, "rename_parameter")
    vs = _require(doc, name)
    check_name(vs, new_name, current=name)
    usage, _ = consumers(doc, vs)
    rewritten = []

    def mutate():
        vs.renameProperty(name, new_name)
        _invalidate(doc)
        self_check(vs, new_name)
        core.observer.note_intent_change(vs)
    changed, _, pruned, before, after = apply_change(core, doc, vs, mutate)
    broken = []
    for key, record in before.items():
        if key[0] == vs.Name:
            continue
        if record[0] == "value" and after.get(key) != record:
            broken.append({"native_feature": key[0], "path": key[1], "before": record[1], "after": after.get(key)})
    if broken:
        raise _error("rename_failed", "Renaming would change or break consumer formulas", broken=broken)
    for entry in usage.get(name, []):
        obj = doc.getObject(entry["native_feature"]) if "native_feature" in entry else vs
        path = entry["path"] if "native_feature" in entry else entry["parameter_of_set"]
        rewritten.append(dict(entry, expression=expression_of(obj, path) if obj else entry["expression"]))
    core._reports["changed_inputs"] = changed
    core._reports["parameter_report"] = {"operation": "rename_parameter", "name": name, "new_name": new_name,
                                         "rewritten": rewritten, "rebound": _public([entry for entry in changed if entry.get("rebound")]),
                                         "changed_inputs": _public(changed), "pruned": pruned}
    return None


def _delete(core, doc, req):
    name = req.get("name")
    _context(core, name, "delete_parameter")
    vs = _require(doc, name)
    freeze = req.get("freeze_consumers", False)
    if not isinstance(freeze, bool):
        raise _error("invalid_argument", "freeze_consumers must be boolean", fields=["freeze_consumers"])
    usage, _ = consumers(doc, vs)
    using = usage.get(name, [])
    if using and not freeze:
        raise _error("parameter_in_use", "Consumers still read this parameter; freeze them or edit them first",
                     name=name, consumers=using, hint="freeze_consumers:true keeps their current values")
    frozen = []

    def mutate():
        for entry in using:
            obj = vs if "parameter_of_set" in entry else doc.getObject(entry["native_feature"])
            path = entry["parameter_of_set"] if "parameter_of_set" in entry else entry["path"]
            record = _evaluate(obj, entry["expression"])
            obj.setExpression(path, None)
            frozen.append(dict(entry, value=record[1] if record[0] == "value" else None))
        vs.removeProperty(name)
        _invalidate(doc)
        core.observer.note_intent_change(vs)
    changed, _, pruned, before, after = apply_change(core, doc, vs, mutate)
    broken = [{"native_feature": key[0], "path": key[1]} for key, record in after.items()
              if key[0] != vs.Name and record[0] == "error" and before.get(key, ("value",))[0] == "value"]
    if broken:
        raise _error("parameter_in_use", "Deleting would break consumer formulas", name=name, consumers=broken)
    core._reports["changed_inputs"] = changed
    core._reports["parameter_report"] = {"operation": "delete_parameter", "name": name, "frozen": frozen,
                                         "changed_inputs": _public(changed), "pruned": pruned}
    return None


def accepted(doc, name):
    """The parameter's state after a rollback (error.parameter.accepted)."""
    vs = parameter_set(doc)
    if vs is None or name not in names(vs) or kind(vs, name) == "unsupported":
        return None
    return {"value": wire_value(vs, name), "native_value": native_value(vs, name), "expression": expression_of(vs, name)}
