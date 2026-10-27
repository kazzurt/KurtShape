# Everyday modeling UI (stage 2)

## Behavior changes

### Click selection adds (2026-10-24)

- A click on a face, edge or vertex **adds** it to the selection; clicking an element that is already selected removes it. Hovering a selected face outlines it in orange (a click removes it), an unselected one in blue.
- A click on empty space, or **Space**, clears the selection. Ctrl-click does the same toggle; Shift-click is unchanged.
- Sketch editing, native task dialogs, the joint dialog and every KurtShape picker (sketch plane, Section View, feature references) keep FreeCAD's own click behaviour.
- **Settings → Selection → Click adds to selection** turns it off (preference `KurtShape/Preferences/AdditiveSelection`); a click then replaces the selection again.

### Search tools (Alt+C, or the toolbar search field)

The dialog lists every tool in one place:
- the Part Studio bar and its **More** menus;
- the sketch bar and its menus;
- the assembly bar;
- the Document menu, including Undo/Redo;
- every shortcut-only action from the registry.

How results behave:
- Each tool appears once. Entries are merged by command or name, and the dialog shows where else the tool lives.
- Activating a result triggers the same `QAction` as its button, so it behaves exactly like the toolbar.
- Common CAD names find tools: *remove material, pocket, cut* → **Extrude · Cut**; *pad, boss* → Extrude; *round* → Fillet; *bevel* → Chamfer; *project, convert entities* → Use; and more.
- The shortcut column shows the user's current binding, so overrides are kept.
- An **Availability** column explains context: *Start or edit a sketch first*, *Finish the sketch first*, *Switch to Assembly*. Tools that cannot run in the current workspace explain why instead of running.

### Toolbar

- The Undo/Redo arrow buttons are gone from the Part Studio, Sketch and Assembly bars.
- Ctrl+Z / Ctrl+Y, custom bindings, **Document → Undo / Redo** and search still work.

### One Extrude tool

- The primary toolbar has a single **Extrude**. Its Operation choice is **New / Add / Cut / Intersect**.
- **Remove material** is now a searchable alias and the **More → Cut → Extrude · Cut** preset of the same tool. The separate Remove button is gone.
- In a native Body, Add and Cut create native Pad and Pocket, as before. New and Intersect, an explicit scope or an already-enabled Part Studio use Studio operations.
- Existing features are not converted. Reopening still shows their real native settings and keeps the existing limits on changing operation or end condition.

### Direction

**Measured:**
- For a sketch on a planar face, the default Extrude goes outward and the default Cut inward. This holds on top, bottom and side faces, for native and Studio features, for direct face extrusion, and for native features in a placed and rotated Body.
- A deliberate **Reverse** is respected: the solid goes into the material.

**Changed:** switching a face extrusion between Add and Cut now keeps a deliberate Reverse choice. It previously always overwrote it.

### Sketch fill

- Closed regions get a light translucent blue tint instead of an opaque light gray that could read as a hole.
- A small polygon offset with a `LEQUAL` depth test keeps the fill on a coplanar face without z-fighting, while solids still occlude it.
- The fill writes no depth and stays unpickable. Native outlines are unchanged. Only rendering changed; sketch geometry is untouched.

### Status, errors, Messages, Enter and Escape (slice A/B U7, 2026-10-22)

