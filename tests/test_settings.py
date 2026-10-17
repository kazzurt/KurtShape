"""New checkout defaults and existing-user grant compatibility."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kurtshape.settings import Settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "arbitrary checkout"
        self.session = self.root / "runtime"
        self.session.mkdir(parents=True)
        override = patch.dict(os.environ, {"KURTSHAPE_SESSION_DIR": str(self.session)})
        override.start()
        self.addCleanup(override.stop)

    def test_first_run_grants_only_local_projects_and_stays_portable_after_save(self):
        settings = Settings(self.root)
        self.assertEqual(settings.project_directory, self.root / "projects")
        self.assertEqual(settings.roots, {(self.root / "projects").resolve()})
        settings.persist()
        self.assertEqual(Settings(self.root).roots, settings.roots)

    def test_legacy_profile_retains_implicit_and_explicit_grants(self):
        extra = self.root / "chosen-folder"
        (self.session / "settings.json").write_text(json.dumps({"project_roots": [str(extra)]}), encoding="utf-8")
        settings = Settings(self.root)
        self.assertEqual(settings.project_directory, self.root.parent.parent / "projects")
        self.assertEqual(settings.roots, {self.root.parent.resolve(), settings.project_directory.resolve(), extra.resolve()})
        settings.persist()
        self.assertEqual(Settings(self.root).roots, settings.roots)

    def test_portable_user_chosen_destination_survives_reload(self):
        settings = Settings(self.root)
        target = self.root.parent / "chosen" / "part.FCStd"
        settings.grant_destination(target)
        reloaded = Settings(self.root)
        self.assertIn(target.parent.resolve(), reloaded.roots)
        self.assertNotIn(self.root.parent.resolve(), reloaded.roots)
        self.assertEqual(reloaded.last_directory, str(target.parent))
