# Dodec fixture workflow regression

October 21, 2026. FreeCAD 1.1.4 / OCCT 7.8.1. The completed three-bolt,
five-axis hub fixture is a regression input, not a design revision. Originals
and the user's separately running viewer were not modified, closed or restarted.
Private evidence lives under `CADkz/projects/dodec-fixture-workflow-regression`;
private CAD and process data are not repository assets.

## Actual reopen failure

The retained fixture `assembly-reopen-check.json` already says
`build_status:failed` for `EmbeddedPart003`, while every occurrence's
`geometry_check_report` is valid. The design record's success description had
conflated solid validity with assembly integrity. Fresh headless and offscreen
GUI opens reproduce **the same** seal mismatch and fingerprint. GUI
initialization is not the cause of this case.

The builder and user's viewer both recorded build `src-6c4c799f964be9a9`,
git `c328bab6c9cc972d4951fe386869cf2580101aa9`. The embedded source's saved SHA
still matches `hub-reference.FCStd` (`97500daa21c239fdb8c4432a2eb72729b261ad02bad7e1ff4f6f4fe2d96658e8`).
Its embedded and source placements are identity. Source-version and placement
differences do not explain the failure.

Native BREP reading repeatedly renormalizes oblique analytic curve frames by
about 1e-16. Seven successive native roundtrips produced different exact hashes,
with unchanged measured volume. The fingerprint after one cycle was
`978a95978cca4ecbfcbcd8a1baebf1f11336394a7ff21cd38d85ea6fc6b11974` (stored seal);
after two it was `775b1547637886fcf7d5c11041e5714084a82b7c1316b5a53653bf47174b74e2`
(both reopened processes). The previous one-cycle stabilization assumption was
false for this imported hub. Raw BREP diffs retain the evidence.

## Persistence correction

`assembly_persistence.save_copy` verifies live embedded fingerprints, lets
FreeCAD serialize the native archive, restores each serialized source BREP
through the pinned reader and seals that exact restored representation. Only
`SourceGeometryFingerprint` metadata in the staging archive changes; every
geometry payload byte and the live document are preserved. Restored BREP must
be valid. No coordinate rounding, fuzzy matching or relaxed hash comparison is
introduced. Mismatching live sources remain mismatches, even in recovery files.

The wrapper covers managed save, recovery, batch preview, adoption and worker
snapshots. It does not intercept arbitrary third-party FreeCAD `saveAs/saveCopy`
calls. Already-invalid legacy files are not silently accepted. The regression
copy was repaired with explicit `refresh_assembly_part(instance="Hub")` from
its unchanged saved source, retaining all 35 occurrence IDs, placements and
volumes. The user's original assembly remains untouched.

## Reproduce both application modes

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\run-assembly-reopen-regression.ps1 `
  -FilePath C:\path\to\fixture.FCStd `
  -OutputDirectory C:\path\to\fixture-reopen-regression
