# Operation reference

> **Generated file; do not edit.** Rendered from `src/kurtshape/operation_schemas.py` by `tools/generate_operations_doc.py`. Regenerate from the checkout root with
> `runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\pythonw.exe -B tools\generate_operations_doc.py > runtime\test-tmp\operations-doc.log 2>&1`.
> `tests/test_operations_doc.py` fails when this file and the schema disagree.

One entry per operation of this build (90 operations, schema version 1, schema digest `635fd5c632167f3e`): summary, envelope, arguments, one runnable example and the error codes the schema names. Behaviour, response shapes and history are in [OPERATION_CONTRACT.md](OPERATION_CONTRACT.md); worked modeling recipes in [COOKBOOK.md](COOKBOOK.md). A running build answers `{"op": "operation_schema"}` with the full JSON schema this page summarises (argument descriptions, constraints, every example).

## Reading an entry

- **Envelope** lists the request fields besides the arguments. `document_id` comes from `new`, `open`, `inspect` or `list_documents`; `expected_revision` is the `revision` of the latest response for that document; `request_id` (bridge) is required through the bridge for retry identity and optional headless (`tools/assistant_client.py` adds one). Every operation also accepts `measure` (`false`, `true` or `"full"`; default `true`), the measurement level of the returned inspection.
- **Arguments** are sorted by name. *required* means the request is meaningless without it; a *one of* group needs at least one of its fields; *required when* depends on the mode. A default that applies only in one mode says when. Types name the shared definitions under [Types](#types).
- **Example** is the schema's first example; the native suite runs it on the named fixture (after the listed setup requests). Values in angle brackets are placeholders.
- **Schema-named errors** are only the codes this operation's schema text names (handler checks, constraints, argument and type descriptions). The list is not exhaustive: handlers raise other codes too (for example `empty_cut`, `empty_add` or `invalid_geometry` from result checks, or path errors from `save`). Every operation can also return the [common codes](#common-error-codes); see the contract's [error-code table](OPERATION_CONTRACT.md#326-error-codes) and its per-operation sections.

## Types

- `absolute_path`: Absolute file path.
- `angle` (rad): Radians: a finite number, or an angle quantity string such as "90 deg".
- `assembly_id`: Name for the created assembly object: an ASCII letter, then letters, digits or underscores (invalid_id otherwise; an existing name rejects with duplicate_id).
- `assembly_reference`: Joint connector on an assembly occurrence.
- `axis`: World line {origin, direction}; each key may be omitted (origin [0,0,0], direction [0,0,1]).
- `body`: PartDesign Body name or logical part id that receives the new work; optional when the target, support or profile owns one, or when the document has a single current part (ambiguous_body otherwise).
- `boolean`: boolean.
- `color`: RGB, each between 0 and 1.
- `direction3`: Nonzero [x, y, z] direction; normalized, so it need not be unit length.
- `expression`: Native dimensional formula over named properties and arithmetic, such as "PlateProfile.Constraints.Width / 10".
- `feature`: Name (stable ID) of an existing native object, as inspect reports it.
- `length` (mm): Millimetres: a finite number, or a length quantity string with units and arithmetic such as "1/8 in" or "12.7/2".
- `merge_scope`: "auto" (parts the tool touches; contact counts for Add) or the target parts.
- `multi_reference`: Every matching edge of the current part, re-evaluated at each managed rebuild.
- `native_reference`: Explicit native element of a feature's shape.
- `new_id`: Name for the created native object: an ASCII letter, then up to 63 letters, digits or underscores; an existing name rejects with duplicate_feature.
- `number`: Unitless finite number (booleans are not numbers).
- `origin_plane`: Body origin plane.
- `part`: Current logical part: its id (inspect studio.parts[].id) or its Body name.
- `point2` (mm): Sketch-local [x, y] in millimetres.
- `positive_angle` (rad): Positive radians, or an angle quantity string such as "180 deg".
- `positive_length` (mm): Positive millimetres: a number or a length quantity string.
- `reference`: One geometry element: {feature, subelement}, a bare selector, or {selector}.
- `result_operation`: new makes an independent part; add/remove/intersect combine with the merge scope.
- `selector`: Authored geometry query; x-kinds lists each kind's allowed keys. Unknown keys reject with invalid_selector.
- `selector_reference`: A selector wrapped as {selector: <query>}.
- `subelement`: Native element name FaceN, EdgeN or VertexN.
- `support`: Planar support: {feature} for a datum plane, {feature, subelement:"FaceN"} for a planar face of a solid in the same Body, or a face selector.
- `vector3` (mm): World [x, y, z] in millimetres.

## Example fixtures and placeholders

- Fixture `assembly`: Assembly of three occurrences of the plate fixture's Body: Base (grounded), Rotor (revolute joint Hinge to Base) and Free (unconstrained).
- Fixture `none`: No document is needed; nothing is open.
- Fixture `plate`: Legacy single-Body plate: a 60 x 40 x 6 mm Pad with a through Pocket of 8 mm diameter, plus unconsumed sketches BossProfile (6 mm circle at 10, 10 on XY), Crossing (a line on XZ crossing the XY plane at x 2) and Target (XY, holding one free native point at 4, 0 as geometry 0, added outside typed operations because no typed sketch-point operation exists).
- Fixture `studio`: Part Studio with parts Body (40 x 30 x 10 block) and Tool (10 mm cube at x 35..45, y 10..20, overlapping it), plus unconsumed sketches BossProfile, RingProfile (XZ rectangle at x 60), PathSketch (line along +X at y -20), SweepProfile (YZ circle at the path start), LoftLower and LoftUpper (on datum plane LoftPlane, 20 mm above XY).
- `<document_id>`: document_id of the fixture document.
- `<plate_file>`: the plate fixture saved as an FCStd file that is not open.
- `<project>`: an empty folder inside a granted project folder.
- `<recovery_manifest>`: a forced checkpoint manifest of the plate fixture in the session's project-recovery folder.
- `<revision>`: its current revision.
- `<step_file>`: the plate fixture exported as STEP.

## Common error codes

Clients match on `error.code`, never on the message.

- `unsupported_operation`: the `op` is not an operation of this build.
- `unknown_argument`: the request carries a field the operation does not declare (`fields`).
- `invalid_argument`: a value has the wrong type or range, or a field is missing: `reason` is `missing_required` (with `one_of:true` for an empty one-of group) or `missing_conditional`.
- `unknown_document`: `document_id` is not the UUID of a document open in this session.
- `stale_revision`: `expected_revision` is missing or is not the current revision (`expected`, `actual`).
- `unmanaged_document`: a change to a native file KurtShape does not manage; `adopt` a copy first.
- `busy`: another modeling operation is active.
- `sketch_edit_active`: a sketch or graphical edit is open; finish or cancel it first.
- `unmanaged_transaction`: a native transaction opened outside KurtShape is pending.
- `build_failed`: the native recompute failed; the change was rolled back.
- `operation_failed`: an unexpected handler error; nothing was committed.

Bridge and client outcomes (`invalid_request`, `queue_full`, `outcome_unknown`, `request_pending`, `outcome_pending`, ...) are transport results, not operation errors; see the contract's [client reconciliation](OPERATION_CONTRACT.md#325-identity-schemas-lifecycle-compact-inspect-transport-client).

## Index

- **Reads:** [assembly_candidates](#assembly_candidates), [assembly_instance_source](#assembly_instance_source), [capabilities](#capabilities), [check_geometry](#check_geometry), [diagnostics](#diagnostics), [inspect](#inspect), [list_documents](#list_documents), [list_parameters](#list_parameters), [measure](#measure), [operation_schema](#operation_schema), [orphan_helpers](#orphan_helpers), [part_inventory](#part_inventory), [preview](#preview), [request_status](#request_status), [resolve_selector](#resolve_selector)
- **View:** [render_view](#render_view), [set_view](#set_view)
- **Open or create a document:** [import_step](#import_step), [new](#new), [open](#open), [recover](#recover)
- **Modeling:** [add_arc](#add_arc), [add_circle](#add_circle), [add_line](#add_line), [add_polyline](#add_polyline), [add_rectangle](#add_rectangle), [boolean_parts](#boolean_parts), [chamfer](#chamfer), [circular_pattern_parts](#circular_pattern_parts), [create_body](#create_body), [create_helix](#create_helix), [create_parameter](#create_parameter), [create_plane](#create_plane), [create_sketch](#create_sketch), [delete_feature](#delete_feature), [delete_features](#delete_features), [delete_parameter](#delete_parameter), [delete_part](#delete_part), [duplicate_feature](#duplicate_feature), [edit_dress_up](#edit_dress_up), [edit_extrusion](#edit_extrusion), [edit_parameter](#edit_parameter), [extrude_face](#extrude_face), [fillet](#fillet), [hole](#hole), [linear_pattern_parts](#linear_pattern_parts), [loft](#loft), [mirror_parts](#mirror_parts), [move_face](#move_face), [pad](#pad), [pierce](#pierce), [pocket](#pocket), [project_geometry](#project_geometry), [rebuild](#rebuild), [rename_feature](#rename_feature), [rename_parameter](#rename_parameter), [repair_orphan_helpers](#repair_orphan_helpers), [revolve](#revolve), [rollback](#rollback), [set_expression](#set_expression), [set_parameter](#set_parameter), [set_part_appearance](#set_part_appearance), [set_sketch_support](#set_sketch_support), [shell](#shell), [sketch_circle](#sketch_circle), [sketch_rectangle](#sketch_rectangle), [split_part](#split_part), [sweep](#sweep), [transform_part](#transform_part)
- **Assembly:** [create_assembly](#create_assembly), [create_assembly_joint](#create_assembly_joint), [delete_assembly_object](#delete_assembly_object), [edit_assembly_joint](#edit_assembly_joint), [ground_assembly_instance](#ground_assembly_instance), [insert_assembly_part](#insert_assembly_part), [move_assembly_instance](#move_assembly_instance), [move_assembly_instances](#move_assembly_instances), [move_assembly_joint](#move_assembly_joint), [refresh_assembly_part](#refresh_assembly_part), [set_assembly_folders](#set_assembly_folders), [solve_assembly](#solve_assembly)
- **File lifecycle:** [adopt](#adopt), [close_document](#close_document), [export](#export), [save](#save)
- **History and sketch editing:** [begin_sketch_edit](#begin_sketch_edit), [finish_sketch_edit](#finish_sketch_edit), [redo](#redo), [undo](#undo)
- **Batch:** [batch](#batch)

## Reads

Unless an entry says otherwise: envelope: `document_id`; not undoable, not previewable, not batchable.

### assembly_candidates

Selectable native solids of an FCStd or STEP source, with final/helper/history roles. [Contract][contract-assembly]. Envelope: none; not undoable, not previewable, not batchable.

- `final_only`: boolean; default `false`
- `path`: absolute_path; **required** (missing: `invalid_assembly_source`)

Example (fixture `none`): `{"op": "assembly_candidates", "path": "<plate_file>"}`

Schema-named errors: `invalid_assembly_source`.

### assembly_instance_source

The saved source an occurrence was embedded from: path, kind (fcstd/step), whether it exists and is open. [Contract][contract-assembly-folders].

- `assembly`: string
- `instance`: string; **required** (missing: `missing_assembly_instance`)

Example (fixture `assembly`): `{"op": "assembly_instance_source", "document_id": "<document_id>", "instance": "Free"}`

Schema-named errors: `missing_assembly_instance`.

### capabilities

Contract identity, supported operations, measurement levels and limits. [Contract][contract-historical]. Envelope: none; not undoable, not previewable, not batchable.

- No arguments.

Example (fixture `none`): `{"op": "capabilities"}`

### check_geometry

Explicit cached BRepCheck of current solids, with per-result issues. [Contract][contract-30].

- `body`: body

Example (fixture `plate`): `{"op": "check_geometry", "document_id": "<document_id>"}`

Schema-named errors: `ambiguous_body`.

### diagnostics

Bounded timing samples and the checkpoint location. [Contract][contract-historical]. Envelope: none; not undoable, not previewable, not batchable.

- No arguments.

Example (fixture `none`): `{"op": "diagnostics"}`

### inspect

Read the document: features, parameters, dependencies, build status and measurements. [Contract][contract-30].

- `detail`: full / compact; default `"full"` when `features`, `parts` are absent
- `features`: array of string
- `parts`: array of string

Example (fixture `plate`): `{"op": "inspect", "document_id": "<document_id>"}`

Schema-named errors: `missing_part`, `missing_reference`.

### list_documents

Inspect every document open in this session. [Contract][contract-30]. Envelope: none; not undoable, not previewable, not batchable.

- `detail`: full / compact; default `"full"`

Example (fixture `plate`): `{"op": "list_documents", "measure": false}`

### list_parameters

The document's model parameters with values, formulas, consumers and the features and parts they affect. [Contract][contract-32-parameters].

- `names`: array of string

Example (fixture `plate`): `{"op": "list_parameters", "document_id": "<document_id>"}`

Schema-named errors: `missing_parameter`.

### measure

Measure 1-24 references in global coordinates: length/area/Ø, distances with ΔX ΔY ΔZ, angles. [Contract][contract-measure].

- `references`: array of object; **required** (missing: `invalid_argument`)

Example (fixture `plate`): `{"op": "measure", "document_id": "<document_id>", "references": [{"cap": "end", "entity_type": "face", "feature": "Pad", "kind": "created_by"}]}`

### operation_schema

Argument schemas, defaults, constraints and examples of the operations this build supports. [Contract][contract-32-bridge]. Envelope: none; not undoable, not previewable, not batchable.

- `operations`: array of string

Example (fixture `none`): `{"op": "operation_schema"}`

### orphan_helpers

Helper groups whose owning studio operation no longer exists. [Contract][contract-30].

- No arguments.

Example (fixture `plate`): `{"op": "orphan_helpers", "document_id": "<document_id>"}`

### part_inventory

Current usable solids across legacy, studio and assembly documents. [Contract][contract-assembly].

- `include_history`: boolean; default `false`

Example (fixture `plate`): `{"op": "part_inventory", "document_id": "<document_id>"}`

### preview

Evaluate a modeling proposal on a disposable clone; nothing changes. [Contract][contract-historical]. Envelope: `document_id`, `expected_revision` optional (checked when given); not undoable, not previewable, not batchable.

- `proposal`: object; **required** (missing: `unsupported_preview`)

Example (fixture `plate`): `{"op": "preview", "document_id": "<document_id>", "proposal": {"op": "set_parameter", "feature": "Pad", "parameter": "Length", "value": 8}}`

Schema-named errors: `unsupported_preview`.

### request_status

Status of a bridge request_id in this session's ledger, with its retained response. [Contract][contract-historical]. Envelope: none; not undoable, not previewable, not batchable.

- `request_id`: string

Example (fixture `none`): `{"op": "request_status", "request_id": "agent-0001"}`

### resolve_selector

Matched native elements of a selector, with part identity and geometry summaries. [Contract][contract-selectors].

- `selector`: selector; **required** (missing: `invalid_selector`)

Example (fixture `plate`): `{"op": "resolve_selector", "document_id": "<document_id>", "selector": {"cap": "end", "entity_type": "face", "feature": "Pad", "kind": "created_by"}}`

Schema-named errors: `invalid_selector`.

## View

Unless an entry says otherwise: envelope: `document_id`, `expected_revision` optional (checked when given), `request_id` (bridge); not undoable, not previewable, not batchable.

### render_view

Render orthographic PNG images (views, sections, labelled highlights) of the current parts; read-only, ledger-tracked. [Contract][contract-32-render].

- `edges`: boolean; default `true`
- `frame`: included / model / highlights or object; default `"included"`
- `highlights`: array of object
- `labels`: boolean; default `true`
- `layout`: separate / sheet; default `"separate"`
- `part_labels`: boolean; default `false`
- `parts`: all / visible or array of string; default `"all"`
- `quality`: standard / draft; default `"standard"`
- `section`: object
- `size`: array of (integer 128..2048) x 2; default `[1024, 768]` unless `layout` is `"sheet"`
- `sketches`: auto / none / include; default `"auto"`
- `views`: array of (iso / front / back / right / left / top / bottom / section or object); default `["iso"]` when `section` is absent

Example (fixture `plate`): `{"op": "render_view", "document_id": "<document_id>", "quality": "draft", "size": [320, 240]}`

Schema-named errors: `invalid_selector`, `missing_part`, `render_busy`.

### set_view

Aim the running app's 3D view of the document (orthographic camera); the camera is saved in the FCStd and restored on open. Never changes the document; headless reports applied:false. [Contract][contract-set-view].

- `frame`: model or object; default `"model"`
- `view`: iso / front / back / right / left / top / bottom or object; default `"iso"`

Example (fixture `plate`): `{"op": "set_view", "document_id": "<document_id>", "view": "top"}`

## Open or create a document

Unless an entry says otherwise: envelope: `request_id` (bridge); not undoable, not previewable, not batchable.

### import_step

New managed unsaved document from a STEP file: one Body per solid. [Contract][contract-30].

- `detail`: full / compact
- `path`: absolute_path; **required** (missing: `invalid_argument`)

Example (fixture `none`): `{"op": "import_step", "path": "<step_file>"}`

### new

New managed document with one empty Body. [Contract][contract-intro].

- `detail`: full / compact
- `name`: string; default `"New part"`

Example (fixture `none`): `{"op": "new", "name": "Bracket"}`

### open

Open an existing native FCStd file. [Contract][contract-intro].

- `detail`: full / compact
- `path`: absolute_path; **required**

Example (fixture `none`): `{"op": "open", "path": "<plate_file>"}`

Schema-named errors: `duplicate_document_id`.

### recover

Open a verified checkpoint as a new unsaved document. [Contract][contract-historical].

- `detail`: full / compact
- `path`: absolute_path; **required**

Example (fixture `none`): `{"op": "recover", "path": "<recovery_manifest>"}`

## Modeling

Unless an entry says otherwise: envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, previewable, batchable.

### add_arc

Append a fully constrained counter-clockwise circular arc. [Contract][contract-30].

- `body`: body
- `construction`: boolean; default `false`
- `cx`: length; **required** (missing: `invalid_argument`)
- `cy`: length; **required** (missing: `invalid_argument`)
- `detail`: full / compact
- `end_angle`: angle; required when centre form (no x1/y1/x2/y2 given)
- `radius`: positive_length; required when centre form (no x1/y1/x2/y2 given)
- `sketch`: feature; **required**
- `start_angle`: angle; required when centre form (no x1/y1/x2/y2 given)
- `x1`: length; required when endpoint form
- `x2`: length; required when endpoint form
- `y1`: length; required when endpoint form
- `y2`: length; required when endpoint form

Example (fixture `plate`): `{"op": "add_arc", "document_id": "<document_id>", "expected_revision": "<revision>", "cx": 20, "cy": -10, "end_angle": "90 deg", "radius": 5, "sketch": "Target", "start_angle": 0}`

Schema-named errors: `ambiguous_body`.

### add_circle

Append a constrained circle to an existing sketch. [Contract][contract-30].

- `body`: body
- `construction`: boolean; default `false`
- `detail`: full / compact
- `diameter`: positive_length; **required**
- `sketch`: feature; **required**
- `x`: length; **required**
- `y`: length; **required**

Example (fixture `plate`): `{"op": "add_circle", "document_id": "<document_id>", "expected_revision": "<revision>", "diameter": 5, "sketch": "Target", "x": 20, "y": 20}`

Schema-named errors: `ambiguous_body`.

### add_line

Append a line with driving endpoint coordinates. [Contract][contract-30].

- `body`: body
- `construction`: boolean; default `false`
- `detail`: full / compact
- `sketch`: feature; **required**
- `x1`: length; **required**
- `x2`: length; **required**
- `y1`: length; **required**
- `y2`: length; **required**

Example (fixture `plate`): `{"op": "add_line", "document_id": "<document_id>", "expected_revision": "<revision>", "sketch": "Target", "x1": 10, "x2": 25, "y1": 30, "y2": 30}`

Schema-named errors: `ambiguous_body`.

### add_polyline

Append connected line segments joined by native coincidences. [Contract][contract-30].

- `body`: body
- `closed`: boolean; default `false`
- `construction`: boolean; default `false`
- `detail`: full / compact
- `points`: array of point2; **required** (missing: `invalid_argument`)
- `sketch`: feature; **required**

Example (fixture `plate`): `{"op": "add_polyline", "document_id": "<document_id>", "expected_revision": "<revision>", "closed": true, "points": [[30, 30], [40, 30], [40, 40]], "sketch": "Target"}`

Schema-named errors: `ambiguous_body`.

### add_rectangle

Append a constrained rectangle to an existing sketch. [Contract][contract-30].

- `body`: body
- `construction`: boolean; default `false`
- `detail`: full / compact
- `height`: positive_length; **required**
- `sketch`: feature; **required**
- `width`: positive_length; **required**
- `x`: length; default `0`
- `y`: length; default `0`

Example (fixture `plate`): `{"op": "add_rectangle", "document_id": "<document_id>", "expected_revision": "<revision>", "height": 3, "sketch": "Target", "width": 4, "x": 10, "y": 10}`

Schema-named errors: `ambiguous_body`.

### boolean_parts

Union, subtract or intersect independent parts. [Contract][contract-studio].

- `body`: body
- `detail`: full / compact
- `id`: new_id; id `StudioFeature` when omitted
- `keep_tools`: boolean; default `false`
- `kind`: union / subtract / intersect; default `"union"`
- `name`: string
- `source_feature_id`: string
- `source_feature_name`: string
- `targets`: array of part; **required** (missing: `invalid_argument`)
- `tools`: array of part; **required** (missing: `invalid_argument`)

Example (fixture `studio`): `{"op": "boolean_parts", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Joined", "kind": "subtract", "targets": ["Body"], "tools": ["Tool"]}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`.

### chamfer

Native equal-distance chamfer on edges of the current part. [Contract][contract-multi].

- `body`: body
- `detail`: full / compact
- `edges`: array of (reference or multi_reference); **required** (missing: `invalid_argument`)
- `id`: new_id; id `Chamfer` when omitted
- `part`: part
- `size`: positive_length; **required** (missing: `invalid_argument`)
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `plate`): `{"op": "chamfer", "document_id": "<document_id>", "expected_revision": "<revision>", "edges": [{"kind": "closest", "point": [0, 20, 6], "query": {"entity_type": "edge", "kind": "owned_by", "part": "Body"}}], "id": "EdgeBevel", "size": 1}`

Schema-named errors: `ambiguous_body`, `ambiguous_reference`, `duplicate_feature`, `invalid_selector`.

### circular_pattern_parts

Rotated copies of parts about an axis. [Contract][contract-patterns].

- `angle`: positive_angle; default `"360 deg"`
- `axis`: axis; default `{"direction": [0, 0, 1], "origin": [0, 0, 0]}`
- `body`: body
- `count`: integer 2..100; default `2`
- `detail`: full / compact
- `id`: new_id; id `StudioFeature` when omitted
- `include_source`: boolean; default `false`
- `merge_scope`: merge_scope; default `"auto"`
- `name`: string
- `operation`: result_operation; default `"new"`
- `parts`: array of part; **required** (missing: `invalid_argument`)
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `studio`): `{"op": "circular_pattern_parts", "document_id": "<document_id>", "expected_revision": "<revision>", "count": 3, "id": "Around", "parts": ["Tool"]}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`.

### create_body

New native PartDesign Body. [Contract][contract-historical].

- `detail`: full / compact
- `id`: new_id; id `Body` when omitted
- `name`: string
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `plate`): `{"op": "create_body", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Second", "name": "Second part"}`

Schema-named errors: `duplicate_feature`.

### create_helix

Native top-level helix for sweep paths. [Contract][contract-31].

- `axis`: axis; default `{"direction": [0, 0, 1], "origin": [0, 0, 0]}`
- `detail`: full / compact
- `handedness`: right / left; default `"right"`
- `height`: positive_length; **required** (missing: `invalid_argument`)
- `id`: new_id; id `Helix` when omitted
- `name`: string
- `pitch`: positive_length; **required** (missing: `invalid_argument`)
- `radius`: positive_length; **required** (missing: `invalid_argument`)
- `segment_length`: number; default `1`
- `source_feature_id`: string
- `source_feature_name`: string
- `start_angle`: angle; default `0`
- `x_direction`: direction3

Example (fixture `plate`): `{"op": "create_helix", "document_id": "<document_id>", "expected_revision": "<revision>", "height": 20, "id": "Coil", "pitch": 5, "radius": 10}`

Schema-named errors: `duplicate_feature`.

### create_parameter

Create a model parameter (length, angle or number) with a value, a formula over other parameters, or by promoting existing dimensions (bind). [Contract][contract-32-parameters].

- `bind`: array of object
- `detail`: full / compact
- `expression`: string
- `name`: string; **required**
- `type`: length / angle / number
- `value`: number or string

Example (fixture `plate`): `{"op": "create_parameter", "document_id": "<document_id>", "expected_revision": "<revision>", "name": "plate_width", "type": "length", "value": 60}`

Schema-named errors: `invalid_parameter_name`.

### create_plane

Native datum plane: offset, point-normal, three-point or line-angle. [Contract][contract-planes].

- `angle`: angle; default `0` when any of `axis`, `reference_normal` is given
- `axis`: axis or reference; required when line-angle mode
- `base_plane`: origin_plane; default `"XY"` when `support`, `origin`, `normal`, `x_direction`, `points`, `axis`, `reference_normal`, `angle` are absent
- `body`: body
- `detail`: full / compact
- `id`: new_id; id `Plane` when omitted
- `name`: string
- `normal`: direction3; required when point-normal mode
- `offset`: length; default `0`
- `origin`: vector3; required when point-normal mode
- `points`: array of vector3 x 3; required when three-point mode
- `reference_normal`: direction3; required when line-angle mode
- `source_feature_id`: string
- `source_feature_name`: string
- `support`: support
- `x_direction`: direction3

Example (fixture `plate`): `{"op": "create_plane", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "MidPlane", "normal": [0, 1, 0], "origin": [0, 20, 0]}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`.

### create_sketch

Empty attached native sketch on an origin plane, datum plane or planar face. [Contract][contract-30].

- `body`: body
- `detail`: full / compact
- `id`: new_id; id `Sketch` when omitted
- `plane`: origin_plane; default `"XY"` when `support` is absent
- `source_feature_id`: string
- `source_feature_name`: string
- `support`: support

Example (fixture `plate`): `{"op": "create_sketch", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "FrontSketch", "plane": "XZ"}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`.

### delete_feature

Delete one feature; dependents need cascade. [Contract][contract-30]. Envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, previewable, not batchable.

- `body`: body
- `cascade`: boolean; default `false`
- `detail`: full / compact
- `feature`: feature; **required**

Example (fixture `plate`): `{"op": "delete_feature", "document_id": "<document_id>", "expected_revision": "<revision>", "feature": "Pocket"}`

Schema-named errors: `ambiguous_body`.

### delete_features

Delete a validated set of features in one transaction. [Contract][contract-30]. Envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, previewable, not batchable.

- `body`: body
- `cascade`: boolean; default `false`
- `detail`: full / compact
- `features`: array of feature; **required** (missing: `invalid_argument`)

Example (fixture `plate`): `{"op": "delete_features", "document_id": "<document_id>", "expected_revision": "<revision>", "features": ["Pocket", "HoleProfile"]}`

Schema-named errors: `ambiguous_body`, `dependent_features`.

### delete_parameter

Delete a parameter; consumers reject unless freeze_consumers keeps their current values. [Contract][contract-32-parameters]. Envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, previewable, not batchable.

- `detail`: full / compact
- `freeze_consumers`: boolean; default `false`
- `name`: string; **required**

Example (fixture `plate`, after `{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 60}`): `{"op": "delete_parameter", "document_id": "<document_id>", "expected_revision": "<revision>", "name": "plate_width"}`

Schema-named errors: `parameter_in_use`.

### delete_part

Consume a current part in history (undo restores it). [Contract][contract-studio].

- `body`: body
- `detail`: full / compact
- `id`: new_id; id `StudioFeature` when omitted
- `name`: string
- `part`: part; **required** (missing: `missing_part`)
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `studio`): `{"op": "delete_part", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "RemoveTool", "part": "Tool"}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `missing_part`.

### duplicate_feature

Copy a sketch, Pad or Pocket in its Body, keeping links. [Contract][contract-historical]. Envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, previewable, not batchable.

- `body`: body
- `detail`: full / compact
- `feature`: feature; **required**
- `fingerprint`: string

Example (fixture `plate`): `{"op": "duplicate_feature", "document_id": "<document_id>", "expected_revision": "<revision>", "feature": "PlateProfile"}`

Schema-named errors: `ambiguous_body`.

### edit_dress_up

Change the edges, size or formula of an existing fillet or chamfer in place. [Contract][contract-multi].

- `body`: body
- `detail`: full / compact
- `edges`: array of (reference or multi_reference)
- `expression`: expression or null
- `feature`: feature; **required** (missing: `missing_reference`)
- `radius`: positive_length
- `size`: positive_length

Example (fixture `plate`, after `{"op": "fillet", "edges": [{"kind": "closest", "point": [0, 20, 6], "query": {"entity_type": "edge", "kind": "owned_by", "part": "Body"}}], "id": "EdgeRound", "radius": 1}`): `{"op": "edit_dress_up", "document_id": "<document_id>", "expected_revision": "<revision>", "feature": "EdgeRound", "radius": 2}`

Schema-named errors: `ambiguous_body`, `ambiguous_reference`, `invalid_selector`, `missing_reference`.

### edit_extrusion

Edit an Extrude/Remove in place: depth, depth formula, direction, end condition. [Contract][contract-30].

- `body`: body
- `detail`: full / compact
- `end_type`: blind / through_all / up_to_face
- `expression`: expression or null
- `feature`: feature; **required** (missing: `missing_reference`)
- `length`: positive_length
- `reversed`: boolean

Example (fixture `plate`): `{"op": "edit_extrusion", "document_id": "<document_id>", "expected_revision": "<revision>", "feature": "Pad", "length": 8}`

Schema-named errors: `ambiguous_body`, `expression_driven`, `missing_reference`.

### edit_parameter

Change a parameter's value or formula; dependents rebuild, unchanged consumers are pruned. [Contract][contract-32-parameters].

- `detail`: full / compact
- `expression`: string or null
- `name`: string; **required**
- `value`: number or string

Example (fixture `plate`, after `{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 60}`): `{"op": "edit_parameter", "document_id": "<document_id>", "expected_revision": "<revision>", "name": "plate_width", "value": 62}`

Schema-named errors: `expression_driven`.

### extrude_face

Extrude one planar face into a studio result. [Contract][contract-studio].

- `body`: body
- `detail`: full / compact
- `face`: reference; **required**
- `id`: new_id; id `ExtrudeFace` when omitted
- `length`: positive_length; **required** (missing: `invalid_argument`)
- `merge_scope`: merge_scope; default `"auto"`
- `name`: string
- `operation`: result_operation; default `"add"`
- `refine`: boolean; default `true`
- `reversed`: boolean
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `plate`): `{"op": "extrude_face", "document_id": "<document_id>", "expected_revision": "<revision>", "face": {"cap": "end", "entity_type": "face", "feature": "Pad", "kind": "created_by"}, "id": "Raise", "length": 2}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`.

### fillet

Native fillet on edges of the current part. [Contract][contract-multi].

- `body`: body
- `detail`: full / compact
- `edges`: array of (reference or multi_reference); **required** (missing: `invalid_argument`)
- `id`: new_id; id `Fillet` when omitted
- `part`: part
- `radius`: positive_length; **required** (missing: `invalid_argument`)
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `plate`): `{"op": "fillet", "document_id": "<document_id>", "expected_revision": "<revision>", "edges": [{"kind": "closest", "point": [0, 20, 6], "query": {"entity_type": "edge", "kind": "owned_by", "part": "Body"}}], "id": "EdgeRound", "radius": 1}`

Schema-named errors: `ambiguous_body`, `ambiguous_reference`, `duplicate_feature`, `invalid_geometry`, `invalid_selector`.

### hole

Native PartDesign Hole at a sketch's circles and points. [Contract][contract-studio].

- `body`: body
- `counterbore`: object
- `countersink`: object
- `depth`: positive_length; required when end_type blind (the default)
- `detail`: full / compact
- `diameter`: positive_length; **required** (missing: `invalid_argument`)
- `direction`: along / against
- `end_type`: blind / through_all; default `"blind"`
- `id`: new_id; id `Hole, Hole001, ...` when omitted
- `part`: part
- `point_angle`: angle or "flat"; default `"118 deg"` unless `end_type` is `"through_all"`
- `reversed`: boolean; default `false`
- `sketch`: feature; **required** (missing: `missing_reference`)
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `plate`): `{"op": "hole", "document_id": "<document_id>", "expected_revision": "<revision>", "depth": 4, "diameter": 3, "reversed": true, "sketch": "BossProfile"}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `empty_cut`, `missing_reference`.

### linear_pattern_parts

Linear copies of parts, optionally combined with a merge scope. [Contract][contract-patterns].

- `body`: body
- `count`: integer 2..100; default `2`
- `detail`: full / compact
- `direction`: direction3; default `[1, 0, 0]`
- `id`: new_id; id `StudioFeature` when omitted
- `include_source`: boolean; default `false`
- `merge_scope`: merge_scope; default `"auto"`
- `name`: string
- `operation`: result_operation; default `"new"`
- `parts`: array of part; **required** (missing: `invalid_argument`)
- `source_feature_id`: string
- `source_feature_name`: string
- `spacing`: positive_length; **required** (missing: `invalid_argument`)

Example (fixture `studio`): `{"op": "linear_pattern_parts", "document_id": "<document_id>", "expected_revision": "<revision>", "direction": [0, 1, 0], "id": "Row", "parts": ["Tool"], "spacing": 40}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`.

### loft

Loft through ordered sketch sections into a studio result. [Contract][contract-studio].

- `body`: body
- `closed`: boolean; default `false`
- `detail`: full / compact
- `id`: new_id; id `StudioFeature` when omitted
- `merge_scope`: merge_scope; default `"auto"`
- `name`: string
- `operation`: result_operation; default `"new"`
- `refine`: boolean; default `true`
- `ruled`: boolean; default `false`
- `sections`: array of feature; **required** (missing: `invalid_argument`)
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `studio`): `{"op": "loft", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Taper", "sections": ["LoftLower", "LoftUpper"]}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`.

### mirror_parts

Mirrored copies of parts. [Contract][contract-patterns].

- `body`: body
- `detail`: full / compact
- `id`: new_id; id `StudioFeature` when omitted
- `include_source`: boolean; default `false`
- `merge_scope`: merge_scope; default `"auto"`
- `name`: string
- `normal`: direction3; default `[1, 0, 0]` when `plane` is absent
- `operation`: result_operation; default `"new"`
- `origin`: vector3; default `[0, 0, 0]` when `plane` is absent
- `parts`: array of part; **required** (missing: `invalid_argument`)
- `plane`: reference
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `studio`): `{"op": "mirror_parts", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Mirrored", "normal": [1, 0, 0], "origin": [0, 0, 0], "parts": ["Tool"]}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`.

### move_face

Offset parallel planar faces of a part. [Contract][contract-studio].

- `body`: body
- `detail`: full / compact
- `distance`: length; **required** (missing: `invalid_argument`)
- `faces`: array of reference; **required** (missing: `invalid_argument`)
- `id`: new_id; id `MoveFace` when omitted
- `name`: string
- `part`: part
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `plate`): `{"op": "move_face", "document_id": "<document_id>", "expected_revision": "<revision>", "distance": 1, "faces": [{"cap": "end", "entity_type": "face", "feature": "Pad", "kind": "created_by"}], "id": "Thicken"}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`.

### pad

Extrude (native Pad, or a studio result with operation/merge_scope). [Contract][contract-studio].

- `body`: body
- `detail`: full / compact
- `direction`: along / against
- `end_type`: blind / through_all / up_to_face; default `"blind"` when `up_to_face` is absent
- `face`: reference; **one of** this or `profile`
- `id`: new_id; id `Pad` when omitted
- `length`: positive_length; required when blind end (end_type blind, the default) without up_to_face
- `merge_scope`: merge_scope; default `"auto"` when `operation` is given
- `name`: string
- `operation`: result_operation; default `"new"` when `merge_scope` is given
- `profile`: feature; **one of** this or `face`
- `refine`: boolean; default `true` when any of `operation`, `merge_scope` is given
- `reversed`: boolean; default `false`
- `source_feature_id`: string
- `source_feature_name`: string
- `up_to_face`: reference; required when end_type up_to_face

Example (fixture `plate`): `{"op": "pad", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Boss", "length": 10, "profile": "BossProfile"}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `empty_add`, `empty_merge_scope`, `invalid_selector`.

### pierce

Coincide a sketch point with the crossing of a curve edge and the sketch plane. [Contract][contract-historical].

- `body`: body
- `detail`: full / compact
- `geometry`: integer 0..; **required**
- `point`: 1 / 2 / 3; default `1`
- `sketch`: feature; **required**
- `subelement`: string; required when target is a feature ID (a selector target supplies it)
- `target`: feature or selector or selector_reference; **required**

Example (fixture `plate`): `{"op": "pierce", "document_id": "<document_id>", "expected_revision": "<revision>", "geometry": 0, "point": 1, "sketch": "Target", "subelement": "Edge1", "target": "Crossing"}`

Schema-named errors: `ambiguous_body`, `ambiguous_intersection`, `invalid_selector`.

### pocket

Remove (native Pocket, or a studio result with operation/merge_scope). [Contract][contract-studio].

- `body`: body
- `detail`: full / compact
- `direction`: along / against
- `end_type`: blind / through_all / up_to_face
- `face`: reference; **one of** this or `profile`
- `id`: new_id; id `Pocket` when omitted
- `length`: positive_length; required when blind cut (through_all false, end_type not through_all, no up_to_face)
- `merge_scope`: merge_scope; default `"auto"` when `operation` is given
- `name`: string
- `operation`: result_operation; default `"remove"` when `merge_scope` is given
- `profile`: feature; **one of** this or `face`
- `refine`: boolean; default `true` when any of `operation`, `merge_scope` is given
- `reversed`: boolean
- `source_feature_id`: string
- `source_feature_name`: string
- `through_all`: boolean; default `true` when `up_to_face` is absent
- `up_to_face`: reference; required when end_type up_to_face

Example (fixture `plate`): `{"op": "pocket", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Recess", "length": 3, "profile": "BossProfile", "through_all": false}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `empty_cut`, `empty_merge_scope`, `invalid_selector`.

### project_geometry

Project associated edges into a sketch as defining or reference geometry. [Contract][contract-studio].

- `body`: body
- `defining`: boolean; default `true`
- `detail`: full / compact
- `references`: array of reference; **required** (missing: `invalid_argument`)
- `sketch`: feature; **required**

Example (fixture `plate`): `{"op": "project_geometry", "document_id": "<document_id>", "expected_revision": "<revision>", "references": [{"kind": "closest", "point": [60, 20, 0], "query": {"entity_type": "edge", "kind": "owned_by", "part": "Body"}}], "sketch": "Target"}`

Schema-named errors: `ambiguous_body`, `invalid_selector`.

### rebuild

Touch native modeling features and recompute. [Contract][contract-30]. Envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, not previewable, not batchable.

- `detail`: full / compact

Example (fixture `plate`): `{"op": "rebuild", "document_id": "<document_id>", "expected_revision": "<revision>"}`

### rename_feature

Change a feature's, Body's or assembly object's label, keeping its ID. [Contract][contract-30].

- `body`: body
- `detail`: full / compact
- `feature`: feature; **required**
- `name`: string; **required**

Example (fixture `plate`): `{"op": "rename_feature", "document_id": "<document_id>", "expected_revision": "<revision>", "feature": "Pad", "name": "Plate body"}`

Schema-named errors: `ambiguous_body`.

### rename_parameter

Rename a parameter; every consumer formula is rewritten natively and verified. [Contract][contract-32-parameters]. Envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, previewable, not batchable.

- `detail`: full / compact
- `name`: string; **required**
- `new_name`: string; **required**

Example (fixture `plate`, after `{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 60}`): `{"op": "rename_parameter", "document_id": "<document_id>", "expected_revision": "<revision>", "name": "plate_width", "new_name": "width"}`

Schema-named errors: `rename_failed`.

### repair_orphan_helpers

Remove unconsumed leftover helper groups in one undoable transaction. [Contract][contract-30]. Envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, previewable, not batchable.

- `body`: body
- `detail`: full / compact
- `owners`: array of string

No schema example (none runs on the fixtures); the bare request is `{"op": "repair_orphan_helpers", "document_id": "<document_id>", "expected_revision": "<revision>"}`

Schema-named errors: `ambiguous_body`, `no_orphans`.

### revolve

Revolve a sketch profile into a studio result. [Contract][contract-studio].

- `angle`: positive_angle; default `"360 deg"`
- `axis`: axis or reference; default `{"direction": [0, 0, 1], "origin": [0, 0, 0]}`
- `body`: body
- `detail`: full / compact
- `id`: new_id; id `StudioFeature` when omitted
- `merge_scope`: merge_scope; default `"auto"`
- `name`: string
- `operation`: result_operation; default `"new"`
- `profile`: feature; **required**
- `refine`: boolean; default `true`
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `studio`): `{"op": "revolve", "document_id": "<document_id>", "expected_revision": "<revision>", "angle": "180 deg", "id": "Ring", "profile": "RingProfile"}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`.

### rollback

Move the history rollback bar; later features are held. [Contract][contract-studio]. Envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, previewable, not batchable.

- `body`: body
- `detail`: full / compact
- `index`: integer 0..; **required** (missing: `invalid_argument`)

Example (fixture `studio`): `{"op": "rollback", "document_id": "<document_id>", "expected_revision": "<revision>", "index": 1}`

Schema-named errors: `ambiguous_body`.

### set_expression

Set or clear a native dimensional formula. [Contract][contract-historical].

- `body`: body
- `detail`: full / compact
- `expression`: expression or null; default `null`
- `feature`: feature; **required**
- `parameter`: string; **required**

Example (fixture `plate`): `{"op": "set_expression", "document_id": "<document_id>", "expected_revision": "<revision>", "expression": "PlateProfile.Constraints.Width / 10", "feature": "Pad", "parameter": "Length"}`

Schema-named errors: `ambiguous_body`.

### set_parameter

Set a driving dimension or numeric feature parameter. [Contract][contract-30].

- `body`: body
- `detail`: full / compact
- `feature`: feature; **required**
- `parameter`: string; **required**
- `value`: number or string; **required**

Example (fixture `plate`): `{"op": "set_parameter", "document_id": "<document_id>", "expected_revision": "<revision>", "feature": "Pad", "parameter": "Length", "value": 8}`

Schema-named errors: `ambiguous_body`, `expression_driven`.

### set_part_appearance

Part name, visibility and colour (visibility never removes a part from export). [Contract][contract-studio].

- `body`: body
- `color`: color
- `detail`: full / compact
- `name`: string
- `part`: part; **required** (missing: `missing_part`)
- `visible`: boolean

Example (fixture `studio`): `{"op": "set_part_appearance", "document_id": "<document_id>", "expected_revision": "<revision>", "color": [0.8, 0.2, 0.2], "part": "Tool"}`

Schema-named errors: `ambiguous_body`, `missing_part`.

### set_sketch_support

Replace a sketch's support, keeping its local geometry, constraints and expressions. [Contract][contract-30].

- `body`: body
- `detail`: full / compact
- `plane`: origin_plane
- `sketch`: feature; **required**
- `support`: support

Example (fixture `plate`): `{"op": "set_sketch_support", "document_id": "<document_id>", "expected_revision": "<revision>", "plane": "XZ", "sketch": "Target"}`

Schema-named errors: `ambiguous_body`, `invalid_selector`.

### shell

Native thickness (shell) removing the selected faces. [Contract][contract-studio].

- `body`: body
- `detail`: full / compact
- `faces`: array of reference; **required** (missing: `invalid_argument`)
- `id`: new_id; id `Shell` when omitted
- `part`: part
- `reversed`: boolean; default `false`
- `source_feature_id`: string
- `source_feature_name`: string
- `thickness`: positive_length; **required** (missing: `invalid_argument`)

Example (fixture `plate`): `{"op": "shell", "document_id": "<document_id>", "expected_revision": "<revision>", "faces": [{"cap": "end", "entity_type": "face", "feature": "Pad", "kind": "created_by"}], "id": "Hollow", "thickness": 1}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`.

### sketch_circle

New sketch holding a constrained circle. [Contract][contract-30].

- `body`: body
- `center_on`: feature
- `detail`: full / compact
- `diameter`: positive_length; **required**
- `id`: new_id; id `Circle` when omitted
- `plane`: origin_plane; default `"XY"` when `support` is absent
- `source_feature_id`: string
- `source_feature_name`: string
- `support`: support
- `x`: length; **required**
- `y`: length; **required**

Example (fixture `plate`): `{"op": "sketch_circle", "document_id": "<document_id>", "expected_revision": "<revision>", "diameter": 4, "id": "Bore", "plane": "XZ", "x": 10, "y": 3}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`.

### sketch_rectangle

New sketch holding a closed, fully constrained rectangle with Width/Height dimensions. [Contract][contract-30].

- `body`: body
- `detail`: full / compact
- `height`: positive_length; **required**
- `id`: new_id; id `Rectangle` when omitted
- `plane`: origin_plane; default `"XY"` when `support` is absent
- `source_feature_id`: string
- `source_feature_name`: string
- `support`: support
- `width`: positive_length; **required**
- `x`: length; default `0`
- `y`: length; default `0`

Example (fixture `plate`): `{"op": "sketch_rectangle", "document_id": "<document_id>", "expected_revision": "<revision>", "height": 5, "id": "Tab", "plane": "XZ", "width": 10, "x": 5, "y": 5}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`.

### split_part

Split a part by a plane into two editable parts. [Contract][contract-studio].

- `body`: body
- `detail`: full / compact
- `face`: reference
- `id`: new_id; id `StudioFeature` when omitted
- `name`: string
- `part`: part; **required** (missing: `missing_part`)
- `plane`: object
- `sketch`: feature
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `studio`): `{"op": "split_part", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Halves", "part": "Body", "plane": {"normal": [1, 0, 0], "origin": [20, 0, 0]}}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`, `missing_part`.

### sweep

Sweep a sketch profile along a path into a studio result. [Contract][contract-studio].

- `body`: body
- `detail`: full / compact
- `frenet`: boolean; default `false`
- `id`: new_id; id `StudioFeature` when omitted
- `merge_scope`: merge_scope; default `"auto"`
- `name`: string
- `operation`: result_operation; default `"new"`
- `path`: feature or reference; **required** (missing: `missing_reference`)
- `profile`: feature; **required**
- `refine`: boolean; default `true`
- `source_feature_id`: string
- `source_feature_name`: string

Example (fixture `studio`): `{"op": "sweep", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Rail", "path": "PathSketch", "profile": "SweepProfile"}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `invalid_selector`, `missing_reference`.

### transform_part

Move, rotate or copy a part. [Contract][contract-studio].

- `body`: body
- `coordinate_system`: object
- `copy`: boolean; default `false`
- `detail`: full / compact
- `id`: new_id; id `StudioFeature` when omitted
- `name`: string
- `part`: part; **required** (missing: `missing_part`)
- `rotation`: object; default `{"angle": 0, "axis": [0, 0, 1]}`
- `source_feature_id`: string
- `source_feature_name`: string
- `translation`: vector3; default `[0, 0, 0]`

Example (fixture `studio`): `{"op": "transform_part", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Moved", "part": "Tool", "translation": [0, 40, 0]}`

Schema-named errors: `ambiguous_body`, `duplicate_feature`, `missing_part`.

## Assembly

Unless an entry says otherwise: envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, not previewable, not batchable.

### create_assembly

Create the document's native assembly and joint group. [Contract][contract-assembly].

- `detail`: full / compact
- `folder`: string or null
- `id`: assembly_id; id `Assembly` when omitted
- `name`: string; default `"Assembly"`

Example (fixture `plate`): `{"op": "create_assembly", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Assembly", "name": "Plate assembly"}`

Schema-named errors: `duplicate_id`, `invalid_id`.

### create_assembly_joint

Native joint between two occurrences, then solve. [Contract][contract-assembly].

- `assembly`: string
- `detail`: full / compact
- `first`: assembly_reference; **required** (missing: `invalid_assembly_reference`)
- `id`: assembly_id; id `FixedJoint, RevoluteJoint or SliderJoint` when omitted
- `joint_type`: fixed / revolute / slider; **required** (missing: `invalid_assembly_joint_type`)
- `name`: string
- `second`: assembly_reference; **required** (missing: `invalid_assembly_reference`)

Example (fixture `assembly`): `{"op": "create_assembly_joint", "document_id": "<document_id>", "expected_revision": "<revision>", "first": {"instance": "Base", "subelement": ""}, "id": "FreeFix", "joint_type": "fixed", "second": {"instance": "Free", "subelement": ""}}`

Schema-named errors: `duplicate_id`, `invalid_assembly_joint_type`, `invalid_assembly_reference`, `invalid_id`.

### delete_assembly_object

Remove a joint or occurrence; dependent joints need cascade. [Contract][contract-assembly].

- `assembly`: string
- `cascade`: boolean; default `false`
- `detail`: full / compact
- `feature`: feature; **required** (missing: `unsupported_assembly_delete`)

Example (fixture `assembly`): `{"op": "delete_assembly_object", "document_id": "<document_id>", "expected_revision": "<revision>", "feature": "Hinge"}`

Schema-named errors: `unsupported_assembly_delete`.

### edit_assembly_joint

Change a joint's references, type or label and solve. [Contract][contract-assembly].

- `assembly`: string
- `detail`: full / compact
- `first`: assembly_reference
- `joint`: string; **required** (missing: `missing_assembly_joint`)
- `joint_type`: fixed / revolute / slider
- `name`: string
- `second`: assembly_reference

Example (fixture `assembly`): `{"op": "edit_assembly_joint", "document_id": "<document_id>", "expected_revision": "<revision>", "joint": "Hinge", "name": "Main hinge"}`

Schema-named errors: `missing_assembly_joint`.

### ground_assembly_instance

Make one occurrence the grounded reference and solve. [Contract][contract-assembly].

- `assembly`: string
- `detail`: full / compact
- `instance`: string; **required** (missing: `missing_assembly_instance`)

Example (fixture `assembly`): `{"op": "ground_assembly_instance", "document_id": "<document_id>", "expected_revision": "<revision>", "instance": "Free"}`

Schema-named errors: `missing_assembly_instance`.

### insert_assembly_part

Embed a source solid snapshot and add one occurrence (the first is grounded). [Contract][contract-assembly].

- `assembly`: string
- `detail`: full / compact
- `folder`: string or null
- `id`: assembly_id; id `Instance` when omitted
- `name`: string
- `path`: absolute_path; **required** (missing: `invalid_assembly_source`)
- `source_id`: string; **required** (missing: `missing_assembly_source_part`)

Example (fixture `assembly`): `{"op": "insert_assembly_part", "document_id": "<document_id>", "expected_revision": "<revision>", "id": "Extra", "path": "<plate_file>", "source_id": "Body"}`

Schema-named errors: `duplicate_id`, `invalid_assembly_source`, `invalid_id`, `missing_assembly_source_part`.

### move_assembly_instance

Place a free occurrence and solve. [Contract][contract-assembly].

- `assembly`: string
- `detail`: full / compact
- `instance`: string; **required** (missing: `missing_assembly_instance`)
- `position_mm`: array of (number or string) x 3; **required** (missing: `invalid_assembly_motion`)
- `rotation_xyzw`: array of number x 4

Example (fixture `assembly`): `{"op": "move_assembly_instance", "document_id": "<document_id>", "expected_revision": "<revision>", "instance": "Free", "position_mm": [100, 0, 0]}`

Schema-named errors: `assembly_motion_locked`, `invalid_assembly_motion`, `missing_assembly_instance`.

### move_assembly_instances

Move occurrences into an instance-list folder (created when missing) or back to the root. [Contract][contract-assembly-folders].

- `assembly`: string
- `detail`: full / compact
- `folder`: string or null
- `instances`: array of string; **required** (missing: `missing_assembly_instance`)

Example (fixture `assembly`): `{"op": "move_assembly_instances", "document_id": "<document_id>", "expected_revision": "<revision>", "folder": "Fasteners/M3", "instances": ["Free"]}`

Schema-named errors: `missing_assembly_instance`.

### move_assembly_joint

Set a revolute or slider joint coordinate and solve. [Contract][contract-assembly].

- `assembly`: string
- `detail`: full / compact
- `joint`: string; **required** (missing: `missing_assembly_joint`)
- `value`: number or string; **required** (missing: `invalid_assembly_motion`)

Example (fixture `assembly`): `{"op": "move_assembly_joint", "document_id": "<document_id>", "expected_revision": "<revision>", "joint": "Hinge", "value": 30}`

Schema-named errors: `fixed_joint`, `invalid_assembly_motion`, `missing_assembly_joint`.

### refresh_assembly_part

Refresh an occurrence from a saved source without replacing its identity or placement. [Contract][contract-assembly].

- `assembly`: string
- `detail`: full / compact
- `folder`: string or null
- `instance`: string; **required** (missing: `missing_assembly_instance`)
- `path`: absolute_path
- `shared`: instance / all
- `source_id`: string

Example (fixture `assembly`): `{"op": "refresh_assembly_part", "document_id": "<document_id>", "expected_revision": "<revision>", "instance": "Free", "shared": "instance"}`

Schema-named errors: `missing_assembly_instance`.

### set_assembly_folders

Replace the instance-list folder tree (presentation metadata only). [Contract][contract-assembly-folders].

- `assembly`: string
- `detail`: full / compact
- `folders`: array of (object or string); **required** (missing: `invalid_assembly_folders`)
- `membership`: object

Example (fixture `assembly`): `{"op": "set_assembly_folders", "document_id": "<document_id>", "expected_revision": "<revision>", "folders": [{"children": [{"children": [], "name": "M3"}], "name": "Fasteners"}, "Frame"], "membership": {"Free": "Fasteners/M3"}}`

Schema-named errors: `invalid_assembly_folders`.

### solve_assembly

Explicit solve of the current assembly intent. [Contract][contract-assembly].

- `assembly`: string
- `detail`: full / compact

Example (fixture `assembly`): `{"op": "solve_assembly", "document_id": "<document_id>", "expected_revision": "<revision>"}`

## File lifecycle

Unless an entry says otherwise: envelope: `document_id`, `expected_revision`, `request_id` (bridge); not undoable, not previewable, not batchable.

### adopt

Save a managed copy of the document under a new path and project identity. [Contract][contract-historical].

- `detail`: full / compact
- `path`: absolute_path; **required**

Example (fixture `plate`): `{"op": "adopt", "document_id": "<document_id>", "expected_revision": "<revision>", "path": "<project>/adopted.FCStd"}`

### close_document

Close an open document; unsaved changes need discard:true, which writes a discard checkpoint first. [Contract][contract-32-bridge].

- `discard`: boolean; default `false`

Example (fixture `plate`): `{"op": "close_document", "document_id": "<document_id>", "expected_revision": "<revision>"}`

Schema-named errors: `document_in_use`, `unsaved_changes`, `user_editing`.

### export

Export current solid results with provenance; requires a current build and valid geometry checks. [Contract][contract-30].

- `body`: body
- `detail`: full / compact
- `path`: absolute_path; **required**

Example (fixture `plate`): `{"op": "export", "document_id": "<document_id>", "expected_revision": "<revision>", "path": "<project>/plate.step"}`

Schema-named errors: `ambiguous_body`.

### save

Staged native save with a recovery copy of the previous file. [Contract][contract-30].

- `detail`: full / compact
- `overwrite`: boolean; default `false`
- `path`: absolute_path; **required**

Example (fixture `plate`): `{"op": "save", "document_id": "<document_id>", "expected_revision": "<revision>", "path": "<project>/plate.FCStd"}`

Schema-named errors: `save_destination_locked`, `save_destination_other_project`.

## History and sketch editing

Unless an entry says otherwise: envelope: `document_id`, `expected_revision`, `request_id` (bridge); not undoable, not previewable, not batchable.

### begin_sketch_edit

Start an exclusive managed edit lease on a sketch. [Contract][contract-30].

- `body`: body
- `detail`: full / compact
- `feature`: feature; **required**

Example (fixture `plate`): `{"op": "begin_sketch_edit", "document_id": "<document_id>", "expected_revision": "<revision>", "feature": "Target"}`

Schema-named errors: `ambiguous_body`.

### finish_sketch_edit

Finish the managed sketch edit as one history step, or cancel it. [Contract][contract-30].

- `cancel`: boolean; default `false`
- `detail`: full / compact

Example (fixture `plate`, after `{"op": "begin_sketch_edit", "feature": "Target"}`): `{"op": "finish_sketch_edit", "document_id": "<document_id>", "expected_revision": "<revision>"}`

### redo

Native redo, or one sketch step inside a managed sketch edit. [Contract][contract-30].

- `detail`: full / compact

Example (fixture `plate`, after `{"op": "rename_feature", "feature": "Pad", "name": "Plate body"}`; `{"op": "undo"}`): `{"op": "redo", "document_id": "<document_id>", "expected_revision": "<revision>"}`

### undo

Native undo, or one sketch step inside a managed sketch edit. [Contract][contract-30].

- `detail`: full / compact

Example (fixture `plate`, after `{"op": "rename_feature", "feature": "Pad", "name": "Plate body"}`): `{"op": "undo", "document_id": "<document_id>", "expected_revision": "<revision>"}`

## Batch

Unless an entry says otherwise: envelope: `document_id`, `expected_revision`, `request_id` (bridge); undoable, previewable, not batchable.

### batch

Run 1-32 modeling steps as one native transaction: one undo step and one revision change, or nothing at all when any step or the final result check fails. [Contract][contract-32-batch].

- `detail`: full / compact
- `label`: string
- `steps`: array of object; **required**

Example (fixture `plate`): `{"op": "batch", "document_id": "<document_id>", "expected_revision": "<revision>", "label": "plate width", "steps": [{"op": "create_parameter", "name": "plate_width", "type": "length", "value": 62}, {"op": "set_expression", "expression": "plate_width", "feature": "PlateProfile", "parameter": "Width"}, {"op": "sketch_circle", "as": "spot", "diameter": 4, "id": "BatchSpot", "x": 10, "y": 10}, {"op": "add_circle", "diameter": 4, "sketch": {"$ref": "spot"}, "x": 20, "y": 10}]}`

[contract-30]: OPERATION_CONTRACT.md#contract-30--q03-lightweight-status-and-explicit-checks
[contract-31]: OPERATION_CONTRACT.md#contract-31--fail-fast-studio-results-typed-helices-and-tight-boxes
[contract-32-batch]: OPERATION_CONTRACT.md#324-atomic-batches-and-preview-accepted
[contract-32-bridge]: OPERATION_CONTRACT.md#325-identity-schemas-lifecycle-compact-inspect-transport-client
[contract-32-parameters]: OPERATION_CONTRACT.md#323-parameters
[contract-32-render]: OPERATION_CONTRACT.md#322-model-images
[contract-assembly]: OPERATION_CONTRACT.md#assembly-increment--october-2
[contract-assembly-folders]: OPERATION_CONTRACT.md#instance-folders-assembly-ux-2026-10-24
[contract-historical]: OPERATION_CONTRACT.md#historical-contract-2-additions--october-2-review-follow-up
[contract-intro]: OPERATION_CONTRACT.md#shared-operation-contract
[contract-measure]: OPERATION_CONTRACT.md#measure-assembly-ux-2026-10-24
[contract-multi]: OPERATION_CONTRACT.md#multi-edge-references
[contract-patterns]: OPERATION_CONTRACT.md#pattern-tools
[contract-planes]: OPERATION_CONTRACT.md#datum-planes
[contract-selectors]: OPERATION_CONTRACT.md#geometry-references-and-selectors
[contract-set-view]: OPERATION_CONTRACT.md#viewport-camera-set_view-gui-2026-10-20
[contract-studio]: OPERATION_CONTRACT.md#u2-part-studio-and-reference-queries--october-2
