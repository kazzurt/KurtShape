"""Create and edit real PartDesign features with the bundled headless runtime.

Run from the project directory:
  runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin/python.exe -B tools/validate_modeling_workflows.py

Native setup follows the bundled PartDesignTests/TestLinearPattern.py,
TestPolarPattern.py, TestPipe.py, TestLoft.py and KurtShape's attached sketch
contract. Every feature is actual native document state, not substitute BRep.
This checks accepted geometry, dependencies, changes, native creation undo,
controller edit undo/redo, staged saving and a fresh recompute after reopening.
It does not exercise GUI toolbar selection, task dialogs or preview rendering.
Fixtures/profile are retained in a unique runtime/modeling-workflow-validation
folder. Originals and the user's open app are not touched.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import socket
import sys
import time
import traceback
import uuid


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runtime" / "modeling-workflow-validation" / (time.strftime("%Y-%m-%d_%H-%M-%S") + "_" + uuid.uuid4().hex[:8])
for directory in (RUN / "user-data", RUN / "temporary", RUN / "appdata", RUN / "fixtures"):
    directory.mkdir(parents=True, exist_ok=True)
os.environ.update(FREECAD_USER_HOME=str(RUN / "user-data"),
                  KURTSHAPE_SESSION_DIR=str(RUN / "user-data" / "session"),
                  APPDATA=str(RUN / "appdata"), LOCALAPPDATA=str(RUN / "appdata"),
                  TEMP=str(RUN / "temporary"), TMP=str(RUN / "temporary"),
                  PYTHONDONTWRITEBYTECODE="1")


def deny_network(*args, **kwargs):
    raise RuntimeError("Python networking disabled for native modeling workflow validation")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.socket.sendto = deny_network
socket.create_connection = deny_network
socket.getaddrinfo = deny_network
socket.gethostbyname = deny_network
socket.gethostbyname_ex = deny_network
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
import Sketcher
from kurtshape.bodies import bodies, owner, origin_plane
from kurtshape.core import Controller, native_intent


REPORT = {"passed": False, "engine": {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION},
          "network": "Python connect/connect_ex/sendto/create_connection/DNS denied; no bridge/server started.",
          "limits": "Headless synthetic native features; no GUI button/task/preview or Onshape parity claim. Physical disconnect and native C++ networking not intercepted. Only additive sweep/loft and feature patterns are covered.",
          "recipe": "tools/validate_modeling_workflows.py", "runtime_artifacts": str(RUN.relative_to(ROOT)),
          "api_sources": ["Mod/PartDesign/PartDesignTests/" + item for item in
                          ("TestLinearPattern.py", "TestPolarPattern.py", "TestPipe.py", "TestLoft.py")],
          "persistence_note": "FreeCAD 1.1.4 restores deprecated AttacherEngine display text from Engine 3D to Engine Plane for Attacher::AttachEnginePlane and uses the filename as document display label. Comparison checks authoritative AttacherType and every other object intent field exactly; only that known engine display alias is normalized, and the filename display label is checked separately.",
          "cases": []}


def persisted_intent(doc):
    state = native_intent(doc)
    for item in state:
        properties = item["properties"]
        if properties.get("AttacherType") == "Attacher::AttachEnginePlane" and properties.get("AttacherEngine") in {"Engine 3D", "Engine Plane"}:
            properties["AttacherEngine"] = "Engine Plane"
    return state


class Workflow:
    def __init__(self, name):
        self.name = name
        self.initial_documents = set(App.listDocuments())
        self.core = Controller()
        self.state = None
        self.checks = []
        self.call("new", name="Modeling workflow: " + name)
        self.body_id = bodies(self.doc)[0].Name

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    @property
    def body(self):
        return self.doc.getObject(self.body_id)

    def call(self, op, **args):
        request = {"op": op, **args}
        if op not in {"new", "open"}:
            self.state = self.core.inspect(self.doc)
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        if not response["ok"]:
            raise AssertionError(response)
        self.state = response["result"]
        return self.state

    def check(self, label, condition):
        if not condition:
            raise AssertionError(label)
        self.checks.append(label)

    def near(self, label, actual, expected, tolerance=1e-5):
        self.check(label, abs(actual - expected) <= tolerance)

    def accepted(self, label, volume):
        self.doc.recompute()
        self.state = self.core.inspect(self.doc)
        self.check(label + ": current valid solid", self.state["build_status"] == "valid")
        self.check(label + ": one real valid solid", len(self.body.Shape.Solids) == 1 and self.body.Shape.isValid())
        self.near(label + ": analytical volume", self.body.Shape.Volume, volume)
        self.near(label + ": controller volume agrees", self.state["measurements"]["volume_mm3"], volume)

    def native(self, label, mutation):
        self.doc.openTransaction("Modeling validation: " + label)
        try:
            mutation()
            self.doc.recompute()
            self.doc.commitTransaction()
        except Exception:
            self.doc.abortTransaction()
            raise
        self.state = self.core.inspect(self.doc)

    def creation_history(self, feature, before_volume, created_volume):
        self.call("undo")
        self.check(feature + ": creation undo removes feature", self.doc.getObject(feature) is None)
        if before_volume is None:
            self.check(feature + ": creation undo leaves sketches only", self.state["build_status"] == "sketch_only")
        else:
            self.accepted(feature + " creation undo", before_volume)
        self.call("redo")
        self.check(feature + ": creation redo restores native ownership", owner(self.doc, self.doc.getObject(feature)) == self.body)
        self.accepted(feature + " creation redo", created_volume)

    def edit_history(self, label, mutation, before_volume, after_volume, verify_before=None, verify_after=None):
        self.native(label, mutation)
        self.accepted(label, after_volume)
        if verify_after:
            verify_after()
        self.call("undo")
        self.accepted(label + " undo", before_volume)
        if verify_before:
            verify_before()
        self.call("redo")
        self.accepted(label + " redo", after_volume)
        if verify_after:
            verify_after()

    def dependencies(self, feature, expected):
        actual = {obj.Name for obj in self.doc.getObject(feature).OutList}
        self.check(feature + ": native dependency links", set(expected).issubset(actual))
        self.check(feature + ": owned by expected part", owner(self.doc, self.doc.getObject(feature)) == self.body)

    def reopen(self, volume, verify):
        path = RUN / "fixtures" / (self.name + ".FCStd")
        self.call("save", path=str(path))
        before_intent = persisted_intent(self.doc)
        identifier = self.state["document_id"]
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(path))
        self.check("reopen: same managed project identity", self.state["document_id"] == identifier)
        self.check("reopen: filename display label", self.doc.Label == path.stem)
        self.check("reopen: native intent preserved except documented display alias", persisted_intent(self.doc) == before_intent)
        self.call("rebuild")
        self.accepted("reopen and fresh rebuild", volume)
        verify()
        self.check("reopen: saved editable native file", path.is_file())
        return str(path.relative_to(ROOT))

    def close(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial_documents:
            App.closeDocument(name)


def linears(w):
    w.call("sketch_rectangle", id="PlateProfile", width=40, height=16)
    w.call("pad", id="Base", profile="PlateProfile", length=4)
    w.call("sketch_rectangle", id="BossProfile", width=4, height=4, x=4, y=4)
    w.native("boss profile at top of plate", lambda: setattr(w.doc.BossProfile, "AttachmentOffset", App.Placement(App.Vector(0, 0, 4), App.Rotation())))
    w.call("pad", id="Boss", profile="BossProfile", length=3)

    def create():
        pattern = w.body.newObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = [w.doc.Boss]
        axis = next(obj for obj in w.body.Origin.OriginFeatures if getattr(obj, "Role", "") == "X_Axis")
        pattern.Direction = (axis, [""])
        pattern.Length = 20
        pattern.Occurrences = 3
        pattern.Refine = True
        w.body.Tip = pattern

    base = 40 * 16 * 4
    w.native("create linear feature pattern", create)
    w.accepted("linear feature pattern", base + 3 * 4 * 4 * 3)
    w.creation_history("LinearPattern", base + 4 * 4 * 3, base + 3 * 4 * 4 * 3)
    w.edit_history("linear count 3 to 4", lambda: setattr(w.doc.LinearPattern, "Occurrences", 4), base + 3 * 48, base + 4 * 48)

    def points(spacing):
        for index in range(4):
            w.check("linear boss center " + str(index) + " at spacing " + str(spacing), w.body.Shape.isInside(App.Vector(6 + spacing * index, 6, 5), 1e-7, True))

    w.edit_history("linear spacing 20/3 to 9 mm", lambda: setattr(w.doc.LinearPattern, "Length", 27), base + 4 * 48, base + 4 * 48,
                   lambda: points(20 / 3), lambda: points(9))
    w.check("linear spacing changes actual instance location", not w.body.Shape.isInside(App.Vector(6 + 20 / 3, 6, 5), 1e-7, True))
    w.call("set_parameter", feature="Boss", parameter="Length", value=5)
    final = base + 4 * 4 * 4 * 5
    w.accepted("linear upstream boss height", final)
    w.call("undo")
    w.accepted("linear upstream boss height undo", base + 4 * 48)
    w.call("redo")
    w.accepted("linear upstream boss height redo", final)

    def verify():
        w.dependencies("LinearPattern", ["Boss"])
        w.dependencies("Boss", ["BossProfile"])
        w.check("linear parameters preserved", w.doc.LinearPattern.Occurrences == 4 and abs(w.doc.LinearPattern.Length.Value - 27) < 1e-7)
        points(9)
    verify()
    return w.reopen(final, verify)


def circulars(w):
    w.call("sketch_circle", id="PlateProfile", diameter=32, x=0, y=0)
    w.call("pad", id="Base", profile="PlateProfile", length=4)
    w.call("sketch_circle", id="BossProfile", diameter=3, x=8, y=0)
    w.native("boss profile on top of disk", lambda: setattr(w.doc.BossProfile, "AttachmentOffset", App.Placement(App.Vector(0, 0, 4), App.Rotation())))
    w.call("pad", id="Boss", profile="BossProfile", length=3)

    def create():
        pattern = w.body.newObject("PartDesign::PolarPattern", "CircularPattern")
        pattern.Originals = [w.doc.Boss]
        axis = next(obj for obj in w.body.Origin.OriginFeatures if getattr(obj, "Role", "") == "Z_Axis")
        pattern.Axis = (axis, [""])
        pattern.Angle = 360
        pattern.Occurrences = 4
        pattern.Refine = True
        w.body.Tip = pattern

    base = math.pi * 16**2 * 4
    boss = math.pi * 1.5**2 * 3
    w.native("create circular feature pattern", create)
    w.accepted("circular feature pattern", base + 4 * boss)
    w.creation_history("CircularPattern", base + boss, base + 4 * boss)
    w.edit_history("circular count 4 to 6", lambda: setattr(w.doc.CircularPattern, "Occurrences", 6), base + 4 * boss, base + 6 * boss)

    def points(step):
        for index in range(6):
            angle = math.radians(step * index)
            w.check("circular boss at " + str(step * index) + " degrees", w.body.Shape.isInside(App.Vector(8 * math.cos(angle), 8 * math.sin(angle), 5), 1e-7, True))

    w.edit_history("circular angular extent 360 to 180 degrees", lambda: setattr(w.doc.CircularPattern, "Angle", 180), base + 6 * boss, base + 6 * boss,
                   lambda: points(60), lambda: points(36))
    w.check("circular extent changes actual instance location", not w.body.Shape.isInside(App.Vector(0, -8, 5), 1e-7, True))
    w.call("set_parameter", feature="Boss", parameter="Length", value=5)
    final = base + 6 * math.pi * 1.5**2 * 5
    w.accepted("circular upstream boss height", final)
    w.call("undo")
    w.accepted("circular upstream boss height undo", base + 6 * boss)
    w.call("redo")
    w.accepted("circular upstream boss height redo", final)

    def verify():
        w.dependencies("CircularPattern", ["Boss"])
        w.check("circular parameters preserved", w.doc.CircularPattern.Occurrences == 6 and abs(w.doc.CircularPattern.Angle.Value - 180) < 1e-7)
        points(36)
    verify()
    return w.reopen(final, verify)


def make_plane(w, name, support, height, angle=0):
    plane = w.body.newObject("PartDesign::Plane", name)
    plane.AttachmentSupport = (support, [""])
    plane.MapMode = "FlatFace"
    plane.AttachmentOffset = App.Placement(App.Vector(0, 0, height), App.Rotation(App.Vector(1, 0, 0), angle))
    return plane


def offset_plane(w):
    w.native("create offset plane", lambda: make_plane(w, "OffsetPlane", origin_plane(w.body, "XY"), 7))
    w.call("undo")
    w.check("offset plane creation undo", w.doc.getObject("OffsetPlane") is None)
    w.call("redo")
    w.dependencies("OffsetPlane", [origin_plane(w.body, "XY").Name])
    w.call("sketch_rectangle", id="Profile", support={"feature": "OffsetPlane"}, width=4, height=3)
    w.call("pad", id="Pad", profile="Profile", length=2)
    w.accepted("extrude on offset plane", 24)

    def position(z):
        w.near("offset plane position " + str(z), w.doc.OffsetPlane.Placement.Base.z, z)
        w.near("attached sketch follows offset " + str(z), w.doc.Profile.Placement.Base.z, z)
        w.near("real solid follows offset " + str(z), w.body.Shape.BoundBox.ZMin, z)

    position(7)
    w.edit_history("offset plane edit 7 to 12 mm", lambda: setattr(w.doc.OffsetPlane, "AttachmentOffset", App.Placement(App.Vector(0, 0, 12), App.Rotation())), 24, 24,
                   lambda: position(7), lambda: position(12))

    def verify():
        w.dependencies("Profile", ["OffsetPlane"])
        w.dependencies("Pad", ["Profile"])
        position(12)
    verify()
    return w.reopen(24, verify)


def angled_plane(w):
    def create():
        support = make_plane(w, "SupportPlane", origin_plane(w.body, "XY"), 5)
        make_plane(w, "AngledPlane", support, 0, 30)
    w.native("create angled plane on an offset support", create)
    w.call("undo")
    w.check("angled plane creation undo", w.doc.getObject("SupportPlane") is None and w.doc.getObject("AngledPlane") is None)
    w.call("redo")
    w.dependencies("AngledPlane", ["SupportPlane"])
    w.call("sketch_rectangle", id="Profile", support={"feature": "AngledPlane"}, width=4, height=3)
    w.call("pad", id="Pad", profile="Profile", length=2)
    w.accepted("extrude on angled plane", 24)

    def orientation(angle):
        expected = App.Rotation(App.Vector(1, 0, 0), angle).multVec(App.Vector(0, 0, 1))
        plane_normal = w.doc.AngledPlane.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        sketch_normal = w.doc.Profile.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        w.near("angled plane normal " + str(angle), plane_normal.dot(expected), 1, 1e-7)
        w.near("attached sketch normal " + str(angle), sketch_normal.dot(expected), 1, 1e-7)
        projection = [point.dot(expected) for point in [vertex.Point for vertex in w.body.Shape.Vertexes]]
        w.near("solid depth along angled normal", max(projection) - min(projection), 2)

    w.edit_history("angled plane edit 30 to 60 degrees", lambda: setattr(w.doc.AngledPlane, "AttachmentOffset", App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 60))), 24, 24,
                   lambda: orientation(30), lambda: orientation(60))

    def height(z):
        w.near("upstream support position " + str(z), w.doc.AngledPlane.Placement.Base.z, z)
        w.near("sketch follows upstream plane " + str(z), w.doc.Profile.Placement.Base.z, z)
    w.edit_history("upstream support plane 5 to 10 mm", lambda: setattr(w.doc.SupportPlane, "AttachmentOffset", App.Placement(App.Vector(0, 0, 10), App.Rotation())), 24, 24,
                   lambda: height(5), lambda: height(10))

    def verify():
        w.dependencies("AngledPlane", ["SupportPlane"])
        w.dependencies("Profile", ["AngledPlane"])
        orientation(60)
        height(10)
    verify()
    return w.reopen(24, verify)


def sweep(w):
    w.call("sketch_circle", id="Profile", diameter=4, x=0, y=0)
    w.call("create_sketch", id="Path", plane="XZ")

    def path_geometry():
        path = w.doc.Path
        path.addGeometry(Part.LineSegment(App.Vector(), App.Vector(0, 20, 0)), False)
        path.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
        path.addConstraint(Sketcher.Constraint("PointOnObject", 0, 2, -2))
        constraint = path.addConstraint(Sketcher.Constraint("DistanceY", 0, 1, 0, 2, 20))
        path.renameConstraint(constraint, "PathLength")
    w.native("create constrained sweep path", path_geometry)

    def create():
        feature = w.body.newObject("PartDesign::AdditivePipe", "Sweep")
        feature.Profile = w.doc.Profile
        feature.Spine = (w.doc.Path, ["Edge1"])
        w.body.Tip = feature
    w.native("create additive sweep", create)
    w.accepted("straight-path circular sweep", math.pi * 2**2 * 20)
    w.creation_history("Sweep", None, math.pi * 2**2 * 20)
    w.call("set_parameter", feature="Path", parameter="PathLength", value=30)
    w.accepted("upstream sweep path length", math.pi * 2**2 * 30)
    w.call("undo")
    w.accepted("upstream sweep path undo", math.pi * 2**2 * 20)
    w.call("redo")
    w.call("set_parameter", feature="Profile", parameter="Diameter", value=6)
    final = math.pi * 3**2 * 30
    w.accepted("upstream sweep profile diameter", final)
    w.call("undo")
    w.accepted("upstream sweep profile undo", math.pi * 2**2 * 30)
    w.call("redo")

    def verify():
        w.dependencies("Sweep", ["Profile", "Path"])
        w.check("sweep path remains constrained", w.doc.Path.FullyConstrained)
        w.near("sweep path length persists", w.doc.Path.Geometry[0].length(), 30)
        w.near("sweep profile radius persists", w.doc.Profile.Geometry[0].Radius, 3)
    verify()
    return w.reopen(final, verify)


def loft(w):
    w.call("sketch_circle", id="Profile", diameter=8, x=0, y=0)
    w.native("create loft section plane", lambda: make_plane(w, "SectionPlane", origin_plane(w.body, "XY"), 12))
    w.call("sketch_circle", id="Section", diameter=4, x=0, y=0, support={"feature": "SectionPlane"})

    def create():
        feature = w.body.newObject("PartDesign::AdditiveLoft", "Loft")
        feature.Profile = w.doc.Profile
        feature.Sections = [w.doc.Section]
        w.body.Tip = feature
    volume = lambda height, top_radius: math.pi * height * (4**2 + 4 * top_radius + top_radius**2) / 3
    w.native("create additive loft", create)
    w.accepted("circular frustum loft", volume(12, 2))
    w.creation_history("Loft", None, volume(12, 2))
    w.edit_history("upstream loft plane separation 12 to 18 mm", lambda: setattr(w.doc.SectionPlane, "AttachmentOffset", App.Placement(App.Vector(0, 0, 18), App.Rotation())), volume(12, 2), volume(18, 2))
    w.call("set_parameter", feature="Section", parameter="Diameter", value=6)
    final = volume(18, 3)
    w.accepted("upstream loft section diameter", final)
    w.call("undo")
    w.accepted("upstream loft section undo", volume(18, 2))
    w.call("redo")

    def verify():
        w.dependencies("Loft", ["Profile", "Section"])
        w.dependencies("Section", ["SectionPlane"])
        w.near("loft separation persists", w.doc.Section.Placement.Base.z, 18)
        w.near("loft section radius persists", w.doc.Section.Geometry[0].Radius, 3)
    verify()
    return w.reopen(final, verify)


def main():
    started = time.perf_counter()
    for name, function in (("linear-feature-pattern", linears), ("circular-feature-pattern", circulars),
                           ("offset-plane", offset_plane), ("angled-plane", angled_plane),
                           ("additive-sweep", sweep), ("additive-loft", loft)):
        case = {"name": name, "passed": False}
        REPORT["cases"].append(case)
        workflow = None
        try:
            workflow = Workflow(name)
            case["editable_fixture"] = function(workflow)
            case["measurements"] = workflow.state["measurements"]
            case["passed"] = True
        except Exception:
            case["failure"] = traceback.format_exc()
        finally:
            if workflow:
                case["checks"] = workflow.checks
                workflow.close()
        print(name + ": " + ("PASS" if case["passed"] else "FAIL"), flush=True)
    REPORT["passed"] = all(case["passed"] for case in REPORT["cases"])
    REPORT["seconds"] = time.perf_counter() - started
    REPORT["checks"] = sum(len(case.get("checks", [])) for case in REPORT["cases"])
    output = ROOT / "validation" / "ui-refinement" / "modeling-workflows.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
    print(json.dumps({"passed": REPORT["passed"], "cases": len(REPORT["cases"]), "checks": REPORT["checks"], "report": str(output)}, indent=2))
    if not REPORT["passed"]:
        for case in REPORT["cases"]:
            if not case["passed"]:
                print(case["failure"])
    return 0 if REPORT["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
