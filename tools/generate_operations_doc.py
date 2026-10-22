"""Render docs/OPERATIONS.md, the per-operation reference, from src/kurtshape/operation_schemas.py.

The schema module is the tested source of truth for operation names, argument
types, defaults, required sets and runnable examples; this script only lays it
out. The output is deterministic: no timestamps, no absolute paths, LF line
endings, arguments and nested JSON keys sorted, so a second run is
byte-identical and ``tests/test_operations_doc.py`` fails when the file drifts.

Run it from the checkout root under the bundled interpreter (the schema
resolves values through modules that import FreeCAD), with output redirected
because ``pythonw.exe`` has no console::

    runtime\\freecad-1.1.4\\FreeCAD_1.1.4-Windows-x86_64-py311\\bin\\pythonw.exe -B tools\\generate_operations_doc.py > runtime\\test-tmp\\operations-doc.log 2>&1

``--check`` compares instead of writing (exit 1 on drift). Started outside an
isolated session (``KURTSHAPE_SESSION_DIR`` unset), the script re-runs itself
with a private profile under ``runtime/test-tmp/operations-doc`` so importing
FreeCAD never touches the user's profile.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "OPERATIONS.md"
REGENERATE = (r"runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\pythonw.exe -B "
              r"tools\generate_operations_doc.py > runtime\test-tmp\operations-doc.log 2>&1")

# Section order; the keys are operation_schemas._kind values.
KINDS = (("read", "Reads"), ("view", "View"), ("create", "Open or create a document"),
         ("modeling", "Modeling"), ("assembly", "Assembly"), ("lifecycle", "File lifecycle"),
         ("history", "History and sketch editing"), ("batch", "Batch"), ("other", "Other"))

# Codes any operation can return from the shared dispatch path, listed once instead of per operation.
# Each must be raised somewhere in src/kurtshape (render checks it), so the list cannot name a dead code.
COMMON_CODES = (
    ("unsupported_operation", "the `op` is not an operation of this build"),
    ("unknown_argument", "the request carries a field the operation does not declare (`fields`)"),
    ("invalid_argument", "a value has the wrong type or range, or a field is missing: `reason` is "
                         "`missing_required` (with `one_of:true` for an empty one-of group) or `missing_conditional`"),
    ("unknown_document", "`document_id` is not the UUID of a document open in this session"),
    ("stale_revision", "`expected_revision` is missing or is not the current revision (`expected`, `actual`)"),
    ("unmanaged_document", "a change to a native file KurtShape does not manage; `adopt` a copy first"),
    ("busy", "another modeling operation is active"),
    ("sketch_edit_active", "a sketch or graphical edit is open; finish or cancel it first"),
    ("unmanaged_transaction", "a native transaction opened outside KurtShape is pending"),
    ("build_failed", "the native recompute failed; the change was rolled back"),
    ("operation_failed", "an unexpected handler error; nothing was committed"),
)

_CODE_TOKEN = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_BRIDGE_CODE = re.compile(r'"code"\s*:\s*"([a-z_]+)"')


def raised_codes(package=ROOT / "src" / "kurtshape"):
    """Every string-literal first argument of OperationError(...) or _error(...), plus bridge JSON codes.

    The rule of tests/test_contract32_conventions.raised_codes, extended to both branches of a
    conditional code (``OperationError("a" if x else "b", ...)``), so the vocabulary is what the code raises.
    """
    codes = set()
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = node.func
            name = function.id if isinstance(function, ast.Name) else getattr(function, "attr", None)
            if name not in ("OperationError", "_error"):
                continue
            first = node.args[0]
            for value in ((first.body, first.orelse) if isinstance(first, ast.IfExp) else (first,)):
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    codes.add(value.value)
    codes.update(_BRIDGE_CODE.findall((package / "bridge.py").read_text(encoding="utf-8")))
    return codes


def dumps(value):
    """JSON with sorted keys at every level; no NaN."""
    return json.dumps(value, sort_keys=True, separators=(", ", ": "), ensure_ascii=False, allow_nan=False)


def request_json(value):
    """A request as one JSON line: op, document_id, expected_revision first, then the other keys sorted.

    Nested requests (batch steps, preview proposals) get the same order; other objects are sorted.
    """
    if isinstance(value, dict):
        head = [key for key in ("op", "document_id", "expected_revision") if key in value and "op" in value]
        keys = head + sorted(key for key in value if key not in head)
        return "{" + ", ".join(json.dumps(key) + ": " + request_json(value[key]) for key in keys) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(request_json(item) for item in value) + "]"
    return dumps(value)


def _scalar(value):
    return value if isinstance(value, str) else dumps(value)


def type_text(schema, depth=0):
    """Short type of a rendered JSON schema: a $defs name, an enum, 'array of ...', alternatives joined by 'or'."""
    if not isinstance(schema, dict):
        return "any"
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return dumps(schema["const"])
    if "enum" in schema:
        return " / ".join(_scalar(value) for value in schema["enum"])
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return " or ".join(type_text(item, depth + 1) for item in schema[key])
    kind = schema.get("type")
    if isinstance(kind, list):
        return " or ".join(kind)
    if kind == "array":
        items = schema.get("items")
        inner = type_text(items, depth + 1) if items is not None and depth < 3 else "any"
        if " " in inner:
            inner = "(" + inner + ")"
        count = ""
        if schema.get("minItems") is not None and schema.get("minItems") == schema.get("maxItems"):
            count = " x " + str(schema["minItems"])
        return "array of " + inner + count
    if kind == "integer" and ("minimum" in schema or "maximum" in schema):
        low, high = schema.get("minimum"), schema.get("maximum")
        return "integer " + ("" if low is None else str(low)) + ".." + ("" if high is None else str(high))
    return kind or "any"


def _names(fields):
    return ", ".join("`" + field + "`" for field in fields)


def default_text(schema):
    if "default" not in schema:
        return ""
    text = "default `" + dumps(schema["default"]) + "`"
    when = schema.get("x-default-when") or {}
    if "present_any" in when:
        text += " when " + ("" if len(when["present_any"]) == 1 else "any of ") + _names(when["present_any"]) + " is given"
    if "absent" in when:
        text += " when " + _names(when["absent"]) + (" is" if len(when["absent"]) == 1 else " are") + " absent"
    if "not_equal" in when:
        text += " unless " + " and ".join("`" + key + "` is `" + dumps(value) + "`"
                                          for key, value in sorted(when["not_equal"].items()))
    return text


def envelope_text(op, classes, schemas):
    document, revision, tracked = schemas.envelope_requirements(op, classes)
    parts = []
    if document:
        parts.append("`document_id`")
    if op in classes["view"]:
        parts.append("`expected_revision` optional (checked when given)")
    elif revision:
        parts.append("`expected_revision`")
    if tracked and "request_id" not in schemas.OPERATIONS[op]["fields"]:
        parts.append("`request_id` (bridge)")
    return ", ".join(parts) if parts else "none"


def _refs(value, found):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                found.add(item.rsplit("/", 1)[-1])
            else:
                _refs(item, found)
    elif isinstance(value, list):
        for item in value:
            _refs(item, found)
    return found


def operation_codes(body, defs, vocabulary, excluded):
    """Error codes the operation's schema names: handler checks, constraints, descriptions and its types."""
    names, pending = set(), _refs(body["request"]["properties"], set())
    while pending:
        name = pending.pop()
        if name in names or name not in defs:
            continue
        names.add(name)
        pending |= _refs(defs[name], set())
    # The envelope's op const is the operation's own name, which may also be a code (duplicate_feature): skip it.
    properties = {name: value for name, value in body["request"]["properties"].items() if name != "op"}
    text = [dumps(properties), dumps(body["constraints"]), dumps(body["x-required-when"]),
            dumps(body["checked_by_handler"])]
    text.extend(dumps(defs[name]) for name in sorted(names))
    return sorted((set(_CODE_TOKEN.findall("\n".join(text))) & vocabulary) - excluded)


