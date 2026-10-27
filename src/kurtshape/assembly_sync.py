"""Are an assembly's occurrences current with their saved sources? (assembly UX item 7)

Each embedded snapshot records ``SourcePath`` and ``SourceSHA256``. A source
is *changed* when the file's SHA-256 differs from the recorded one. Hashing is
the expensive step, so a per-process cache keeps ``(mtime_ns, size) → sha256``
for every path: a file is hashed again only when its modification time or size
moved. ``source_state(..., hash=False)`` never hashes; it answers from the cache
and reports ``"unchecked"`` when the file moved since it was last hashed (the
GUI's idle/activation pre-check). The bridge's ``inspect`` hashes lazily.

No Qt here; the GUI wiring is ``assembly_refresh_button``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import threading

_cache = {}
_lock = threading.Lock()
# The GUI turns lazy hashing off for its frequent inspections; the Refresh button hashes explicitly.
INSPECT_HASHES = True


def _stat(path):
    try:
        value = Path(path).stat()
    except (OSError, ValueError):
        return None
    return value.st_mtime_ns, value.st_size


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def current_sha(path, hash=True):
    """The file's SHA-256 from the cache, hashing only when allowed and the stat moved.

    Returns (sha or None, stat or None); None stat = missing file.
    """
    stat = _stat(path)
    if stat is None:
        return None, None
    with _lock:
        cached = _cache.get(str(path))
    if cached is not None and cached[0] == stat:
        return cached[1], stat
    if not hash:
        return None, stat
    value = sha256(path)
    after = _stat(path)
    if after == stat:
        with _lock:
            _cache[str(path)] = (stat, value)
    return value, stat


def source_state(path, recorded, hash=None):
    """``{"status": current|changed|missing|unchecked|unrecorded, "current_sha256"}``."""
    if not path:
        return {"status": "unrecorded", "current_sha256": None}
    value, stat = current_sha(path, INSPECT_HASHES if hash is None else hash)
    if stat is None:
        return {"status": "missing", "current_sha256": None}
    if value is None:
        return {"status": "unchecked", "current_sha256": None}
    return {"status": "current" if value == recorded else "changed", "current_sha256": value}


def remember(path, value):
    """Seed the cache after a file was hashed elsewhere (insert/refresh read the same bytes)."""
    stat = _stat(path)
    if stat is not None and value:
        with _lock:
            _cache[str(path)] = (stat, value)


def moved_since_check(path):
    """Pre-check: True when the file's mtime/size differ from the last hash (or it was never hashed)."""
    stat = _stat(path)
    with _lock:
        cached = _cache.get(str(path))
    return stat is None or cached is None or cached[0] != stat


def clear():
    with _lock:
        _cache.clear()
