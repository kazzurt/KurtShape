# Onshape shortcut compatibility

The complete official Windows default table is recorded in `shortcuts.json`, checked on October 2, 2026 against the [official Onshape shortcuts documentation](https://cad.onshape.com/help/Content/Home/keyboard_shortcuts_and_hotkeys.htm) (page updated September 24, 2026). The registry contains 126 normalized default action/gesture records and 3 separate local file shortcuts. Directional key groups are expanded; the repeated construction-tool entry is deduplicated.

This is a complete key registry with partial function equivalence. Unsupported operations are named in help and feedback. After the review follow-up the registry has 38 native equivalents, 48 official callback actions, 34 unavailable meanings and 6 recorded gestures with unverified exact compatibility. Live help checks callbacks and installed native commands. Pierce is Shift+G, Perpendicular remains Shift+L. Kurt deferred analysis/history-bar tools, assemblies/mates, Feature Studio code tools and drawings.

**Rebind selected / Reset selected** in shortcut help persists action-ID overrides in `runtime/shortcuts.user.json` (or the isolated session profile). Keyboard syntax and context collisions reject before replacement. Overrides show `*`; invalid startup files fall back to usable defaults. Palettes list capable actions in the current context.

## Daily use

- `Shift+S` starts sketch-plane selection in a Part Studio. In an active sketch it selects Point, matching the official context-specific default.
- `Shift+E` opens Extrude; `Shift+W` opens Revolve. `Shift+F` means edge fillet outside a sketch and sketch fillet inside one.
- `S` opens a compact tool palette at the pointer; `Alt+C` opens current-context tool search; `Shift+/` opens the complete searchable shortcut list.
- The single backquote key opens native entities under the pointer, including occluded faces, with hover highlighting and exact subelement selection.
- `Shift+1` through `Shift+7` select front, back, left, right, top, bottom, and isometric views. `F` fits the current view, `W` opens box zoom, `Z` zooms out, and `Shift+Z` zooms in.
- `Ctrl+S`, `Ctrl+N`, and `Ctrl+O` are separately labeled local save/new/open extensions. The different official drawing and Feature Studio meanings of `Ctrl+S` remain recorded in their own contexts.

Text inputs retain ordinary letters, copy/paste, text undo, and arrows. Local Ctrl+S/N/O still invoke the application save/new/open callbacks from those fields, protecting staged/recovery save behavior. Modal dialogs own their shortcuts and retain Return/Escape. Callback handlers can return `False` to leave a key to native Sketcher; Escape can cancel its current geometry tool without discarding the whole sketch. Native workbench shortcut conflicts are intercepted through the application event filter, not competing QShortcut objects.

## Native equivalent boundaries

Geometry and constraints operate in the same native sketch and document. The native [Coincident tool](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Sketcher_ConstrainCoincident.md) supplies concentric circle/arc/ellipse centers. The native [Symmetric tool](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Sketcher_ConstrainSymmetric.md) supplies midpoint when a line and point are selected. Native tool selection and solver feedback can differ from Onshape. Circle/rectangle/line/point and editing tools exit when their shortcut is repeated; construction invokes its native toggle each time.

True continuous curvature, Onshape normal and 3D pierce constraints, the in-progress line/tangent-arc switch, rollback, Feature Studios, assemblies/mates, drawings, and analysis tools remain unavailable unless a concrete application callback is supplied. Held Shift and mouse gestures are recorded and passed to the native GUI; that is not evidence of exact Onshape gesture equivalence. Select Other uses the native ray-hit API, preserving the active view/edit context and rejecting stale geometry; eight real viewport checks passed at 150% DPI. See [general action compatibility](general-actions-compatibility.md) for native feature/sketch copy, reports, document switching, and selection evidence.

## Integration contract

Use `ShortcutRouter(app, callbacks, context_provider, status_callback, registry_path=None, native_runner=None)`, then `install()`. Callbacks map action IDs below to zero-argument functions. Return `False` to defer; normal returns consume the key. The optional native runner receives the verified command ID and can perform the same transaction/safety handling as toolbar tools. `available_actions(context=None)` returns context-resolved registry dictionaries with `resolved_status`; `show_help`, `show_palette`, and `show_search` provide the built-in panels. Specific sketch/assembly/drawing contexts override shared general/view keys.

## Complete registry

| Action | Key | Context | Registered backend | Native command |
| --- | --- | --- | --- | --- |
| Accept and repeat tool | Shift+Enter | general | callback |  |
| Accept tool | Enter | general | callback |  |
| Cancel tool | Escape | general | callback |  |
| Clear selection | Space | general | callback |  |
| Copy feature | Ctrl+C | general | callback |  |
| Curve and surface analysis | Shift+C | general | unsupported |  |
| Delete selection | Delete | general | callback |  |
| Delete selection | Backspace | general | native | Std_Delete |
| Dihedral analysis | Shift+D | general | unsupported |  |
| Find FeatureScript | Ctrl+Shift+F | feature_studio | unsupported |  |
| Report a bug | Ctrl+U | general | callback |  |
| Flip mate primary axis | A | mate_edit | unsupported |  |
| Show or hide mate connectors | K | general | unsupported |  |
| Keyboard shortcuts | Shift+/ | general | callback |  |
| Lock mate inference (hold) | Shift | assembly | pass_through |  |
| Create mate connector | Ctrl+M | general | unsupported |  |
| Measure | [ | general | callback |  |
| Open document in browser tab | Ctrl+Click | document_browser | pass_through |  |
| Open document in browser window | Shift+Click | document_browser | pass_through |  |
| Paste feature | Ctrl+V | general | callback |  |
| Switch recent document tabs | Ctrl+Space | general | callback |  |
| Redo | Ctrl+Y | general | callback |  |
| Rename selection | Shift+N | general | callback |  |
| Search tools | Alt+C | general | callback |  |
| Select other entity | &#96; | general | callback |  |
| Shortcut tool palette | S | general | callback |  |
| Document tab manager | Alt+T | general | callback |  |
| Undo | Ctrl+Z | general | callback |  |
| Extrude | Shift+E | part_studio | callback |  |
| Edge fillet | Shift+F | part_studio | native | PartDesign_Fillet |
| Show or hide sketches | Shift+H | part_studio | callback |  |
| Move selected rollback bar up | Up | rollback | unsupported |  |
| Move selected rollback bar down | Down | rollback | unsupported |  |
| Revolve | Shift+W | part_studio | native | PartDesign_Revolution |
| Start sketch; select face or plane | Shift+S | part_studio | callback |  |
| Show or hide mates | J | assembly | unsupported |  |
| Insert parts and assemblies | I | assembly | unsupported |  |
| Fasten mate | M | assembly | unsupported |  |
| Show mates mode | H | assembly | unsupported |  |
| Assembly snap mode | Shift+S | assembly | unsupported |  |
| Back view | Shift+2 | view | native | Std_ViewRear |
| Bottom view | Shift+6 | view | native | Std_ViewBottom |
| Front view | Shift+1 | view | native | Std_ViewFront |
| Hide construction geometry | Shift+P | view | callback |  |
| Hide selected or hovered part | Y | view | callback |  |
| Show or hide planes | P | view | callback |  |
| Isometric view | Shift+7 | view | native | Std_ViewIsometric |
| Left view | Shift+3 | view | native | Std_ViewLeft |
| Isolate selection | Shift+I | view | callback |  |
| Make selection transparent | Shift+T | view | callback |  |
| Named views | Shift+V | view | callback |  |
| Pan left | Ctrl+Shift+Left | view | callback |  |
| Pan right | Ctrl+Shift+Right | view | callback |  |
| Pan up | Ctrl+Shift+Up | view | callback |  |
| Pan down | Ctrl+Shift+Down | view | callback |  |
| Rotate left 5 degrees | Ctrl+Left | view | callback |  |
| Rotate right 5 degrees | Ctrl+Right | view | callback |  |
| Rotate up 5 degrees | Ctrl+Up | view | callback |  |
| Rotate down 5 degrees | Ctrl+Down | view | callback |  |
| Rotate left 90 degrees | Shift+Left | view | callback |  |
| Rotate right 90 degrees | Shift+Right | view | callback |  |
| Rotate up 90 degrees | Shift+Up | view | callback |  |
| Rotate down 90 degrees | Shift+Down | view | callback |  |
| Right view | Shift+4 | view | native | Std_ViewRight |
| Rotate left 15 degrees | Left | view | callback |  |
| Rotate right 15 degrees | Right | view | callback |  |
| Rotate up 15 degrees | Up | view | callback |  |
| Rotate down 15 degrees | Down | view | callback |  |
| Section view | Shift+X | view | callback |  |
| Select through transparent | Alt+Click | view | pass_through |  |
| Show hidden parts | Shift+Y | view | callback |  |
| Top view | Shift+5 | view | native | Std_ViewTop |
| High-quality view | Shift+R | view | callback |  |
| Normal to selected plane or face | N | view | callback |  |
| Zoom in | Shift+Z | view | native | Std_ViewZoomIn |
| Zoom out | Z | view | native | Std_ViewZoomOut |
| Zoom to fit | F | view | native | Std_ViewFitAll |
| Zoom window | W | view | native | Std_ViewBoxZoom |
| Three-point arc | A | sketch | native | Sketcher_Create3PointArc |
| Center-point circle | C | sketch | native | Sketcher_CreateCircle |
| Center rectangle | R | sketch | native | Sketcher_CreateRectangle_Center |
| Coincident constraint | I | sketch | native | Sketcher_ConstrainCoincidentUnified |
| Concentric constraint | Shift+O | sketch | native | Sketcher_ConstrainCoincident |
| Corner rectangle | G | sketch | native | Sketcher_CreateRectangle |
| Curvature constraint | Shift+U | sketch | unsupported |  |
| Dimension | D | sketch | native | Sketcher_Dimension |
| Equal constraint | E | sketch | native | Sketcher_ConstrainEqual |
| Extend geometry | X | sketch | native | Sketcher_Extend |
| Fix geometry | Shift+J | sketch | native | Sketcher_ConstrainBlock |
| Horizontal constraint | H | sketch | native | Sketcher_ConstrainHorizontal |
| Line | L | sketch | native | Sketcher_CreateLine |
| Switch line and tangent arc | Shift+A | sketch | unsupported |  |
| Midpoint constraint | Shift+M | sketch | native | Sketcher_ConstrainSymmetric |
| Normal constraint | Shift+K | sketch | unsupported |  |
| Offset geometry | O | sketch | native | Sketcher_Offset |
| Parallel constraint | B | sketch | native | Sketcher_ConstrainParallel |
| Perpendicular constraint | Shift+L | sketch | native | Sketcher_ConstrainPerpendicular |
| Pierce constraint | Shift+G | sketch | unsupported |  |
| Sketch point | Shift+S | sketch | native | Sketcher_CreatePoint |
| Sketch fillet | Shift+F | sketch | native | Sketcher_CreateFillet |
| Suppress inference (hold) | Shift | sketch | pass_through |  |
| Symmetric constraint | Shift+Q | sketch | native | Sketcher_ConstrainSymmetric |
| Tangent constraint | T | sketch | native | Sketcher_ConstrainTangent |
| Construction geometry | Q | sketch | native | Sketcher_ToggleConstruction |
| Trim geometry | M | sketch | native | Sketcher_Trimming |
| Use / project external geometry | U | sketch | native | Sketcher_Projection |
| Vertical constraint | V | sketch | native | Sketcher_ConstrainVertical |
| Previous cursor position | Ctrl+] | feature_studio | unsupported |  |
| Commit Feature Studio | Ctrl+S | feature_studio | unsupported |  |
| Commit all Feature Studios | Ctrl+Shift+S | feature_studio | unsupported |  |
| Dismiss autocomplete | Escape | feature_studio | unsupported |  |
| Next cursor position | Ctrl+[ | feature_studio | unsupported |  |
| Top-level symbol outline | Ctrl+Shift+O | feature_studio | unsupported |  |
| Copy annotation by dragging | Alt+LeftDrag | drawing | pass_through |  |
| Diameter dimension | Shift+D | drawing | unsupported |  |
| Show or hide drawing sheets | Ctrl+S | drawing | unsupported |  |
| First drawing sheet | Home | drawing | unsupported |  |
| Last drawing sheet | End | drawing | unsupported |  |
| Minimum / maximum dimension | Ctrl+M | drawing | unsupported |  |
| Next drawing sheet | PageDown | drawing | unsupported |  |
| Drawing note | N | drawing | unsupported |  |
| Previous drawing sheet | PageUp | drawing | unsupported |  |
| Projected drawing view | P | drawing | unsupported |  |
| Drawing midpoint / quadrant points | Shift+Q | drawing | unsupported |  |
| Drawing radial dimension | Shift+R | drawing | unsupported |  |
| Update drawing views and properties | Ctrl+Q | drawing | unsupported |  |
| Save native project (local extension) | Ctrl+S | general | callback |  |
| New part (local extension) | Ctrl+N | general | callback |  |
| Open native project (local extension) | Ctrl+O | general | callback |  |

## Verification

All 38 native mappings appear in the pinned runtime command inventory. The isolated probe activated PartDesign, Sketcher, Part, Draft, and TechDraw without importing KurtShape UI or touching the current app session. Twenty-one focused checks passed, including native shortcut collision interception, text typing/undo safety, global save/new/open from fields, modal dialog shortcut ownership, shifted number views, context conflicts, unsupported feedback, dimension dialog Return, palette arrow/Escape isolation, shortcut-help typing/toggling, and restarting a tool after native right-click cancellation.

Reproduce with the bundled Python: `python -B -m unittest discover -s tests -p test_shortcuts.py -v` (from the KurtShape folder; set `QT_QPA_PLATFORM=offscreen` for the Qt checks). Run `tools/shortcut-command-probe.FCMacro` in a separate hidden native session only to refresh the native inventory. Evidence is in `validation/onshape-shortcuts-source.json` and `validation/onshape-shortcuts-command-probe.json`. GUI-level modeling and current callback coverage are validated by the main usability pass.
