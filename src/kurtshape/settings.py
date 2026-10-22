"""Local project locations and user preferences; no bridge-created grants."""
import json
import os
from pathlib import Path

# Slice A/B U8 (A4): preferences kept in the session's settings.json (docs/EVERYDAY_UI.md, "Recovery").
PREFERENCE_DEFAULTS = {
    # Recovery checkpoints write their FCStd archive with ZIP compression level 1 instead of FreeCAD's
    # configured level: faster on large projects, the archive 16-40 % larger, every restored BRep identical.
    "recovery_fast_snapshots": True,
    # Decision 3: FreeCAD's own one-minute autosaver stays off while KurtShape's recovery checkpoints run;
    # true keeps it on beside them.
    "keep_freecad_autosave": False,
}


def session_directory(root):
    """The session folder holding settings.json and project-recovery (KURTSHAPE_SESSION_DIR or <root>/runtime)."""
    return Path(os.environ.get("KURTSHAPE_SESSION_DIR", str(root / "runtime")))


def preference(data, name):
    """``data[name]`` when it has the default's type, else the default."""
    default = PREFERENCE_DEFAULTS[name]
    value = data.get(name) if isinstance(data, dict) else None
    return value if isinstance(value, type(default)) else default


def load_preference(directory, name):
    """One preference from ``<directory>/settings.json``; the default when the file or the value is missing."""
    try:
        data = json.loads((Path(directory) / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return preference(data, name)


def freecad_autosave(keep_freecad_autosave):
    """FreeCAD's ``Preferences/Document`` autosave values under decision 3.

    KurtShape's recovery checkpoints are always on, so FreeCAD's own autosaver (a second writer that
    stalls the app every minute) is off unless the user keeps it; kept, it runs at one minute as before.
    FreeCAD reads these values when it starts, so a change takes effect at the next start.
    """
    return {"AutoSaveEnabled": True, "AutoSaveTimeout": 1} if keep_freecad_autosave else {"AutoSaveEnabled": False}


def apply_freecad_autosave(preferences, keep_freecad_autosave):
    """Write :func:`freecad_autosave` into a FreeCAD parameter group; returns the values written."""
    values = freecad_autosave(keep_freecad_autosave)
    preferences.SetBool("AutoSaveEnabled", values["AutoSaveEnabled"])
    if "AutoSaveTimeout" in values:
        preferences.SetInt("AutoSaveTimeout", values["AutoSaveTimeout"])
    return values


class Settings:
    def __init__(self, root):
        self.root = root
        self.path = session_directory(root) / "settings.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}
        # New installations must not assume the author's CADkz/Codex layout.
        # Retain the implicit grants of existing profiles until users migrate them.
        layout = self.data.setdefault("workspace_layout", "legacy" if self.path.exists() else "portable")
        self.project_directory = root.parent.parent / "projects" if layout == "legacy" else root / "projects"
        self.roots = {self.project_directory.resolve()}
        if layout == "legacy":
            self.roots.add(root.parent.resolve())
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
