# Conversion coverage and original-source acceptance gaps

Recorded October 1, 2026 (America/Los_Angeles), for KurtShape's first FreeCAD 1.1.4 / OCCT 7.8.1 implementation increment. **Zero supplied Onshape examples are converted.** The reusable converter currently accepts two explicitly synthetic normalized fixtures; their passing native edits do not satisfy the real-example migration gate.

## Original source inventory

Originals remain in `CADkz/Onshape examples`; the scripts read them in place and preserve SHA256. `validation/source-inventory.json` retains individual generated feature IDs/names, lines, families, constraints, expressions, compressed-query counts, headers and source hashes. It now reports each source feature as unconverted and gives an explicit whole-example rejection report. `newSketch` is counted once; a second alias called `sketch` was removed.

Both text files are generated Part Studio FeatureScript 3083, importing `onshape/std/geometry.fs` version `3083.0`. They are complete generated feature definitions with queries and dependencies, rather than raw feature API JSON or simple standalone custom-feature functions. Static counts include conditional branches and do not establish active configuration counts.

| Source | Static definitions | Sketch definitions | Other families | Compressed queries | Source units / configuration |
|---|---:|---:|---|---:|---|
| Dodec pipe mount.txt | 28 | 10 | Extrude 8, chamfer 4, fillet 3, mirror 2, hole 1 | 98 | Default length inch; `main` calls `build({})` |
| Dodec Hub Conformal.txt | 145 | 28 | Extrude, variables, datum planes/points, booleans, patterns, fillet, revolve, split, transforms, move face, shell, mirror, hole, loft, fill, offset surface | 439 | Default length millimeter; `main` selects `List_ZbEDhDNx0XOm6R_conf.Switch` |

Full native conversion rejects both examples at source representation preflight. Selecting just their sketch/extrude-looking definitions would lose required feature order, expressions, projected geometry, topology references and configuration behavior. The first single-body slice also cannot represent their measured three-solid outputs. No STEP archival import is counted as an editable migration, and no easier example has replaced either supplied example.

## Original STEP measurements

`tools/validate_sources.py` calls OCCT through `Part.read`, without aligning, transforming, rewriting or tessellating originals. Measurements use millimeters; area and volume use mm²/mm³. Full solid-by-solid bounds, validity, centroid, surface families, cylindrical faces and source hashes are in `validation/source-geometry.json`. Compound centroids use the explicit volume-weighted solid-centroid method because generic `Part.Shape` lacks a `CenterOfMass` attribute.

| Original STEP | Valid solids | Bounding-box size X × Y × Z (mm) | Volume (mm³) | Area (mm²) | Volume-weighted center of mass (mm) |
|---|---:|---|---:|---:|---|
| Dodec pipe mount | 3, all valid | 162.56 × 80.6945566663 × 304.8 | 690742.532951 | 99898.8264776 | (5.173949699, 5.444551176, 0.000000032) |
| Dodec Hub Conformal | 3, all valid | 94.6821869054 × 86.7974624305 × 80.4926651617 | 73546.8291754 | 37959.3995428 | (-349.593002794, -253.994671049, 5.666851489) |

Placement is consequential: the hub bounding box starts at (-392.020924946, -290.477462430, -26.298012130) mm and ends at (-297.338738041, -203.680000000, 54.194653032) mm. The pipe mount bounds start at (-27.305, -27.305, -152.4) mm and end at (135.255, 53.3895566663, 152.4) mm. Future comparison must retain these source coordinates or document an authorized transform. Total volume and face counts alone cannot prove shape agreement. Cylindrical radii are measured, but may describe external walls or fillets; they are not automatically identified as hole dimensions.

The validation script also supplies bidirectional solid-difference comparison with an explicit volume tolerance and reports failed/invalid booleans as indeterminate. It performs no automatic alignment. That residual check complements critical dimensions and surface tolerances; it does not prove native edit equivalence.

## Links and provenance

Kurt supplied two mutable workspace links and deferred dimension-change STEP variants:

