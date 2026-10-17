# Visual proposals — Fable deep review, 2026-10-17

Checkout reviewed: `f57d592` (`main`). Every image in `concepts/` is a **concept mockup drawn from the real icon set and design tokens; none is a screenshot of implemented behavior.** Every image in `annotated/` is an existing validation capture with numbered callouts added; the source path and capture date are printed in each legend.

| Folder | What it holds |
| --- | --- |
| `annotated/` | Three current-era captures (2026-10-04 and 2026-10-06, the newest shell images in the repository) with callouts. |
| `concepts/` | Six concept mockups, PNG (2×) and editable SVG: main workspace, sketch editing and feature-editor states, each as a *restrained* and an *ambitious* option. |
| `tools/` | `annotate_screenshot.py` + three JSON specs and `render_concepts.py`. Both run offscreen under the bundled runtime: `runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\pythonw.exe -B docs\fable-deep-review\visual-proposals\tools\render_concepts.py` from the repository root regenerates `concepts/`; `annotate_screenshot.py <spec.json>` regenerates one annotated image. No application process is involved. |

The baseline is preserved in every proposal: light compact Onshape-inspired shell, SolidWorks mouse navigation, icon-only persistent toolbars with names in hover labels, menus and Alt+C search, and geometry dominating the screen. The ambitious options say explicitly which existing decisions they change.

## 1. What the annotated captures show

`annotated/01-model-workspace-2026-10-04-annotated.png` (from `validation/onshape-theme-repair/model-workspace-1440.png`):

1. One row of twenty cube-based grayscale glyphs with two separators; at 20 px the Extrude/Remove/Revolve/Sweep/Loft/Shell/Draft/Boolean/Transform silhouettes differ only in small marks and names appear only after the 350 ms hover label.
2. Feature history rows keep FreeCAD's colored native icons (red sketch, yellow pad) next to the grayscale toolbar: two icon languages for the same features. Source: `ui.py` `refresh()` uses `obj.ViewObject.Icon` directly for feature rows (line 1698) while toolbars go through `presentation_icons.icon_for`.
3. The active part is shown twice (owner chooser combo plus bold row) and the default name is `Body`.
4. Status is spread over the bottom bar with no build/validity indicator; the save state lives only in the title.
5. The native NaviCube is untouched (no `NaviCube` parameter is set anywhere in `src/kurtshape`), so it renders at FreeCAD's default `CubeSize` with rotation arrows and hatched faces, visually the heaviest element on a light shell.
6. The numeric Rollback slider in this capture was replaced on 2026-10-05 by the draggable line (image 03).
7. Flat Phong shading with black 1 px edges; no ambient/hemisphere cue.
8. Document tabs carry the native ` : 1*` MDI suffix; nothing in `ui.py` sets tab text.

`annotated/02-sketch-editing-2026-10-04-annotated.png` (from `validation/onshape-theme-repair/sketch-editor-1440.png`):

1. The floating sketch box contains **Normal to sketch** and **Isometric view** push buttons (`ui.py` lines 382–385) that duplicate toolbar tools (line 620), and its header check/cross are `QStyle` standard icons (`feature_panel.py` `_icon_button`, lines 15–26 and 60–63), a different style from the toolbar's SVG `confirm`/`cancel` glyphs.
2. The native Tasks header adds a third acceptance control, **Close**, beside the box's check/cross and the toolbar's check/cross.
3. Native constraint rows are `Constraint1…N` with no values or targets, so the dock costs about 30 % of the width for little information.
4. The solver status is a plain label with three unexplained icon buttons.
5. Dimension text is rotated along the dimension line (red in this capture; black since 2026-10-05).
6. Context hints share one bar with the view-size field and Messages.
7. Native tab suffixes and a red close glyph on the active tab.
8. The Tasks dock takes ~650 of 2160 px while editing, and the floating box overlaps the viewport on the left. `hide_native_panels()` (`ui.py` lines 96–108) only forces the dock to the right area and hides it when no dialog is active; there is no width policy.

`annotated/03-sketch-tasks-2026-10-06-annotated.png` (from `docs/sketch-interaction-reliability/evidence/screenshots/circle-drag-after.png`):

