# Predictable history and clean operation lifecycles

This milestone covers four behaviors in the feature history:
1. Finishing a new sketch is one Undo step.
2. Deleting a Studio operation also deletes the helper objects it created.
3. While history is rolled back, new work models only the active state.
4. Rolling history back with the pointer requires a deliberate drag of the boundary marker.

## 1. Sketch Undo/Redo

- **While editing a sketch:** Ctrl+Z / Ctrl+Y step through individual drawing and constraint actions, as before.
- **After Finish on a newly created sketch:** one Undo removes the whole sketch, and one Redo restores it with its support, attachment and geometry. This also applies when Extrude finishes the sketch implicitly: Undo removes the extrusion, and the next Undo removes the sketch.
- **Finishing edits to an existing sketch:** produces one undoable edit and never deletes the sketch.
- **Unchanged:** Cancel, failed-Finish draft recovery, recovered unfinished sketches and earlier history.

How it works:
- Native FreeCAD history still records two transactions: `KurtShape: create_sketch`, then `KurtShape: new sketch contents <label>`.
- The controller's Undo/Redo treats that adjacent pair as one step. The pairing applies only when the edit lease began immediately after that sketch's creation: same revision, same undo depth, no Redo stack. Otherwise the creation and the edit stay separate steps.
- Cancel on a new sketch keeps the existing behavior: the empty sketch remains, and one Undo removes it.

## 2. Operation helper lifecycle

**Root cause.** Codex found 13 helpers tagged `KurtShapeOperationOwner = Extrude3` with no `Extrude3`. I tested creation, rejection, Undo and deletion on a synthetic equivalent:
- Undo of a Studio operation and rejected creations leave nothing behind.
- Deleting a Studio Add/Remove operation's history row removed only its representative Boolean. Every helper stayed behind, including the `…ToolProfile` binder that still references the sketch. Deleting the sketch then failed with `external_dependency`, exactly as in the saved file.

**Second defect.** `studio._record` also re-tagged shared inputs as owned by the new operation, for example a previous part's `FeatureBase`. A tag-based cleanup could therefore have removed part of a surviving part.

Fixes:
- **Deletion.** Deleting a Studio operation removes its whole operation closure in one undoable transaction. If anything outside the closure still uses it, such as a later operation, the deletion is rejected and nothing changes. The deletion plan reports the removed helpers separately (`helpers`).
- **Ownership tagging.** New operations no longer take over objects owned by another Studio operation, or objects inside another operation's Body. Helpers an operation places in a user Body, such as a revolve axis datum, are still owned by it.
- **Existing files.**
  - Opening a file only *reports* leftover helpers: "Menu → Repair leftover helpers".
  - The read-only `orphan_helpers` operation lists each group's objects, consumers and kept inputs.
  - The explicit `repair_orphan_helpers` operation removes only groups that nothing surviving uses, in one undoable transaction. It returns a report of removed objects, kept inputs and skipped groups.
  - Groups that are still consumed are never removed, and requesting them explicitly is rejected (`orphan_has_consumers`).
  - Objects that were mis-tagged into a group but sit inside another operation's Body are treated as shared inputs and kept.
  - Deleting a sketch that leftover helpers still reference now explains this (`orphan_helpers`) instead of failing generically.

## 3. Modeling while history is rolled back

**Root cause.** A Body whose part exists only beyond the rollback bar has no solid at the bar, so it looked like an "empty" part:
- The GUI offered it as the active part, and new sketches were created inside it.
- Extrude then defaulted to New instead of Add.
- A New result adopted the future part's identity, so rolling forward produced two generations of one part.
- The previews themselves were already bar-aware, because current parts, results and auto scope all use the rollback cutoff.

Fixes:
- `studio.held_bodies(doc)` identifies held parts.
- The controller rejects new sketches in them (`held_part`).
- New results never adopt a held part's identity.
- The GUI part chooser excludes held parts.

Tested end to end:
- The in-process exact preview and the worker-process exact preview both model only the active state.
- Auto scope excludes held parts, and a stale task rejects after a rollback change.
- Cancel keeps the boundary, Confirm inserts at the bar, and rolling forward rebuilds.

## 4. Rollback gestures

Only dragging the boundary marker itself moves history, and the pointer must travel at least the platform drag distance. These no longer roll history back:
- clicking row gaps;
- selecting or double-clicking rows;
- scrolling;
- tiny pointer movements.

Escape cancels a drag in progress, and its release commits nothing. Context-menu rollback and keyboard Up/Down on a focused marker are unchanged.

