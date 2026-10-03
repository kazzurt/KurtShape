# KurtShape code review and upgrade plan

October 3, 2026. Reviewer: Claude. Scope: everything under `src/kurtshape` (7,605 lines), the tests, launch/validation scripts and the design/progress docs at commit `d9efdcc`. Goal set by Kurt: an app that operates quickly and seamlessly and is at least as good as Onshape.

## Summary

The foundation choice (FreeCAD 1.1.4 / OCCT 7.8.1, native FCStd) is still sound. The engineering around safety is careful: revision tokens, request replay, staged saves, recovery, explicit error paths and a large regression suite. **The thing standing between KurtShape and "fast and seamless" is the Python shell around FreeCAD, not the geometry kernel.** On a synthetic 60-hole plate (132 document objects), KurtShape spends 5.3 of the 6.2 seconds of a one-dimension edit on its own bookkeeping; FreeCAD's recompute is 0.83 s of it. The overhead grows faster than linearly with model size, so real parts will feel worse than the small fixtures that the earlier validation used.

The five changes with the largest payoff, in order:

1. **Take OCCT's full validity check (`Shape.isValid()`) and mass-property integration out of the interactive path.** They run on whole bodies several times per operation and after every shape change anywhere in the document. Measured: 1.87 s per validity check and 4.95 s per inspection after any geometry change at 60 holes. Removing them cut a tip edit from 6,301 ms to 964 ms in a direct experiment (native recompute 832 ms), and adding a sketch from 5.7 s to 0.49 s.
2. **Replace the clone-the-document extrusion preview.** Each preview evaluation saves, reopens and rebuilds a full copy of the project: 15.1 s per evaluation at 60 holes, triggered 160 ms after each keystroke in the Depth field. Extruding the sketch face directly takes 4.4 ms.
3. **Stop rebuilding every feature on open.** A native open of the 60-hole file takes 2.3 s; KurtShape then touches and recomputes everything for another 12.7 s.
4. **Get disk work off the interaction path.** Recovery checkpoints stall the UI for 1.27 s every 30 s while you edit, on top of native autosave every 60 s. STEP import, save and export also block.
5. **Fix the hard-coded Windows path in `assembly.py:23`**, add CI, and keep tests from writing into tracked files. With a one-line fix, 89 of 92 native test methods pass on Linux; the other 3 need the external Onshape example files.

The gap to Onshape on features is mostly the interaction layer and tools FreeCAD already has but KurtShape doesn't expose: extrude end conditions, rollback/suppress/reorder, variables, type-while-sketching dimensions, more assembly joints, live part links, BOM and exploded views. Section 5 turns this into a phased plan with performance budgets and acceptance gates.

## 1. How this review was done

- Read all source modules, the test suites, the launch/validation scripts, README/DESIGN/PRODUCT, `docs/M1_PROGRESS.md`, the October 2 review follow-up and the UI refinement records.
- Downloaded the official FreeCAD 1.1.4 Linux AppImage (same FreeCAD 1.1.4 and OCCT 7.8.1 as the pinned Windows runtime) and ran the native test suites headless against an untouched copy of the repository.
- Profiled the controller headless (`evidence/bench_core.py`, `evidence/profile_op.py`, `evidence/fix_probe.py`) and the real Qt shell under Xvfb (`evidence/bench_gui.FCMacro`). Raw results are in `evidence/*.json`.

**Benchmark fixture.** A 600 × 600 × 12 mm plate followed by N "sketch circle → through-all pocket" pairs, built only through `Controller.dispatch` (or `Panel.operation` for the GUI run). It is deliberately simple: one body, analytic faces, no fillets. It is a stress fixture for the shell, not a stand-in for the hub. Xvfb uses software OpenGL, so GUI timings include no GPU and are pessimistic for rendering but representative for Python work. Hardware: 4 vCPU cloud container.

## 2. What is working well

