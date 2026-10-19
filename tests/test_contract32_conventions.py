"""Contract 3.2 shared conventions (integration plan §3): identity, operation classes, error-code
registry and the OPERATION_CONTRACT layout.

Each unit appends its new error codes to NEW_CODES and to the §3.2.6 table. The
registry test scans the OperationError literals under src/kurtshape and insists
every registered code is both raised and documented.
"""
import ast
from pathlib import Path
import re
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape import contract
from kurtshape.core import Controller

CONTRACT_DOC = ROOT / "docs" / "OPERATION_CONTRACT.md"
SECTION = "## Contract 3.2"
SUBSECTIONS = ("3.2.0", "3.2.1", "3.2.2", "3.2.3", "3.2.4", "3.2.5", "3.2.6", "3.2.7")
# Error codes contract 3.2 introduces, appended by the unit that raises them (§3.4).
NEW_CODES = (
    # U2b: lifecycle refusals (close_document) and the discard checkpoint failure
    "unsaved_changes", "document_in_use", "user_editing", "checkpoint_failed",
    # U2d: bridge transport (raised in bridge.py as JSON bodies, not OperationError)
    "invalid_request", "queue_full",
    # U4: render_view (owner-thread refusals, the render service and the worker's codes)
    "no_geometry", "missing_input", "highlight_no_match", "highlight_not_rendered", "too_many_highlight_matches",
    "section_misses_parts", "render_busy", "render_too_large", "render_capture_changed", "render_timeout",
    "render_failed", "render_cancelled", "document_closed",
    # U5: model parameters
    "invalid_parameter_name", "duplicate_parameter", "unit_mismatch", "expression_cycle", "bind_values_differ",
    "invalid_parameter_set", "parameter_not_applied", "missing_parameter", "parameter_in_use", "rename_failed",
    # U6: atomic batches
    "invalid_step_reference", "request_too_large", "batch_time_budget_exceeded", "transaction_split",
)
# Operations outside the READ/VIEW/MODEL/CREATE/ASSEMBLY/LIFECYCLE classes (§3.2).
OTHER_OPS = frozenset({"batch", "adopt", "begin_sketch_edit", "finish_sketch_edit", "undo", "redo", "save", "export"})
ERROR_CALLS = {"OperationError", "_error"}
# Codes the bridge sends as JSON bodies (no OperationError): {"code": "..."} literals in bridge.py.
BRIDGE_CODE_PATTERN = re.compile(r'"code"\s*:\s*"([a-z_]+)"')


def raised_codes(package=ROOT / "src" / "kurtshape"):
    """Every string-literal code passed first to OperationError(...) or a module's _error(...)."""
    codes = {}
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = node.func
            name = function.id if isinstance(function, ast.Name) else getattr(function, "attr", None)
            first = node.args[0]
            if name in ERROR_CALLS and isinstance(first, ast.Constant) and isinstance(first.value, str):
                codes.setdefault(first.value, set()).add(path.name)
    for code in BRIDGE_CODE_PATTERN.findall((package / "bridge.py").read_text(encoding="utf-8")):
        codes.setdefault(code, set()).add("bridge.py")
    return codes


def contract_section():
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    start = text.index(SECTION)
    rest = text[start + len(SECTION):]
    match = re.search(r"^## ", rest, flags=re.MULTILINE)
    return text[start:start + len(SECTION) + (match.start() if match else len(rest))]


