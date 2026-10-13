# S19 proposed publication scope

Prepared October 8, 2026 (America/Los_Angeles). This is a **local review proposal**, not a commit, branch creation or publication.

## Target and history boundary

The proposed target is an ordinary reviewed fast-forward of **`main` to `origin` (`https://github.com/kazzurt/KurtShape.git`)**, preserving project history. The observed remote `main` is `d9efdccdb0bad997f6824ba82d6540e4a40a7bd7`; local `main` is `559e034de3522c325423057b048f955405c522af`, has no upstream configured, and is 18 commits ahead / zero behind the remote. The eventual publication would include all 18 existing commits plus an explicitly reviewed new commit, if authorized. No branch, commit, merge, reset, history rewrite or remote write is performed in S19.

An independent read-only review of those 18 commits examined 297 new blob versions across 175 paths and classified them as legitimate KurtShape requirements, implementation, decisions, experiments and validation. The earlier implementation prompt contains project instructions, not a hidden system/developer dump; inspected records contain no unrelated personal or internal instruction-stack material. Confirmed Windows user-machine paths occur in **23 blob versions across 13 paths**, with other operational receipt metadata. A bounded scan found no strong credential signatures, long credential literals or JWTs. These are factual disclosures, not a secrecy guarantee or a reason to rewrite legitimate history merely because a file is a prompt or log.

There are two distinct inventories: **the existing 18 committed project changes relative to remote**, and **the new selected changes relative to local HEAD**, listed below. The preferred review snapshot starts with local HEAD and overlays only the selected current paths. All other tracked HEAD files remain, including historical project records. Leaving unrelated working edits unstaged preserves their existing committed versions in the proposed tip; it does not remove their history. The earlier remote-based curated snapshot is retained only as a comparison artifact and is not the result of a normal commit on current main. No alternate branch or synthetic commit is proposed or created.

Read-only GitHub inspection found no workflow runs for the observed remote tip. Remote compare returned 404; local Git objects establish the ancestry above. This does not establish a passing hosted CI result or current publication readiness.

The existing local Windows workflow is unchanged from HEAD and is part of those 18 commits. If eventually published, its configured push/PR/manual triggers and daily 09:23 UTC schedule would apply. S19 does not change or enable it. The proposal does not sanitize already-published base files: independent review also found user-path patterns in 31 files inherited unchanged from the remote base. The new selected-content scan and the historical-content review have different scopes.

## Exact file scope

The dependency closure contains **245 explicit files**, of which **186 are proposed new-commit changes relative to local HEAD** (144 additions, 42 modifications, zero deletions), comparing Git text after existing line-ending normalization. The other 59 required files already match HEAD. The table below is the complete proposed NEW changed-path list; there is no wildcard staging instruction. Raw working-file hashes are retained separately for native evidence; the eventual committed/checked-out bytes need their own verification.

The application foundation includes all 54 current source modules, 37 test/support files, 74 unchanged baseline SVG icons, the public runner's recipes and their helper imports, pinned launcher/runtime installer/configuration and CI dependencies. Many were pre-existing untracked foundation files; they are required for a complete checkout and are not all new architecture work. The included example model is the existing user-facing demo; generated recovery/export copies are not proposed changes. The local inventory attributes every selected file to the preserved 645-file baseline or later work.

S18's 113-input acceptance manifest is not a commit list: six entries are ignored historical helpers, while required icons and other baseline dependencies need separate closure. The assembly and extrusion-preview recipes also contain accepted-upgrade assertions outside that manifest. S19's only executable edit is the diagnostic timing-helper relocation: the macro now reads `tools/geometry_check_timing_probe.py`; the copied helper changes its repository root from `parents[2]` to `parents[1]`. Its original evidence helper is preserved.