- **One authoritative model.** Typed operations, native Sketcher/PartDesign and the assistant bridge all write the same FCStd document; there is no parallel feature graph to drift.
- **Safety engineering.** Revision tokens with stale-request rejection, a session request ledger with replay, staged save with ZIP verification, paired export replacement with rollback, sketch-lease preservation on failed Finish, and recovery checkpoints that include unfinished sketches.
- **Tests that check consequences.** 118 test methods assert geometry, undo/redo, persistence and failure rollback rather than only return codes. Most of the suite runs unchanged on a second OS.
- **The idle loop is already cheap.** The October 2 fix holds: an idle 25 ms tick costs about 5 µs.
- **Local bridge hygiene.** Loopback only, bearer token, `Origin` rejection, 64 KiB cap, GUI-thread-only mutation.

## 3. Findings

Severity: **P0** blocks "fast and seamless" on real parts; **P1** is a correctness, portability or maintainability problem; **P2** is polish.

### 3.1 Performance

#### P0-1. Validity and mass properties run on whole bodies for every operation

`measurements()` (`core.py:157-165`) calls `shape.isValid()` (OCCT `BRepCheck_Analyzer`) and integrates volume, area and per-solid center of mass. It is reached from:

- `_build_status` → `_evaluated_shape` for every result body (`core.py:490-494`, `285-292`). `_build_status` runs in `sync`, in `_new_revision`, after every model operation, and twice per `inspect` (`core.py:505` and `543`).
- `_geometry` for the document aggregate, which builds a compound of all bodies and validates it again (`core.py:257-274`).
- Pocket's `cut_valid` (`core.py:1296-1299`) and the extrusion preview (`extrusion_preview.py:203-206`), which validates the preview body and the material difference.

The caches are keyed by one document-wide `generation` counter (`document_state.py:15-20, 32-34`). Any `Shape` or `Placement` change on any object, including a sketch recompute while drawing, increments it and invalidates every body's cached result. The next 25 ms tick then re-validates every body.

`BRepCheck` cost grows with the number of wires per face (it checks wire pairs), so a face with many holes is expensive.

| 60-hole plate (132 objects) | Time |
|---|---:|
| `isValid()` on the body | 1.87 s |
| `measurements()` on the body | 2.33 s |
| `inspect` with warm caches | 17.6 ms |
| `inspect` after any shape change | 4.95 s |
| Tip dimension edit, total | 6.2 s |
| ↳ native recompute | 0.83 s |
| ↳ KurtShape overhead | 5.3 s (86%) |

At 25 holes, cProfile attributes 58% of a sketch-creation operation to `isValid`, 19% to center-of-mass integration and 7% to FreeCAD's recompute.

Growth of a single operation as the history grows (headless):

| Holes | Objects | Add sketch: total / native | Add pocket: total / native |
|---:|---:|---:|---:|
| 1 | 14 | 24 / 3 ms | 78 / 30 ms |
| 20 | 52 | 489 / 37 ms | 1,168 / 261 ms |
| 40 | 92 | 2,175 / 157 ms | 5,016 / 949 ms |
| 60 | 132 | 5,702 / 394 ms | 12,419 / 2,172 ms |

Through the real GUI at 40 holes, one tip dimension edit took 6.9 s and the last sketch-plus-pocket step took 19.3 s.

**Fix.** Derive interactive build status from FreeCAD's own feature state (`Invalid`/`Error`/`Touched`) plus `Shape.isNull()`; PartDesign already marks failed features. Run `BRepCheck` before export, on an explicit "Check geometry" command, and optionally in a background `freecadcmd` process when idle. Compute volume/area/center of mass only when something displays them, and cache per object keyed by that object's own shape change rather than a document-wide counter. **Measured effect.** `fix_probe.py` builds the same 60-hole model with `measurements()` replaced by a bounding-box-only version, then repeats the edits:

| 60-hole plate | Today | Without validity / mass properties | Native recompute |
|---|---:|---:|---:|
| Tip dimension edit | 6,301 ms | 964 ms | 832 ms |
| Add a sketch | 5,702 ms | 485 ms | 369 ms |
| Add a through-all pocket | 12,419 ms | 2,676 ms | 2,337 ms |