def _sentence(text):
    text = text.strip()
    return text if text.endswith((".", "?", "!")) else text + "."


def _header(add, built, operations):
    add("# Operation reference")
    add("")
    add("> **Generated file; do not edit.** Rendered from `src/kurtshape/operation_schemas.py` by "
        "`tools/generate_operations_doc.py`. Regenerate from the checkout root with")
    add("> `" + REGENERATE + "`.")
    add("> `tests/test_operations_doc.py` fails when this file and the schema disagree.")
    add("")
    add("One entry per operation of this build ({} operations, schema version {}, schema digest `{}`): "
        "summary, envelope, arguments, one runnable example and the error codes the schema names. "
        "Behaviour, response shapes and history are in [OPERATION_CONTRACT.md](OPERATION_CONTRACT.md); "
        "worked modeling recipes in [COOKBOOK.md](COOKBOOK.md). A running build answers "
        "`{{\"op\": \"operation_schema\"}}` with the full JSON schema this page summarises (argument "
        "descriptions, constraints, every example).".format(len(operations), built["schema_version"],
                                                            built["digest"][:16]))
    add("")
    add("## Reading an entry")
    add("")
    add("- **Envelope** lists the request fields besides the arguments. `document_id` comes from `new`, "
        "`open`, `inspect` or `list_documents`; `expected_revision` is the `revision` of the latest response "
        "for that document; `request_id` (bridge) is required through the bridge for retry identity and "
        "optional headless (`tools/assistant_client.py` adds one). Every operation also accepts `measure` "
        "(`false`, `true` or `\"full\"`; default `true`), the measurement level of the returned inspection.")
    add("- **Arguments** are sorted by name. *required* means the request is meaningless without it; a "
        "*one of* group needs at least one of its fields; *required when* depends on the mode. A default that "
        "applies only in one mode says when. Types name the shared definitions under [Types](#types).")
    add("- **Example** is the schema's first example; the native suite runs it on the named fixture (after "
        "the listed setup requests). Values in angle brackets are placeholders.")
    add("- **Schema-named errors** are only the codes this operation's schema text names (handler checks, "
        "constraints, argument and type descriptions). The list is not exhaustive: handlers raise other codes "
        "too (for example `empty_cut`, `empty_add` or `invalid_geometry` from result checks, or path errors from "
        "`save`). Every operation can also return the [common codes](#common-error-codes); see the contract's "
        "[error-code table](OPERATION_CONTRACT.md#326-error-codes) and its per-operation sections.")