1. **Verified in the image:** the solver verdict is cut to `Under-constrainec 3 Degrees of Free` with no ellipsis or tooltip. The DoF count is the key sketching cue and it is the part that is lost.
2. Empty Tasks area while a single circle exists.
3. `Rebuild required · pending model changes` appears in the history-dock footer during sketching, far from the Rebuild glyph.
4. The 2026-10-05 rollback line has a 10 px handle and reads as a separator.
5. `Parts (0)` while the chooser shows `Body`: two meanings of "part" in one panel.
6. The hint string truncates at narrower windows.
7. Good and worth preserving: closed-region tint, blue free geometry, green fixed centre, origin snap markers.

## 2. Concepts

### 2.1 Main workspace

**Restrained** (`concepts/workspace-restrained.png`). Changes: thin family dividers and a fixed 34 px pitch in the toolbar; history rows drawn from the same grayscale SVG set with state carried by the row (italic + muted when rolled back, red cross glyph when failed); a 14 px rollback handle with a label; one Parts list with an *Active* tag instead of combo + bold row; a zoned status bar (left = model truth: solid count, build state, unsaved; centre = units and view context; right = Messages); NaviCube lighter and without arrows; tabs with a modified dot. The renderer is unchanged apart from a stronger top/side tonal contrast.

Why it helps: the same feature looks the same everywhere; the two things Kurt most often has to know (is it built, is it saved) are in one fixed place; the rollback control reads as a control; the Parts panel no longer shows the target twice.

Implementation path (all Qt/Python in `src/kurtshape`, no native change):
- History icons: route `refresh()` row icons through `presentation_icons.icon_for(label, command, native=obj.ViewObject.Icon)` so unmapped types grayscale-fall-back exactly as toolbars do; add `sketch`, `extrude`, `remove`, `fillet`, `chamfer`, `plane`, `hole` to `LABEL_ICONS` by feature `TypeId`. Effort S.
- Toolbar pitch/dividers: `make_toolbars()` + the toolbar stylesheet in `theme.py` (`QToolBar::separator` margins, `QToolButton` padding). Effort S.
- Rollback handle: `rollback_history.py` paint and hit-test width; keep drag-only semantics. Effort S.
- Parts list: remove `body_choice` from the dock, keep it as a hidden model behind a context-menu *Make active target* action and the existing bold/`mark_active_part`. Effort M (it is wired into `active_body()`, `change_body()`, `fill_merge_parts()`).
- Status zones: replace the single `self.message` permanent widget with three `QLabel`s (left truth, centre context, right Messages) fed from `status_detail()` and `restore_status()`; move transient completion text (`notify(... " complete")`) to a 4.5 s toast in the centre zone only. Effort S–M.
- NaviCube: set `User parameter:BaseApp/Preferences/NaviCube` → `CubeSize` (e.g. 96), `BaseColor`, and `View/NaviRotateToNearest`; arrows are part of the native cube and cannot be removed individually in 1.1.4 (verify the `NaviCube` group keys in the running build; the template `View.cfg` lists `CornerNaviCube`, `CubeSize`, `NaviRotateToNearest`, `InactiveOpacity`). Effort S.
- Tabs: set the MDI sub-window title from the document label plus a modified marker in `update_document_identity()`; the native ` : 1` suffix comes from FreeCAD's view numbering and can be overridden on `QMdiSubWindow.setWindowTitle` after `maximize_document_view()`. Effort S (verify FreeCAD does not rewrite the title on activation).

Accessibility and performance: no new interaction surfaces; all labels keep accessible names; the only cost is one grayscale conversion per native icon, already cached by `grayscale_icon`.

**Ambitious** (`concepts/workspace-ambitious.png`). Adds a right-hand vertical view rail (fit, iso, normal, section, measure, check geometry) with a Quality preset popover (Draft / Standard / Present), document-row state chips (Saved/Unsaved, Build state), part cards with colour swatches and an explicit *Active* chip, a 58 px NaviCube, a selection chip that names feature · element · geometry type, a progress bar for background jobs in the status bar, and a cooler material response (base colour, headlight/backlight contrast, thinner dark-gray edges, MSAA 4×).

