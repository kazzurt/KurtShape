"""Worked example: a small assembly built headless with folders, a measured clearance and a part refresh.

    runtime\\freecad-1.1.4\\FreeCAD_1.1.4-Windows-x86_64-py311\\bin\\pythonw.exe -B examples\\assembly_folders_refresh.py <scratch> <out> > build.log 2>&1

<scratch> is a private, short folder (TEMP at most 104 characters); <out> is the only folder the script
saves to. It builds a plate and a pin as separate KurtShape projects, assembles one plate and two pins
into folders (Frame, Fasteners/Pins), measures the pin-to-pin clearance, lengthens the pin, sees both pin
occurrences reported as changed, refreshes them together and saves. The result summary is printed as
JSON on the last line (docs/COOKBOOK.md, Assemblies).
"""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main(run, out):
    for name, sub in (("KURTSHAPE_SESSION_DIR", "session"), ("FREECAD_USER_HOME", "user-data"), ("APPDATA", "appdata"),
                      ("LOCALAPPDATA", "localappdata"), ("TEMP", "temporary"), ("TMP", "temporary")):
        (run / sub).mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(run / sub)
    (run / "session" / "settings.json").write_text(json.dumps({"project_roots": [str(out)]}), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "src"))
    from kurtshape.core import Controller  # imports FreeCAD: only after the environment is set

    core, state = Controller(), {}

    def call(op, **args):
        nonlocal state
        if state and op not in {"new", "open", "assembly_candidates"}:
            args.update(document_id=state["document_id"], expected_revision=state["revision"])
        response = core.dispatch({"op": op, **args})
        if not response["ok"]:
            raise RuntimeError(op + ": " + json.dumps(response["error"], default=str)[:2000])
        if "revision" in response["result"]:
            state = response["result"]
        return response["result"]

    summary = {}
    try:
        plate, pin = out / "plate.FCStd", out / "pin.FCStd"
        call("new", name="plate")
        call("sketch_rectangle", id="Profile", width=60, height=30, body="Body")
        call("pad", id="Solid", profile="Profile", length=5, body="Body")
        call("save", path=str(plate))
        call("close_document")
        call("new", name="pin")
        call("sketch_circle", id="Profile", x=0, y=0, diameter=6, body="Body")
        call("pad", id="Solid", profile="Profile", length=20, body="Body")
        call("save", path=str(pin))
        call("close_document")

        call("new", name="Pinned plate")
        assembly_id = state["document_id"]
        call("create_assembly", id="Assembly", name="Pinned plate")
        call("insert_assembly_part", path=str(plate), source_id="Body", id="Plate", folder="Frame")
        for index, x in ((1, 15), (2, 45)):
            call("insert_assembly_part", path=str(pin), source_id="Body", id=f"Pin{index}", folder="Fasteners/Pins")
            call("move_assembly_instance", instance=f"Pin{index}", position_mm=[x, 15, 5], rotation_xyzw=[0, 0, 0, 1])
        folders = {row["id"]: row["folder"] for row in call("inspect")["assembly"]["instances"]}
        clearance = call("measure", references=[{"object": "Pin1"}, {"object": "Pin2"}])
        summary.update(folders=folders, clearance=clearance)

        # Change the pin in its own project and save it.
        call("open", path=str(pin))
        call("edit_extrusion", feature="Solid", length=30)
        call("save", path=str(pin))
        call("close_document")
        state = core.dispatch({"op": "inspect", "document_id": assembly_id})["result"]  # back to the assembly
        assembly_state = state["assembly"]
        summary["status_after_edit"] = {row["id"]: row["source"]["status"] for row in assembly_state["instances"]}
        call("refresh_assembly_part", instance="Pin1", shared="all")
        assembly_state = call("inspect")["assembly"]
        summary["status_after_refresh"] = {row["id"]: row["source"]["status"] for row in assembly_state["instances"]}
        summary["folders_after_refresh"] = {row["id"]: row["folder"] for row in assembly_state["instances"]}
        call("save", path=str(out / "pinned-plate.FCStd"))
        summary["saved"] = str(out / "pinned-plate.FCStd")
    finally:
        core.close()
    return summary


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()), default=str))