class Contract32ConventionTests(unittest.TestCase):
    def test_contract_identity_is_3_2(self):
        self.assertEqual((contract.CONTRACT_VERSION, contract.CONTRACT_REVISION), (3, 2))
        self.assertEqual(contract.REQUEST_SIZE_LIMIT, 65536)
        core = Controller()
        try:
            capabilities = core.dispatch({"op": "capabilities"})["result"]
        finally:
            core.close()
        self.assertEqual((capabilities["contract"], capabilities["contract_revision"]), (3, 2))
        self.assertEqual(capabilities["request_size_limit_bytes"], contract.REQUEST_SIZE_LIMIT)
        for module in ("core.py", "bridge.py"):
            source = (ROOT / "src" / "kurtshape" / module).read_text(encoding="utf-8")
            self.assertNotIn("65536", source, module + " must read the shared REQUEST_SIZE_LIMIT")

    def test_every_operation_is_in_exactly_one_class(self):
        classes = {"READ_OPS": Controller.READ_OPS, "VIEW_OPS": Controller.VIEW_OPS, "MODEL_OPS": Controller.MODEL_OPS,
                   "CREATE_OPS": Controller.CREATE_OPS, "ASSEMBLY_OPS": Controller.ASSEMBLY_OPS,
                   "LIFECYCLE_OPS": Controller.LIFECYCLE_OPS, "other": OTHER_OPS}
        for op in sorted(Controller.OPS):
            owners = [name for name, members in classes.items() if op in members]
            self.assertEqual(len(owners), 1, (op, owners))
        for name, members in classes.items():
            if name != "other":
                self.assertLessEqual(members, Controller.OPS, name)
        self.assertEqual(Controller.NON_MUTATING_OPS, frozenset(Controller.READ_OPS) | Controller.VIEW_OPS)
        self.assertLessEqual(Controller.QUIET_OPS, Controller.NON_MUTATING_OPS)
        self.assertLessEqual(Controller.DOCUMENTLESS_OPS, Controller.NON_MUTATING_OPS)
        self.assertFalse({"check_geometry", "preview", "assembly_candidates"} & Controller.QUIET_OPS)
        self.assertEqual(Controller.TRANSPORT_FIELDS, frozenset({"document_id", "expected_revision", "request_id", "measure"}))
        # request_status looks a request_id up, so that name is its one argument.
        for op in Controller.OPS - {"request_status"}:
            self.assertFalse(Controller.ARGS[op] & Controller.TRANSPORT_FIELDS, op)
        self.assertEqual(Controller.ARGS["request_status"], {"request_id"})
        self.assertIsInstance(Controller.VIEW_OPS, frozenset)
        self.assertIsInstance(Controller.LIFECYCLE_OPS, frozenset)

    def test_transport_fields_are_the_only_tolerated_envelope(self):
        core = Controller()
        try:
            state = core.dispatch({"op": "new", "name": "Envelope"})["result"]
            response = core.dispatch({"op": "inspect", "document_id": state["document_id"],
                                      "expected_revision": state["revision"], "request_id": "r1", "measure": False})
            self.assertTrue(response["ok"], response)
            response = core.dispatch({"op": "inspect", "document_id": state["document_id"], "detail_level": 1})
            self.assertEqual(response["error"]["code"], "unknown_argument")
            self.assertEqual(response["error"]["fields"], ["detail_level"])
        finally:
            for name in list(core.documents.values()):
                if core._is_open(name):
                    App.closeDocument(name.Name)
            core.close()

    def test_new_codes_are_raised_and_documented(self):
        codes = raised_codes()
        self.assertIn("build_failed", codes)
        self.assertIn("invalid_argument", codes)
        table = contract_section()
        self.assertIn("3.2.6", table)
        for code in NEW_CODES:
            with self.subTest(code=code):
                self.assertIn(code, codes, "registered 3.2 code is never raised")
                self.assertRegex(table, r"`" + re.escape(code) + r"`", "registered 3.2 code is not documented in §3.2.6")
        self.assertTrue(all(re.fullmatch(r"[a-z][a-z0-9_]*", code) for code in NEW_CODES), "codes are snake_case")

    def test_operation_contract_has_the_3_2_section_layout(self):
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        self.assertEqual(text.count(SECTION), 1)
        self.assertLess(text.index("## Contract 3.1"), text.index(SECTION), "3.2 follows the 3.1 section")
        section = contract_section()
        for number in SUBSECTIONS:
            self.assertIn("### " + number, section, number)
        self.assertIn("contract_revision:2", section.replace(" ", "").replace("`", ""))
