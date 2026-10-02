# Native sketch planes and edit transactions

Verified against the bundled FreeCAD 1.1.4 / OCCT 7.8.1 on 2026-10-02. The authoritative model remains the native FreeCAD document. Sketches use native `AttachmentSupport` and `MapMode = FlatFace`; this version has no older `Support` alias. No planar-face sketch is represented by a frozen placement.

## Shared operations

All mutations require the current `document_id` and `expected_revision` returned by inspect. Examples omit these two fields for readability.

```json
{"op":"create_sketch","id":"FrontSketch","plane":"XZ"}
{"op":"create_sketch","id":"TopSketch","support":{"feature":"Pad","subelement":"Face6"}}
{"op":"create_sketch","id":"DatumSketch","support":{"feature":"OffsetPlane"}}
{"op":"begin_sketch_edit","feature":"TopSketch"}
{"op":"add_circle","sketch":"TopSketch","x":10,"y":6,"diameter":4}
{"op":"finish_sketch_edit"}
```

- `plane` accepts XY, XZ, YZ. Omitting both plane and support selects XY. Specifying both is rejected.
- `support.feature` is a native object ID in the current Body or its native Origin. A selected Body face resolves to the current solid Tip to avoid a circular Body association.
- Native `App::Plane` and `PartDesign::Plane` references accept an absent/empty subelement. A solid reference must specify exactly one valid planar `FaceN`. Missing, ambiguous, curved, foreign-Body and malformed references are rejected before sketch creation.
- The existing `sketch_rectangle` and `sketch_circle` convenience operations also accept plane/support. Coordinates are sketch-local millimeters. Expressions centering a circle on a rectangle require both sketches to share the same placement.
- `add_rectangle` accepts sketch, width, height, optional x/y, optional boolean construction. `add_circle` accepts sketch, x/y, diameter, optional construction. `add_line` accepts sketch, x1/y1/x2/y2, optional construction. They append real solver geometry and driving constraints. Dimensions receive unique native names when a sketch already contains entities. These operations also work outside an edit session in individual native transactions.
- `pad` and `pocket` accept optional boolean reversed. Pad follows the attached sketch's positive normal by default. Pocket initially follows native inward direction, against the normal. With direction omitted, an empty inward cut tries the opposite direction; inspect reports the resulting reversed flag. An explicitly requested direction is never substituted. Blind pockets require through_all:false and honor length; through_all defaults true.

## Graphical edit lifecycle

1. Call begin_sketch_edit using a refreshed revision. It opens a native document transaction and an exclusive sketch edit lease.
2. Activate native Sketcher and call `Gui.getDocument(doc.Name).setEdit(sketch.Name)`.
3. Native Sketcher tools modify that same sketch. Inspect detects native geometry, constraints, expressions, construction-state and attachment changes, advancing the revision. Refresh inspect before sending another mutation.
4. Stop any active tool, call native resetEdit, then call finish_sketch_edit. Finish validates and groups only post-checkpoint native commands into one history step. A failed Finish preserves the current draft/lease, checkpoints it, reports the reason and reopens the GUI editor. Repair and retry, or explicitly Cancel. Failed typed sketch commands restore their pre-command draft rather than losing the whole session.
5. Cancel follows the same resetEdit sequence with finish_sketch_edit cancel:true; rollback restores the exact accepted sketch and advances revision. Native resetEdit commits in this FreeCAD version. The controller undoes only lease-created transactions and invalidates cancelled geometry's redo with a discard-only metadata boundary. Shared undo/redo skips that boundary. External history changes crossing the checkpoint reject rather than undoing unrelated features; recovery material retains the draft.

Only add_* operations targeting the edited sketch, set_parameter on that sketch, managed undo/redo and finish are permitted during the lease. Save, export, rebuild, switching/opening documents and other feature changes are guarded. Unmanaged native edit mode is guarded separately. Inspect's `active_sketch_edit` is the native sketch ID or null. Ordinary FCStd does not store an edit lease; the separate verified recovery manifest retains its accepted sketch buffer. Closing its native document discards the lease; reopening the same saved project UUID starts without the old snapshots/history checkpoint. Reattaching the same still-open native document preserves its live lease.

