"""Loaded build identity: LF digests, disk drift, git state at load, worker marker, verdicts.

Every package under test is a private copy (or a hand-built package) under the
suite's scratch folder; the live sources are only read. Module copies are
loaded by file path so each has its own snapshot, git probe and thread.
"""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
import uuid

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape import build_identity as live  # noqa: E402

PACKAGE = (ROOT / "src" / "kurtshape").resolve()
MODULE_PATH = PACKAGE / "build_identity.py"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GIT = shutil.which("git")
GIT_SKIP = support.EXTERNAL_SKIP_PREFIX + " git executable not found on PATH"
IDENTITY_KEYS = {"id", "source_sha256", "source_files", "source_dir", "loaded_at", "pid", "python",
                 "workers_load_from_disk", "git", "on_disk"}
NOT_A_CHECKOUT = {"state": "unavailable", "reason": "not a git checkout", "head": None, "ref": None,
                  "head_now": None, "head_moved": False}

# A launcher whose child inherits its pipes, like Git for Windows' cmd\git.exe in front of the real git.
LAUNCHER = r'''
import os, subprocess, sys, time
open(sys.argv[1], "w").write(str(os.getpid()))
child = subprocess.Popen([sys.executable, "-B", "-c",
                          "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)",
                          sys.argv[2]], stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr)
time.sleep(30)
'''

WORKER_CHILD = r'''
import importlib.util, json, subprocess, sys, threading
calls = []
_original = subprocess.Popen
class _Recorder(_original):
    def __init__(self, *args, **kwargs):
        calls.append(repr(args[0] if args else kwargs.get("args")))
        super().__init__(*args, **kwargs)
subprocess.Popen = _Recorder
names = lambda: sorted(thread.name for thread in threading.enumerate())
before = names()
spec = importlib.util.spec_from_file_location("build_identity_worker_probe", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = {"worker": module.WORKER, "snapshot_is_none": module.SNAPSHOT is None,
          "git_at_load": module.GIT_AT_LOAD, "probe_after_import": module._PROBE_THREAD is not None,
          "threads_before": before, "threads_after_import": names()}
if module.WORKER:
    result.update(identity=module.identity(), summary=module.summary(), provenance=module.provenance(),
                  compare_disk=module.compare_disk(), started=module.start_git_probe(),
                  probe_after_calls=module._PROBE_THREAD is not None)
else:
    result.update(source_files=module.SNAPSHOT["count"], source_dir=module.SNAPSHOT["directory"])
result.update(threads_end=names(), popen_calls=calls)
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    stream.write(json.dumps(result))
'''


