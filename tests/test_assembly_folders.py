"""Assembly UX item 3: instance folders as assembly presentation metadata."""
import json
import unittest

from test_assembly import AssemblyWorkflowTests
from kurtshape import assembly, assembly_folders as folders


class FolderStructureTests(unittest.TestCase):
    def test_paths_ensure_move_rename_remove(self):
        data = folders.empty()
        data = folders.moved(data, ["Bolt1", "Bolt2"], "Fasteners/M3")
        data = folders.moved(data, ["Frame1"], "Frame")
        self.assertEqual(folders.paths(data["folders"]), ["Fasteners", "Fasteners/M3", "Frame"])
        self.assertEqual(data["membership"], {"Bolt1": "Fasteners/M3", "Bolt2": "Fasteners/M3", "Frame1": "Frame"})
        self.assertEqual(folders.counts(data, ["Bolt1", "Bolt2", "Frame1", "Loose"]),
                         {"Fasteners": 2, "Fasteners/M3": 2, "Frame": 1})
        renamed = folders.renamed(data, "Fasteners", "Hardware")
        self.assertEqual(folders.paths(renamed["folders"]), ["Hardware", "Hardware/M3", "Frame"])
        self.assertEqual(renamed["membership"]["Bolt1"], "Hardware/M3")
        self.assertEqual(data["membership"]["Bolt1"], "Fasteners/M3", "helpers return copies")
        removed = folders.removed(renamed, "Hardware")
        self.assertEqual(folders.paths(removed["folders"]), ["M3", "Frame"])
        self.assertEqual(removed["membership"], {"Bolt1": "M3", "Bolt2": "M3", "Frame1": "Frame"})
        flat = folders.removed(removed, "M3")
        self.assertEqual(flat["membership"], {"Frame1": "Frame"}, "members of a removed top folder go to the root")
        back = folders.moved(flat, ["Frame1"], None)
        self.assertEqual(back["membership"], {})
        self.assertEqual(folders.paths(back["folders"]), ["Frame"], "an emptied folder stays")

    def test_validation(self):
        for bad in ([{"name": ""}], [{"name": "a/b"}], [{"name": "A"}, {"name": "A"}], [{"name": "A", "x": 1}],
                    "Fasteners", [3], [{"name": "x" * 121}]):
            with self.assertRaises(folders.FolderError, msg=repr(bad)):
                folders.normalize_tree(bad)
        for path in ("A//B", "/A", 5, "A/" + "/".join(["x"] * 16)):
            with self.assertRaises(folders.FolderError, msg=repr(path)):
                folders.split(path)
        self.assertEqual(folders.normalize_tree(["A/B", "A/C", {"name": " D ", "children": []}]),
                         [{"name": "A", "children": [{"name": "B", "children": []}, {"name": "C", "children": []}]},
                          {"name": "D", "children": []}])
        with self.assertRaises(folders.FolderError):
            folders.structure(["A"], {"Ghost": "A"}, ["Real"])
        with self.assertRaises(folders.FolderError):
            folders.structure(["A"], {"Real": "B"}, ["Real"])
        with self.assertRaises(folders.FolderError):
            folders.renamed(folders.moved(folders.empty(), [], "A/B"), "A/B", "x/y")


