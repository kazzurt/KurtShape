"""Identity of the KurtShape sources this process loaded (stdlib only, no FreeCAD).

``core`` imports this module first, so the snapshot taken here describes the
package files as they were when the process started. Every ``*.py`` directly in
the package directory is hashed with line endings normalised to LF, so a CRLF
checkout and an LF checkout of the same sources give the same digest.

- ``identity()`` is what ``capabilities.build`` reports. It never waits for git:
  the comparison with the commit checked out at load runs once, in a daemon
  thread started by ``start_git_probe()`` (from ``Bridge.__init__``, or lazily
  from the first ``identity()`` call). ``on_disk`` restats the package and
  re-hashes only files whose size or mtime changed.
- The ``git`` block always carries ``head``, ``ref``, ``head_now`` and
  ``head_moved`` (null and false outside a checkout). A git that has not
  answered after ``GIT_TIMEOUT_S`` is killed with its child processes, so the
  state leaves ``pending`` within about ``GIT_TIMEOUT_S + GIT_KILL_TIMEOUT_S +
  GIT_REAP_TIMEOUT_S``. Only SHA-1 repositories are compared; a SHA-256
  repository reports ``unavailable`` rather than a false ``dirty``.
- ``summary()`` (session file) and ``provenance()`` (export and STEP provenance)
  are smaller views. ``provenance()`` is constant for the life of the process.
- Worker processes (``KURTSHAPE_WORKER=1``) capture nothing and start no thread.
- ``build_verdict()`` classifies a running build against a checkout:
  ``current``, ``stale``, ``different_tree`` or ``unknown``.

Command line: ``python -B -m kurtshape.build_identity [package_dir]`` prints
``{source_dir, source_sha256, id, source_files}`` for a package directory
(default: this module's own package). A directory without ``__init__.py``,
``contract.py`` and ``core.py`` (for example the checkout root) is refused with
exit code 2.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading

PACKAGE_DIR = Path(__file__).resolve().parent
WORKER = os.environ.get("KURTSHAPE_WORKER") == "1"
LOADED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")
GIT_EXECUTABLE = "git"
GIT_TIMEOUT_S = 10.0
GIT_KILL_TIMEOUT_S = 5.0  # taskkill /T of a git that did not answer
GIT_REAP_TIMEOUT_S = 2.0  # then its pipes, at most this long
# Present in every KurtShape package, older trees without this module included; not in a checkout root.
PACKAGE_MARKERS = ("__init__.py", "contract.py", "core.py")
UNSUPPORTED_OBJECT_FORMAT = "unsupported git object format: only SHA-1 repositories are compared"
_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHA1_ID = re.compile(r"[0-9a-f]{40}")
_MAX_SYMREF_DEPTH = 5
_GIT_REPOSITORY_VARIABLES = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                                       "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                                       "GIT_NAMESPACE"})


def _git_blob(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _source_files(directory):
    """``*.py`` files directly in ``directory``, by name (the package is flat).

    ``scandir`` answers ``is_file`` from the directory listing, so only the
    callers' own ``stat`` touches each file.
    """
    with os.scandir(directory) as entries:
        paths = [Path(entry.path) for entry in entries if entry.name.endswith(".py") and entry.is_file()]
    return sorted(paths, key=lambda path: path.name)


def _file_digest(path):
    """Stat first, then read: an edit racing the read shows up later as a stat mismatch."""
    status = path.stat()
    raw = path.read_bytes()
    text = raw.replace(b"\r\n", b"\n")
    return {"sha256": hashlib.sha256(text).hexdigest(), "size": status.st_size,
            "mtime_ns": status.st_mtime_ns, "blobs": (_git_blob(text), _git_blob(raw))}


def _combine(names_and_digests):
    total = hashlib.sha256()
    for name, digest in names_and_digests:
        total.update(name.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
    return total.hexdigest()


def snapshot(directory=PACKAGE_DIR):
    """Hash every ``*.py`` directly in ``directory`` (LF-normalised); raises OSError on I/O failure.

    Returns ``{directory, sha256, id, count, files}``. ``sha256`` is SHA-256 over
    ``b"<name>\\0<file sha256 hex>\\n"`` in name order; ``id`` is ``"src-"`` plus
    its first 16 hex digits. Each file row holds the LF-text SHA-256, the stat
    size and mtime_ns, and the git blob ids of the LF text and of the raw bytes.
    """
    directory = Path(directory).resolve()
    files = {path.name: _file_digest(path) for path in _source_files(directory)}
    total = _combine((name, row["sha256"]) for name, row in files.items())
    return {"directory": str(directory), "sha256": total, "id": "src-" + total[:16],
            "count": len(files), "files": files}


def _read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace").strip()


def _safe_ref(name):
    parts = name.split("/")
    return bool(name) and name.startswith("refs/") and "" not in parts and ".." not in parts and "\\" not in name


def _resolve_ref(name, git_dir, common_dir, depth=0):
    """Loose ref (worktree dir first, then the common dir), then packed-refs; None if unresolved."""
    if depth > _MAX_SYMREF_DEPTH or not _safe_ref(name):
        return None
    for base in dict.fromkeys((git_dir, common_dir)):
        candidate = base.joinpath(*name.split("/"))
        if candidate.is_file():
            value = _read_text(candidate)
            if value.startswith("ref:"):
                return _resolve_ref(value[4:].strip(), git_dir, common_dir, depth + 1)
            return value if _COMMIT.fullmatch(value) else None
    packed = common_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line[0] in "#^":
                continue
            value, _, ref = line.partition(" ")
            if ref.strip() == name and _COMMIT.fullmatch(value):
                return value
    return None


def _head(git_dir, common_dir):
    """``(commit or None, ref or None)`` from HEAD by file reads only."""
    value = _read_text(git_dir / "HEAD")
    if value.startswith("ref:"):
        ref = value[4:].strip()
        return _resolve_ref(ref, git_dir, common_dir), ref
    return (value if _COMMIT.fullmatch(value) else None), None


def read_head(directory=PACKAGE_DIR):
    """Find the checkout containing ``directory`` and read its HEAD; never raises.

    Returns ``{head, ref, checkout, git_dir, common_dir}`` or None when no usable
    ``.git`` is found. A ``.git`` file (linked worktree) is followed through
    ``gitdir:`` and ``commondir``. ``head`` is None when HEAD does not resolve
    to a commit (for example an unborn branch).
    """
    try:
        start = Path(directory).resolve()
        for folder in (start, *start.parents):
            marker = folder / ".git"
            if marker.is_dir():
                git_dir = marker
            elif marker.is_file():
                value = _read_text(marker)
                if not value.startswith("gitdir:"):
                    return None
                git_dir = Path(value[7:].strip())
                if not git_dir.is_absolute():
                    git_dir = folder / git_dir
            else:
                continue
            git_dir = git_dir.resolve()
            if not (git_dir / "HEAD").is_file():
                return None
            common_dir = git_dir
            if (git_dir / "commondir").is_file():
                common_dir = Path(_read_text(git_dir / "commondir"))
                if not common_dir.is_absolute():
                    common_dir = git_dir / common_dir
                common_dir = common_dir.resolve()
            head, ref = _head(git_dir, common_dir)
            return {"head": head, "ref": ref, "checkout": str(folder), "git_dir": str(git_dir),
                    "common_dir": str(common_dir)}
        return None
    except Exception:
        return None


def _capture():
    if WORKER:
        return None, None, None
    error = None
    for _ in range(2):  # one retry: a file replaced between listing and reading
        try:
            return snapshot(PACKAGE_DIR), read_head(PACKAGE_DIR), None
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    return None, None, error


# 12-15 ms once, main process only; workers load from disk and never report.
SNAPSHOT, GIT_AT_LOAD, CAPTURE_ERROR = _capture()

_PROBE_LOCK = threading.Lock()
_PROBE_THREAD = None
_GIT_RESULT = {"state": "pending"}


class _GitError(RuntimeError):
    """git ran but refused the request (its first stderr line is the message)."""


def _unavailable(reason):
    return {"state": "unavailable", "reason": reason}


def _kill_tree(process):
    """Kill ``process`` and its descendants; never raises, waits at most ``GIT_KILL_TIMEOUT_S``.

    On Windows ``taskkill /T`` finds the descendants through the still-running
    parent, so it runs before the parent itself is killed. Git for Windows'
    ``cmd\\git.exe`` is such a parent: a launcher whose real git inherits the pipes.
    ``process`` still holds its process handle, so the PID cannot be reused meanwhile.
    """
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
        try:
            subprocess.run([str(Path(system_root) / "System32" / "taskkill.exe"), "/T", "/F", "/PID", str(process.pid)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=GIT_KILL_TIMEOUT_S, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def _run_bounded(command, environment, timeout):
    """``(returncode, stdout, stderr)``; raises TimeoutExpired within about ``timeout`` + 7 s.

    ``subprocess.run(timeout=)`` kills only the direct child and then waits for
    the pipes without a limit, so a launcher whose child inherited them held it
    until that child finished. Here the whole tree is killed and the pipes get
    ``GIT_REAP_TIMEOUT_S``; Popen's reader threads are daemons, so one still
    blocked on a surviving descendant ends with that descendant.
    """
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        try:
            process.communicate(timeout=GIT_REAP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            pass
        raise subprocess.TimeoutExpired(command, timeout) from None
    except BaseException:
        _kill_tree(process)
        raise
    return process.returncode, stdout, stderr


def _ls_tree(checkout, head, relative, executable=None, timeout=None):
    """``{file name: blob id}`` for the ``*.py`` blobs directly under ``relative`` at ``head``."""
    checkout = Path(checkout)
    command = [executable or GIT_EXECUTABLE, "-c", "safe.directory=" + checkout.as_posix(), "-C", str(checkout),
               "ls-tree", "-r", "-z", head, "--", relative or "."]
    # Repository overrides inherited from a launching shell or hook would redirect -C.
    environment = {key: value for key, value in os.environ.items() if key.upper() not in _GIT_REPOSITORY_VARIABLES}
    environment.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    returncode, stdout, stderr = _run_bounded(command, environment, GIT_TIMEOUT_S if timeout is None else timeout)
    if returncode != 0:
        message = stderr.decode("utf-8", "replace").strip().splitlines()
        raise _GitError(f"git ls-tree exited {returncode}" + (": " + message[0] if message else ""))
    prefix = relative + "/" if relative else ""
    blobs = {}
    for entry in stdout.decode("utf-8", "replace").split("\0"):
        meta, _, name = entry.partition("\t")
        fields = meta.split()
        if len(fields) != 3 or fields[1] != "blob" or not name.startswith(prefix):
            continue
        name = name[len(prefix):]
        if "/" not in name and name.endswith(".py"):
            blobs[name] = fields[2]
    return blobs


def _git_compare(captured, at_load, executable=None, timeout=None):
    """Compare loaded blobs with the commit checked out at load; never raises."""
    try:
        if captured is None:
            return _unavailable("no source snapshot")
        if at_load is None:
            return _unavailable("not a git checkout")
        if not at_load.get("head"):
            return _unavailable("HEAD did not resolve to a commit at load")
        if not _SHA1_ID.fullmatch(at_load["head"]):
            # The loaded blob ids are SHA-1: every file of a SHA-256 repository would read "modified".
            return _unavailable(UNSUPPORTED_OBJECT_FORMAT)
        try:
            relative = Path(captured["directory"]).relative_to(Path(at_load["checkout"])).as_posix()
        except ValueError:
            return _unavailable("package directory is outside the checkout")
        relative = "" if relative == "." else relative
        try:
            committed = _ls_tree(at_load["checkout"], at_load["head"], relative, executable, timeout)
        except FileNotFoundError:
            return _unavailable("git executable not found")
        except subprocess.TimeoutExpired:
            return _unavailable(f"git ls-tree timed out after {GIT_TIMEOUT_S if timeout is None else timeout:g} s")
        except _GitError as exc:
            return _unavailable(str(exc))
        if not all(_SHA1_ID.fullmatch(blob) for blob in committed.values()):
            return _unavailable(UNSUPPORTED_OBJECT_FORMAT)
        loaded = captured["files"]
        modified = sorted(name for name, row in loaded.items() if name in committed and committed[name] not in row["blobs"])
        untracked = sorted(name for name in loaded if name not in committed)
        deleted = sorted(name for name in committed if name not in loaded)
        return {"state": "ready", "head": at_load["head"], "ref": at_load.get("ref"),
                "dirty": bool(modified or untracked or deleted),
                "modified": modified, "untracked": untracked, "deleted": deleted}
    except Exception as exc:
        return _unavailable(f"{type(exc).__name__}: {exc}")


def _run_git_probe():
    global _GIT_RESULT
    _GIT_RESULT = _git_compare(SNAPSHOT, GIT_AT_LOAD)


def start_git_probe():
    """Start the one background git comparison of this process; idempotent, never raises.

    Returns True only for the call that started the thread. No-op in workers,
    without a snapshot, or outside a git checkout.
    """
    global _PROBE_THREAD, _GIT_RESULT
    if WORKER or SNAPSHOT is None or GIT_AT_LOAD is None:
        return False
    with _PROBE_LOCK:
        if _PROBE_THREAD is not None:
            return False
        if not GIT_AT_LOAD.get("head"):
            _PROBE_THREAD = False  # nothing to run; settled synchronously
            _GIT_RESULT = _git_compare(SNAPSHOT, GIT_AT_LOAD)
            return False
        thread = threading.Thread(target=_run_git_probe, name="kurtshape-build-identity-git", daemon=True)
        try:
            thread.start()
        except Exception as exc:
            _PROBE_THREAD = False
            _GIT_RESULT = _unavailable(f"could not start git probe: {exc}")
            return False
        _PROBE_THREAD = thread
        return True


def wait_for_git(timeout=None):
    """Start the git probe if needed and join it; returns the git state.

    For tests and tools only, never an interactive path: it waits up to ``timeout``.
    """
    start_git_probe()
    thread = _PROBE_THREAD
    if isinstance(thread, threading.Thread):
        thread.join(timeout)
    return _git_state()


def _git_state():
    """The ``git`` block: always carries ``head``, ``ref``, ``head_now`` and ``head_moved``."""
    if GIT_AT_LOAD is None:
        result = _unavailable("not a git checkout")
        result.update(head=None, ref=None, head_now=None, head_moved=False)
        return result
    result = dict(_GIT_RESULT)
    result.setdefault("head", GIT_AT_LOAD.get("head"))
    result.setdefault("ref", GIT_AT_LOAD.get("ref"))
    try:
        head_now, _ = _head(Path(GIT_AT_LOAD["git_dir"]), Path(GIT_AT_LOAD["common_dir"]))
    except Exception:
        head_now = None
    result.update(head_now=head_now, head_moved=head_now != GIT_AT_LOAD.get("head"))
    return result


def compare_disk(captured=None):
    """Compare the package on disk with a snapshot (default: the loaded one); never raises.

    Stats every ``*.py`` and re-hashes the LF text only on a size or mtime
    mismatch. Returns ``{matches_loaded, changed, added, removed}``, or
    ``{"state": "not_captured"}`` without a snapshot.
    """
    captured = SNAPSHOT if captured is None else captured
    if captured is None:
        return {"state": "not_captured"}
    loaded = captured["files"]
    changed, added, seen = [], [], set()
    try:
        present = _source_files(Path(captured["directory"]))
    except OSError:
        present = []
    for path in present:
        name = path.name
        row = loaded.get(name)
        if row is None:
            added.append(name)
            seen.add(name)
            continue
        try:
            status = path.stat()
            if (status.st_size, status.st_mtime_ns) != (row["size"], row["mtime_ns"]) and (
                    hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != row["sha256"]):
                changed.append(name)
        except FileNotFoundError:
            continue  # vanished after listing: reported as removed
        except OSError:
            changed.append(name)  # present but unreadable: cannot match what was loaded
        seen.add(name)
    removed = sorted(name for name in loaded if name not in seen)
    return {"matches_loaded": not (changed or added or removed), "changed": changed, "added": added,
            "removed": removed}


def identity():
    """``capabilities.build``: what this process loaded, git state if known, disk drift. Never blocks on git."""
    if SNAPSHOT is None:
        return _unavailable(CAPTURE_ERROR) if CAPTURE_ERROR else {"state": "not_captured"}
    start_git_probe()
    return {"id": SNAPSHOT["id"], "source_sha256": SNAPSHOT["sha256"], "source_files": SNAPSHOT["count"],
            "source_dir": SNAPSHOT["directory"], "loaded_at": LOADED_AT, "pid": os.getpid(),
            "python": platform.python_version(), "workers_load_from_disk": True,
            "git": _git_state(), "on_disk": compare_disk()}


def summary():
    """Session-file view: ``{id, source_sha256, source_dir, loaded_at, git_head}`` (head at load)."""
    if SNAPSHOT is None:
        return {"state": "not_captured"}
    return {"id": SNAPSHOT["id"], "source_sha256": SNAPSHOT["sha256"], "source_dir": SNAPSHOT["directory"],
            "loaded_at": LOADED_AT, "git_head": (GIT_AT_LOAD or {}).get("head")}


def provenance():
    """Export/STEP provenance ``{id, source_sha256, git_head}``: constant for the life of the process."""
    if SNAPSHOT is None:
        return {"state": "not_captured"}
    return {"id": SNAPSHOT["id"], "source_sha256": SNAPSHOT["sha256"], "git_head": (GIT_AT_LOAD or {}).get("head")}


def _same_directory(left, right):
    def canonical(value):
        path = Path(value)
        try:
            path = path.resolve()
        except (OSError, RuntimeError):
            pass
        return os.path.normcase(os.path.normpath(str(path)))
    return canonical(left) == canonical(right)


def _not_package_reason(directory, files):
    """None for a package directory (``files``: its snapshot rows); otherwise why it is refused.

    The reason names ``<directory>/src/kurtshape`` when that is a package (``directory`` is a checkout root).
    """
    missing = [name for name in PACKAGE_MARKERS if name not in files]
    if not missing:
        return None
    reason = "not a KurtShape package directory (no " + ", ".join(missing) + ")"
    try:
        candidate = Path(directory) / "src" / "kurtshape"
        if all((candidate / name).is_file() for name in PACKAGE_MARKERS):
            reason += f"; the package is {candidate.resolve()}"
    except (OSError, RuntimeError):
        pass
    return reason


def build_verdict(running, checkout_dir):
    """Classify a running build (``capabilities.build``) against a checkout's package directory.

    - ``current``: same directory, same digest (the app runs this code).
    - ``stale``: same directory, different digest (the app predates these edits).
    - ``different_tree``: the app was launched from another directory.
    - ``unknown``: the app reports no identity (it predates Contract 3.2), the
      checkout cannot be hashed, or ``checkout_dir`` is not a package directory
      (it lacks ``__init__.py``, ``contract.py`` or ``core.py``; for example the checkout root).
    Never raises.
    """
    try:
        checkout = snapshot(checkout_dir)
        local = {"source_dir": checkout["directory"], "source_sha256": checkout["sha256"],
                 "id": checkout["id"], "source_files": checkout["count"]}
    except Exception as exc:
        return {"verdict": "unknown", "reason": f"checkout could not be hashed: {exc}",
                "running": running, "checkout": {"source_dir": str(checkout_dir)}}
    refused = _not_package_reason(checkout_dir, checkout["files"])
    if refused:
        return {"verdict": "unknown", "reason": refused, "running": running,
                "checkout": {"source_dir": local["source_dir"]}}
    if (not isinstance(running, dict) or not isinstance(running.get("source_dir"), str)
            or not isinstance(running.get("source_sha256"), str)):
        return {"verdict": "unknown", "reason": "the running app reports no build identity",
                "running": running, "checkout": local}
    shown = {key: running.get(key) for key in ("source_dir", "source_sha256", "id", "loaded_at", "pid")}
    if not _same_directory(running["source_dir"], local["source_dir"]):
        verdict = "different_tree"
    else:
        verdict = "current" if running["source_sha256"] == local["source_sha256"] else "stale"
    return {"verdict": verdict, "running": shown, "checkout": local}


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else list(argv)
    if len(arguments) > 1:
        print("usage: python -B -m kurtshape.build_identity [package_dir]", file=sys.stderr)
        return 2
    directory = Path(arguments[0]) if arguments else PACKAGE_DIR
    if not directory.is_dir():
        print(json.dumps({"error": "not a directory", "source_dir": str(directory)}), file=sys.stderr)
        return 2
    try:
        captured = snapshot(directory)
    except OSError as exc:
        print(json.dumps({"error": f"could not be hashed: {exc}", "source_dir": str(directory)}), file=sys.stderr)
        return 2
    refused = _not_package_reason(directory, captured["files"])
    if refused:
        print(json.dumps({"error": refused, "source_dir": captured["directory"]}), file=sys.stderr)
        return 2
    print(json.dumps({"source_dir": captured["directory"], "source_sha256": captured["sha256"],
                      "id": captured["id"], "source_files": captured["count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