**Document status line** (bottom of the history panel; `feedback.status_text`). The first matching state wins. The footer (the window's status bar) shows the same text once command feedback times out, so the two never disagree.

| State | Exact text |
|---|---|
| Build failed, result check | `Result check failed · <feature> · <code> — see Messages` (plus ` (+N more)`) |
| Build failed, invalid solid | `Invalid geometry · <feature> — see Messages` |
| Build failed, native error | `Build failed · <feature>: <message>` (plus ` (+N more)`); `Build failed — see Messages` when no feature is named |
| Editing a sketch (managed lease open) | `Editing sketch · mm` (never "Rebuild required": a sketch under edit is always touched) |
| Needs rebuild | `Rebuild required · <reason>` (pending model changes, geometry engine changed, saved by another application build, geometry engine not recorded, stored geometry is missing) |
| No history rows | `Empty part · mm` |
| Sketches only | `Sketches only · mm` |
| Valid solids | `N solid(s)`, then ` · V mm³` when measured, ` · checked` after a valid check |

` · checks pending` follows the last two while result checks are pending. Imported STEP and reference files keep their prefixes (`Imported STEP · …`, `Reference file · inspect or adopt a copy · …`). The footer reads `Ready · create or open a part studio` with no document.

**Errors.** A rejected operation (a GUI action, or any assistant mutation the bridge processes, assembly included) puts `<message> · <feature> · <code>` in red in the status bar (`<document> · ` in front for bridge failures). The feature is the error's own `feature`, else the first of `features`, else `trigger.feature`, else the rejected request's `feature`, `id` (the new feature), `profile` or `sketch`; it is omitted when none names one. Messages keeps that line, one line per failing feature that carries its own message, `while <op> on <feature>`, the hint, and `details: <every other field of the error as JSON>` (the message is logged once). For the user's own actions, the first of those features that has a history row (a rolled-back new feature has none, so a rejected Remove selects the profile it was made from) is selected in the history and, while no editor, task, native feature dialog, sketch or picker is open, in the viewport, so an open Extrude or studio dialog keeps its inputs. A rejected assistant (bridge) change is reported in the status line and Messages only: it never changes the selection.

**Messages dot.** Every line that arrives while Messages is hidden counts as unread (hover help: `Show messages · N unread · K warnings or errors`); only warnings and errors light the dot (`Messages •`). Native report lines take their severity from the report view's warning / error colors. Lines from startup (until the shell finishes starting) count as neither.

**Text fields own their editing keys.** Copy, Select all, Paste, Cut, Undo and Redo in a focused text field (read-only ones such as Messages and the status line included) act on the text: with a model object selected, Ctrl+C in Messages copies the text and never opens FreeCAD's Object Selection dialog.

**Hover labels** show every shortcut, single keys included, read from the live shortcut registry when the label appears, so a rebinding (shortcut help → Rebind selected) shows the user's key: `Line  (L)`, `Fit  (F)`, `Sketch  (Shift+S)`, `Confirm  (Enter)`, `Cancel  (Escape)`. A tool whose key is unavailable or shadowed in its toolbar's context shows none (Spline, Rebuild; the sketch's Finish and Cancel, which Enter / Escape in the viewport do not trigger).

**Enter / Shift+Enter** in any field of an owned editor (the Feature settings editor and every studio dialog: Revolve, Sweep, Loft, Boolean, Split, Transform, patterns, Mirror, Fillet, Chamfer, Shell, Plane, Move face) confirm as the header check mark does, through the same gate: a disabled Confirm (no valid preview yet) ignores Enter. Shift+Enter confirms and reopens Extrude / Remove for the next profile; in a studio dialog (no repeat) it confirms. Enter does nothing while a reference picker field has the focus, and an open combo box list or completer keeps it. In a sketch's floating box Enter finishes the sketch, as its check mark does; Enter in the viewport does not (Kurt's decision, 2026-10-22).

**Escape ends the tool, never the sketch** (decision 2). In a sketch, Escape ends the active drawing or constraint tool (or reference picking); with no tool active the sketch stays open and the footer says `Sketch stays open · Finish or Cancel the sketch to leave it`. Finish and Cancel on the floating box (or the sketch toolbar) are the ways out. The app sets FreeCAD's Sketcher preference `LeaveSketchWithEscape` to false in its profile (`ui.start`, beside the autosave preferences) and, when it has nothing of its own to cancel, passes Escape on to native Sketcher: Sketcher ends a handler started outside KurtShape's tracking, cancels a drag in progress, and otherwise keeps the sketch open. Outside a sketch, Escape cancels the feature dialog, Extrude, sketch placement, a running geometry check or STEP export, as before.

### Saving and recovery (slice A/B U8, 2026-10-22)

**"Saving…" before every save stall.** Save, Save As, Adopt and an assistant's `save` write the project synchronously (FreeCAD's `saveCopy`, about 2.4 s on a 10 MB project). Before that write starts, the status line and the footer read `Saving…`, painted at once; a recovery checkpoint shows `Checkpoint…` the same way. The previous texts come back when the write is done (then `Save complete`, or the error).

**A locked destination.** When another program holds the file open (or it is read-only), the save fails with `Cannot write <file>: <OS reason>. Close it in the other program (or make it writable), then save again · save_destination_locked` in the status line and the details in Messages. The previous file is unchanged, no `<name>.saving.FCStd` is left behind, and saving again after the file is closed works. The `<name>.recovery.FCStd` copy of the previous file is written without the read-only attribute.

**Another project's file.** Save As asks before replacing an existing file (the Save dialog's own question) and then replaces it. An assistant's `save` onto an FCStd that holds another project is refused unless it passes `overwrite:true` (see `docs/OPERATION_CONTRACT.md`, slice A/B U8).

**Recovery checkpoints.** A project that changed since its last checkpoint is checkpointed after 2 s without input, at most once every 30 s per project (and immediately when a failed edit or a discard needs one). Checkpoints live in the session's `project-recovery` folder: `<checkout>\runtime\project-recovery\` for the normal app (`KURTSHAPE_SESSION_DIR\project-recovery\` for private and agent sessions), one `<document id>.FCStd` + `.json` pair per project with the one before it kept as `.previous`, and up to 20 `.discarded-…` pairs from closes that discarded changes. **Document → Recovery** lists the checkpoints newer than their saved file and shows this policy and the folder at the bottom. The checkpoint archive is written with ZIP compression level 1 (`"recovery_fast_snapshots": true` in `settings.json`, the default; false uses FreeCAD's level): every restored shape is byte-identical and the file 16–40 % larger; on the Dodec Hub the write drops from 2.30 s to 1.31 s and a forced checkpoint from 2.61 s to 1.62 s (no measurable change on small parts). The ZIP check, hash and replace of a checkpoint run off the GUI thread.

