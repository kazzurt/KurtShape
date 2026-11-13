"""A one-sheet drawing written to the Aerial Hedra engineering drawing standard of 2026-11-11
(C:/Users/Kurtz/Documents/Dodec/Drawing Template/Engineering Drawing Standard.md): the worked
example to copy from. It shows, by rule number:

  1, 2  one note, on sheet 1, saying what nothing else says; no loose text
  3     complete callouts built by callout(): thread with its class, THRU, counterbore and depth symbols
  4     hole_callout(): centre mark, radial leader to the near side; holes located by their centres
  5     leaders that cross neither leaders nor dimension lines
  6     view_label(): 'SECTION A-A' and nothing more, no scale because it is the sheet scale
  7     the section's cutting-plane line on the view that sees the plane edge-on
  8     one scale, stated in the title block
  10    set_weight(): pounds on an inch sheet, from the model's volume
  11    nothing in the title block, the revision table or the border

Run headless under the bundled interpreter, output to a file:

    runtime\\freecad-1.1.4\\FreeCAD_1.1.4-Windows-x86_64-py311\\bin\\pythonw.exe -B ^
        examples\\drawing_standard_example.py <output folder> > runtime\\drawing_standard_example.txt 2>&1

Writes 'Engineering Drawing Standard - example sheet' .dxf / .pdf / .png and a check report. It
exits 1 on any lint finding, as every drawing spec should.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
from kurtshape.drawing import sheet as SH, views as VW  # noqa: E402

TEMPLATES = Path(r"C:\Users\Kurtz\Documents\Dodec\Drawing Template")
STEM = "Engineering Drawing Standard - example sheet"
IN = 25.4
V = App.Vector

# Design values, inches. Every number on the sheet comes from these or is measured by a dimension.
LENGTH, WIDTH, THICK = 3.000, 2.000, 0.500
TAP_X, CBORE_X, HOLE_Y = 0.750, 2.250, 1.000
TAP_DRILL, THRU, CBORE, CBORE_DEPTH = 0.201, 0.281, 0.438, 0.250
DENSITY = 2.70                                          # g/cm3, 6061-T6


def build_part():
    plate = Part.makeBox(LENGTH * IN, WIDTH * IN, THICK * IN)
    tap = Part.makeCylinder(TAP_DRILL * IN / 2, THICK * IN, V(TAP_X * IN, HOLE_Y * IN, 0))
    thru = Part.makeCylinder(THRU * IN / 2, THICK * IN, V(CBORE_X * IN, HOLE_Y * IN, 0))
    cbore = Part.makeCylinder(CBORE * IN / 2, CBORE_DEPTH * IN, V(CBORE_X * IN, HOLE_Y * IN, (THICK - CBORE_DEPTH) * IN))
    return plate.cut(tap).cut(thru).cut(cbore)


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    part = build_part()
    top = VW.project(part, (1, 0, 0), (0, 1, 0), name="TOP")
    section = VW.section(part, (1, 0, 0), (0, 0, 1), offset=-HOLE_Y * IN, name="A-A")   # through both hole axes

    sh = SH.Sheet(TEMPLATES / "AH-B-in-sheet1.dxf", template_map=str(TEMPLATES / "AH-B-in-sheet1.json"))
    sh.fill({"TITLE": "EXAMPLE PLATE", "DWG_NO": "EXAMPLE", "REV": "A", "SCALE": "2:1", "SHEET": "1 OF 1",
             "MATERIAL": "6061-T6 ALUMINUM", "FINISH": "CLEAR ANODIZE PER MIL-PRF-8625\nTYPE II, CLASS 1",
             "DRAWN_NAME": "CLAUDE", "DRAWN_DATE": "2026-11-11"})
    sh.set_weight(part.Volume, DENSITY)                                     # rule 10
    sh.blank_placeholders()
    sh.revision_row(1, "A", "INITIAL DRAWING", "", date="2026-11-11")
    label = sh.map["notes_label"]["insert"]
    sh.notes((label[0], label[1] - 5.0), None, ["DIMENSIONS APPLY AFTER ANODIZING."], h=2.5, width_mm=110.0)

    # rule 8: both views at the sheet scale
    pt = sh.place(top, (140.0, 125.0), 2.0, "TOP", styles=("visible", "section"))
    ps = sh.place(section, (140.0, 72.0), 2.0, "A-A", styles=("visible", "section"), letter="A")
    # rule 7: the cutting-plane line on the view that sees the plane edge-on; rule 6: the label
    sh.cutting_plane(pt, (-6.0, HOLE_Y * IN), (LENGTH * IN + 6.0, HOLE_Y * IN), "A", toward=(0.0, 1.0))
    sh.view_label(ps, (140.0 + LENGTH * IN, 70.0))

    # rules 3 and 4: complete callouts on the view that looks down the holes
    sh.hole_callout(pt, (TAP_X * IN, HOLE_Y * IN), TAP_DRILL * IN / 2, (95.0, 200.0),
                    sh.callout(thread="1/4-20 UNC-2B", thru=True), side="left")
    sh.hole_callout(pt, (CBORE_X * IN, HOLE_Y * IN), THRU * IN / 2, (300.0, 240.0),
                    sh.callout(dia=THRU, thru=True, cbore=(CBORE, CBORE_DEPTH)))

    # size and location; the holes are located by their centres. Each value is given once (rule 9):
    # the counterbore depth is in the callout, so the section does not repeat it.
    sh.dim_linear(pt, (0.0, 0.0), (LENGTH * IN, 0.0), base=(0.0, -9.0), expect="3.000")
    sh.dim_linear(pt, (LENGTH * IN, 0.0), (LENGTH * IN, WIDTH * IN), base=(LENGTH * IN + 16.0, 0.0), angle=90,
                  expect="2.000")
    sh.dim_linear(pt, (0.0, WIDTH * IN), (TAP_X * IN, HOLE_Y * IN), base=(0.0, WIDTH * IN + 6.0), expect=".750")
    sh.dim_linear(pt, (0.0, WIDTH * IN), (CBORE_X * IN, HOLE_Y * IN), base=(0.0, WIDTH * IN + 12.0), expect="2.250")
    sh.dim_linear(pt, (0.0, 0.0), (TAP_X * IN, HOLE_Y * IN), base=(-8.0, 0.0), angle=90, expect="1.000")
    sh.dim_linear(ps, (0.0, 0.0), (0.0, THICK * IN), base=(-8.0, 0.0), angle=90, expect=".500")

    findings = sh.lint()
    sh.save(out / f"{STEM}.dxf")                                            # refuses a sheet off the standard
    sh.render(out / f"{STEM}.pdf", out / f"{STEM}.png", dpi=200, title=STEM)
    report = {"standard": sh.standard_report(), "lint": findings, "issues": sh.issues, "checks": sh.checks}
    (out / f"{STEM} - check report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("LINT", json.dumps(findings, indent=1))
    print("ISSUES", sh.issues)
    return 1 if findings or sh.issues else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()))
