# Shared checkout coordination

October 2, 2026, America/Los_Angeles. The assembly conversation works in the same local checkout as the originating conversation's separately authorized modeling/UI refinement. Both preserve the open user application and original sources.

## Assembly ownership while implementation is active

- Assembly controller owner: `src/kurtshape/core.py` operation sets/argument whitelist, dispatch, assembly inspection/build checks, reopen and occurrence export; `bodies.py` occurrence traversal and `document_state.py` placement cache invalidation.
- Assembly UI agent: `src/kurtshape/ui.py` Assembly workspace chooser/toolbar, assembly history/selection/context actions, insertion/joint/placement dialogs, assembly shortcut callbacks and availability; `shortcuts.py` and `shortcuts.json` only for implemented context routing.
- Native adapter agent: new `src/kurtshape/assembly.py`, `tools/assembly-native-probe.py`, native API evidence/documentation.
- Validation agent: `tests/test_assembly.py`, `tools/assembly-gui-validation.FCMacro`, `tools/validate_offline.py` assembly registration and `validate-review-gui.ps1` assembly scenario.

Assembly edits are bounded to those integrations. Existing extrusion fields/tasks, theme/popup styling, catalog organization, navigation selector and preview machinery belong to the refinement conversation. It can prepare independent modules and acceptance material now. Avoid concurrent edits to `ui.py` and `core.py` until assembly ownership is released below; inspect the current diff before integrating independent modules. No separate editable model graph or custom assembly solver is introduced.

## Handoff status

Assembly implementation and native/controller/GUI acceptance are complete. **All file ownership is released to the refinement conversation.** Preserve Assembly mode, toolbar, dialogs/history, selection, shared controller/native adapter and callbacks. The Part Studio toolbar, extrusion/editor, naming, popup/theme and navigation-settings regions of `ui.py` were released earlier; their independent changes remain outside this focused commit.

For a focused commit, the assembly-only `ui.py` and `shortcuts.json` snapshot has been staged before releasing the Part Studio regions. Do not stage the whole shared `ui.py` again after unrelated refinements arrive; stage only subsequent assembly-fix hunks. Independent `feature_tools.py`, preview modules/tests and modeling-validation recipes belong to the refinement conversation and must stay outside the assembly commit. No `git add -A` or broad revert/reset is allowed during this shared handoff.

Assembly `ui.py` regions at release: workspace fields in init; workspace selector/Assembly toolbar (approximately lines 283–361); Assembly methods/dialogs (418–749); captured document/revision operation routing (820+); grouped Assembly history (983+); edit guard/bar visibility (1440+); Assembly rename/delete/context menu (1610+); Assembly context/callbacks (1817+). Line numbers will move when the Part Studio regions change; identify methods/conditions, not fixed line ranges.

The refinement work does not replace or interrupt assembly acceptance. The focused commit is titled **Implement native single-level Assembly workflow**; retrieve its exact identity from the local Git log at handoff.

## Controller release after final native acceptance

The final native regression passes 83 offline tests, 4 bridge tests and 22 shortcut tests under the immutable snapshot/solver/transaction fixes. The assembly-only controller, bodies and observer changes were staged before their release. **`core.py`, `bodies.py` and `document_state.py` are released to the refinement conversation**; preserve that Assembly integration when adding preview/modeling changes. Native adapter/probe files are frozen for this increment. The final isolated UI audit fixes are staged independently: native Assembly creation selects the correct workspace, Y/Shift+Y restores occurrence visibility without exposing source storage, and newly rejected shared-client Assembly requests appear once in Messages. Exact replay does not duplicate notification. Final actual GUI acceptance passes 58 checks, including authenticated HTTP requests, plus 4 fresh-process reopen checks against fixture `gui-solved-assembly-40576.FCStd`; the existing STEP GUI passes 19 checks. **All Assembly `ui.py` regions are now released.** No further Assembly source/index changes are planned beyond completing the focused commit.