def _shared(add, built):
    defs = built["$defs"]
    add("")
    add("## Types")
    add("")
    for name in sorted(defs):
        schema = defs[name]
        unit = schema.get("x-unit")
        description = schema.get("description")
        add("- `" + name + "`" + (" (" + unit + ")" if unit else "") + ": "
            + (_sentence(description) if description else type_text(schema) + "."))
    add("")
    add("## Example fixtures and placeholders")
    add("")
    for name in sorted(built["x-example-fixtures"]):
        add("- Fixture `" + name + "`: " + _sentence(built["x-example-fixtures"][name]["description"]))
    for name in sorted(built["x-example-placeholders"]):
        add("- `" + name + "`: " + _sentence(built["x-example-placeholders"][name]))
    add("")
    add("## Common error codes")
    add("")
    add("Clients match on `error.code`, never on the message.")
    add("")
    for code, meaning in COMMON_CODES:
        add("- `" + code + "`: " + meaning + ".")
    add("")
    add("Bridge and client outcomes (`invalid_request`, `queue_full`, `outcome_unknown`, `request_pending`, "
        "`outcome_pending`, ...) are transport results, not operation errors; see the contract's "
        "[client reconciliation](OPERATION_CONTRACT.md#325-identity-schemas-lifecycle-compact-inspect-transport-client).")


def traits(op, body, classes, schemas):
    """'Envelope: ...; undoable, previewable, batchable' for one operation."""
    flags = [label if body[flag] else "not " + label
             for flag, label in (("undoable", "undoable"), ("preview", "previewable"), ("batch", "batchable"))]
    return "Envelope: " + envelope_text(op, classes, schemas) + "; " + ", ".join(flags) + "."


def section_traits(ops, operations, classes, schemas):
    """The traits most operations of a section share (ties: the alphabetically first)."""
    counts = {}
    for op in ops:
        text = traits(op, operations[op], classes, schemas)
        counts[text] = counts.get(text, 0) + 1
    return min(counts, key=lambda text: (-counts[text], text))


def doc_labels(schemas, operations):
    """Short reference-link labels for the contract anchors the operations cite."""
    labels = {}
    for name in sorted(vars(schemas)):
        value = getattr(schemas, name)
        if name.startswith("DOC_") and isinstance(value, str):
            labels.setdefault(value, "contract-" + name[4:].lower().replace("_", "-"))
    unnamed = sorted({body["doc"] for body in operations.values()} - set(labels))
    for index, value in enumerate(unnamed, 1):
        labels[value] = "contract-" + str(index)
    return labels


def _entry(add, op, body, entry, shared, labels, codes, schemas, classes):
    properties = body["request"]["properties"]
    add("")
    add("### " + op)
    add("")
    line = _sentence(body["summary"]) + " [Contract][" + labels[body["doc"]] + "]."
    if shared:
        line += " " + shared
    add(line)
    add("")
    one_of = {}
    for group in body["requires_one_of"]:
        for field in group:
            one_of.setdefault(field, []).append([other for other in group if other != field])
    if not entry["fields"]:
        add("- No arguments.")
    for name in sorted(entry["fields"]):
        schema = properties[name]
        notes = []
        if name in entry["required"]:
            notes.append("**required**" + (" (missing: `" + body["checked_by_handler"][name] + "`)"
                                           if name in body["checked_by_handler"] else ""))
        for others in one_of.get(name, ()):
            notes.append("**one of** this or " + _names(others))
        if name in body["x-required-when"]:
            notes.append("required when " + body["x-required-when"][name])
        if default_text(schema):
            notes.append(default_text(schema))
        if "x-default-id" in schema:
            notes.append("id `" + schema["x-default-id"] + "` when omitted")
        add("- `" + name + "`: " + type_text(schema) + ("; " + "; ".join(notes) if notes else ""))
    add("")
    if body["examples"]:
        fixtures = entry.get("x-example-fixtures") or [body["x-example-fixture"]]
        setup = body.get("x-example-setup") or []
        context = "fixture `" + fixtures[0] + "`"
        if setup:
            context += ", after " + "; ".join("`" + request_json(request) + "`" for request in setup)
        add("Example (" + context + "): `" + request_json(body["examples"][0]) + "`")
    else:
        # Not invented: only the envelope the schema derives, labelled as untested.
        add("No schema example (none runs on the fixtures); the bare request is `"
            + request_json(schemas._example(op, {"op": op}, classes)) + "`")
    if codes:
        add("")
        add("Schema-named errors: " + ", ".join("`" + code + "`" for code in codes) + ".")


