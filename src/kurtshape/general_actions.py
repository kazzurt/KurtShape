"""General shortcut actions over the same managed native FreeCAD documents.

Copy outside sketch edit is a shallow native sketch/Pad/Pocket feature copy:
dependencies remain references, parameters remain editable, and no Body or
frozen shape is fabricated. Native geometry clipboard stays within Sketcher.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from .core import ROOT, METADATA, metadata
from .bodies import owner


class GeneralActions:
    COPY_TYPES = {"Sketcher::SketchObject", "PartDesign::Pad", "PartDesign::Pocket"}

    def __init__(self, panel):
        import FreeCAD as App
        self.panel = panel
        self._feature_clipboard = None
        self._sketch_clipboard_digest = None
        self._recent = []
        self._closed = False
        if App.activeDocument():
            self._remember(App.activeDocument().Name)
        App.addDocumentObserver(self)
        if hasattr(panel, "destroyed"):
            panel.destroyed.connect(self.close)

    def callbacks(self):
        return {"general.copy": self.copy, "general.paste": self.paste,
                "general.feedback": self.feedback, "general.tabs": self.switch_recent,
                "general.tab_manager": self.tab_manager, "general.select_other": self.select_other}

    def close(self, *_):
        if not self._closed:
            import FreeCAD as App
            App.removeDocumentObserver(self)
            self._closed = True

    def _remember(self, name):
        self._recent = [name] + [key for key in self._recent if key != name]

    def slotActivateDocument(self, doc):
        self._remember(doc.Name)

    def slotDeletedDocument(self, doc):
        self._recent = [name for name in self._recent if name != doc.Name]

    def _notify(self, message):
        self.panel.notify(message)

    def _document(self):
        import FreeCAD as App
        doc = App.activeDocument()
        if doc is None or doc.getObject(METADATA) is None:
            raise ValueError("Create or open a KurtShape project first.")
        if metadata(doc).DocumentId not in self.panel.core.documents:
            raise ValueError("This document is not attached to the active modeling core.")
        if self.panel.core.busy:
            raise ValueError("Wait for the current modeling operation to finish.")
        return doc

    def _inspect(self, doc):
        result = self.panel.core.dispatch({"op": "inspect", "document_id": metadata(doc).DocumentId})
        if not result["ok"]:
            raise ValueError(result["error"]["message"])
        return result["result"]

    @staticmethod
    def _fingerprint(obj):
        return hashlib.sha256(bytes(obj.dumpContent())).hexdigest()

    @staticmethod
    def _clipboard_digest():
        from PySide import QtGui
        # Sketcher generates native geometry and constraints as clipboard text.
        text = QtGui.QApplication.clipboard().text()
        return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None

    def copy(self):
        import FreeCADGui as Gui
        try:
            doc = self._document()
            sketch = self.panel.active_sketch()
            if sketch:
                selected = Gui.Selection.getSelectionEx()
                if not any(item.Object == sketch and item.SubElementNames for item in selected):
                    raise ValueError("Select sketch geometry before copying.")
                if "Sketcher_CopyClipboard" not in Gui.listCommands():
                    raise ValueError("Native sketch copy is unavailable.")
                from PySide import QtCore, QtGui
                clipboard = QtGui.QApplication.clipboard()
                previous = QtCore.QMimeData()
                current = clipboard.mimeData()
                if current:
                    for mime_format in current.formats():
                        previous.setData(mime_format, current.data(mime_format))
                clipboard.clear()
                try:
                    Gui.runCommand("Sketcher_CopyClipboard")
                except Exception:
                    clipboard.setMimeData(previous)
                    raise
                digest = self._clipboard_digest()
                if digest is None:
                    clipboard.setMimeData(previous)
                    raise ValueError("Native Sketcher did not copy geometry.")
                self._feature_clipboard = None
                self._sketch_clipboard_digest = digest
                self._notify("Sketch geometry and related constraints copied.")
                return True
            selected = Gui.Selection.getSelection()
            if len(selected) != 1:
                name = self.panel.selected()
                obj = doc.getObject(name or "")
                selected = [obj] if obj else []
            if len(selected) != 1:
                raise ValueError("Select one native sketch, extrude, or remove feature to copy.")
            obj = selected[0]
            if obj.Document != doc or obj.TypeId not in self.COPY_TYPES or owner(doc, obj) is None:
                raise ValueError("Copy supports native sketches, extrudes, and remove features in this Body.")
            self._inspect(doc)
            self._feature_clipboard = {"document_id": metadata(doc).DocumentId, "document_name": doc.Name,
                                       "feature": obj.Name, "fingerprint": self._fingerprint(obj)}
            self._sketch_clipboard_digest = None
            self._notify(obj.Label + " copied; existing support and profile references are retained.")
            return True
        except Exception as exc:
            self._notify("Copy: " + str(exc))
            return True

    def paste(self):
        import FreeCADGui as Gui
        try:
            doc = self._document()
            sketch = self.panel.active_sketch()
            if sketch:
                if not self._sketch_clipboard_digest or self._clipboard_digest() != self._sketch_clipboard_digest:
                    raise ValueError("Copy compatible sketch geometry in KurtShape before pasting into a sketch.")
                if "Sketcher_Paste" not in Gui.listCommands():
                    raise ValueError("Native sketch paste is unavailable.")
                Gui.runCommand("Sketcher_Paste")
                self._notify("Choose where to place the pasted sketch geometry.")
                return True
            if not self._feature_clipboard:
                raise ValueError("Copy a native feature first; sketch geometry is pasted while editing a sketch.")
            clip = self._feature_clipboard
            if clip["document_id"] != metadata(doc).DocumentId or clip["document_name"] != doc.Name:
                raise ValueError("Feature paste retains dependencies in its source document. Switch to that document to paste.")
            source = doc.getObject(clip["feature"])
            if source is None or owner(doc, source) is None or self._fingerprint(source) != clip["fingerprint"]:
                raise ValueError("The copied source feature changed or was removed. Copy it again.")
            state = self._inspect(doc)
            if state["active_sketch_edit"] or doc.HasPendingTransaction or self.panel.task or self.panel.pending_sketch:
                raise ValueError("Finish or cancel the current tool before pasting a feature.")
            previous_tip = owner(doc, source).Tip
            result = self.panel.operation("duplicate_feature", feature=source.Name, fingerprint=clip["fingerprint"])
            if not result:
                return True
            created_name = result["created_feature"]
            created = doc.getObject(created_name)
            self.panel.select_feature(created_name)
            if hasattr(created, "ViewObject"):
                created.ViewObject.Visibility = True
            if created.TypeId.startswith("PartDesign::") and previous_tip and previous_tip != created:
                previous_tip.ViewObject.Visibility = False
            self._notify(created.Label + " pasted as an editable native feature; existing profile/support references are retained.")
            return True
        except Exception as exc:
            self._notify("Paste: " + str(exc))
            return True

    def _can_switch(self):
        import FreeCADGui as Gui
        live_lease = any(identifier in self.panel.core.sketch_edits and self.panel.core._is_open(doc)
                         for identifier, doc in self.panel.core.documents.items())
        gui_document = Gui.activeDocument()
        native_edit = gui_document.getInEdit() if gui_document else None
        native_task_check = getattr(self.panel, "native_feature_task_active", None)
        native_task = native_task_check() if callable(native_task_check) else bool(Gui.Control.activeDialog())
        if self.panel.active_sketch() or live_lease or self.panel.task or self.panel.pending_sketch or native_edit or native_task:
            self._notify("Finish or cancel the current tool before switching documents.")
            return False
        return True

    def _documents(self):
        import FreeCAD as App
        return [doc for doc in App.listDocuments().values()
                if doc.getObject(METADATA) and metadata(doc).DocumentId in self.panel.core.documents]

    def _activate(self, name):
        import FreeCAD as App
        if not self._can_switch():
            return False
        names = {doc.Name for doc in self._documents()}
        if name not in names:
            self._notify("That native document is no longer open.")
            return False
        App.setActiveDocument(name)
        self._remember(name)
        self.panel.tick()
        self._notify("Active part studio: " + App.activeDocument().Label)
        return True

    def switch_recent(self):
        import FreeCAD as App
        if not self._can_switch():
            return True
        docs = self._documents()
        active = App.activeDocument().Name if App.activeDocument() else None
        targets = [name for name in self._recent if name != active and any(doc.Name == name for doc in docs)]
        targets += [doc.Name for doc in docs if doc.Name != active and doc.Name not in targets]
        if targets:
            self._activate(targets[0])
            return True
        self._notify("Only one part studio is open.")
        return True

    def tab_manager(self):
        import FreeCAD as App
        from PySide import QtCore, QtGui
        if not self._can_switch():
            return True
        dialog = QtGui.QDialog(self.panel.main)
        dialog.setWindowTitle("Open part studios")
        dialog.resize(430, 310)
        layout = QtGui.QVBoxLayout(dialog)
        items = QtGui.QListWidget()
        for doc in self._documents():
            row = QtGui.QListWidgetItem(doc.Label + (" *" if not doc.FileName else ""))
            row.setData(QtCore.Qt.UserRole, doc.Name)
            items.addItem(row)
            if doc == App.activeDocument():
                items.setCurrentItem(row)
        layout.addWidget(items)
        buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        items.itemDoubleClicked.connect(lambda *_: dialog.accept())
        layout.addWidget(buttons)
        if dialog.exec() == QtGui.QDialog.Accepted and items.currentItem():
            self._activate(items.currentItem().data(QtCore.Qt.UserRole))
        return True

    def save_report(self, description):
        """Save a local report; no credentials, clipboard, or transport sessions."""
        import FreeCAD as App
        import FreeCADGui as Gui
        description = str(description).strip()
        if not description:
            raise ValueError("Describe the problem before saving a report.")
        doc = App.activeDocument()
        state = self._inspect(doc) if doc and doc.getObject(METADATA) and metadata(doc).DocumentId in self.panel.core.documents else None
        report = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                  "description": description, "freecad_version": App.Version(),
                  "document": {key: state[key] for key in ("document_id", "revision", "name", "build_status", "build_errors")} if state else None,
                  "feature_count": len(state["features"]) if state else 0,
                  "active_sketch": self.panel.active_sketch().Name if self.panel.active_sketch() else None,
                  "selection": [{"feature": item.ObjectName, "subelements": list(item.SubElementNames)} for item in Gui.Selection.getSelectionEx()],
                  "status_message": self.panel.message.text()}
        folder = ROOT / "validation" / "user-reports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("kurtshape-problem-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".json")
        path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        return path

    def feedback(self):
        from PySide import QtGui
        description, accepted = QtGui.QInputDialog.getMultiLineText(self.panel.main, "Report a problem",
            "Describe what happened and what you expected. The report is saved locally.")
        if accepted:
            try:
                path = self.save_report(description)
                self._notify("Problem report saved: " + str(path))
            except Exception as exc:
                self._notify("Problem report: " + str(exc))
        return True

    def zoom_to_selection(self):
        import FreeCADGui as Gui
        if Gui.Selection.getSelection() and "Std_ViewFitSelection" in Gui.listCommands():
            Gui.runCommand("Std_ViewFitSelection")
        else:
            self._notify("Select geometry to fit the view to it.")
        return True

    def hits_at_pointer(self, global_position=None):
        """Native ray hits at Qt pointer coordinates, including occluded faces."""
        import FreeCADGui as Gui
        from PySide import QtGui
        self._document()
        view = Gui.activeDocument().activeView()
        if not hasattr(view, "getObjectsInfo"):
            raise ValueError("The native view has no ray-hit selection API.")
        mdi = self.panel.main.findChild(QtGui.QMdiArea)
        surface = mdi.activeSubWindow() if mdi and mdi.activeSubWindow() else self.panel.main
        candidates = [widget for widget in surface.findChildren(QtGui.QWidget)
                      if widget.isVisible() and widget.metaObject().className() == "QOpenGLWidget"
                      and widget.parentWidget() and widget.parentWidget().metaObject().className() == "Gui::View3DInventorViewer"]
        if len(candidates) != 1:
            raise ValueError("Move the pointer over the active native modeling viewport.")
        widget = candidates[0]
        point = widget.mapFromGlobal(global_position if global_position is not None else QtGui.QCursor.pos())
        if not widget.rect().contains(point):
            raise ValueError("Move the pointer over model geometry before selecting another entity.")
        ratio = widget.devicePixelRatioF()
        width, height = view.getSize()
        pixel = (int(round(point.x() * ratio)), int(height) - 1 - int(round(point.y() * ratio)))
        if not 0 <= pixel[0] < width or not 0 <= pixel[1] < height:
            raise ValueError("The pointer is outside the native viewport.")
        hits = view.getObjectsInfo(pixel) or []
        result, seen = [], set()
        doc = self._document()
        for hit in hits:
            document_name, object_name, component = hit.get("Document"), hit.get("Object"), hit.get("Component", "")
            key = (document_name, object_name, component)
            if key not in seen and document_name == doc.Name and doc.getObject(object_name or ""):
                result.append(dict(hit))
                seen.add(key)
        return result

    def select_other(self, global_position=None):
        """Open the ordered native hit list; selection is the only change."""
        import FreeCAD as App
        import FreeCADGui as Gui
        from PySide import QtCore, QtGui
        try:
            doc = self._document()
            state = self._inspect(doc)
            sketch = self.panel.active_sketch()
            edit_name = sketch.Name if sketch else None
            position = global_position if global_position is not None else QtGui.QCursor.pos()
            hits = self.hits_at_pointer(position)
            if not hits:
                self._notify("No selectable native geometry under the pointer.")
                return True
            menu = QtGui.QMenu(self.panel.main)
            if self.panel.main.testAttribute(QtCore.Qt.WA_DontShowOnScreen):
                menu.setAttribute(QtCore.Qt.WA_DontShowOnScreen)
            actions = {}
            for index, hit in enumerate(hits, 1):
                obj = doc.getObject(hit["Object"])
                label = f"{index}. {obj.Label} · {hit.get('Component') or obj.TypeId}"
                action = menu.addAction(label)
                action.setData(hit)
                actions[action] = hit
            def hover(action):
                hit = actions.get(action)
                if hit and App.activeDocument() and App.activeDocument().Name == doc.Name:
                    obj = doc.getObject(hit["Object"])
                    if obj:
                        Gui.Selection.setPreselection(obj, hit.get("Component", ""),
                            float(hit.get("x", 0)), float(hit.get("y", 0)), float(hit.get("z", 0)))
            menu.hovered.connect(hover)
            try:
                chosen = menu.exec(position)
            finally:
                Gui.Selection.clearPreselection()
                menu.deleteLater()
            if chosen not in actions:
                return True
            current = App.activeDocument()
            current_sketch = self.panel.active_sketch()
            if current is None or current.Name != doc.Name or (current_sketch.Name if current_sketch else None) != edit_name:
                self._notify("The document or editing tool changed. Open Select other again.")
                return True
            if self._inspect(doc)["revision"] != state["revision"]:
                self._notify("Geometry changed while choosing an entity. Open Select other again.")
                return True
            hit = actions[chosen]
            obj = doc.getObject(hit["Object"])
            if obj is None:
                self._notify("That native object is no longer available.")
                return True
            Gui.Selection.addSelection(hit["Document"], hit["Object"], hit.get("Component", ""))
            component = hit.get("Component", "")
            selected = any(item.DocumentName == hit["Document"] and item.ObjectName == hit["Object"]
                           and (not component or component in item.SubElementNames)
                           for item in Gui.Selection.getSelectionEx())
            if not selected:
                self._notify("The current native editing tool does not permit selecting that entity.")
                return True
            self._notify("Selected " + obj.Label + " · " + hit.get("Component", "object"))
            return True
        except Exception as exc:
            self._notify("Select other: " + str(exc))
            return True