**FreeCAD's own autosaver is off** (decision 3). KurtShape's checkpoints are the one recovery writer, so `ui.start` sets FreeCAD's `Preferences/Document/AutoSaveEnabled` to false. To keep FreeCAD's one-minute autosaver as well, put `"keep_freecad_autosave": true` in the session's `settings.json` (`<checkout>\runtime\settings.json` for the normal app). FreeCAD reads the value when it starts, so either change takes effect from the next start (the first start after this update still runs the old one-minute autosaver once).

## Evidence

Fresh cloud runs: Linux, FreeCAD 1.1.4 / OCCT 7.8.1. **Windows not run.**

| Check | Kind | Result |
|---|---|---|
| `test_tool_search` (4) | headless, pure Python | pass: dedupe, aliases, user binding, availability |
| `test_everyday_modeling` (5) | headless native | 4 pass plus 1 expected failure (below): defaults on four faces, native, Studio, face extrusion, rotated native |
| `everyday-ui` GUI recipe | hidden GUI (Xvfb) | 23/23. Real search dialog (194 tools, no duplicates); `cut` + Enter opens Cut mode; preview inward, Add outward; Cut creates a native Pocket in one Undo step; toolbar and menu checks; rendered pixels |
| Visual inspection | screenshots of the same run | from above: translucent blue square on the face with a readable outline, face visible through it. From below: uniform bottom face, fill occluded (identical pixels at the sketch location and a bare area) |
| `extrusion-edit` / `history-lifecycle` GUI recipes | hidden GUI | 43/43, 29/29 |
| `sketch-regions` GUI recipe | hidden GUI | Not run here: segfaults during setup in this harness on the baseline too. Its "light gray" pixel checks now expect a translucent tint. Needs Windows. |

**Windows validation (October 15, FreeCAD 1.1.4 / OCCT 7.8.1):**

- **`everyday-ui`: 46/46.** Adds repeated search open, search, activate, close and reopen after native deletion. This reproduced and now fixes *Internal C++ object already deleted*. It also adds rotated-Body Studio Add/Cut preview = Confirm.
- **`sketch-regions`: 34/34.** The recipe now faces the sketch front, compares the on-face tint with the bare face, and samples the unselected boundary.
- **Other GUI recipes:** `extrusion-edit` 43/43; `part-studio` 101/101; `design-surface` 408/408; `history-lifecycle` 29/29; `rollback-history` 45/45.
- **`run-checks.ps1`:** 522 passed and 4 opt-in perf skips, with 0 failures and 0 expected failures.

## Limitations

- **Corrected on Windows (October 15):** the reported placed/rotated Body Studio Add/Remove preview failure was a test defect, not a product defect. The expected-failure test looked for a global +Z face. A rotated Studio part has no such face, because its output faces are global, so the test failed before it reached the preview. With rotated face normals, every face previews validly for Add and Cut, and Confirm produces exactly the previewed solid, in native tests and in the real GUI (`everyday-ui` recipe: Add 1204 = 1204 mm³, Cut 1196 = 1196 mm³, Reverse override honored). The test is now an ordinary passing regression. The transformed-Body Up-to-face limitation is separate and unchanged.
- Translucent blending depends on the native Coin blend mode. The exact blended color is not asserted, only the tint and occlusion.
- The search dialog lists Part Studio tools in Assembly with *Switch to Part Studio*. It does not switch workspaces automatically.

## Windows acceptance walkthrough

1. Launch `.\launch-kurtshape.ps1` on this branch. The Part Studio bar has no Undo/Redo arrows and one **Extrude**. Ctrl+Z / Ctrl+Y still work, and **Document → Undo/Redo** exist.
2. Press **Alt+C** and type `remove material`: **Extrude · Cut** is first. Try `pocket`, `round`, `spline` (it shows *Start or edit a sketch first*) and `undo` (it shows *Ctrl+Z*). If you rebind Extrude under **Help → Shortcuts**, search shows the new key.
3. Pad a block. Sketch a small rectangle on its top face; the region shows a light translucent tint and you can still see the face. Orbit underneath: the tint is hidden by the solid. Zoom in and out: no flicker.
4. Select the sketch, search `cut` and press Enter. Extrude opens in **Cut**, and the preview removes material. Switch Operation to **Add**: the preview goes outward. Confirm in Cut: a native Pocket is created, and one Ctrl+Z removes it.
5. Repeat on a bottom face and a side face, and with **Extrude** on a selected face. Tick **Reverse** and then switch Add↔Cut: the Reverse choice stays.
6. Reopen an existing Pad, Pocket and Studio feature by double-click. Their settings and limits are unchanged.
7. Run the automated checks:

```powershell
.\run-checks.ps1
.\tools\run_gui_recipe.ps1 -Recipe everyday-ui
.\tools\run_gui_recipe.ps1 -Recipe sketch-regions
.\tools\run_gui_recipe.ps1 -Recipe extrusion-edit
.\tools\run_gui_recipe.ps1 -Recipe history-lifecycle
.\tools\run_gui_recipe.ps1 -Recipe parameter-panel
.\tools\run_gui_recipe.ps1 -Recipe parameter-panel-reopen -SeedUserConfig <user-data\user.cfg of the parameter-panel run>
```
