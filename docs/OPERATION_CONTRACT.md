# Shared operation contract

The authoritative document is native FreeCAD FCStd. A feature object's `Name` is its stable ID; native Sketcher constraints are parameters and native expressions are dependencies. `KurtShapeProject` stores project UUID, opaque revision, build status and source mapping, without duplicating editable geometry or dimensions. Body resolution uses explicit `body`, the target/support's owning Body, or the sole Body. Several eligible Bodies without a target or explicit ID reject with `ambiguous_body`; assistants never inherit GUI focus.

`Controller.dispatch(request)` returns `{ok:true,result}` or `{ok:false,error:{code,message,...}}`. Successful document operations return inspection including `document_id`, `revision`, native features, `build_status`, measurements and `active_sketch_edit`. Mutations run serially on the GUI thread; the interface does not transport arbitrary executable code.

Create/open requests are `{op:"new",name:"Plate"}`, `{op:"open",path:"absolute.FCStd"}` and `{op:"import_step",path:"absolute.step"}` (also `.stp`, case insensitive). These create/select documents without an existing document/revision. Existing-document operations require `document_id`; every mutation, including undo/redo, sketch lifecycle, rebuild, save and export, also requires current `expected_revision`. Inspect requires no revision. Tokens are UUIDs rather than counters. Native modeling edits, undo/redo and reopen invalidate older tokens; stale requests reject before mutation.

| Operation | Additional arguments | Native behavior |
|---|---|---|
| `list_documents` | None; no document/revision | Inspect all managed documents still open in this session |
| `inspect` | None | Features, parameters, expressions, dependencies, attachment/placement, solver/build state and evaluated measurements |
| `import_step` | Absolute existing `.step` / `.stp` `path`; no document/revision | New managed unsaved project; one native Body/base feature per solid, other geometry retained as references; source SHA256 provenance. Failures leave prior documents intact. Native editing blocks import. Session `request_id` replay returns the original import without creating another document |
| `create_sketch` | Optional `id`; `plane:"XY"/"XZ"/"YZ"` or `support:{feature,subelement:"FaceN"}` | Empty attached native sketch; default XY. Native datum planes omit subelement. Both plane and support together reject |
| `sketch_rectangle` | Optional `id`, plane/support; `width`, `height`, `x=0`, `y=0` | New closed, fully constrained rectangle with named driving dimensions |
| `sketch_circle` | Optional `id`, plane/support; `x`, `y`, `diameter`, optional `center_on` | New constrained circle; optional native center expressions for a compatible origin rectangle in the same native coordinate frame |
| `add_rectangle` | `sketch`, `width`, `height`, `x=0`, `y=0`, `construction=false` | Append constrained rectangle to an existing sketch |
| `add_circle` | `sketch`, `x`, `y`, `diameter`, `construction=false` | Append constrained circle |
| `add_line` | `sketch`, `x1`, `y1`, `x2`, `y2`, `construction=false` | Append line with driving endpoint coordinates; coincident endpoints reject |
| `begin_sketch_edit` | `feature` | Start an exclusive managed native sketch edit lease |
| `finish_sketch_edit` | `cancel=false` | Validate/rebuild and group the completed edit into one history step, or restore its accepted starting state |
| `pad` | `profile`, `length`, optional `id`, `reversed=false` | Native Pad along the attached sketch's positive normal; optional reverse |
| `pocket` | `profile`, optional `id`, `through_all=true`; `length` for blind cut; optional `reversed` | Native Pocket against the sketch normal. With direction omitted, an empty cut tries the opposite direction; an explicit direction is respected. Must remove material and retain one valid solid |
| `set_parameter` | `feature`, `parameter`, `value` | Named or indexed driving sketch dimension, Pad Length or blind-Pocket Length; expression-driven/reference parameters reject numeric replacement |
| `rename_feature` | `feature`, `name` | Change native Label, preserving internal ID/references; Body can be renamed as the visible part |
| `delete_feature` | `feature`, `cascade=false` | Delete sketches, datum planes and built-in native PartDesign features, including fillet/chamfer/revolution/mirror/pattern. Dependencies require explicit cascade; Body, external references and script-owned/proxy targets or consumers reject |
| `rebuild` | None | Touch native modeling features and recompute |
| `undo` / `redo` | None | Native document history outside editing; native sketch snapshots within its managed lease; fresh revision |
| `save` | Absolute `path` in a granted project folder, `.FCStd` | Native staging file, checked ZIP, atomic replacement and recovery copy of prior file |
| `export` | Absolute `path`, optional `body`, `.step`/`.stp`/`.stl` | All final solid results by default, or selected Body; included IDs, engine/settings/revision/units/SHA256 provenance; replacement failure restores the prior pair when possible |

