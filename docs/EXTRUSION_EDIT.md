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
- **Preview:** the exact preview runs the same `edit_extrusion` operation on a disposable clone in the existing preview worker. It shows the changed region at the edited feature's own history step, drawn through the live model, which stays unchanged. The status line reports the resulting part-volume change. For an **edit**, Confirm is enabled only for a current, valid exact result (the evaluator has no provisional result for an edit). For **creation** (Extrude / Remove material from a sketch, Blind) Confirm no longer waits for the exact preview; see "Confirm gate" below.
- **Confirm / Enter:** commits one undo step. The feature name, history position, attached sketches and downstream features are preserved, and later features rebuild. With no changes, Confirm closes without touching the model.
- **Cancel / Escape:** closes with the accepted model, revision and history untouched. A failed preview or failed commit leaves the dialog open with the error, and the model unchanged.
- **Untouched values are never resent:** the dialog sends a depth only after you change the field by typing, arrow keys, spin buttons or the mouse wheel. Displayed text is never treated as authoritative. A depth the widget must round, such as 6.123456 mm, is kept exactly; the dialog's context line and the depth tooltip state the exact value. Direction-only edits and clearing a formula leave the native depth unchanged. Clearing keeps the formula's last evaluated value.
- **Open profiles:** a profile without any closed loop now fails immediately with `open_profile`, and the message lists free endpoints in sketch coordinates, for example `(0, 0); (10, 5) mm`. Coordinates are local to the sketch, even inside a moved or rotated Body. Endpoints are found topologically, so a near-miss closure such as `(0, 0.0000004)` is still reported. A profile that mixes closed and open curves keeps native behavior. When the native build fails on it, the same endpoint diagnostic replaces the generic error.
- **Studio Remove direction fix:** in a Part Studio, **Reverse direction** on a Blind Remove material previously had no effect, because both states cut into the material. Unchecked now cuts into the material and checked cuts the opposite way, matching legacy Remove.

## Confirm gate

The rule is one pure function, `src/kurtshape/confirm_gate.py`, shared by the dialog's button state and the preview adapter's `flush` / `current_result`:

    Confirm enabled  <=>  (an exact result exists for the current normalized fields and is valid)
                          or (provisional acceptance is allowed for this task,
                              no exact or commit rejection is remembered for the current fields,
                              a provisional result exists for them, and it carries a mesh)

