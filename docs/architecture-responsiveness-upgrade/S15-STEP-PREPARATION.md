# S15 private STEP preparation and pending feedback

The private probe supports a completed-Qt-paint barrier before STEP capture and identifies the dominant measured preparation phases in one representative sample. Production remains the accepted S14 checkpoint: all 111 source hashes are unchanged. This is a feasibility result, not activation or a speedup result.

## Preparation diagnostic

The retained S09B representative fixture contains 1,000 translated solids in one `WorldSolids` result. Original archive SHA256 is `ed2b514d7550c3f74eea2ded2fb71cb900ad70fd8708982ac88253cda7405642`. The probe opened those exact bytes, exported a synchronous oracle, then populated the private snapshot cache from a fresh native `saveCopy` of the current document. No eligibility flag was forced. The measured production `Panel.start_step_export` obtained an eligible worker and borrowed the snapshot. GeometryCache computed/memo counters were unchanged across the action.

| Instrumented phase | Milliseconds |
|---|---:|
| Whole `start_step_export` action | 2321.4308 |
| `prepare_step_export` | 2076.4772 |
| Native roundtrip admission | 929.4944 |
| Initial world fingerprints | 522.5158 |
| Final model guard | 573.5994 |
| Final world fingerprints, inside that guard | 554.9216 |
| Full measurements, with warm computed counters | 14.8769 |
| Snapshot acquisition | 0.2529 |
| Borrowed snapshot handoff | 0.5366 |
| Final destination guard | 1.4027 |
| Worker submission | 224.8106 |
| Worker startup, inside submission | 17.3231 |
| Existing `step_export_snapshot_gui` timer | 1113.4763 |

These are inclusive, nested, nonadditive timings from one instrumented call. Wrapper overhead is included; there are no ownership-gate spans or saveCopy profiler in the representative phase. No assumed overhead is subtracted. The existing snapshot timer excludes roundtrip admission and worker allocation, so it does not describe the whole stall. Roundtrip and fingerprint work dominate this sample; it provides no evidence that measurement or cache-copy optimization would resolve the measured delay. The 2321.43 ms result is diagnostic context for S09B's earlier 2340.19 ms launch, not a matched before/after performance comparison.

Strict source/native/camera snapshots match before and after; the retained worker archive SHA is unchanged. Both STEP and provenance destination sentinels remain untouched while the child is pending. The child exits 0 before acceptance. Imported STEP world geometry exactly matches the synchronous oracle for all 1,000 solids. Provenance matches after excluding only separately verified file SHA and per-body native check timing; each file's own SHA is verified.

## Pending feedback proof

The helper replaces the actual `Panel.message` QLabel with a private subclass. After the base `paintEvent` returns, it records a marker only when the complete contents are visible, covered by the paint region and updates-enabled, with a nonminimized window. A distinct owned Qt timer then continues. No `processEvents`, forced repaint or capture inside paintEvent is used. The isolated window uses `WA_DontShowOnScreen`: the proof concerns Qt paint completion, not physical screen presentation.

Waiting uses separate pending state, leaving `_step_export_preparing` false so `Panel.tick` can process context changes. The ticket binds exact generation, document object, observer instance, native revision/generation/change serial, authorized resolved destination, parent identity, STEP and sidecar identities. Eventful admission/context/destination reads are followed by ownership checks. Allocation, snapshot acquisition/borrow, actual native saveCopy and submission retain guards. Actual preparation alone uses the existing preparing bracket. Active sketch/native feature-task admission and post-submit ownership checks are preserved in the private helper.

The final small fixture is the existing S09B `LifecycleSolid` archive, SHA256 `bea192042c59caf291eb00bfa2858326a5a30fd1421c2fe15ef8c77871f727f3`. Private cache retirement deliberately forces a real owned-copy path without editing native source. The final run proves:

- Caller returns at monotonic ns `1809973580799500`.
- Actual feedback base paint completes at `1809973625914000`.
- Native `saveCopy` C-call starts at `1809973653803600` and returns 22.6588 ms later.

The instrumented action takes 18.4132 ms; return-to-paint is 45.1145 ms and paint-to-native-capture is 27.8896 ms. These are single-run observations, not latency bounds. Exactly one preparation, allocation, acquisition, completed native saveCopy and submission occur, all for the positive request. Its native source/camera, archive and successful provenance checks pass.

Ten cancellation cases pass: queued Escape, document switch, native Label edit, destination content change, replacement, hidden label, updates disabled, clipped label, minimized window, and source-document close. After deliberate mutations, the post-mutation native/destination state is the comparison oracle. No abandoned request enters prepare, allocation, snapshot capture or submission. Direct invocation of an old continuation cannot clear a successor's feedback. The four unpaintable cases terminally cancel in 609.3181–621.5682 ms using a 600 ms timer, without timeout-forced capture.

