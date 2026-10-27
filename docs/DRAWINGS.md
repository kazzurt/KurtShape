# 2D manufacturing drawings

`kurtshape.drawing` turns a KurtShape solid into a dimensioned drawing on Kurt's Onshape
template: DXF for the supplier's CAD, a vector PDF to send, and a PNG preview. It runs headless
in the bundled FreeCAD 1.1.4 interpreter. The first drawing made with it is the Dodec bolt
D021 Rev B, in English and Chinese (`projects/dodec-bolt-5-16-18-t40/drawing_d021.py`).

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
   - Dimensions: `dim_linear`, `dim_radius`, `dim_angle`. They are real DIMENSION entities with
     DIMLFAC = 1/scale, so they read true size in any CAD program. Tolerances are given as
     `("sym", 0.05)`, `("dev", upper, lower)` or `("limits", hi, lo)`. Pass `expect="Ø11.00±0.03"`
     so the printed text is checked. `text_pos` moves the value outside a short dimension, and
     the dimension line is carried on to it. `mask=True` blanks the lines behind the value.
   - Notes and symbols:
     - `leader`;
     - `fcf` (feature control frames, with a WIPEOUT mask);
     - `datum`;
     - `roughness` (ISO 1302 symbol, value under the bar, upright or read from the right);
     - `roughness_leader` (for surfaces facing down or left);
     - `cutting_plane`, `detail_circle`, `centerline`;
     - `notes`, which wrap with the real font to a width that can change down the sheet
       (`width_at(y)`). `layout_notes` is a dry run, for choosing the largest text height that fits.
   - Title block: `fill(fields)`, `set_text` (fixed template texts), `revision_row`.
4. **Check and save:**
   - `lint()` returns layout clashes. A spec should refuse to ship with any (D021 does).
   - `save(dxf)` writes R2018 UTF-8 and audits it. It also refuses CJK in a non-CJK style and any
     character missing from its font.
   - `render(pdf, png, title=...)` writes the vector PDF and a PNG preview. `check_render` then
     inspects the preview.

## What the pipeline checks

A drawing that fails any of these stops with `DrawingError` (or a lint record):

- **Dimensions measure real geometry.**
  - Each definition point and leader target lies within 0.01 mm of the projected geometry. Points
    in a detail view must also lie inside its circle.
  - A radius needs a real arc of that radius and centre.
  - An angle checks a point on each leg (`leg_check`).
- **Printed values are the intended ones.** Every dimension's rendered text is compared with
  `expect`. Callout and note values come from the model's design values in the spec, not typed
  numbers.
- **Arrows fit.** Two arrowheads must fit between the extension lines.
- **No layout clashes** (`lint`):
  - text against text, view lines, leaders, its own dimension and extension lines, frames,
    hatching and the template's own texts. Title-block texts the drawing rewrote are measured by
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

`templates/aerial_hedra_b_mm.json` maps Kurt's B-size mm Onshape template
(`Documents/Dodec/Drawing template aerial hedra mm.dxf`). It records:

- the MTEXT handles of the title-block fields;
- the sheet and logo boxes;
- the revision-table grid;
- lineweights.

To add another template, export it from Onshape as DXF and list its field handles (dump the
MTEXT entities with ezdxf). `template_map` also accepts an absolute path.

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

`tests/test_drawing.py` has 27 tests. They cover:

- **Views and sections:** handedness, hidden lines, distance, section volume and hatch loops.
- **Dimensions:** true-size dimensions; refusal of off-geometry points; text expectations;
  radius-arc and angle-leg checks; arrow fit; unilateral tolerances.
- **Text:** CJK styles; measured and glued wrapping; the line-start rule; missing glyphs.
- **Layout:** lint for text, symbols, masks, masked text over an outline, rewritten template text,
  and bracket ink against a line.
- **Output:** the DXF audit, B-size MediaBox, PDF line widths, Ø counters printing white, the
  render check, and detail clipping including a bridged clip.

It is not yet listed in `tools/run_native_tests.py`.
