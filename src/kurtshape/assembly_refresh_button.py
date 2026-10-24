"""The assembly studio's Refresh button (assembly UX item 7).

First click: check every occurrence's saved source (``assembly_sync``: SHA-256,
hashed only when the file's mtime/size moved) and mark the outdated rows; no
dialog, the status line says what was found. Second click, or **Update changed
parts**: refresh every outdated occurrence through the typed
``refresh_assembly_part`` with ``shared:"all"`` (every occurrence of a source
updates together). A refresh rejected because a joint's referenced geometry
changed is reported per instance in Messages with the joint's name; the others
still update. Activating an assembly tab runs only the mtime/size pre-check.
"""
from __future__ import annotations

from pathlib import Path

from PySide import QtCore

from . import assembly_sync

AMBER = "#b7791f"


def open_unsaved(path):
    """The label of an open document of ``path`` with unsaved changes, else None."""
    import FreeCAD as App
    if not getattr(App, "GuiUp", False):
        return None
    import FreeCADGui as Gui
    try:
        target = Path(path).resolve()
    except (OSError, ValueError):
        return None
    for name, doc in App.listDocuments().items():
        try:
            if doc.FileName and Path(doc.FileName).resolve() == target:
                gui = Gui.getDocument(name)
                if gui is not None and gui.Modified:
                    return doc.Label
        except Exception:  # a document closing under us
            continue
    return None


class AssemblyRefresh:
    def __init__(self, panel):
        self.panel = panel
        self.pending = None  # (document name, revision, stale ids) after a check that found changes
        self.checked = None  # (document name, revision) of the last full check
        self.last_report = None

    # Row decoration -------------------------------------------------------
    def decoration(self, entry):
        """(suffix, color) for an instance row from its inspected source status."""
        source = entry.get("source") or {}
        unsaved = open_unsaved(source.get("path")) if source.get("path") else None
        if unsaved:
            return " · unsaved in " + unsaved, AMBER
        if source.get("status") == "changed":
            return " · outdated", AMBER
        if source.get("status") == "missing":
            return " · source missing", AMBER
        return "", None

    # Checks ----------------------------------------------------------------
    def _instances(self):
        return (self.panel.assembly_state() or {}).get("instances", [])

    def check(self):
        """Hash every source whose file moved; returns (stale ids, unsaved ids, missing ids)."""
        stale, unsaved, missing = [], [], []
        for entry in self._instances():
            source = entry.get("source") or {}
            path = source.get("path")
            if not path:
                continue
            if open_unsaved(path):
                unsaved.append(entry["id"])
                continue
            state = assembly_sync.source_state(path, source.get("sha256"), hash=True)
            if state["status"] == "changed":
                stale.append(entry["id"])
            elif state["status"] == "missing":
                missing.append(entry["id"])
        return stale, unsaved, missing

    def precheck(self):
        """Activation/idle check: only stat the files, never hash or solve."""
        moved = sorted({(entry.get("source") or {}).get("path") for entry in self._instances()
                        if (entry.get("source") or {}).get("path")
                        and assembly_sync.moved_since_check(entry["source"]["path"])})
        return moved

    def _signature(self):
        doc = self.panel.document()
        return (doc.Name, self.panel.state.get("revision")) if doc is not None and self.panel.state else None

    def reinspect(self):
        """Inspect again so the rows read the freshly cached hashes, then rebuild them."""
        doc = self.panel.document()
        if doc is not None:
            self.panel.state = self.panel.core.inspect(doc, measure=self.panel.MEASURE)
            self.panel.refresh_assembly()

    def click(self):
        """Toolbar Refresh: check, or update when the previous check found outdated parts."""
        if not self.panel.assembly_ready():
            return None
        if self.pending and self.pending[:2] == self._signature():
            return self.update()
        return self.run_check()

    def run_check(self):
        stale, unsaved, missing = self.check()
        self.reinspect()
        signature = self._signature()
        self.checked = signature
        self.pending = signature + (tuple(stale),) if stale and signature else None
        parts = []
        if stale:
            parts.append(f"{len(stale)} part{'s' if len(stale) != 1 else ''} changed on disk · Refresh again to update")
        if unsaved:
            parts.append(f"{len(unsaved)} unsaved in another tab")
        if missing:
            parts.append(f"{len(missing)} source{'s' if len(missing) != 1 else ''} missing")
        self.panel.notify(" · ".join(parts) if parts else "All parts current")
        return {"stale": stale, "unsaved": unsaved, "missing": missing}

    def update(self):
        """Refresh every outdated occurrence (shared:"all"); report rejections per instance."""
        stale, _, _ = self.check()
        done, failed, seen = [], [], set()
        for identity in stale:
            if identity in seen:
                continue
            entry = next((value for value in self._instances() if value["id"] == identity), None)
            if entry is None:
                continue
            users = [value["id"] for value in self._instances() if value.get("embedded_source") == entry.get("embedded_source")]
            seen.update(users)
            args = {"instance": identity}
            if len(users) > 1:
                args["shared"] = "all"
            state = self.panel.operation("refresh_assembly_part", **args)
            if state:
                done.extend(users)
                continue
            error = self.panel.last_operation_error or {}
            joint = error.get("joint")
            for user in users:
                failed.append(user)
                detail = (user + ": not refreshed · " + str(error.get("message", "refresh rejected"))
                          + (" · joint " + joint if joint else "") + " (" + str(error.get("code", "")) + ")")
                self.panel.append_message(detail, severity="error")
        self.pending = None
        self.reinspect()
        self.last_report = {"updated": done, "failed": failed}
        if failed:
            self.panel.notify(f"Updated {len(done)} · {len(failed)} could not update · see Messages",
                              "error", detail=f"{len(failed)} occurrences kept their previous geometry: " + ", ".join(failed))
        else:
            self.panel.notify(f"Updated {len(done)} part{'s' if len(done) != 1 else ''}" if done else "All parts current")
        return self.last_report

    def on_refresh(self):
        """Called after the assembly rows are rebuilt: pre-check once per tab activation."""
        doc = self.panel.document()
        name = doc.Name if doc is not None else None
        if name != getattr(self, "_active", None):
            self._active = name
            if name is not None:
                return self.activated()
        return None

    def activated(self):
        """An assembly tab became active: the cheap pre-check only."""
        moved = self.precheck()
        if moved:
            self.panel.notify(f"{len(moved)} source file{'s' if len(moved) != 1 else ''} may have changed · Refresh to check")
        return moved

    def source_saved(self, path):
        """A part was saved in another tab: say which open assemblies use it (no hash, no solve)."""
        import FreeCAD as App
        from . import assembly
        users = []
        for doc in App.listDocuments().values():
            try:
                if any(getattr(obj.LinkedObject, "SourcePath", "") and
                       Path(obj.LinkedObject.SourcePath).resolve() == Path(path).resolve()
                       for obj in assembly.result_objects(doc)):
                    users.append(doc.Label)
            except Exception:
                continue
        return users
