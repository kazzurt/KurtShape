"""Folders in the assembly instance lists and their context menu (assembly UX item 3).

Rows: ``instance_rows`` nests the instance rows of both lists (the features
tree's Instances group and the Instances list) under folder rows built from
``inspect.assembly.folders``; a folder row's key is ``assembly_folder:<path>``
and its text carries the count of instances inside it, subfolders included.

Menus are built, not executed, by ``instance_menu`` so ``ui.py`` shows them and
recipes can trigger their actions. Folder names are typed in an inline editor
over the row (a child of the tree, not a dialog). Every change goes through the
typed operations ``set_assembly_folders`` / ``move_assembly_instances``; the
trees are rebuilt from the result, never edited directly.
"""
from __future__ import annotations

from PySide import QtCore, QtGui

from . import assembly_folders

FOLDER_PREFIX = "assembly_folder:"
PATH_ROLE = QtCore.Qt.UserRole + 5


def folder_key(path):
    return FOLDER_PREFIX + path


def folder_path(key):
    return key[len(FOLDER_PREFIX):] if isinstance(key, str) and key.startswith(FOLDER_PREFIX) else None


def structure(assembly):
    """The folder data of an inspected assembly: {folders, membership}."""
    membership = {entry["id"]: entry["folder"] for entry in assembly.get("instances", []) if entry.get("folder")}
    return {"folders": assembly.get("folders", []) or [], "membership": membership}


def instance_rows(assembly, row_for, folder_icon=None):
    """Folder rows (with counts) and instance rows, nested by folder path, folders first."""
    data = structure(assembly)
    entries = assembly.get("instances", [])
    counts = assembly_folders.counts(data, [entry["id"] for entry in entries])
    by_folder = {}
    for entry in entries:
        by_folder.setdefault(data["membership"].get(entry["id"]), []).append(row_for(entry))

    def build(nodes, prefix):
        rows = []
        for node in nodes:
            path = prefix + node["name"]
            row = {"key": folder_key(path), "text": f"{node['name']} ({counts.get(path, 0)})",
                   "data": {QtCore.Qt.UserRole: folder_key(path), PATH_ROLE: path},
                   "tooltip": "Folder " + path + " · " + str(counts.get(path, 0)) + " instances",
                   "children": build(node["children"], path + "/") + by_folder.get(path, [])}
            if folder_icon is not None:
                row["icon"] = folder_icon
            rows.append(row)
        return rows
    return build(data["folders"], "") + by_folder.get(None, [])


def unique_name(nodes, base="New folder"):
    names = {node["name"] for node in nodes}
    if base not in names:
        return base
    index = 2
    while f"{base} {index}" in names:
        index += 1
    return f"{base} {index}"


def children_at(folders, path):
    level = folders
    for name in assembly_folders.split(path):
        level = next(node for node in level if node["name"] == name)["children"]
    return level


class InlineName(QtGui.QLineEdit):
    """A row-sized name editor inside the tree viewport: Enter or focus loss commits, Esc cancels."""

    def __init__(self, tree, item, text, commit):
        super().__init__(tree.viewport())
        self.setObjectName("KurtShapeFolderNameEditor")
        self.commit, self.done = commit, False
        self.setText(text)
        self.selectAll()
        rect = tree.visualItemRect(item)
        self.setGeometry(rect.adjusted(18, 0, 0, 0) if rect.isValid() else QtCore.QRect(0, 0, 200, 22))
        self.editingFinished.connect(self.finish)
        self.show()
        self.setFocus()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.done = True
            self.deleteLater()
            return
        super().keyPressEvent(event)

    def finish(self):
        if self.done:
            return
        self.done = True
        text = self.text().strip()
        self.deleteLater()
        if text:
            QtCore.QTimer.singleShot(0, lambda: self.commit(text))


