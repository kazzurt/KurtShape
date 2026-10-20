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
| Shift+X | `view.section` | Section View: a view-only cut on a face or plane with a drag arrow (below) |

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

## Section View (Shift+X)

`src/kurtshape/section_view.py`; the Panel owns one `SectionView` and feeds it
selection, history clicks, Escape, its tick and mouse events. It replaced the
native Clipping dock (X/Y/Z check boxes and number fields, hollow cuts, no way to
close it with Shift+X) on 2026-10-20. Same behaviour in Part Studio, Assembly and
while sketching.

- **Start:** select a face or plane and press Shift+X, or press Shift+X with
  nothing selected and then click a face, a visible datum plane, or Top / Front /
  Right in the history. Escape cancels that pick. Shift+X with an edge or vertex
  selected says it needs a face or plane.
- **Which plane:** a round face (cylinder, cone, torus, sphere, revolved face, or
  a flat face whose outline is one circle, such as an end cap or washer face) and
  any other curved face cut through their centre: the middle of the axis within
  the face, or the face's centre of mass for freeform faces. The plane is the
  origin plane (Top, Front or Right) the camera looks at most squarely; a tilted
  axis keeps that origin-aligned plane through the centre. In an assembly these
  are the assembly's planes. A non-round flat face, a datum plane or an origin
  plane cuts on itself (nudged 2e-6 of the model size toward the camera so the
  face itself never flickers).
- **What shows:** the side between the camera and the plane is hidden, so the cut
  faces you. Cut faces are filled, unshaded, in exactly the colour of the body
  being cut (the colour its view draws), with a dark outline. A dashed outline shows the plane (with a faint fill while
  dragging), and an orange double arrow with a ring sits at the cut's centre (for
  planes, over the model). The status bar reads
  `Section View · Right plane · +12.40 mm · drag the arrow · Shift+X or Esc exits`.
- **Adjust:** drag the arrow (or its ring) to slide the cut along the normal. The
  offset follows the mouse along the arrow's on-screen direction; when the cut
  faces you squarely and the arrow points at you, vertical motion moves it (up
  pulls it toward you). The cut stays within the shown parts. There are no inputs.
- **Leave or move:** Shift+X with nothing selected or Escape leaves (Escape first
  cancels an open feature dialog). Shift+X with another face or plane selected
  moves the cut there. Starting clears the selection.
- **View only:** nothing is added to the document: no feature, history row,
  transaction, undo step, revision or modified flag, and nothing is saved.

How it is built:

- The model is clipped by one `SoClipPlane` inserted just before the viewer's
  `ObjectGroup`, where FreeCAD's own clip plane goes, so sketch editing in
  `EditingRoot` stays whole. Native ray picks respect it: clicks cannot select
  hidden geometry. The cut faces, plane outline and arrow sit in a separator
  before the clip plane and are never clipped; the arrow is an unpickable
  `SoAnnotation` drawn over the model and kept about 58 px long on screen.
- Cut faces come from a tessellation of each visible solid (cached per part,
  shape, placement and tolerance), not from OCCT `slice`, which takes about
  0.5 s per Shell M solid. A cut walks only the triangles in the slab around the
  plane, chains crossing edges into closed loops, nests holes by depth and fills
  them by ear clipping (`polygon_fill.py`, a port of Mapbox earcut). Pure Python:
  the GUI process keeps numpy out. Measured on 2026-10-20: a cut-face update takes
  about 5 ms on Shell M and 35 ms on the LED pole battery assembly; meshing on
  first use takes 0.3 s and 2.0 s and runs a slice at a time after the cut first
  paints, so faces fill in part by part; afterwards the other visible solids are
  meshed in idle time, one per turn, so a drag into a part the cut did not cross
  at first fills live too. Areas match OCCT's exact section within about 0.1 %.
- During a drag the cut faces are recomputed in the same mouse event that moves
  the clip plane (never meshing there; a solid not meshed yet stays open until the
  drag ends). Recomputing them on a timer a frame later made a cut moving toward
  the camera flicker: for that frame the clip had already opened the solid while
  its cut face was still behind, so its hollow inside showed (fixed 2026-10-20).
- The arrow is dragged in the Panel's application event filter, which sees mouse
  events before the viewer: a left press within 7 px of the drawn arrow or inside
  its ring takes the press, moves and release, so neither selection nor any
  navigation style reacts. (A Coin `SoTranslate1Dragger` was tried first; its
  drag crashed in Coin with an access violation and cannot follow an end-on arrow.)
- Model edits, visibility and colour changes refresh the cut faces from the Panel
  tick; closing the document drops the section.

The headless `render_view` sections (`model_render.py`, `render_jobs.py`) are a
separate, exact renderer for model images and are unchanged.

Primary source references:

- [Native Sketcher visibility layers and checkbox](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Sketcher/Gui/TaskSketcherElements.cpp)
- [Native geometry cloning and extension APIs](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Part/App/GeometryPyImp.cpp)
- [Native camera bookmarks](https://github.com/FreeCAD/FreeCAD/blob/main/src/Gui/CommandView.cpp)
- [Viewer scene roots used by Section View (EditingRoot, ObjectGroup)](https://github.com/FreeCAD/FreeCAD/blob/main/src/Gui/View3DInventorViewer.cpp)

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
behavior and document-scoped camera caches. (That 2026-10-02 record still lists the
retired native clipping checks; the macro now checks Section View's pick mode.)
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

Section View has its own recipe: `tools/run_gui_recipe.ps1 -Recipe section-view`
runs `tools/section-view-validation.FCMacro` in a hidden private FreeCAD on copies
of `projects/led-pole-battery/parts/Shell M.FCStd` and the LED pole battery
assembly (override with `SECTION_PART_SOURCE` / `SECTION_ASSEMBLY_SOURCE`). It
presses Shift+X and Escape through the shortcut router, clicks faces and drags the
arrow with Qt mouse events, and checks plane choice, clip placement, cut faces,
picking, arrow size on zoom, Escape order, cut-face colour, live update time, that
every drag event already shows the cut face at the moved cut (no flicker), and that
the document is untouched. 45 checks passed on 2026-10-20 (cut-face updates 3 ms on
Shell M, 25 ms on the assembly). Unit tests: `tests/test_section_view.py`.
