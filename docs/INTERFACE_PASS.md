# October 2 interface and functionality pass

The user's requested interface is implemented around the existing authoritative native CAD document: document controls and feature/sketch tools on top, persistent left feature history with Top/Front/Right planes and parts, central native 3D graphics, and contextual settings/native tasks on the right. This retains Sketcher, PartDesign and OCCT rather than creating a second model.

SolidWorks navigation is the installed `Gui::SolidWorksNavigationStyle`. Middle orbit, Ctrl-middle pan, Shift-middle zoom, wheel, picked pivot and double-middle fit were verified through native Qt viewport events. Sketch entry preserves the camera, orbit works while editing, and normal/isometric views retain the editing session. Native coordinates are physical bottom-left pixels; Qt clicks use logical top-left pixels. The tested display scale is 150%.

Sketch creation uses real origin/datum/planar-face attachment. Shift+S enters placement mode; one history-plane or viewport-face click creates the native sketch. Face attachment follows tested upstream thickness edits. Geometry, constraints and dependencies remain native and persist through save/reopen. Invalid/curved supports reject explicitly.

Functionality fixes include actual blind-pocket depth, automatic material-side cut direction, unnamed driving dimensions and angles, exact spline intent signatures, grouped native sketch undo/redo, rollback after native resetEdit auto-commits, stale lease removal after closing a tab, dimension entry with Enter, repeat tool with Shift+Enter, task ownership on document switches, selection/visibility preservation, and clean modified indicators after successful staged save/reopen. N aligns to all three datum planes or a selected planar face and repeats to flip; Y also works on a hovered object. Built-in native PartDesign features can be deleted with dependency protection and undo. If no solid survives deletion, Body.Tip is cleared rather than incorrectly assigned to a sketch. Native workbench tasks stay usable while custom history remains visible; conflicting file/model/document-switch actions are guarded until the edit finishes or cancels.

The complete Onshape Windows default table is registered with context precedence and native-shortcut collision protection. Text input keeps typing, text undo and clipboard behavior; app save/new/open shortcuts remain guarded even from fields. Native feature/sketch copy-paste, native select-other, local problem reports, recent-document selection, clipping, construction layers and tessellation controls use the existing document. Named cameras persist in native metadata. Unsupported assembly/drawing/Feature Studio/analysis/advanced constraints remain named in help and feedback.

## Verification records and recipes

The completed core/transport/keyboard suites total **70 passing tests** (47 + 2 + 21). The integrated actual interface walkthrough passes **36 checks**; the navigation, general actions, select-other, viewport tools and normal/hover selection reports pass another 16, 25, 8, 40 and 20 checks respectively. These are bounded automated checks, with hands-on usability acceptance still pending.

The native model toolbar passes eight scenarios plus 39 active-feature guards. Fillet, Chamfer and Revolve were accepted as valid native solids and appeared in history; Mirror and Pattern were tested for dialog entry and exact restoration on Cancel. Direct assistant New/Open/Save/parameter requests reject during native editing and preserve the model, document inventory and edit dialog.

| Area | Record | Recipe |
| --- | --- | --- |
| Offline native model and projection suite | `validation/offline-test-result.json` | `run-checks.ps1` |
| Qt shortcut routing | `tests/test_shortcuts.py` | `run-checks.ps1` |
| Loopback cancellation/unknown outcome | `tests/test_bridge.py` | `run-checks.ps1` |
| Integrated shell, real keys/clicks, persistence and bridge | `validation/interface-pass/gui-test-result.json` | `launch-kurtshape.ps1 -Validation` |
| SolidWorks mouse controls and 3D sketch camera | `validation/navigation-test-result.json` | `tools/navigation-validation.FCMacro` |
| Native sketch transaction, grouped history, cancel and save state | `validation/sketch-lifecycle-result.json` | `tools/sketch-lifecycle-validation.FCMacro` |
| Native copy/paste, document tools, local report | `validation/general-actions-gui-result.json` | `tools/general-actions-validation.FCMacro` |
| Native select-other ray hits and occluded selection | `validation/general-actions-select-other-result.json` | Same general-actions macro |
| Construction layers, persisted cameras, clipping and quality | `validation/viewport-actions-test-result.json` | `tools/viewport-actions-validation.FCMacro` |
| Normal view on datum planes/faces, repeated flip and selected/hovered hide | `validation/view-selection-result.json` | `tools/view-selection-validation.FCMacro` |
| Fillet/Chamfer/Revolve native acceptance, Mirror/Pattern dialog cancellation and active-feature guards | `validation/toolbar-pass/toolbar-test-result.json` | `tools/toolbar-validation.FCMacro` |

