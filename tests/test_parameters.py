"""Contract 3.2 U5 (F3a): model parameters in one native App::VarSet (ParameterTests, ParameterPruningTests).

Every rejection asserts the revision, the undo count and the native intent signature are unchanged.
The pruning matrix compares each scenario with KURTSHAPE_FULL_PARAMETER_RECOMPUTE=1 (the oracle).
"""
import json
import math
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Sketcher
from kurtshape import parameters
from kurtshape.core import Controller, intent_signature, native_intent


class ParameterFixture:
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="parameters-")
        self.core = Controller()
        self.core.settings.roots.add(self.folder)
        self.state = None
        self.addCleanup(self.close_all)

    def close_all(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    @property
    def vs(self):
        return parameters.parameter_set(self.doc)

    def new(self, name="Parameters"):
        response = self.core.dispatch({"op": "new", "name": name})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]

    def request(self, op, **args):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **args})

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "revision" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def invariant(self):
        doc = self.doc
        return self.core._meta(doc).Revision, doc.UndoCount, intent_signature(doc)

    def reject(self, code, op, **args):
        before = self.invariant()
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        self.assertEqual(self.invariant(), before, "a rejected request changes nothing")
        return response["error"]

    def rows(self, **args):
        return {row["name"]: row for row in self.call("list_parameters", **args)["parameters"]}

    def constraint(self, sketch, name):
        obj = self.doc.getObject(sketch)
        return next(c.Value for c in obj.Constraints if c.Name == name)

    def block(self):
        self.new()
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")

    def shaft_model(self):
        """Section 15 of the spec: a block with a shoulder and a shaft driven by two parameters."""
        self.new("Shaft")
        self.call("create_parameter", name="shaft_diameter", type="length", value=6)
        self.call("create_parameter", name="shoulder_diameter", expression="shaft_diameter + 2 mm")
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")
        self.call("create_plane", id="Top", base_plane="XY", offset=10)
        self.call("create_sketch", id="ShoulderSk", support={"feature": "Top"})
        self.call("add_circle", sketch="ShoulderSk", x=10, y=10, diameter=5)
        self.call("set_expression", feature="ShoulderSk", parameter=self.circle("ShoulderSk"), expression="shoulder_diameter")
        self.call("pad", id="Shoulder", profile="ShoulderSk", length=3, operation="add", merge_scope=["Body"])
        self.call("create_plane", id="Top2", base_plane="XY", offset=13)
        self.call("create_sketch", id="ShaftSk", support={"feature": "Top2"})
        self.call("add_circle", sketch="ShaftSk", x=10, y=10, diameter=5)
        self.call("set_expression", feature="ShaftSk", parameter=self.circle("ShaftSk"), expression="Params.shaft_diameter")
        self.call("pad", id="Shaft", profile="ShaftSk", length=12, operation="add", merge_scope=["Body"])

    def circle(self, sketch):
        """The public name of a sketch's diameter dimension, as inspect reports it."""
        feature = next(row for row in self.call("inspect")["features"] if row["id"] == sketch)
        return next(name for name, info in feature["parameters"].items() if info.get("constraint_type") == "Diameter")

    def dimension(self, sketch, parameter):
        return next(row for row in self.call("inspect")["features"] if row["id"] == sketch)["parameters"][parameter]


