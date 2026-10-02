"""Verified native checkpoints, including an unfinished managed sketch lease."""
import base64
import hashlib
import json
import os
from pathlib import Path
import time
import zipfile


class RecoveryStore:
    interval_seconds = 30

    def __init__(self, session_directory):
        self.directory = Path(session_directory) / "project-recovery"
        self.last = {}

    def capture(self, doc, meta, editing=None, force=False, draft=None):
        previous = self.last.get(meta.DocumentId, (0, None))
        if not force and (previous[1] == meta.Revision or time.monotonic() - previous[0] < self.interval_seconds):
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (meta.DocumentId + ".FCStd")
        stage = path.with_suffix(".saving.FCStd")
        doc.saveCopy(str(stage))
        with zipfile.ZipFile(stage) as archive:
            if "Document.xml" not in archive.namelist() or archive.testzip():
                raise RuntimeError("Recovery archive failed ZIP verification")
        record = {"schema": 1, "document_id": meta.DocumentId, "revision": meta.Revision,
                  "name": doc.Label, "source_file": doc.FileName or None, "saved_at": time.time(),
                  "sha256": hashlib.sha256(stage.read_bytes()).hexdigest(), "snapshot": path.name,
                  "sketch": editing["feature"] if editing else None,
                  "accepted_sketch": base64.b64encode(editing["initial"]).decode() if editing else None,
                  "draft_sketch": base64.b64encode(draft).decode() if draft is not None else None}
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
        self.last[meta.DocumentId] = (time.monotonic(), meta.Revision)
        return manifest

    def read(self, raw):
        manifest = Path(raw).resolve()
        if manifest.parent != self.directory.resolve() or manifest.suffix != ".json":
            raise ValueError("Choose a manifest from the project's recovery directory")
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
