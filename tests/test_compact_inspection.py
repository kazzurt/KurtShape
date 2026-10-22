"""Contract 3.2 U2c: compact, focused inspection (F5 §5).

Compact mode returns the status header with part rows and only the selected feature rows,
never computes geometry unless ``measure`` is explicit, and shares the full inspection's
status path (sync), so its revision equals the full inspection's after a native edit.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller, native_feature_summary

HEADER_KEYS = {"document_id", "revision", "name", "native_file", "modified", "modified_basis", "unsaved", "managed",
               "build_status", "rebuild_reason", "build_errors", "geometry_check", "active_sketch_edit", "detail", "studio",
               "result_checks"}  # result_checks: U3
FEATURE_ROW_KEYS = {"id", "name", "type", "state", "history_index", "rolled_back", "part", "output_parts", "parameters",
                    "expressions", "depends_on", "used_by", "affects", "reference_health", "result_check"}  # result_check: U3
PART_ROW_KEYS = {"id", "name", "body", "tip", "visible", "color", "build_status", "geometry_check", "features",
                 "reference_issues", "measurements", "result_check", "geometry_state"}  # the last two: U3
# The 3.1 full-inspection keys plus the three contract 3.2 lifecycle fields (U2b).
FULL_KEYS_31 = {"document_id", "revision", "name", "native_file", "units", "build_status", "build_errors", "features",
                "rebuild_reason", "geometry_check", "measurements", "retained_geometry_measurements", "last_failed_attempt",
                "active_sketch_edit", "managed", "unsupported_objects", "bodies", "import_source", "assembly", "studio",
                "operations"}
NEW_FULL_KEYS = {"modified", "modified_basis", "unsaved", "result_checks",  # U2b; result_checks: U3
                 "parameter_set", "parameters"}  # U5 (other_parameter_sets only when present)


class CompactInspectionTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="compact-inspection-")
        self.core = Controller()
        self.state = None
        self.new("Compact")

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def new(self, name):
        response = self.core.dispatch({"op": "new", "name": name})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def request(self, op, **args):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **args})

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "revision" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def compact(self, **args):
        response = self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"], **args})
        self.assertTrue(response["ok"], response)
        return response["result"]

    def reject(self, code, **args):
        response = self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"], **args})
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        return response["error"]

    def studio_model(self):
        """Body: Base → Plate (new) → Boss sketch → Boss (add) → Fillet; a second part Tool with its own pad."""
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Plate", profile="Base", length=10, operation="new")
        self.call("sketch_rectangle", id="BossProfile", x=5, y=5, width=5, height=5)
        self.call("pad", id="Boss", profile="BossProfile", length=15, operation="add", merge_scope="auto")
        self.call("fillet", id="Round", radius=1, edges=[{"kind": "closest", "point": [7.5, 5, 15],
                                                          "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}])
        self.call("create_body", id="Tool", name="Tool")
        self.call("sketch_rectangle", id="ToolProfile", body="Tool", x=30, y=0, width=5, height=5)
        self.call("pad", id="ToolPad", profile="ToolProfile", body="Tool", length=4, operation="new")

    # ---------------------------------------------------------------------------------

    def test_default_inspect_unchanged_except_new_fields(self):
        self.studio_model()
        full = self.call("inspect")
        self.assertEqual(set(full) - {"created_feature", "operation_ms"}, FULL_KEYS_31 | NEW_FULL_KEYS)
        self.assertNotIn("detail", full)
        for row in full["features"]:
            oracle = native_feature_summary(self.doc.getObject(row["id"]))
            oracle["dependencies"] = sorted(oracle["dependencies"])
            compared = {key: value for key, value in row.items() if key in oracle}
            compared["dependencies"] = sorted(compared["dependencies"])
            # helper rows are appended to the owner's health by _helper_reference_health
            compared["reference_health"] = [entry for entry in compared["reference_health"] if "native_feature" not in entry]
            self.assertEqual(compared, oracle, row["id"])
        self.assertEqual(self.compact(detail="full")["features"], full["features"])

    def test_compact_without_selection_is_an_overview(self):
        self.studio_model()
        full = self.call("inspect")
        overview = self.compact(detail="compact")
        self.assertEqual(set(overview) - {"operation_ms"}, HEADER_KEYS | {"history", "parts"})
        self.assertEqual(overview["detail"], "compact")
        for key in ("document_id", "revision", "name", "build_status", "rebuild_reason", "build_errors", "geometry_check",
                    "active_sketch_edit", "managed", "modified", "modified_basis", "unsaved"):
            self.assertEqual(overview[key], full[key], key)
        self.assertEqual(overview["studio"], {"enabled": True, "rollback_index": full["studio"]["rollback_index"],
                                              "history_count": len(full["studio"]["feature_order"])})
        self.assertEqual(overview["history"]["ids"], full["studio"]["feature_order"])
        self.assertEqual(overview["history"]["rolled_back"], [])
        self.assertEqual([row["id"] for row in overview["parts"]], [part["id"] for part in full["studio"]["parts"]])
        for row in overview["parts"]:
            self.assertEqual(set(row), PART_ROW_KEYS)
            self.assertIsNone(row["measurements"])
        self.call("rollback", index=3)
        overview = self.compact(detail="compact")
        self.assertEqual(overview["history"]["rollback_index"], 3)
        self.assertEqual(overview["history"]["rolled_back"], overview["history"]["ids"][3:])
        self.assertTrue(overview["history"]["rolled_back"])

    def test_compact_feature_rows_report_parameters_dependencies_affects_and_health(self):
        self.studio_model()
        full = {row["id"]: row for row in self.call("inspect")["features"]}
        result = self.compact(features=["Base"])
        self.assertEqual(set(result) - {"operation_ms"}, HEADER_KEYS | {"features"})
        self.assertNotIn("parts", result, "part rows only when parts is given")
        rows = {row["id"]: row for row in result["features"]}
        self.assertEqual(list(rows), ["Base"])
        base = rows["Base"]
        self.assertEqual(set(base), FEATURE_ROW_KEYS)
        self.assertEqual(base["affects"], ["Plate", "Boss", "Round"], "history order, helpers mapped to their operation")
        self.assertEqual(base["used_by"], ["Plate"])
        self.assertEqual(base["depends_on"], [])
        self.assertEqual(base["parameters"], full["Base"]["parameters"])
        self.assertEqual(base["expressions"], full["Base"]["expressions"])
        self.assertEqual(base["reference_health"], full["Base"]["reference_health"])
        self.assertEqual((base["history_index"], base["rolled_back"], base["part"], base["output_parts"]), (0, False, "Body", []))
        # a studio Remove: its row carries the helper health rows exactly as the full row does
        self.call("sketch_circle", id="Hole", body="Body", x=15, y=15, diameter=2)
        self.call("pocket", id="Cut", profile="Hole", body="Body", length=3, through_all=False, reversed=False, operation="remove")
        full = {row["id"]: row for row in self.call("inspect")["features"]}
        cut = {row["id"]: row for row in self.compact(features=["Cut", "Boss"])["features"]}
        self.assertEqual(list(cut), ["Boss", "Cut"], "selected rows come in history order")
        self.assertEqual(cut["Cut"]["reference_health"], full["Cut"]["reference_health"])
        self.assertEqual(cut["Cut"].get("reference_consumers"), full["Cut"].get("reference_consumers"))
        self.assertEqual(cut["Cut"]["output_parts"], ["Body"])
        # The documented mapping: raw links become history features (a hidden helper counts as its
        # operation), in history order, never the feature itself, Bodies or origins.
        order = {name: index for index, name in enumerate(self.call("inspect")["studio"]["feature_order"])}

        def mapped(objects, exclude):
            names = set()
            for obj in objects:
                owner = obj.Name if obj.Name in order else getattr(obj, "KurtShapeOperationOwner", "")
                if owner in order and owner != exclude:
                    names.add(owner)
            return sorted(names, key=order.__getitem__)
        for name, row in cut.items():
            obj = self.doc.getObject(name)
            self.assertEqual(row["depends_on"], mapped(obj.OutList, name), name)
            self.assertEqual(row["used_by"], mapped(obj.InList, name), name)
            self.assertEqual(row["affects"], mapped(obj.InListRecursive, name), name)
            self.assertNotIn(name, row["affects"])
        self.assertIn("Cut", cut["Boss"]["affects"], "the Remove consumes the part the Add produced")
        with_parts = self.compact(features=["Cut"], parts=["Body"])
        self.assertEqual([row["id"] for row in with_parts["parts"]], ["Body"])

    def test_parts_only_selection_returns_owned_and_output_features(self):
        self.studio_model()
        result = self.compact(parts=["Tool"])
        self.assertEqual(set(result) - {"operation_ms"}, HEADER_KEYS | {"features", "parts"})
        self.assertEqual([row["id"] for row in result["parts"]], ["Tool"])
        self.assertEqual([row["id"] for row in result["features"]], ["ToolProfile", "ToolPad"])
        body = self.compact(parts=["Body"])
        self.assertEqual([row["id"] for row in body["features"]], ["Base", "Plate", "BossProfile", "Boss", "Round"])
        both = self.compact(parts=["Tool", "Body"])
        self.assertEqual([row["id"] for row in both["parts"]], ["Tool", "Body"], "part rows follow the request order")
        self.assertEqual([row["id"] for row in both["features"]], ["Base", "Plate", "BossProfile", "Boss", "Round", "ToolProfile", "ToolPad"])
        by_body_name = self.compact(parts=[self.doc.Tool.Name])
        self.assertEqual([row["id"] for row in by_body_name["parts"]], ["Tool"])

    def test_part_rows_summarise_features_and_reference_issues(self):
        self.studio_model()
        full = self.call("inspect")
        row = next(part for part in self.compact(detail="compact")["parts"] if part["id"] == "Body")
        self.assertEqual(row["features"], ["Base", "Plate", "BossProfile", "Boss", "Round"])
        self.assertEqual(row["reference_issues"], {"count": 0, "features": []})
        self.assertEqual(row["tip"], self.doc.getObject(row["body"]).Tip.Name)
        self.assertEqual(row["build_status"], full["build_status"])
        self.assertEqual(row["geometry_check"], "not_checked")
        self.assertEqual((row["name"], row["visible"], len(row["color"])), ("Body", True, 3))
        # A radius-filtered multi reference loses every match when the hole grows natively (outside a
        # managed transaction), which sync reports as an unresolved reference until a managed rebuild.
        self.call("sketch_circle", id="Hole", body="Body", x=15, y=15, diameter=3)
        self.call("pocket", id="Cut", profile="Hole", body="Body", through_all=True, operation="remove")
        self.call("fillet", id="RoundHole", part="Body", radius=0.3, edges=[{"selector": {"kind": "geometry", "geometry": "circle", "radius": 1.5,
                  "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}, "all": True}])
        row = next(part for part in self.compact(detail="compact")["parts"] if part["id"] == "Body")
        self.assertEqual(row["reference_issues"], {"count": 0, "features": []})
        hole = self.doc.getObject("Hole")
        index = next(i for i, c in enumerate(hole.Constraints) if c.Name == "Diameter")
        self.doc.openTransaction("native edit")
        hole.setDatum(index, App.Units.Quantity("4 mm"))
        self.doc.recompute()
        self.doc.commitTransaction()
        full = self.call("inspect")
        flagged = [entry for entry in next(r for r in full["features"] if r["id"] == "RoundHole")["reference_health"]
                   if entry.get("status") != "healthy"]
        self.assertTrue(flagged, "the grown hole leaves the fillet's radius-filtered selector without a match")
        row = next(part for part in self.compact(detail="compact")["parts"] if part["id"] == "Body")
        self.assertEqual(row["reference_issues"], {"count": len(flagged), "features": ["RoundHole"]})
        self.assertIn("RoundHole", row["features"])

    def test_compact_measure_only_when_explicit(self):
        self.studio_model()
        row = next(part for part in self.compact(detail="compact")["parts"] if part["id"] == "Body")
        self.assertIsNone(row["measurements"])
        row = next(part for part in self.compact(detail="compact", measure=False)["parts"] if part["id"] == "Body")
        self.assertEqual(row["measurements"]["solid_count"], 1)
        self.assertIsNone(row["measurements"]["volume_mm3"])
        row = next(part for part in self.compact(detail="compact", measure=True)["parts"] if part["id"] == "Body")
        full = self.call("inspect", measure=True)
        self.assertAlmostEqual(row["measurements"]["volume_mm3"], full["bodies"][0]["measurements"]["volume_mm3"])
        self.assertIsNone(row["measurements"]["center_of_mass_mm"])
        row = next(part for part in self.compact(detail="compact", measure="full")["parts"] if part["id"] == "Body")
        self.assertIsNotNone(row["measurements"]["center_of_mass_mm"])
        self.reject("invalid_argument", detail="compact", measure=None)

    def test_compact_never_computes_geometry(self):
        self.studio_model()
        self.core.inspect(self.doc, False)  # settle the cheap caches
        before = dict(self.core.geometry.stats["computed"])
        original = type(self.core.geometry).check

        def check(cache, obj, compute=False):
            self.assertFalse(compute, "compact inspection must not run BRepCheck")
            return original(cache, obj, compute)
        with patch.object(type(self.core.geometry), "check", check):
            self.compact(detail="compact")
            self.compact(features=["Round", "Base"])
            self.compact(parts=["Body", "Tool"])
            self.core.dispatch({"op": "list_documents", "detail": "compact"})
        self.assertEqual(self.core.geometry.stats["computed"], before, "no measurement or check was computed")
        timings = self.core.timings.report()
        self.assertIn("inspection_compact", timings)

    def test_compact_inspection_of_an_unmanaged_document(self):
        self.core.settings.roots.add(self.folder)
        native = App.newDocument("Reference")
        native.addObject("PartDesign::Body", "Body")
        box = native.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 5
        native.recompute()
        path = self.folder / "reference.FCStd"
        native.saveAs(str(path))
        App.closeDocument(native.Name)
        response = self.core.dispatch({"op": "open", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertFalse(self.state["managed"])
        overview = self.compact(detail="compact")
        self.assertEqual((overview["detail"], overview["managed"]), ("compact", False))
        self.assertEqual(overview["history"]["ids"], [], "a plain file has no managed history")
        self.assertEqual([row["id"] for row in overview["parts"]], ["Body"])
        self.assertEqual(set(overview["parts"][0]), PART_ROW_KEYS)
        self.assertEqual(overview["parts"][0]["features"], [])
        selected = self.compact(detail="compact", parts=["Body"])
        self.assertEqual(([row["id"] for row in selected["parts"]], selected["features"]), (["Body"], []))
        rows = self.core.dispatch({"op": "list_documents", "detail": "compact"})["result"]["documents"]
        row = next(entry for entry in rows if entry["document_id"] == self.state["document_id"])
        self.assertEqual((row["feature_count"], row["part_count"]), (0, 1))
        # an explicit null selection is absent, like every other null argument in 3.2
        self.assertNotIn("history", self.compact(features=None, parts=None))
        full = self.compact(detail="full", features=None)
        self.assertTrue(FULL_KEYS_31 <= set(full) and "detail" not in full, "full mode is the 3.1 shape")

    def test_compact_rejects_unknown_ids_bad_detail_and_full_with_selection(self):
        self.studio_model()
        before = (self.state["revision"], self.doc.UndoCount)
        self.reject("invalid_argument", detail="x")
        self.reject("invalid_argument", detail="full", features=["Base"])
        self.reject("invalid_argument", detail="full", parts=["Body"])
        self.reject("invalid_argument", features="Base")
        self.reject("invalid_argument", features=["Base", "Base"])
        self.reject("invalid_argument", parts=[5])
        error = self.reject("missing_reference", features=["Base", "NoSuch", "Other"])
        self.assertEqual(error["features"], ["NoSuch", "Other"])
        error = self.reject("missing_part", parts=["Body", "Nope"])
        self.assertEqual(error["parts"], ["Nope"])
        self.assertEqual(self.core.dispatch({"op": "list_documents", "detail": "both"})["error"]["code"], "invalid_argument")
        self.assertEqual(self.core.dispatch({"op": "list_documents", "features": ["Base"]})["error"]["code"], "unknown_argument")
        self.assertEqual((self.core._meta(self.doc).Revision, self.doc.UndoCount), before)
        self.assertIsNone(self.call("inspect")["last_failed_attempt"], "reads record no failed attempt")

    def test_list_documents_compact_rows(self):
        self.studio_model()
        first = self.state["document_id"]
        self.new("Second")
        self.call("sketch_rectangle", id="Only", width=5, height=5)
        rows = self.core.dispatch({"op": "list_documents", "detail": "compact"})["result"]["documents"]
        self.assertEqual({row["document_id"] for row in rows}, {first, self.state["document_id"]})
        for row in rows:
            self.assertEqual(set(row), HEADER_KEYS | {"feature_count", "part_count"})
            self.assertEqual(row["detail"], "compact")
        by_id = {row["document_id"]: row for row in rows}
        self.assertEqual((by_id[first]["feature_count"], by_id[first]["part_count"]), (7, 2))
        self.assertEqual((by_id[self.state["document_id"]]["feature_count"], by_id[self.state["document_id"]]["part_count"]), (1, 1))
        full = self.core.dispatch({"op": "list_documents", "detail": "full", "measure": False})["result"]["documents"]
        self.assertEqual({row["document_id"] for row in full}, {first, self.state["document_id"]})
        self.assertIn("features", full[0])

    def test_compact_revision_matches_full_after_native_edit(self):
        self.studio_model()
        revision = self.state["revision"]
        base = self.doc.getObject("Base")
        index = next(i for i, c in enumerate(base.Constraints) if c.Name == "Width")
        self.doc.openTransaction("native edit")
        base.setDatum(index, App.Units.Quantity("22 mm"))
        self.doc.recompute()
        self.doc.commitTransaction()
        compact = self.compact(detail="compact")
        self.assertNotEqual(compact["revision"], revision, "sync rotates the revision after a native edit")
        full = self.call("inspect")
        self.assertEqual(compact["revision"], full["revision"])
        self.assertEqual(self.compact(detail="compact")["revision"], full["revision"])