The remaining ~130 ms of overhead is mostly the full-document intent signature and inspection (P2-8). The pocket's 2.3 s is OCCT boolean time on a face with 60 holes; real models should use patterns or multi-profile sketches for repeated holes, as in Onshape.

#### P0-2. Extrusion preview clones the whole project through disk on every evaluation

`ExtrusionEvaluator.evaluate` (`extrusion_preview.py:151-224`) saves the live document to a temporary FCStd when the generation changes, then for every evaluation opens that file as a new document, runs the Pad/Pocket operation, recomputes, runs `_build_status` (P0-1), computes `measurements`, performs a boolean difference and validates it. The assistant `preview` operation uses the same pattern (`core.py:889-940`).

| 60-hole plate | Time |
|---|---:|
| Preview, first evaluation | 15.7 s |
| Preview, each later evaluation (cache miss) | 15.1 s |
| Direct OCCT: extrude sketch face + boolean against body + tessellate | 0.57 s |
| Direct OCCT: extrude sketch face + tessellate, no boolean | 4.4 ms |

The debounce is 160 ms, so typing a depth on a mid-sized part freezes the UI for roughly 15 s per pause.

**Fix.** For Pad/Pocket, build the preview from `Part.Face(sketch wires).extrude(direction × depth)` and display it immediately; Onshape shows the swept volume itself, so a boolean is optional. If the exact removed volume is wanted for cuts, compute `tip.common(prism)` after the first frame is shown. Accept still goes through the real operation. For other features, use FreeCAD's own task panels, which already preview in place, or a single short transaction on the live document with the observer suspended.

#### P0-3. Opening a managed project rebuilds every feature

`_dispatch` for `open`/`recover` touches every Sketcher and PartDesign object and recomputes (`core.py:642-646`). At 60 holes: native open 2.3 s, then 12.7 s more of recompute. Startup cost therefore equals a full rebuild, which for the 145-feature hub could be minutes.

**Fix.** Trust the stored BReps. Record FreeCAD/OCCT versions in the project metadata and rebuild only when they differ, when the file has no stored shapes, or when the user asks. Mark status `needs_rebuild` and offer Rebuild instead of forcing it.

#### P0-4. Disk work blocks the GUI thread

- **Recovery checkpoints** (`recovery.py:18-48`, timer at `ui.py:103-105`, `1271-1279`): `saveCopy`, then `testzip()` (decompresses the whole archive), then SHA-256 of the file, then a copy of the previous checkpoint. 1.27 s at 60 holes (`saveCopy` alone 1.15 s), every 30 s whenever the revision changed. 367 ms at 40 holes through the GUI.
- **Native autosave** is forced to every minute (`ui.py:2033-2036`), duplicating the checkpoint.
- **STEP import**, **save** and **export** run synchronously with only a wait cursor (`ui.py:1341-1349`, `core.py:1400-1452`).

**Fix.** Keep one recovery mechanism. FreeCAD's AutoSaver writes shapes from worker threads; let it own periodic recovery and keep the custom checkpoint for the unfinished-sketch lease only, written when the user pauses (no input for a few seconds) rather than on a fixed clock. Replace `testzip()` with a central-directory read plus `Document.xml` presence. Move STEP read/convert into a `freecadcmd` subprocess that writes an FCStd, with progress and Cancel, then open the result.

#### P1-5. The GUI inspects the full document twice per operation

`Panel.operation` inspects before dispatch to fetch the revision (`ui.py:917`), dispatch returns a second full inspection (`core.py:815`), and the failure path inspects a third time (`ui.py:934`). `begin_preview` (`ui.py:1603`) and `assembly_ready` (`ui.py:531`) add more. With P0-1 each one can cost seconds. **Fix.** Add a cheap `revision` read for the pre-check, and return a delta (changed features, status) from mutations.

#### P1-6. Every mouse release in a sketch triggers document-wide work

