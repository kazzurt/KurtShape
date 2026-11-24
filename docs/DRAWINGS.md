# 2D manufacturing drawings

`kurtshape.drawing` turns a KurtShape solid into a dimensioned drawing on Kurt's Onshape
template: DXF for the supplier's CAD, a vector PDF to send, and a PNG preview. It runs headless
in the bundled FreeCAD 1.1.4 interpreter. The first drawing made with it is the Dodec bolt
D021 Rev B, in English and Chinese (`projects/dodec-bolt-5-16-18-t40/drawing_d021.py`).

## The drawing standard comes first

Kurt's engineering drawing standard of 11 November 2026 binds every drawing:
`C:\Users\Kurtz\Documents\Dodec\Drawing Template\Engineering Drawing Standard.md`. Read it before
writing a spec. `Sheet` enforces the rules a program can test: `lint()` reports each finding with
its rule number (kinds in `STANDARD_KINDS`) and `save()` refuses a sheet that has any.

| Rule | What the spec does | What fails |
|---|---|---|
| 1, 2 Notes | `notes()` on sheet 1 only; never bare `text()` | notes on a continuation sheet; loose text; a note repeating the material, finish, edge break or "do not scale", or naming a sheet |
| 3 Callouts | `callout(qty=, thread=, dia=, tol=, thru=, depth=, depth_qual=, cbore=, csink=)` builds the lines; `{cbore}`, `{csink}`, `{depth}` print as the ASME symbols | a thread without its class; a hole or internal thread without THRU or a depth; a thread designation in a note; "RIGHT HAND" |
| 4 Holes | `hole_callout(pv, centre, r, text_pos, lines)` draws the centre mark and a radial leader to the near side; `centre_mark()` alone for other circles | a leader ending on a circle that is not radial, or whose circle has no centre mark |
| 5 Leaders | route them clear; `allow("leader-extension", at, reason)` for an extension line that cannot be avoided | leader over leader or over a dimension line; an unwaived leader over an extension line; a waiver that waives nothing |
| 6 Labels | `view_label(pv, pos, name)`; the scale prints only when it differs from the sheet's | `label()` (free text); a view name over four words; an unlabelled section, detail or off-scale view |
| 7 Sections, details | `place(..., letter="A")` with `cutting_plane(..., "A", ...)`; `place(..., clip=, letter="B")` with `detail_circle(..., "B", ...)`; an auxiliary view `place(view, ..., letter="C")` with `view_arrow(parent, tip, toward, "C")` on its sheet, labelled VIEW C (state `rotated=` when turned); across sheets `parent_sheet=` / `view_sheet=` and `check_set(sheets)` | a section without its cutting-plane line, a detail without its circle, a lettered view without its arrow, and the reverse |
| 8 Scale | `fill({"SCALE": "2:1"})`; views at that scale; `place(..., scale_reason=)` for another | "AS SHOWN"; a scale outside `SCALE_SERIES`; a main view off the sheet scale without a reason |
| 10 Weight | `set_weight(volume_mm3, density_g_cm3)` | a blank weight, the wrong unit, "REF" |
| 11 Keep-out | lay out inside the map's `usable` areas | anything in the title block or revision table, or outside the frame |

`standard_report()` returns the sheet's scale, weight, views, letters and waivers for the check
record. `Sheet(..., standard=False)`, or `sheet.standard = False` right after a shared helper
opens the sheet, switches the standard off; it is for the script of a drawing released before
11 November 2026, until that drawing is next revised, and never for a new one. Scripts written
before the standard stop with a message saying so when they are rerun.

Worked example: `examples/drawing_standard_example.py` (one inch sheet with a top view, a
section, a thread callout and a counterbore callout; its comments name the rule each call
serves). Its PDF is filed beside the standard as `Engineering Drawing Standard - example sheet.pdf`.

## Why this stack

Surveyed and tested on the bolt and the template on 2026-10-23, before building:

- **FreeCAD 1.1.4 TechDraw, headless.** It computes views and dimensions, but:
  - page PDF/SVG export is GUI-only;
  - `writeDXFPage` drops the template, the hatching, unequal tolerances and most annotations,
    and garbles CJK, Ø, ° and ±;
  - it silently falls back to an uncut view when the solid fails BOPCheck;
  - a modelled helix draws as about 80 B-spline curves instead of a standard thread.
