# Reopen and edit Extrude / Remove material

Milestone 1 of the focused improvement plan: existing Extrude and Remove material features reopen in the same feature dialog used to create them. The dialog shows current native settings, previews the edit exactly, and commits through the controller's usual revision-checked transaction.

## What works

- **Reopen:** double-click an Extrude or Remove row in the feature history, choose **Edit Extrude / Edit Remove material** from its context menu, or press **Edit feature** in its settings panel. The dialog title is the feature name. Its first line names the profile, the feature kind and the current physical direction, for example "along the sketch normal".
- **Current values:** depth, depth formula, direction and end condition come from native properties. `KurtShapeStudioOperation` only identifies the feature family. It records the original request, so values changed later through **Apply dimension**, a formula or an upstream edit are what the dialog shows.
- **Editable:**
  - Depth, entered as a quantity such as `1/2 in` or `12.7/2`.
  - Depth formula, using the same rules as **Apply dimension**. A formula disables the numeric depth; clear it to type a value.
  - Reverse direction, where a direction applies.
  - End condition **Blind ↔ Through all** for a native Remove material (PartDesign Pocket). The unused Blind depth remains native, so switching back restores it.
- **Preview:** the exact preview runs the same `edit_extrusion` operation on a disposable clone in the existing preview worker. It shows the changed region at the edited feature's own history step, drawn through the live model, which stays unchanged. The status line reports the resulting part-volume change. Confirm is enabled only for a current, valid exact result; acceptance behavior is unchanged.
- **Confirm / Enter:** commits one undo step. The feature name, history position, attached sketches and downstream features are preserved, and later features rebuild. With no changes, Confirm closes without touching the model.
- **Cancel / Escape:** closes with the accepted model, revision and history untouched. A failed preview or failed commit leaves the dialog open with the error, and the model unchanged.
- **Open profiles:** a profile without any closed loop now fails immediately with `open_profile`, and the message lists free endpoints in sketch coordinates, for example `(0, 0); (10, 5) mm`. A profile that mixes closed and open curves keeps native behavior. When the native build fails on it, the same endpoint diagnostic replaces the generic error.
- **Studio Remove direction fix:** in a Part Studio, **Reverse direction** on a Blind Remove material previously had no effect, because both states cut into the material. Unchecked now cuts into the material and checked cuts the opposite way, matching legacy Remove.

## Supported features

| Feature | Depth / formula | Direction | End condition change |
|---|---|---|---|
| Native Extrude (PartDesign Pad, Blind) | Yes | Yes | No (Blind only) |
| Native Remove (PartDesign Pocket, Blind / Through all) | Yes (Blind) | Yes | Blind ↔ Through all |
| Native Up to face (Pad / Pocket) | No depth | Yes | No |
| Studio Extrude / Remove (New, Add, Remove, Intersect; sketch or face) | Yes (Blind) | Yes | No |
| Studio Through all | No depth | No: extends both ways | No |
| Studio Up to face | No depth | Yes | No |

A native Midplane (symmetric) extrusion edits its depth with direction locked. Features outside this table, such as native Two lengths or Up to first, open the earlier settings panel unchanged. Revolve, Sweep and other features keep their existing behavior.

## Limitations

- No end-condition change for Part Studio features. Studio Through all is a two-sided extrusion sized from scope bounds, and Up to face uses a separate carrier body, so switching requires rebuilding the feature graph. The dialog shows the end condition read-only with that reason, and the controller rejects the change with `unsupported_transition`.
- No switch to **Up to face** while editing, and no change of result operation, merge scope or profile.
- **Reverse direction** means "opposite this feature's default direction", where the default is what creation does when Reverse is unchecked. A legacy Remove that was created unchecked but automatically flipped to find material reopens as reversed; the direction line states the actual direction. A Studio Remove created through the API with `reversed:false` also reopens as reversed.
- The general **Apply dimension** panel still lists a Studio Through all's computed length as a formula-driven "Length". Use the Edit dialog for these features.

## Controller operation

Contract 3.0 gains one additive typed mutation:

```json
{"op": "edit_extrusion", "document_id": "...", "expected_revision": "...", "feature": "Cut",
 "length": "2 mm", "expression": null, "reversed": true, "end_type": "blind"}
```

- Every field except `feature` is optional, and only supplied fields change.
- `expression` sets a depth formula; `null` clears it.
- A numeric `length` on a formula-driven depth rejects with `expression_driven`. No formula is ever dropped implicitly.
- Unsupported end transitions reject with `unsupported_transition`, and a direction change that is not available rejects with `unsupported_parameter`.
- A Remove that would remove nothing rejects with `empty_cut`.
- The operation is also accepted by `preview`.
- Failures abort the transaction and keep the accepted revision.