| New action versus local HEAD | Path |
| --- | --- |
| Modify | `ARCHITECTURE.md` |
| Modify | `README.md` |
| Modify | `docs/ATLAS_PARITY.md` |
| Modify | `docs/OPERATION_CONTRACT.md` |
| Modify | `docs/U2_WALKTHROUGH.md` |
| Add | `docs/architecture-responsiveness-upgrade/PUBLICATION_SCOPE.md` |
| Add | `docs/architecture-responsiveness-upgrade/README.md` |
| Add | `docs/architecture-responsiveness-upgrade/STATUS_REPORT.md` |
| Add | `resources/icons/adopt-copy.svg` |
| Add | `resources/icons/arc.svg` |
| Add | `resources/icons/assembly.svg` |
| Add | `resources/icons/axis.svg` |
| Add | `resources/icons/boolean.svg` |
| Add | `resources/icons/build-menu.svg` |
| Add | `resources/icons/cancel.svg` |
| Add | `resources/icons/chamfer.svg` |
| Add | `resources/icons/check-geometry.svg` |
| Add | `resources/icons/circle.svg` |
| Add | `resources/icons/circular-pattern.svg` |
| Add | `resources/icons/confirm.svg` |
| Add | `resources/icons/constraints-menu.svg` |
| Add | `resources/icons/construction.svg` |
| Add | `resources/icons/coordinate-system.svg` |
| Add | `resources/icons/cut-menu.svg` |
| Add | `resources/icons/dimension.svg` |
| Add | `resources/icons/document-menu.svg` |
| Add | `resources/icons/draft.svg` |
| Add | `resources/icons/edit-menu.svg` |
| Add | `resources/icons/example.svg` |
| Add | `resources/icons/export.svg` |
| Add | `resources/icons/extrude.svg` |
| Add | `resources/icons/fillet.svg` |
| Add | `resources/icons/fit.svg` |
| Add | `resources/icons/fixed-joint.svg` |
| Add | `resources/icons/geometry-menu.svg` |
| Add | `resources/icons/groove.svg` |
| Add | `resources/icons/ground.svg` |
| Add | `resources/icons/insert.svg` |
| Add | `resources/icons/isometric.svg` |
| Add | `resources/icons/line.svg` |
| Add | `resources/icons/linear-pattern.svg` |
| Add | `resources/icons/loft-remove.svg` |
| Add | `resources/icons/loft.svg` |
| Add | `resources/icons/measure.svg` |
| Add | `resources/icons/mirror.svg` |
| Add | `resources/icons/modify-menu.svg` |
| Add | `resources/icons/more.svg` |
| Add | `resources/icons/move-face.svg` |
| Add | `resources/icons/new-document.svg` |
| Add | `resources/icons/new-part.svg` |
| Add | `resources/icons/normal.svg` |
| Add | `resources/icons/open.svg` |
| Add | `resources/icons/patterns-menu.svg` |
| Add | `resources/icons/pierce.svg` |
| Add | `resources/icons/plane.svg` |
| Add | `resources/icons/point.svg` |
| Add | `resources/icons/polyline.svg` |
| Add | `resources/icons/rebuild.svg` |
| Add | `resources/icons/recent.svg` |
| Add | `resources/icons/recovery.svg` |
| Add | `resources/icons/rectangle.svg` |
| Add | `resources/icons/redo.svg` |
| Add | `resources/icons/reference-menu.svg` |
| Add | `resources/icons/remove.svg` |
| Add | `resources/icons/revolute-joint.svg` |
| Add | `resources/icons/revolve.svg` |
| Add | `resources/icons/save.svg` |
| Add | `resources/icons/search.svg` |
| Add | `resources/icons/settings.svg` |
| Add | `resources/icons/shape-tools-menu.svg` |
| Add | `resources/icons/shell.svg` |
| Add | `resources/icons/shortcuts.svg` |
| Add | `resources/icons/sketch.svg` |
| Add | `resources/icons/slider-joint.svg` |
| Add | `resources/icons/spline.svg` |
| Add | `resources/icons/split.svg` |
| Add | `resources/icons/sweep-remove.svg` |
| Add | `resources/icons/sweep.svg` |
| Add | `resources/icons/tools.svg` |
| Add | `resources/icons/transform.svg` |
| Add | `resources/icons/trim.svg` |
| Add | `resources/icons/undo.svg` |
| Modify | `src/kurtshape/bodies.py` |
| Modify | `src/kurtshape/bridge.py` |
| Modify | `src/kurtshape/core.py` |
| Add | `src/kurtshape/document_index.py` |
| Modify | `src/kurtshape/document_state.py` |
| Modify | `src/kurtshape/extrusion_preview.py` |
| Add | `src/kurtshape/feature_panel.py` |
| Modify | `src/kurtshape/feature_tools.py` |
| Modify | `src/kurtshape/geometry.py` |
| Add | `src/kurtshape/geometry_check_worker.py` |
| Add | `src/kurtshape/history_model.py` |
| Add | `src/kurtshape/history_selection.py` |
| Add | `src/kurtshape/hover_outline.py` |
| Add | `src/kurtshape/incremental_intent.py` |
| Add | `src/kurtshape/inspection_cache.py` |
| Add | `src/kurtshape/modeling_geometry.py` |
| Modify | `src/kurtshape/navigation.py` |
| Add | `src/kurtshape/presentation_icons.py` |
| Add | `src/kurtshape/preview_worker.py` |
| Modify | `src/kurtshape/recovery.py` |
| Modify | `src/kurtshape/reference_tools.py` |
| Modify | `src/kurtshape/request_ledger.py` |
| Add | `src/kurtshape/responsiveness.py` |
| Add | `src/kurtshape/rollback_history.py` |
| Modify | `src/kurtshape/selectors.py` |
| Modify | `src/kurtshape/shortcuts.py` |
| Add | `src/kurtshape/sketch_colors.py` |
| Add | `src/kurtshape/sketch_cursor.py` |
| Add | `src/kurtshape/sketch_edit_panel.py` |
| Add | `src/kurtshape/sketch_history.py` |
| Add | `src/kurtshape/sketch_references.py` |
| Add | `src/kurtshape/sketch_regions.py` |
| Add | `src/kurtshape/sketch_snapping.py` |
| Modify | `src/kurtshape/sketch_tools.py` |
| Add | `src/kurtshape/snapshots.py` |
| Add | `src/kurtshape/startup.py` |
| Add | `src/kurtshape/step_capture.py` |
| Add | `src/kurtshape/step_export_worker.py` |
| Modify | `src/kurtshape/studio.py` |
| Modify | `src/kurtshape/theme.py` |
| Add | `src/kurtshape/tool_session.py` |
| Add | `src/kurtshape/toolbar_labels.py` |
| Modify | `src/kurtshape/ui.py` |
| Modify | `src/kurtshape/workspace_preferences.py` |
| Add | `tests/test_borrowed_preview.py` |
| Modify | `tests/test_bridge.py` |
| Add | `tests/test_bridge_native.py` |
| Modify | `tests/test_build_status.py` |
| Modify | `tests/test_extrusion_preview.py` |
| Add | `tests/test_geometry_check_jobs.py` |
| Add | `tests/test_incremental_state.py` |
| Modify | `tests/test_navigation.py` |
| Modify | `tests/test_part_studio.py` |
| Add | `tests/test_preview_worker_leases.py` |
| Modify | `tests/test_reference_tools.py` |
| Add | `tests/test_responsiveness.py` |
| Add | `tests/test_scope_membership.py` |
| Modify | `tests/test_selector_consumers.py` |
| Add | `tests/test_selector_preparation.py` |
| Modify | `tests/test_shortcuts.py` |
| Add | `tests/test_sketch_cursor.py` |
| Modify | `tests/test_sketch_planes.py` |
| Add | `tests/test_sketch_snapping.py` |
| Add | `tests/test_snapshot_transport.py` |
| Add | `tests/test_snapshots.py` |
| Add | `tests/test_step_capture.py` |
| Add | `tests/test_step_export_jobs.py` |
| Add | `tests/test_tool_session.py` |
| Modify | `tools/assembly-step-validation.FCMacro` |
| Add | `tools/design-surface-validation.FCMacro` |
| Modify | `tools/extrusion-preview-validation.FCMacro` |
| Add | `tools/generate-presentation-icons.py` |
| Add | `tools/geometry-check-lifecycle-validation.FCMacro` |
| Add | `tools/geometry-check-timing-validation.FCMacro` |
| Add | `tools/geometry-check-validation.FCMacro` |
| Add | `tools/geometry_check_timing_probe.py` |
| Modify | `tools/gui-validation.FCMacro` |
| Add | `tools/history-selection-validation.FCMacro` |
| Modify | `tools/messages-validation.FCMacro` |
| Add | `tools/onshape-workflows-validation.FCMacro` |
| Modify | `tools/part-model-spike-gui-validation.FCMacro` |
| Add | `tools/parts-refresh-validation.FCMacro` |
| Modify | `tools/perf/bench_gui.FCMacro` |
| Add | `tools/presentation-scheduling-validation.FCMacro` |
| Add | `tools/preview_validation.py` |
| Add | `tools/responsiveness-preview-benchmark.FCMacro` |
| Add | `tools/rollback-history-validation.FCMacro` |
| Modify | `tools/run_gui_recipe.ps1` |
| Modify | `tools/run_native_tests.py` |
| Add | `tools/sketch-dimension-point-colors-validation.FCMacro` |
| Add | `tools/sketch-drag-validation.FCMacro` |
| Add | `tools/sketch-edit-state-validation.FCMacro` |
| Add | `tools/sketch-origin-snap-validation.FCMacro` |
| Add | `tools/sketch-plane-editor-validation.FCMacro` |
| Add | `tools/sketch-references-validation.FCMacro` |
| Add | `tools/sketch-regions-validation.FCMacro` |
| Add | `tools/startup-view-validation.FCMacro` |
| Add | `tools/step-export-validation.FCMacro` |
| Add | `tools/surface-snap-validation.FCMacro` |
| Add | `tools/theme-startup-validation.FCMacro` |
| Modify | `tools/u2-part-model-gui-validation.FCMacro` |
| Modify | `tools/ui-refinement-validation.FCMacro` |
| Add | `tools/unused-sketch-visibility-validation.FCMacro` |
| Add | `tools/view-interaction-validation.FCMacro` |