The application event filter marks an edit boundary and forces a refresh on each `MouseButtonRelease` while a sketch is open (`ui.py:1994-1996`). The next tick runs `sync`: a full-document intent signature, a full-sketch byte snapshot pushed onto a 128-entry stack (`core.py:370-384`), `_build_status`, which re-validates every body whenever the sketch has been recomputed since the last tick (P0-1), and a full feature-tree rebuild when the revision changed (`ui.py:970-1060`). On a large part, drawing in a sketch inherits multi-second stalls. **Fix.** Fixing P0-1 removes most of it. Then snapshot only on real transaction commits, hash only the edited sketch during a lease, and leave the tree alone while editing.

#### P2-7. Five application-wide Python event filters

Panel, WorkspacePreferences, ShortcutRouter, DoubleMiddleFit and the theme filter each see every Qt event in the process. Measured 407 µs vs 239 µs per synthetic mouse-move event with and without them (about 0.17 ms per event; Xvfb). `DoubleMiddleFit` reads a FreeCAD parameter on every event before checking the event type (`navigation.py:101-104`). **Fix.** One filter with an early integer type check; cache the navigation style and refresh it when Settings changes.

#### P2-8. Linear full-document work that will matter later

- `intent_signature` serializes every property of every object to JSON and hashes it after each operation: 40 ms at 132 objects (`core.py:124-154`, `880-887`). Sketch geometry and Pocket properties dominate. Hash per object and update only objects the observer reports as changed.
- `refresh()` clears and rebuilds the whole tree, part list and body combo on each revision: 6.7 ms for 86 items (`ui.py:970-1060`). It also resets scroll position. Move to a `QAbstractItemModel` with diffing.
- The assembly validator serializes every embedded source BRep to a string and hashes it whenever the document-wide generation changes (`assembly.py:698-708`, `734`). With large STEP parts this is a large per-edit cost.
- STL export uses a fixed absolute deflection of 0.05 mm (`core.py:1433`): huge files for large parts. Make it relative and configurable, recorded in provenance.

### 3.2 Correctness and portability

| ID | Finding | Location | Fix |
|---|---|---|---|
| P1-9 | The Assembly module path is hard-coded to the Windows portable layout. On any other install, every assembly operation fails with `assembly_runtime`. 18 of the 20 failing test methods on Linux were this. Replacing it with `Path(App.getHomePath()) / "Mod" / "Assembly"` made 17 of 17 runnable assembly tests pass. | `assembly.py:23` | One line, verified |
| P1-10 | No CI. Tests run only through PowerShell against the Windows runtime, and several write into tracked `validation/` files (`tools/validate_offline.py`, `tests/test_core.py` → `validation/core-acceptance/`), so a test run dirties the tree. | `run-checks.ps1`, tests | Linux CI with the AppImage (Appendix B); write to temp dirs |
| P1-11 | Probable exception loop (found by reading, not reproduced): when the active document leaves the managed set, `tick()` sets `self.state = None` but keeps `last_document`. Returning to that same document with no pending changes takes the early-return branch and calls `self.state.get(...)` on `None`, raising every 25 ms; the panel stops updating until something changes. | `ui.py:861-865`, `881-891` | Reset `last_document` when clearing state |
| P1-12 | Assistant write roots include the entire parent folder of the repository, and every folder a human ever saves into is granted to assistants permanently, with no way to review or revoke. | `core.py:25`, `settings.py:17-37` | Scope grants to project folders; add a revoke list in Settings |
| P2-13 | `number()` says "must be a finite number in mm" for angle parameters. | `core.py:48-50` | Use the target unit in the message |
| P2-14 | A missing `path` on `open` surfaces as `operation_failed` with a traceback in the log instead of `invalid_argument`. | `core.py:632` | Validate arguments per operation (Section 3.3, operation registry) |
| P2-15 | The bridge rejects `Content-Type: application/json; charset=utf-8`. | `bridge.py:32` | Compare the media type only |

### 3.3 Architecture and maintainability

