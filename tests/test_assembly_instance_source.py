"""Assembly UX item 4: where an occurrence came from (assembly_instance_source)."""
import unittest

import FreeCAD as App
import Part

from test_assembly import AssemblyWorkflowTests
from kurtshape import assembly


class AssemblyInstanceSourceTests(unittest.TestCase):
    for _name in ("setUp", "tearDown", "doc", "request", "call", "reject", "source_project", "insert"):
        locals()[_name] = AssemblyWorkflowTests.__dict__[_name]

    def step_source(self):
        path = self.folder / "imported-block.step"
        Part.makeBox(3, 4, 5).exportStep(str(path))
        candidate = self.call("assembly_candidates", path=str(path))["candidates"][0]["id"]
        return path, candidate

    def test_fcstd_and_step_sources_with_kind_existence_and_sharing(self):
        self.call("create_assembly", id="Asm")
        self.insert("First")
        self.insert("Second")
        step, candidate = self.step_source()
        self.call("insert_assembly_part", path=str(step), source_id=candidate, id="Imported")
        native = self.call("assembly_instance_source", instance="First")
        self.assertEqual(native["path"], str(self.source.resolve()))
        self.assertEqual(native["kind"], "fcstd")
        self.assertTrue(native["exists"])
        self.assertEqual(native["object"], "SourceBody")
        self.assertEqual(native["shared_with"], ["Second"])
        self.assertEqual(native["open_documents"], [])
        imported = self.call("assembly_instance_source", instance="Imported")
        self.assertEqual(imported["kind"], "step")
        self.assertEqual(imported["path"], str(step.resolve()))
        self.assertTrue(imported["exists"])
        self.assertEqual(imported["shared_with"], [])
        revision = self.state["revision"]
        self.assertEqual(self.state["revision"], revision, "a read leaves the revision alone")

    def test_open_source_document_and_missing_file(self):
        self.call("create_assembly", id="Asm")
        self.insert("Only")
        opened = App.openDocument(str(self.source))
        try:
            info = self.call("assembly_instance_source", instance="Only")
            self.assertEqual(info["open_documents"], [opened.Name])
        finally:
            App.closeDocument(opened.Name)
        moved = self.source.with_name("moved-away.FCStd")
        self.source.rename(moved)
        info = self.call("assembly_instance_source", instance="Only")
        self.assertFalse(info["exists"])
        self.assertEqual(info["path"], str(self.source.resolve()), "the recorded path is reported even when missing")
        self.assertEqual(info["open_documents"], [])

    def test_unknown_or_non_instance_rejects(self):
        self.call("create_assembly", id="Asm")
        self.insert("Only")
        self.reject("assembly_instance_source", "missing_assembly_instance", instance="Ghost")
        embedded = self.doc.getObject("Only").LinkedObject.Name
        self.reject("assembly_instance_source", "missing_assembly_instance", instance=embedded)

    def test_kind_classification(self):
        self.assertEqual(assembly.source_kind("C:/a/b.STEP"), "step")
        self.assertEqual(assembly.source_kind("b.stp"), "step")
        self.assertEqual(assembly.source_kind("C:/a/b.FCStd"), "fcstd")
        self.assertIsNone(assembly.source_kind(""))
        self.assertIsNone(assembly.source_kind("part.iges"))


if __name__ == "__main__":
    unittest.main()
