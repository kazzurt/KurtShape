"""Assembly UX item 7: find occurrences whose saved source changed and update them."""
import base64
import hashlib
import shutil
import unittest
import zipfile

import FreeCAD as App
import Part

from test_assembly import AssemblyWorkflowTests
from kurtshape import assembly_sync
from kurtshape.assembly_refresh_button import AssemblyRefresh


class HeadlessPanel:
    """The parts of Panel that AssemblyRefresh uses, over the test's Controller."""

    MEASURE = False

    def __init__(self, test):
        self.test, self.messages, self.notices, self.last_operation_error = test, [], [], None

    @property
    def core(self):
        return self.test.core

    @property
    def state(self):
        return self.test.state

    @state.setter
    def state(self, value):
        self.test.state = value

    def document(self):
        return self.test.doc

    def assembly_state(self):
        return self.test.state.get("assembly") or {}

    def assembly_ready(self):
        return True

    def operation(self, op, **args):
        response = self.core.dispatch(self.test.request(op, **args))
        if not response["ok"]:
            self.last_operation_error = response["error"]
            return None
        self.test.state = response["result"]
        return response["result"]

    def refresh_assembly(self):
        pass

    def append_message(self, text, severity="info"):
        self.messages.append((severity, text))

    def notify(self, text, *args, detail=None):
        self.notices.append(text)