class AssemblyTree:
    """Folder commands for the panel's two instance lists."""

    def __init__(self, panel):
        self.panel = panel
        self.editor = None
        self.icon = None

    def folder_icon(self):
        if self.icon is None:
            from .presentation_icons import icon_for
            self.icon = icon_for("Folder")
        return self.icon

    def assembly(self):
        return self.panel.assembly_state() or {}

    def data(self):
        return structure(self.assembly())

    def instance_ids(self):
        return [entry["id"] for entry in self.assembly().get("instances", [])]

    def selected_instances(self, tree, item):
        ids = set(self.instance_ids())
        chosen = [row.data(0, QtCore.Qt.UserRole) for row in tree.selectedItems()]
        chosen = [key for key in chosen if key in ids]
        key = item.data(0, QtCore.Qt.UserRole) if item is not None else None
        if key in ids and key not in chosen:
            chosen = [key]
        return chosen

    # Operations -------------------------------------------------------
    def set_folders(self, data):
        membership = {key: value for key, value in data["membership"].items() if value}
        return self.panel.operation("set_assembly_folders", folders=data["folders"], membership=membership)

    def move(self, instances, folder):
        if instances:
            return self.panel.operation("move_assembly_instances", instances=list(instances), folder=folder)
        return None

    def new_folder(self, tree, parent=None, instances=()):
        """Create "New folder" under ``parent`` (moving ``instances`` into it), then edit its name."""
        data = self.data()
        try:
            name = unique_name(children_at(data["folders"], parent))
        except StopIteration:
            return None
        path = (parent + "/" if parent else "") + name
        if instances:
            state = self.move(instances, path)
        else:
            state = self.set_folders(assembly_folders.moved(data, [], path))
        if state:
            self.rename_later(tree, path)
        return state

    def rename(self, path, name):
        try:
            data = assembly_folders.renamed(self.data(), path, name)
        except (assembly_folders.FolderError, StopIteration) as exc:
            self.panel.notify(str(exc) or "Choose another folder name", "error")
            return None
        return self.set_folders(data)

    def remove(self, path):
        try:
            data = assembly_folders.removed(self.data(), path)
        except (assembly_folders.FolderError, StopIteration) as exc:
            self.panel.notify(str(exc), "error")
            return None
        return self.set_folders(data)

    def rename_later(self, tree, path):
        QtCore.QTimer.singleShot(0, lambda: self.edit_name(tree, path))

    def edit_name(self, tree, path):
        items = self.panel.items if tree is self.panel.features else self.panel.part_model.items
        item = items.get(folder_key(path))
        if item is None:
            return None
        ancestor = item.parent()
        while ancestor is not None:
            ancestor.setExpanded(True)
            ancestor = ancestor.parent()
        tree.scrollToItem(item)
        if self.editor is not None:
            try:
                self.editor.finish()
            except RuntimeError:
                pass
        name = path.rpartition("/")[2]
        self.editor = InlineName(tree, item, name, lambda text: text != name and self.rename(path, text))
        return self.editor

    # Open part (item 4) -------------------------------------------------
    def source(self, instance):
        from . import assembly
        doc = self.panel.document()
        try:
            return assembly.instance_source(doc, {"instance": instance}) if doc is not None else None
        except Exception as exc:  # AssemblyError: not an occurrence of this assembly
            self.panel.notify(str(exc), "error")
            return None

    def open_part(self, instance):
        """Open the occurrence's saved source in its own tab, or activate the tab that has it.

        An FCStd source opens as a project (``open``); a STEP source imports into a new part
        studio (``import_step``). A missing file is reported in the status line and Messages.
        """
        info = self.source(instance)
        if info is None:
            return None
        if not info["path"]:
            self.panel.notify(info["name"] + " has no recorded source file", "error")
            return None
        if not info["exists"]:
            self.panel.notify("Source file not found: " + info["path"], "error",
                              detail=info["name"] + ": the source file recorded in the assembly is missing: " + info["path"])
            return None
        import FreeCADGui as Gui
        # A live selection in the assembly makes the native GUI re-activate the assembly tab
        # after another document opens (measured 2026-10-24); the new tab must stay in front.
        Gui.Selection.clearSelection()
        if info["kind"] == "fcstd" and info["open_documents"]:
            name = info["open_documents"][0]
            if self.activate(name):
                self.panel.notify("Opened " + info["name"] + " · already open in its tab")
            return name
        state = self.panel.open_path(info["path"])
        if state:
            # Make the new tab current even when the window system delays MDI activation.
            opened = self.panel.core.documents.get(state.get("document_id"))
            if opened is not None:
                self.activate(opened.Name)
            self.panel.notify(("Imported " if info["kind"] == "step" else "Opened ") + info["name"] + " from " + info["path"])
        return state

    def activate(self, name):
        """Bring the document's tab to the front (its MDI subwindow), then make it active."""
        import FreeCAD as App
        doc = App.listDocuments().get(name)
        if doc is None:
            return False
        from pathlib import Path
        names = {doc.Label, doc.Name, Path(doc.FileName).stem if doc.FileName else doc.Name}
        mdi = self.panel.main.findChild(QtGui.QMdiArea)
        if mdi is not None:
            for window in mdi.subWindowList():
                title = window.windowTitle().replace("[*]", "")
                if (title.rpartition(" : ")[0] or title) in names:
                    mdi.setActiveSubWindow(window)
                    break
        return self.panel.general_actions._activate(name)

    def show_source(self, instance):
        info = self.source(instance)
        if info is not None:
            self.panel.notify((info["kind"] or "Source").upper() + " source: " + (info["path"] or "not recorded")
                              + ("" if info["exists"] else " (missing)"))
        return info

    def double_click(self, item):
        key = item.data(0, QtCore.Qt.UserRole) if item is not None else None
        if key in set(self.instance_ids()):
            self.open_part(key)
            return True
        return folder_path(key) is not None

    # Menu ---------------------------------------------------------------
    def menu(self, tree, item):
        """The assembly context menu for a row of either list (built, not shown)."""
        import FreeCADGui as Gui
        p = self.panel
        key = item.data(0, QtCore.Qt.UserRole) if item is not None else None
        doc = p.document()
        obj = doc.getObject(key) if doc is not None and isinstance(key, str) and folder_path(key) is None else None
        menu = QtGui.QMenu(p)
        menu.setObjectName("KurtShapeAssemblyInstanceMenu")
        if obj is not None:
            if not item.isSelected():
                tree.setCurrentItem(item)
            if len(self.selected_instances(tree, item)) <= 1:
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(obj)
            if key in set(self.instance_ids()):
                menu.addAction("Open part", lambda: self.open_part(key))
                info = self.source(key)
                if info is not None and info["kind"] == "step":
                    menu.addAction("Show source file", lambda: self.show_source(key))
                menu.addSeparator()
            visible = bool(obj.ViewObject and obj.ViewObject.Visibility)
            menu.addAction("Hide" if visible else "Show", lambda: p.set_visibility(obj, not visible))
            if key in set(self.instance_ids()):
                menu.addAction("Ground as reference", p.ground_assembly_instance)
                menu.addAction("Move free instance", p.move_assembly_selection)
            else:
                menu.addAction("Edit joint", p.edit_assembly_selection)
                menu.addAction("Move allowed coordinate", p.move_assembly_selection)
            menu.addAction("Rename", p.rename_selected)
            menu.addAction("Remove", p.delete_selected)
            menu.addSeparator()
        self.folder_entries(menu, tree, item)
        return menu if menu.actions() else None

    def move_menu(self, menu, tree, instances):
        submenu = menu.addMenu("Move to folder")
        submenu.setObjectName("KurtShapeMoveToFolder")
        for path in assembly_folders.paths(self.data()["folders"]):
            depth = path.count("/")
            submenu.addAction("    " * depth + path.rpartition("/")[2],
                              lambda path=path: self.move(instances, path)).setData(path)
        if submenu.actions():
            submenu.addSeparator()
        submenu.addAction("New folder…", lambda: self.new_folder(tree, None, instances)).setData("__new__")
        submenu.addAction("Root (no folder)", lambda: self.move(instances, None)).setData("__root__")
        return submenu

    def folder_entries(self, menu, tree, item):
        """Folder entries for an instance, folder or group row; returns True when any were added."""
        key = item.data(0, QtCore.Qt.UserRole) if item is not None else None
        path = folder_path(key)
        if path is not None:
            menu.addAction("New folder", lambda: self.new_folder(tree, path))
            menu.addAction("Rename folder", lambda: self.edit_name(tree, path))
            menu.addAction("Remove folder", lambda: self.remove(path))
            return True
        instances = self.selected_instances(tree, item)
        if instances:
            menu.addAction("New folder", lambda: self.new_folder(tree, None, instances))
            self.move_menu(menu, tree, instances)
            return True
        if key in (None, "assembly_group:instances"):
            menu.addAction("New folder", lambda: self.new_folder(tree, None))
            return True
        return False


def action(menu, text):
    """Find a menu action by its text, searching submenus (for recipes)."""
    for owner in [menu] + menu.findChildren(QtGui.QMenu):
        for entry in owner.actions():
            if entry.text().strip() == text:
                return entry
    return None
