"""Slice A/B U8 (A4): recovery snapshot speed without changing what a snapshot restores, the "Checkpoint…"
notice around the native write, and FreeCAD's autosaver off while KurtShape recovery is on (decision 3)."""
import ast
import json
from pathlib import Path
import sys
import unittest
import zipfile

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import FreeCAD as App
from kurtshape import settings as settings_module
from kurtshape.core import Controller
from kurtshape.recovery import DOCUMENT_PREFERENCES, FAST_SNAPSHOT_COMPRESSION, RecoveryStore
from native_validation_snapshot import snapshot_document, without_gui

SHAPE_PROPERTIES = ("Shape", "InternalShape", "AddSubShape", "SuppressedShape")


def restored_view(path, core):
    """The strict native snapshot of the archive at ``path``, opened fresh; without the GUI record, the
    document's own name/file name and the raw hashCode leaves (process addresses, different for any two
    open documents). Every BRep digest, placement, state, revision, intent hash and undo field stays."""
    doc = App.openDocument(str(path), True)
    try:
        view = without_gui(snapshot_document(doc, core))
    finally:
        App.closeDocument(doc.Name)
    view.pop("name")
    view.pop("filename")
    for row in view["objects"]:
        for facts in row["shapes"].values():
            facts.pop("hash_code", None)
    return view


def brep_members(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist() if name.endswith((".brp", ".bin"))}


class RecoveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="recovery-policy-")
        self.preferences = App.ParamGet(DOCUMENT_PREFERENCES)
        self.saved_preferences = {name: (name in self.preferences.GetInts() and self.preferences.GetInt(name))
                                  for name in ("CompressionLevel",)}
        self.saved_binary = "SaveBinaryBrep" in self.preferences.GetBools() and self.preferences.GetBool("SaveBinaryBrep")
        self.core = Controller()
        response = self.core.dispatch({"op": "new", "name": "Recovery policy plate"})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.call("sketch_rectangle", id="Base", width=60, height=40)
        self.call("pad", id="Plate", profile="Base", length=6)
        for index, (x, y) in enumerate(((12, 10), (30, 20), (48, 30))):
            self.call("sketch_circle", id=f"Hole{index}", x=x, y=y, diameter=5)
            self.call("pocket", id=f"Cut{index}", profile=f"Hole{index}", length=6)

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    def call(self, op, **args):
        response = self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                       "expected_revision": self.state["revision"], **args})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def assert_preferences_untouched(self):
        self.assertEqual({name: (name in self.preferences.GetInts() and self.preferences.GetInt(name))
                          for name in ("CompressionLevel",)}, self.saved_preferences)
        self.assertEqual("SaveBinaryBrep" in self.preferences.GetBools() and self.preferences.GetBool("SaveBinaryBrep"),
                         self.saved_binary)

    # --- snapshot speed lever ---------------------------------------------------------------------------

    def test_fast_checkpoint_restores_strictly_identically_to_freecads_default(self):
        store = self.core.recovery
        self.assertEqual(store.compression, FAST_SNAPSHOT_COMPRESSION, "fast snapshots are on by default")
        # Same file name in two folders: FreeCAD derives an opened document's label from it.
        fast, default = self.folder / "fast" / "snapshot.FCStd", self.folder / "default" / "snapshot.FCStd"
        for copy in (fast, default):
            copy.parent.mkdir()
        fast.write_bytes(store.read(self.core.checkpoint(self.doc, force=True))[0].read_bytes())
        self.assert_preferences_untouched()
        store.compression = None
        default.write_bytes(store.read(self.core.checkpoint(self.doc, force=True))[0].read_bytes())
        self.assert_preferences_untouched()
        self.assertGreater(fast.stat().st_size, default.stat().st_size, "level 1 really applied to the checkpoint")
        members = brep_members(default)
        self.assertTrue(members and all(name.endswith(".brp") for name in members), "checkpoints keep text BRep")
        self.assertEqual(brep_members(fast), members, "every BRep member is byte-identical")
        self.assertEqual(restored_view(fast, self.core), restored_view(default, self.core))

    def test_binary_brep_is_not_adopted_because_its_restore_differs(self):
        # The measured lever SaveBinaryBrep writes faster, but a restored BRep differs from FreeCAD's
        # default (TShape Checked flags; on a real project also location digits). If this ever restores
        # identically, it can be reconsidered (docs/OPERATION_CONTRACT.md, slice A/B U8).
        text, binary = self.folder / "text" / "snapshot.FCStd", self.folder / "binary" / "snapshot.FCStd"
        for copy in (text, binary):
            copy.parent.mkdir()
        self.doc.saveCopy(str(text))
        self.preferences.SetBool("SaveBinaryBrep", True)
        try:
            self.doc.saveCopy(str(binary))
        finally:
            if self.saved_binary is False:
                self.preferences.RemBool("SaveBinaryBrep")
            else:
                self.preferences.SetBool("SaveBinaryBrep", self.saved_binary)
        self.assertTrue(all(name.endswith(".bin") for name in brep_members(binary)))
        self.assertNotEqual(restored_view(binary, self.core), restored_view(text, self.core))
        manifest = self.core.checkpoint(self.doc, force=True)
        self.assertTrue(all(name.endswith(".brp") for name in brep_members(self.core.recovery.read(manifest)[0])))

    def test_fast_snapshot_setting(self):
        self.assertEqual(settings_module.load_preference(self.folder, "recovery_fast_snapshots"), True)
        session = self.folder / "slow-session"
        session.mkdir()
        (session / "settings.json").write_text(json.dumps({"recovery_fast_snapshots": False}), encoding="utf-8")
        self.assertIsNone(RecoveryStore(session).compression)
        (session / "settings.json").write_text(json.dumps({"recovery_fast_snapshots": "no"}), encoding="utf-8")
        self.assertEqual(RecoveryStore(session).compression, FAST_SNAPSHOT_COMPRESSION, "an invalid value is the default")
        self.assertIs(settings_module.preference(self.core.settings.data, "recovery_fast_snapshots"), True)

    # --- "Checkpoint…" notice ---------------------------------------------------------------------------

    def test_checkpoint_notice_brackets_the_native_write(self):
        store = self.core.recovery
        stage = store.directory / (self.state["document_id"] + ".saving.FCStd")
        seen = []
        store.stall_status = lambda text: seen.append((text, stage.exists()))
        self.core.checkpoint(self.doc, force=True)
        # Announced before the stage exists, cleared once the native write made it (then it is published).
        self.assertEqual(seen, [("Checkpoint…", False), (None, True)])
        self.assertFalse(stage.exists())
        seen.clear()
        store.last.clear()
        self.call("rename_feature", feature="Plate", name="Plate background")
        self.assertIsNone(self.core.checkpoint(self.doc, background=True))
        # Background publication (ZIP verification, hash, replace) runs off the GUI thread after the notice.
        self.assertEqual([text for text, _ in seen], ["Checkpoint…", None])
        self.assertTrue(seen[1][1], "the notice clears once the native write is done, before publication")
        store.close()
        self.assertEqual(store.read(store.directory / (self.state["document_id"] + ".json"))[1]["name"],
                         "Recovery policy plate")

    # --- FreeCAD autosaver (decision 3) ------------------------------------------------------------------

    def test_freecad_autosaver_is_off_while_recovery_is_on_unless_kept(self):
        self.assertEqual(settings_module.freecad_autosave(False), {"AutoSaveEnabled": False})
        self.assertEqual(settings_module.freecad_autosave(True), {"AutoSaveEnabled": True, "AutoSaveTimeout": 1})
        group = App.ParamGet("User parameter:BaseApp/Preferences/KurtShapeTests/RecoveryPolicy")
        self.addCleanup(lambda: App.ParamGet("User parameter:BaseApp/Preferences/KurtShapeTests").RemGroup("RecoveryPolicy"))
        group.SetBool("AutoSaveEnabled", True)
        group.SetInt("AutoSaveTimeout", 1)
        keep = settings_module.load_preference(self.folder, "keep_freecad_autosave")
        self.assertIs(keep, False, "the default turns FreeCAD's autosaver off")
        self.assertIs(settings_module.preference(self.core.settings.data, "keep_freecad_autosave"), False)
        settings_module.apply_freecad_autosave(group, keep)
        self.assertFalse(group.GetBool("AutoSaveEnabled", True))
        session = self.folder / "keeping-session"
        session.mkdir()
        (session / "settings.json").write_text(json.dumps({"keep_freecad_autosave": True}), encoding="utf-8")
        keep = settings_module.load_preference(session, "keep_freecad_autosave")
        settings_module.apply_freecad_autosave(group, keep)
        self.assertTrue(group.GetBool("AutoSaveEnabled", False))
        self.assertEqual(group.GetInt("AutoSaveTimeout", 0), 1)

    def test_app_start_applies_the_autosave_policy(self):
        # ui.start needs a GUI; pin its preference block statically: the policy is applied and FreeCAD's
        # autosaver is no longer switched on unconditionally.
        tree = ast.parse((ROOT / "src" / "kurtshape" / "ui.py").read_text(encoding="utf-8"))
        start = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "start")
        calls = [node for node in ast.walk(start) if isinstance(node, ast.Call)]
        names = [getattr(node.func, "id", getattr(node.func, "attr", None)) for node in calls]
        self.assertIn("apply_freecad_autosave", names)
        literals = [arg.value for node in calls for arg in node.args if isinstance(arg, ast.Constant)]
        self.assertNotIn("AutoSaveEnabled", literals)
        self.assertNotIn("AutoSaveTimeout", literals)


if __name__ == "__main__":
    unittest.main()
