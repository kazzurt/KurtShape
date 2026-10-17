# S14 canonical HTTP request status

Canonical `{"op":"request_status","request_id":"..."}` now reads the locked session ledger without entering the CAD command queue. The supported Controller explicitly supplies a JSON-only lookup; fast-path eligibility requires a string ID of 1–128 characters and a valid live measurement default. Authentication, path, Origin, media type, size and JSON-object checks still run first. The lookup checks ledger identity and primitive configuration before and after copying. It does not call Controller dispatch/pruning, touch native objects, register a request, or update owner-thread timings.

The response retains request/session identity, outcome and the copied original response, including original operation timing. Its own `queue_wait_ms` is 0.0 and it has no operation timing of its own. Optional fields, noncanonical IDs, invalid defaults and custom controllers retain the existing queued validation and error precedence. Ledger capacity, expiry, cancellation, identical replay and mutation timeout behavior are unchanged. Status remains a point-in-time observation; `not_recorded` does not prove a mutation never ran.

## Validation and scope

- Focused bridge gate: 19/19 pass, zero skips/failures/errors, native PID 83264 exit 0 with no forced reap, 14.28 seconds including launch. Ten new transport/ledger tests extend the existing seven; two new actual-Controller tests run in the loopback-capable bridge suite. The native suite's existing Python network ban remains intact.
- An event-held test-controller mutation proves queued, started, unknown-outcome and completed status while the owner dispatch is blocked; it also verifies same-thread timing writes and single execution on replay. A saturated 32-item queue does not block canonical lookup. Guard rejection, exact helper/ledger types, invalid and changing live configuration, nested-copy isolation, failures, cancellation, expiry and capacity are covered.
- Actual FreeCAD tests create a plate, edit length 8 then 9, and query/replay the older result while the Controller is marked busy. Sentinels prohibit tick, dispatch, pruning and timing calls. The original result and operation time remain exact while full inspect, source/native geometry, history and current length 9 remain unchanged. A 28-case matrix compares queued HTTP validation against direct owner dispatch.
- Final native regression: 403 pass out of 407, with the four existing opt-in performance methods skipped; no failures, errors, rejected skips or unassigned tests, 171.37 seconds including launch. Native child 18128 and launcher 82924 exit 0, no timeout. FreeCAD 1.1.4 / OCCT 7.8.1 are used. Both gates have identical final hashes for all 96 runner inputs.

The blocked-owner check uses a test controller; the real native preservation/replay check is separate. Active kernel overlap and response-time guarantees were not tested. Python GIL scheduling and ledger-lock contention still apply. Exact Controller subclass exclusion is source-reviewed; tests exercise nonstandard-controller and lookup-subclass fallback without instantiating a derived native Controller. No GUI/performance rerun, native authority migration, S12/S13 activation, or expanded crash/recovery proof is claimed.

## Retained inputs and reproduction

`runtime/architecture-upgrade-working/s14-request-status-working/` contains all 110 accepted S09B originals in `source-before/`, the original documentation, the 110-entry original manifest, and 111 final source files plus their new manifest. Only `bridge.py`, `core.py`, `request_ledger.py`, `tests/test_bridge.py` and the bridge-suite registration in `tools/run_native_tests.py` change among original sources. `tests/test_bridge_native.py` is new; `test_review_followup.py` remains byte-identical. All 611 S13B evidence hashes still verify against its untouched historical manifest.

Run from the repository root using the preserved bundled FreeCAD Python and isolated test environments:

```powershell
& 'C:/Python314/python.exe' -B runtime/architecture-upgrade-working/s14-request-status-working/run_focused.py
& 'runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin/python.exe' -B tools/run_native_tests.py --suite native --require-native --timeout 420 --keep-temp --report runtime/architecture-upgrade-working/s14-request-status-working/reproduced-native-regression.json
```

The first command creates a fresh run directory and receipt; use a fresh report filename for any later native reproduction. Original focused evidence is in `runtime/test-tmp/s14-request-status-e380d21f/`; original native evidence is in `runtime/test-tmp/regression-run-20261008-075156-82924-2fec63cf/native/`. The focused child has a 180-second limit; the native child has 420 seconds plus bounded owned-process cleanup. Native jobs run sequentially. `verify_s14.py` binds the original receipts, original/final sources, engine, process inventory and retained prior evidence in `final-verification.json`; it verifies this recorded run rather than launching tests.

Final controls at 14:57:14 UTC / 07:57:14 PDT show 65% used in the original 10080-minute window, reset 1791958350, ordinary usage allowed and unchanged 62500 credits. Implementation and native jobs finished before the 15:05 implementation cutoff and 15:14 native cleanup bound; the batch ends before the 15:19 save / 15:20 turn deadlines and 70% cap. The original hard weekly deadline remains October 14, 06:12:30 UTC.

This finite batch ends after saving the execution record and manifest. User FreeCAD 40888 remains running untouched; all S14 test processes have exited. S14 adds no automation, follow-on batch, allowance/reset action, publication, push, merge or deployment.
