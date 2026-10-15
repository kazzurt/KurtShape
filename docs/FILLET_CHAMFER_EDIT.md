# Editable Fillet and Chamfer

Double-click a Fillet or Chamfer in the feature history, or right-click it and choose **Edit Fillet / Edit Chamfer**. The feature dialog reopens with its current edges, Radius/Size and formula.

## What it does

- **Edges.** The edge list shows the feature's current edges. You can click more edges, remove an edge with its row **×**, choose **Clear all**, or replace the set.
- **Input shown.** While editing, the feature's input (the solid before the fillet) is shown, and the completed feature is hidden. The current edges are highlighted on that input. Edges the fillet rounded away can therefore be picked again.
- **Edge-only picking.** Fillet and Chamfer, both new and edited, use a native selection gate. Only eligible edges highlight or select. When editing, these are the input's edges; when creating, they are edges of solid parts. Hovering a face draws no highlight, including KurtShape's face-outline hover. Clicking a face or an ineligible edge leaves the selection unchanged and shows the reason in the message bar.
- **Values.** The Radius/Size field shows the native value. Its tooltip gives the exact value, which is kept unless you change the field. A **Formula** field shows the native expression and can be edited or cleared.
- **Preview and Confirm.** The preview is evaluated in a disposable native copy, so the live document does not change. Confirm edits the same native feature in place; its name and downstream references are kept. A successful edit is one Undo step, and Redo restores it. Cancel changes nothing.
- **Errors.** With no edges selected, the dialog says *Select one or more edges in the model.* An impossible radius reports that the fillet could not be built and suggests a smaller value or different edges. A duplicate edge, a face reference or an invalid formula is rejected. Confirm stays disabled while the preview is invalid.
- **Restored picking.** Confirm, Cancel, a document switch, Undo, or any other operation that closes the dialog removes the gate. The tick loop also removes it if the dialog disappears for any other reason.

Edges picked in the viewport are stored as KurtShape selectors (closest edge on the part), as for a new fillet. They resolve against history before the feature. Untouched edges are sent back as their stored selectors.

## Implementation

| Piece | Where |
|---|---|
| `describe_dress_up`, `edit_dress_up` controller operation | `src/kurtshape/reference_tools.py` |
| Disposable preview of `edit_dress_up` | `src/kurtshape/extrusion_preview.py` |
| Edge-only selection gate and click feedback | `src/kurtshape/edge_picking.py` |
| Face-hover suppression | `src/kurtshape/hover_outline.py` |
| Input-only view (`hide_self`) | `src/kurtshape/sketch_history.py` |
| Dialog edit mode, history entry points | `src/kurtshape/ui.py` (`edit_dress_up`, `studio_tool(edit=...)`) |

Native Undo does not restore a dynamic property that one transaction removes and adds again. The edit therefore rewrites selector metadata values in place instead of unbinding and rebinding the selectors.

## Evidence (Windows, FreeCAD 1.1.4 / OCCT 7.8.1)

- `tests/test_dress_up_edit.py` (native, 9 tests): reopen reports the native settings and edges from the input; add, remove and replace edges in one Undo step with exact Undo/Redo of the native intent; preview is disposable and matches Confirm; exact values and formulas are kept; invalid edits explain the problem and change nothing; downstream features keep their input; Chamfer; Studio parts with part-scoped selectors.
- `tools/dress-up-edit-validation.FCMacro` (`run_gui_recipe.ps1 -Recipe dress-up-edit`, 57 checks): real viewport mouse events. Hovering a face changes 0 rendered pixels while gated, compared with 1448 for an ordinary outlined hover. Edges preselect and select. Create, reopen, the rounded-away edge, add, preview, Confirm, Undo/Redo, row removal, Cancel, Clear all, an oversize radius, a document change, Chamfer size, and the same flow on a Studio part.
- Adopted copy of `test-261014.FCStd`: a Fillet on Part 1 is edited from one edge to two. The preview is valid; the edit is one Undo step; Part 2 and its mirror keep their volumes; save and reopen keep the edges and radius. The original file's hash is unchanged.

## Limitations

- The Radius/Size field displays the native spin box's rounding, for example `1.23 mm` for 1.2345678 mm. The exact value is kept and shown in the tooltip.
- Chamfer types other than equal distance keep their extra settings, but only Size and edges are editable here. A Fillet set to *Use all edges* says so when reopened.
- The reselection view shows each part as it stood before the edited feature, using the same rules as editing an earlier sketch.