class AssemblyRefreshFlowTests(unittest.TestCase):
    for _name in ("setUp", "tearDown", "doc", "request", "call", "reject", "joint", "source_project"):
        locals()[_name] = AssemblyWorkflowTests.__dict__[_name]
    reference = staticmethod(AssemblyWorkflowTests.reference)

    def write_source(self, filename, shape):
        source = App.newDocument("RefreshFlowSource")
        try:
            body = source.addObject("PartDesign::Body", "SourceBody")
            body.newObject("PartDesign::Feature", "SourceSolid").Shape = shape
            source.recompute()
            path = self.folder / filename
            source.saveAs(str(path))
            return path
        finally:
            App.closeDocument(source.Name)
            App.setActiveDocument(self.doc.Name)

    def statuses(self):
        return {row["id"]: (row["source"]["status"], row["source"]["current_sha256"])
                for row in self.call("inspect")["assembly"]["instances"]}

    def test_stale_detection_update_and_rejected_joint(self):
        assembly_sync.clear()
        part_a = self.write_source("part-a.FCStd", Part.makeBox(4, 6, 8, App.Vector(1, 2, 0)))
        part_b = self.write_source("part-b.FCStd", Part.makeCylinder(2, 5))
        self.call("create_assembly", id="Asm")
        for identity, path in (("A1", part_a), ("A2", part_a), ("B", part_b)):
            self.call("insert_assembly_part", path=str(path), source_id="SourceBody", id=identity)
        self.call("move_assembly_instance", instance="B", position_mm=[30, 0, 0], rotation_xyzw=[0, 0, 0, 1])
        # Face1 is the box's x-min face; widening the box in +x keeps it exactly.
        self.joint("fixed", "A2", identity="Bolted", first="A1", first_sub="Face1", second_sub="Face1")
        self.call("save", path=str(self.folder / "flow.FCStd"))
        self.assertEqual({key: value[0] for key, value in self.statuses().items()},
                         {"A1": "current", "A2": "current", "B": "current"})
        refresher = AssemblyRefresh(HeadlessPanel(self))
        self.assertEqual(refresher.check(), ([], [], []))

        old_hash = self.doc.getObject("A1").LinkedObject.SourceSHA256
        self.write_source("part-a.FCStd", Part.makeBox(6, 6, 8, App.Vector(1, 2, 0)))
        new_hash = hashlib.sha256(part_a.read_bytes()).hexdigest()
        self.assertNotEqual(new_hash, old_hash)
        self.assertEqual(refresher.precheck(), [str(part_a)], "the pre-check sees the moved file without hashing")
        statuses = self.statuses()
        self.assertEqual(statuses["A1"], ("changed", new_hash))
        self.assertEqual(statuses["A2"], ("changed", new_hash))
        self.assertEqual(statuses["B"][0], "current")
        self.assertEqual(refresher.check()[0], ["A1", "A2"])

        report = refresher.update()
        self.assertEqual(sorted(report["updated"]), ["A1", "A2"])
        self.assertEqual(report["failed"], [])
        self.assertEqual(self.doc.getObject("A1").LinkedObject, self.doc.getObject("A2").LinkedObject,
                         "shared:all keeps one snapshot for both occurrences")
        self.assertEqual(self.doc.getObject("A1").LinkedObject.SourceSHA256, new_hash)
        joints = self.call("inspect")["assembly"]["joints"]
        self.assertEqual([joint["id"] for joint in joints], ["Bolted"], "the joint survives the update")
        self.assertEqual({key: value[0] for key, value in self.statuses().items()},
                         {"A1": "current", "A2": "current", "B": "current"})

        # Second change: the jointed face moves (A), and B changes too.
        self.write_source("part-a.FCStd", Part.makeBox(6, 6, 8, App.Vector(2, 2, 0)))
        self.write_source("part-b.FCStd", Part.makeCylinder(3, 5))
        before_a = self.doc.getObject("A1").LinkedObject.SourceSHA256
        report = refresher.update()
        self.assertEqual(report["updated"], ["B"])
        self.assertEqual(sorted(report["failed"]), ["A1", "A2"])
        messages = " ".join(text for _, text in refresher.panel.messages)
        self.assertIn("joint Bolted", messages)
        self.assertIn("assembly_refresh_reference_changed", messages)
        self.assertEqual(self.doc.getObject("A1").LinkedObject.SourceSHA256, before_a, "A kept its accepted geometry")
        self.assertEqual(self.doc.getObject("B").LinkedObject.SourceSHA256, hashlib.sha256(part_b.read_bytes()).hexdigest())
        state = self.call("inspect")
        self.assertEqual(state["build_status"], "valid", state.get("build_errors"))
        self.assertEqual(self.statuses()["A1"][0], "changed")
        self.assertEqual(self.statuses()["B"][0], "current")

    def test_missing_source_and_cache_reuse(self):
        assembly_sync.clear()
        part = self.write_source("part-c.FCStd", Part.makeBox(2, 2, 2))
        digest = hashlib.sha256(part.read_bytes()).hexdigest()
        self.assertEqual(assembly_sync.source_state(str(part), digest, hash=False)["status"], "unchecked")
        self.assertEqual(assembly_sync.source_state(str(part), digest)["status"], "current")
        calls = []
        original = assembly_sync.sha256
        try:
            assembly_sync.sha256 = lambda path: calls.append(path) or original(path)
            self.assertEqual(assembly_sync.source_state(str(part), digest)["status"], "current")
            self.assertEqual(calls, [], "an unmoved file is not hashed again")
        finally:
            assembly_sync.sha256 = original
        moved = part.with_name("gone.FCStd")
        shutil.move(part, moved)
        self.assertEqual(assembly_sync.source_state(str(part), digest)["status"], "missing")
        self.assertEqual(assembly_sync.source_state("", digest)["status"], "unrecorded")
        self.assertTrue(assembly_sync.moved_since_check(str(part)), "a missing file counts as moved")

    def managed_project(self, filename):
        """A KurtShape project saved by the Controller (no GuiDocument.xml), then restore the assembly state."""
        assembly_state = self.state
        response = self.core.dispatch({"op": "new", "name": "GUI-saved part"})
        part = response["result"]
        def call(op, **args):
            nonlocal part
            reply = self.core.dispatch({"op": op, "document_id": part["document_id"], "expected_revision": part["revision"], **args})
            self.assertTrue(reply["ok"], reply)
            part = reply["result"]
        call("sketch_rectangle", id="Profile", width=6, height=4, body="Body")
        call("pad", id="Block", profile="Profile", length=3, body="Body")
        path = self.folder / filename
        call("save", path=str(path))
        call("close_document")
        self.state = assembly_state
        return path

    def with_gui(self, source, target, proxy_value, tempovis_value):
        def encoded(value):
            return base64.b64encode(value.encode()).decode()
        gui = ('<?xml version="1.0" encoding="utf-8"?><Document SchemaVersion="1"><ViewProviderData Count="2">'
               '<ViewProvider name="KurtShapeProject"><Properties Count="1">'
               '<Property name="Proxy" type="App::PropertyPythonObject" status="1">'
               f'<Python value="{encoded(proxy_value)}" encoded="yes" json="yes"/></Property></Properties></ViewProvider>'
               '<ViewProvider name="Profile"><Properties Count="1">'
               '<Property name="TempoVis" type="App::PropertyPythonObject" status="16777217">'
               f'<Python value="{encoded(tempovis_value)}" encoded="yes" json="yes"/></Property></Properties></ViewProvider>'
               '</ViewProviderData></Document>')
        with zipfile.ZipFile(source) as reader, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as writer:
            for item in reader.infolist():
                if item.filename != "GuiDocument.xml":
                    writer.writestr(item, reader.read(item.filename))
            writer.writestr("GuiDocument.xml", gui)
        return target

    def test_gui_saved_project_is_an_accepted_source(self):
        # A GUI save writes the metadata view proxy as JSON 1 and a null TempoVis on every edited sketch.
        self.call("create_assembly", id="Asm")
        part = self.managed_project("headless-part.FCStd")
        gui_saved = self.with_gui(part, self.folder / "gui-saved.FCStd", "1", "null")
        self.call("insert_assembly_part", path=str(gui_saved), source_id="Body", id="Edited")
        self.call("refresh_assembly_part", instance="Edited")
        for name, proxy, tempovis in (("scripted-tempovis.FCStd", "1", '{"x": 1}'),
                                      ("scripted-proxy.FCStd", '{"x": 1}', "null"),
                                      ("number-proxy.FCStd", "2", "null")):
            unsafe = self.with_gui(part, self.folder / name, proxy, tempovis)
            self.reject("insert_assembly_part", "unsafe_assembly_source", path=str(unsafe), source_id="Body", id="Bad")


if __name__ == "__main__":
    unittest.main()