class AssemblyFolderTests(unittest.TestCase):
    for _name in ("setUp", "tearDown", "doc", "request", "call", "reject", "source_project", "insert", "fixture",
                  "joint"):
        locals()[_name] = AssemblyWorkflowTests.__dict__[_name]
    reference = staticmethod(AssemblyWorkflowTests.reference)

    def rows(self):
        assembly_state = self.call("inspect")["assembly"]
        return {row["id"]: row["folder"] for row in assembly_state["instances"]}, assembly_state["folders"]

    def test_operations_place_move_and_report_folders(self):
        self.call("create_assembly", id="Asm", folder="Frame")
        self.call("insert_assembly_part", path=str(self.source), source_id="SourceBody", id="Rail", folder="Frame")
        self.call("insert_assembly_part", path=str(self.source), source_id="SourceBody", id="Bolt", folder="Fasteners/M3")
        self.call("insert_assembly_part", path=str(self.source), source_id="SourceBody", id="Loose")
        membership, tree = self.rows()
        self.assertEqual(membership, {"Rail": "Frame", "Bolt": "Fasteners/M3", "Loose": None})
        self.assertEqual(folders.paths(tree), ["Frame", "Fasteners", "Fasteners/M3"])
        before_order = [obj.Name for obj in assembly.result_objects(self.doc)]
        revision = self.state["revision"]
        self.call("move_assembly_instances", instances=["Loose", "Rail"], folder="Fasteners")
        self.assertNotEqual(self.state["revision"], revision)
        membership, _ = self.rows()
        self.assertEqual(membership, {"Rail": "Fasteners", "Bolt": "Fasteners/M3", "Loose": "Fasteners"})
        self.assertEqual([obj.Name for obj in assembly.result_objects(self.doc)], before_order,
                         "folders never reorder or regroup native occurrences")
        self.assertEqual(self.doc.getObject("Asm").Group[0].TypeId, "Assembly::JointGroup")
        self.call("move_assembly_instances", instances=["Rail"], folder=None)
        self.assertIsNone(self.rows()[0]["Rail"])
        self.call("undo")
        self.assertEqual(self.rows()[0]["Rail"], "Fasteners", "one undo step restores the move")
        self.reject("move_assembly_instances", "missing_assembly_instance", instances=["Ghost"], folder="Frame")
        self.reject("move_assembly_instances", "invalid_assembly_folders", instances=["Rail"], folder="A//B")
        self.reject("insert_assembly_part", "invalid_assembly_folders", path=str(self.source), source_id="SourceBody",
                    id="Bad", folder="x/")
        self.assertIsNone(self.doc.getObject("Bad"), "a bad folder rejects before the occurrence is created")
        stale = self.request("move_assembly_instances", instances=["Rail"], folder="Frame")
        stale["expected_revision"] = revision
        response = self.core.dispatch(stale)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "stale_revision")

    def test_set_whole_structure_keeps_or_replaces_membership(self):
        self.fixture(count=3)
        self.call("set_assembly_folders", folders=[{"name": "Motion", "children": [{"name": "Rotor", "children": []}]},
                                                   "Static"],
                  membership={"Rotor": "Motion/Rotor", "Base": "Static"})
        membership, tree = self.rows()
        self.assertEqual(membership, {"Base": "Static", "Fastened": None, "Rotor": "Motion/Rotor"})
        # Omitted membership keeps the entries whose folder survives.
        self.call("set_assembly_folders", folders=["Static", "Empty"])
        membership, tree = self.rows()
        self.assertEqual(membership, {"Base": "Static", "Fastened": None, "Rotor": None})
        self.assertEqual(folders.paths(tree), ["Static", "Empty"])
        self.reject("set_assembly_folders", "invalid_assembly_folders", folders=["Static"], membership={"Ghost": "Static"})
        self.reject("set_assembly_folders", "invalid_assembly_folders", folders=[{"name": "A/B"}])
        self.reject("set_assembly_folders", "invalid_assembly_folders", folders=["A"], membership={"Base": "B"})

    def test_folders_survive_save_and_reopen(self):
        self.fixture(count=2)
        self.joint("fixed", "Fastened", identity="Bolted")
        self.call("move_assembly_instances", instances=["Fastened"], folder="Hardware/Bolts")
        self.call("set_assembly_folders", folders=["Hardware/Bolts", "Spare/Empty"])
        path = self.folder / "folders.FCStd"
        self.call("save", path=str(path))
        self.call("close_document")
        reopened = self.call("open", path=str(path))
        self.assertEqual(reopened["build_status"], "valid", reopened.get("build_errors"))
        membership, tree = self.rows()
        self.assertEqual(membership, {"Base": None, "Fastened": "Hardware/Bolts"})
        self.assertEqual(folders.paths(tree), ["Hardware", "Hardware/Bolts", "Spare", "Spare/Empty"],
                         "an empty folder survives save and reopen")
        stored = json.loads(self.doc.getObject("AcceptanceAssembly").KurtShapeInstanceFolders)
        self.assertEqual(stored["membership"], {"Fastened": "Hardware/Bolts"})
        joints = self.call("inspect")["assembly"]["joints"]
        self.assertEqual([joint["id"] for joint in joints], ["Bolted"])

    def test_deleting_a_foldered_instance_drops_its_membership(self):
        self.fixture(count=3)
        self.call("move_assembly_instances", instances=["Rotor", "Fastened"], folder="Moving")
        self.call("delete_assembly_object", feature="Rotor")
        membership, tree = self.rows()
        self.assertEqual(membership, {"Base": None, "Fastened": "Moving"})
        stored = json.loads(self.doc.getObject("AcceptanceAssembly").KurtShapeInstanceFolders)
        self.assertNotIn("Rotor", stored["membership"])
        self.call("delete_assembly_object", feature="Fastened")
        membership, tree = self.rows()
        self.assertEqual(folders.paths(tree), ["Moving"], "the folder stays, empty")
        # A new occurrence reusing the id starts at the root.
        self.insert("Rotor")
        self.assertIsNone(self.rows()[0]["Rotor"])
        self.call("undo")
        self.call("undo")
        self.assertEqual(self.rows()[0].get("Fastened"), "Moving", "undo restores the occurrence and its folder")

    def test_damaged_property_shows_everything_at_the_root(self):
        self.fixture(count=2)
        asm = self.doc.getObject("AcceptanceAssembly")
        folders.write(asm, folders.moved(folders.empty(), ["Base"], "A"))
        asm.KurtShapeInstanceFolders = "{not json"
        self.assertEqual(folders.read(asm), folders.empty())
        state = assembly.inspect(self.doc)
        self.assertEqual(state["folders"], [])
        self.assertTrue(all(row["folder"] is None for row in state["instances"]))

    def test_refresh_accepts_a_folder(self):
        self.call("create_assembly", id="Asm")
        self.insert("Solo")
        self.call("refresh_assembly_part", instance="Solo", folder="Refreshed")
        self.assertEqual(self.rows()[0]["Solo"], "Refreshed")


if __name__ == "__main__":
    unittest.main()