def load_copy(package_dir):
    """A private build_identity instance whose PACKAGE_DIR is ``package_dir`` (not in sys.modules)."""
    spec = importlib.util.spec_from_file_location("build_identity_under_test_" + uuid.uuid4().hex[:8],
                                                  Path(package_dir) / "build_identity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lf_digest(directory):
    """Independent re-implementation of the package digest (design probe algorithm)."""
    total = hashlib.sha256()
    names = sorted(entry.name for entry in os.scandir(directory) if entry.name.endswith(".py") and entry.is_file())
    for name in names:
        text = (Path(directory) / name).read_bytes().replace(b"\r\n", b"\n")
        total.update(name.encode() + b"\0" + hashlib.sha256(text).hexdigest().encode() + b"\n")
    return total.hexdigest(), len(names)


def git_blob(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def force_rmtree(path):
    """Remove a scratch tree that holds read-only git objects."""
    def retry(function, name, _info):
        try:
            os.chmod(name, stat.S_IWRITE)
            function(name)
        except OSError:
            pass
    if Path(path).exists():
        shutil.rmtree(path, onerror=retry)


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def crlf(data):
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def process_alive(pid, wait_ms):
    """True if process ``pid`` is still running after waiting up to ``wait_ms`` for it to end (Windows)."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, wait_ms) == 0x102  # WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


class BuildIdentityTests(unittest.TestCase):
    def setUp(self):
        # Module copies read the worker marker at import; this suite is the main-process case.
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("KURTSHAPE_WORKER", None)

    # -- fixtures ---------------------------------------------------------------------------

    def scratch(self, prefix="bi-"):
        folder = support.scratch(self, prefix=prefix)
        self.addCleanup(force_rmtree, folder)
        return folder

    def isolate_from_parent_checkouts(self, root):
        """An invalid ``.git`` marker stops read_head below the live checkout (git would stop too)."""
        write(Path(root) / ".git", b"not a git directory marker\n")

    def copy_live_package(self, root):
        """Copy the live ``*.py`` files (read-only on the source) to ``root/src/kurtshape``."""
        target = Path(root) / "src" / "kurtshape"
        target.mkdir(parents=True)
        for name, _ in sorted(live.SNAPSHOT["files"].items()):
            source = PACKAGE / name
            if source.is_file():
                shutil.copyfile(source, target / name)
        self.isolate_from_parent_checkouts(root)
        return target

    def small_package(self, root, files):
        target = Path(root) / "src" / "kurtshape"
        write(target / "build_identity.py", MODULE_PATH.read_bytes())
        for name, data in files.items():
            write(target / name, data)
        return target

    def fake_git_dir(self, root, commit, branch="main"):
        """A minimal file-only repository: enough for read_head, not for git itself."""
        write(Path(root) / ".git" / "HEAD", f"ref: refs/heads/{branch}\n".encode())
        write(Path(root) / ".git" / "refs" / "heads" / branch, (commit + "\n").encode())
        return Path(root) / ".git" / "refs" / "heads" / branch

    def git(self, cwd, *args, safe=()):
        empty = Path(cwd).parent / "empty.gitconfig"
        if not empty.exists():
            empty.write_bytes(b"")
        environment = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(empty),
                           GIT_TERMINAL_PROMPT="0")
        command = [GIT, "-c", "user.name=KurtShape Test", "-c", "user.email=test@example.invalid",
                   "-c", "commit.gpgsign=false", "-c", "core.safecrlf=false"]
        for folder in (cwd, *safe):
            command += ["-c", "safe.directory=" + Path(folder).resolve().as_posix()]
        process = subprocess.run(command + list(args), cwd=cwd, env=environment, capture_output=True,
                                 stdin=subprocess.DEVNULL, timeout=60, creationflags=NO_WINDOW)
        self.assertEqual(process.returncode, 0, (args, process.stderr.decode("utf-8", "replace")))
        return process.stdout.decode("utf-8", "replace").strip()

    def wait_ready(self, module):
        state = module.wait_for_git(30)
        self.assertEqual(state["state"], "ready", state)
        return state

    # -- digests ----------------------------------------------------------------------------

    def test_snapshot_digest_is_line_ending_independent(self):
        root = self.scratch()
        files = {"a.py": b"x = 1\nprint(x)\n", "b.py": b"def f():\n    return 2\n\n", "c.py": b"pass"}
        for name, data in files.items():
            write(root / "lf" / name, data)
            write(root / "crlf" / name, crlf(data))
        for folder in ("lf", "crlf"):  # never part of the flat package digest
            write(root / folder / "notes.txt", uuid.uuid4().hex.encode())
            write(root / folder / "sub" / "nested.py", uuid.uuid4().hex.encode())
        lf, windows = live.snapshot(root / "lf"), live.snapshot(root / "crlf")
        self.assertNotEqual((root / "lf" / "a.py").read_bytes(), (root / "crlf" / "a.py").read_bytes())
        self.assertEqual(lf["sha256"], windows["sha256"])
        self.assertEqual(lf["id"], "src-" + lf["sha256"][:16])
        self.assertEqual(lf["id"], windows["id"])
        self.assertEqual((lf["count"], sorted(lf["files"])), (3, ["a.py", "b.py", "c.py"]))
        self.assertEqual(lf["sha256"], lf_digest(root / "lf")[0])
        for name, data in files.items():
            self.assertEqual(lf["files"][name]["sha256"], windows["files"][name]["sha256"])
            self.assertEqual(lf["files"][name]["sha256"], hashlib.sha256(data).hexdigest())
            # LF blob id first, raw blob id second: a CRLF working tree matches either form in git.
            self.assertEqual(windows["files"][name]["blobs"], (git_blob(data), git_blob(crlf(data))))
            self.assertEqual(windows["files"][name]["size"], len(crlf(data)))
        write(root / "crlf" / "b.py", crlf(files["b.py"]) + b"# edit\r\n")
        self.assertNotEqual(live.snapshot(root / "crlf")["sha256"], lf["sha256"])
        (root / "lf" / "c.py").rename(root / "lf" / "d.py")
        self.assertNotEqual(live.snapshot(root / "lf")["sha256"], lf["sha256"], "file names are part of the digest")

    def test_on_disk_reports_changed_added_removed_without_reload(self):
        package = self.copy_live_package(self.scratch())
        module = load_copy(package)
        before = module.identity()
        self.assertEqual(set(before), IDENTITY_KEYS)
        self.assertEqual(before["source_dir"], str(package.resolve()))
        on_disk_files = sorted(path.name for path in package.glob("*.py"))
        # Every package file is hashed, not only the modules a process happens to import.
        self.assertEqual(before["source_files"], len(on_disk_files))
        self.assertEqual(sorted(module.SNAPSHOT["files"]), on_disk_files)
        self.assertEqual(before["on_disk"], {"matches_loaded": True, "changed": [], "added": [], "removed": []})
        self.assertEqual(before["git"], NOT_A_CHECKOUT)
        # capabilities calls compare_disk every time: an unchanged package is answered from stat alone.
        reads, original_read = [], Path.read_bytes

        def counting_read(path):
            reads.append(path.name)
            return original_read(path)

        with patch.object(Path, "read_bytes", counting_read):
            self.assertTrue(module.compare_disk()["matches_loaded"])
        self.assertEqual(reads, [])
        loaded = json.dumps(module.SNAPSHOT, sort_keys=True)
        names = [name for name in on_disk_files if name not in {"build_identity.py", "contract.py"}]
        removed, line_endings, touched = names[0], names[1], names[2]
        write(package / "contract.py", (package / "contract.py").read_bytes() + b"\n# edited after load\n")
        write(package / "zz_added_after_load.py", b"VALUE = 1\n")
        (package / removed).unlink()
        raw = (package / line_endings).read_bytes()
        flipped = raw.replace(b"\r\n", b"\n") if b"\r\n" in raw else crlf(raw)
        self.assertNotEqual(len(flipped), len(raw))
        write(package / line_endings, flipped)
        status = (package / touched).stat()
        os.utime(package / touched, ns=(status.st_atime_ns, status.st_mtime_ns + 7_000_000_000))
        with patch.object(Path, "read_bytes", counting_read):
            after = module.identity()
        # Only the files whose size or mtime changed are re-read; added and removed files never are.
        self.assertEqual(sorted(reads), sorted(["contract.py", line_endings, touched]))
        for key in ("id", "source_sha256", "source_files", "source_dir", "loaded_at"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(json.dumps(module.SNAPSHOT, sort_keys=True), loaded)
        self.assertEqual(after["on_disk"], {"matches_loaded": False, "changed": ["contract.py"],
                                            "added": ["zz_added_after_load.py"], "removed": [removed]})
        self.assertEqual(module.provenance(), {"id": before["id"], "source_sha256": before["source_sha256"],
                                               "git_head": None})
        current = module.snapshot(package)
        self.assertNotEqual(current["sha256"], before["source_sha256"])
        self.assertEqual(current["sha256"], lf_digest(package)[0])
        self.assertTrue(module.compare_disk(current)["matches_loaded"])

    # -- git --------------------------------------------------------------------------------

    @unittest.skipUnless(GIT, GIT_SKIP)
    def test_git_comparison_uses_loaded_blobs_against_head_at_load(self):
        repo = self.scratch() / "r"
        package = self.small_package(repo, {
            "a.py": crlf(b"A = 1\nB = 2\n"),       # CRLF working tree, stored LF (autocrlf)
            "b.py": b"def b():\n    return 1\n",
            "c.py": b"C = 3\n",                    # stored LF; flipped to CRLF before load
            "d.py": crlf(b"D = 4\n"),              # stored with CRLF bytes (autocrlf off)
            "gone.py": b"GONE = True\n",
        })
        write(package / "sub" / "nested.py", b"NESTED = 1\n")
        write(repo / "outside.py", b"OUTSIDE = 1\n")
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "-c", "core.autocrlf=false", "add", "src/kurtshape/d.py")
        self.git(repo, "-c", "core.autocrlf=true", "add", "src/kurtshape/build_identity.py", "src/kurtshape/a.py",
                 "src/kurtshape/b.py", "src/kurtshape/c.py", "src/kurtshape/gone.py", "src/kurtshape/sub/nested.py",
                 "outside.py")
        self.git(repo, "commit", "-q", "-m", "first")
        first = self.git(repo, "rev-parse", "HEAD")
        stored = {name: self.git(repo, "rev-parse", f"HEAD:src/kurtshape/{name}") for name in ("a.py", "d.py")}
        self.assertEqual(stored["a.py"], git_blob(b"A = 1\nB = 2\n"), "a.py must be stored LF")
        self.assertEqual(stored["d.py"], git_blob(crlf(b"D = 4\n")), "d.py must be stored CRLF")
        # Working tree at load: content edit, new file, deletion, and a line-ending-only flip.
        write(package / "b.py", b"def b():\n    return 2\n")
        write(package / "new.py", b"NEW = 1\n")
        (package / "gone.py").unlink()
        write(package / "c.py", crlf(b"C = 3\n"))
        # Content view of git at load (autocrlf=true). `git status` would also flag c.py: it reports any
        # size change as modified without comparing normalised content.
        changes = self.git(repo, "-c", "core.autocrlf=true", "diff", "--name-status", "HEAD", "--", "src/kurtshape")
        others = self.git(repo, "ls-files", "--others", "--exclude-standard", "--", "src/kurtshape")

        module = load_copy(package)
        self.assertIsNone(module._PROBE_THREAD, "importing never starts the git probe")
        self.assertEqual((module.GIT_AT_LOAD["head"], module.GIT_AT_LOAD["ref"]), (first, "refs/heads/main"))
        self.assertEqual(module.SNAPSHOT["files"]["a.py"]["blobs"][0], stored["a.py"])
        self.assertEqual(module.SNAPSHOT["files"]["d.py"]["blobs"][1], stored["d.py"])
        # After load: HEAD moves to a commit containing the loaded edits, and the disk changes again.
        self.git(repo, "-c", "core.autocrlf=true", "add", "-A")
        self.git(repo, "commit", "-q", "-m", "second")
        second = self.git(repo, "rev-parse", "HEAD")
        write(package / "a.py", crlf(b"A = 10\nB = 2\n"))
        # A repository override inherited from a launching shell or hook must not redirect the probe.
        os.environ["GIT_DIR"] = str(repo.parent / "not-this-repository")

        identity = module.identity()
        self.assertIn(identity["git"]["state"], {"pending", "ready"})
        git = self.wait_ready(module)
        self.assertEqual({key: git[key] for key in ("head", "ref", "dirty", "modified", "untracked", "deleted")},
                         {"head": first, "ref": "refs/heads/main", "dirty": True, "modified": ["b.py"],
                          "untracked": ["new.py"], "deleted": ["gone.py"]})
        self.assertEqual((git["head_now"], git["head_moved"]), (second, True))
        # The LF comparison agrees with git's normalised content view at load: no line-ending false positives.
        entries = sorted([tuple(line.split("\t")) for line in changes.splitlines()]
                         + [("??", path) for path in others.splitlines()])
        self.assertEqual(entries, [("??", "src/kurtshape/new.py"), ("D", "src/kurtshape/gone.py"),
                                   ("M", "src/kurtshape/b.py")])
        final = module.identity()
        self.assertEqual(final["git"], git)
        self.assertEqual(final["on_disk"]["changed"], ["a.py"])
        self.assertFalse(module.start_git_probe(), "one git probe per process")

    @unittest.skipUnless(GIT, GIT_SKIP)
    def test_sha256_repository_is_reported_unavailable_not_dirty(self):
        """The loaded blob ids are SHA-1: a clean SHA-256 checkout must not read as every file modified."""
        repo = self.scratch() / "r"
        package = self.small_package(repo, {"a.py": b"A = 1\n"})
        empty = repo.parent / "empty.gitconfig"
        empty.write_bytes(b"")
        init = subprocess.run([GIT, "init", "-q", "--object-format=sha256", "-b", "main"], cwd=repo,
                              env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(empty)),
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=60, creationflags=NO_WINDOW)
        if init.returncode != 0:
            self.skipTest(support.EXTERNAL_SKIP_PREFIX + " this git cannot create SHA-256 repositories")
        self.git(repo, "add", "src")
        self.git(repo, "commit", "-q", "-m", "first")
        head = self.git(repo, "rev-parse", "HEAD")
        self.assertEqual(len(head), 64)
        self.assertEqual(self.git(repo, "status", "--porcelain"), "", "the checkout is clean")
        # git itself answers with SHA-256 blob ids, which never equal a loaded SHA-1 blob id.
        committed = live._ls_tree(repo.resolve(), head, "src/kurtshape")
        self.assertEqual(sorted(committed), ["a.py", "build_identity.py"])
        self.assertTrue(all(len(blob) == 64 for blob in committed.values()), committed)

        module = load_copy(package)
        self.assertEqual((module.GIT_AT_LOAD["head"], module.GIT_AT_LOAD["ref"]), (head, "refs/heads/main"))
        module.identity()
        git = module.wait_for_git(30)
        self.assertEqual(git, {"state": "unavailable", "reason": module.UNSUPPORTED_OBJECT_FORMAT, "head": head,
                               "ref": "refs/heads/main", "head_now": head, "head_moved": False})

    @unittest.skipUnless(GIT, GIT_SKIP)
    def test_git_worktree_gitdir_file_resolves_head(self):
        scratch = self.scratch()
        repo, worktree, detached = scratch / "r", scratch / "wt", scratch / "wd"
        package = self.small_package(repo, {"a.py": b"A = 1\n"})
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "add", "src")
        self.git(repo, "commit", "-q", "-m", "first")
        first = self.git(repo, "rev-parse", "HEAD")
        self.git(repo, "worktree", "add", "-q", "-b", "feature", str(worktree))
        self.git(repo, "worktree", "add", "-q", "--detach", str(detached), first)
        common = (repo / ".git").resolve()
        self.assertTrue((worktree / ".git").is_file())

        head = live.read_head(worktree / "src" / "kurtshape")
        self.assertEqual(head, {"head": first, "ref": "refs/heads/feature", "checkout": str(worktree.resolve()),
                                "git_dir": str((common / "worktrees" / "wt").resolve()),
                                "common_dir": str(common)})
        loose = live.read_head(detached / "src" / "kurtshape")
        self.assertEqual((loose["head"], loose["ref"], loose["common_dir"]), (first, None, str(common)))
        self.assertEqual(live.read_head(package)["git_dir"], str(common))
        # Packed refs live in the common dir; a relative gitdir: line resolves from the worktree.
        self.git(repo, "pack-refs", "--all")
        self.assertFalse((common / "refs" / "heads" / "feature").exists())
        gitdir = Path(head["git_dir"])
        (worktree / ".git").unlink()  # Git for Windows marks it hidden; a hidden file cannot be reopened for writing
        (worktree / ".git").write_text("gitdir: " + Path(os.path.relpath(gitdir, worktree)).as_posix() + "\n",
                                       encoding="utf-8")
        self.assertEqual(live.read_head(worktree / "src" / "kurtshape"), head)

        module = load_copy(worktree / "src" / "kurtshape")
        module.identity()
        git = self.wait_ready(module)
        self.assertEqual({key: git[key] for key in ("head", "ref", "dirty", "head_now", "head_moved")},
                         {"head": first, "ref": "refs/heads/feature", "dirty": False, "head_now": first,
                          "head_moved": False})

    def test_git_unavailable_is_reported_not_raised(self):
        scratch = self.scratch()
        # Outside any usable checkout: no probe, no thread, a reason instead of an exception.
        isolated = self.copy_live_package(scratch / "copy")
        module = load_copy(isolated)
        self.assertIsNone(module.GIT_AT_LOAD)
        self.assertFalse(module.start_git_probe())
        self.assertIsNone(module._PROBE_THREAD)
        self.assertEqual(module.identity()["git"], NOT_A_CHECKOUT)
        # Broken repository layouts: read_head returns None or a None head, never raises.
        cases = {
            "garbage-marker": {".git": b"\x00\xff not a gitdir"},
            "missing-gitdir": {".git": b"gitdir: does/not/exist\n"},
            "no-head": {".git/config": b"[core]\n"},
            "unborn": {".git/HEAD": b"ref: refs/heads/unborn\n"},
            "garbage-head": {".git/HEAD": b"\xff\xfe nonsense\n"},
            # <root>/.git/refs/../../outside is <root>/outside, a valid-looking commit id that _safe_ref must refuse.
            "escaping-ref": {".git/HEAD": b"ref: refs/../../outside\n", "outside": b"a" * 40 + b"\n"},
            "bad-packed": {".git/HEAD": b"ref: refs/heads/main\n", ".git/packed-refs": b"\x00junk\nzz refs/heads/main\n"},
        }
        self.assertFalse(live._safe_ref("refs/../../outside"))
        for name, files in cases.items():
            with self.subTest(layout=name):
                root = scratch / name
                for relative, data in files.items():
                    write(root / relative, data)
                (root / "pkg").mkdir()
                if name == "escaping-ref":
                    escaped = (root / ".git").joinpath("refs", "..", "..", "outside")
                    self.assertTrue(escaped.is_file(), "the fixture's escape lands on the planted file")
                    self.assertEqual(escaped.resolve(), (root / "outside").resolve())
                head = live.read_head(root / "pkg")
                if name in {"garbage-marker", "missing-gitdir", "no-head"}:
                    self.assertIsNone(head)
                else:
                    self.assertIsNotNone(head)
                    self.assertIsNone(head["head"])
                    self.assertEqual(live._git_compare(live.snapshot(root / "pkg"), head),
                                     {"state": "unavailable", "reason": "HEAD did not resolve to a commit at load"})

        captured = live.snapshot(isolated)
        at_load = {"head": "1" * 40, "ref": "refs/heads/main", "checkout": str(isolated.parent.parent)}
        missing = live._git_compare(captured, at_load, executable="kurtshape-no-such-git-" + uuid.uuid4().hex[:6])
        self.assertEqual(missing, {"state": "unavailable", "reason": "git executable not found"})

        # The git subprocess contract: no window, no stdin, repository overrides dropped, a bounded wait,
        # and on timeout the whole process tree is killed before the pipes get a bounded reap.
        started, killed = [], []

        class HangingGit:
            pid = 0  # never a real process: _kill_tree is replaced below

            def __init__(self, args, **kwargs):
                self.args, self.kwargs, self.timeouts = args, kwargs, []
                started.append(self)

            def communicate(self, timeout=None):
                self.timeouts.append(timeout)
                raise subprocess.TimeoutExpired(self.args, timeout)

        os.environ.update(GIT_DIR=str(scratch / "not-this-repository"), GIT_WORK_TREE=str(scratch))
        try:
            with patch("subprocess.Popen", HangingGit), patch.object(live, "_kill_tree", killed.append):
                self.assertEqual(live._git_compare(captured, at_load),
                                 {"state": "unavailable", "reason": "git ls-tree timed out after 10 s"})
        finally:
            for name in ("GIT_DIR", "GIT_WORK_TREE"):  # this test's own git commands below must not see them
                os.environ.pop(name, None)
        self.assertEqual(len(started), 1)
        call = started[0]
        checkout = Path(at_load["checkout"])
        self.assertEqual(call.args, [live.GIT_EXECUTABLE, "-c", "safe.directory=" + checkout.as_posix(), "-C",
                                     str(checkout), "ls-tree", "-r", "-z", "1" * 40, "--", "src/kurtshape"])
        self.assertIs(call.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual((call.kwargs["stdout"], call.kwargs["stderr"]), (subprocess.PIPE, subprocess.PIPE))
        self.assertEqual(call.kwargs["creationflags"] & NO_WINDOW, NO_WINDOW)
        if os.name == "nt":
            self.assertTrue(NO_WINDOW)
        environment = {key.upper(): value for key, value in call.kwargs["env"].items()}
        self.assertFalse({"GIT_DIR", "GIT_WORK_TREE"} & set(environment), "repository overrides are dropped")
        self.assertEqual((environment["GIT_TERMINAL_PROMPT"], environment["GIT_OPTIONAL_LOCKS"]), ("0", "0"))
        self.assertEqual(call.timeouts, [live.GIT_TIMEOUT_S, live.GIT_REAP_TIMEOUT_S])
        self.assertEqual(live.GIT_TIMEOUT_S, 10.0)
        self.assertEqual(killed, [call])

        # Only SHA-1 repositories are compared; SHA-256 ids are refused, never reported as modified.
        with patch.object(live, "_ls_tree", return_value={name: "b" * 64 for name in captured["files"]}):
            self.assertEqual(live._git_compare(captured, at_load),
                             {"state": "unavailable", "reason": live.UNSUPPORTED_OBJECT_FORMAT})
        with patch.object(live, "_ls_tree", side_effect=AssertionError("git must not run")):
            self.assertEqual(live._git_compare(captured, dict(at_load, head="c" * 64)),
                             {"state": "unavailable", "reason": live.UNSUPPORTED_OBJECT_FORMAT})
        with patch.object(live, "_ls_tree", side_effect=ValueError("broken output")):
            self.assertEqual(live._git_compare(captured, at_load),
                             {"state": "unavailable", "reason": "ValueError: broken output"})
        self.assertEqual(live._git_compare(captured, dict(at_load, checkout=str(scratch / "elsewhere"))),
                         {"state": "unavailable", "reason": "package directory is outside the checkout"})
        self.assertEqual(live._git_compare(captured, None), {"state": "unavailable", "reason": "not a git checkout"})
        self.assertEqual(live._git_compare(None, at_load), {"state": "unavailable", "reason": "no source snapshot"})

        # A checkout whose git cannot answer: identity() still reports everything else.
        repo = scratch / "fake"
        package = self.small_package(repo, {"a.py": b"A = 1\n"})
        self.fake_git_dir(repo, "2" * 40)
        module = load_copy(package)
        module.GIT_EXECUTABLE = "kurtshape-no-such-git-" + uuid.uuid4().hex[:6]
        identity = module.identity()
        self.assertEqual(set(identity), IDENTITY_KEYS)
        git = module.wait_for_git(30)
        self.assertEqual({key: git[key] for key in ("state", "reason", "head", "ref", "head_now", "head_moved")},
                         {"state": "unavailable", "reason": "git executable not found", "head": "2" * 40,
                          "ref": "refs/heads/main", "head_now": "2" * 40, "head_moved": False})
        if GIT:
            # A real git that rejects the request (commit absent) is reported with git's own message.
            real = scratch / "real"
            self.small_package(real, {"a.py": b"A = 1\n"})
            self.git(real, "init", "-q", "-b", "main")
            failed = live._git_compare(live.snapshot(real / "src" / "kurtshape"),
                                       {"head": "3" * 40, "ref": None, "checkout": str(real.resolve())})
            self.assertEqual(failed["state"], "unavailable")
            self.assertTrue(failed["reason"].startswith("git ls-tree exited "), failed)

    @unittest.skipUnless(os.name == "nt", support.EXTERNAL_SKIP_PREFIX + " Windows process-tree kill")
    def test_git_timeout_kills_the_launcher_and_its_child(self):
        """subprocess.run(timeout=) waited for a launcher's child (cmd\\git.exe -> git.exe) that holds the pipes."""
        scratch = self.scratch()
        launcher = write(scratch / "launcher.py", LAUNCHER.encode())
        launcher_pid, child_pid = scratch / "launcher.pid", scratch / "child.pid"
        command = [sys.executable, "-B", str(launcher), str(launcher_pid), str(child_pid)]
        timeout = 3.0
        began = time.perf_counter()
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            live._run_bounded(command, dict(os.environ), timeout)
        elapsed = time.perf_counter() - began
        self.assertEqual((raised.exception.cmd, raised.exception.timeout), (command, timeout))
        # Both processes sleep 30 s: only the tree kill ends them now.
        self.assertTrue(launcher_pid.is_file() and child_pid.is_file(), "the launcher started its child in time")
        for marker in (launcher_pid, child_pid):
            pid = int(marker.read_text(encoding="utf-8"))
            self.assertFalse(process_alive(pid, 5000), f"{marker.stem} {pid} survived the timeout")
        self.assertGreaterEqual(elapsed, timeout)
        self.assertLess(elapsed, timeout + live.GIT_KILL_TIMEOUT_S + live.GIT_REAP_TIMEOUT_S, elapsed)

    def test_identity_never_blocks_on_git(self):
        repo = self.scratch() / "r"
        package = self.small_package(repo, {"a.py": b"A = 1\n", "b.py": crlf(b"B = 2\n")})
        self.fake_git_dir(repo, "4" * 40)
        module = load_copy(package)
        self.assertIsNone(module._PROBE_THREAD)
        release, calls = threading.Event(), []
        self.addCleanup(release.set)

        def slow_ls_tree(checkout, head, relative, executable=None, timeout=None):
            calls.append((Path(checkout), head, relative))
            release.wait(10)
            return {name: row["blobs"][0] for name, row in module.SNAPSHOT["files"].items()}

        module._ls_tree = slow_ls_tree
        elapsed = []
        for _ in range(3):
            began = time.perf_counter()
            identity = module.identity()
            elapsed.append(time.perf_counter() - began)
            self.assertEqual({key: identity["git"][key] for key in ("state", "head", "ref")},
                             {"state": "pending", "head": "4" * 40, "ref": "refs/heads/main"})
        self.assertLess(max(elapsed), 1.0, elapsed)
        self.assertLess(min(elapsed), 0.05, elapsed)
        self.assertIsInstance(module._PROBE_THREAD, threading.Thread)
        self.assertTrue(module._PROBE_THREAD.daemon)
        release.set()
        git = self.wait_ready(module)
        self.assertEqual(calls, [(repo.resolve(), "4" * 40, "src/kurtshape")], "one probe for many calls")
        self.assertEqual((git["dirty"], git["modified"], git["untracked"], git["deleted"]), (False, [], [], []))

    def test_worker_marker_skips_capture(self):
        scratch = self.scratch()
        child = write(scratch / "child.py", WORKER_CHILD.encode())
        results = {}
        for worker in (True, False):
            environment = {key: value for key, value in os.environ.items() if key != "KURTSHAPE_WORKER"}
            if worker:
                environment["KURTSHAPE_WORKER"] = "1"
            output = scratch / f"worker-{worker}.json"
            process = subprocess.run([sys.executable, "-B", str(child), str(MODULE_PATH), str(output)],
                                     cwd=scratch, env=environment, capture_output=True, stdin=subprocess.DEVNULL,
                                     timeout=120, creationflags=NO_WINDOW)
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
            results[worker] = json.loads(output.read_text(encoding="utf-8"))
        worker, main = results[True], results[False]
        self.assertTrue(worker["worker"])
        self.assertTrue(worker["snapshot_is_none"])
        self.assertIsNone(worker["git_at_load"])
        for view in ("identity", "summary", "provenance", "compare_disk"):
            self.assertEqual(worker[view], {"state": "not_captured"}, view)
        self.assertFalse(worker["started"])
        self.assertFalse(worker["probe_after_calls"])
        self.assertEqual(worker["threads_end"], worker["threads_before"], "no git thread in a worker")
        self.assertEqual(worker["popen_calls"], [])
        # Control: the main-process marker is absent, so the package is hashed, but importing starts nothing.
        self.assertFalse(main["worker"])
        self.assertFalse(main["snapshot_is_none"])
        self.assertEqual(main["source_dir"], str(PACKAGE))
        self.assertGreater(main["source_files"], 0)
        self.assertFalse(main["probe_after_import"])
        self.assertEqual(main["threads_end"], main["threads_before"])
        self.assertEqual(main["popen_calls"], [])

    def test_capture_failure_is_reported_not_raised(self):
        """A package that cannot be read at startup: import succeeds, identity names the error, nothing runs."""
        repo = self.scratch() / "r"
        package = self.small_package(repo, {"a.py": b"A = 1\n"})
        self.fake_git_dir(repo, "7" * 40)
        attempts = []

        def failing_read(path):
            attempts.append(path.name)
            raise OSError(5, "simulated read failure")

        with patch.object(Path, "read_bytes", failing_read):
            module = load_copy(package)
        self.assertEqual(len(attempts), 2, "one retry, then the error is kept")
        self.assertIsNone(module.SNAPSHOT)
        self.assertIsNone(module.GIT_AT_LOAD)
        self.assertTrue(module.CAPTURE_ERROR.startswith("OSError: "), module.CAPTURE_ERROR)
        self.assertEqual(module.identity(), {"state": "unavailable", "reason": module.CAPTURE_ERROR})
        for view in (module.summary, module.provenance, module.compare_disk):
            self.assertEqual(view(), {"state": "not_captured"}, view.__name__)
        self.assertFalse(module.start_git_probe())
        self.assertIsNone(module._PROBE_THREAD)
        json.dumps(module.identity(), allow_nan=False)

    def test_provenance_is_constant_across_git_completion_and_disk_edits(self):
        repo = self.scratch() / "r"
        package = self.small_package(repo, {"a.py": b"A = 1\n"})
        ref = self.fake_git_dir(repo, "5" * 40)
        module = load_copy(package)
        module._ls_tree = lambda checkout, head, relative, executable=None, timeout=None: {
            name: row["blobs"][0] for name, row in module.SNAPSHOT["files"].items()}
        first, session = module.provenance(), module.summary()
        self.assertEqual(first, {"id": module.SNAPSHOT["id"], "source_sha256": module.SNAPSHOT["sha256"],
                                 "git_head": "5" * 40})
        self.assertEqual(session, {"id": module.SNAPSHOT["id"], "source_sha256": module.SNAPSHOT["sha256"],
                                   "source_dir": str(package.resolve()), "loaded_at": module.LOADED_AT,
                                   "git_head": "5" * 40})
        self.assertIn(module.identity()["git"]["state"], {"pending", "ready"})
        self.wait_ready(module)
        settled = module.provenance()
        write(package / "a.py", b"A = 2\n")
        write(package / "late.py", b"LATE = 1\n")
        write(ref, ("6" * 40 + "\n").encode())
        identity = module.identity()
        self.assertEqual((identity["git"]["head_now"], identity["git"]["head_moved"]), ("6" * 40, True))
        self.assertFalse(identity["on_disk"]["matches_loaded"])
        later = module.provenance()
        self.assertEqual([settled, later], [first, first])
        self.assertEqual(module.summary(), session)
        encoded = {json.dumps(item, sort_keys=True, allow_nan=False) for item in (first, settled, later)}
        self.assertEqual(len(encoded), 1)
        later["git_head"] = "mutated"
        self.assertEqual(module.provenance(), first, "callers get a fresh dict")

    def test_checkout_digest_differs_from_loaded_tree(self):
        scratch = self.scratch()
        loaded_tree = self.copy_live_package(scratch / "app")
        other_tree = self.copy_live_package(scratch / "green")
        module = load_copy(loaded_tree)
        # What the app's capabilities.build would carry over the wire.
        running = json.loads(json.dumps(module.identity(), allow_nan=False))
        current = module.build_verdict(running, loaded_tree)
        self.assertEqual(current["verdict"], "current")
        self.assertEqual(current["checkout"], {"source_dir": str(loaded_tree.resolve()),
                                               "source_sha256": running["source_sha256"], "id": running["id"],
                                               "source_files": running["source_files"]})
        if os.name == "nt":
            spelled = str(loaded_tree).upper() + os.sep
            self.assertEqual(module.build_verdict(running, spelled)["verdict"], "current")
        # Same digest, different directory: still another tree (its workers and edits are elsewhere).
        self.assertEqual(module.build_verdict(running, other_tree)["verdict"], "different_tree")
        write(loaded_tree / "contract.py", (loaded_tree / "contract.py").read_bytes() + b"\n# checkout edit\n")
        stale = module.build_verdict(running, loaded_tree)
        self.assertEqual(stale["verdict"], "stale")
        self.assertNotEqual(stale["checkout"]["source_sha256"], stale["running"]["source_sha256"])
        self.assertEqual(module.build_verdict(running, other_tree)["verdict"], "different_tree")
        for payload in (None, {}, {"state": "not_captured"}, {"source_dir": 3, "source_sha256": "x"}):
            with self.subTest(running=payload):
                self.assertEqual(module.build_verdict(payload, loaded_tree)["verdict"], "unknown")
        missing = module.build_verdict(running, scratch / "missing")
        self.assertEqual(missing["verdict"], "unknown")
        self.assertIn("checkout could not be hashed", missing["reason"])
        # A directory without __init__.py, contract.py and core.py is not a package: never the digest of
        # whatever *.py it holds (the empty set for a checkout root) reported as "different_tree".
        not_package = "not a KurtShape package directory (no "
        loose = scratch / "loose"
        write(loose / "x.py", b"X = 1\n")
        write(loose / "core.py", b"CORE = 1\n")
        (scratch / "empty").mkdir()
        checkout_root = scratch / "app"
        for directory, reason in (
                (checkout_root,
                 not_package + f"__init__.py, contract.py, core.py); the package is {loaded_tree.resolve()}"),
                (loose, not_package + "__init__.py, contract.py)"),
                (scratch / "empty", not_package + "__init__.py, contract.py, core.py)")):
            with self.subTest(directory=directory.name):
                refused = module.build_verdict(running, directory)
                self.assertEqual((refused["verdict"], refused["reason"]), ("unknown", reason))
                self.assertEqual(refused["checkout"], {"source_dir": str(directory.resolve())})
        # An older KurtShape tree (no build_identity.py yet) is still a package: another tree, not unknown.
        older = scratch / "older" / "src" / "kurtshape"
        older.mkdir(parents=True)
        for name in ("__init__.py", "contract.py", "core.py", "ui.py"):
            shutil.copyfile(loaded_tree / name, older / name)
        self.assertFalse((older / "build_identity.py").exists())
        self.assertEqual(module.build_verdict(running, older)["verdict"], "different_tree")
        # The module CLI reports the checkout digest without FreeCAD.
        process = subprocess.run([sys.executable, "-B", "-m", "kurtshape.build_identity", str(loaded_tree)],
                                 cwd=ROOT / "src", capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
                                 creationflags=NO_WINDOW)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
        printed = json.loads(process.stdout.decode("utf-8"))
        self.assertEqual(printed, {"source_dir": str(loaded_tree.resolve()),
                                   "source_sha256": stale["checkout"]["source_sha256"],
                                   "id": stale["checkout"]["id"], "source_files": stale["checkout"]["source_files"]})
        older_cli = subprocess.run([sys.executable, "-B", "-m", "kurtshape.build_identity", str(older)],
                                   cwd=ROOT / "src", capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
                                   creationflags=NO_WINDOW)
        self.assertEqual(older_cli.returncode, 0, older_cli.stderr.decode("utf-8", "replace"))
        self.assertEqual(json.loads(older_cli.stdout.decode("utf-8"))["source_files"], 4)
        for directory, error in ((scratch / "missing", "not a directory"),
                                 (checkout_root, not_package + "__init__.py, contract.py, core.py); "
                                                 f"the package is {loaded_tree.resolve()}"),
                                 (loose, not_package + "__init__.py, contract.py)")):
            with self.subTest(cli=directory.name):
                refused = subprocess.run([sys.executable, "-B", "-m", "kurtshape.build_identity", str(directory)],
                                         cwd=ROOT / "src", capture_output=True, stdin=subprocess.DEVNULL,
                                         timeout=120, creationflags=NO_WINDOW)
                self.assertEqual(refused.returncode, 2)
                self.assertEqual(refused.stdout, b"")
                self.assertEqual(json.loads(refused.stderr.decode("utf-8"))["error"], error)

    def test_module_is_stdlib_only(self):
        """Importable without FreeCAD and loadable by file path (run_native_tests, assistant_client)."""
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(item.name.split(".")[0] for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "no relative imports")
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported)
        self.assertEqual(sorted(name for name in imported if name not in sys.stdlib_module_names), [])

    def test_live_package_identity_matches_recomputation(self):
        identity = live.identity()
        self.assertEqual(set(identity), IDENTITY_KEYS)
        json.dumps(identity, allow_nan=False)
        self.assertEqual(identity["pid"], os.getpid())
        self.assertEqual(identity["python"], platform.python_version())
        self.assertEqual(identity["source_dir"], str(PACKAGE))
        self.assertIs(identity["workers_load_from_disk"], True)
        self.assertEqual(identity["id"], "src-" + identity["source_sha256"][:16])
        self.assertEqual(live.summary()["source_sha256"], identity["source_sha256"])
        self.assertEqual(live.provenance()["git_head"], (live.GIT_AT_LOAD or {}).get("head"))
        recomputed = lf_digest(PACKAGE)
        if not live.compare_disk()["matches_loaded"] or lf_digest(PACKAGE) != recomputed:
            self.skipTest("the shared src/kurtshape tree changed after this process loaded it")
        self.assertEqual((identity["source_sha256"], identity["source_files"]), recomputed)
        self.assertEqual(live.snapshot(PACKAGE)["sha256"], recomputed[0])
        git = live.wait_for_git(30)
        self.assertIn(git["state"], {"ready", "unavailable"})
        if git["state"] == "ready":
            loaded = set(live.SNAPSHOT["files"])
            self.assertEqual(git["head"], live.GIT_AT_LOAD["head"])
            for key in ("modified", "untracked", "deleted"):
                self.assertEqual(git[key], sorted(git[key]))
            self.assertLessEqual(set(git["modified"]) | set(git["untracked"]), loaded)
            self.assertFalse(set(git["deleted"]) & loaded)
            self.assertEqual(git["dirty"], bool(git["modified"] or git["untracked"] or git["deleted"]))


if __name__ == "__main__":
    unittest.main()