def render(controller_cls=None):
    """The whole OPERATIONS.md text, LF line endings."""
    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    from kurtshape import operation_schemas as schemas
    if controller_cls is None:
        from kurtshape.core import Controller as controller_cls
    built = schemas.build(controller_cls)
    classes = schemas._classes(controller_cls)
    operations = built["operations"]
    vocabulary = raised_codes()
    common = {code for code, _ in COMMON_CODES}
    if common - vocabulary:
        raise LookupError("COMMON_CODES names codes src/kurtshape never raises: " + ", ".join(sorted(common - vocabulary)))
    labels = doc_labels(schemas, operations)
    groups = {}
    for op in sorted(operations):
        groups.setdefault(operations[op]["kind"], []).append(op)
    unknown = sorted(set(groups) - {key for key, _ in KINDS})
    if unknown:
        raise LookupError("operation kinds without a section: " + ", ".join(unknown))

    out = []
    add = out.append
    _header(add, built, operations)
    _shared(add, built)
    add("")
    add("## Index")
    add("")
    for key, title in KINDS:
        if groups.get(key):
            add("- **" + title + ":** " + ", ".join("[" + op + "](#" + op + ")" for op in groups[key]))
    for key, title in KINDS:
        if not groups.get(key):
            continue
        usual = section_traits(groups[key], operations, classes, schemas)
        add("")
        add("## " + title)
        add("")
        add("Unless an entry says otherwise: " + usual[0].lower() + usual[1:])
        for op in groups[key]:
            body = operations[op]
            own = traits(op, body, classes, schemas)
            _entry(add, op, body, schemas.OPERATIONS[op], "" if own == usual else own, labels,
                   operation_codes(body, built["$defs"], vocabulary, common), schemas, classes)
    add("")
    cited = sorted({body["doc"] for body in operations.values()}, key=lambda value: labels[value])
    for value in cited:
        add("[" + labels[value] + "]: " + value.removeprefix("docs/"))
    add("")
    return "\n".join(out)


def _isolated_rerun(arguments):
    session = ROOT / "runtime" / "test-tmp" / "operations-doc"
    env = dict(os.environ)
    for name, child in (("FREECAD_USER_HOME", "user-data"), ("APPDATA", "appdata"), ("LOCALAPPDATA", "localappdata"),
                        ("TEMP", "temporary"), ("TMP", "temporary")):
        (session / child).mkdir(parents=True, exist_ok=True)
        env[name] = str(session / child)
    env.update(KURTSHAPE_SESSION_DIR=str(session), PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
    (session / "settings.json").write_text(json.dumps({"project_roots": [str(session)]}), encoding="utf-8")
    process = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve())] + list(arguments), cwd=ROOT,
                             env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if sys.stdout is not None:
        sys.stdout.write(process.stdout + process.stderr)
    return process.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render docs/OPERATIONS.md from operation_schemas.py")
    parser.add_argument("--check", action="store_true", help="compare with the file on disk; exit 1 on drift")
    arguments = sys.argv[1:] if argv is None else list(argv)
    options = parser.parse_args(arguments)
    if not os.environ.get("KURTSHAPE_SESSION_DIR"):
        return _isolated_rerun(arguments)
    data = render().encode("utf-8")
    if options.check:
        # A Windows checkout with core.autocrlf may hold the file with CRLF; the content is what counts.
        current = OUTPUT.read_bytes().replace(b"\r\n", b"\n") if OUTPUT.exists() else b""
        if current != data:
            print("docs/OPERATIONS.md is out of date; regenerate it")
            return 1
        print("docs/OPERATIONS.md is current ({} bytes)".format(len(data)))
        return 0
    OUTPUT.write_bytes(data)
    print("wrote docs/OPERATIONS.md ({} bytes)".format(len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
