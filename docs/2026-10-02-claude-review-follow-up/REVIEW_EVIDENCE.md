# Evidence for the October 2 review follow-up

Prepared October 2, 2026, America/Los_Angeles. Scope: read Claude's review, the current controller/bridge/UI/clipboard/routing paths, relevant tests, product/design and M1/foundation contracts/plans, and associated recorded validation results. No app changes, Git initialization, full test rerun, user-window interaction, source conversion or message to Claude occurred.

## Current source findings

Line references are to the unmodified app read for this assessment; use the surrounding function names after changes.

| Finding | Evidence |
|---|---|
| Heavy idle inspect | `src/kurtshape/ui.py` 83–85, 345–368; `core.py` 198–226, 340–368. `dispatch(inspect)` reaches `sync` twice. Each calls `_build_status`; measurements and the final build-error check each call validity again. A current solid therefore has four validity calls and two full intent-signature walks per tick. This is a code-derived count, not an instrumented timing result. |
| Failed Finish destroys draft | `core.py` 455–481 and 534–550; `ui.py` 729–745. Exception handling restores the pre-edit snapshot and removes the lease, which the GUI needs to reopen the sketch. Tests at `test_sketch_planes.py` 184–194 and 256–273 explicitly expect rollback after failed Finish. |
| Failed typed operation can destroy earlier draft | `core.py` 482–498 and 535–539 share the whole-lease rollback catch. This must be distinguished from rolling back only the rejected command. |
| Storage and startup restrictions | `core.py` 17, 38–46; `ui.py` 601–630, 1135–1141; `launch-kurtshape.ps1`. Product writes are restricted to Codex and normal launch clears `KURTSHAPE_NO_DEMO`. |
| Dimension limitations | `ui.py` 142–150, 572–584; `core.py` 28–35, 804–826. Value suffix is selected from parameter units, so it is not always mm; quantities/formulas are still unsupported by these numeric controls/requests. |
| Paste bypass | `general_actions.py` 137–196 owns its transaction, busy flag and private build checks. Native shallow-copy behavior is documented in `docs/general-actions-compatibility.md`. |
| Observer already exists | `general_actions.py` 23–55 registers activation/deletion callbacks. It does not supply intent/recompute/transaction invalidation. |
| Snapshot clock | `core.py` 219–246, 560–565: synchronization/new revisions record changed sketch buffers; the timer's inspect determines observed native edit boundaries. |
| Body/adoption limitations | `core.py` 400–408, 575–638, 701–734, 773–803, 875–889; literal Body resolution, metadata-required open and Body-only export are present. |
| Shortcut overrides and Git | `shortcuts.py` 38–52 loads one registry. The registry has 35 entries marked unsupported, spanning different workspaces. `git -C Codex/kurtshape rev-parse --show-toplevel` reports no repository; no `.git` directory was found at app/Codex/workspace roots. |
| Autosave unknown | No `AutoSave`, `SaveBackup`, `Recovery` or `TempPath` matches in the inspected normal/integrated-validation `user.cfg` files; `AutoSave` also absent from the inspected sketch-lifecycle config. Absence does not establish native defaults. |

## Existing recorded evidence, not rerun here

- `validation/foundation-probe/result.json`: FreeCAD 1.1.4, revision `4fd3bf320d9566a27e60069fc8387448aaa3a094`, OCCT 7.8.1; 2.62447-second overall foundation proof.
- `validation/offline-test-result.json`: 47 passing tests, 5.23406 seconds; Python networking denied, physical disconnection/native C++ interception untested.
- `validation/live-bridge-result.json`: one plate edit round trip 31.16 ms; stale replay/native undo/authentication rejection passed; actual Claude client not exercised.
- `docs/M1_PROGRESS.md` and `docs/M1_ACCEPTANCE.md`: both real STEP references contain three valid solids; the 145 hub features are a static source count across branches. Real editable conversion remains 0/2 and edited reference variants were deferred by Kurt.

## Probe run for this assessment

Executed the bundled `runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin/python.exe -B -` with a script importing `FreeCAD`, reporting `App.Version()[:3]`, and calling `App.Units.Quantity(text)` for the inputs below. The script created no document and saved no configuration or output files.

| Input | Observed result in FreeCAD 1.1.4 |
|---|---|
| `1/8 in` | Value 3.175, length unit mm |
| `0.25 in` | Value 6.35, length unit mm |
| `12.7/2` | Value 6.35, dimensionless |
| `Width/2` | `syntax error` without document context |
| `30 deg` | Value 30, angle unit deg |
| `1 rad` | Value 57.29577951308232, angle unit deg |
| `2 s` | Value 2, time unit s; parsing alone does not enforce a length field's type |

Reproduce each row with `App.Units.Quantity(text)` and inspect `.Value` and `.Unit`. This tests the quantity parser only, not the GUI widget, bound-expression editor or complete new parameter operation.

Installed upstream evidence: `Mod/Fem/Resources/ui/ConstraintTie.ui` uses `Gui::QuantitySpinBox`; `Mod/Fem/femtaskpanels/task_constraint_tie.py` 107 explicitly creates an `ExpressionBinding(...).bind(self.obj, "Tolerance")`. These support probing the bound-widget behavior rather than assuming widget substitution completes formula handling.

The pinned [FreeCAD 1.1.4 observer source](https://raw.githubusercontent.com/FreeCAD/FreeCAD/1.1.4/src/App/DocumentObserverPython.cpp) exposes change, recompute, lifecycle and transaction callbacks. [Official expression documentation](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Expressions.md) describes property-bound expression inputs. Version-tagged widget/autosave sources could not be retrieved through the browser tool; no unverified source-default claim is made from those failed lookups.

## Still to verify during implementation

Observer completeness and callback ordering; shape cache invalidation; native widget staging versus direct mutation; full lease recovery after failed grouping; preview isolation; actual native autosave/recovery location and active-sketch survival; interaction/recompute timing; both-client parity; real-part conversion/reference gates. Proposed thresholds and workflows in the plan remain proposals until demonstrated.