- **Operation metadata is spread across five sets and a dictionary** (`READ_OPS`, `MODEL_OPS`, `EDIT_OPS`, `CREATE_OPS`, `ASSEMBLY_OPS`, `ARGS`, `core.py:169-205`), a 310-line `_dispatch` with ten local flags, a 170-line `_model_operation` if/elif chain, and op-name lists repeated in the GUI (`ui.py:899`, `960`). **Recommendation:** an operation registry where each operation declares its argument schema, category (read / model / sketch-edit / create / assembly), guards, handler and preview support. Capabilities, argument validation, the assistant/MCP tool definitions and docs are then generated from one place.
- **`Panel` is a 2,000-line class** covering the document bar, workspaces, assembly dialogs, the sketch lifecycle, the extrude task, the history tree, IO and shortcuts. Split it into a history tree (model/view), feature editor, sketch session, extrude task, assembly workspace and document actions, each owning its own state.
- **Two sketch undo systems.** Native transactions plus a 128-entry stack of full-sketch byte snapshots with lease/grouping logic (`core.py:386-464`, `790-806`). It works and is well tested, but it is the most intricate code in the project. Revisit once P1-6 is done; native Sketcher undo inside a single outer transaction may cover it.
- **Style.** 97 lines over 160 characters, the longest 429; dense one-line conditionals (for example `core.py:783`) are hard to review. Add `ruff` (lint + format) and a type checker in CI.
- **Docs.** 18 doc folders/files totalling about 31,000 words, plus 62 JSON evidence files, mostly status records. Keep README for users, add a short ARCHITECTURE.md for contributors, and move dated evidence into release notes.

### 3.4 Gap to Onshape

"Native" means FreeCAD 1.1.4 already implements it; KurtShape needs a workflow and UI. Effort: S ≈ days, M ≈ 1–2 weeks, L ≈ several weeks.

| Onshape capability | KurtShape today | FreeCAD 1.1.4 native support | Effort |
|---|---|---|---|
| Extrude end conditions: up to next / face / part / vertex, symmetric, second direction, draft | Blind, Through all (cut only) | Pad/Pocket `Type`: Length, UpToFirst, UpToLast, UpToFace, TwoLengths, UpToShape, ThroughAll; `Midplane`, `TaperAngle`, `SideType` | S |
| One Extrude tool with New / Add / Remove / Intersect | Separate Extrude and Remove | Pad, Pocket, Boolean | M |
| Drag handle for extrude depth in the viewport | Numeric field only | Coin draggers (used by native exploded views) | M |
| Live preview for every feature, same dialog style | Pad/Pocket (slow, P0-2); other tools open native Tasks | Native task panels preview in place | M |
| Rollback bar, insert feature mid-history | None | `Body.Tip` | S |
| Suppress / unsuppress | None | `Suppressed` property on PartDesign features | S |
| Reorder features by drag | None | `Body.insertObject` + recompute | M |
| Variables table (`#width`) | Formula field per dimension | `App::VarSet` + expressions | M |
| Configurations | None | Spreadsheet configuration table, VarSet | L |
| Type dimensions while drawing | Dimension tool after drawing | Sketcher on-view parameters (`OnViewParameterVisibility`) | S |
| Hover a feature to highlight its geometry | None | `Gui.Selection.setPreselection` | S |
| Measure panel, mass properties | Status-bar text, volume only | Measure module, `Shape` properties | S |
| Assemblies that update when parts change | Embedded snapshots; source edits never propagate | `App::Link` to Bodies in other documents (`Assembly_InsertLink`) | L |
| Mate types | Fixed, Revolute, Slider | Also Cylindrical, Ball, Distance, Parallel, Perpendicular, Angle, Rack-pinion, Screw, Gears, Belt | S–M |
| Drag parts in an assembly | Numeric dialogs | Native Assembly drag with solver | M |
| Exploded views, BOM, motion | None | `Assembly_CreateView`, `Assembly_CreateBom`, `Assembly_CreateSimulation` | M |
| Sub-assemblies | Single level | Insert an assembly into another (`Assembly_InsertLink`) | M |
| Drawings | None | TechDraw | L |
| Versions and branches | Files plus recovery | None native | L |
| Non-blocking regeneration | UI blocks on recompute | Recompute is single-threaded; can show progress and allow cancel | M |

