"""Slice A/B U8 (A8): a locked destination fails with a typed error that names the file, cleans its stage and
keeps the previous file; ``save`` refuses another project's FCStd without ``overwrite:true``; the "Saving…"
hook brackets the native write."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import shutil
import stat
import sys
import unittest
from unittest.mock import patch
import zipfile

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x1
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def share_deny_lock(path, share=0):
    """Hold ``path`` open with no sharing at all (or only ``share``), as an editor or a sync client may (Windows only)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.CreateFileW(str(path), GENERIC_READ, share, None, OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)


@unittest.skipUnless(os.name == "nt", "share-deny locks are a Windows behaviour")
class SaveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="save-safety-")
        self.core = Controller()
        self.state = self.new("Save safety plate")
        self.call("sketch_rectangle", id="Base", width=40, height=30)
        self.call("pad", id="Plate", profile="Base", length=5)

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    def new(self, name):
        response = self.core.dispatch({"op": "new", "name": name})
        self.assertTrue(response["ok"], response)
        return response["result"]

    def request(self, op, state=None, **args):
        state = state or self.state
        return self.core.dispatch({"op": op, "document_id": state["document_id"], "expected_revision": state["revision"], **args})

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def reject(self, code, op, **args):
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        return response["error"]

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def stage(self, path):
        return path.with_name(path.stem + ".saving.FCStd")

    # --- locked destination ---------------------------------------------------------------------------

    def test_locked_destination_is_named_the_stage_cleaned_and_a_retry_succeeds(self):
        path = self.folder / "locked.FCStd"
        self.call("save", path=str(path))
        before = digest(path)
        self.call("rename_feature", feature="Plate", name="Plate after lock")
        with share_deny_lock(path):
            for overwrite in (None, True):  # the project check reads the file first; overwrite skips it
                with self.subTest(overwrite=overwrite):
                    extra = {} if overwrite is None else {"overwrite": overwrite}
                    error = self.reject("save_destination_locked", "save", path=str(path), **extra)
                    self.assertEqual(error["path"], str(path))
                    self.assertIn(path.name, error["message"])
                    self.assertTrue(error["reason"], error)
                    self.assertFalse(self.stage(path).exists(), "the stage of a failed save is cleaned")
                    self.assertEqual(self.doc.FileName, str(path))
        self.assertEqual(digest(path), before, "the previous file is intact")
        # A share-read lock: the project check and the recovery copy read the file, the replace fails.
        with share_deny_lock(path, FILE_SHARE_READ), self.subTest(lock="share-read"):
            error = self.reject("save_destination_locked", "save", path=str(path))
            self.assertEqual(error["path"], str(path))
            self.assertNotEqual(error.get("file"), str(self.stage(path)), "the removed stage is never named")
            self.assertNotIn("file", error, "os.replace names the stage and the destination; neither is another file")
            self.assertFalse(self.stage(path).exists())
        self.assertEqual(digest(path), before, "the previous file is intact")
        self.assertFalse(self.stage(path).exists())
        saved = self.call("save", path=str(path))
        self.assertEqual((saved["modified"], saved["unsaved"], saved["native_file"]), (False, False, str(path)))
        self.assertNotEqual(digest(path), before)
        self.assertEqual(self.core._saved_project(path)[0], self.state["document_id"])

    def test_read_only_destination_is_named_and_kept(self):
        path = self.folder / "read-only.FCStd"
        self.call("save", path=str(path))
        before = digest(path)
        self.call("rename_feature", feature="Plate", name="Plate read only")
        os.chmod(path, stat.S_IREAD)
        self.addCleanup(lambda: path.exists() and os.chmod(path, stat.S_IREAD | stat.S_IWRITE))
        error = self.reject("save_destination_locked", "save", path=str(path))
        self.assertEqual(error["path"], str(path))
        self.assertIn(path.name, error["message"])
        self.assertFalse(self.stage(path).exists())
        self.assertEqual(digest(path), before)
        backup = path.with_suffix(".recovery.FCStd")
        self.assertTrue(os.access(backup, os.W_OK), "the recovery copy does not inherit the read-only attribute")
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.call("save", path=str(path))
        self.assertNotEqual(digest(path), before)
        self.assertEqual(digest(backup), before)

    # --- another project's file -----------------------------------------------------------------------

    def test_save_refuses_another_projects_file_without_overwrite(self):
        other = self.new("Other project")
        path = self.folder / "shared-name.FCStd"
        response = self.request("save", state=other, path=str(path))
        self.assertTrue(response["ok"], response)
        before = digest(path)
        error = self.reject("save_destination_other_project", "save", path=str(path))
        self.assertEqual(error["path"], str(path))
        self.assertEqual(error["existing_document_id"], other["document_id"])
        self.assertEqual(error["existing_project"], "Other project")
        self.assertIn(path.name, error["message"])
        self.assertIn("Other project", error["message"])
        self.assertIn("overwrite", error["message"])
        self.assertEqual(digest(path), before, "the refused destination is byte-identical")
        self.assertFalse(self.stage(path).exists())
        self.assertNotEqual(self.doc.FileName, str(path))
        self.reject("invalid_argument", "save", path=str(path), overwrite="yes")
        self.assertEqual(digest(path), before)
        saved = self.call("save", path=str(path), overwrite=True)
        self.assertEqual(saved["native_file"], str(path))
        self.assertEqual(self.core._saved_project(path), (self.state["document_id"], "Save safety plate"))
        self.assertEqual(digest(path.with_suffix(".recovery.FCStd")), before, "the replaced file keeps its recovery copy")

    def test_save_refuses_a_native_or_unreadable_file_without_overwrite(self):
        native = App.newDocument("SaveSafetyNative")
        native_path = self.folder / "native.FCStd"
        native.saveAs(str(native_path))
        App.closeDocument(native.Name)
        garbage = self.folder / "garbage.FCStd"
        garbage.write_bytes(b"not a zip archive")
        for path in (native_path, garbage):
            with self.subTest(path=path.name):
                before = digest(path)
                error = self.reject("save_destination_other_project", "save", path=str(path))
                self.assertIsNone(error["existing_document_id"])
                self.assertEqual(digest(path), before)
                self.call("save", path=str(path), overwrite=True)
                self.assertEqual(self.core._saved_project(path)[0], self.state["document_id"])

    def test_save_refuses_a_corrupt_deflate_fcstd_without_overwrite(self):
        path = self.folder / "corrupt.FCStd"
        text = "".join("<Object name=\"N%d\" value=\"%s\"/>\n" % (index, hashlib.sha256(str(index).encode()).hexdigest())
                       for index in range(3000))
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Document.xml", "<Document>" + text + "</Document>")
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("Document.xml")
        data = bytearray(path.read_bytes())
        start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra) + 200
        data[start:start + 64] = b"\xff" * 64
        path.write_bytes(bytes(data))
        import zlib
        with self.assertRaises(zlib.error), zipfile.ZipFile(path) as archive:
            archive.read("Document.xml")
        before = digest(path)
        error = self.reject("save_destination_other_project", "save", path=str(path))
        self.assertIsNone(error["existing_document_id"])
        self.assertEqual(digest(path), before)
        self.call("save", path=str(path), overwrite=True)
        self.assertEqual(self.core._saved_project(path)[0], self.state["document_id"])

    def test_a_stage_that_cannot_be_removed_is_reported(self):
        path = self.folder / "stage-report.FCStd"
        self.call("save", path=str(path))
        unlink = Path.unlink

        def refuse_stage(target, *args, **kwargs):
            if target.name.endswith(".saving.FCStd"):
                raise PermissionError(13, "Permission denied", str(target))
            return unlink(target, *args, **kwargs)
        self.call("rename_feature", feature="Plate", name="Plate stage")
        with patch.object(Path, "unlink", refuse_stage):
            saved = self.call("save", path=str(path))
            self.assertEqual(saved["save_stage"], {"stage": str(self.stage(path)), "stage_cleanup_error": "Permission denied"})
            with share_deny_lock(path):
                error = self.reject("save_destination_locked", "save", path=str(path), overwrite=True)
        self.assertEqual(error["stage"], str(self.stage(path)))
        self.assertEqual(error["stage_cleanup_error"], "Permission denied")
        self.stage(path).unlink(missing_ok=True)

    def test_own_file_copies_and_fresh_paths_need_no_flag(self):
        own = self.folder / "own.FCStd"
        self.call("save", path=str(own))
        self.call("rename_feature", feature="Plate", name="Plate again")
        self.call("save", path=str(own))
        copy = self.folder / "same-project-copy.FCStd"
        shutil.copy2(own, copy)
        self.call("rename_feature", feature="Plate", name="Plate copy")
        saved = self.call("save", path=str(copy))
        self.assertEqual(saved["native_file"], str(copy))
        fresh = self.folder / "fresh-name.FCStd"
        self.call("save", path=str(fresh), overwrite=False)
        self.assertTrue(fresh.is_file())

    def test_overwrite_is_a_save_argument_in_the_schema(self):
        self.assertIn("overwrite", self.core.ARGS["save"])
        self.reject("unknown_argument", "export", path=str(self.folder / "x.step"), overwrite=True)

    # --- "Saving…" hook -------------------------------------------------------------------------------

    def test_saving_notice_brackets_the_native_write(self):
        path = self.folder / "notice.FCStd"
        self.call("save", path=str(path))
        before = digest(path)
        self.call("rename_feature", feature="Plate", name="Plate notice")
        seen = []

        def notice(text):
            seen.append((text, self.stage(path).exists(), digest(path)))
        self.core.recovery.stall_status = notice
        self.call("save", path=str(path))
        after = digest(path)
        self.assertNotEqual(after, before)
        self.assertEqual(seen, [("Saving…", False, before), (None, False, after)],
                         "announced before the stage is written, cleared after the replace")
        seen.clear()
        self.core.recovery.stall_status = lambda text: seen.append((text,))
        with share_deny_lock(path):
            self.reject("save_destination_locked", "save", path=str(path), overwrite=True)
        self.assertEqual(seen, [("Saving…",), (None,)], "a failed save clears the notice too")
        self.assertEqual(digest(path), after)


if __name__ == "__main__":
    unittest.main()
