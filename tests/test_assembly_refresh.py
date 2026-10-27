"""Occurrence refresh, source sharing and usable-part discovery regressions."""
import hashlib
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part

from test_assembly import AssemblyWorkflowTests
from kurtshape import assembly, studio
from kurtshape.core import intent_signature


class AssemblyRefreshTests(unittest.TestCase):
    # Reuse the existing native fixture helpers without rerunning its entire
    # inherited acceptance suite under a second class.
    for _name in ("setUp", "tearDown", "doc", "request", "call", "reject", "source_project",
                  "insert", "fixture", "joint", "placement", "assertPlacementEqual", "snapshot", "assertSnapshotEqual"):
        locals()[_name] = AssemblyWorkflowTests.__dict__[_name]
    reference = staticmethod(AssemblyWorkflowTests.reference)

    def replacement(self, width=5, position=None):
        doc = App.newDocument("RefreshReplacement")
        try:
            body = doc.addObject("PartDesign::Body", "SourceBody")
            obj = body.newObject("PartDesign::Feature", "SourceSolid")
            obj.Shape = Part.makeBox(width, 6, 8, App.Vector(1, 2, 0))
            if position is not None:
                body.Placement.Base = App.Vector(*position)
            doc.recompute()
            path = self.folder / "saved-component-revision.FCStd"
            doc.saveAs(str(path))
            return path
        finally:
            App.closeDocument(doc.Name)
            App.setActiveDocument(self.doc.Name)

    def test_refresh_single_preserves_identity_grounding_placement_and_source_file(self):
        self.fixture(count=1)
        link = self.doc.Base
        placement = link.Placement.copy()
        ground = assembly._group(assembly.get(self.doc)).Group[0]
        replacement = self.replacement(position=[100, 20, 7])
        digest = hashlib.sha256(replacement.read_bytes()).hexdigest()
        before_undo = self.doc.UndoCount
        result = self.call("refresh_assembly_part", instance="Base", path=str(replacement))
        self.assertIs(self.doc.Base, link)
        self.assertIs(ground.ObjectToGround, link)
        self.assertEqual(link.Label, "Base")
        self.assertPlacementEqual(link.Placement, placement)
        self.assertAlmostEqual(link.LinkedObject.Shape.Volume, 240)
        self.assertEqual(result["refresh_report"]["instances"], ["Base"])
        self.assertTrue(result["refresh_report"]["placement_preserved"])
        self.assertEqual(self.doc.UndoCount, before_undo + 1)
        self.assertEqual(hashlib.sha256(replacement.read_bytes()).hexdigest(), digest)
        self.call("undo")
        self.assertAlmostEqual(self.doc.Base.LinkedObject.Shape.Volume, 192)
        self.call("redo")
        self.assertAlmostEqual(self.doc.Base.LinkedObject.Shape.Volume, 240)

    def test_shared_requires_choice_and_instance_refresh_is_copy_on_write(self):
        self.fixture(count=2)
        self.call("move_assembly_instance", instance="Fastened", position_mm=[30, 20, 10])
        replacement = self.replacement()
        before = self.snapshot()
        self.reject("refresh_assembly_part", code="assembly_refresh_shared_source",
                    instance="Fastened", path=str(replacement))
        self.assertSnapshotEqual(before)
        source = self.doc.Base.LinkedObject
        link = self.doc.Fastened
        placement = link.Placement.copy()
        result = self.call("refresh_assembly_part", instance="Fastened", path=str(replacement), shared="instance")
        self.assertIs(self.doc.Fastened, link)
        self.assertIs(self.doc.Base.LinkedObject, source)
        self.assertIsNot(link.LinkedObject, source)
        self.assertAlmostEqual(source.Shape.Volume, 192)
        self.assertAlmostEqual(link.LinkedObject.Shape.Volume, 240)
        self.assertPlacementEqual(link.Placement, placement)
        self.assertEqual(result["refresh_report"]["instances"], ["Fastened"])

    def test_insert_after_single_shared_refresh_reuses_embedded_source_not_occurrence(self):
        self.fixture(count=2)
        old_source = self.doc.Base.LinkedObject
        replacement = self.replacement()
        self.call("refresh_assembly_part", instance="Fastened", path=str(replacement), shared="instance")
        updated_source = self.doc.Fastened.LinkedObject
        self.assertIsNot(updated_source, old_source)
        # App::Link forwards source properties; the first matching metadata owner
        # in document order is now the occurrence, not its later-created source.
        self.assertTrue(self.doc.Fastened.KurtShapeEmbeddedSource)
        self.assertNotIn("KurtShapeEmbeddedSource", self.doc.Fastened.PropertiesList)
        objects = list(self.doc.Objects)
        self.assertLess(objects.index(self.doc.Fastened), objects.index(updated_source))
        placements = {obj.Name: obj.Placement.copy() for obj in assembly.result_objects(self.doc)}
        result = self.insert("RevisedOccurrence", path=replacement)
        self.assertEqual(result["build_status"], "valid")
        self.assertIs(self.doc.RevisedOccurrence.LinkedObject, updated_source)
        self.assertEqual(self.doc.RevisedOccurrence.LinkedObject.TypeId, "Part::Feature")
        self.assertIs(self.doc.Base.LinkedObject, old_source)
        self.assertIs(self.doc.Fastened.LinkedObject, updated_source)
        self.assertEqual(assembly.validation_errors(self.doc), [])
        for name, placement in placements.items():
            self.assertPlacementEqual(self.doc.getObject(name).Placement, placement)
        rows = self.call("part_inventory", include_history=True)["parts"]
        self.assertEqual({row["id"] for row in rows if row["role"] == "final"},
                         {"Base", "Fastened", "RevisedOccurrence"})
        self.assertEqual({row["id"] for row in rows if row["role"] == "embedded_source"},
                         {old_source.Name, updated_source.Name})
        path = self.folder / "reinsert-refreshed-source.FCStd"
        self.call("save", path=str(path))
        self.call("close_document")
        reopened = self.call("open", path=str(path))
        self.assertEqual(reopened["build_status"], "valid")
        self.assertIs(self.doc.RevisedOccurrence.LinkedObject, self.doc.Fastened.LinkedObject)
        self.assertIsNot(self.doc.Base.LinkedObject, self.doc.Fastened.LinkedObject)


    def test_shared_all_keeps_origin_joint_and_every_placement(self):
        self.fixture(count=2)
        self.joint("fixed", "Fastened", identity="FastenerJoint")
        joint = self.doc.FastenerJoint
        before = {obj.Name: obj.Placement.copy() for obj in assembly.result_objects(self.doc)}
        result = self.call("refresh_assembly_part", instance="Base", path=str(self.replacement()), shared="all")
        self.assertIs(self.doc.FastenerJoint, joint)
        self.assertIs(joint.Reference1[0], self.doc.Base)
        self.assertIs(joint.Reference2[0], self.doc.Fastened)
        self.assertIs(self.doc.Base.LinkedObject, self.doc.Fastened.LinkedObject)
        self.assertEqual(result["refresh_report"]["preserved_joint_references"], 2)
        for obj in assembly.result_objects(self.doc):
            self.assertPlacementEqual(obj.Placement, before[obj.Name])
            self.assertAlmostEqual(obj.LinkedObject.Shape.Volume, 240)
        self.assertEqual(result["build_status"], "valid")

    def test_changed_joint_subelement_rejects_and_rolls_back(self):
        self.fixture(count=2)
        self.joint("fixed", "Fastened", identity="FaceJoint", first_sub="Face2", second_sub="Face2")
        before = self.snapshot()
        source = self.doc.Base.LinkedObject
        before_seal = source.SourceGeometryFingerprint
        self.reject("refresh_assembly_part", code="assembly_refresh_reference_changed", instance="Base",
                    path=str(self.replacement()), shared="all")
        self.assertSnapshotEqual(before)
        self.assertEqual(self.doc.Base.LinkedObject.SourceGeometryFingerprint, before_seal)
        self.assertAlmostEqual(self.doc.Base.LinkedObject.Shape.Volume, 192)
        self.assertEqual(self.call("inspect")["build_status"], "valid")

    def test_solver_failure_rolls_back_copy_on_write_and_links(self):
        self.fixture(count=2)
        self.joint("fixed", "Fastened", identity="FaceJoint", first_sub="Face1", second_sub="Face1")
        before = self.snapshot()
        names = {obj.Name for obj in self.doc.Objects}
        replacement = self.replacement()
        with patch("kurtshape.assembly_refresh.assembly.solve",
                   side_effect=assembly.AssemblyError("assembly_solver_failed", "regression injected solver failure")):
            self.reject("refresh_assembly_part", code="assembly_solver_failed", instance="Fastened",
                        path=str(replacement), shared="instance")
        self.assertSnapshotEqual(before)
        self.assertEqual({obj.Name for obj in self.doc.Objects}, names)
        self.assertIs(self.doc.Base.LinkedObject, self.doc.Fastened.LinkedObject)

    def test_unchanged_joint_subelements_survive_component_revision(self):
        self.fixture(count=2)
        self.joint("fixed", "Fastened", identity="FaceJoint", first_sub="Face1", second_sub="Face1")
        joint = self.doc.FaceJoint
        result = self.call("refresh_assembly_part", instance="Base", path=str(self.replacement()), shared="all")
        self.assertEqual(result["build_status"], "valid")
        self.assertIs(self.doc.FaceJoint, joint)
        self.assertEqual(joint.Reference1[1][0], "Face1")

    def test_refresh_reopens_with_source_provenance_and_valid_joints(self):
        self.fixture(count=2)
        self.joint("fixed", "Fastened")
        self.call("refresh_assembly_part", instance="Base", path=str(self.replacement()), shared="all")
        path = self.folder / "refreshed-assembly.FCStd"
        self.call("save", path=str(path))
        self.call("close_document")
        result = self.call("open", path=str(path))
        self.assertEqual(result["build_status"], "valid")
        self.assertEqual(len(result["assembly"]["instances"]), 2)
        self.assertAlmostEqual(self.doc.Base.LinkedObject.Shape.Volume, 240)
        self.assertEqual(assembly.validation_errors(self.doc), [])

    def test_inventory_legacy_and_step_and_studio_finals_share_roles(self):
        legacy = self.call("assembly_candidates", path=str(self.source))["candidates"]
        self.assertEqual([(row["id"], row["role"], row["usable"]) for row in legacy], [("SourceBody", "final", True)])
        step = self.folder / "legacy-step.step"
        Part.makeBox(3, 4, 5).exportStep(str(step))
        step_candidates = self.call("assembly_candidates", path=str(step), final_only=True)["candidates"]
        self.assertEqual(len(step_candidates), 1)
        self.assertTrue(step_candidates[0]["usable"])
        self.call("sketch_rectangle", id="Profile", width=10, height=10)
        result = self.call("pad", id="Extrude", profile="Profile", length=8, operation="new")
        part = result["studio"]["parts"][0]["id"]
        self.call("sketch_circle", id="HoleProfile", diameter=2, x=5, y=5)
        self.call("pocket", id="Cut", profile="HoleProfile", length=4, operation="remove", merge_scope=[part])
        signature = intent_signature(self.doc)
        finals = self.call("part_inventory")["parts"]
        all_parts = self.call("part_inventory", include_history=True)["parts"]
        self.assertEqual({row["id"] for row in finals}, {obj.Name for obj in studio.current_parts(self.doc)})
        self.assertTrue(all(row["role"] == "final" and row["usable"] for row in finals))
        self.assertTrue(any(row["role"] in {"helper", "history"} for row in all_parts))
        self.assertEqual(intent_signature(self.doc), signature)
        path = self.folder / "studio-inventory.FCStd"
        self.call("save", path=str(path))
        compatible = self.call("assembly_candidates", path=str(path))["candidates"]
        filtered = self.call("assembly_candidates", path=str(path), final_only=True)["candidates"]
        self.assertGreater(len(compatible), len(filtered))
        self.assertEqual({row["id"] for row in filtered}, {row["id"] for row in finals})

    def test_inventory_flags_require_booleans(self):
        self.reject("part_inventory", code="invalid_argument", include_history="true")
        self.reject("assembly_candidates", code="invalid_argument", path=str(self.source), final_only=1)