```

For a legacy failed seal, add `-RefreshInstance Hub` to explicitly refresh only
the private copy before testing. The source must be available. This runner
creates separate headless and hidden offscreen GUI processes, three successive
managed save/reopen cycles per mode, and intentional embedded-geometry negative
cases. It hashes the original, checks build status and native geometry, tests
that corrupted embedded sources still fail after save/reopen, and exits its own
processes. It never connects to a live user or benchmark session.

Fixture evidence: three repeated cycles passed in each mode, 35 occurrences
each; changed-source detection passed before and after serialization. A separate
hidden GUI refresh probe verified source/occurrence appearance for shared
copy-on-write and in-place refresh, then reopened the result successfully.
Native persistence tests also check exact geometry archive-byte preservation,
small genuine coordinate edits, missing BREP payloads and failed staged writes.

Final production build `src-73578ae7e4f4c57c` passed the three-cycle headless
(10.070 s) and hidden GUI (11.586 s) fixture regressions with genuine-change
negative controls. The required `run-checks.ps1 -KeepNativeTemp` took 1209.498 s:
1,152 passed, five opt-in performance tests skipped, one failure, no errors,
with source hashes unchanged. The failure was an outdated worker-capture
expectation for a Boolean whose native roundtrip changes signed-zero plane
directions. A test-only correction now checks real stable-source capture after
reopening and real unstable-source synchronous fallback, with pending validation
before either decision. All 47 tests in the affected result-validation and
geometry-worker classes passed in 31.288 s afterward. Production code remained
unchanged; the full command was not rerun after the test-only correction.
Raw full-run and focused reports are retained in the regression project's
`repository-checks` and `assembly-refresh-checks` directories.

Null-source recovery is separately covered: assigning an empty native shape to
an embedded source makes its occurrence lose the forwarded `Shape` attribute.
Inspection still reports the embedded integrity failure; forced recovery and
discard-close checkpoints remain available. Both archives reopen with the null
shape and rejected seal preserved, and cannot become valid through saving.

Source identity also excludes properties forwarded by occurrences. Shared
sources appear once in delivery reports, with every occurrence listed. After
refreshing a single occurrence of a shared source, reinserting that revised
saved part links directly to its replacement embedded snapshot. The regression
checks source identity, placement, inventory roles and valid native reopening.

## Related improvements and limits

The same native roundtrip issue also affected GUI background geometry checking.
Exact detached BREP admission now routes unstable sources to the existing
synchronous check, while stable geometry still uses the worker and all worker
fingerprint comparisons remain enforced. The fixture previously spent 1.396 s
capturing and 2.027 s in a worker before rejecting the snapshot. The corrected
path took 0.227 s for admission and 0.433 s for successful synchronous checking.
Native-invalid geometry and genuine embedded-source changes still fail their
respective gates. The source file and live geometry were unchanged by the probe.

- [Component refresh and part inventory](COMPONENT_REFRESH.md): explicit shared
  source policy, valid joint retention and transactional rollback. Changed
  topological joint references require explicit editing; no guessed remapping.
- [Measured Session iteration](../SESSION_ITERATION.md): roughly 19.4% faster
  cartridge recipe, with geometry and validation retained.
- [Session discovery and selected open/fit](../AGENT_QUICKSTART.md#discover-and-explicitly-select-a-delivery-session):
  no automatic benchmark selection, launch or restart.
- [Delivery and clearance validation](../DELIVERY_VALIDATION.md): native build
  integrity and valid solids are separate mandatory gates. STEP surface sampling
  is opt-in and is not a proof of equivalence.

The actual fixture's continuous three-arm OD envelopes reproduced 1.4679159867 mm
minimum nominal tool clearance at `CartridgeScrew2`/`CartridgeScrew3` and
34.4628633114 mm holder clearance at `Cartridge`. Straight loaded-hub Allen-key
access and the underside radial approach correctly fail. Side-spanner samples
and finite through-dowel tip probes pass. These are geometric access checks,
not machine-specific CAM, load qualification or a fixture redesign.

One export discrepancy remains explicitly failed: the original assembly STEP
and a fresh STEP from the corrected native file have identical per-component
metrics, but total reported volume differs from native by 2.392949 mm³ (about
2.85 ppm). Two-way 500-point surface sampling agrees within 5.41e-8 mm and bounds
agree closely. The hub accounts for most of the difference. FreeCAD exposes the
default native BRepGProp volume integration without a Python accuracy parameter;
an independent mesh-volume probe did not establish convergence. A stronger
control proved numerical nonadditivity: adding a disjoint analytic 1 mm³ cube
to the unchanged valid native hub changed the inferred hub volume by
-0.11347 mm³ at cube Z=-100 and +0.38579 mm³ at Z=1000. This demonstrates that
default `Shape.Volume` is not a sufficiently precise independent reference for
this case; it does not prove native/STEP equivalence. Section-area and split-solid
integration probes did not establish convergence and remain failed diagnostics.
The volume gate is retained and the delivery report does **not** certify the
STEP export. Detailed values, commands and primary FreeCAD/OCCT source links are
in the private regression folder's `delivery-clearance/Delivery and clearance evidence.md`.