Entity coordinates are sketch-local millimeters. Supported dimensional constraints are Distance, DistanceX, DistanceY, Diameter, Radius and Angle; angles use radians. Unnamed dimensions use keys such as `Constraints[17]`. Numeric values must be finite and satisfy native dimensional/solver validation. Source-created features may carry optional request fields `source_feature_id`/`source_feature_name`, stored in native source properties and metadata mapping.

The GUI starts a lease before native `setEdit`. Stop active drawing tools, call native `resetEdit`, then finish or cancel through the controller. During the lease, only that sketch's add-geometry/parameter changes, inspect, managed undo/redo and finish are permitted. Refresh inspect after native edits. Native construction tools may commit intermediate transactions; finish groups lease transactions and cancel restores the initial sketch without deleting prior history or allowing canceled geometry to return through redo. Closed-document leases cannot survive same-UUID reopen. See [native sketch plane and lifecycle details](SKETCH_PLANE_CONTRACT.md).

Standalone modeling failures abort their transaction and retain accepted geometry/revision. A failed managed command restores its pre-command draft; failed Finish retains the full current draft/lease and advances the revision. The GUI reopens Sketcher and shows the error in Messages. Only explicit Cancel discards the lease. Native failed builds report explicit errors; unrecomputed touched features report `needs_rebuild`, `measurements:null` and separate `retained_geometry_measurements`. Export rejects failed or unrecomputed builds. Retained geometry is not a successful evaluation of new intent.

## Contract 2 additions — October 2 review follow-up

| Operation | Arguments and behavior |
|---|---|
| `capabilities` | No document/revision: contract/session IDs, supported operations, engine and retry limits |
| `request_status` | `request_id`, no document/revision: queued/started/completed/failed/cancelled/expired/not_recorded; retained original response |
| `diagnostics` | No document/revision: bounded timing samples and checkpoint location |
| `create_body` | Optional `id`, `name`: native Body; returns `created_feature` |
| `set_expression` | `feature`, `parameter`, `expression` string or null: native dimensional formula; null clears; native cycle/unit/reference errors reject and roll back |
| `duplicate_feature` | `feature`, optional SHA256 `fingerprint`: shallow native sketch/Pad/Pocket copy in its Body, links preserved, one transaction, returns `created_feature` |
| `pierce` | `sketch`, zero-based `geometry`, `point:1/2/3`, `target`, `subelement:"EdgeN"`: one native curve/plane intersection plus coincidence; same Body, no downstream cycle; ambiguous/conflicting cases reject |
| `preview` | `proposal:{op:"set_parameter"/"set_expression",...}` and current revision: hidden disposable FCStd clone, automatically destroyed; returns proposal/base revision, validity/errors and measurements. Commit sends the operation afresh against that revision |
| `adopt` | Absolute new `path`: copy with new project identity, original native IDs/links preserved, staged save; existing destination and script/external-link objects reject |
| `recover` | Absolute checkpoint-manifest `path`, no document/revision: hash verification; unfinished sketch retains its accepted Cancel buffer; choose Save destination anew |

Typed modeling and begin-edit requests accept optional `body` except `create_body`/`rebuild`. Inspection adds `managed`, `unsupported_objects` and per-result `bodies`, including standalone Part solids. Aggregate and per-result status/measurements distinguish current and retained geometry. One-solid validation applies to the affected PartDesign Body, not the entire document.

Quantity strings accept units and arithmetic (`1/8 in`, `12.7/2`, `90 deg`). Explicit angles convert FreeCAD's internal degrees into the radian contract. Wrong dimensions, booleans and nonfinite values reject. Document-dependent formulas use `set_expression`; the unbound native input fields stage values until dispatch.

Human save/export dialogs persist destination-folder grants and recent projects in the local profile. Default roots are `CADkz/Codex` and `CADkz/projects`; the bridge cannot grant itself another folder. Unmanaged FCStd opens with a transient session identity and no added input metadata. Typed/native app modeling is guarded until adoption. Adoption rejects script/proxy objects and cross-document dependencies; it does not certify every native object for every typed operation.

STEP import reads with FreeCAD Part/OCCT, validates before publishing a new native document, preserves occurrences/placements without fusing solids, and stores an `ImportSource` provenance property. Inspection exposes `import_source` (otherwise null); export sidecars include it. Geometry is in FreeCAD's internal mm units. Import preserves no original feature history, product hierarchy, names or colors. Surface-only inputs remain native references with `sketch_only` build status and cannot produce a solid export. `capabilities.import_formats` lists STEP suffixes. Source reads require no destination grant; later save/export still require one. The GUI routes STEP files from Open/Recent to `import_step`; the native `open` operation remains FCStd-only.

The bridge requires `request_id` on mutations, including New/Open/Save/Export/Undo; internal human UI calls may omit it. Canonical identical replay returns the original result before stale checking; different-payload reuse rejects. Up to 512 full results are retained, with tombstones for every admitted ID. After 4096 IDs, new IDs reject until reconciliation/restart; old IDs cannot execute again within that session. Expired results reject. A queued timeout records cancelled; started timeout reports `outcome_unknown` with ID/session. Use status lookup or identical replay. `not_recorded` after restart is not proof of nonexecution; no cross-crash exactly-once guarantee. Request cap stays 64 KiB. CLI `send` adds an ID to its caller's dictionary when missing; use explicit persisted IDs in durable retry files.