- **Where a provisional result may commit** (`confirm_gate.provisional_allowed`): only where the operation validates the geometry itself, so that a commit from a provisional preview can never silently produce a no-op or an invalid solid. That is a **Part Studio** operation (Add / Remove / Intersect run the result checks: `empty_add`, `empty_cut`, `invalid_geometry`, `build_failed`) a **legacy Remove material** (the native pocket requires removed material: `empty_cut`) and, since slice A/B U9, a **legacy Extrude** (the native pad must add material: a pad fully inside existing material is rejected with `empty_add` instead of committing as a no-op). So every new Extrude / Remove task qualifies; edits keep the exact gate. The committed solid uses the same normalized proposal the exact preview evaluates, so where the commit succeeds it equals the exact preview's result.
- **Reach, in user terms.** Every new **Extrude** and **Remove material** with a blind depth commits from the provisional, on any document. On a document that is not yet a Part Studio, a Remove without **Reverse direction** ticked has no provisional result, so it waits for the exact preview; an Extrude that would only fill existing material is rejected when you confirm (`empty_add`, the dialog stays open and remembers it). With the Operation set or the merge scope explicit, the request carries `operation` / `merge_scope` and the controller runs it as a Part Studio operation with the result checks. A queued Confirm (see below) commits the fields that are current when it resumes.
- **Creation where allowed**: the provisional preview appears synchronously when you type, and Confirm (header button, **Enter**, **Shift+Enter**) commits at once. The exact preview keeps running as an advisory: when it arrives valid it refines the ghost and the status; when it arrives *invalid* for the current fields (for example a Remove that removes nothing) it disables Confirm with its error, because a commit known to fail is not offered. Confirm discards the in-flight exact evaluation before the commit (`operation()` clears the preview and closes its worker), so a late result cannot paint a ghost over the committed feature.
- **Remembered rejections**: an exact rejection of the current fields, and a commit the operation rejected, stay on those fields (error in the status line, Confirm disabled) until the fields change or the task restarts; pressing Enter or Confirm again does not re-offer them. Worker, transport and revision failures are not remembered, so the same fields are retried.
- **Exact-only cases**: an edit (`edit_extrusion`), **Up to face**, **Through all**, a face extrusion, and a legacy Remove with no direction set wait for the exact result as before (none of them produces a provisional result).
- **Failed commits** (`empty_cut`, `empty_add`, `build_failed`, `stale_revision`, …) keep the dialog open with the error and restart the preview, as before, with the rejection remembered as above. A provisional commit is still checked against the live revision the dialog is working on (`expected_revision` is the preview's base revision).
- **Confirm during the preview snapshot**: the first exact evaluation of a task snapshots the document (`saveCopy`, 0.4–0.8 s on plate60), which pumps Qt. A Confirm / Enter / Shift+Enter delivered inside that window is queued ("Confirm queued · committing after the preview snapshot…") and commits once the snapshot releases the document, with the fields current at that moment; it is never dropped and never clears the preview. The queue applies only where the task can commit from a provisional (or Confirm is already enabled); otherwise the click behaves as before.
- Status text while a provisional may commit: "Provisional preview · Confirm commits now; exact check running…"; where it may not: "Provisional preview · checking exact result…".

Gate record (slice A/B, U1): `tools\run_gui_recipe.ps1 -Recipe confirm-gating -Holes 60` on plate60 measures Confirm-click to `pocket` dispatch for a legacy Remove (shell latency, under 100 ms), click to the new history row (kernel-bound), the exact-preview wait that is no longer imposed, and committed-versus-exact volume (1e-6 mm³); it also checks that a legacy Extrude commits from its provisional and that a legacy Extrude inside material is rejected at commit with `empty_add` (slice A/B U9; until then it stayed exact-only), that a Part Studio Extrude commits from its provisional and that an inside-material Add is rejected, Enter and Shift+Enter, a Confirm inside the snapshot window, and remembered rejections. `tests/test_confirm_gating.py` covers the rule headlessly.

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
- **Signed depth formulas** are kept as written. A formula that evaluates negative, such as `-2 mm` on a Part Studio extrusion, makes the solid extend opposite its direction setting. The dialog's direction line reports the actual direction and the end-condition tooltip explains why. The numeric depth field still accepts only positive values.
- **Up to face in a transformed Body:** the provisional/exact creation preview can be inaccurate for Up to face in a moved or rotated Body. This was observed in an ordinary creation-preview control during review; it is not specific to editing. The broader investigation is deferred.
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
- A Remove that would remove nothing rejects with `empty_cut`. Since contract 3.2 (OPERATION_CONTRACT §3.2.1) every edit of a studio Add/Remove/Intersect runs the 3.1 result post-conditions on the edited operation and on every downstream result operation it affects, at their own history positions; a failure rejects with the creation code (`empty_add`, `empty_cut`, `invalid_geometry`, `build_failed`), `feature` naming the failing operation, `validation:"history"` and `trigger`. The own-tip pre-check of this operation stays in place (it also covers automatic merge scopes, which the native gate would otherwise report as `build_failed`); the live GUI preview runs only the own-tip checks.
- The operation is also accepted by `preview`.
- Failures abort the transaction and keep the accepted revision.

## Walkthrough (Windows GUI)

Use a disposable copy of any model. Save and close running KurtShape windows first; already-running processes keep the code they loaded.

1. `git fetch origin` and `git switch claude/sleepy-euler-3jjcom` in a separate checkout or worktree, then run `.\launch-kurtshape.ps1` (or double-click `KurtShape.cmd`).
2. Sketch a rectangle on **Top**, **Finish**, then **Extrude** 6 mm. This walkthrough document is a legacy (non-Part-Studio) document, so this Extrude waits for the exact preview before Confirm is enabled (see "Confirm gate"); a **Remove material** with **Reverse direction** ticked would commit from the provisional. Sketch a circle on the top face and use **Remove material → Through all** (Through all has no provisional result, so Confirm waits for the exact preview).
3. **Double-click the Extrude row.** Expect:
   - a dialog titled with the feature name;
   - Depth `6 mm`, End condition **Blind** (other ends disabled), Operation locked;
   - "No changes" in the status line.
4. Type `10` in Depth. Expect a blue preview of the added slab, with the live solid unchanged and the status "Preview · edited … part volume +…". Press **Enter**. The block is now 10 mm, the circle sketch has moved up with the face, and one **Ctrl+Z** restores 6 mm.
5. Reopen the Extrude and type `BaseProfile.Constraints.Width / 4` into **Formula**, using your rectangle sketch's name and dimension. Depth greys out and the preview updates. **Confirm.** Reopen: the formula is shown and Depth shows the evaluated value.
6. Reopen it, tick **Reverse direction**, wait for the exact preview (edits keep the exact-only gate), then press **Cancel**. Nothing changes, and Undo history is unaffected.
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
.\tools\run_gui_recipe.ps1 -Recipe extrusion-edit   # hidden GUI: real dialog, 43 checks
.\tools\run_gui_recipe.ps1 -Recipe confirm-gating -Holes 60   # hidden GUI: immediate Confirm gate on plate60
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

### Correction pass (2026-10-14, cloud session, same Linux engine)

These fixes follow Codex's Windows review of `7d1c56a`. Codex reported 489 tests passing with 4 opt-in performance skips, and 31/31 GUI checks.
- Untouched depths are never resent.
- Open-profile endpoints are found without rounding and reported in sketch coordinates.
- Signed formula depths report their actual direction.
- The GUI recipe now fails if the required Save fails.

| Check (fresh, cloud) | Result |
|---|---|
| `test_extrusion_edit` | 11/11 pass. The 2 new cases (near-closed and transformed-Body open profiles; signed formula direction) fail on `7d1c56a`. |
| Native suite (runner) | 429 pass, 7 skip, 5 fail. The failures are the same environmental `test_native_files` Windows-path assertions as before. |
| Bridge / shortcuts / workflows | 19/19, 29/29, 6/6 (415 workflow checks) |
| `extrusion-edit` GUI recipe | 43/43 pass. Against `7d1c56a`'s `ui.py` it fails at "Untouched reopen reports no changes" (6.123456 mm). |
| Lint (`ruff 0.16.10`) | the 16 pre-existing findings are unchanged; no new ones |

**Windows GUI acceptance of this correction pass has not been run.**
