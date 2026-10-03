"""Independent proof after the owned recovery GUI recipe exits.

Run only through the isolated validation launcher. This script reads the
producer's evidence without changing its report, profile or checkpoint pair.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import traceback
import uuid
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CHECKS = 10


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def utc_seconds(raw):
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    require(value.tzinfo is not None and value.utcoffset().total_seconds() == 0,
            "Producer timestamps must be explicit UTC")
    return value.timestamp()


def within(path, parent):
    return path != parent and path.is_relative_to(parent)


def private_session(path):
    runtime = ROOT / "runtime"
    require(within(path, runtime), "Expected a private repository runtime session")
    for protected in (runtime / name for name in (
            "freecad-1.1.4", "downloads", "user-data", "temporary", "appdata",
            "localappdata", "project-recovery")):
        require(path != protected and not path.is_relative_to(protected),
                "Engine, download and live profile directories cannot be validation profiles")


def environment(args):
    require(Path(os.environ["KURTSHAPE_ROOT"]).resolve() == ROOT,
            "KURTSHAPE_ROOT does not identify this checkout")
    session = Path(os.environ["KURTSHAPE_SESSION_DIR"]).resolve()
    producer = Path(args.producer_session).resolve()
    private_session(session)
    private_session(producer)
    require(session.is_dir() and producer.is_dir(), "Both private profiles must exist")
    require(session != producer and not session.is_relative_to(producer)
            and not producer.is_relative_to(session), "Verifier must use an independent profile")
    roots = {"KURTSHAPE_SESSION_DIR": str(session)}
    for name in ("FREECAD_USER_HOME", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA"):
        child = Path(os.environ[name]).resolve()
        require(within(child, session) and child.is_dir(), name + " must be inside verifier profile")
        roots[name] = str(child)
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "Bytecode must be disabled before imports")
    require(os.environ.get("KURTSHAPE_WRITE_EVIDENCE") != "1", "Private proof cannot publish tracked evidence")
    evidence = Path(os.environ["KURTSHAPE_EVIDENCE_DIR"]).resolve()
    require(evidence == session / "evidence", "Verifier evidence must stay inside its own profile")
    output = Path(args.out).resolve()
    require(within(output, evidence) and output.suffix == ".json", "Proof output must be private JSON evidence")
    require(not output.exists(), "Proof output must be absent before this fresh process")
    require(args.producer_pid > 0 and args.producer_pid != os.getpid(), "Expected a separate owned producer PID")
    require(args.producer_exit_code in (23, -1073740791), "Unexpected recovery producer exit code")
    began = utc_seconds(args.producer_start_utc)
    ended = utc_seconds(args.producer_exit_utc)
    require(began < ended <= datetime.now(timezone.utc).timestamp(), "Invalid producer lifetime")
    return session, producer, output, roots, began, ended


def fresh_file(path, began, ended):
    require(path.is_file(), "Missing producer evidence: " + str(path))
    # Filesystem mtimes and launcher UTC timestamps are checked together;
    # no previous-session artifact can satisfy the new-session path binding.
    require(began <= path.stat().st_mtime <= ended, "Evidence falls outside owned producer lifetime: " + str(path))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_zip(path):
    with zipfile.ZipFile(path) as archive:
        require("Document.xml" in archive.namelist() and archive.testzip() is None,
                "Invalid native FCStd ZIP: " + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer-session", required=True)
    parser.add_argument("--producer-pid", required=True, type=int)
    parser.add_argument("--producer-start-utc", required=True)
    parser.add_argument("--producer-exit-utc", required=True)
    parser.add_argument("--producer-exit-code", required=True, type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        session, producer, output, roots, began, ended = environment(args)
    except Exception as error:
        parser.error(str(error))
    report = {"passed": False, "pid": os.getpid(), "producer_pid": args.producer_pid,
              "started_utc": utc_now(), "method": "Independent isolated native process after the owned blocking recovery GUI recipe exits",
              "session": str(session), "producer_session": str(producer), "environment": roots,
              "producer_started_utc": args.producer_start_utc, "producer_exited_utc": args.producer_exit_utc,
              "producer_exit_code": args.producer_exit_code, "checks": [],
              "native_autosave_reopened": False,
              "native_autosave": {"available": False, "verified": False, "status": "NotVerified",
                                  "reason": "No native autosave archive was produced; enabled preferences alone do not prove recovery"}}
    core = None
    App = None
    owned_documents = set()
    protected_hashes = {}

    def check(label, condition):
        require(condition, label)
        report["checks"].append(label)

    def close_owned(doc):
        name = doc.Name
        App.closeDocument(name)
        owned_documents.discard(name)

    try:
        check("Verifier imports use six independent private environment roots", len(roots) == 6)
        gui_path = producer / "evidence" / "review-followup" / "recovery-crash.json"
        fresh_file(gui_path, began, ended)
        gui = json.loads(gui_path.read_text(encoding="utf-8-sig"))
        require(isinstance(gui, dict) and gui.get("passed") is True and "error" not in gui, "GUI crash report must strictly pass")
        require(type(gui.get("pid")) is int and gui["pid"] == args.producer_pid, "GUI report PID does not match owned producer")
        require(type(gui.get("expected_draft_geometry")) is int and gui["expected_draft_geometry"] == 1,
                "Unexpected current-main draft fixture")
        require(type(gui.get("expected_volume_mm3")) is int and gui["expected_volume_mm3"] == 1800,
                "Unexpected current-main volume fixture")
        identifier = gui["document_id"]
        require(isinstance(identifier, str) and str(uuid.UUID(identifier)) == identifier, "Document ID is not a canonical UUID")
        check("Fresh GUI report is bound to the owned crash PID and lifetime", True)
        report["producer_report_verified"] = True
        report["producer_report"] = str(gui_path)
        manifest = Path(gui["checkpoint_manifest"]).resolve()
        require(manifest.parent == producer / "project-recovery" and manifest.name == identifier + ".json",
                "Checkpoint manifest must belong to this producer and document")
        fresh_file(manifest, began, ended)
        record = json.loads(manifest.read_text(encoding="utf-8"))
        require(isinstance(record, dict) and type(record.get("schema")) is int and record["schema"] == 1,
                "Unexpected checkpoint schema")
        require(record.get("document_id") == identifier and record.get("sketch") == "Unfinished", "Checkpoint document/sketch mismatch")
        revision = record.get("revision")
        require(isinstance(revision, str) and str(uuid.UUID(revision)) == revision, "Checkpoint revision is not a canonical UUID")
        require(record.get("snapshot") == identifier + ".FCStd", "Expected the current complete snapshot")
        require(isinstance(record.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", record["sha256"]), "Invalid snapshot hash")
        saved_at = record.get("saved_at")
        require(type(saved_at) in (int, float) and math.isfinite(saved_at) and began <= saved_at <= ended,
                "Checkpoint timestamp falls outside owned producer lifetime")
        require(isinstance(record.get("accepted_sketch"), str) and bool(base64.b64decode(record["accepted_sketch"], validate=True)),
                "Checkpoint lacks accepted sketch serialization")
        if record.get("draft_sketch") is not None:
            require(isinstance(record["draft_sketch"], str) and bool(base64.b64decode(record["draft_sketch"], validate=True)),
                    "Invalid draft sketch serialization")
        snapshot = (manifest.parent / record["snapshot"]).resolve()
        fresh_file(snapshot, began, ended)
        require(snapshot.parent == manifest.parent and sha256(snapshot) == record["sha256"], "Checkpoint snapshot hash mismatch")
        native_zip(snapshot)
        check("Producer checkpoint UUID, private path, SHA-256 and native ZIP are verified", True)
        report["checkpoint_pair_verified"] = True
        source = Path(gui["original_file"]).resolve()
        require(source == producer / "saved-before-crash.FCStd" and Path(record["source_file"]).resolve() == source,
                "Original project must be the producer's saved fixture")
        fresh_file(source, began, ended)
        native_zip(source)
        protected_hashes = {path: sha256(path) for path in (gui_path, manifest, snapshot, source)}
        check("Original saved fixture is a fresh private native ZIP", True)
        report["inputs"] = {"manifest": str(manifest), "snapshot": str(snapshot), "original_file": str(source),
                            "snapshot_sha256": record["sha256"], "original_file_sha256": protected_hashes[source]}
        sys.path.insert(0, str(ROOT / "src"))
        import FreeCAD as App
        import Part
        from kurtshape.core import Controller
        from kurtshape.recovery import RecoveryStore
        require(not App.listDocuments(), "Verifier must start without native documents")
        expected_home = ROOT / "runtime" / "freecad-1.1.4" / "FreeCAD_1.1.4-Windows-x86_64-py311"
        require(Path(App.getHomePath()).resolve() == expected_home, "Verifier is not using the pinned native engine")
        report["engine"] = {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION, "home": App.getHomePath()}
        core = Controller()
        # Read the producer store through its real API without swapping any
        # verifier environment variable or writing to that recovery directory.
        core.recovery = RecoveryStore(producer)
        verified_snapshot, verified_record = core.recovery.read(manifest)
        require(verified_snapshot == snapshot and verified_record == record, "RecoveryStore disagrees with verified pair")
        response = core.dispatch({"op": "recover", "path": str(manifest)})
        require(response.get("ok") is True, "Checkpoint recovery rejected: " + str(response))
        state = response["result"]
        doc = core.documents[state["document_id"]]
        owned_documents.add(doc.Name)
        check("Checkpoint reopens the same document with valid unsaved 1800 mm3 geometry",
              state["document_id"] == identifier and state["build_status"] == "valid"
              and doc.Pad.Shape.isValid() and len(doc.Pad.Shape.Solids) == 1
              and abs(doc.Pad.Shape.Volume - 1800) < 1e-6 and abs(doc.Pad.Length.Value - 9) < 1e-9)
        report.update(reopened_checkpoint=True, recovered_unsaved_volume_mm3=doc.Pad.Shape.Volume)
        check("Recovered unfinished sketch contains the real one-circle draft",
              state["active_sketch_edit"] == "Unfinished" and doc.Unfinished.GeometryCount == 1
              and abs(doc.Unfinished.Geometry[0].Radius - 2) < 1e-9
              and abs(doc.Unfinished.Geometry[0].Center.x) < 1e-9
              and abs(doc.Unfinished.Geometry[0].Center.y) < 1e-9)
        report.update(recovered_draft=True, recovered_draft_geometry=doc.Unfinished.GeometryCount)
        check("Recovered checkpoint has no saved native filename",
              state["native_file"] is None and doc.FileName == "")
        report["recovered_unsaved_native_semantics"] = True
        response = core.dispatch({"op": "finish_sketch_edit", "document_id": state["document_id"],
                                  "expected_revision": state["revision"], "cancel": True})
        require(response.get("ok") is True, "Explicit Cancel rejected: " + str(response))
        state = response["result"]
        check("Explicit Cancel restores the accepted empty sketch and preserves unsaved geometry",
              doc.Unfinished.GeometryCount == 0 and state["active_sketch_edit"] is None
              and state["native_file"] is None and doc.FileName == ""
              and doc.Pad.Shape.isValid() and len(doc.Pad.Shape.Solids) == 1
              and abs(doc.Pad.Shape.Volume - 1800) < 1e-6)
        report.update(explicit_cancel_restored_accepted_sketch=True, accepted_sketch_geometry=doc.Unfinished.GeometryCount,
                      cancel_preserved_unsaved_geometry=True, cancel_kept_unsaved_native_semantics=True)
        close_owned(doc)
        saved = App.openDocument(str(source))
        owned_documents.add(saved.Name)
        check("Original saved project independently reopens at 1200 mm3",
              saved.Pad.Shape.isValid() and len(saved.Pad.Shape.Solids) == 1
              and abs(saved.Pad.Shape.Volume - 1200) < 1e-6 and abs(saved.Pad.Length.Value - 6) < 1e-9)
        report.update(saved_project_reopened=True, saved_volume_mm3=saved.Pad.Shape.Volume)
        close_owned(saved)
        native_files = gui.get("native_stable_recovery_files", [])
        require(isinstance(native_files, list), "Native autosave inventory must be a list")
        transient = Path(gui["stable_transient_directory"]).resolve()
        require(within(transient, producer), "Native autosave transient directory must remain private")
        candidates = []
        for item in native_files:
            require(isinstance(item, dict) and isinstance(item.get("path"), str), "Invalid native autosave inventory entry")
            path = Path(item["path"]).resolve()
            require(within(path, transient), "Native autosave inventory escaped its transient directory")
            fresh_file(path, began, ended)
            require(type(item.get("bytes")) is int and item["bytes"] == path.stat().st_size, "Native autosave size mismatch")
            if path.suffix.lower() == ".fcstd":
                candidates.append(path)
        if candidates:
            native = candidates[0]
            native_zip(native)
            native_hash = sha256(native)
            recovered_native = App.openDocument(str(native))
            owned_documents.add(recovered_native.Name)
            require(recovered_native.Solid.Shape.isValid() and abs(recovered_native.Solid.Shape.Volume - 27) < 1e-6,
                    "Native autosave archive does not contain the unsaved stable fixture")
            report["native_autosave"] = {"available": True, "verified": True, "status": "Verified", "path": str(native),
                                         "sha256": native_hash, "volume_mm3": recovered_native.Solid.Shape.Volume}
            report["native_autosave_reopened"] = True
            close_owned(recovered_native)
            require(sha256(native) == native_hash, "Native autosave bytes changed during verification")
        check("Producer report, checkpoint pair and saved original bytes remain unchanged",
              all(sha256(path) == digest for path, digest in protected_hashes.items()))
        report.update(original_file_unchanged=True, producer_files_unchanged=True,
                      original_file_sha256=protected_hashes[source], timings=core.timings.report())
        require(len(report["checks"]) == EXPECTED_CHECKS, "Incomplete private recovery proof")
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        cleanup_errors = []
        if core is not None:
            try:
                core.close()
            except Exception:
                cleanup_errors.append(traceback.format_exc())
        if App is not None:
            # This fresh process owns every document it opened, including a
            # partially attached document if a recovery operation failed.
            try:
                remaining = list(App.listDocuments())
            except Exception:
                remaining = []
                cleanup_errors.append(traceback.format_exc())
            for name in remaining:
                try:
                    App.closeDocument(name)
                except Exception:
                    cleanup_errors.append(traceback.format_exc())
        if protected_hashes:
            try:
                require(all(sha256(path) == digest for path, digest in protected_hashes.items()),
                        "Producer files changed during cleanup")
            except Exception:
                cleanup_errors.append(traceback.format_exc())
        if cleanup_errors:
            report["passed"] = False
            report["cleanup_errors"] = cleanup_errors
        report["completed_utc"] = utc_now()
        output.parent.mkdir(parents=True, exist_ok=True)
        staged = output.with_suffix(".json.saving")
        try:
            staged.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
            os.replace(staged, output)
        finally:
            staged.unlink(missing_ok=True)
    print(json.dumps({"passed": report["passed"], "pid": report["pid"], "producer_pid": report["producer_pid"],
                      "checks": len(report["checks"]), "report": str(output)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