Observers mark intent/evaluation dirty. Idle GUI ticks check queued work/editing state without full inspection; BRep validity is cached until geometry/recompute invalidation. Native commit/mouse-release and typed-command boundaries record sketch undo snapshots independently of stale detection. Checkpoints run at up to 30-second intervals, storing native FCStd and the accepted sketch buffer; failed Finish forces a verified checkpoint. Hash mismatch rejects and the previous pair remains available. Native recovery/autosave is enabled at one minute in the app profile. Disk/checkpoint/recompute timing remains separate from ordinary feedback.

Successful staged save/open clears the native GUI Modified flag after final inspection. This does not perform a second in-place save or clear undo history. Failed writes remain modified; later edits mark the document modified again. Open freshly rebuilds native features and rejects a simultaneous second copy of the same project UUID. Close the original before opening a relocated copy.

New/open and existing-document mutations reject while native graphical editing is active, including solid-feature task dialogs; finish or cancel the graphical edit first. The compatibility error code remains `sketch_edit_active`. Deletion restores the latest surviving solid feature as Body.Tip, or clears Tip when only profiles remain; native undo restores deleted features, references and geometry.

Current limits: no general expression-evaluation request, arbitrary FeatureScript execution, automatic topology guessing, general multi-body conversion or typed operations for every native GUI feature. Face sketches require a retained native planar support; native lost references/rebuild failures are explicit and no frozen placement is substituted. Native GUI tools can create other features in the same authoritative document. **The two supplied Onshape designs remain 0/2 converted**; synthetic subset fixtures do not count as real migrations.

The token-authenticated loopback adapter sends the same dispatch requests to the GUI thread; CLI clients read its local session file. It does not configure cloud Onshape access or message another assistant. An actual Claude-client session and reference-backed imported-edit equivalence remain M1 acceptance gaps.

## Assembly increment — October 2

All assembly mutations require the existing current document UUID/revision and bridge request ID. GUI dialogs retain their starting revision so an intervening edit rejects instead of applying to a changed assembly. A project contains one single-level native assembly. Sources are embedded shape snapshots with same-document native link occurrences; external source changes never silently update accepted parts. [Policy, workflow and verification](assembly-workflow/WORKFLOW.md).

| Operation | Additional arguments | Behavior |
|---|---|---|
| `assembly_candidates` | Absolute existing FCStd `path`; read-only, no document/revision | Return selectable final Body/solid IDs/names/counts; unsafe sources reject without publishing/opening a user document |
| `create_assembly` | Optional `id`, `name` | Create native Assembly and joint group in this document; one assembly only |
| `insert_assembly_part` | FCStd `path`, `source_id`; optional `assembly`, `id`, `name` | Embed selected source geometry and create one independent native link occurrence; first insertion grounds automatically |
| `ground_assembly_instance` | `instance`; optional `assembly` | Change the sole grounded reference and solve |
| `create_assembly_joint` | `joint_type:fixed/revolute/slider`, `first`, `second`; optional `assembly`, `id`, `name` | Native joint connectors and solver; each reference is `{instance,subelement}` with empty subelement for origin or native Face/Edge/Vertex ID |
| `edit_assembly_joint` | `joint`; optional `assembly`, `joint_type`, `first`, `second`, `name` | Change references/type/label and solve in one native transaction |
| `move_assembly_joint` | `joint`, `value`; optional `assembly` | Revolute degrees or slider millimeters; set permitted coordinate and solve, fixed motion rejects |
| `move_assembly_instance` | `instance`, `position_mm:[x,y,z]`, `rotation_xyzw:[x,y,z,w]`; optional `assembly` | Place a free occurrence, validate and solve; no arbitrary transform code |
| `delete_assembly_object` | `feature`; optional `assembly`, `cascade:false` | Remove a joint or occurrence; dependent joints need explicit cascade; native undo restores references/placements |
| `solve_assembly` | Optional `assembly` | Explicit solve of current native assembly intent |

`rename_feature` additionally accepts supported assembly/instance/joint IDs and preserves internal references. Inspection adds `assembly`; capabilities identify native solver, single-level scope, source snapshot policy and motion units. Undo/redo restore transaction placements and solver evidence without rerunning the solver on idle. Assembly current-solid export includes every occurrence globally transformed once, excludes embedded sources, and rejects a `body` filter. Its sidecar includes the inspected assembly state. Solver failure rolls back typed mutations; unresolved native intent is never current valid geometry. Reopen/recovery uses native persistence and rechecks solving. Arbitrary proxy/cross-document safety remains narrow; this is not a general FCStd trust waiver.
