"""Managed projects saved the way an assistant builds them: the headless
Controller with no GUI, so the FCStd archive has no GuiDocument.xml.

python.exe -B tools/headless_part_fixture.py <existing-output-folder>

Writes studio.FCStd (one named, colored part rebuilt through three result
generations) and single-body.FCStd (one native Body, no studio operations),
then prints a JSON summary. Run it inside an isolated validation session.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PART_NAME = "Bone Mallet"
PART_COLOR = [0.62, 0.38, 0.17]


def build(folder):
    sys.path.insert(0, str(ROOT / "src"))
    import FreeCAD as App
    from kurtshape.core import Controller
    from kurtshape import studio
    if getattr(App, "GuiUp", False):
        raise RuntimeError("The headless fixture must be built without the FreeCAD GUI")
    folder = Path(folder).resolve()
    if not os.environ.get("KURTSHAPE_SESSION_DIR"):
        # The grant below persists in the session's settings.json; never widen the live runtime profile.
        raise RuntimeError("The headless fixture needs a private session (set KURTSHAPE_SESSION_DIR)")
    core = Controller()
    # The fixture folder is granted the way a user's Save dialog grants it; a fresh private profile grants
    # only <root>/projects (slice A/B U8, as the interface recipe's save).
    core.settings.grant_destination(str(folder / "studio.FCStd"))
    summary = {}
    try:
        state = core.dispatch({"op": "new", "name": "Headless studio"})["result"]

        def call(op, **kwargs):
            nonlocal state
            response = core.dispatch({"op": op, "document_id": state["document_id"],
                                      "expected_revision": state["revision"], **kwargs})
            if not response["ok"]:
                raise RuntimeError(f"{op} failed: {response['error']}")
            state = response["result"]

        call("sketch_rectangle", id="HeadProfile", body="Body", x=0, y=0, width=40, height=20)
        call("pad", id="Head", profile="HeadProfile", body="Body", length=20, operation="new")
        call("set_part_appearance", part="Body", name=PART_NAME, color=PART_COLOR)
        call("sketch_rectangle", id="HandleProfile", body="Body", x=15, y=20, width=10, height=60)
        call("pad", id="Handle", profile="HandleProfile", length=12, operation="add", merge_scope=["Body"])
        call("sketch_rectangle", id="GripProfile", body="Body", x=17, y=60, width=6, height=10)
        call("pad", id="Grip", profile="GripProfile", length=4, operation="remove", merge_scope=["Body"])
        doc = core.documents[state["document_id"]]
        part = state["studio"]["parts"][0]
        current = doc.getObject(part["body"])
        box = current.Shape.BoundBox
        studio_path = folder / "studio.FCStd"
        call("save", path=str(studio_path))
        summary["studio"] = {
            "path": str(studio_path), "part": part["id"], "name": part["name"], "body": current.Name,
            "tip": current.Tip.Name, "label": current.Label, "color": part["color"],
            "bbox": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax],
            "part_bodies": {obj.Name: obj.Label for obj in doc.Objects
                            if obj.TypeId == "PartDesign::Body" and studio.part_id(obj) == part["id"]}}
        App.closeDocument(doc.Name)

        state = core.dispatch({"op": "new", "name": "Headless single body"})["result"]
        call("sketch_rectangle", id="BlockProfile", body="Body", x=0, y=0, width=30, height=10)
        call("pad", id="Block", profile="BlockProfile", body="Body", length=5)
        doc = core.documents[state["document_id"]]
        box = doc.Body.Shape.BoundBox
        single_path = folder / "single-body.FCStd"
        call("save", path=str(single_path))
        summary["single_body"] = {"path": str(single_path), "body": "Body", "tip": doc.Body.Tip.Name,
                                  "bbox": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]}
        App.closeDocument(doc.Name)
    finally:
        core.close()
    return summary


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1])))
