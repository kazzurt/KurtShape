"""Verified native checkpoints, including an unfinished managed sketch lease."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

from .settings import load_preference

DOCUMENT_PREFERENCES = "User parameter:BaseApp/Preferences/Document"
# ZIP level of a checkpoint archive when recovery_fast_snapshots is on (slice A/B U8). Level 1 restores
# every BRep byte-identically and writes up to 1.75x faster (Dodec Hub; small parts unchanged); SaveBinaryBrep was
# measured and not adopted: its restore differs (TShape Checked bits, and location digits on a real project).
FAST_SNAPSHOT_COMPRESSION = 1


@contextmanager
def snapshot_compression(level):
    """FreeCAD's ``CompressionLevel`` at ``level`` for one saveCopy on this thread, restored afterwards."""
    if level is None:
        yield
        return
    import FreeCAD as App
    group = App.ParamGet(DOCUMENT_PREFERENCES)
    previous = group.GetInt("CompressionLevel") if "CompressionLevel" in group.GetInts() else None
    group.SetInt("CompressionLevel", level)
    try:
        yield
    finally:
        if previous is None:
            group.RemInt("CompressionLevel")
        else:
            group.SetInt("CompressionLevel", previous)


class RecoveryStore:
    interval_seconds = 30
    # Discard checkpoints kept per recovery directory (contract 3.2 close_document discard:true).
    discard_keep = 20

    def __init__(self, session_directory):
        self.directory = Path(session_directory) / "project-recovery"
        self.last = {}
        self.pending = {}
        self._executor = None
        self.notifications = []
        # Count native snapshot attempts separately from asynchronous publication.
        self.snapshot_count = 0
        self.snapshot_cache_failures = 0
        self.compression = FAST_SNAPSHOT_COMPRESSION if load_preference(session_directory, "recovery_fast_snapshots") else None
        # A4 (slice A/B U8): called with "Saving…" / "Checkpoint…" right before a synchronous native save
        # on this thread and with None when it is done; the GUI binds a status painter, headless leaves None.
        self.stall_status = None

    def stall(self, text):
        if self.stall_status is not None:
            self.stall_status(text)

    def _snapshot(self, doc, stage):
        """The native checkpoint write, announced before it starts and cleared when it ends."""
        self.stall("Checkpoint…")
        try:
            with snapshot_compression(self.compression):
                doc.saveCopy(str(stage))
        finally:
            self.stall(None)

    def capture(self, doc, meta, editing=None, force=False, draft=None, background=False, snapshot_cache=None):
        if not force:
            self.poll()
        if meta.DocumentId in self.pending:
            if not force:
                return None
            # A forced checkpoint keeps its synchronous durability contract;
            # serialize it after the older publication for this same document.
            try:
                self._finish(meta.DocumentId, wait=True)
            except Exception as exc:
                # A failed older publication must not prevent an emergency
                # fresh snapshot. Surface its error on the next GUI poll.
                self.notifications.append(str(exc))
        previous = self.last.get(meta.DocumentId, (0, None))
        if not force and (previous[1] == meta.Revision or time.monotonic() - previous[0] < self.interval_seconds):
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (meta.DocumentId + ".FCStd")
        stage = path.with_suffix(".saving.FCStd")
        self.snapshot_count += 1
        self._snapshot(doc, stage)
        # Check on the native thread after capture. A harmless notification may
        # conservatively reject sharing; recovery still publishes its archive.
        shared = None
        if snapshot_cache is not None and not (force or editing or draft is not None):
            store, key, current_key = snapshot_cache
            if key is not None and current_key() == key:
                shared = store, key
        record = {"schema": 1, "document_id": meta.DocumentId, "revision": meta.Revision,
                  "name": doc.Label, "source_file": doc.FileName or None, "saved_at": time.time(),
                  "snapshot": path.name,
                  "sketch": editing["feature"] if editing else None,
                  "accepted_sketch": base64.b64encode(editing["initial"]).decode() if editing else None,
                  "draft_sketch": base64.b64encode(draft).decode() if draft is not None else None}
        if background and not force:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="KurtShape-recovery-files")
            # Only ordinary paths and immutable serialized metadata cross the
            # thread boundary. No FreeCAD/Gui/native objects are retained.
            self.pending[meta.DocumentId] = (self._executor.submit(self._publish_cached, stage, path, record, shared), meta.Revision)
            return None
        manifest = self._publish_cached(stage, path, record, shared)
        self.last[meta.DocumentId] = (time.monotonic(), meta.Revision)
        return manifest

    def capture_discarded(self, doc, meta):
        """Checkpoint a document whose unsaved changes are being discarded; returns the manifest path.

        Writes ``<DocumentId>.discarded-<rev>.FCStd`` and ``.json`` through the same stage,
        verify and publish path as ordinary checkpoints (``record["discarded"]`` is true and
        carries the full revision; ``<rev>`` is its first 12 hex digits, because the bundled
        FreeCAD cannot save to paths beyond about 225 characters and the session folder is
        validated for a 62-character checkpoint name). The name never rotates and ``read``
        accepts it; after each capture only the newest ``discard_keep`` discard pairs are kept.
        """
        if meta.DocumentId in self.pending:
            self._finish(meta.DocumentId, wait=True)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{meta.DocumentId}.discarded-{meta.Revision.replace('-', '')[:12]}.FCStd"
        stage = path.with_suffix(".saving.FCStd")
        self.snapshot_count += 1
        self._snapshot(doc, stage)
        record = {"schema": 1, "document_id": meta.DocumentId, "revision": meta.Revision,
                  "name": doc.Label, "source_file": doc.FileName or None, "saved_at": time.time(),
                  "snapshot": path.name, "sketch": None, "accepted_sketch": None, "draft_sketch": None,
                  "discarded": True}
        manifest = self._publish(stage, path, record)
        self._prune_discarded()
        return manifest

    def _prune_discarded(self):
        manifests = sorted((path for path in self.directory.glob("*.discarded-*.json")
                            if ".previous" not in path.name and ".saving" not in path.name),
                           key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
        for manifest in manifests[self.discard_keep:]:
            for victim in (manifest, manifest.with_suffix(".FCStd"),
                           manifest.with_suffix(".previous.json"), manifest.with_suffix(".previous.FCStd")):
                try:
                    victim.unlink()
                except FileNotFoundError:
                    pass

    def _publish_cached(self, stage, path, record, shared):
        manifest = self._publish(stage, path, record)
        if shared is not None:
            store, key = shared
            try:
                store.publish(key, path)
            except Exception:
                # Optional cache publication cannot turn a durable checkpoint
                # into a failure. The next preview takes its normal snapshot.
                self.snapshot_cache_failures += 1
        return manifest

    @staticmethod
    def _publish(stage, path, record):
        with zipfile.ZipFile(stage) as archive:
            if "Document.xml" not in archive.namelist() or archive.testzip():
                raise RuntimeError("Recovery archive failed ZIP verification")
        digest = hashlib.sha256()
        with stage.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        record = dict(record, sha256=digest.hexdigest())
        manifest = path.with_suffix(".json")
        staged_manifest = manifest.with_suffix(".saving.json")
        staged_manifest.write_text(json.dumps(record, indent=2), encoding="utf-8")
        # Preserve the last complete pair if either replacement fails or is interrupted.
        import shutil
        if path.exists() and manifest.exists():
            shutil.copy2(path, path.with_suffix(".previous.FCStd"))
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            previous["snapshot"] = path.with_suffix(".previous.FCStd").name
            manifest.with_suffix(".previous.json").write_text(json.dumps(previous, indent=2), encoding="utf-8")
        os.replace(stage, path)
        os.replace(staged_manifest, manifest)
        return manifest

    def _finish(self, identifier, wait=False):
        future, revision = self.pending[identifier]
        if not wait and not future.done():
            return None
        try:
            manifest = future.result()
            self.last[identifier] = (time.monotonic(), revision)
            return manifest
        finally:
            self.pending.pop(identifier, None)

    def poll(self):
        completed, failures = [], self.notifications
        self.notifications = []
        for identifier in tuple(self.pending):
            try:
                path = self._finish(identifier)
                if path is not None:
                    completed.append(path)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError("Recovery publication failed: " + "; ".join(failures))
        return completed

    def close(self):
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self.poll()

    def read(self, raw):
        manifest = Path(raw).resolve()
        if manifest.parent != self.directory.resolve() or manifest.suffix != ".json":
            raise ValueError("Choose a manifest from the project's recovery directory")
        identifier = manifest.stem.removesuffix(".previous")
        if identifier in self.pending:
            # Recovery opens this verified path immediately on the GUI thread.
            # Finish this document's publisher before reading either member so
            # an async replacement cannot mix native geometry and draft metadata.
            self._finish(identifier, wait=True)
        record = json.loads(manifest.read_text(encoding="utf-8"))
        path = (manifest.parent / record["snapshot"]).resolve()
        if path.parent != manifest.parent or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Recovery pair is incomplete or corrupt; inspect the previous checkpoint")
        return path, record

    def available(self):
        records = []
        if self.directory.exists():
            for path in self.directory.glob("*.json"):
                try:
                    _, record = self.read(path)
                    source = Path(record["source_file"]) if record.get("source_file") else None
                    if source and source.exists() and source.stat().st_mtime >= record["saved_at"] and not record.get("sketch"):
                        continue
                    records.append((path, record))
                except (OSError, ValueError, KeyError):
                    pass
        return sorted(records, key=lambda item: item[1]["saved_at"], reverse=True)