Coverage remains limited: queued cases are deliberately held unpainted; native Label editing is not a solid-geometry edit. Active native task admission is source-reviewed, not separately injected. Reentry inside native/file getters, an already-painted stale timer, pending Save/panel shutdown and callback-error feedback are not independently exercised. Signal teardown restores forwarding closures, so reinstalling on the same panel may not disconnect those closures through the original bound method; this is a single-installation private proof. The eight ordinary-Python gate checks prove that ownership exceptions, including OSError, become cancellation rather than entering acquisition's legitimate OSError-to-saveCopy fallback. They do not replace native race tests.

Terminal cancellation when feedback cannot paint is this probe's diagnostic policy. It is not a recommended production policy: a later design may need a bounded grace followed by ordinary later-turn continuation that explicitly records no completed painted acknowledgment. Stale, cancelled, closed and changed requests must still cancel permanently. S15 does not implement that policy.

## Failures, receipts and preservation

All private code and evidence are in `runtime/architecture-upgrade-working/s15-step-preparation-working/`.

The first run, `runs/first-probe-5a493742`, completed all 51 checks and the representative diagnostic but remains **failed overall**. Cleanup raised a legacy PySide `im_func` error while reconnecting an original bound slot. Its small phase was named `small-painted-positive-copy` but actually reused a snapshot and observed no native saveCopy; that label does not establish a cache miss. Original executed helpers, source hashes, failed receipt and all artifacts remain untouched. GUI PID 58304 and STEP children 31580/60784 exited 0; the parent's contained job counted seven processes in total and zero active before closing. No forced reap was required.

The repaired run, `runs/pending-proof-40464c24`, repeats only the small pending-feedback cases. All 41 checks pass, including helper teardown, restored instrumentation and exactly one completed native saveCopy. GUI PID 52772 and STEP child 48744 exit 0, cleanly reaped; its contained job counts five processes and zero active. Slot restoration now uses retained forwarding closures. Gate exception normalization preserves genuine underlying acquisition OSError fallback. These repaired helpers were not retroactively attributed to the first run.

The launcher creates each GUI process suspended, assigns its exact handle to a private kill-on-close Windows Job Object, then resumes the primary thread. It rechecks absolute headroom before creation/resume, reserves 30 seconds for cleanup, and retains failures independently through final receipt writing. Each job has a 240-second parent bound and a 210-second in-GUI timeout. The final child independently attests its PID, 111 source hashes and five executed-input hashes; the parent agrees and retained copies are rehashed. The first child lacks the later self-attestation field; its parent launch binds the preserved executed copies, which also rehash correctly.

`assessment.json` and `assess_s15.py` verify the receipts, exact comparisons, timestamps, zero abandoned work, source freeze and preserved evidence. All 617 S14 manifest entries remain available, using the pre-S15 saved versions for the two intentionally updated living documents; all 611 S13B evidence files remain unchanged. A failed first assessor with a local variable typo is retained separately. User FreeCAD PID 40888, started October 3, remains untouched. Only recorded owned PIDs were checked; no reviewer process enumeration was requested.

Reproduce only with a separately authorized bounded session: ordinary Python runs `run_gui.py <label>` for the combined diagnostic, or a label beginning `pending-` for only pending cases. Each run creates a new private folder, copies helpers before launch and preserves both raw fixtures in place. The current launcher retains S15's absolute October 8, 15:55 UTC cleanup deadline and intentionally refuses later execution until a future authorization supplies new bounds. `assess_s15.py` reads the retained runs without launching native work.

## Decision and next useful work

Go for further private design/testing; no-go for production activation. A useful next finite experiment is an exact-oracle A/B limited initially to one target, carrying only the canonical original BRep digest from successful roundtrip admission into initial fingerprint construction. Retain fresh detached shape, metadata and map reads, the unchanged independent final fingerprint, all child/measurement/destination guards, and the existing multi-target path. This targets duplicate serialization, not the entire 522.52 ms fingerprint phase or all shape copies; no recoverable time or speedup is estimated. Reentrant mutation parity and exception-order tests are required before any production change. Separately resolve unpaintable-feedback policy and the untested races before promoting the pending helper.

Final control at 15:37:51 UTC / 08:37:51 PDT reports 69% used, original 10080-minute window/reset 1791958350 and unchanged 62500 credits. Ordinary allowance remains available. The original hard weekly deadline stays October 14, 06:12:30 UTC. This batch ends below its 71% cap, before the 15:45 implementation and 15:55 cleanup limits. No production activation, broad regression, scheduling, allowance/account action, publication or automatic next batch follows.