Each GUI recipe uses separate runtime configuration and an invisible independent window. Raw originals are referenced in place. Test-native projects and exports are scoped to validation; the original acceptance fixture is not rewritten by this pass. Hands-on usability, broad topology changes and physical offline operation remain user acceptance checks. Native topological naming cannot guarantee every arbitrary face-changing edit.

The two actual Onshape migrations remain unconverted, and the supplied mutable workspace links are not authenticated/frozen captures. Their deferred edited STEP variants remain a separate M1 requirement. No Claude message or external publishing action was performed.

## Appearance and expanded-toolbar follow-up

Kurt reported white text on white backgrounds and missing top-bar features. The root cause was light widget backgrounds combined with an inherited dark Qt palette and FreeCAD window stylesheet. `src/kurtshape/theme.py` now owns the process-local application palette and stylesheet together, including native Tasks, dynamic dialogs, menus, inputs, disabled text and placeholders. Bundled native arrow assets restore dropdown/spin indicators, and neutral split-menu styling removes the black Sketcher dropdown rectangles. No Windows setting or FreeCAD preference is changed.

Modeling uses compact native command icons and six labeled menus. The installed catalog exposes 39 native modeling commands and 64 sketch commands, with native toolbar overflow at compact widths. Sweep, Loft, Hole, Shell, Draft and Boolean are directly visible. Sketch Geometry, Constraints and Edit menus expose the installed native tools; Extrude and Revolve also appear in the sketch toolbar. Each icon resolves from installed command metadata. Document views maximize after creation/opening/tab switching rather than remaining in a small framed window.

The core now blocks conflicting document and model mutations during native Tasks even when FreeCAD reports no `getInEdit()` object. The actual Part Extrude dialog reproduced this gap. A managed sketch lease only permits edits while the native edit object matches the same sketch and document.

Current evidence: `validation/appearance-pass/theme-result.json` passes 72 checks after a hostile dark-theme startup, including rendered glyph/button/indicator checks and long-menu scrolling. The minimum checked text contrast is 4.703:1. `layout-test-result.json` passes 133 checks and captures 21 screenshots at large/compact/narrow sizes, real expanded menus, Geometry-to-Point creation, native Fillet Tasks, settings/help and Qt file dialogs. Direct Build, Geometry and Constraints clicks open the actual tool list. At 800 pixels, native overflow expands the toolbar into rows; Shape tools and the Planes utility were reached and used through that route. The current core passes 47 offline tests and the integrated native GUI walkthrough passes 36 checks. These are bounded checks; catalog availability does not claim every advanced tool has full semantic acceptance coverage. See `docs/NATIVE_TOOL_CATALOG.md` for 17 native feature scenarios, 48 guard checks and reproduction commands.

A construction bug initially produced a redundant one-entry menu before the tool list. Binding the same QAction both as the button's default action and explicitly through `setMenu` cleared its native bindings. The final toolbar uses the menu's own QAction and its associated menu, with direct native one-click behavior. No timer or event-filter workaround is required. The final report hashes and current source fingerprints are recorded in `validation/appearance-pass/verification-summary.json`.

Run the original integrated recipe with `launch-kurtshape.ps1 -Validation`. Theme and layout checks use `tools/theme-validation.FCMacro` and `tools/appearance-validation.FCMacro` in separate invisible FreeCAD processes with `KURTSHAPE_ROOT`, `KURTSHAPE_NO_DEMO=1`, an isolated `KURTSHAPE_SESSION_DIR`, user/system configuration, APPDATA, LOCALAPPDATA and temporary directories. Invoke the bundled `freecad.exe` with `-u`, `-s`, `--log-file` and the macro path using `Start-Process -WindowStyle Hidden`; do not add FreeCAD's `--hidden` flag, which prevents this GUI macro lifecycle. Reports and editable native fixtures remain under validation. Existing user windows and raw source files are preserved.

Save and close an older running KurtShape window, then relaunch `KurtShape.cmd` to load this source. Standalone Shape tools may create objects outside the active Body; the assistant/export subset remains scoped to the managed Body. Assembly, drawing and full Onshape conversion parity remain separate work.
