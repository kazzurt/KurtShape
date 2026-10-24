# Saved-component refresh and part discovery

2026-10-21. These additive operations were developed against the completed Dodec
hub fixture; the fixture geometry and original files are unchanged. Run them in
the explicitly selected session, with ordinary document UUID, revision and
request-ID tracking. No source is updated automatically.

## Find a usable final part

`part_inventory` is a quiet, read-only document operation. By default `parts`
contains current solid results, including imported STEP/legacy Bodies, studio
logical parts and assembly occurrences. `include_history:true` also returns
solid helpers, history features and embedded snapshots. Every row includes
native `id`, `name`, `type`, logical `part_id`, `solid_count`, `role`
(`final`, `helper`, `history`, `embedded_source`), `final`, `usable` and
`assembly_source_eligible`. Visibility does not determine whether a part is final.
`usable` describes current result membership and native error state; it is not
a substitute for `check_geometry`. Rows make that basis explicit with
`usable_basis:"current_result_and_native_state"` and
`geometry_validation:"not_checked"`; inventory does not run an expensive BRepCheck.

`assembly_candidates` reads a saved FCStd/STEP in a disposable document and
returns the same row format. Its default candidate membership is unchanged for
compatibility. Use `final_only:true` when choosing a finished studio result:

```json
{"op":"assembly_candidates","path":"C:/projects/cartridge/cartridge.FCStd","final_only":true}
```

Use the returned native `id` as `source_id`. Do not guess that the first Body is
the result; studio files also retain Bodies used for tools and history.

## Refresh an occurrence

```json
{"op":"refresh_assembly_part","instance":"Cartridge","path":"C:/projects/cartridge/cartridge.FCStd","source_id":"Cartridge","shared":"instance"}
```

`path` and `source_id` may be omitted to use the embedded source's recorded
provenance. The source must exist and pass the same safe source checks as insert.
When several occurrences share the snapshot, `shared` is required:

- `instance` creates a private replacement snapshot for that occurrence.
- `all` updates every occurrence linked to that exact embedded snapshot.

The native occurrence object, label, placement, appearance, grounding and joint
references remain. A changed placement in the saved source is provenance only;
it does not move an existing occurrence. Origin joints can survive arbitrary
valid solid revisions. Face/edge/vertex joints require the referenced subelement
to retain its exact canonical geometry and connector frame. A surviving `FaceN`
name alone is not sufficient. Changed references reject with
`assembly_refresh_reference_changed`; explicitly edit the joint before retrying.
There is no automatic topological remapping in this operation.

The operation validates the source's native serialization, existing connector
identity, native solver result, embedded integrity and unchanged placements
inside one undoable transaction. A failure restores the accepted geometry,
links, frames, appearance, history and revision. The result's `refresh_report`
lists the affected occurrences, old/new embedded source and file hashes, source
path/ID and preserved reference count. The external source is never written.

For the fixture, save a revised component in a separate part session, refresh
only its occurrence (or explicitly all repeated users), run `check_geometry`,
then save and validate a new delivery copy. This avoids reconstructing the other
34 occurrences just to revise the cartridge or one fastener.

Native regression coverage is in `test_assembly_refresh.AssemblyRefreshTests`:
legacy/STEP/studio inventory, final filtering, shared-source policy, copy-on-write,
placement and origin/face-joint preservation, rejection of changed references,
injected solver failure with exact rollback, undo/redo and native reopening.

GUI-native appearance is checked separately by
`tools/assembly-refresh-gui-probe.FCMacro`. Run it only in a private offscreen
process (`QT_QPA_PLATFORM=offscreen`, isolated `KURTSHAPE_SESSION_DIR`,
`FREECAD_USER_HOME`, `APPDATA`, `LOCALAPPDATA`, `TEMP`/`TMP`, and explicit private
`-u user.cfg -s system.cfg`); the macro refuses a normal user session and exits
its own process after writing `gui-refresh-result.json`. It verifies FreeCAD
1.1's `ShapeAppearance`, material overrides and visibility across both refresh
policies, then saves and reopens through the Controller. Offscreen verification
establishes native GUI state, not hardware viewport rendering.