## Limitations

- **The original `test-261014.FCStd` was not accessible in the cloud session.** Saved-file verification is pending on Windows. Synthetic fixtures reproduce its state: an operation whose representative was deleted, 13 remaining tagged helpers, and an unreferenced sketch blocked by the leftover `…ToolProfile` binder.
- **Cancel on a newly created sketch still leaves an empty sketch.** One Undo removes it. Removing it automatically on Cancel was not requested.
- **Deleting a Studio operation that later operations consume is still rejected.** Delete-and-keep-broken-history behavior is out of scope.
- **Native FreeCAD Undo outside KurtShape**, such as a Python console call, still sees two transactions for a new sketch.
- **The existing `rollback-history` GUI recipe** was updated from gap clicks to marker drags, because a plain gap click intentionally no longer rolls back. It crashes during setup in the Linux cloud harness on both baseline and this branch, so it needs the Windows run.

## Windows walkthrough

Use a disposable copy of any model.

1. Launch with `.\launch-kurtshape.ps1` from this branch.
2. Sketch a rectangle (**Shift+S**, Top, **G**) and draw a few lines, then **Ctrl+Z** once: one line disappears. Press **Ctrl+Y**, then **Confirm**. One **Ctrl+Z** removes the whole sketch, and one **Ctrl+Y** restores it.
3. Double-click the sketch, add a line and Confirm. **Ctrl+Z** removes only that line, never the sketch.
4. Start a new sketch, draw a closed profile and press **Shift+E** without finishing. Extrude and Confirm. **Ctrl+Z** twice removes the extrusion, then the whole sketch.
5. Create a Part Studio Remove: a circle sketch, then **Remove material** with **Operation → Remove**. Delete the Remove row, then delete its circle sketch; both succeed. **Ctrl+Z** restores everything.
6. Saved-file check on a copy of `test-261014.FCStd`:
   - On open, Messages reports leftover helpers from `Extrude3`.
   - **Menu → Repair leftover helpers** lists 13 objects and `Sketch3` as a kept input.
   - Confirm, then delete `Sketch3`; it succeeds.
   - **Ctrl+Z** twice restores the sketch and the helpers.
7. Create two parts. Drag the blue rollback marker above the second part.
   - The part chooser no longer offers the held part.
   - A new sketch overlapping both parts extrudes as **Add** to the first part, and the preview ignores the held part.
   - Cancel keeps the marker in place. Confirm inserts the extrusion there. Dragging the marker to the end rebuilds both parts.
8. Click between rows, click and double-click rows, scroll the history, and nudge the marker by 1–2 px: none of these rolls back. Start a marker drag and press **Escape**: the marker returns and nothing is committed.
9. Run the automated checks:

```powershell
.\run-checks.ps1
.\tools\run_gui_recipe.ps1 -Recipe history-lifecycle
.\tools\run_gui_recipe.ps1 -Recipe rollback-history
.\tools\run_gui_recipe.ps1 -Recipe extrusion-edit
```

## Recorded results (2026-10-14, Linux cloud session, FreeCAD 1.1.4 / OCCT 7.8.1 AppImage)

**Windows has not been tested.**

| Check | Result |
|---|---|
| `test_history_lifecycle` (new, 9 cases) | 9/9 pass. On `37d4eb2` product code, 8/9 fail; several of those fail on missing APIs rather than behavior. |
| Native suite (runner) | 438 pass, 7 skip, 5 fail. All 5 failures are the environmental `test_native_files` Windows-path assertions. |
| Bridge / shortcuts / workflows | 19/19, 29/29, 6/6 (415 workflow checks) |
| `history-lifecycle` GUI recipe (Xvfb) | 26/26. On `37d4eb2` it fails at "One Ctrl+Z after Finish removes the whole new sketch". |
| `extrusion-edit` GUI recipe | 43/43 |
| `rollback-history` GUI recipe | Not run to completion: it segfaults during setup in this harness on both baseline and branch |
| Lint (`ruff 0.16.10`) | the 16 pre-existing findings are unchanged |

**Updated existing tests.** Three existing tests asserted the old two-step new-sketch Undo, where Undo after Finish left an empty sketch. They now assert the one-step contract and still check prior history, grouping and Redo:
- `test_sketch_planes` (two tests);
- `test_part_studio.test_use_sketch_edit_groups_helper_creation_and_restores_undo_redo`.

One deletion-plan assertion gained the new `helpers` key.
