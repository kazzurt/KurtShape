# M1 fixture inventory and acceptance gates

Started October 1, 2026, America/Los_Angeles. Implementation is authorized. All generated material stays under `CADkz/Codex`; originals stay in `Onshape examples`.

## Fixtures

| Fixture | Supplied evidence | Declared checks | Current gate |
|---|---|---|---|
| New plate | Proposed local task: 60 × 40 × 6 mm, centered Ø8 through hole, XY datum, positive Z pad | One valid solid; bounding box 60 × 40 × 6 mm; hole axis (30,20); volume (2400 − π×16)×6 mm³; graphical creation; thickness 8 mm and diameter 10 mm edits; undo/redo, fresh rebuild, save/reopen/relocation, STEP/STL | Local development fixture; dimensions proposed to Kurt |
| Dodec pipe mount | Generated FS3083 text + AP242 STEP | No auto-alignment; compare native/reference body counts, validity, bounding box, mass properties, critical pipe/fastener dimensions, and both directional boolean residuals; repeat two meaningful edits | Full editable conversion unsupported by the first slice; missing immutable provenance and edited references |
| Dodec Hub Conformal | Generated FS3083 text + AP242 STEP; `main()` selects `Switch`/Default, six configuration choices | Same checks plus configuration/body membership, loft/surface relationships and placements; repeat two meaningful edits | Full editable conversion unsupported by the first slice; STEP configuration is unknown, edited references missing |

`validation/source-inventory.json` contains hashes, per-feature source line/ID/name/guard, families, constraints, expressions, query counts and raw STEP header. Counts are static across branches, not evaluated active feature counts. Matching names do not prove same configuration/revision.

## Tolerances and reporting

Before any real-example comparison is accepted: propose 0.01 mm critical dimension/bounding-box tolerance, 1e-5 relative volume tolerance, and 0.01 mm tessellation deflection for visualization. Kurt's manufacturing requirements may revise these. Boolean residuals must be valid and small in both directions; record numerical residuals and tolerance rather than treating failed booleans as equality. These provisional values have not been agreed as manufacturing tolerances.

New plate analytic checks use 1e-6 mm dimension and 1e-6 relative volume tolerances. Cached STEP geometry cannot satisfy fresh native rebuild or editability. A STEP reference may be opened for inspection but is always labeled archival geometry.

## Source complexity (scope decision)

Pipe mount requires arcs, tangent/perpendicular/equal/projected/pattern constraints, eight extrudes, mirrors, a hole, fillets, chamfers and persistent query decoding. Hub adds configuration-dependent variables, planes, loft, split, revolve, booleans, patterns, transforms, offset/fill surfaces, shell and move-face operations. Both import only the standard geometry library in the supplied text; compressed historical topology queries and configuration logic are additional dependencies on Onshape semantics. No custom Feature Studio dependency was found in import statements. Units differ: pipe uses inch defaults, hub millimeter defaults; initial-guess coordinates are meter-scale and must not be interpreted in the UI default units.

These actual examples remain the M1 migration fixtures. Small synthetic supported fixtures may develop the converter, but do not replace them or count toward the required 2–3 migrations. Do not hand-reconstruct them and label that a reusable conversion.

## Missing inputs

Requested asynchronously: source links, frozen revision/configuration, critical dimensions, two intended independent parameter edits and matching STEP variants per real example. No cloud authentication exists. No original Onshape model will be changed. Until supplied, baseline correspondence and edit equivalence remain unverified even if local shape checks pass.

## Foundation evaluation budget

Bound the initial foundation comparison to 30 minutes of focused inspection/installation/probe effort, excluding download wait. Inspect Dune3D and PartMode for decisive integration gaps; prove one coherent constrained sketch→pad→cut→transaction→save/reopen→STEP slice in FreeCAD first. Expand only for a named failure. UI architecture follows that probe, not a preselected framework.
