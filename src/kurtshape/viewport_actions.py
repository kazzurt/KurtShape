"""View actions backed by FreeCAD camera, tessellation and clipping APIs."""
from __future__ import annotations

import json
import math
import re
import FreeCAD as App

VISUAL_EXTENSION = 'SketcherGui::ViewProviderSketchGeometryExtension'
NAMED_VIEWS_PROPERTY = 'NamedViews'
MAX_NAMED_VIEWS = 256


def _validate_camera(camera, projection):
    """Accept one native camera block; reject scene nodes and nonfinite fields."""
    if projection not in ('Orthographic', 'Perspective') or not isinstance(camera, str):
        raise ValueError('Unsupported named camera projection or value.')
    if len(camera) > 16384:
        raise ValueError('Named camera data is too large.')
    match = re.fullmatch(r'#Inventor V2\.1 ascii\s+(Orthographic|Perspective)Camera\s*\{([^{}]*)\}\s*',
                         camera.strip(), re.DOTALL)
    if match is None or match.group(1) != projection:
        raise ValueError('Named camera must contain one matching native camera block.')
    fields = {}
    counts = {'position': 3, 'orientation': 4, 'nearDistance': 1, 'farDistance': 1,
              'aspectRatio': 1, 'focalDistance': 1,
              'height' if projection == 'Orthographic' else 'heightAngle': 1}
    for line in match.group(2).splitlines():
        parts = line.split()
        if not parts:
            continue
        key = parts[0]
        if key in fields:
            raise ValueError('Duplicate native camera field.')
        if key == 'viewportMapping':
            if len(parts) != 2 or parts[1] not in ('ADJUST_CAMERA', 'LEAVE_ALONE',
                    'CROP_VIEWPORT_FILL_FRAME', 'CROP_VIEWPORT_LINE_FRAME', 'CROP_VIEWPORT_NO_FRAME'):
                raise ValueError('Invalid native viewport mapping.')
            fields[key] = parts[1]
        elif key in counts and len(parts)-1 == counts[key]:
            values = [float(value) for value in parts[1:]]
            if not all(math.isfinite(value) and abs(value) < 1e30 for value in values):
                raise ValueError('Named camera has an invalid numeric field.')
            fields[key] = values
        else:
            raise ValueError('Unknown or malformed native camera field.')
    if set(fields) != set(counts) | {'viewportMapping'}:
        raise ValueError('Native camera fields are incomplete.')
    if fields['farDistance'][0] <= fields['nearDistance'][0] or fields['focalDistance'][0] <= 0:
        raise ValueError('Named camera has invalid clipping or focal distance.')
    if fields['aspectRatio'][0] <= 0:
        raise ValueError('Named camera has invalid aspect ratio.')
    size = fields['height' if projection == 'Orthographic' else 'heightAngle'][0]
    if size <= 0 or (projection == 'Perspective' and (size >= math.pi or fields['nearDistance'][0] <= 0)):
        raise ValueError('Named camera has invalid view size.')
    if fields['orientation'][3] != 0 and sum(value*value for value in fields['orientation'][:3]) == 0:
        raise ValueError('Named camera has invalid rotation axis.')
    return {'camera': camera, 'projection': projection}


def _validate_views(payload):
    if (not isinstance(payload, dict) or set(payload) != {'schema', 'views'} or
            type(payload['schema']) is not int or payload['schema'] != 1 or
            not isinstance(payload['views'], dict) or len(payload['views']) > MAX_NAMED_VIEWS):
        raise ValueError('Unsupported named view metadata schema.')
    result = {}
    for name, saved in payload['views'].items():
        if (not isinstance(name, str) or not name or name != name.strip() or len(name) > 160 or
                any(ord(character) < 32 for character in name) or
                not isinstance(saved, dict) or set(saved) != {'camera', 'projection'}):
            raise ValueError('Invalid named view entry.')
        result[name] = _validate_camera(saved['camera'], saved['projection'])
    return result


def _unique_json_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('Duplicate named view metadata key.')
        result[name] = value
    return result