Which existing decisions it changes: the viewport loses ~40 px on the right (the rail); state moves into the document row (DESIGN.md currently keeps the document row to identity, mode, Save, Help, Settings); default part colour becomes a per-part appearance rather than FreeCAD's uniform gray (DESIGN.md's Model Color Rule still holds because user-set appearances are never overwritten; only the *default* for new parts changes); icons go to 22 px / 36 px pitch (DESIGN.md says 20 px).

Implementation path: the rail is a `QToolBar` in `Qt::RightToolBarArea` or a floating `QWidget` child of the MDI viewport; quality presets set the parameters listed in §3; the selection chip reads the existing `SelectionObserver` and the geometry summaries `resolve_selector` already computes; progress bars come from the existing `_poll_geometry_check` / `_poll_step_export` states. The "material response" in the mockup is MSAA 4× plus a session-only satin `ShapeAppearance` (lower shininess) and thinner dark-gray edges; it does not assume lighting controls that are unverified on this build. Effort M for the rail and chips, L with presets and material defaults.

Tradeoffs: MSAA 4× costs GPU fill rate on integrated graphics and remote desktop (fallback: preset auto-downgrades when `QT_OPENGL=software` or the GL vendor string reports a software renderer); a right rail competes with the native Tasks dock for the right edge; colour swatches must respect per-part appearance (read-only here).

### 2.2 Sketch editing

**Restrained** (`concepts/sketch-restrained.png`). One sketch box with one check/cross pair, no Normal/Isometric buttons; a wrapped, coloured solver line with the DoF count and a plain-language cause that is never elided; constraint/dimension/conflict counts; the native Tasks panel hidden by default behind a *Native panel ›* link; later features muted/italic in history while editing an earlier sketch; the status bar's left chip says *Editing sketch*; hints elide with a tooltip.

Why it helps: the viewport regains ~30 % of its width during the most interaction-heavy mode; the single most useful solver cue (free DoF) is always complete; there is one way to finish and one way to cancel.