## 4. Performance budgets

Proposed targets on the 60-hole benchmark and on Kurt's hardware with the real parts. "Overhead" means time outside FreeCAD's recompute.

| Interaction | Today (60 holes) | Target |
|---|---:|---:|
| Dimension edit, overhead | 5.3 s (132 ms in the P0-1 experiment) | ≤ 150 ms after Phase 0, ≤ 50 ms after Phase 1 |
| Inspection after a shape change | 4.95 s | ≤ 20 ms |
| Extrude preview update (blind) | 15.1 s | ≤ 50 ms first frame |
| Open, beyond native open | +12.7 s | ≤ +10% |
| Recovery stall while editing | 1.27 s / 30 s | none during input; ≤ 16 ms visible |
| Tree refresh, 200 features | not measured (6.7 ms at 86) | ≤ 5 ms incremental |
| Idle CPU | ~0 | ~0 |

Add `evidence/bench_core.py` (parameterized) to CI as a non-blocking trend report first, then gate on the overhead budgets.

## 5. Upgrade plan

Each phase ends with a measurable gate. Phases 0 and 1 add no new tools; they change speed and when checks run.

### Phase 0 — Unblock (2–4 days)

1. Assembly path fix (`assembly.py:23`) and the `tick()` state reset (P1-11).
2. Interactive build status from native feature state; validity at export and on demand; lazy, per-object mass properties (P0-1). Touch points: `core.measurements`, `_evaluated_shape`, `_geometry`, `_build_status`, `inspect`, pocket `cut_valid`, `extrusion_preview`, `DocumentState`.
3. Open without full rebuild; version-mismatch rebuild only (P0-3).
4. Linux CI running the native suites with the AppImage; tests write to temp dirs (P1-10).
5. **Gate:** dimension-edit overhead ≤ 150 ms and inspection ≤ 20 ms on the 60-hole benchmark; all suites green in CI; existing GUI recipes still pass on Windows.

### Phase 1 — Responsive shell (1–2 weeks)

1. Extrusion preview from the sketch face; optional exact boolean after first frame; Revolve preview the same way (P0-2).
2. One recovery mechanism, idle-triggered, without `testzip`; STEP import/export in a `freecadcmd` subprocess with progress and Cancel (P0-4).
3. Event-driven refresh: observer marks dirty, a zero-delay single-shot timer coalesces, the bridge wakes the GUI with a queued signal; remove the 25 ms poll.
4. One inspection per GUI operation; per-object intent hashing; model/view history tree (P1-5, P1-6, P2-8).
5. One application event filter (P2-7).
6. Display settings: evaluate `UseVBO`, `RenderCache` and tessellation deviation on large parts; keep what improves orbit frame time.
7. **Gate:** the budgets table met; Kurt's 30-minute walkthrough on a real part with no stall longer than 100 ms outside recompute.

### Phase 2 — Onshape-grade Part Studio (2–4 weeks)

1. Unified Extrude: New/Add/Remove/Intersect, all native end conditions, second direction, draft, and a viewport depth handle bound to the Depth field.
2. Rollback bar (Tip), Suppress, drag-to-reorder, insert-here.
3. Variables panel backed by `App::VarSet`, with expression autocomplete in every quantity field.
4. Sketcher: enable on-view parameters and auto-constraints by default; keep Kurt's shortcut map.
5. History tree: hover highlights geometry; failed features show their message inline; every feature edits in the same right-hand panel with Confirm/Cancel.
6. Measure and mass-properties panel.
7. Operation registry (Section 3.3) so each new tool is available to the assistant contract at the same time.
8. **Gate:** a scripted list of everyday Onshape Part Studio workflows that Kurt signs off, each with a preview and one undo step.

