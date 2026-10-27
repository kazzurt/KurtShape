"""Generated operation reference, cookbook snippets and documentation links (slice A/B, B4).

* ``docs/OPERATIONS.md`` is exactly what ``tools/generate_operations_doc.py`` renders from
  ``operation_schemas`` (so a schema change without regenerating fails here), covers every
  operation and carries no absolute path.
* Every relative link and anchor in the entry-point documents resolves to an existing file and,
  for markdown targets, to a heading.
* Every request in a ``docs/COOKBOOK.md`` snippet names a real operation and only argument names
  its schema declares; selector objects use only their kind's keys.
"""
import ast
import json
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from kurtshape import operation_schemas as schemas
from kurtshape.core import Controller
import generate_operations_doc as generator

LINKED_DOCS = ("README.md", "AGENTS.md", "docs/AGENT_QUICKSTART.md", "docs/COOKBOOK.md", "docs/OPERATIONS.md",
               "docs/history/SHARING_STATUS.md", "docs/DEVELOPMENT_HISTORY.md")
# Operations the cookbook's recipes must show (unit brief: quickstart plus the "how to model" entries).
COOKBOOK_OPS = {"new", "sketch_rectangle", "pad", "check_geometry", "save", "export", "render_view", "create_sketch",
                "add_polyline", "revolve", "fillet", "create_helix", "sweep", "circular_pattern_parts", "pocket", "hole",
                "create_plane", "transform_part", "preview", "batch", "assembly_candidates", "create_assembly",
                "insert_assembly_part", "move_assembly_instance", "inspect"}

_FENCE = re.compile(r"^(```|~~~)([^\n`]*)\n(.*?)^\1[ \t]*$", re.M | re.S)
_INLINE_CODE = re.compile(r"(`+)(.+?)\1", re.S)
_INLINE_LINK = re.compile(r"!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*(<[^>]*>|[^)\s]*)(?:\s+\"[^\"]*\")?\s*\)")
_REFERENCE_USE = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\[([^\[\]]*)\]")
_REFERENCE_DEF = re.compile(r"^ {0,3}\[([^\[\]]+)\]:\s+(<[^>]*>|\S+)", re.M)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$", re.M)
_HTML_ANCHOR = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"", re.I)


def without_code(text):
    """Markdown text with fenced blocks and inline code spans blanked (their links are not links)."""
    text = _FENCE.sub(lambda match: "\n" * match.group(0).count("\n"), text)
    return _INLINE_CODE.sub("", text)


