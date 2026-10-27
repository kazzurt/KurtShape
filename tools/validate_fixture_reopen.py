"""Shared headless/offscreen GUI regression; configured by the PS1 runner."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def run():
    import FreeCAD as App
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from kurtshape.core import Controller
    from kurtshape import assembly
    from kurtshape.assembly_persistence import save_copy
    config = json.loads(Path(os.environ["KURTSHAPE_REOPEN_CONFIG"]).read_text(encoding="utf-8"))
    mode = "gui" if App.GuiUp else "headless"
    out = Path(config["output"])
    source = Path(config["input"])
    report = {"mode": mode, "passed": False, "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "cycles": [], "engine": App.Version()}
    started = time.perf_counter()
    core, state = Controller(), {}

    def call(op, **args):
        if state and op not in core.CREATE_OPS | {"capabilities", "list_documents"}:
            args.update(document_id=state["document_id"], expected_revision=state["revision"])
        response = core.dispatch({"op": op, "measure": False, **args})
        if not response["ok"]:
            raise RuntimeError(json.dumps(response))
        result = response["result"]
        if "features" in result:
            state.clear()
            state.update(result)
        return result

    try:
        report["build"] = call("capabilities")["build"]
        call("list_documents")
        call("open", path=str(source))
        report["initial_status"] = state["build_status"]
        if mode == "headless" and config.get("refresh_instance"):
            call("refresh_assembly_part", instance=config["refresh_instance"], shared="instance")
        for cycle in range(3):
            if state["build_status"] != "valid":
                raise RuntimeError(json.dumps(state.get("build_errors")))
            checked = call("check_geometry")["geometry_check_report"]
            if checked["status"] != "valid":
                raise RuntimeError("Native geometry check failed")
            destination = out / (mode + "-cycle-" + str(cycle) + ".FCStd")
            call("save", path=str(destination))
            call("close_document")
            call("open", path=str(destination))
            errors = assembly.validation_errors(core.documents[state["document_id"]])
            report["cycles"].append({"build_status": state["build_status"], "embedded_errors": errors,
                                     "occurrences": len(state["assembly"]["instances"]), "path": str(destination)})
            if state["build_status"] != "valid" or errors:
                raise RuntimeError("Serialized assembly did not reopen valid")
        report["output"] = str(destination)
        # An actual edit to an embedded shape stays a failure, including after
        # native recovery serialization. Only this disposable document changes.
        doc = core.documents[state["document_id"]]
        embedded = next(obj for obj in doc.Objects if getattr(obj, "KurtShapeEmbeddedSource", False))
        changed = embedded.Shape.copy()
        changed.translate(App.Vector(.01, 0, 0))
        embedded.Shape = changed
        report["changed_source_detected"] = any(error["feature"] == embedded.Name for error in assembly.validation_errors(doc))
        damaged = out / (mode + "-intentional-negative-case.FCStd")
        save_copy(doc, damaged)
        App.closeDocument(doc.Name)
        call("open", path=str(damaged))
        report["changed_source_reopen_detected"] = state["build_status"] == "failed"
        report["input_unchanged"] = report["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        report["passed"] = all(report[key] for key in ("changed_source_detected", "changed_source_reopen_detected", "input_unchanged"))
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        report["seconds"] = time.perf_counter() - started
        core.close()
        for name in list(App.listDocuments()):
            App.closeDocument(name)
        (out / (mode + "-report.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report["passed"]


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