### Phase 3 — Assembly v2 (3–5 weeks)

1. Live-linked parts (`App::Link` to a Body in another managed FCStd) with an explicit "pin to this version" option that keeps today's snapshot behavior.
2. All native joint types; pick faces/edges in the viewport to define connector frames.
3. Drag parts with the solver; exploded views; BOM; sub-assemblies.
4. **Gate:** edit a part, see the assembly update, undo restores both; save, relocate and reopen a multi-file project.

### Phase 4 — Strategic (next quarter)

- Configurations, drawings (TechDraw templates), and a project history with named versions, thumbnails and an intent diff.
- MCP server generated from the operation registry, so Claude and Codex use the same schemas.
- **Foundation checkpoint.** After Phase 1, measure native recompute for typical edits on the reconstructed hub. If typical edits stay above about 1 s with the shell overhead gone, evaluate kernel/app alternatives with real numbers; until then FreeCAD remains the fastest route to Onshape-level breadth.

## 6. Decisions

Kurt decided on October 3, 2026:

1. **Validation:** yes. Geometry validity is checked at export and on explicit request, not after every edit.
2. **Assemblies:** live links that update like Onshape. Pinning to a snapshot may remain as an option.
3. **Platform:** Windows only. CI runs on Windows with the pinned portable runtime; the Linux AppImage remains a convenient probe tool, not a product target.
4. **Order of work:** both. Speed work and new Onshape-parity tools are interleaved rather than speed-only first.

Still open: whether feature dialogs should be KurtShape-styled panels for the common tools or FreeCAD's task panels embedded in the right-hand dock. The Codex implementation prompt (`CODEX_PROMPT.md`) states the default it assumes.

## Appendix A. Test results on FreeCAD 1.1.4 / OCCT 7.8.1 (Linux AppImage)

| Suite | Result |
|---|---|
| Native offline suites (same classes as `tools/validate_offline.py`) | 72 / 92 test methods pass. 18 fail with `assembly_runtime` (P1-9); 2 need the external `Onshape examples` folder |
| Assembly suite with the P1-9 one-line fix | 17 / 19 pass; 2 need the external folder. Overall 89 / 92 |
| Bridge timeout/replay | 4 / 4 |
| Shortcut routing | 22 / 22 |

## Appendix B. CI sketch

```yaml
name: native-tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - name: FreeCAD 1.1.4 runtime
        run: |
          curl -sSL -o FreeCAD.AppImage https://github.com/FreeCAD/FreeCAD/releases/download/1.1.4/FreeCAD_1.1.4-Linux-x86_64-py311.AppImage
          chmod +x FreeCAD.AppImage && ./FreeCAD.AppImage --appimage-extract > /dev/null
      - name: Native suites
        env: { QT_QPA_PLATFORM: offscreen, PYTHONDONTWRITEBYTECODE: "1" }
        run: squashfs-root/usr/bin/freecadcmd tools/run_native_tests.py
```

`tools/run_native_tests.py` would load the same test classes as `validate_offline.py`, skip tests whose external fixtures are absent, and write reports to a temporary directory. Pin the AppImage SHA-256 the same way `install-runtime.ps1` pins the Windows archive.

## Appendix C. Reproducing the measurements

From an extracted AppImage (`squashfs-root/usr/bin/freecadcmd`):

```bash
export BENCH_SCRATCH=/tmp/ks-bench BENCH_HOLES=60
freecadcmd docs/2026-10-03-claude-review/evidence/bench_core.py   # controller hot paths
freecadcmd docs/2026-10-03-claude-review/evidence/profile_op.py   # cProfile of one operation (BENCH_HOLES=25)
freecadcmd docs/2026-10-03-claude-review/evidence/fix_probe.py    # same edits with validity checks removed
# GUI shell under Xvfb (see header of bench_gui.FCMacro for environment variables)
xvfb-run -a freecad docs/2026-10-03-claude-review/evidence/bench_gui.FCMacro
```
