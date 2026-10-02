# Foundation decision — M1 increment 1

October 1, 2026, America/Los_Angeles. Selected: **portable FreeCAD 1.1.4, native FCStd documents and Sketcher/PartDesign**, extended by a small KurtShape Python/Qt panel and typed operations. No new geometry kernel, independent editable graph, or deep FreeCAD fork.

## Evidence before UI architecture

The bounded probe `tools/probe_freecad.py` ran on this machine with the official portable Windows x86-64 archive. `validation/foundation-probe/result.json` records exact runtime versions and results. It created two fully constrained sketches with real Sketcher constraints/expressions, a pad and through pocket, verified one valid solid, changed thickness in a transaction, undid/redid it, saved/reopened FCStd, touched and recomputed native features, and exported STEP/STL. Baseline volume 14098.40710525538 mm³ agrees with the analytic plate; edited thickness volume 18797.876140340504 mm³. The full proof took 2.62 seconds, including persistence/exchange; this is not an interaction latency measurement.

Pinned FreeCAD revision: `4fd3bf320d9566a27e60069fc8387448aaa3a094` (tag 1.1.4); Python 3.11 runtime bundled; OCCT 7.8.1. Official archive SHA256 `4828741fc91ee37fafcdb97a1abacb18b04ba451ac4372d9ff7a7349b36f4d6d` was verified. Source release metadata is preserved in `runtime/downloads/freecad-release-1.1.4.json`. No global installation or pip installation.

## Bounded alternatives

| Candidate | Evidence considered against actual fixtures and manual task | Decision |
|---|---|---|
| FreeCAD | Installed native slice passed. Existing graphical Sketcher, feature history, native transactions/persistence, Python inspect/edit and kernel exchange. Native operations cover many source families, but compressed Onshape references and semantic conversion remain our work. | Select the largest coherent proven reusable unit. |
| Dune3D | Official Python documentation calls its module a proof of concept and requires a separate build with headers/pybind11. Promising interactive application, but completing its Windows transactional adapter would add foundation work before the requested source conversion. | Defer within this budget; no complete prototype. |
| PartMode | Official architecture documents canonical schema-5 and shared WASM/agent boundary. Roadmap explicitly leaves constrained-sketch revolve and portability work open; hub uses four revolves and complex configuration/surface operations. Account/headless storage needs local adaptation. | Defer: less immediate required-feature coverage than proven FreeCAD slice. |
| Custom OCCT core | Can build solids, but would require document/history/solver/graphical sketch integration we just proved through reuse. | Fallback only if a named reuse blocker appears. |

This selects a first increment, not proof of full Onshape migration or comfortable graphical usability. Both supplied designs remain full-conversion acceptance gaps; no unsupported operation is silently removed.

## Integration and license record

KurtShape launches unmodified portable FreeCAD with isolated user/config/temp paths under Codex and loads our extension. The native application supplies viewport/orbit/pan/zoom, selection and graphical constrained sketch editing. The panel supplies the bounded create/pad/cut/parameter/save workflow. Native FCStd is authoritative; adapter inspection is derived. Keeping standard features also allows native editing without a custom engine.

FreeCAD tag license is LGPL 2.1 (see [tag LICENSE](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/LICENSE)); OCCT uses LGPL 2.1 with its additional exception; bundled Qt/PySide/Python and other components retain their own notices. This local evaluation is not a cleared redistributable installer. Preserve the upstream runtime intact and perform a complete component/notice inventory before redistribution. No SolveSpace library is added. Maintenance is confined to a small adapter and panel; avoid private C++ APIs and report native features outside the typed subset explicitly.

Primary comparison sources: [Dune3D Python module](https://docs.dune3d.org/en/latest/python.html), [PartMode architecture](https://github.com/BOMWiki/partmode/blob/main/docs/architecture.md), [PartMode roadmap](https://github.com/BOMWiki/partmode/blob/main/ROADMAP.md). Those are inspected documentation, not hands-on benchmark results.
