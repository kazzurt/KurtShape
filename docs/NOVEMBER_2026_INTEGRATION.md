# November 2026 main reconciliation

Status: reconciled and validated on 13 November 2026.

## Preserved source and integration basis

- Original working branch: `claude/slice-ab`, commit `6d329e2844da8b75ccca6f165feff2c147bf7c73`.
- All 23 modified tracked files and 27 untracked source/documentation files were preserved in local commit `42fdfd3` on `backup/local-before-main-2026-11-13` before changing the checkout.
- Integration base: GitHub `main`, `bdbfe3f9bc20d33ab8e66103dca6aa73bfcd3437` (27 October 2026).
- Reapplied the preservation commit onto that base without publishing the snapshot commit. Changes already incorporated by the October integration disappear from the final diff.

## Resulting behavior

- Named-part STEP export retains part names and world placements, writes provenance, and leaves source documents unchanged. The default compound export remains available.
- KurtShape startup branding supplies the application icon, document/version title, and cached loading screen.
- Drawing support includes the Aerial Hedra metric/inch template generator, the 11 November drawing standard, auxiliary views, geometric fitting for imported curves, bounded section-gap snapping, and the latest dimension/leader corrections through 12 November.
- Agent launch instructions include opening a finished modeling result for the user's review.

## Reconciliation decisions

The five conflicts were the drawing manual, generated operation reference, drawing sheet/view implementation, and drawing tests. Retained the latest local drawing implementation and tests, then reapplied the upstream font-independent missing-glyph regression (`aebe858`). Regenerated `docs/OPERATIONS.md` from the reconciled schema.

Retained GitHub's sketch endpoint alignment fix, regression/lint corrections, and hosted Windows CI fixes. Registered `test_drawing.StandardTests`, which had been absent from the full runner, alongside the existing drawing, named-STEP, and branding classes. No existing assertion was weakened.

## Validation and reproduction

- Pinned Ruff 0.16.10: passed (`ruff check .`).
- Isolated installation check: 18 checks passed (`tools/check-install.ps1`).
- Full ordinary regression: passed in 1,455.8 seconds (`run-checks.ps1`, bundled FreeCAD 1.1.4 / OCCT 7.8.1): 1,341 tests, 1,336 passed, 5 opt-in performance tests skipped, zero failures or errors. All external-fixture tests ran. Every suite and the parent run confirmed unchanged source.
- Source/credential publication scan: only source, tests, and documentation are staged; runtime, tokens, models, profiles, and generated logs remain excluded.

Local preservation and validation details are recorded in `runtime/november-main-reconciliation/reconciliation-status.json`; console logs are beside that file. Full reports include source hashes and isolated runtime provenance. These generated records remain local, as required by `AGENTS.md`.

Headless and offscreen tests do not establish interactive viewport acceptance on the user's hardware. The five skips were `ResultValidationPerfTests.test_plate_edit_checks_only_affected_operations` and the four `StatusPerformanceTests` methods, all requiring `KURTSHAPE_PERF=1`. Interactive GUI acceptance and those opt-in benchmarks are not claimed.

| Suite | Passed | Skipped | Failures / errors |
| --- | ---: | ---: | ---: |
| Native CAD, drawings, STEP export and branding | 1,218 | 5 | 0 |
| Bridge | 77 | 0 | 0 |
| Shortcuts | 35 | 0 | 0 |
| Modeling workflows | 6 | 0 | 0 |

Validated loaded-build SHA256: `95ba1009fb9610fb48fb578cbd7826dd169ca64eeb4bce30bd09e5425a70a939`.

Full regression report: `runtime/test-tmp/checks-20261113-103551-54556/evidence/checks/native.json` (JUnit beside it). Installation report: `runtime/installation-check/b0f9a6c1b73c4c60b90995cfc092c3c2/evidence/installation.json`. The final source files were also checked against every hash in the regression report immediately before commit. The original local snapshot remains on its backup branch.
