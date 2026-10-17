# Windows friends preview — 2026-10-17

This handoff prepares the current `main` application for other Windows users.
Its modeling baseline is `f57d59267857ad32c302d2ae6e6c1368ce3c6a68`; it does not
merge unreviewed feature branches or implement the Fable backlog wholesale.

## Included

- Native editable sketches, extrusions, cuts, fillets and chamfers; shared Part
  Studio history, rollback, Undo/Redo, STEP/STL export and basic assemblies.
- The October 16–17 bridge additions: arcs, arbitrary datum-plane frames,
  connected polylines, native Hole, selector parameter filters, multi-edge query
  references and pattern `include_source`. Some are typed operations without
  dedicated toolbar dialogs; query `capabilities` and read the operation contract.
- `setup.ps1`: pinned runtime installation and an isolated end-to-end native
  smoke check; `tools/assistant.ps1` uses bundled Python for agent connections.
- Portable first-run save locations under `<checkout>/projects`. Existing
  settings retain their legacy implicit grants and explicit chosen folders.
- A concise README, Windows/agent guides, repository-local AGENTS/CLAUDE entry
  points, MIT license for original code, and third-party notices.
- Hosted test scratch-root correction and unused-import/assignment cleanup.
  The assertions and accepted test coverage are retained.
- The full Fable review, backlog and supporting artifacts, labeled with their
  original evidence and verification limits. Those findings describe the
  baseline review; this document records subsequent setup/CI changes.

## Validation

- Fresh isolated Windows regression: **619 cases, 612 passed, seven skipped,
  zero failures/errors**. Three skips require private external examples; four
  are opt-in performance tests. Source hashes were unchanged and rechecked
  against the final application/test files.
- Clean source-only install: the official 418 MB archive was downloaded,
  checksum-verified and extracted in a separate folder with no copied profile
  or runtime. Windows PowerShell 5.1 setup passed **18 smoke checks**, including
  native save/reopen, Undo/Redo, STEP and STL export. Repeat setup passed.
- Missing 7-Zip was rejected before downloading; an invalid cached archive was
  rejected before extraction. The checksum was never bypassed.
- A private offscreen app started and answered `capabilities` and
  `list_documents` through the bundled-Python wrapper. Its process was stopped
  after the check; no user document was opened or mutated.
- Ruff 0.16.10: clean. Documentation links and Git whitespace checks: clean.

[Compact evidence and source hashes](sharing-release/validation-2026-10-17.json).
The [Windows workflow](https://github.com/kazzurt/KurtShape/actions/workflows/windows-ci.yml)
records hosted results after push and now also exercises newcomer setup under
Windows PowerShell. The earlier Fable report describes the baseline separately.

The first hosted Windows 2022 run reproduced all 612 passes/seven skips and
passed the 18-step setup. Its final hygiene check rejected the new empty
`projects/` directory. The check now permits that empty destination while still
rejecting files placed there or any other unexpected repository changes.

## Known limitations to tell testers

- This is a preview, with ongoing sketch/status/viewport polish documented in
  the [review](fable-deep-review/FABLE_REVIEW.md). Performance on large models
  can stall during snapshot capture, save and committed recompute.
- Pattern-reference and cross-body Mirror work on separate branches is not
  included by this sharing change. A Mirror link-scope warning can still occur.
- Assembly parts are embedded snapshots; editing a source part does not update
  the assembly automatically. Advanced mates and nested assemblies are deferred.
- Slow bridge operations need explicit request-status reconciliation; the
  [agent guide](AGENT_QUICKSTART.md) describes safe retries. The current app does
  not report the loaded source commit in its title/capabilities. A setup report
  identifies checked source only; save and relaunch after updating.
- Cylindrical Move face, retained-error deletion and further Sweep improvements
  remain separate work. Do not assume all audit suggestions are implemented.
- Source conversion is separate from STEP geometry import. Private Onshape
  examples and the author's CAD projects are not needed or bundled for setup.
- Headless validation does not establish graphics, DPI or mouse behavior on a
  friend's machine. Perform the brief interactive check in the Windows guide.

The user's already-running CAD session and original model files were not
restarted or modified during release preparation.

## Next development step

Collect short installation and modeling reports from friends, then address a
bounded usability increment from the Fable backlog. Prioritize build identity,
bridge outcome reconciliation and useful error/status feedback before broad
visual redesign. Keep experimental branches separate until reviewed and tested.