- [Workspace link 1](https://cad.onshape.com/documents/78bda5b91e6e399f2c4df30e/w/0c4ffbfaeea5e757f487f9a2/e/696a14b65b999c81002d68f7?renderMode=0&uiState=6abf48dd4bd670947d6d4bbf): document `78bda5b91e6e399f2c4df30e`, workspace `0c4ffbfaeea5e757f487f9a2`, element `696a14b65b999c81002d68f7`.
- [Workspace link 2](https://cad.onshape.com/documents/d927645e1e93befc9057cf2c/w/3453d85417a543d884e3e606/e/a0e73f6dfdd8ce0e0988794d?configuration=List_ZbEDhDNx0XOm6R%3DSwitch&renderMode=0&uiState=6abf48e74bd670947d6d4be0): document `d927645e1e93befc9057cf2c`, workspace `3453d85417a543d884e3e606`, element `a0e73f6dfdd8ce0e0988794d`, URL configuration `List_ZbEDhDNx0XOm6R=Switch`.

Link 2's configuration name/value agrees with the hub's generated `main`; the link-to-file binding and frozen export revision remain unverified. The web reader could not access either page; no authenticated source payload or account access was obtained. The source file and STEP filename pairing does not establish same-revision/configuration correspondence.

Remaining real-example acceptance gaps: confirmed source-to-link binding, frozen version/microversion, configuration and export settings tied to each STEP, authenticated feature/sketch/dependency capture or equally reliable structured input, agreed critical dimensions/tolerances and intended two edits per example, and matching edited STEP references. Kurt has explicitly deferred the edited variants; do not repeatedly request them while independent implementation is possible.

## Declared normalized fixture schema

`src/kurtshape/onshape.py` accepts only `kurtshape.onshape-subset/1`, with `provenance.kind = synthetic_fixture`. This is a small development representation using quantity/enum/sketch-region parameter conventions. It is **not raw Onshape REST JSON** and is not a FeatureScript translator. Raw BTFeatureListResponse/BTMSketch/BTMFeature captures are rejected until a tested capture normalizer preserves their actual constraints, datums, expressions and queries.

The [official feature API guide](https://onshape-public.github.io/docs/api-adv/featureaccess/) distinguishes sketch and general feature payloads, and exposes quantity/enum/query parameter types. It recommends inspecting actual returned payloads because formats and omitted defaults can vary. The first increment consequently requires explicit normalized inputs and never guesses topology IDs or omitted geometric semantics.

| Supported fixture input | Native operation / editable intent |
|---|---|
| XY rectangle, explicit x/y/width/height quantity literals | `sketch_rectangle`; native coincident/horizontal/vertical/position/Width/Height constraints |
| XY circle, explicit x/y/diameter literals | `sketch_circle`; native center/diameter constraints |
| Circle `centerOn` preceding origin-anchored rectangle | Native expressions bind circle center to rectangle Width/Height halves |
| One initial +Z blind NEW, explicit sketch-region feature ID | `pad`, native profile link and Length |
| +Z through-all REMOVE from preceding unused profile | `pocket`, native profile link and through-all extent |
| Explicit mm/cm/m/in literals | Normalize once to native mm; no evaluation of expressions or variables |

Each feature retains source ID/name and deterministic native ID through `source_feature_id`/`source_feature_name` fields in the shared dispatch request. The FCStd document owns the resulting editable constraints, expressions, geometry and source properties. The conversion plan and returned mapping are traceability views, not a second authoritative model.

The compiler validates the entire source before sending even `new`. Unknown properties or parameters at any nesting level, general constraints/geometry, expressions, non-XY datums, unknown references, compressed/deterministic queries, suppressed/conditional features, duplicate IDs, multi-body NEW, unused profiles and unsupported extent/boolean combinations reject explicitly. A native runtime failure reports the failed source feature, applied mapping and partial document; each accepted feature remains a separate native transaction, and no partial conversion is saved automatically. Whole-import rollback is not implemented.

The two editable development fixtures are `examples/onshape-supported-subset/centered-plate-with-hole.json` (60 × 40 × 6 mm, centered Ø8 through hole) and `circular-inch-pad.json` (Ø1 in, 0.25 in thick, center at 0.5/-0.25 in). They are marked synthetic in their source and converter results.

## Verification and acceptance policy

Thirteen tests in `tests/test_onshape.py` passed using the bundled Python/FreeCAD runtime. Native checks use independently stated analytic volumes and a separately constructed primitive/boolean reference: original plate-hole residual below 10⁻⁶ mm³; one valid solid; fully constrained native sketches; stable mapping. A Width 60 → 72 mm edit moves the hole center from X=30 to X=36; a separate Ø8 → Ø10 edit changes native radius and expected volume. Rebuild succeeds after both edits. Inch fixture bounds/volume establish units and placement. Native save/reopen/relocation preserves mappings and expressions, and a subsequent width edit works. An outside-body cut fails explicitly while retaining the accepted plate. Other tests verify unsupported late features/parameters/queries cause zero dispatch calls.

These are development acceptance values, not Kurt-approved tolerances for the supplied designs:

| Example | Baseline requirements | Native edit requirements | Current gate |
|---|---|---|---|
| Synthetic plate fixture | 1 valid solid; 60 × 40 × 6; Ø8 at (30,20); analytic volume and original placement; geometric residual <10⁻⁶ mm³ | Width→72 moves center to (36,20); diameter→10; analytic volume after each; native save/reopen/relocation/rebuild | Verified development fixture only |
| Synthetic inch fixture | 1 valid solid; diameter 25.4; thickness 6.35; center (12.7,-6.35); analytic volume and measured bounds | Native dimensions remain editable | Verified development fixture only |
| Dodec pipe mount | 3 valid solids; source coordinates; critical dimensions and differences against same-source STEP | Two meaningful edits against matching Onshape STEP variants, native fresh rebuild and persistence | Unsupported source/features; no shape-agreement claim; edited references deferred |
| Dodec Hub Conformal | 3 valid solids; source coordinates; correct Switch configuration; critical dimensions and differences | Two meaningful edits against matching Onshape STEP variants, native fresh rebuild and persistence | Unsupported source/features; no shape-agreement claim; edited references deferred |

Reproduce the measurements with bundled `bin/python.exe -B tools/validate_sources.py`, inventory with `-B tools/inventory_sources.py`, and converter checks with `-B -m unittest discover -s tests -p test_onshape.py -v` from the KurtShape root. No new dependencies are required by this stream. Next step for real migration is an authenticated frozen-revision capture and bounded extension driven by the actual required constraints/multiple bodies; edited-reference comparisons follow when Kurt supplies them.