class ParameterTests(ParameterFixture, unittest.TestCase):
    def test_types_units_reopen_undo_redo(self):
        self.new()
        created = self.call("create_parameter", name="width", type="length", value=6)
        self.assertEqual(created["created_parameter"], "width")
        self.assertNotIn("created_feature", created, "a parameter is not a feature")
        self.assertEqual(created["parameter_report"]["row"]["used_by_count"], 0)
        self.call("create_parameter", name="tilt", type="angle", value="15 deg")
        self.reject("invalid_parameter_name", "create_parameter", name="count", type="number", value=3)  # count() is a function
        self.call("create_parameter", name="teeth", type="number", value=3)
        rows = self.rows()
        self.assertEqual((rows["width"]["value"], rows["width"]["unit"], rows["width"]["native_unit"]), (6.0, "mm", "mm"))
        self.assertEqual((rows["tilt"]["native_value"], rows["tilt"]["native_unit"]), (15.0, "deg"))
        self.assertAlmostEqual(rows["tilt"]["value"], math.radians(15), places=12)
        self.assertEqual((rows["teeth"]["value"], rows["teeth"]["unit"]), (3.0, ""))
        self.assertEqual(self.vs.Name, "Params")
        self.assertEqual(self.vs.Label, "Params")
        state = self.call("inspect")
        self.assertEqual(state["parameter_set"], {"id": "Params", "label": "Params", "state": "valid", "error": None})
        self.assertEqual([row["name"] for row in state["parameters"]], ["teeth", "tilt", "width"])
        self.assertNotIn("Params", [feature["id"] for feature in state["features"]])
        path = self.folder / "parameters.FCStd"
        self.call("save", path=str(path))
        self.call("close_document")
        self.state = self.core.dispatch({"op": "open", "path": str(path)})["result"]
        self.assertEqual({name: row["native_value"] for name, row in self.rows().items()},
                         {"teeth": 3.0, "tilt": 15.0, "width": 6.0})
        self.assertEqual(self.request("undo")["error"]["code"], "empty_history", "a reopened file has no undo history")
        self.call("edit_parameter", name="width", value=8)
        self.call("undo")
        self.assertEqual(self.rows()["width"]["value"], 6.0)
        self.call("redo")
        self.assertEqual(self.rows()["width"]["value"], 8.0)

    def test_shaft_shoulder_formula_drives_sketch_and_edit_updates_dependents(self):
        self.shaft_model()
        shaft, shoulder = self.circle("ShaftSk"), self.circle("ShoulderSk")
        self.assertEqual(self.dimension("ShoulderSk", shoulder)["expression"], "Params.shoulder_diameter",
                         "bare names are stored qualified")
        result = self.call("edit_parameter", name="shaft_diameter", value=8)
        self.assertAlmostEqual(self.dimension("ShaftSk", shaft)["value"], 8.0)
        self.assertAlmostEqual(self.dimension("ShoulderSk", shoulder)["value"], 10.0)
        report = result["parameter_report"]
        self.assertEqual({(row["name"], row["previous"], row["current"]) for row in report["changed_parameters"]},
                         {("shaft_diameter", 6.0, 8.0), ("shoulder_diameter", 8.0, 10.0)})
        self.assertEqual(sorted(row["feature"] for row in report["changed_inputs"]), ["ShaftSk", "ShoulderSk"])
        self.assertIn("Shaft", report["affected"]["features"])
        self.assertEqual(report["affected"]["parts"], ["Body"])
        self.assertEqual(result["build_status"], "valid")

    def test_name_rules(self):
        self.new()
        self.call("create_parameter", name="width", type="length", value=1)
        for name, code, reason in (("Width", "invalid_parameter_name", "format"), ("_x", "invalid_parameter_name", "format"),
                                   ("kurtshapeThing", "invalid_parameter_name", "reserved"),
                                   ("WIDTH", "invalid_parameter_name", "format"), ("mm", "invalid_parameter_name", None),
                                   ("t", "invalid_parameter_name", None), ("h", "invalid_parameter_name", None),
                                   ("pi", "invalid_parameter_name", "constant"), ("e", "invalid_parameter_name", "constant"),
                                   ("sin", "invalid_parameter_name", "function"),
                                   ("touch", "invalid_parameter_name", "reserved_attribute"),
                                   ("isValid", "invalid_parameter_name", "reserved_attribute"),
                                   ("Name", "invalid_parameter_name", "format"), ("State", "invalid_parameter_name", "format"),
                                   ("TypeId", "invalid_parameter_name", "format"), ("Proxy", "invalid_parameter_name", "format"),
                                   ("QueryInputs", "invalid_parameter_name", "format")):
            with self.subTest(name=name):
                error = self.reject(code, "create_parameter", name=name, type="length", value=1)
                if reason:
                    self.assertEqual(error["reason"], reason)
                else:
                    self.assertIn(error["reason"], {"unit", "expression_token"})
        error = self.reject("duplicate_parameter", "create_parameter", name="wiDTH", type="length", value=1)
        self.assertEqual(error["existing"], "width")
        self.assertTrue(self.call("inspect")["parameters"])

    def test_native_shadowing_name_reports_invalid_parameter_set_and_native_repair_recovers(self):
        self.new()
        self.call("create_parameter", name="zz", type="length", value=3)
        self.vs.renameProperty("zz", "State")
        response = self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"]})
        self.assertEqual(response["error"]["code"], "invalid_parameter_set")
        self.assertEqual(response["error"]["names"], ["State"])
        self.vs.renameProperty("State", "zz")
        self.assertEqual(sorted(self.rows()), ["zz"])

    def test_angle_storage_exact_and_range(self):
        self.new()
        self.call("create_parameter", name="a", type="angle", value="15 deg")
        self.call("create_parameter", name="b", type="angle", value=0.2617993877991494)
        rows = self.rows()
        self.assertEqual((rows["a"]["native_value"], rows["b"]["native_value"]), (15.0, 15.0))
        self.reject("invalid_argument", "create_parameter", name="c", type="angle", value="400 deg")
        self.reject("invalid_expression", "create_parameter", name="c", type="angle", expression="400 deg")
        self.reject("invalid_argument", "edit_parameter", name="a", value="-361 deg")

    def test_unit_matrix(self):
        self.block()
        self.call("create_parameter", name="tilt", type="angle", value="10 deg")
        self.call("create_parameter", name="span", type="length", value=12)
        self.call("create_parameter", name="ratio", type="number", value=2)
        width = "Width" if "Width" in self.call("inspect")["features"][0]["parameters"] else None
        sketch = next(row for row in self.call("inspect")["features"] if row["id"] == "Base")
        width = next(name for name, info in sketch["parameters"].items() if info["unit"] == "mm")
        self.reject("unit_mismatch", "set_expression", feature="Base", parameter=width, expression="tilt")
        self.call("set_expression", feature="Base", parameter=width, expression="ratio * 10")  # unitless is mm
        self.assertAlmostEqual(self.dimension("Base", width)["value"], 20.0)
        self.reject("unit_mismatch", "edit_extrusion", feature="Block", expression="tilt")
        self.reject("unit_mismatch", "create_parameter", name="n", type="number", value="5 mm")
        self.reject("unit_mismatch", "create_parameter", name="m", type="number", bind=[{"feature": "Block", "parameter": "Length"}])
        self.call("fillet", id="Round", edges=[{"kind": "closest", "point": [20, 10, 10],
                                                "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}], radius=1)
        self.reject("unit_mismatch", "edit_dress_up", feature="Round", expression="tilt")
        self.call("edit_dress_up", feature="Round", expression="span / 10")
        self.call("sketch_circle", id="Spot", x=10, y=10, diameter=4)
        self.call("hole", id="Drill", sketch="Spot", diameter=4, depth=5, reversed=True)
        self.reject("unit_mismatch", "set_expression", feature="Drill", parameter="Diameter", expression="tilt")
        self.reject("unit_mismatch", "create_parameter", name="cone", type="angle",
                    bind=[{"feature": "Drill", "parameter": "Diameter"}])
        self.call("create_sketch", id="Turn", plane="XZ")
        self.call("add_rectangle", sketch="Turn", x=30, y=0, width=4, height=5)
        self.call("revolve", id="Spin", profile="Turn", operation="new", axis={"origin": [0, 0, 0], "direction": [0, 0, 1]},
                  angle="90 deg")
        self.reject("unit_mismatch", "set_expression", feature="Spin", parameter="Angle", expression="span")
        self.reject("unit_mismatch", "set_expression", feature="Spin", parameter="Angle", expression="ratio")
        self.call("set_expression", feature="Spin", parameter="Angle", expression="tilt * 9")
        self.assertAlmostEqual(next(row for row in self.call("inspect")["features"] if row["id"] == "Spin")
                               ["parameters"]["Angle"]["value"], math.radians(90))
        report = self.call("edit_parameter", name="tilt", value="20 deg")["parameter_report"]
        spin = next(row for row in report["changed_inputs"] if row["feature"] == "Spin")
        self.assertAlmostEqual(spin["previous"], math.radians(90), msg="a revolve's float Angle reports radians")
        self.assertAlmostEqual(spin["current"], math.radians(180))

    def test_parameter_formulas_only_read_parameters_and_cycles_reject(self):
        self.block()
        self.call("create_parameter", name="a", type="length", value=1)
        error = self.reject("invalid_expression", "create_parameter", name="b", type="length",
                            expression="Block.LengthFwd + 1 mm")
        self.assertIn("reads", error["reason"])
        self.call("create_parameter", name="b", type="length", expression="a + 1 mm")
        self.reject("expression_cycle", "edit_parameter", name="a", expression="b * 2")

    def test_label_reference_rejected_and_bare_names_auto_qualified(self):
        self.block()
        self.call("create_parameter", name="w", type="length", value=30)
        width = next(name for name, info in self.dimension_rows("Base").items() if info["unit"] == "mm")
        self.call("set_expression", feature="Base", parameter=width, expression="w")
        self.assertEqual(self.dimension("Base", width)["expression"], "Params.w")
        self.vs.Label = "Parameters"
        self.call("inspect")
        error = self.reject("invalid_expression", "set_expression", feature="Base", parameter=width, expression="Parameters.w")
        self.assertEqual(error["reason"], "label_reference")
        error = self.reject("invalid_expression", "set_expression", feature="Base", parameter=width, expression="_self.w")
        self.assertEqual(error["reason"], "pseudo_object")

    def dimension_rows(self, sketch):
        return next(row for row in self.call("inspect")["features"] if row["id"] == sketch)["parameters"]

    def test_bind_promotes_and_rejects_differing_values_with_one_rebuild(self):
        self.block()
        rows = self.dimension_rows("Base")
        lengths = sorted(name for name, info in rows.items() if info.get("constraint_type") == "Distance")
        rebuilds = []
        record = self.core.timings.record
        with patch.object(self.core.timings, "record", side_effect=lambda label, ms: (rebuilds.append(label), record(label, ms))):
            result = self.call("create_parameter", name="side", bind=[{"feature": "Base", "parameter": name} for name in lengths])
        self.assertEqual(rebuilds.count("managed_rebuild"), 1, "one managed rebuild for N binds")
        self.assertEqual(result["parameter_report"]["row"]["value"], 20.0)
        self.assertEqual(len(result["parameter_report"]["bound"]), 2)
        self.call("edit_parameter", name="side", value=25)
        self.assertEqual({info["value"] for name, info in self.dimension_rows("Base").items() if name in lengths}, {25.0})
        self.call("create_sketch", id="Odd", plane="XY")
        self.call("add_rectangle", sketch="Odd", x=40, y=0, width=3, height=4)
        odd = sorted(name for name, info in self.dimension_rows("Odd").items() if info.get("constraint_type") == "Distance")
        error = self.reject("bind_values_differ", "create_parameter", name="odd",
                            bind=[{"feature": "Odd", "parameter": name} for name in odd])
        self.assertEqual(sorted(row["value"] for row in error["targets"]), [3.0, 4.0])
        self.reject("expression_driven", "create_parameter", name="again", type="length", value=1,
                    bind=[{"feature": "Base", "parameter": lengths[0]}])

    def test_create_requires_type_for_plain_numbers(self):
        self.new()
        error = self.reject("invalid_argument", "create_parameter", name="x", value=5)
        self.assertEqual(error["fields"], ["type"])
        self.call("create_parameter", name="x", value="5 mm")
        self.call("create_parameter", name="y", expression="x * 2")
        self.assertEqual(self.rows()["y"]["type"], "length")

    def test_rename_preserves_consumers_undo_redo_and_rebinds_dangling(self):
        self.block()
        width = next(name for name, info in self.dimension_rows("Base").items() if info["unit"] == "mm")
        self.call("create_parameter", name="w", type="length", value=20)
        self.call("set_expression", feature="Base", parameter=width, expression="w")
        result = self.call("rename_parameter", name="w", new_name="width")
        self.assertEqual(self.dimension("Base", width)["expression"], "Params.width")
        self.assertEqual(result["parameter_report"]["rewritten"][0]["expression"], "Params.width")
        self.call("undo")
        self.assertEqual(self.dimension("Base", width)["expression"], "Params.w")
        self.call("redo")
        self.assertEqual(self.dimension("Base", width)["expression"], "Params.width")
        self.call("create_parameter", name="height", type="length", value=5)
        error = self.reject("duplicate_parameter", "rename_parameter", name="width", new_name="height")
        self.assertEqual(error["existing"], "height")
        self.reject("missing_parameter", "rename_parameter", name="nope", new_name="other")
        # A consumer naming a parameter that does not exist yet (native authoring) is dangling until a rename
        # gives that name: it is then re-bound and reported.
        height = next(name for name, info in self.dimension_rows("Base").items()
                      if info.get("constraint_type") == "Distance" and name != width)
        self.doc.getObject("Base").setExpression("Constraints." + height, "Params.ghost")
        warnings = self.call("list_parameters")["warnings"]
        self.assertIn(("dangling_reference", "ghost", "Base"), [(w["code"], w.get("name"), w.get("feature")) for w in warnings])
        result = self.call("rename_parameter", name="height", new_name="ghost")
        self.assertEqual([row["native_feature"] for row in result["parameter_report"]["rebound"]], ["Base"])
        self.assertEqual(self.dimension("Base", height)["value"], 5.0)
        self.assertFalse(self.call("list_parameters")["warnings"])

    def test_rename_failed_and_parameter_not_applied_guard_the_native_result(self):
        self.block()
        width = next(name for name, info in self.dimension_rows("Base").items() if info.get("constraint_type") == "Distance")
        self.call("create_parameter", name="w", type="length", value=20)
        self.call("set_expression", feature="Base", parameter=width, expression="w")
        records = parameters.records
        calls = []

        def drifting(doc, vs):
            result = records(doc, vs)
            calls.append(1)
            if len(calls) == 2:  # after the native rename: pretend a consumer's value moved
                result = {key: ("value", value[1] + 1) if key[0] == "Base" else value for key, value in result.items()}
            return result
        with patch.object(parameters, "records", side_effect=drifting):
            error = self.reject("rename_failed", "rename_parameter", name="w", new_name="width")
        self.assertEqual(error["broken"][0]["native_feature"], "Base")
        with patch.object(parameters, "current_value", return_value=999.0):
            error = self.reject("parameter_not_applied", "edit_parameter", name="w", value=22)
        self.assertEqual((error["feature"], error["expected"], error["actual"]), ("Base", 22.0, 999.0))

    def test_set_parameter_hints_point_to_edit_parameter(self):
        self.block()
        width = next(name for name, info in self.dimension_rows("Base").items() if info.get("constraint_type") == "Distance")
        self.call("create_parameter", name="w", type="length", value=20)
        self.call("set_expression", feature="Base", parameter=width, expression="w")
        error = self.reject("expression_driven", "set_parameter", feature="Base", parameter=width, value=30)
        self.assertEqual((error["parameters"], error["hint"], error["expression"]), (["w"], "edit_parameter", "Params.w"))
        error = self.reject("unknown_argument", "set_parameter", name="w", value=30)
        self.assertEqual(error["hint"], "model parameters use edit_parameter")

    def test_argument_types_reject_before_any_change(self):
        self.block()
        self.call("create_parameter", name="w", type="length", value=20)
        self.reject("invalid_argument", "create_parameter", name="x", type="length", expression=5)
        self.reject("invalid_argument", "create_parameter", name="x", type=["length"], value=1)
        self.reject("invalid_argument", "create_parameter", name="x", bind=[{"feature": "Base", "parameter": ["Width"]}])
        self.reject("invalid_argument", "edit_parameter", name="w", expression=7)
        self.reject("unsupported_parameter", "set_expression", feature="Base", parameter=["Width"], expression="w")

    def test_delete_in_use_rejects_and_freeze_keeps_values_and_undo_restores(self):
        self.block()
        width = next(name for name, info in self.dimension_rows("Base").items() if info["unit"] == "mm")
        self.call("create_parameter", name="w", type="length", value=26)
        self.call("create_parameter", name="half", expression="w / 2")
        self.call("set_expression", feature="Base", parameter=width, expression="w")
        error = self.reject("parameter_in_use", "delete_parameter", name="w")
        self.assertEqual(len(error["consumers"]), 2)
        result = self.call("delete_parameter", name="w", freeze_consumers=True)
        self.assertEqual(len(result["parameter_report"]["frozen"]), 2)
        self.assertIsNone(self.dimension("Base", width)["expression"])
        self.assertEqual(self.dimension("Base", width)["value"], 26.0)
        self.assertEqual(self.rows()["half"]["value"], 13.0)
        self.assertNotIn("w", self.rows())
        self.call("undo")
        self.assertEqual(self.dimension("Base", width)["expression"], "Params.w")
        self.assertIn("w", self.rows())
        self.call("delete_parameter", name="half")
        self.call("delete_parameter", name="w", freeze_consumers=True)
        state = self.call("inspect")
        self.assertEqual((state["parameter_set"]["id"], state["parameters"]), ("Params", []), "the empty set is kept")

    def test_rejected_edit_restores_accepted_value(self):
        self.shaft_model()
        self.call("edit_parameter", name="shaft_diameter", value=8)
        error = self.reject("build_failed", "edit_parameter", name="shaft_diameter", value=0)
        self.assertEqual(error["parameter"]["name"], "shaft_diameter")
        self.assertEqual(error["parameter"]["accepted"]["value"], 8.0)
        self.assertEqual(self.call("inspect")["build_status"], "valid")

    def test_hole_diameter_and_depth_driven_by_one_parameter_recheck(self):
        self.block()
        self.call("sketch_circle", id="Spot", x=10, y=10, diameter=4)
        self.call("hole", id="Drill", sketch="Spot", diameter=4, depth=5, reversed=True)
        self.call("create_parameter", name="d", type="length", value=4)
        self.call("set_expression", feature="Drill", parameter="Diameter", expression="d")
        self.call("set_expression", feature="Drill", parameter="Depth", expression="d * 15")
        self.call("edit_parameter", name="d", value=3)
        rows = self.dimension_rows("Drill")
        self.assertEqual((rows["Diameter"]["value"], rows["Depth"]["value"]), (3.0, 45.0))
        error = self.reject("invalid_argument", "edit_parameter", name="d", value=5)  # depth 75 > the native 60.6 mm maximum here
        self.assertIn("maximum_depth", error)

    def test_helix_pitch_formula_limits_on_set_expression_and_edit_parameter(self):
        self.new()
        self.call("create_helix", id="Coil", pitch=5, height=20, radius=5)
        self.call("create_parameter", name="p", type="length", value=5)
        self.call("set_expression", feature="Coil", parameter="Pitch", expression="p")
        error = self.reject("invalid_argument", "edit_parameter", name="p", value=0.001)  # refused before any rebuild
        self.assertEqual(error["parameter"]["accepted"]["value"], 5.0)
        self.reject("invalid_argument", "set_expression", feature="Coil", parameter="Height", expression="p * 2000")
        self.call("edit_parameter", name="p", value=4)
        self.assertEqual(self.dimension_rows("Coil")["Pitch"]["value"], 4.0)

    def test_signed_extrude_formula_through_parameter_is_kept(self):
        self.block()
        self.call("create_parameter", name="depth", type="length", value=8)
        self.call("edit_extrusion", feature="Block", expression="depth")
        self.call("edit_parameter", name="depth", value=-2)
        self.assertEqual(self.dimension_rows("Block")["Length"]["value"], -2.0)

    def test_touched_set_marks_document_and_bodies_needs_rebuild_and_blocks_export(self):
        self.block()
        self.call("create_parameter", name="w", type="length", value=20)
        self.vs.touch()
        state = self.call("inspect")
        self.assertEqual(state["build_status"], "needs_rebuild")
        self.assertEqual({body["build_status"] for body in state["bodies"]}, {"needs_rebuild"})
        self.assertEqual(state["parameter_set"]["state"], "needs_rebuild")
        response = self.request("export", path=str(self.folder / "touched.step"))
        self.assertFalse(response["ok"])
        self.call("rebuild")
        self.assertEqual(self.call("inspect")["build_status"], "valid")

    def test_a_broken_native_formula_is_named_although_the_set_is_also_touched(self):
        self.new()
        self.call("create_parameter", name="a", type="length", value=2)
        self.call("create_parameter", name="b", type="length", expression="a * 2")
        self.vs.setExpression("b", "no_such_name * 2")  # a native edit outside managed operations
        self.doc.recompute()
        block = self.call("inspect")["parameter_set"]
        self.assertEqual((block["state"], block["error"]["name"]), ("invalid", "b"), block)

    def test_external_native_parameter_edit_marks_results_pending_and_export_validates(self):
        self.block()
        self.call("create_sketch", id="Cap", plane="XY")
        self.call("add_rectangle", sketch="Cap", width=20, height=20)
        self.call("create_parameter", name="cap", type="length", value=15)
        self.call("pad", id="Raise", profile="Cap", length=15, operation="add", merge_scope=["Body"])
        self.call("edit_extrusion", feature="Raise", expression="cap")
        self.call("create_plane", id="TopPlane", origin=[0, 0, 15], normal=[0, 0, 1])
        self.call("create_sketch", id="TopSketch", support={"feature": "TopPlane"})
        self.call("add_rectangle", sketch="TopSketch", x=8, y=8, width=4, height=4)
        self.call("pocket", id="TopCut", profile="TopSketch", length=3, through_all=False, reversed=True,
                  operation="remove", merge_scope=["Body"])
        setattr(self.vs, "cap", 11)  # a native edit outside any managed operation
        self.doc.recompute()
        state = self.call("inspect")
        self.assertEqual((state["result_checks"]["status"], state["result_checks"].get("reason")), ("pending", "native_change"))
        response = self.request("export", path=str(self.folder / "pending.step"))
        self.assertEqual(response["error"]["code"], "build_failed")

    def test_native_silent_rename_rotates_revision(self):
        self.new()
        self.call("create_parameter", name="a", type="length", value=1)
        revision = self.call("inspect")["revision"]
        self.vs.renameProperty("a", "b")
        self.assertNotEqual(self.call("list_parameters")["revision"], revision)
        self.assertEqual(sorted(self.rows()), ["b"])

    def test_varsets_excluded_from_features_other_sets_read_only_first_marked_authoritative(self):
        self.new()
        self.call("create_parameter", name="a", type="length", value=1)
        loose = self.doc.addObject("App::VarSet", "Loose")
        loose.addProperty("App::PropertyLength", "x", "Base")
        copy = self.doc.addObject("App::VarSet", "ParamsCopy")
        copy.addProperty("App::PropertyBool", parameters.MARKER, "KurtShape")
        setattr(copy, parameters.MARKER, True)
        copy.addProperty("App::PropertyDistance", "b", "Parameters")
        self.doc.recompute()
        state = self.call("inspect")
        self.assertFalse({"Loose", "ParamsCopy", "Params"} & {row["id"] for row in state["features"]})
        self.assertEqual(state["parameter_set"]["id"], "Params")
        self.assertEqual(sorted(row["id"] for row in state["other_parameter_sets"]), ["Loose", "ParamsCopy"])
        listed = self.call("list_parameters")
        self.assertEqual([row["name"] for row in listed["parameters"]], ["a"])
        self.assertIn({"code": "extra_parameter_set", "id": "ParamsCopy"}, listed["warnings"])

    def test_preview_matches_commit_and_leaves_source_unchanged(self):
        self.shaft_model()
        before = self.invariant()
        preview = self.call("preview", proposal={"op": "edit_parameter", "name": "shaft_diameter", "value": 7})
        self.assertTrue(preview["accepted"])
        self.assertEqual(self.invariant()[1:], before[1:])
        committed = self.call("edit_parameter", name="shaft_diameter", value=7)
        self.assertEqual(preview["parameter_report"]["changed_parameters"], committed["parameter_report"]["changed_parameters"])
        self.assertEqual(preview["parameter_report"]["pruned"], committed["parameter_report"]["pruned"])
        self.assertAlmostEqual(preview["measurements"]["volume_mm3"], committed["measurements"]["volume_mm3"], places=6)

    def test_rolled_back_consumers_are_held(self):
        self.shaft_model()
        self.call("rollback", index=self.call("inspect")["studio"]["feature_order"].index("Top2"))
        with patch.object(parameters, "current_value", wraps=parameters.current_value) as spy:
            result = self.call("edit_parameter", name="shaft_diameter", value=7)
        self.assertEqual(result["build_status"], "valid")
        self.assertIn("ShaftSk", [row["feature"] for row in result["parameter_report"]["changed_inputs"]],
                      "the held consumer is bound and reported")
        self.assertEqual([call.args[1] for call in spy.call_args_list], ["ShoulderSk"], "only active consumers are verified")
        self.call("rollback", index=len(self.call("inspect")["studio"]["feature_order"]))
        self.assertAlmostEqual(self.dimension("ShaftSk", self.circle("ShaftSk"))["value"], 7.0)

    def test_list_parameters_usage_closure_affects_parts_and_dangling_warnings(self):
        self.shaft_model()
        rows = self.rows()
        shaft = rows["shaft_diameter"]
        self.assertEqual(shaft["used_by_parameters"], ["shoulder_diameter"])
        self.assertEqual([row["feature"] for row in shaft["used_by"]], ["ShaftSk"])
        self.assertEqual(rows["shoulder_diameter"]["depends_on"], ["shaft_diameter"])
        self.assertIn("Shoulder", shaft["affects"]["features"], "the closure reaches the shoulder through the set")
        self.assertEqual(shaft["affects"]["parts"], ["Body"])
        self.assertEqual(sorted(parameters.usage(self.doc)), ["shaft_diameter", "shoulder_diameter"])
        self.assertEqual({row["name"]: row["used_by_count"] for row in self.call("inspect")["parameters"]},
                         {"shaft_diameter": 2, "shoulder_diameter": 1})
        self.reject("missing_parameter", "list_parameters", names=["nope"])

    def test_reserved_feature_id_params(self):
        self.new()
        error = self.reject("invalid_argument", "create_body", id="params")
        self.assertEqual(error["reason"], "reserved_id")
        error = self.reject("invalid_id", "create_assembly", id="Params", name="Assembly")
        self.assertEqual(error["reason"], "reserved_id")

    def test_compact_rows_report_uses_parameters(self):
        self.shaft_model()
        state = self.call("inspect", features=["ShaftSk", "Block"])
        rows = {row["id"]: row for row in state["features"]}
        self.assertEqual(rows["ShaftSk"]["uses_parameters"], ["shaft_diameter"])
        self.assertNotIn("uses_parameters", rows["Block"])


class ParameterPruningTests(ParameterFixture, unittest.TestCase):
    """Pruned recompute equals the full recompute (the oracle) on every scenario."""

    def outcome(self):
        doc = self.doc
        state = self.call("inspect")
        shapes = sorted((obj.Name, round(obj.Shape.Volume, 6), tuple(sorted(obj.State)))
                        for obj in doc.Objects if hasattr(obj, "Shape") and not obj.Shape.isNull() and obj.Shape.Solids)
        volume = (state["measurements"] or {}).get("volume_mm3")
        # Each run is its own document: per-document UUIDs differ, everything else must not. Coordinates
        # below 1e-10 are recompute noise (a sketch end point at -1.1e-16 one run and 0 the next).
        intent = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>",
                        json.dumps(native_intent(doc), sort_keys=True, default=str))
        intent = re.sub(r"-?\d+(?:\.\d+)?e-(?:1\d|[2-9]\d|\d{3})", "0", intent).replace('\\"-0\\"', '\\"0\\"')
        return state["build_status"], None if volume is None else round(volume, 6), shapes, intent

    def scenario(self, build, edits):
        results = []
        for oracle in (False, True):
            with patch.dict(os.environ, {parameters.FULL_RECOMPUTE_ENV: "1" if oracle else "0"}):
                build()
                trail = []
                for edit in edits:
                    result = self.call(*edit[:1], **edit[1])
                    trail.append(self.outcome())
                    if edit[0] == "edit_parameter":
                        trail.append(tuple(result["parameter_report"]["changed_parameters"][0].values()))
                for _ in edits:
                    self.call("undo")
                trail.append(self.outcome())
                results.append(trail)
                self.call("close_document", discard=True)
        self.assertEqual(results[0], results[1])

    def two_parameter_block(self):
        self.new("Prune")
        self.call("create_parameter", name="w", type="length", value=20)
        self.call("create_parameter", name="len", type="length", value=10)
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        sketch = next(row for row in self.call("inspect")["features"] if row["id"] == "Base")
        width = next(name for name, info in sketch["parameters"].items() if info["unit"] == "mm")
        self.call("set_expression", feature="Base", parameter=width, expression="w")
        self.call("pad", id="Block", profile="Base", length=10, operation="new")
        self.call("edit_extrusion", feature="Block", expression="len")
        self.call("sketch_circle", id="Hole", x=5, y=5, diameter=3)
        self.call("pocket", id="Bore", profile="Hole", through_all=True, operation="remove", merge_scope=["Body"])

    def test_pruning_matches_full_recompute_matrix(self):
        self.scenario(self.two_parameter_block, [("edit_parameter", {"name": "w", "value": 30})])
        self.scenario(self.two_parameter_block, [("edit_parameter", {"name": "len", "value": 12})])
        self.scenario(self.two_parameter_block, [("edit_parameter", {"name": "len", "value": 12}),
                                                 ("edit_parameter", {"name": "w", "value": 25})])

    def hole_block(self):
        self.new("Prune")
        self.call("create_parameter", name="d", type="length", value=4)
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")
        self.call("sketch_circle", id="Spot", x=10, y=10, diameter=4)
        self.call("hole", id="Drill", sketch="Spot", diameter=4, depth=5, reversed=True)
        self.call("set_expression", feature="Drill", parameter="Diameter", expression="d")
        self.call("set_expression", feature="Drill", parameter="Depth", expression="d * 2")

    def helix_and_plane(self):
        self.new("Prune")
        self.call("create_parameter", name="p", type="length", value=5)
        self.call("create_parameter", name="z", type="length", value=10)
        self.call("create_helix", id="Coil", pitch=5, height=20, radius=5)
        self.call("set_expression", feature="Coil", parameter="Pitch", expression="p")
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")
        self.call("create_plane", id="Top", base_plane="XY", offset=10)
        self.call("set_expression", feature="Top", parameter="Offset", expression="z")
        self.call("create_sketch", id="CapSk", support={"feature": "Top"})
        self.call("add_rectangle", sketch="CapSk", x=5, y=5, width=10, height=10)
        self.call("pad", id="Cap", profile="CapSk", length=2, operation="add", merge_scope=["Body"])

    def rolled_back_shaft(self):
        self.shaft_model()
        self.call("rollback", index=self.call("inspect")["studio"]["feature_order"].index("Top2"))

    def test_pruning_matches_full_recompute_on_holes_helix_planes_and_rollback(self):
        self.scenario(self.hole_block, [("edit_parameter", {"name": "d", "value": 3})])
        self.scenario(self.helix_and_plane, [("edit_parameter", {"name": "p", "value": 4})])
        self.scenario(self.helix_and_plane, [("edit_parameter", {"name": "z", "value": 9})])
        self.scenario(self.rolled_back_shaft, [("edit_parameter", {"name": "shaft_diameter", "value": 7})])

    def test_pruning_prunes_unchanged_consumers(self):
        self.two_parameter_block()
        result = self.call("edit_parameter", name="len", value=12)
        self.assertEqual(result["parameter_report"]["pruned"], ["Base"])
        self.assertEqual([row["feature"] for row in result["parameter_report"]["changed_inputs"]], ["Block"])


if __name__ == "__main__":
    unittest.main()
