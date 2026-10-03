"""Content fingerprints for native feature archives, independent of ZIP times."""
from __future__ import annotations

import hashlib
import io
import struct
import zipfile
import zlib


_DOMAIN = b"KurtShape:native-feature-content:v1\0"


def native_content_fingerprints(raw: bytes) -> tuple[str, str]:
    """Return canonical content and current raw SHA256 from one native dump.

    Every exact member name and complete payload contributes, including empty
    members. Framing prevents name/payload boundary ambiguity; sorting makes
    member order irrelevant. ZIP headers, timestamps and compression are wrapper
    details. Invalid archives and duplicate names cannot produce a fingerprint.
    """
    members = []
    names = set()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for entry in archive.infolist():
                name = entry.orig_filename
                if name != entry.filename or "\0" in name:
                    raise ValueError("Malformed native feature archive member name")
                if name in names:
                    raise ValueError("Duplicate native feature archive member name")
                names.add(name)
                # Reading by ZipInfo checks this member's local header and CRC.
                members.append((name.encode("utf-8"), archive.read(entry)))
    except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError, OSError, zlib.error) as exc:
        raise ValueError("Malformed native feature archive") from exc

    digest = hashlib.sha256(_DOMAIN)
    digest.update(struct.pack(">Q", len(members)))
    for name, payload in sorted(members):
        digest.update(struct.pack(">Q", len(name)))
        digest.update(name)
        digest.update(struct.pack(">Q", len(payload)))
        digest.update(payload)
    return digest.hexdigest(), hashlib.sha256(raw).hexdigest()
