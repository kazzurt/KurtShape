# Assembly & selection UX program — status

Branch `claude/assembly-ux` (worktree `Codex\ksasm`, from `claude/slice-ab` 455e6cb).
Engine via junction `runtime\freecad-1.1.4` → main checkout. Evidence: `validation/assembly-ux/`.
Running cost: the driver's per-session figure is not visible to the agent; rows say "n/a".

## Hands-on checklist for Kurt

(written at item 9)

## Items

| # | Item | Changed | Verified | Try after restart | Open questions |
|---|---|---|---|---|---|
| 0 | Copy refresh work from main tree (commit 1) | `assembly_refresh.py`, `part_inventory.py`, `assembly_persistence.py`, their tests, `COMPONENT_REFRESH.md`, `assembly-refresh-gui-probe.FCMacro` copied unmodified from the main checkout's uncommitted state (HEAD 455e6cb + working tree, files dated 2026-10-21); minimal hunks in `core.py` (ops, args, refresh transaction/rollback, `save_native_copy` at core's 5 saveCopy sites), `assembly.py` (`is_embedded_source`, `candidates(final_only)`), `operation_schemas.py` (3 entries; `part_inventory` excluded from `detail`), `run_native_tests.py`; schema-test probes for `final_only`/`include_history` from the same tree; `OPERATIONS.md` regenerated; two contract rows | `test_assembly_refresh`, `test_assembly_persistence`, `test_assembly` (35/35), `test_operation_schemas`, `test_operations_doc` (30/30) | nothing visible yet | One copied test adapted: `test_managed_save_failure_…` now passes `overwrite=True`, because slice-ab's A8 guard refuses a non-project destination before the seal runs (intent unchanged). `recovery.py`/`extrusion_preview.py` still use plain `saveCopy` (not in the allowed hunk list); recovery archives are therefore not sealed on this branch. |
| 1 | Additive click selection | new `selection_mode.py` (app-wide Qt filter on each viewer's QOpenGLWidget: a plain left click that hits geometry is re-sent with Ctrl, which the native unified selection already treats as add/remove toggle; empty-space clicks stay plain → native clear); `ui.py` (+3 lines: install, shutdown, joint-dialog text); `workspace_preferences.py` (Settings → Selection → "Click adds to selection", pref `AdditiveSelection`, default on); `hover_outline.py` (selected face hovers orange = click removes); `EVERYDAY_UI.md`, `WORKFLOW.md`; recipe `additive-selection` | `test_selection_mode.SelectionModeTests` (6); recipe `additive-selection` on a private desktop: saved part and saved assembly, two plain clicks add, third removes, Ctrl alias, empty clears, Space clears, off-switch, untouched in sketch edit (`validation/assembly-ux/additive-selection/`); `view-interaction`, `surface-snap`, `test_shortcuts`, `test_private_desktop` still pass | Click two faces: both stay selected; click one again: it drops; hover a selected face: orange outline; click background or Space: clears. Settings → untick "Click adds to selection" to get the old behaviour | **Deviation:** the suggested Coin callback does not work — in FreeCAD 1.1.4 the callback sees only the press and a handled press still lets the native replace-selection run (measured, run 26e3e3b0…). Joint dialog is excluded while it is open; its fields pick references explicitly. |
