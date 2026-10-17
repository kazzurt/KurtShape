# KurtShape: preliminary review and Fable handoff

Prepared 2026-10-17. Source baseline: `d95cc2e` (`Run studio booleans exact and reject implausible fillet results`). The working tree was clean before these review documents were added. Git inspection used a command-local safe-directory exception; no Git configuration was changed.

This is a source-and-existing-evidence review to prepare the Fable deep dive, not a completed runtime audit or a formal Impeccable critique run. Impeccable product/design context and review guidance informed the brief. No native tests, performance benchmarks, desktop automation, or live bridge operations were run. No application code or models were changed. Questions skipped: the requested review prompt can be completed from the existing project context.

## Main assessment

KurtShape has a stronger foundation than a cosmetic FreeCAD wrapper: authoritative native documents, guarded mutations, undo/recovery, explicit geometry checks, typed operations, private workers, and unusually careful records of performance limitations. The highest-value review should connect professional appearance to predictable interaction and trustworthy feedback, while preserving those foundations.

The visual direction is already defined. It needs scrutiny of consistency and execution, rather than an automatic replacement with a different UI framework or a fashionable theme. Existing images suggest mixed icon styles, a native Tasks surface that feels different from the compact shell, and opportunities to improve the hierarchy of geometry and editing state. Their age limits what can be claimed about today's app.

## Prioritized leads

| Lead | Evidence inspected | Interpretation and next step |
| --- | --- | --- |
| Unify native and owned editing surfaces | `feature_panel.py:29` and `:123`; existing `circle-drag-after.png` | Owned editors have compact floating placement, fixed acceptance controls, and preview verdicts. The October 6 native sketch image has substantial empty task-panel space and clipped solver text. Verify current layout and DPI behavior, then harmonize presentation without replacing native solver behavior. |
| Improve icon coherence and recognition | `presentation_icons.py:103` and `:132`; October 4 workspace image | The toolbar combines original art with grayscale native fallbacks; the history retains colored native glyphs. This is observable variation, not automatically a defect. Review silhouettes, semantic color, and contrast at real sizes; preserve intentional icon-only toolbars and named help routes. |
| Develop a richer viewport-quality plan | `viewport_actions.py:219` | The existing quality toggle adjusts Deviation and AngularDeflection and restores original values. It is not a complete lighting/material/anti-aliasing system. Investigate supported renderer controls, useful presets, selection clarity, and cost on large models. Do not assume rendering features are absent elsewhere. |
| Improve sketch editability through actual relationships | `core.py:2135`, `_add_line` | Line-to-line junctions intentionally retain independently positioned endpoint constraints; automatic joining targets fixed non-line geometry. That leaves a practical parametric-continuity gap for bridge-created polylines. Reproduce dimension edits and design compatible coincidence/constraint operations before changing existing behavior. |
| Consolidate command metadata and lifecycle ownership | `ui.py:127`, `:485`, `:1175`; `ARCHITECTURE.md`, Commands and transactions | `ui.py` has 4,339 lines, `core.py` 2,783, `studio.py` 1,693, and `selectors.py` 1,271 at this baseline. Architecture explicitly records separately wired shortcut and toolbar metadata. Explore incremental command/feature-editor extraction tied to concrete consistency and testability gains; size itself proves no bug. |
| Address remaining main-thread stalls | `ARCHITECTURE.md:89`; responsiveness status report, Open gaps | Native workers already exist. Preparation, capture, acceptance/publication, import, explicit save, recompute and synchronous fallbacks can still block the GUI. Measure user-visible feedback and cancellation with representative models before proposing concurrency changes. |
| Fill assistant observability and capability gaps | `core.py:246`, `:1344`; operation contract; workspace instructions | `_inspect` returns rich model/build information but no unsaved/modified flag. The inspected operation table does not provide close-document, feature-visibility, spline, or helix operations. Investigate full registration and runtime capabilities, safe semantics, and task value; distinguish native UI support from bridge support. |
| Review transport resource bounds and long-session ergonomics | `bridge.py:15`, `request_ledger.py:11` | Authenticated loopback, Origin rejection, payload-size cap, queue bound, replay protection and status lookup already exist. Connection/thread/read-deadline behavior and the session retry-capacity ceiling deserve focused review. These are investigation leads, not reproduced exploits or production failures. |
| Keep evidence and design documentation current | `DESIGN.md`, `.impeccable/design.json`, architecture status report | Context loading flagged legacy product-document schema and stale design sidecar metadata. More importantly, screenshots and historical tests need explicit source/version associations. Refresh documentation deliberately; do not let old totals imply current validation. |

## Visual evidence actually viewed

- `validation/onshape-theme-repair/model-workspace-1440.png` — file timestamp October 4, 2026. Shows the light shell, compact toolbar, colored native history icons, white viewport, navigation cube, and document/status rows.
- `validation/sketch-presentation/part-studio/fillet-dialog.png` — historical main-window capture. Shows multipart highlighting and history; the floating editor is not visible in this image, so it cannot establish editor layout quality or absence.
- `docs/sketch-interaction-reliability/evidence/screenshots/circle-drag-after.png` — file timestamp October 6, 2026. Shows native sketch Tasks, clipped solver text, substantial panel whitespace, a filled circle, and edit/status cues. These are image observations, not newly reproduced defects.

Current source corroborates the general light palette, icon strategy, compact editor framework, and tessellation toggle. Exact current rendering, panel geometry, input behavior, frame rate, and DPI behavior remain unverified. No screenshot was taken of Kurt's session.

## Existing strengths to preserve

- Native FCStd authority and editable features rather than a duplicate geometry/state model.
- Revision checks, request identity/replay protection, graphical edit ownership, and native transactions.
- Geometry checks separated from ordinary lightweight status; failed/stale results distinguished from current results.
- Fresh private preview processes and guarded result acceptance, with explicit ownership and cleanup.
- Local-file honesty, explicit Save, recovery, original-source preservation, and export provenance.
- A documented light design system, accessible names on inspected feature-editor buttons, persistent preview verdicts, and contextual command help.

## Handoff

Use `FABLE_REVIEW_PROMPT.md` as the standalone assignment. The next step is Fable's independent evidence-backed review, concrete visual concepts, and phased backlog. No implementation decision has been approved or made by this preliminary pass.