def slug(heading):
    """GitHub heading anchor: link text kept, lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\([^)]*\)", r"\1", heading.strip())
    text = re.sub(r"[^\w\- ]", "", text.lower())
    return text.replace(" ", "-")


def anchors(path):
    """Every anchor a markdown file defines, with GitHub's -1, -2 suffixes for repeated headings."""
    text = path.read_text(encoding="utf-8")
    found, seen = set(_HTML_ANCHOR.findall(text)), {}
    for match in _HEADING.finditer(_FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)):
        base = slug(match.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        found.add(base if count == 0 else base + "-" + str(count))
    return found


def links(path):
    """(target, line) for every inline link, image, used reference definition and bare reference use."""
    text = without_code(path.read_text(encoding="utf-8"))
    definitions = {label.lower(): target for label, target in _REFERENCE_DEF.findall(text)}
    rows = []
    for match in _INLINE_LINK.finditer(text):
        rows.append((match.group(2), text.count("\n", 0, match.start()) + 1))
    for match in _REFERENCE_USE.finditer(text):
        label = (match.group(2) or match.group(1)).lower()
        rows.append((definitions.get(label, "\0undefined reference [" + label + "]"),
                     text.count("\n", 0, match.start()) + 1))
    for target in definitions.values():
        rows.append((target, 0))
    return rows


def snippet_requests(text):
    """(request, context, origin) for every request in the cookbook's fenced JSON and Python blocks."""
    found = []
    for match in _FENCE.finditer(text):
        language, body = match.group(2).strip().lower(), match.group(3)
        origin = "line " + str(text.count("\n", 0, match.start()) + 1)
        if language == "json":
            try:
                values = [json.loads(body)]
            except ValueError:
                values = [json.loads(line) for line in body.splitlines() if line.strip()]
            for value in values:
                found.append((value, "top", origin))
        elif language == "python":
            for node in ast.walk(ast.parse(body)):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "call"
                        and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                    request = {"op": node.args[0].value}
                    request.update({keyword.arg: None for keyword in node.keywords if keyword.arg})
                    found.append((request, "top", origin))
                elif isinstance(node, ast.Dict):
                    keys = [key.value for key in node.keys if isinstance(key, ast.Constant)]
                    op = dict(zip([getattr(key, "value", None) for key in node.keys], node.values)).get("op")
                    if isinstance(op, ast.Constant) and isinstance(op.value, str):
                        request = {key: None for key in keys}
                        request["op"] = op.value
                        found.append((request, "top", origin))
    return found


class OperationsDocTests(unittest.TestCase):
    def test_operations_md_is_regenerated_from_the_schema(self):
        rendered = generator.render(Controller)
        self.assertEqual(rendered, generator.render(Controller), "rendering is not deterministic")
        data = rendered.encode("utf-8")
        # A Windows checkout with core.autocrlf may hold the file with CRLF line endings.
        on_disk = (ROOT / "docs" / "OPERATIONS.md").read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(on_disk, data, "docs/OPERATIONS.md is stale: run tools/generate_operations_doc.py "
                                        "under the bundled pythonw.exe")
        entries = re.findall(r"^### (\S+)$", rendered, re.M)
        self.assertEqual(entries, sorted(entries, key=lambda op: (
            [key for key, _ in generator.KINDS].index(schemas.build(Controller)["operations"][op]["kind"]), op)))
        self.assertEqual(set(entries), set(schemas.OPERATIONS))
        self.assertEqual(len(entries), len(schemas.OPERATIONS))
        self.assertNotIn(str(ROOT), rendered)
        self.assertIsNone(re.search(r"\b[A-Za-z]:[\\/]", rendered), "absolute path in the generated file")
        self.assertIsNone(re.search(r"\b20\d\d-\d\d-\d\d[T ]\d\d:\d\d", rendered), "timestamp in the generated file")
        for op, operation in schemas.build(Controller)["operations"].items():
            with self.subTest(op=op):
                section = rendered.split("\n### " + op + "\n", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
                if operation["examples"]:
                    self.assertIn("Example (fixture `", section)
                    self.assertIn(generator.request_json(operation["examples"][0]), section)
                else:
                    self.assertIn("No schema example", section)
                for name in schemas.OPERATIONS[op]["fields"]:
                    self.assertIn("\n- `" + name + "`: ", section)
                for name in schemas.OPERATIONS[op]["required"]:
                    self.assertRegex(section, r"\n- `" + re.escape(name) + r"`: [^\n]*\*\*required\*\*")

    def test_entry_point_links_and_anchors_resolve(self):
        checked = 0
        for name in LINKED_DOCS:
            path = ROOT / name
            for target, line in links(path):
                with self.subTest(document=name, line=line, target=target):
                    self.assertFalse(target.startswith("\0"), target)
                    target = target.strip("<>")
                    if _SCHEME.match(target):
                        continue
                    checked += 1
                    location, _, anchor = target.partition("#")
                    destination = (path.parent / unquote(location)).resolve() if location else path
                    self.assertTrue(destination.exists(), destination)
                    self.assertTrue(destination.is_relative_to(ROOT), destination)
                    if anchor and destination.suffix.lower() == ".md":
                        self.assertIn(unquote(anchor).lower(), anchors(destination))
        self.assertGreater(checked, 150)

    def test_cookbook_snippets_use_real_operations_and_arguments(self):
        text = (ROOT / "docs" / "COOKBOOK.md").read_text(encoding="utf-8")
        kinds = schemas.build(Controller)["$defs"]["selector"]["x-kinds"]
        seen, count = set(), 0

        def check_request(request, context, origin):
            nonlocal count
            op = request.get("op")
            self.assertIn(op, schemas.OPERATIONS, origin)
            seen.add(op)
            count += 1
            allowed = set(schemas.arg_names(op)) | {"op"}
            if context == "top":
                allowed |= set(schemas.ENVELOPE)
            elif context == "step":
                allowed.add("as")
            self.assertLessEqual(set(request) - allowed, set(), (origin, op))
            for key, value in request.items():
                if op == "batch" and key == "steps":
                    for step in value:
                        check_request(step, "step", origin)
                elif op == "preview" and key == "proposal":
                    check_request(value, "proposal", origin)
                else:
                    check_selectors(value, origin)

        def check_selectors(value, origin):
            if isinstance(value, dict):
                if "kind" in value:
                    self.assertIn(value["kind"], kinds, origin)
                    self.assertLessEqual(set(value), set(kinds[value["kind"]]), (origin, value["kind"]))
                for item in value.values():
                    check_selectors(item, origin)
            elif isinstance(value, list):
                for item in value:
                    check_selectors(item, origin)

        for request, context, origin in snippet_requests(text):
            with self.subTest(origin=origin, op=request.get("op")):
                check_request(request, context, origin)
        self.assertLessEqual(COOKBOOK_OPS, seen)
        self.assertGreaterEqual(count, 30)

    def test_one_launch_rule(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("launching-which-app-an-agent-uses", anchors(ROOT / "AGENTS.md"))
        self.assertEqual(agents.count("## Launching: which app an agent uses"), 1)
        quickstart = (ROOT / "docs" / "AGENT_QUICKSTART.md").read_text(encoding="utf-8")
        self.assertNotIn("Launch KurtShape if it is not already running", quickstart)
        self.assertIn("../AGENTS.md#launching-which-app-an-agent-uses", quickstart)


if __name__ == "__main__":
    unittest.main()
