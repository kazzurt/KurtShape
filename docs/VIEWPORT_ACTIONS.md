# Native view shortcut actions

Implemented for the bundled FreeCAD 1.1.4 build (revision
`4fd3bf320d9566a27e60069fc8387448aaa3a094`). The UI retains one callback map:

```python
from .viewport_actions import callbacks as viewport_callbacks
callbacks.update(viewport_callbacks(self))
```

| Onshape shortcut | Callback id | Native operation |
| --- | --- | --- |
| Shift+P | `view.construction` | Toggle visual layers of construction geometry in the sketch being edited |
| Shift+V | `view.named` | Open named camera bookmarks; save, recall, replace and remove |
| Shift+R | `view.high_quality` | Toggle object tessellation deviation and angular deflection |
| Shift+X | `view.section` | Open the native Clipping dock with X/Y/Z and custom plane controls |

Construction visibility uses
`SketcherGui.ViewProviderSketchGeometryExtension.VisualLayerId=2`, the same hidden
layer used by the native Elements visibility checkbox. It never toggles the
construction flag. Native geometry `clone()` retains tags, so restoring original
visual layers does not replace points edited while hidden. `copy()` allocates a
new tag and was rejected during validation. Original layer 1 and absent visual
extensions both restore exactly. The native layer is saved as geometry metadata;
its transaction participates in the existing sketch-edit lease and undo history.
Geometry created after a hide operation keeps its native default visibility.
Native construction is displayed while editing a sketch, so this action requires
an active sketch edit.

Named views retain the native `getCamera()` serialization and camera projection,
then restore them with `setCameraType()` and `setCamera()`. This is the native
camera mechanism used by FreeCAD's frozen views. Bookmarks are scoped to the
document and persist in `KurtShapeProject.NamedViews`, a versioned JSON property
inside the native FCStd file. Saving or deleting a bookmark marks the native
document modified; loading and recalling bookmarks do not modify geometry or
create metadata properties. The property is created only by save/delete actions.
View metadata is excluded from the core geometry-intent signature. Recall
preserves the active native sketch edit. Native camera
serialization rounds numeric fields, and FreeCAD adjusts near/far clipping during
redraw; validation compares position, orientation, focal distance, field of view
and projection at an appropriate numeric tolerance.

High quality uses native ViewObject properties: deviation at most 0.05 percent
and angular deflection at most 10 degrees, retaining finer existing settings.
Turning it off restores every original value. These settings change
tessellation, not the solid BRep. Native angular deflection can also influence
native mesh-export tessellation. Objects added after enabling quality retain
their native defaults.

Section view opens `Std_ToggleClipPlane` and exposes its actual clipping dock.
Users enable the desired native plane there. It creates no solid feature and
does not cut or replace the BRep. Hidden clipping controls reopen; the native
dialog owns the Coin clip planes and document activation behavior.

Primary source references:

- [Native Sketcher visibility layers and checkbox](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Sketcher/Gui/TaskSketcherElements.cpp)
- [Native geometry cloning and extension APIs](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Part/App/GeometryPyImp.cpp)
- [Native camera bookmarks and clipping command](https://github.com/FreeCAD/FreeCAD/blob/main/src/Gui/CommandView.cpp)
- [Native clipping plane implementation](https://github.com/FreeCAD/FreeCAD/blob/main/src/Gui/Clipping.cpp)

## Reproduce verification

Run `tools/viewport-actions-validation.FCMacro` in a separate FreeCAD process with
`-u` and `-s` paths under `runtime/viewport-actions-validation`, plus isolated
`FREECAD_USER_HOME`, `APPDATA`, `LOCALAPPDATA`, `TEMP` and `TMP` there. Set
`KURTSHAPE_ROOT` to this project. Start the helper with PowerShell
`Start-Process -WindowStyle Hidden`; do not add FreeCAD's `--hidden` flag.
The macro renders its main window with `WA_DontShowOnScreen`, without opening a
visible helper window or the assistant bridge. It closes only its own documents
and process.

Persisted data is validated before camera restoration: one native camera block,
known fields, finite numeric values, matching projection, valid camera distances,
unique JSON keys, supported schema and bounded names/count/data size. Scene
nodes, file references and malformed camera data are rejected. The project is
the only persisted source; the dialog's document cache refreshes when the native
property changes.

Results are recorded in `validation/viewport-actions-test-result.json`, including
native metadata restoration, unchanged BReps, camera fields, native dialog button
behavior, an enabled Coin clipping plane and document-scoped camera caches.
The expanded checks also save/close/reopen an FCStd file, restore perspective
camera bookmarks, preserve exact geometry/constraints/construction flags and
canonical attachment data, delete/save/reopen a bookmark, reject malformed data,
and verify repeated navigation setup leaves the native modified indicator clear.
Native restore refreshes the derived `AttacherEngine` display label from its
canonical `AttacherType`; this display text is excluded from the roundtrip
comparison.
The completed isolated run passed all 40 assertions. All helper processes closed
their own native documents and exited; the user's live FreeCAD process was not
used.
