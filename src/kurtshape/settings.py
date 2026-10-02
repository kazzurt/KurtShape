"""Local project locations and user preferences; no bridge-created grants."""
import json
import os
from pathlib import Path


class Settings:
    def __init__(self, root):
        self.root = root
        self.path = Path(os.environ.get("KURTSHAPE_SESSION_DIR", str(root / "runtime"))) / "settings.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}
        self.project_directory = root.parent.parent / "projects"
        self.roots = {root.parent.resolve(), self.project_directory.resolve()}
        configured = self.data.get("project_roots", [])
        if isinstance(configured, list):
            self.roots.update(Path(p).resolve() for p in configured if isinstance(p, str) and Path(p).is_absolute())

    @property
    def last_directory(self):
        return self.data.get("last_directory", str(self.project_directory))

    def persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stage = self.path.with_suffix(".saving")
        stage.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(stage, self.path)

    def grant_destination(self, raw):
        path = Path(raw).resolve()
        self.roots.add(path.parent)
        self.data["project_roots"] = sorted(str(p) for p in self.roots)
        self.remember(path)

    def remember(self, raw):
        path = str(Path(raw).resolve())
        self.data["last_directory"] = str(Path(path).parent)
        self.data["recent_projects"] = [path] + [p for p in self.data.get("recent_projects", []) if p != path][:11]
        self.persist()
