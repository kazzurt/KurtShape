"""Native Assembly solver, embedded occurrences and shared-controller safety gates."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, OperationError, intent_signature, measurements


class AssemblyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.temporary = tempfile.TemporaryDirectory(prefix="assembly-native-fixture-", dir=ROOT / "runtime")
        self.folder = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"KURTSHAPE_SESSION_DIR": str(self.folder)})
        self.environment.start()
        self.core = Controller()
        self.state = None
        self.call("new", name="Assembly acceptance")
        self.source = self.source_project()

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)
        self.environment.stop()
        self.temporary.cleanup()

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        request = {"op": op, **args}
        if op not in self.core.CREATE_OPS | {"capabilities", "request_status", "list_documents", "assembly_candidates"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return request

    def call(self, op, **args):
        response = self.core.dispatch(self.request(op, **args))
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def reject(self, op, code=None, **args):
        response = self.core.dispatch(self.request(op, **args))
        self.assertFalse(response["ok"], response)
        if code:
            self.assertEqual(response["error"]["code"], code, response)
        return response

    def source_project(self, filename="asymmetric-block.FCStd", multiple=False):
        source = App.newDocument("AssemblySource")
        try:
            body = source.addObject("PartDesign::Body", "SourceBody")
            body.Label = "Asymmetric block"
            base = body.newObject("PartDesign::Feature", "SourceSolid")
            base.Shape = Part.makeBox(4, 6, 8, App.Vector(1, 2, 0))
            if multiple:
                second = source.addObject("PartDesign::Body", "SecondBody")
                second.Label = "Second selectable body"
                feature = second.newObject("PartDesign::Feature", "SecondSolid")
                feature.Shape = Part.makeCylinder(2, 7, App.Vector(20, 0, 0))
            source.recompute()
            path = self.folder / filename
            source.saveAs(str(path))
            return path
        finally:
            App.closeDocument(source.Name)
            App.setActiveDocument(self.doc.Name)

    def insert(self, identity, path=None, source_id="SourceBody"):
        return self.call("insert_assembly_part", path=str(path or self.source), source_id=source_id,
                         id=identity, name=identity)

    def fixture(self, count=4):
        self.call("create_assembly", id="AcceptanceAssembly", name="Native acceptance assembly")
        for identity in ("Base", "Fastened", "Rotor", "Carriage")[:count]:
            self.insert(identity)
        self.call("ground_assembly_instance", instance="Base")

    @staticmethod
    def reference(instance, subelement=""):
        return {"instance": instance, "subelement": subelement}

    def joint(self, kind, second, identity=None, first="Base", first_sub="", second_sub=""):
        return self.call("create_assembly_joint", joint_type=kind,
                         first=self.reference(first, first_sub), second=self.reference(second, second_sub),
                         id=identity or kind.title() + "Joint")

    def placement(self, identity):
        return self.doc.getObject(identity).Placement

    def assertPlacementEqual(self, actual, expected, places=6):
        self.assertLess((actual.Base - expected.Base).Length, 10 ** -places)
        self.assertLess((actual.Rotation.inverted() * expected.Rotation).Angle, 10 ** -places)

    def snapshot(self):
        return (intent_signature(self.doc), self.state["revision"], self.doc.UndoCount, self.doc.RedoCount,
                {obj.Name: obj.Placement.copy() for obj in self.doc.Objects if obj.TypeId == "App::Link"})

    def assertSnapshotEqual(self, before):
        after = self.snapshot()
        self.assertEqual(after[:4], before[:4])
        self.assertEqual(set(after[4]), set(before[4]))
        for identity in before[4]:
            self.assertPlacementEqual(after[4][identity], before[4][identity])

    def test_candidates_repeated_embedded_occurrences_and_ground_switch(self):
        multi = self.source_project("two-selectable-bodies.FCStd", multiple=True)
        digest = hashlib.sha256(multi.read_bytes()).hexdigest()
        names = set(App.listDocuments())
        candidates = self.call("assembly_candidates", path=str(multi))["candidates"]
        self.assertEqual({part["id"] for part in candidates}, {"SourceBody", "SecondBody"})
        self.assertTrue(all(part["solid_count"] == 1 for part in candidates))
        self.assertEqual(set(App.listDocuments()), names)
        self.call("create_assembly", id="AcceptanceAssembly")
        self.insert("First", path=multi)
        self.insert("Repeated", path=multi)
        self.insert("OtherBody", path=multi, source_id="SecondBody")
        instances = self.state["assembly"]["instances"]
        self.assertEqual({part["id"] for part in instances}, {"First", "Repeated", "OtherBody"})
        first, repeated = (self.doc.getObject(identity) for identity in ("First", "Repeated"))
        self.assertEqual(first.TypeId, "App::Link")
        self.assertEqual(repeated.TypeId, "App::Link")
        self.assertIs(first.LinkedObject.Document, self.doc)
        self.assertIs(repeated.LinkedObject.Document, self.doc)
        self.assertIs(first.LinkedObject, repeated.LinkedObject)
        self.assertEqual(self.state["measurements"]["solid_count"], 3)
        self.call("ground_assembly_instance", instance="Repeated")
        self.assertEqual([part["id"] for part in self.state["assembly"]["instances"] if part["grounded"]], ["Repeated"])
        self.assertEqual(hashlib.sha256(multi.read_bytes()).hexdigest(), digest)

    def test_native_fixed_revolute_slider_solve_and_allowed_motion(self):
        self.fixture()
        self.joint("fixed", "Fastened")
        self.joint("revolute", "Rotor")
        self.joint("slider", "Carriage")
        assembly = self.doc.getObject("AcceptanceAssembly")
        self.assertEqual(assembly.TypeId, "Assembly::AssemblyObject")
        self.assertEqual(len([obj for obj in self.doc.Objects if obj.TypeId == "Assembly::JointGroup"]), 1)
        self.assertEqual({joint["joint_type"] for joint in self.state["assembly"]["joints"]}, {"fixed", "revolute", "slider"})
        self.assertEqual(self.state["build_status"], "valid")
        base, fixed = self.placement("Base").copy(), self.placement("Fastened").copy()
        self.call("move_assembly_joint", joint="RevoluteJoint", value=45)
        self.assertPlacementEqual(self.placement("Base"), base)
        self.assertPlacementEqual(self.placement("Fastened"), fixed)
        relative = base.inverse() * self.placement("Rotor")
        self.assertAlmostEqual(relative.Rotation.Angle, math.radians(45), places=6)
        self.assertLess(relative.Base.Length, 1e-6)
        self.call("move_assembly_joint", joint="SliderJoint", value=20)
        relative = base.inverse() * self.placement("Carriage")
        self.assertAlmostEqual(relative.Base.x, 0, places=6)
        self.assertAlmostEqual(relative.Base.y, 0, places=6)
        self.assertAlmostEqual(abs(relative.Base.z), 20, places=6)
        self.assertLess(relative.Rotation.Angle, 1e-6)
        before = self.snapshot()
        self.reject("move_assembly_joint", code="fixed_joint", joint="FixedJoint", value=4)
        self.assertSnapshotEqual(before)

    def test_free_instance_move_and_jointed_placement_are_one_undo_command(self):
        self.fixture(count=2)
        before = self.placement("Fastened").copy()
        count = self.doc.UndoCount
        self.call("move_assembly_instance", instance="Fastened", position_mm=[30, 4, 5],
                  rotation_xyzw=[0, 0, math.sin(math.pi / 8), math.cos(math.pi / 8)])
        accepted = self.placement("Fastened").copy()
        self.assertAlmostEqual(accepted.Base.x, 30, places=6)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.call("undo")
        self.assertPlacementEqual(self.placement("Fastened"), before)
        self.call("redo")
        self.assertPlacementEqual(self.placement("Fastened"), accepted)
        self.joint("fixed", "Fastened")
        self.assertLess(self.placement("Fastened").Base.Length, 1e-6)
        self.call("undo")
        self.assertIsNone(self.doc.getObject("FixedJoint"))
        self.assertPlacementEqual(self.placement("Fastened"), accepted)
        self.call("redo")
        self.assertIsNotNone(self.doc.getObject("FixedJoint"))
        self.assertLess(self.placement("Fastened").Base.Length, 1e-6)

    def test_edit_rename_delete_joint_and_cascade_instance_restore_native_references(self):
        self.fixture(count=2)
        self.joint("revolute", "Fastened", identity="Joint")
        self.call("move_assembly_joint", joint="Joint", value=35)
        moved = self.placement("Fastened").copy()
        self.call("rename_feature", feature="Joint", name="Edited hinge")
        self.assertEqual(self.doc.getObject("Joint").Label, "Edited hinge")
        self.call("edit_assembly_joint", joint="Joint", joint_type="slider")
        self.assertEqual(self.state["assembly"]["joints"][0]["joint_type"], "slider")
        self.call("undo")
        self.assertEqual(self.state["assembly"]["joints"][0]["joint_type"], "revolute")
        self.assertPlacementEqual(self.placement("Fastened"), moved)
        before = self.snapshot()
        self.reject("delete_assembly_object", code="assembly_dependency", feature="Fastened")
        self.assertSnapshotEqual(before)
        self.call("delete_assembly_object", feature="Fastened", cascade=True)
        self.assertIsNone(self.doc.getObject("Fastened"))
        self.assertIsNone(self.doc.getObject("Joint"))
        self.call("undo")
        self.assertIsNotNone(self.doc.getObject("Fastened"))
        self.assertIsNotNone(self.doc.getObject("Joint"))
        restored = self.state["assembly"]["joints"][0]
        self.assertEqual({ref["instance"] for ref in restored["references"]}, {"Base", "Fastened"})
        self.assertPlacementEqual(self.placement("Fastened"), moved)
        self.call("redo")
        self.assertIsNone(self.doc.getObject("Fastened"))

    def test_replay_stale_unknown_arguments_and_invalid_inputs_do_not_mutate(self):
        self.fixture(count=2)
        request = self.request("create_assembly_joint", joint_type="revolute",
                               first=self.reference("Base"), second=self.reference("Fastened"),
                               id="ReplayJoint", request_id=str(uuid.uuid4()))
        first = self.core.dispatch(request)
        self.assertTrue(first["ok"], first)
        self.state = first["result"]
        before = self.snapshot()
        self.assertEqual(self.core.dispatch(request), first)
        self.assertSnapshotEqual(before)
        changed = {**request, "id": "DifferentJoint"}
        self.assertFalse(self.core.dispatch(changed)["ok"])
        stale = {**self.request("ground_assembly_instance", instance="Fastened"), "expected_revision": request["expected_revision"]}
        self.assertEqual(self.core.dispatch(stale)["error"]["code"], "stale_revision")
        self.reject("ground_assembly_instance", instance="Base", execute="unsafe")
        self.reject("ground_assembly_instance", assembly="MissingAssembly", instance="Base")
        self.reject("create_assembly_joint", joint_type="revolute", first=self.reference("Base", "Face9999"),
                    second=self.reference("Fastened"))
        self.reject("create_assembly_joint", joint_type="fixed", first=self.reference("Base"), second=self.reference("Base"))
        self.reject("move_assembly_instance", instance="Fastened", position_mm=[float("nan"), 0, 0], rotation_xyzw=[0, 0, 0, 1])
        self.reject("insert_assembly_part", path=str(self.source), source_id="NoSuchBody")
        self.assertSnapshotEqual(before)

    def test_real_solver_conflict_and_injected_solver_failure_rollback(self):
        from kurtshape import assembly as native
        self.fixture(count=3)
        self.joint("fixed", "Fastened")
        self.joint("fixed", "Rotor", identity="SecondFixed", first="Fastened")
        before = self.snapshot()
        self.reject("create_assembly_joint", code="assembly_solver_failed", joint_type="fixed",
                    first=self.reference("Base", "Face1"), second=self.reference("Rotor", "Face2"), id="ConflictingJoint")
        self.assertSnapshotEqual(before)
        self.assertIsNone(self.doc.getObject("ConflictingJoint"))
        self.call("delete_assembly_object", feature="FixedJoint")
        self.call("delete_assembly_object", feature="SecondFixed")
        before = self.snapshot()
        with patch.object(native, "solve", side_effect=OperationError("assembly_solver_failed", "Injected solver failure", native_code=-99)):
            self.reject("create_assembly_joint", code="assembly_solver_failed", joint_type="slider",
                        first=self.reference("Base"), second=self.reference("Fastened"), id="FailedJoint")
        self.assertSnapshotEqual(before)
        self.assertIsNone(self.doc.getObject("FailedJoint"))
        self.joint("slider", "Fastened")
        before = self.snapshot()
        with patch.object(native, "solve", side_effect=OperationError("assembly_solver_failed", "Injected edit failure", native_code=-99)):
            self.reject("edit_assembly_joint", code="assembly_solver_failed", joint="SliderJoint", joint_type="revolute",
                        first=self.reference("Base", "Face1"), second=self.reference("Fastened", "Face1"))
        self.assertSnapshotEqual(before)
        with patch.object(native, "solve", side_effect=OperationError("assembly_solver_failed", "Injected movement failure", native_code=-99)):
            self.reject("move_assembly_joint", code="assembly_solver_failed", joint="SliderJoint", value=40)
        self.assertSnapshotEqual(before)
        self.assertEqual(self.core.inspect(self.doc)["build_status"], "valid")

    def test_fcstd_reopen_relocation_embedded_policy_and_instance_export(self):
        self.fixture()
        self.joint("fixed", "Fastened")
        self.joint("revolute", "Rotor")
        self.joint("slider", "Carriage")
        self.call("move_assembly_joint", joint="RevoluteJoint", value=37)
        self.call("move_assembly_joint", joint="SliderJoint", value=23)
        identities = {instance["id"] for instance in self.state["assembly"]["instances"]}
        placements = {identity: self.placement(identity).copy() for identity in identities}
        native = self.folder / "solved-assembly.FCStd"
        self.call("save", path=str(native))
        relocated_folder = self.folder / "relocated-assembly-deliverables"
        relocated_folder.mkdir()
        relocated = relocated_folder / native.name
        shutil.copy2(native, relocated)
        self.source.rename(self.folder / "original-source-preserved.FCStd")
        manifest = self.core.checkpoint(self.doc, force=True)
        self.assertTrue(manifest.is_file())
        App.closeDocument(self.doc.Name)
        self.call("recover", path=str(manifest))
        self.assertIsNone(self.state["native_file"])
        self.assertEqual(self.state["build_status"], "valid")
        self.assertEqual(len(self.state["assembly"]["joints"]), 3)
        for identity, placement in placements.items():
            self.assertPlacementEqual(self.placement(identity), placement)
            self.assertIs(self.doc.getObject(identity).LinkedObject.Document, self.doc)
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(relocated))
        self.assertEqual(self.state["build_status"], "valid")
        self.assertEqual({part["id"] for part in self.state["assembly"]["instances"]}, identities)
        self.assertEqual(len(self.state["assembly"]["joints"]), 3)
        for identity, placement in placements.items():
            self.assertPlacementEqual(self.placement(identity), placement)
            self.assertIs(self.doc.getObject(identity).LinkedObject.Document, self.doc)
        exported = relocated_folder / "solved-occurrences.step"
        self.call("export", path=str(exported))
        shape = Part.read(str(exported))
        expected = self.state["measurements"]
        self.assertEqual(len(shape.Solids), 4)
        self.assertAlmostEqual(shape.Volume, 4 * 4 * 6 * 8, places=6)
        actual = measurements(shape)
        for bound in ("min", "max"):
            for left, right in zip(actual["bbox_mm"][bound], expected["bbox_mm"][bound]):
                self.assertAlmostEqual(left, right, places=5)
        provenance = json.loads(exported.with_suffix(".step.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["sha256"], hashlib.sha256(exported.read_bytes()).hexdigest())
        self.assertEqual(provenance["revision"], self.state["revision"])

    def test_original_three_solid_steps_insert_explicit_bodies_and_preserve_sources(self):
        source_paths = [ROOT.parents[1] / "Onshape examples" / filename
                        for filename in ("Dodec pipe mount.step", "Dodec Hub Conformal.step")]
        digests = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
        projects = []
        original_metrics = {}
        expected_volume = 0
        for path in source_paths:
            self.call("import_step", path=str(path))
            native = self.folder / (path.stem + ".FCStd")
            self.call("save", path=str(native))
            body_ids = list(self.state["import_source"]["body_ids"])
            self.assertEqual(len(body_ids), 3)
            projects.append((native, body_ids))
            for body in self.state["bodies"]:
                original_metrics[(str(native), body["id"])] = body["measurements"]
                expected_volume += body["measurements"]["volume_mm3"]
            App.closeDocument(self.doc.Name)
        self.call("new", name="Original STEP geometry assembly")
        self.call("create_assembly")
        for index, (path, body_ids) in enumerate(projects):
            candidates = self.call("assembly_candidates", path=str(path))["candidates"]
            self.assertEqual({item["id"] for item in candidates}, set(body_ids))
            for body_index, body_id in enumerate(body_ids):
                identity = f"Original{index}Body{body_index}"
                self.insert(identity, path=path, source_id=body_id)
                current = next(item["measurements"] for item in self.state["bodies"] if item["id"] == identity)
                baseline = original_metrics[(str(path), body_id)]
                self.assertAlmostEqual(current["volume_mm3"], baseline["volume_mm3"], delta=baseline["volume_mm3"] * 1e-10)
                for bound in ("min", "max"):
                    for left, right in zip(current["bbox_mm"][bound], baseline["bbox_mm"][bound]):
                        self.assertAlmostEqual(left, right, places=6)
        repeated_path, repeated_ids = projects[0]
        source_shape = self.doc.getObject("Original0Body0").Shape
        expected_volume += source_shape.Volume
        self.insert("RepeatedPipeBody", path=repeated_path, source_id=repeated_ids[0])
        self.call("move_assembly_instance", instance="RepeatedPipeBody", position_mm=[300, 0, 0], rotation_xyzw=[0, 0, 0, 1])
        self.assertEqual(self.state["measurements"]["solid_count"], 7)
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], expected_volume, delta=expected_volume * 1e-9)
        self.assertEqual(self.state["assembly"]["joints"], [])
        output = self.folder / "original-step-occurrences.step"
        self.call("export", path=str(output))
        self.assertEqual(len(Part.read(str(output)).Solids), 7)
        self.assertTrue(all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in digests.items()))

    def test_original_steps_insert_directly_as_three_solid_choices(self):
        self.call("create_assembly")
        names = set(App.listDocuments())
        expected_volume = 0
        for source_index, filename in enumerate(("Dodec pipe mount.step", "Dodec Hub Conformal.step")):
            path = ROOT.parents[1] / "Onshape examples" / filename
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            baseline = Part.read(str(path)).Solids
            candidates = self.call("assembly_candidates", path=str(path))["candidates"]
            self.assertEqual([item["id"] for item in candidates], ["Solid1", "Solid2", "Solid3"])
            self.assertTrue(all(item["solid_count"] == 1 for item in candidates))
            self.assertEqual(set(App.listDocuments()), names)
            self.assertIs(App.ActiveDocument, self.doc)
            for index, (candidate, solid) in enumerate(zip(candidates, baseline)):
                identity = f"Direct{source_index}Solid{index}"
                self.insert(identity, path=path, source_id=candidate["id"])
                embedded = self.doc.getObject(identity).LinkedObject
                self.assertEqual(embedded.SourcePath, str(path))
                self.assertEqual(embedded.SourceSHA256, digest)
                self.assertEqual(embedded.SourceObject, candidate["id"])
                actual = next(item["measurements"] for item in self.state["bodies"] if item["id"] == identity)
                wanted = measurements(solid)
                expected_volume += wanted["volume_mm3"]
                for metric in ("volume_mm3", "area_mm2"):
                    self.assertAlmostEqual(actual[metric], wanted[metric], delta=abs(wanted[metric]) * 1e-10)
                for bound in ("min", "max"):
                    for left, right in zip(actual["bbox_mm"][bound], wanted["bbox_mm"][bound]):
                        self.assertAlmostEqual(left, right, places=6)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertEqual(self.state["measurements"]["solid_count"], 6)
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], expected_volume, delta=expected_volume * 1e-9)
        exported = self.folder / "direct-step-occurrences.step"
        self.call("export", path=str(exported))
        self.assertEqual(len(Part.read(str(exported)).Solids), 6)

    def test_step_choices_keep_nested_placements_and_ignore_reference_surfaces(self):
        first = Part.makeBox(2, 3, 4)
        second = Part.makeCylinder(1, 5)
        second.Placement = App.Placement(App.Vector(17, 11, 9), App.Rotation(App.Vector(0, 1, 0), 30))
        nested = Part.makeCompound([second])
        nested.Placement = App.Placement(App.Vector(7, 4, 3), App.Rotation(App.Vector(0, 0, 1), 45))
        mixed = Part.makeCompound([first, nested, Part.makePlane(2, 3, App.Vector(50, 0, 0))])
        path = self.folder / "positioned-mixed.STP"
        mixed.exportStep(str(path))
        expected = Part.read(str(path)).Solids
        before = self.snapshot()
        names = set(App.listDocuments())
        candidates = self.call("assembly_candidates", path=str(path))["candidates"]
        self.assertEqual([item["id"] for item in candidates], ["Solid1", "Solid2"])
        self.assertSnapshotEqual(before)
        self.assertEqual(set(App.listDocuments()), names)
        self.assertIs(App.ActiveDocument, self.doc)
        self.call("create_assembly")
        for index, (candidate, shape) in enumerate(zip(candidates, expected)):
            identity = "Placed" + str(index)
            self.insert(identity, path=path, source_id=candidate["id"])
            actual = next(item["measurements"] for item in self.state["bodies"] if item["id"] == identity)
            wanted = measurements(shape)
            self.assertAlmostEqual(actual["volume_mm3"], wanted["volume_mm3"], places=7)
            for bound in ("min", "max"):
                for left, right in zip(actual["bbox_mm"][bound], wanted["bbox_mm"][bound]):
                    self.assertAlmostEqual(left, right, places=6)

    def test_direct_step_instances_replay_undo_and_portable_saved_snapshot(self):
        path = self.folder / "portable-source.STEP"
        Part.makeBox(4, 6, 8, App.Vector(3, 7, 11)).exportStep(str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.call("create_assembly")
        before = self.doc.UndoCount
        request = {**self.request("insert_assembly_part", path=str(path), source_id="Solid1", id="First"),
                   "request_id": str(uuid.uuid4())}
        accepted = self.core.dispatch(request)
        self.assertTrue(accepted["ok"], accepted)
        self.state = accepted["result"]
        self.assertEqual(self.doc.UndoCount, before + 1)
        self.assertEqual(self.core.dispatch(request), accepted)
        self.assertEqual(len(self.state["assembly"]["instances"]), 1)
        self.insert("Second", path=path, source_id="Solid1")
        self.assertIs(self.doc.getObject("First").LinkedObject, self.doc.getObject("Second").LinkedObject)
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Second"))
        self.call("redo")
        self.assertIsNotNone(self.doc.getObject("Second"))
        snapshot = self.state["measurements"]
        native = self.folder / "portable-direct-step-assembly.FCStd"
        self.call("save", path=str(native))
        App.closeDocument(self.doc.Name)
        path.unlink()
        self.call("open", path=str(native))
        self.call("rebuild")
        self.assertEqual(self.state["build_status"], "valid")
        self.assertEqual(self.state["measurements"], snapshot)
        for identity in ("First", "Second"):
            self.assertEqual(self.doc.getObject(identity).LinkedObject.SourceSHA256, digest)
            self.assertIs(self.doc.getObject(identity).LinkedObject.Document, self.doc)
        exported = self.folder / "portable-direct-step-assembly.step"
        self.call("export", path=str(exported))
        self.assertEqual(len(Part.read(str(exported)).Solids), 2)

    def test_direct_step_invalid_sources_and_read_race_leave_assembly_intact(self):
        from kurtshape import assembly as native
        self.fixture(count=2)
        before = self.snapshot()
        names = set(App.listDocuments())
        broken = self.folder / "broken.step"
        broken.write_text("This is not STEP geometry", encoding="utf-8")
        surface = self.folder / "surface.stp"
        Part.makePlane(2, 3).exportStep(str(surface))
        for path, code in ((broken, "invalid_assembly_source"), (surface, "empty_assembly_source")):
            self.reject("assembly_candidates", code=code, path=str(path))
            self.reject("insert_assembly_part", code=code, path=str(path), source_id="Solid1")
            self.assertSnapshotEqual(before)
            self.assertEqual(set(App.listDocuments()), names)
        valid = self.folder / "read-race.step"
        Part.makeBox(2, 3, 4).exportStep(str(valid))
        with patch.object(native.Part, "read", return_value=Part.Shape()):
            self.reject("assembly_candidates", code="empty_assembly_source", path=str(valid))
        original = valid.read_bytes()
        def changed_file(raw):
            valid.write_bytes(original + b"\nChanged during read")
            return Part.makeBox(2, 3, 4)
        for operation in ("assembly_candidates", "insert_assembly_part"):
            valid.write_bytes(original)
            with patch.object(native.Part, "read", side_effect=changed_file):
                args = {"path": str(valid)}
                if operation == "insert_assembly_part":
                    args.update(source_id="Solid1", id="RejectedSTEP")
                self.reject(operation, code="assembly_source_changed", **args)
            self.assertSnapshotEqual(before)
            self.assertEqual(set(App.listDocuments()), names)
            self.assertIs(App.ActiveDocument, self.doc)

    def test_idle_inspection_does_not_resolve_sources_or_run_native_solver(self):
        from kurtshape import assembly as native
        from kurtshape import core as controller_module
        self.fixture(count=2)
        self.joint("revolute", "Fastened")
        accepted = self.state["revision"]
        with patch.object(native, "solve", side_effect=AssertionError("Idle inspection must not solve")), \
             patch.object(native, "_source_document", side_effect=AssertionError("Idle inspection must not reread source files")), \
             patch.object(native, "_geometry_fingerprint", side_effect=AssertionError("Idle inspection must not serialize embedded BReps")), \
             patch.object(controller_module, "measurements", wraps=controller_module.measurements) as brep, \
             patch.object(controller_module, "intent_signature", wraps=controller_module.intent_signature) as intent:
            for _ in range(25):
                state = self.core.inspect(self.doc)
                self.assertEqual(state["revision"], accepted)
                self.assertEqual(state["build_status"], "valid")
            self.assertEqual(brep.call_count, 0)
            self.assertEqual(intent.call_count, 0)
        changed = self.placement("Fastened").copy()
        changed.Base = App.Vector(3, 0, 0)
        self.doc.getObject("Fastened").Placement = changed
        response = self.core.dispatch({**self.request("solve_assembly"), "expected_revision": accepted})
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "stale_revision")

    def test_single_level_busy_and_native_edit_guards_preserve_assembly(self):
        self.fixture(count=2)
        before = self.snapshot()
        self.reject("create_assembly", id="NestedAssembly")
        self.assertSnapshotEqual(before)
        self.core.busy = True
        try:
            self.reject("ground_assembly_instance", code="busy", instance="Fastened")
            self.reject("assembly_candidates", code="busy", path=str(self.source))
        finally:
            self.core.busy = False
        self.assertSnapshotEqual(before)
        self.call("create_sketch", id="EditingGuard")
        self.call("begin_sketch_edit", feature="EditingGuard")
        editing_before = intent_signature(self.doc)
        self.reject("ground_assembly_instance", code="sketch_edit_active", instance="Fastened")
        self.reject("insert_assembly_part", code="sketch_edit_active", path=str(self.source), source_id="SourceBody")
        self.assertEqual(intent_signature(self.doc), editing_before)
        self.call("finish_sketch_edit", cancel=True)

    def test_native_edge_and_face_connectors_preserve_allowed_motion(self):
        self.fixture(count=3)
        self.joint("revolute", "Fastened", identity="EdgeHinge", first_sub="Edge1", second_sub="Edge1")
        self.call("move_assembly_joint", joint="EdgeHinge", value=61)
        hinge = self.doc.getObject("EdgeHinge")
        relative = (self.placement("Base") * hinge.Placement1).inverse() * (self.placement("Fastened") * hinge.Placement2)
        self.assertLess(relative.Base.Length, 1e-6)
        self.assertAlmostEqual(relative.Rotation.Angle, math.radians(61), places=6)
        self.joint("slider", "Rotor", identity="FaceSlider", first_sub="Face1", second_sub="Face1")
        self.call("move_assembly_joint", joint="FaceSlider", value=11)
        slider = self.doc.getObject("FaceSlider")
        relative = (self.placement("Base") * slider.Placement1).inverse() * (self.placement("Rotor") * slider.Placement2)
        self.assertAlmostEqual(relative.Base.x, 0, places=6)
        self.assertAlmostEqual(relative.Base.y, 0, places=6)
        self.assertAlmostEqual(relative.Base.z, 11, places=6)
        self.assertLess(relative.Rotation.Angle, 1e-6)

    def test_native_unresolved_placement_blocks_export_until_explicit_solve(self):
        self.fixture(count=2)
        self.joint("slider", "Fastened")
        accepted = self.state["revision"]
        changed = self.placement("Fastened").copy()
        changed.Base = App.Vector(4, 3, 12)
        self.doc.getObject("Fastened").Placement = changed
        self.call("inspect")
        self.assertNotEqual(self.state["revision"], accepted)
        self.assertIn(self.state["build_status"], {"needs_rebuild", "failed"})
        self.assertIsNone(self.state["measurements"])
        self.assertTrue(all(item["measurements"] is None and item["build_status"] in {"needs_rebuild", "failed"}
                            for item in self.state["bodies"]))
        destination = self.folder / "unresolved-occurrences.step"
        self.reject("export", path=str(destination))
        self.assertFalse(destination.exists())
        self.call("solve_assembly")
        self.assertEqual(self.state["build_status"], "valid")
        self.assertAlmostEqual(self.placement("Fastened").Base.x, 0, places=6)
        self.assertAlmostEqual(self.placement("Fastened").Base.y, 0, places=6)
        self.call("export", path=str(destination))
        self.assertEqual(len(Part.read(str(destination)).Solids), 2)

    def test_source_script_and_nested_link_safeguards_are_not_weakened(self):
        self.fixture(count=2)
        before = self.snapshot()
        for kind in ("script", "nested-link"):
            with self.subTest(kind=kind):
                source = App.newDocument("UnsafeAssemblySource")
                try:
                    solid = source.addObject("Part::Feature", "Solid")
                    solid.Shape = Part.makeBox(2, 3, 4)
                    if kind == "script":
                        source.addObject("App::FeaturePython", "ArbitraryScript")
                    else:
                        source.addObject("App::Link", "NestedLink").setLink(solid)
                    source.recompute()
                    path = self.folder / (kind + ".FCStd")
                    source.saveAs(str(path))
                finally:
                    App.closeDocument(source.Name)
                    App.setActiveDocument(self.doc.Name)
                names = set(App.listDocuments())
                self.reject("assembly_candidates", code="unsafe_assembly_source", path=str(path))
                self.reject("insert_assembly_part", code="unsafe_assembly_source", path=str(path), source_id="Solid")
                self.assertEqual(set(App.listDocuments()), names)
                self.assertSnapshotEqual(before)

    def test_embedded_source_native_geometry_change_rejects_until_undo_restores_snapshot(self):
        self.fixture(count=2)
        self.joint("revolute", "Fastened")
        source = self.doc.getObject("Base").LinkedObject
        accepted_revision = self.state["revision"]
        baseline_volume = source.Shape.Volume
        self.doc.openTransaction("Native source geometry alteration")
        source.Shape = Part.makeBox(9, 6, 8)
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertNotEqual(self.state["revision"], accepted_revision)
        self.assertEqual(self.state["build_status"], "failed")
        self.assertIsNone(self.state["measurements"])
        self.assertTrue(all(item["measurements"] is None and item["build_status"] == "failed" for item in self.state["bodies"]))
        destination = self.folder / "tampered-embedded-occurrences.step"
        self.reject("export", path=str(destination))
        self.assertFalse(destination.exists())
        self.reject("solve_assembly")
        self.assertEqual(self.core.inspect(self.doc)["build_status"], "failed")
        self.call("undo")
        self.assertAlmostEqual(source.Shape.Volume, baseline_volume, places=6)
        self.assertEqual(self.state["build_status"], "valid")
        self.call("export", path=str(destination))
        self.assertEqual(len(Part.read(str(destination)).Solids), 2)

    def test_marked_embedded_source_with_python_property_is_not_trusted_or_adoptable(self):
        from kurtshape import assembly as native
        self.fixture(count=2)
        source = self.doc.getObject("Base").LinkedObject
        source.addProperty("App::PropertyPythonObject", "Proxy")
        source.Proxy = {"arbitrary": "untrusted scripted payload"}
        self.call("inspect")
        self.assertFalse(native.safe_object(source))
        self.assertIn(source.Name, self.state["unsupported_objects"])
        self.assertEqual(self.state["build_status"], "failed")
        self.assertIsNone(self.state["measurements"])
        destination = self.folder / "unsafe-source-adoption.FCStd"
        self.reject("adopt", code="unsupported_adoption", path=str(destination))
        self.assertFalse(destination.exists())
        self.reject("solve_assembly")


if __name__ == "__main__":
    unittest.main(verbosity=2)