## Exclusions and remaining local work

The NEW changes add no raw runtime tree, native installation, private profile, screenshot, test archive, token/session file, local account/control record, `.impeccable` data, generated validation tree, recovery file or generated export. Untracked detailed `EXECUTION.md`, Sxx records and newer design/workflow audit trees remain local. Already-committed historical records, validation data and optional CI/green-copy tools remain at their HEAD versions and would be included in a normal main publication; they are not removed by this selection. Necessary public user guides have historical counts labeled and local evidence links distinguished.

Unrelated modified documents such as `DESIGN.md`, `docs/M1_PROGRESS.md`, `docs/SOLIDWORKS_NAVIGATION.md` and `docs/long-run/STATUS.md`, and unrelated untracked historical/validation material, remain in the working tree. The saved local status, exact remaining-path list and original index are retained under ignored S19 working materials. No pre-existing staged changes were present, and this pass performs no staging. No user files or unique evidence are deleted.

## Checks and acceptance limits

The [status report](STATUS_REPORT.md) states the retained five focused passes, 426 native passes/four opt-in skips, and 91 GUI checks with their original S17/S18 versions. S19 checks exact native/STEP input parity, preserved evidence, Python/PowerShell syntax, local imports, required icons, advertised recipes, public links, the relocated helper and the proposed diff. It does not claim a fresh native/GUI run or hosted CI pass.

The reproducible local builder is `runtime/architecture-upgrade-working/s19-publication-readiness-working/prepare_publication.py`; it creates a snapshot and new-change patch against local HEAD without Git writes. `publication-file-set.json`, `remaining-local-work.json`, `proposed-publication.patch`, the separate existing-history inventory and verification/review receipts remain local. Package hashes identify the exact reviewed files independently of any future commit.

## Publication state

Preparation is local and reviewable. The recommendation is to preserve the legitimate project history and, only if directly authorized, publish the reviewed main fast-forward including the 18 commits, disclosed operational metadata, existing CI triggers and selected new changes. Automatic approval review rejected the commit/push handoff because direct end-user publication authorization could not be verified. That blocker is independent of the history review. No alternate branch or API route may bypass it; appropriate checks still apply to the eventual committed tree.