- **draftwright 0.4.35** (AGPL-3.0). It makes automatic drawings from STEP, but it draws the
  thread literally, rounds sizes to one decimal and uses its own title block.
- **build123d and build123d-drafting-helpers** (Apache-2.0). They have good drafting pieces, but
  they need numpy 2 and OCP 7.9 or later, so they cannot run in the FreeCAD runtime. build123d
  also has no sections, hatching, radius dimensions or PDF output.
- **Side pieces only:** CadQuery exporters, cq_warehouse drafting, pythonocc-core, LibreCAD's
  command line and LibreDWG.

The pipeline keeps the parts that held up:

- **Views:** OCCT hidden-line removal through `TechDraw.projectEx`, which runs without a GUI.
- **Sheet:** [ezdxf](https://github.com/mozman/ezdxf) 1.4.5 (MIT), which writes real `DIMENSION`,
  `HATCH`, `MTEXT` and `LEADER` entities onto the template DXF and renders it with matplotlib.
- **Logo:** [olefile](https://github.com/decalage2/olefile) 0.47 (BSD) reads the template's
  OLE2FRAME logo, which ezdxf cannot draw.

## Setup

```powershell
tools\setup-drawing-deps.ps1
```

This installs ezdxf and olefile with pip `--target --no-deps` into
`runtime\vendor\drawing-py311`. The runtime's own numpy, matplotlib, fontTools, pyparsing and
Pillow are used as they are. `kurtshape.drawing.sheet` appends the folder to `sys.path` and keeps
ezdxf's font cache in `runtime\vendor\drawing-py311-cache`.

## Writing a drawing

A drawing is a short Python spec run with the bundled `pythonw.exe` (output redirected to a file).

1. **Make the drawing body.** Sections need a solid that boolean operations accept. A modelled
   helical thread usually fails them, so the build writes a *drawing body*: the same part with
   the thread as its crest cylinder. Threads are then drawn in the simplified convention
   (ISO 6410 / GB/T 4459.1 / ASME Y14.6): a thick crest line, a thin root line, and a thread-end
   line, added by the spec with `Sheet.vline`.
2. **Project views** (`kurtshape.drawing.views`):
   - `project(shape, x_axis, y_axis, hidden=False)` gives an orthographic view. The viewer looks
     from `x_axis × y_axis`, so `((1,0,0), (0,0,1))` is a front view with world +X to the right.
   - `section(shape, x_axis, y_axis, offset)` removes the material on the viewer's side of the
     plane, projects what is left, and returns the cut faces as hatch loops.
   - Results are true-size lines, arcs and circles. B-splines and ellipses become 0.002 mm
     polylines.
3. **Lay out the sheet** (`kurtshape.drawing.sheet.Sheet(template, template_map, lang)`):
   - `place(view, origin, scale)` puts a view on the sheet. `clip=(centre, r)` makes a detail view.
     A section or detail takes its `letter`; `view_label(pv, pos, name)` labels a view.
   - Dimensions: `dim_linear`, `dim_radius`, `dim_diameter`, `dim_angle`. They are real DIMENSION
     entities with DIMLFAC = 1/scale (inches on an inch sheet, radii and diameters included), so
     they read true size in any CAD program. ezdxf writes the R and Ø prefixes itself: a radius
     takes `text="3X <>"`, not `"R<>"`. `dim_diameter(..., pattern=3)` dimensions a bolt circle
     through that many hole centres and draws its centre-line circle.
   - STEP files often carry an oblique hole edge or a fillet as a B-spline, which projects as a
     polyline, not a circle or arc. `hole_callout`, `dim_diameter` and `dim_radius` take
     `fit_tol=` (at most 0.02 mm): such a polyline then counts as the circle or arc when every
     point lies that close to it, the deviation goes in the checks, and a hole accepted this way
     locates dimensions by its centre and is linted like any circle.
   - `views.section(..., snap=)` (at most 0.002 mm) closes the micron-level endpoint gaps that
     imported STEP cut faces leave, records each in `view.meta['snaps']`, and keeps the loop
     area check. Tolerances are given as
     `("sym", 0.05)`, `("dev", upper, lower)` or `("limits", hi, lo)`. Pass `expect="Ø11.00±0.03"`
     so the printed text is checked. `text_pos` moves the value outside a short dimension, and
     the dimension line is carried on to it. `mask=True` blanks the lines behind the value.
   - Notes and symbols:
     - `leader` (a string, or the lines `callout` returns);
     - `callout` and `hole_callout` (complete hole and thread callouts with centre mark, radial
       leader and the counterbore, countersink and depth symbols), `centre_mark`;
     - `fcf` (feature control frames, with a WIPEOUT mask);
     - `datum`;
     - `roughness` (ISO 1302 symbol, value under the bar, upright or read from the right);
     - `roughness_leader` (for surfaces facing down or left);
     - `cutting_plane`, `detail_circle`, `centerline`;
     - `notes`, which wrap with the real font to a width that can change down the sheet
       (`width_at(y)`). `layout_notes` is a dry run, for choosing the largest text height that fits.
   - Title block: `fill(fields)`, `set_weight(volume_mm3, density_g_cm3)`, `set_text` (fixed
     template texts), `revision_row`.
4. **Check and save:**
   - `lint()` returns layout clashes. A spec should refuse to ship with any (D021 does).
   - `save(dxf)` writes R2018 UTF-8 and audits it. It also refuses CJK in a non-CJK style and any
     character missing from its font.
   - `render(pdf, png, title=...)` writes the vector PDF and a PNG preview. `check_render` then
     inspects the preview.

## What the pipeline checks

A drawing that fails any of these stops with `DrawingError` (or a lint record):

- **Dimensions measure real geometry.**
  - Each definition point and leader target lies within 0.01 mm of the projected geometry, or at
    the centre of one of the view's circles or arcs (a hole is located by its centre). Points in
    a detail view must also lie inside its circle.
  - A radius needs a real arc of that radius and centre.
  - An angle checks a point on each leg (`leg_check`).
- **Printed values are the intended ones.** Every dimension's rendered text is compared with
  `expect`. Callout and note values come from the model's design values in the spec, not typed
  numbers.
- **Arrows fit.** Two arrowheads must fit between the extension lines.
- **No layout clashes** (`lint`):
  - text against text, view lines, leaders, its own dimension and extension lines, frames,
    hatching and the template's own texts. Text turned off the sheet axes (an aligned
    dimension's value) is tested by its own rectangle, not its axis-aligned box. Title-block texts the drawing rewrote are measured by
    their ink and must not overlap other template text. Brackets and ascenders count as ink
    (0.15 × text height), so a "(" cannot sit on a line;
  - roughness, datum and frame strokes against view and dimension lines;
  - masks (WIPEOUTs and masked text, DIMTFILL or background fill) over anything but centre lines.
- **Hatches are sound.** Cut-face loops are built in wire order and must close and match the face
  area. A clipped detail loop must not cross or overlap itself; no degenerate loops.
- **Text is legible.**
  - No missing glyphs.
  - Notes never start a line with closing punctuation.
  - A revision description never shrinks below its `min_h`.
- **The preview is clean.** The PNG has no coloured pixels and no solid black blocks.
- **The DXF is clean.** It passes the `ezdxf` audit after saving.
- **Views are not mirrored.** View axes follow the stated frame, and the tests check handedness.
- **The drawing standard holds.** The findings in the table at the top of this document; `save`
  raises on any of them.

## ezdxf rendering traps handled in `render`

- `ColorPolicy.BLACK` also blackens WIPEOUTs and text masks. Rendering uses `COLOR`, where
  colour 7 prints black on white.
- The matplotlib backend reads lineweights as points. They are scaled by 72/25.4, so 0.50 mm
  prints 0.50 mm. The minimum is 0.13 mm.
- ezdxf skips "canvas colour" text masks (DIMTFILL) and draws masks only for its complex MTEXT.
  For the PDF they become white and take that path; the DXF keeps canvas-colour masks.
- Hole detection misfills glyphs whose counter is split by a stroke, such as Ø. Text is filled
  with its own TrueType winding; hatches keep hole detection.
- The CJK font wraps complex MTEXT at spaces when rendered. Write `2×<>`, not `2× <>`.
- `text2path` rejects MTEXT, so `lint` measures text with `mtext_size`.

## Languages

`lang="zh"` switches dimension and note text to the `AH-CJK` style (Microsoft YaHei, `msyh.ttc`).
Any string containing CJK characters gets that style automatically on any sheet. Latin text uses
Noto Sans. `wrap` measures with the real font:

- Latin words stay whole, and CJK breaks between characters.
- Closing punctuation never starts a line; the tokens before it move down with it. Opening
  punctuation never ends a line.
- A one-character CJK last line takes one more character from the line above.
- U+00A0 (no-break space) and U+2060 (word joiner) glue neighbours, Latin or CJK. Use them for
  phrases such as `28 HRC`, `630 型` or `（参考）`. They print as an ordinary space and nothing.

Keep each language's texts in the spec, side by side, so the two sheets cannot drift apart.

## Templates

**Aerial Hedra templates (since 2026-10-28):** `Documents/Dodec/Drawing Template/` holds four
ANSI B sheets written by `tools/make_drawing_templates.py`, each DXF with its field map beside
it: `AH-B-mm-sheet1`, `AH-B-mm-sheetN` (continuation), `AH-B-in-sheet1`, `AH-B-in-sheetN`. The
README there lists the field and fixed-text names and the design. Open one with
`Sheet(dxf, template_map=<absolute path of the .json>)`. What the pipeline reads from a map:

- `fields`: MTEXT handles (with `ch`, `width`, `attach`) for `fill`; a bold placeholder keeps
  its bold style when filled;
- `fixed_texts`: named handles for `set_fixed` (units line, tolerance rows, roughness, edge
  break, projection label, address lines);
- `revision_table`: `columns_x` (REV, DESCRIPTION, DATE, APPROVED), `row_height`,
  `next_row_top` (the table ships empty; `revision_row(index, ..., date=...)` adds rows under
  the header and lines every column boundary), `text_inset`; `null` on continuation sheets;
- `units`: `"in"` makes dimensions print as inches to three decimals, ASME style without a
  leading zero (`.394`, `1.000±.005`), through DIMLFAC = 1/(25.4·scale), DIMDEC 3 and DIMZIN 4;
  the paper stays in millimetres and the spec gives tolerances in inches. `dec=` still overrides;
- `placeholders` for `blank_placeholders`, `notes_label`, `logo_box` (the vector lockup; no
  OLE logo to pull out), `sheet_box`, `frame_box`, `title_block_box`, `usable` areas.

The generator renders each template and a filled example through `Sheet.render`, runs `lint`
and the render check, and exits 1 on any finding, so a template change cannot ship a clash.

**Onshape template (2024, superseded):** `templates/aerial_hedra_b_mm.json` maps Kurt's B-size
mm Onshape export, now at `Documents/Dodec/Drawing Template/Drawing template aerial hedra mm.dxf`
(D021 Rev B was drawn on it). It records the MTEXT handles of the title-block fields, the sheet
and logo boxes (an OLE2FRAME bitmap, pulled out with olefile), the revision-table grid (row A is
part of the template; added rows go under it) and lineweights. To map another exported template,
list its field handles (dump the MTEXT entities with ezdxf).

## Fillable sign-off (16 November 2026)

The current first-sheet Aerial Hedra templates have DRAWN and CHECKED in the title
block. Approval is recorded once, in the revision table. The removed title-block
`APPROVED_NAME` / `APPROVED_DATE` keys should be removed from specs using the new maps.
Empty legacy values are ignored; a nonempty value raises a message to use the revision row.

`Sheet.render` automatically adds printable PDF text fields for CHECKED name/date
and the DATE/APPROVED cells of revision rows whose `approved` argument is blank.
Already-approved historical rows remain ordinary drawing text. Leave current
approval dates blank until Kurt fills them; fields accept YYYY-MM-DD. No name or
date is inserted on Kurt's behalf. The DXF remains an ordinary CAD drawing.

Template maps own field rectangles in paper millimetres (`pdf_form_fields` and
`revision_table.pdf_approval_fields`); old maps keep their previous behavior.
This uses pypdf 6.21.4, installed by `tools/setup-drawing-deps.ps1`. PDF fields have
print flags and saved appearance streams. Names shrink to fit narrow cells while
short values stay at the requested lettering height. Typed names are not digital signatures.

When joining sheets or several drawings into one PDF, use the merge helper:

```python
from kurtshape.drawing.pdf_forms import merge_drawing_pdfs

merge_drawing_pdfs(["part-a.pdf", "part-a-sheet2.pdf", "part-b.pdf"], "drawing-set.pdf")
```

It preserves the AcroForm tree, entered values and saved appearances, and groups
each input's fields under its input position: `drawing_1.CHECKED_NAME`,
`drawing_3.CHECKED_NAME`, etc. Source PDFs remain untouched. Standalone drawings
keep their existing field names. This also handles older PDFs and repeated inputs.
Direct `PdfWriter.append` preserves fields but does not separate identical names
across drawings; copying page content alone can lose the fields entirely.
Reopen the result and verify its qualified field names and values with
`PdfReader.get_fields()`. Typed sign-offs are retained; cryptographic signatures
are not preserved by merging. A PDF filled by Kurt is the signed-off PDF; re-rendering
from the CAD recipe creates a fresh blank sign-off and does not read back PDF edits.
The PNG exported directly by matplotlib shows the CAD text; inspect the final PDF
render when verifying field values and appearances.

`tests/test_drawing_pdf_forms.py` covers blank/filled/cleared fields, printable
appearances, longer names in narrow cells, historical approvals, independent edits after merging first sheets,
continuations, repeated inputs, nested packets and source-file preservation. It
is registered in the native regression runner. The 23 November 2026 publication
review found the duplicate-name issue; the merge helper and these checks resolve it.

## Limits

- Tangent ("smooth") edges are drawn thin. Leave them out with `styles=("visible", "section")`.
- A section needs a BOP-valid body. `section` raises instead of returning a partial view.
- A detail circle that would split a cut face into two pieces is refused, not drawn.
- PDF text is outlined (vector paths), like the Onshape originals. It is not selectable.
- The isometric reference view is a plain projection; there is no shading.

## Tests

```powershell
cd tests
..\runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\pythonw.exe -B -m unittest test_drawing > ..\runtime\test_drawing.txt 2>&1
```

`tests/test_drawing.py` has 57 tests (39 for the pipeline, written against `standard=False`, and
18 in `StandardTests` for the drawing standard). The eight added on 2026-11-11 for the aluminum
prototype second pass cover inch radii, `section(snap=)`, lint of turned text, a turned value's
carried dimension line, B-spline fillet radii, diameters and bolt circles, B-spline hole loops,
and auxiliary views with `view_arrow()`. One added on 2026-11-12 (the sleeve, ALP-006) covers a
radial hole in a tube, whose edge projects as two open B-spline halves: with `fit_tol` the pieces
count as the hole only when together they cover the whole circle. Another, also 2026-11-12, covers a
diameter called out from outside (`dim_diameter(location=)`): one radial leader to the near side,
arrow pointing in, no line across the circle (Kurt's rule). An inch unilateral tolerance is written
inline in ASME Y14.5 inch form (`text="<> +.00/-.02"`): ezdxf prints a nil deviation as a bare `0`,
the millimetre form. They cover:

- **Views and sections:** handedness, hidden lines, distance, section volume and hatch loops.
- **Dimensions:** true-size dimensions; refusal of off-geometry points; text expectations;
  radius-arc and angle-leg checks; arrow fit; unilateral tolerances.
- **Text:** CJK styles; measured and glued wrapping; the line-start rule; missing glyphs.
- **Layout:** lint for text, symbols, masks, masked text over an outline, rewritten template text,
  and bracket ink against a line.
- **Output:** the DXF audit, B-size MediaBox, PDF line widths, Ø counters printing white, the
  render check, and detail clipping including a bridged clip.
- **Templates:** inch sheets printing `.394±.005` from model millimetres, revision rows with a
  DATE column under an empty header (`next_row_top`), and fixed texts rewritten by name.
- **Standard:** every finding kind in the table at the top, a sheet that follows the standard
  saving clean, the waiver, hole-centre dimensions, callout texts and symbols, the legacy switch,
  and `check_set` across two sheets.

All four drawing test classes, including `StandardTests`, are registered in `tools/run_native_tests.py` and run by `run-checks.ps1`.