class ViewportActions:
    def __init__(self, parent=None):
        self.parent = parent
        self._documents = {}
        self._dialogs = {}

    def _notify(self, message):
        if self.parent is not None and hasattr(self.parent, 'notify'):
            self.parent.notify(message)
        else:
            import FreeCADGui as Gui
            Gui.getMainWindow().statusBar().showMessage(message, 8000)

    def _context(self):
        import FreeCADGui as Gui
        gui_doc = Gui.activeDocument()
        doc = App.ActiveDocument
        if doc is None or gui_doc is None:
            self._notify('Open a document to use this view tool.')
            return None, None, None
        return doc, gui_doc, gui_doc.activeView()

    def _state(self, doc):
        # Native documents remain the only model. These caches hold view state.
        opened = App.listDocuments()
        for name in list(self._documents):
            if opened.get(name) is not self._documents[name]['document']:
                self._documents.pop(name, None)
                dialog = self._dialogs.pop(name, None)
                if dialog is not None:
                    dialog.close()
        if doc.Name not in self._documents:
            self._documents[doc.Name] = {'document': doc, 'views': {}, 'quality': None,
                                         'construction': {}, 'clipping': None, 'named_raw': None}
        state = self._documents[doc.Name]
        meta = doc.getObject('KurtShapeProject')
        raw = getattr(meta, NAMED_VIEWS_PROPERTY, None) if meta is not None else None
        if raw != state['named_raw']:
            state['named_raw'] = raw
            state['views'] = {}
            if raw:
                try:
                    if not isinstance(raw, str) or len(raw) > 1048576:
                        raise ValueError('Named view metadata is too large or has an invalid type.')
                    state['views'] = _validate_views(json.loads(raw, object_pairs_hook=_unique_json_object))
                except (ValueError, TypeError, OverflowError, RecursionError):
                    self._notify('Saved named view metadata is invalid; its camera entries were ignored.')
        return state

    def _store_views(self, doc, views):
        validated = _validate_views({'schema': 1, 'views': views})
        serialized = json.dumps({'schema': 1, 'views': validated}, ensure_ascii=False, allow_nan=False)
        if len(serialized) > 1048576:
            raise ValueError('Named view metadata is too large.')
        from .core import metadata
        meta = metadata(doc)
        if NAMED_VIEWS_PROPERTY not in meta.PropertiesList:
            meta.addProperty('App::PropertyString', NAMED_VIEWS_PROPERTY, 'KurtShape',
                             'Named native camera bookmarks stored with this project')
            meta.setEditorMode(NAMED_VIEWS_PROPERTY, 1)
        if meta.getTypeIdOfProperty(NAMED_VIEWS_PROPERTY) != 'App::PropertyString':
            raise ValueError('The project named view property has an incompatible type.')
        meta.NamedViews = serialized
        state = self._state(doc)
        state['views'] = validated
        state['named_raw'] = serialized

    def toggle_construction(self):
        """Toggle native visual layers of existing construction in edited sketch.

        Native Sketcher persists visibility as geometry-extension metadata. The
        construction flag and geometric definition are never changed. Original
        layer ids, including missing extensions, are restored by stable tags.
        """
        doc, gui_doc, view = self._context()
        if doc is None:
            return False
        edited = gui_doc.getInEdit()
        sketch = edited.Object if edited is not None else None
        if sketch is None or sketch.TypeId != 'Sketcher::SketchObject':
            self._notify('Edit a sketch to show or hide its construction geometry.')
            return False
        state = self._state(doc)['construction']
        saved = state.pop(sketch.Name, None)
        geometry = list(sketch.Geometry)
        original = {}
        changed = False
        for index, geo in enumerate(geometry):
            if saved is None and not sketch.getConstruction(index):
                continue
            tag = str(geo.Tag)
            has_layer = geo.hasExtensionOfType(VISUAL_EXTENSION)
            layer = geo.getExtensionOfType(VISUAL_EXTENSION).VisualLayerId if has_layer else None
            if saved is None:
                original[tag] = layer
                desired = 2
            elif tag in saved:
                desired = saved[tag]
            else:
                continue
            if layer == desired:
                continue
            # clone retains FreeCAD's geometry tag; copy allocates a new tag.
            copied = geo.clone()
            if desired is None:
                copied.deleteExtensionOfType(VISUAL_EXTENSION)
            else:
                import SketcherGui
                extension = SketcherGui.ViewProviderSketchGeometryExtension()
                extension.VisualLayerId = desired
                copied.setExtension(extension)
            geometry[index] = copied
            changed = True
        if saved is None and not original:
            self._notify('This sketch has no construction geometry.')
            return False
        if changed:
            doc.openTransaction('Construction geometry visibility')
            try:
                sketch.Geometry = geometry
                sketch.solve()
                doc.commitTransaction()
            except Exception:
                doc.abortTransaction()
                if saved is not None:
                    state[sketch.Name] = saved
                raise
        if saved is None:
            state[sketch.Name] = original
        view.redraw()
        self._notify('Construction geometry hidden.' if saved is None else
                     'Construction geometry visibility restored.')
        return saved is None

    def toggle_high_quality(self):
        """Toggle native tessellation quality and restore each original value."""
        doc, _, view = self._context()
        if doc is None:
            return False
        state = self._state(doc)
        saved = state['quality']
        if saved is None:
            saved = {}
            for obj in doc.Objects:
                vp = obj.ViewObject
                values = {}
                for name, maximum in [('Deviation', 0.05), ('AngularDeflection', 10.0)]:
                    if name in vp.PropertiesList:
                        value = getattr(vp, name)
                        value = float(value.Value if hasattr(value, 'Value') else value)
                        values[name] = value
                        setattr(vp, name, min(value, maximum))
                if values:
                    saved[obj.Name] = (obj, values)
            if not saved:
                self._notify('No tessellated objects are available in this document.')
                return False
            state['quality'] = saved
        else:
            for name, (original, values) in saved.items():
                obj = doc.getObject(name)
                if obj is original:
                    for key, value in values.items():
                        setattr(obj.ViewObject, key, value)
            state['quality'] = None
        view.redraw()
        self._notify('High-quality tessellation enabled.' if state['quality'] is not None
                     else 'Original tessellation quality restored.')
        return state['quality'] is not None

    def save_view(self, name, doc=None):
        doc = doc or App.ActiveDocument
        if doc is None:
            return False
        import FreeCADGui as Gui
        view = Gui.getDocument(doc.Name).activeView()
        name = str(name).strip()
        if not name:
            raise ValueError('Enter a name for the view.')
        state = self._state(doc)
        saved = dict(state['views'])
        saved[name] = _validate_camera(view.getCamera(), view.getCameraType())
        self._store_views(doc, saved)
        return True

    def delete_view(self, name, doc=None):
        doc = doc or App.ActiveDocument
        if doc is None:
            return False
        saved = dict(self._state(doc)['views'])
        if name not in saved:
            return False
        saved.pop(name)
        self._store_views(doc, saved)
        return True

    def recall_view(self, name, doc=None):
        doc = doc or App.ActiveDocument
        if doc is None:
            return False
        import FreeCADGui as Gui
        saved = self._state(doc)['views'][name]
        _validate_camera(saved['camera'], saved['projection'])
        view = Gui.getDocument(doc.Name).activeView()
        if view.getCameraType() != saved['projection']:
            view.setCameraType(saved['projection'])
        view.setCamera(saved['camera'])
        view.redraw()
        return True

    def named_views(self):
        doc, _, _ = self._context()
        if doc is None:
            return False
        from PySide import QtCore, QtGui
        import FreeCADGui as Gui
        state = self._state(doc)
        document_name = doc.Name
        existing = self._dialogs.get(doc.Name)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing
        dialog = QtGui.QDialog(Gui.getMainWindow())
        dialog.setObjectName('KurtShapeNamedViews')
        dialog.setWindowTitle('Named views · ' + doc.Label)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        layout = QtGui.QVBoxLayout(dialog)
        layout.addWidget(QtGui.QLabel('Camera bookmarks are stored with this project when saved.', dialog))
        listing = QtGui.QListWidget(dialog)
        listing.setObjectName('NamedViewList')
        layout.addWidget(listing)
        name = QtGui.QLineEdit(dialog)
        name.setObjectName('NamedViewName')
        name.setPlaceholderText('View name')
        layout.addWidget(name)
        buttons = QtGui.QHBoxLayout()
        layout.addLayout(buttons)
        def refresh():
            listing.clear()
            listing.addItems(list(state['views']))
        def valid_document():
            if App.listDocuments().get(document_name) is not doc:
                self._notify('The document for these camera bookmarks is closed.')
                return False
            return True
        def save():
            if valid_document() and name.text().strip():
                chosen = name.text().strip()
                try:
                    self.save_view(chosen, doc)
                except ValueError as exc:
                    self._notify(str(exc))
                    return
                refresh()
                listing.setCurrentRow(list(state['views']).index(chosen))
        def recall():
            if valid_document() and listing.currentItem():
                try:
                    self.recall_view(listing.currentItem().text(), doc)
                except (ValueError, KeyError) as exc:
                    self._notify(str(exc))
        def remove():
            if valid_document() and listing.currentItem():
                self.delete_view(listing.currentItem().text(), doc)
                refresh()
        for label, slot in [('Save current', save), ('Recall', recall), ('Remove', remove),
                            ('Close', dialog.close)]:
            button = QtGui.QPushButton(label, dialog)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        listing.itemDoubleClicked.connect(lambda _: recall())
        listing.currentTextChanged.connect(name.setText)
        def forget():
            if self._dialogs.get(document_name) is dialog:
                self._dialogs.pop(document_name, None)
        dialog.destroyed.connect(forget)
        self._dialogs[doc.Name] = dialog
        refresh()
        dialog.resize(400, 320)
        dialog.show()
        return dialog

    def section_view(self):
        """Open the native clipping controls with real X/Y/Z/custom planes."""
        doc, _, _ = self._context()
        if doc is None:
            return False
        import FreeCADGui as Gui
        from PySide import QtGui
        state = self._state(doc)
        main = Gui.getMainWindow()
        before = main.findChildren(QtGui.QDockWidget, 'Clipping')
        Gui.runCommand('Std_ToggleClipPlane')
        docks = main.findChildren(QtGui.QDockWidget, 'Clipping')
        # Native clipping creates its own per-document dock and owns its planes.
        # Existing docks remain alive while hidden, so ensure controls can reopen.
        created = [dock for dock in docks if dock not in before]
        dock = state['clipping']
        if created:
            dock = created[-1]
        elif dock not in docks:
            dock = next((candidate for candidate in docks if candidate.isVisible()), None)
        state['clipping'] = dock
        if dock is not None:
            dock.show()
            dock.raise_()
        return dock is not None


def callbacks(parent=None):
    """Return retained callbacks for the four Onshape view shortcut ids."""
    actions = ViewportActions(parent)
    return {'view.construction': actions.toggle_construction,
            'view.named': actions.named_views,
            'view.high_quality': actions.toggle_high_quality,
            'view.section': actions.section_view}