During a managed edit, route Ctrl+Z / Ctrl+Y through shared undo/redo operations. Each complete typed edit, native transaction commit, or completed mouse gesture, is retained as a native `dumpContent()` byte snapshot in an ephemeral undo cache (up to 128 states). Undo restores the previous native sketch buffer without replacing the sketch object or ending its document transaction. Redo restores the next buffer. A new edit clears redo. These buffers are neither a second sketch representation nor persistent modeling intent. Native `Std_Undo` must not bypass this lease: it ends a pending native transaction. After finish, ordinary shared document undo reverses the completed sketch transaction as one document-history step.

## Inspection and history

Sketch inspection exposes `support: [{feature, subelements}]`, `map_mode`, and `placement: {position_mm, rotation_xyzw}` alongside constraint counts and solver state. Unnamed driving dimensions are accessible with keys such as `Constraints[17]`; named dimensions preserve their existing keys. Constraint expressions/reference dimensions remain noneditable. Driving angles use radians, other supported dimensions use millimeters. The signature uses the kernel's exact geometry Content XML, so spline interior-pole changes are detected even when an abbreviated repr stays the same.

`rename_feature {feature,name}` changes a printable native Label, preserving internal IDs and references. A Body can be renamed as the visible part while preserving its existing internal ID. `delete_feature {feature,cascade?:false}` supports sketches, pads, pockets and native datum planes; deleting Body remains rejected. Dependent features block deletion unless cascade:true. References outside the active Body block it even with cascade. Consumers are removed before their sources, source mappings are cleaned and the surviving last solid becomes Body.Tip. Native undo restores the feature references and Tip.

After a successful staged save or native open plus final inspection, the controller clears the native GUI document's writable `Modified` flag. The bundled API exposes `Gui.getDocument(doc.Name).Modified`, with no setModified method. Clearing the flag does not rewrite the file or clear undo history. Failed writes retain the modified flag; later modeling edits set it again normally. Fresh session UUIDs and native rebuild-cache touches on open therefore do not give a saved project a spurious unsaved tab marker.

## Evidence and remaining limits

`tests/test_sketch_planes.py` contains 21 native checks: origin-plane extrusion orientation; persistent top-face attachment; upstream thickness changes, undo/redo, relocation and fresh rebuild; datum-plane offset tracking; Body-face resolution; invalid support rejection; actual blind-cut depth and explicit-direction rollback; grouped edit commit/cancel; managed typed/native undo/redo; failed-edit revision safety; unnamed length and angle dimension edits; spline/construction native revision detection; dependency-safe rename/delete and undo; Body part-name undo/redo and deletion rejection; cancellation and failed finish after native auto-commit; external history checkpoint safety; close/reopen and direct-attach lease cleanup; grouping multiple native command transactions. The prior 18 offline core/converter/safety tests also pass.

`tools/sketch-lifecycle-validation.FCMacro` was run in its own hidden native process using isolated config and temporary directories under `validation/sketch-lifecycle-working`. The result in `validation/sketch-lifecycle-result.json` passes: native setEdit, an actual Sketcher_CreateRectangle command with Qt mouse clicks, native geometry editing, snapshot undo/redo while the viewport remains in Sketcher, native resetEdit auto-commit, grouped finish, cancel, prior feature undo and redo without resurrecting canceled geometry. The actual rectangle tool created three session history entries; finish collapsed them to one, with empty-sketch undo and full-sketch redo verified. `getInEdit()` returns a `SketcherGui::ViewProviderSketch`; its `.Object` is the native sketch. UI code must unwrap that object before checking `Sketcher::SketchObject`.

Native topological naming retains the support reference when geometry permits. This is not a universal guarantee across arbitrary topology-changing edits. Native lost/invalid supports and failed rebuilds surface as build errors; no detached placement or frozen shape is silently substituted. The supplied Onshape designs are unchanged and this work does not constitute their native conversion.