Implementation path: the sketch box is `sketch_edit_panel.py`/`ui.py` (`normal_button`, `iso_button` removed; the toolbar keeps N and Shift+7); the solver line subscribes to Sketcher's `SketchObject` solver state (`sketch.solve()` return and `getGeometryWithDependentParameters` are already read by `sketch_colors.py`) and formats DoF from `sketch.ConflictingConstraints`/`RedundantConstraints` plus the solver's DoF (`sketch.solve()` returns the status; the DoF number comes from the Sketcher task message, which can be read from the `TaskSketcherMessages` widget's label text until a Python API is exposed); `hide_native_panels()` gains a user-visible toggle instead of hiding only when no dialog is active. The native dock stays the source of truth for constraint lists. Effort M.

Dimension text: FreeCAD renders datum text with `SoDatumLabel`, which rotates text along the dimension line; there is no View parameter for upright text in 1.1.4. Upright labels would need a Coin overlay re-draw or a native patch. **Not promised here**; listed as a deferred native item.

**Ambitious** (`concepts/sketch-ambitious.png`). Text Finish/Cancel buttons, a support chip, *Shows* toggles (constraints, dimensions, construction, later features), inline dimension entry at placement (a floating `QuantityField` over the viewport with Tab cycling free dimensions), constraint glyph badges on geometry, a persistent DoF badge at the viewport corner, and snap narration near the cursor.

Which existing decisions it changes: the box gains text buttons (DESIGN.md header uses icon-only Confirm/Cancel); overlays add a Coin `SoAnnotation` layer that KurtShape owns during sketch edit; the DoF badge is a second status surface in the viewport.

Implementation path: inline entry reuses `quantity_field.QuantityField` positioned by projecting the dimension's label point (`sketch_references.py` already maps picks to view coordinates); constraint badges are drawn from `sketch.Constraints` with `SoAnnotation` + `SoImage` per constraint type; the DoF badge is a `QLabel` overlay on the MDI viewport; snap narration reads `sketch_snapping.py`'s current target. Effort L.

Tradeoffs: overlays must be removed on every tool change and document switch (use the existing `tool_session` generation guard); badges on dense sketches need a cap (hide beyond ~200 constraints) to keep hover cost bounded; inline entry must not steal Escape/Enter from native Sketcher (route through the existing `eventFilter`).

### 2.3 Feature editor states

**Restrained** (`concepts/feature-editor-states-restrained.png`). The existing `FeaturePanel` skeleton with: header check/cross from the toolbar's own SVG set, Confirm tinted blue only when the exact preview is valid; a verdict strip with a 4 px semantic edge, icon or spinner, and a second line naming the consequence (`adds 33,446 mm³ · 1 solid`, from the preview measurements already returned); pending shown as spinner + *Provisional preview shown* with a dashed translucent preview; errors naming the failing input, a next step and that values are kept, with the offending field and reference row in the theme's existing invalid outline and a *missing* tag; Operation as a segmented control.

Implementation path: `feature_panel.py` `set_status(text, severity)` gains an optional detail line and icon; `_icon_button` takes `presentation_icons.icon_for("confirm")`/`("cancel")` instead of `QStyle.SP_Dialog*`; `ReferencePicker.add()` accepts a health flag that sets a `missing` property for QSS; the segmented control is four checkable `QToolButton`s in a `QButtonGroup`. The preview verdict text already comes from `preview_status()` (`ui.py` ~3739) and `extrusion_preview.py`. Effort S–M.

**Ambitious** (`concepts/feature-editor-states-ambitious.png`). Text Confirm/Cancel (primary blue when valid), *Feature 4 of 7* history position, in-viewport flip-direction handle and volume-delta chip (Coin `SoAnnotation` overlays bound to the preview result), expected wait from the responsiveness timing samples, and one-click repairs when the kernel can propose a value (fillet maximum radius probe).

Tradeoffs: the repair suggestion needs a kernel-side probe (a bisection on `BRepFilletAPI_MakeFillet` in the preview worker; cost grows with edge count); overlays need lifecycle guards; the history position must update on rollback.

## 3. Quality presets (display only; model precision and export mesh untouched)

Renderer facts established from the pinned runtime by offscreen probes (review finding set B, `FABLE_REVIEW.md` §4.6): the main view is Coin3D fixed-function Gouraud/Phong lighting with three directional lights (0.9 white, 0.6 warm, 0.4 cool) and a specular default material (ambient 0.33, diffuse `#ADB5BD`, specular 0.53, shininess 0.9); anti-aliasing is `View/AntiAliasing` (none by default; line smoothing or MSAA 2×/4×/8×); transparency is sorted-object sorted-triangle blending; tessellation is per-ViewObject `Deviation` (0.2 %) and `AngularDeflection` (28.65°) whose defaults come from `Mod/Part MeshDeviation` / `MeshAngularDeflection` when a view provider is created; a fresh 1.1.4 profile already carries the FreeCAD Light colours (preselection `#007A00`, selection `#3B5BDB`, shape `#ADB5BD`). There is no SSAO, shadow, PBR, order-independent transparency, capped clip plane or screen-space outline in the main view. KurtShape today sets nothing for anti-aliasing, tessellation defaults, lights, selection colours, line widths or the NaviCube; its only quality control is Shift+R, a per-document toggle that re-tessellates every object synchronously, marks the document Modified, and does not apply to objects created afterwards (verified defect B-01). The preview ghost is tessellated with an absolute 0.15 mm rule (~126 segments per circle) while the committed model uses the display rule (26 segments on a 3 mm hole), so Confirm visibly coarsens geometry (B-04).

| Preset | `View/AntiAliasing` | `Mod/Part MeshDeviation` / `MeshAngularDeflection` | Other | Measured cost | What Kurt would notice |
| --- | --- | --- | --- | --- | --- |
| Draft (auto on software GL / Remote Desktop, or by choice on huge imports) | 0 | 0.5 % / 28.65° | `RenderCache=0`; cheap sorted blend; overlays at the display rule | plate60 6.5k facets; no MSAA fill cost | jagged edges, 7-facet fillets, fastest orbit |
| Standard (default) | 3 = MSAA 4× (confirm the enum in the running build's Preferences dialog) | 0.2 % / 12° | `DefaultShapeLineWidth` 2 (3 at 150 %, 4 at 200 %); owned highlight/selection colours; preview mesh uses the same rule as the model | plate60 14.7k facets (2.3×); ~100 MB MSAA buffers at 2160×1380, trivial on a dGPU, fine on Intel UHD | smooth edges, round holes (60 segments), fillets 15 per 90°, identical picking |
| Presentation (captures) | 4 = MSAA 8×, fallback 3 | 0.05 % / 5° | hide cube, axis cross, corner triad, sketches and planes; optional session-only satin material (shininess 0.4, colour untouched) | plate60 34.8k facets (5.4×), ~0.9 s re-tessellation on a busy CPU; ~200 MB | capture-grade smoothness, 36 per 90° fillets, a short stall when switching on dense models |

Rules: presets write KurtShape's private profile and apply to open documents per visible, non-internal object only when the value differs, with the Modified flag preserved (the `PlaneHighlight.restore_modified` pattern) and batched through a timer so a dense model never blocks input for more than one frame per object; STEP export stays exact and STL keeps its absolute 0.05 mm / 0.1 rad (`core.py` line 2834, recorded in provenance); `ShapeAppearance` colours of parts are never touched; `PickRadius` is untouched. Platform fallback: read `GL_RENDERER` once after the first view exists; on `llvmpipe` / `GDI Generic` / Microsoft Basic Render Driver force Draft and say so in Settings; cap MSAA at 4× on Intel. Lighting: `HeadlightColor/Intensity` and `EnableBacklight/BacklightIntensity` exist as parameter strings in the bundled `FreeCADGui.dll`, but whether they still drive the three-light rig on 1.1.4 is unverified; the material response shown in the ambitious workspace mockup therefore comes from the satin material and MSAA, not from lighting changes.

## 4. Icon strategy

One grayscale family for everything persistent: toolbars, history rows, parts, tabs, editor headers. Semantic colour is reserved for *state*: accent blue for armed/active/selected, red for failed/missing, amber for pending/unsaved, green for valid/checked. Native coloured glyphs appear only inside native dialogs that KurtShape does not own (and the restrained sketch proposal hides the one that shows most).

Concretely: (1) history and parts rows go through `icon_for` with grayscale fallback; (2) the editor header stops using `QStyle` standard icons; (3) the SVG set gets a silhouette pass for the nine cube-based glyphs listed under image 01 callout 1 (distinct profile shapes rather than marks on the same cube: e.g. Revolve as a lathe profile, Sweep as a bent tube, Loft as two differing sections, Shell as a hollow corner, Draft as a tapered wall); (4) the three menu glyphs (`build-menu`, `cut-menu`, `modify-menu`) get a shared chevron so menus read as menus. The review's icon audit (`FABLE_REVIEW.md` §4.2 and finding A-04) lists which silhouettes were judged ambiguous at 20 px.

## 5. Native Tasks integration

Keep native Tasks for operations KurtShape does not own (native Fillet/Chamfer/Pattern dialogs); for sketch editing, hide it by default and surface its three useful facts (solver status, constraint count, conflicts) in the KurtShape box, with *Native panel ›* to show it. When it is shown, set a width policy (`dock.setMinimumWidth(300)`, `setMaximumWidth(380)`) and let the long solver message wrap (`QLabel.setWordWrap(True)` on `TaskSketcherMessages`' label, found via `findChild`). Remove the duplicate Normal/Isometric buttons from the box. These are Qt-only changes in `ui.py` / `sketch_edit_panel.py`; no Sketcher behaviour changes.

## 6. Not worth their cost yet

- Upright dimension text (needs a native `SoDatumLabel` change or a full overlay re-draw).
- Shadows, SSAO or PBR materials (not available in the pinned Coin3D main view; would need a different renderer).
- A second status surface (toast system) before the status bar zones exist.
- Replacing the native constraint list with a KurtShape list (duplicates Sketcher state; keep native, hide by default).