## Walkthrough (Windows GUI)

Use a disposable copy of any model. Save and close running KurtShape windows first; already-running processes keep the code they loaded.

1. `git fetch origin` and `git switch claude/sleepy-euler-3jjcom` in a separate checkout or worktree, then run `.\launch-kurtshape.ps1` (or double-click `KurtShape.cmd`).
2. Sketch a rectangle on **Top**, **Finish**, then **Extrude** 6 mm. Sketch a circle on the top face and use **Remove material → Through all**.
3. **Double-click the Extrude row.** Expect:
   - a dialog titled with the feature name;
   - Depth `6 mm`, End condition **Blind** (other ends disabled), Operation locked;
   - "No changes" in the status line.
4. Type `10` in Depth. Expect a blue preview of the added slab, with the live solid unchanged and the status "Preview · edited … part volume +…". Press **Enter**. The block is now 10 mm, the circle sketch has moved up with the face, and one **Ctrl+Z** restores 6 mm.
5. Reopen the Extrude and type `BaseProfile.Constraints.Width / 4` into **Formula**, using your rectangle sketch's name and dimension. Depth greys out and the preview updates. **Confirm.** Reopen: the formula is shown and Depth shows the evaluated value.
6. Reopen it, tick **Reverse direction**, wait for the preview, then press **Cancel**. Nothing changes, and Undo history is unaffected.
7. Double-click the Remove row. Switch End condition to **Blind**, type `2`, and press **Enter**. The hole is now 2 mm deep. **Ctrl+Z** restores Through all, and **Ctrl+Y** reapplies.
8. Reopen the Remove and tick **Reverse direction**. The preview reports that no material is removed, and Confirm stays disabled. Cancel.
9. Right-click either row: **Edit Extrude / Edit Remove material** appears in place of the native "Edit feature".
10. **Ctrl+S** to a scratch folder, close the document, reopen it, and double-click the Extrude. The formula is still shown.
11. Optional Part Studio check: create a part, then a Blind **Remove material** with Operation **Remove**. Reverse now flips the cut, and the reopened dialog shows the native depth and direction. On a Through all Remove, Reverse and End condition are locked, with the reason in the tooltip.
12. Optional open-profile check: draw two connected lines that do not close and choose **Extrude**. The status lists both free endpoints.

## Validation

Automated checks:

```powershell
.\run-checks.ps1                                    # all native/bridge/shortcut/workflow suites
.\tools\run_gui_recipe.ps1 -Recipe extrusion-edit   # hidden GUI: real dialog, 31 checks
```

`tests/test_extrusion_edit.py` covers:

- current native values versus the stored creation request;
- single-step Undo/Redo;
- failed, unsupported and stale edits preserving intent, revision and history;
- formula protection;
- downstream attached sketches and save/reopen;
- Studio upstream edits after later operations consumed the output;
- exact-preview agreement with acceptance;
- open-profile endpoints.

The GUI recipe drives the actual history double-click, typed fields, Confirm, Cancel, Enter and the context menu.

### Recorded results (2026-10-13, cloud implementation session)

These results come from a Linux cloud container running the official FreeCAD 1.1.4 / OCCT 7.8.1 Linux AppImage, which is the same engine version as the pinned Windows runtime. They are fresh runs of this branch, not retained evidence. **Windows GUI acceptance has not been performed.**

| Check | Result |
|---|---|
| `test_extrusion_edit` (new) | 9/9 pass |
| Native suite (runner) | 427 pass, 7 skip (3 external examples absent, 4 opt-in perf), 5 fail. All 5 failures are `test_native_files` assertions that the runtime lives at the Windows `runtime/freecad-1.1.4/…py311` path, which is environmental on Linux. |
| Bridge / shortcuts / workflows | 19/19, 29/29, 6/6 (415 workflow checks) |
| `extrusion-edit` GUI recipe (Xvfb, hidden window) | 31/31 checks pass |
| Lint (`ruff 0.16.10`) | no new findings; the 16 pre-existing ones are unchanged |

Linux-only harness accommodations, none of them in the repository:
- Python safe-path mode.
- A `python.exe` symlink.
- `PYTHONPATH` for worker processes.
- A guard on two GUI observers that read a view provider's `Object` before FreeCAD binds it. On the Linux build that read segfaults at startup, on unchanged baseline code too.
