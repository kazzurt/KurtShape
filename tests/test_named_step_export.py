"""Named-part STEP export (export ``named_parts``, 2026-11-01).

With ``named_parts:true`` a STEP export writes one product per included current result, named
after its part, from the same detached world copies the default export writes. The default export
stays the plain compound. docs/OPERATION_CONTRACT.md "Named-part STEP export (2026-11-01)".
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Import
import Part
from kurtshape import assembly as native_assembly
from kurtshape.bodies import results as native_results
from kurtshape.core import Controller

GUIDE, FLANGE, TRACKER = "rosa_ee_guide_20", "rosa_arm_l6_flange", "rosa_tracker_femur"
NAMED_WRITER = "FreeCAD Import.export (named products)"


def products(path):
    """PRODUCT names of a STEP file, in file order."""
    return re.findall(r"=\s*PRODUCT\('([^']*)'", Path(path).read_bytes().decode("utf-8", "replace"))


def data_section(path):
    """The STEP DATA section (the header's FILE_NAME carries a timestamp), with OCCT's per-process
    product counter ("Open CASCADE STEP translator 7.8 <n>", one more per exportStep call) masked."""
    raw = Path(path).read_bytes()
    return re.sub(rb"(Open CASCADE STEP translator [0-9.]+ )[0-9]+", rb"\1#", raw[raw.index(b"\nDATA;"):])


def box(shape):
    bound = shape.BoundBox
    return [bound.XMin, bound.YMin, bound.ZMin, bound.XMax, bound.YMax, bound.ZMax]


class NamedStepExportTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="named-step-export-")
        self.core = Controller()
        self.core.settings.roots.add(self.folder)
        response = self.core.dispatch({"op": "new", "name": "Named step fixture"})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **args})

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "revision" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def reject(self, code, op, **args):
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response)
        return response["error"]

    # Fixture ---------------------------------------------------------------------------------------
    def build_parts(self):
        """Three named studio parts: a pad, a revolve and a moved pad. Returns {name: part id}."""
        self.call("sketch_rectangle", id="GuideProfile", body="Body", width=20, height=10)
        self.call("pad", id="GuideExtrude", profile="GuideProfile", body="Body", length=5, operation="new")
        self.call("create_sketch", id="FlangeProfile", plane="XZ", body="Body")
        self.call("add_polyline", sketch="FlangeProfile", closed=True,
                  points=[[60, 0], [72, 0], [72, 4], [66, 4], [66, 15], [60, 15]])
        self.call("revolve", id="FlangeRevolve", profile="FlangeProfile", operation="new", name=FLANGE,
                  axis={"origin": [60, 0, 0], "direction": [0, 0, 1]})
        self.call("create_body", id="Tracker", name="Tracker")
        self.call("sketch_rectangle", id="TrackerProfile", body="Tracker", x=0, y=0, width=8, height=6)
        self.call("pad", id="TrackerExtrude", profile="TrackerProfile", body="Tracker", length=3, operation="new")
        self.call("transform_part", id="TrackerMove", part="Tracker", translation=[30, -40, 12],
                  rotation={"axis": [1, 1, 0], "angle": "35 deg"})
        parts = {row["name"]: row["id"] for row in self.state["studio"]["parts"]}
        # Part names (KurtShapePartName) differ from the native labels, so the export must read the part name.
        self.call("set_part_appearance", part=parts["Body"], name=GUIDE)
        self.call("set_part_appearance", part=parts["Tracker"], name=TRACKER)
        parts = {row["name"]: row["id"] for row in self.state["studio"]["parts"]}
        self.assertEqual(set(parts), {GUIDE, FLANGE, TRACKER})
        self.assertEqual(self.state["build_status"], "valid", self.state)
        return parts

    def world(self):
        """{part name: detached world shape} of the current results, as the export copies them."""
        shapes = {}
        for obj in native_results(self.doc):
            if not obj.Shape.isNull() and obj.Shape.Solids:
                name = str(getattr(obj, "KurtShapePartName", "") or obj.Label)
                shapes[name] = native_assembly.global_shape(obj).copy()
        return shapes

    def invariant(self):
        """What an export must leave unchanged: revision, modified flags and the native document state."""
        inspected = self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"]})["result"]
        return {"revision": inspected["revision"], "modified": inspected["modified"], "unsaved": inspected["unsaved"],
                "undo": self.doc.UndoCount, "pending": self.doc.HasPendingTransaction,
                "states": sorted((obj.Name, tuple(sorted(obj.State))) for obj in self.doc.Objects),
                "documents": sorted(App.listDocuments()),
                "active": App.activeDocument().Name if App.activeDocument() else None}

    def reread(self, path):
        """{label: shape} of the Part::Feature leaves Import.insert makes from ``path`` in a fresh document."""
        document = App.newDocument("NamedStepReread", hidden=True, temp=True)
        try:
            Import.insert(str(path), document.Name)
            return {obj.Label: obj.Shape.copy() for obj in document.Objects if obj.TypeId == "Part::Feature"}
        finally:
            App.closeDocument(document.Name)

    def sidecar(self, path):
        return json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))

    # Named products --------------------------------------------------------------------------------
    def test_named_parts_write_one_named_product_per_part(self):
        parts = self.build_parts()
        world = self.world()
        self.assertEqual(set(world), set(parts))
        before = self.invariant()
        path = self.folder / "named-parts.step"
        result = self.call("export", path=str(path), named_parts=True)
        self.assertEqual(result["revision"], before["revision"])
        self.assertEqual(self.invariant(), before)

        manifest = self.sidecar(path)
        self.assertEqual(manifest["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(manifest["units"], "mm")
        self.assertEqual(manifest["settings"]["writer"], NAMED_WRITER)
        root = manifest["settings"]["root_product"]
        self.assertEqual(root, "Named_step_fixture")
        rows = manifest["named_parts"]
        self.assertEqual([row["part_id"] for row in rows], manifest["included_part_ids"])
        self.assertEqual({row["name"]: row["part_id"] for row in rows}, parts)
        for row in rows:
            with self.subTest(part=row["name"]):
                self.assertEqual(set(row), {"part_id", "name", "solid_count", "volume_mm3"})
                self.assertEqual(row["solid_count"], 1)
                self.assertAlmostEqual(row["volume_mm3"], world[row["name"]].Volume,
                                       delta=1e-6 * world[row["name"]].Volume)

        # The file: a root product over one product per part, in millimetres.
        names = products(path)
        self.assertEqual(names[0], root)
        self.assertEqual(sorted(names[1:]), sorted(parts))
        self.assertIn(b"SI_UNIT(.MILLI.,.METRE.)", path.read_bytes())
        # Re-read: one named solid per part with the source volume and world position.
        leaves = self.reread(path)
        self.assertEqual(set(leaves), set(parts))
        for name, shape in leaves.items():
            with self.subTest(reread=name):
                self.assertEqual(len(shape.Solids), 1)
                self.assertAlmostEqual(shape.Volume, world[name].Volume, delta=1e-6 * world[name].Volume)
                for actual, expected in zip(box(shape), box(world[name])):
                    self.assertAlmostEqual(actual, expected, places=6)
        merged = Part.read(str(path))
        self.assertEqual(len(merged.Solids), 3)
        total = sum(shape.Volume for shape in world.values())
        self.assertAlmostEqual(merged.Volume, total, delta=1e-6 * total)
        self.assertFalse(list(self.folder.glob("*.exporting.*")))

    def test_selected_body_is_a_single_root_product(self):
        parts = self.build_parts()
        world = self.world()[FLANGE]
        path = self.folder / "flange.stp"
        self.call("export", path=str(path), body=parts[FLANGE], named_parts=True)
        self.assertEqual(products(path), [FLANGE])
        manifest = self.sidecar(path)
        self.assertIsNone(manifest["settings"]["root_product"])
        self.assertEqual([(row["part_id"], row["name"]) for row in manifest["named_parts"]], [(parts[FLANGE], FLANGE)])
        read = Part.read(str(path))
        self.assertEqual(len(read.Solids), 1)
        self.assertAlmostEqual(read.Volume, world.Volume, delta=1e-6 * world.Volume)

    def test_single_placed_result_keeps_its_world_placement_and_label_name(self):
        # A native Part::Feature result: no part name, so its label names the product, and its shape
        # carries a non-identity placement (studio results have placements baked into geometry).
        solid = self.doc.addObject("Part::Feature", "PosedSolid")
        solid.Label = "rosa_tracker_tibia"
        solid.Shape = Part.makeBox(8, 6, 3)
        solid.Placement = App.Placement(App.Vector(30, -40, 12), App.Rotation(App.Vector(1, 1, 0), 35))
        self.doc.recompute()
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        world = native_assembly.global_shape(solid).copy()
        self.assertFalse(world.Placement.isIdentity(), "the result must reach the export with a placement")
        path = self.folder / "tibia.step"
        self.call("export", path=str(path), named_parts=True)
        self.assertEqual(products(path), ["rosa_tracker_tibia"])
        manifest = self.sidecar(path)
        self.assertEqual([(row["part_id"], row["name"]) for row in manifest["named_parts"]],
                         [("PosedSolid", "rosa_tracker_tibia")])
        self.assertIsNone(manifest["settings"]["root_product"])
        read = Part.read(str(path))
        self.assertEqual(len(read.Solids), 1)
        self.assertAlmostEqual(read.Volume, 144, places=6)
        # FreeCAD's default keepPlacement=False writes a single product at the identity placement.
        for actual, expected in zip(box(read), box(world)):
            self.assertAlmostEqual(actual, expected, places=6)

    # Default export unchanged ----------------------------------------------------------------------
    def test_default_export_is_the_unchanged_plain_compound(self):
        parts = self.build_parts()
        included = [obj for obj in native_results(self.doc) if not obj.Shape.isNull() and obj.Shape.Solids]
        reference = self.folder / "reference.step"
        Part.makeCompound([native_assembly.global_shape(obj).copy() for obj in included]).exportStep(str(reference))
        before = self.invariant()
        plain, unflagged = self.folder / "plain.step", self.folder / "unflagged.step"
        self.call("export", path=str(plain))
        self.call("export", path=str(unflagged), named_parts=False)
        self.assertEqual(self.invariant(), before)
        # Same writer, same bytes as Shape.exportStep of the compound (only the header timestamp differs).
        self.assertEqual(data_section(plain), data_section(reference))
        self.assertEqual(data_section(unflagged), data_section(reference))
        for path in (plain, unflagged):
            with self.subTest(path=path.name):
                manifest = self.sidecar(path)
                self.assertIsNone(manifest["named_parts"])
                self.assertEqual(manifest["settings"], {"writer": "FreeCAD Part/OCCT"})
                self.assertEqual(len(products(path)), 1)
                self.assertFalse(set(products(path)) & set(parts))
                self.assertEqual(len(Part.read(str(path)).Solids), 3)
        stl = self.folder / "plain.stl"
        self.call("export", path=str(stl), named_parts=False)
        self.assertIsNone(self.sidecar(stl)["named_parts"])

    # Rejections and cleanup ------------------------------------------------------------------------
    def test_stl_and_non_boolean_values_reject_before_writing(self):
        self.build_parts()
        before = self.invariant()
        cases = [("named.stl", True), ("yes.step", "yes"), ("one.step", 1), ("null-list.step", [])]
        for name, value in cases:
            with self.subTest(path=name, value=value):
                error = self.reject("invalid_argument", "export", path=str(self.folder / name), named_parts=value)
                self.assertEqual(error["fields"], ["named_parts"])
                self.assertFalse((self.folder / name).exists())
                self.assertFalse((self.folder / (name + ".json")).exists())
        self.assertEqual(self.invariant(), before)

    def test_writer_failure_closes_the_temporary_document_and_keeps_the_previous_pair(self):
        self.build_parts()
        path = self.folder / "kept.step"
        self.call("export", path=str(path))
        kept, kept_sidecar = path.read_bytes(), Path(str(path) + ".json").read_bytes()
        before = self.invariant()
        with patch.object(Import, "export", side_effect=RuntimeError("writer exploded")):
            self.reject("export_failed", "export", path=str(path), named_parts=True)
        self.assertEqual(self.invariant(), before)
        self.assertEqual(path.read_bytes(), kept)
        self.assertEqual(Path(str(path) + ".json").read_bytes(), kept_sidecar)
        self.assertFalse(list(self.folder.glob("*.exporting.*")))


if __name__ == "__main__":
    unittest.main()
