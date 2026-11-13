"""2D drawing pipeline: view projection, sections, dimensions, tolerances, CJK text, DXF and PDF output.

Runs in the bundled interpreter with the drafting dependency installed
(tools/setup-drawing-deps.ps1); skips cleanly when ezdxf is missing.
"""
from pathlib import Path
import json
import math
import re
import sys
import unittest
import support  # noqa: F401 - isolated scratch and profile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.drawing import views as VW

try:
    from kurtshape.drawing import sheet as SH
    import ezdxf
except ImportError as exc:  # pragma: no cover - dependency not installed
    SH = None
    _MISSING = str(exc)

V = App.Vector
FRONT = ((1, 0, 0), (0, 0, 1))          # viewer on -Y looking +Y: world +X right, +Z up
RIGHT = ((0, 1, 0), (0, 0, 1))          # viewer on +X looking -X: world +Y right, +Z up
SHEET_BOX = [0.0, 0.0, 431.8, 279.4]   # B size, 17 x 11 in


def stepped_block():
    """10 x 4 x 6 block with a boss on its +X end and a hole through it along Y."""
    body = Part.makeBox(10, 4, 6, V(0, 0, 0))
    boss = Part.makeCylinder(1.0, 2.0, V(10, 2, 3), V(1, 0, 0))
    hole = Part.makeCylinder(1.0, 4.0, V(4, 0, 3), V(0, 1, 0))
    return body.fuse(boss).cut(hole).removeSplitter()


def bored_cylinder():
    """R5 x 10 cylinder on Z with an R2 bore: the classic hatched section."""
    return Part.makeCylinder(5, 10).cut(Part.makeCylinder(2, 10))


def polygon_area(loop):
    return 0.5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, loop[1:] + loop[:1])))


class ViewProjectionTests(unittest.TestCase):
    def test_front_view_keeps_world_handedness(self):
        view = VW.project(stepped_block(), *FRONT, name="front")
        x0, y0, x1, y1 = view.bbox()
        self.assertAlmostEqual(x0, 0.0, places=5)
        self.assertAlmostEqual(x1, 12.0, places=5)          # boss sticks out on the right, not mirrored
        self.assertAlmostEqual(y0, 0.0, places=5)
        self.assertAlmostEqual(y1, 6.0, places=5)
        circles = [c for c in view.curves if c.kind == "circle" and c.style == "visible"]
        self.assertTrue(any(abs(c.c[0] - 4.0) < 1e-6 and abs(c.c[1] - 3.0) < 1e-6 and abs(c.r - 1.0) < 1e-6
                            for c in circles), "the through hole is seen end-on as a circle")

    def test_hidden_edges_only_on_request(self):
        shape = stepped_block()
        plain = VW.project(shape, *RIGHT, name="right")
        with_hidden = VW.project(shape, *RIGHT, name="right", hidden=True)
        self.assertFalse([c for c in plain.curves if c.style == "hidden"])
        hidden = [c for c in with_hidden.curves if c.style == "hidden"]
        self.assertTrue(hidden, "the hole behind the boss face shows as hidden lines")
        # the right view sees the boss end-on at world (y, z) = (2, 3)
        self.assertTrue(any(c.kind == "circle" and abs(c.c[0] - 2.0) < 1e-6 and abs(c.c[1] - 3.0) < 1e-6
                            for c in plain.curves))

    def test_distance_to_geometry(self):
        view = VW.project(stepped_block(), *FRONT)
        self.assertLess(view.distance((5.0, 6.0)), 1e-6)    # top edge
        self.assertAlmostEqual(view.distance((5.0, 7.0)), 1.0, places=6)

    def test_axes_must_be_orthogonal(self):
        with self.assertRaises(ValueError):
            VW.project(stepped_block(), (1, 0, 0), (1, 0, 1))


class SectionTests(unittest.TestCase):
    def test_half_section_volume_and_hatch(self):
        view = VW.section(bored_cylinder(), *FRONT, name="A-A")
        self.assertAlmostEqual(view.meta["kept_volume"], math.pi * (25 - 4) * 10 / 2, places=4)
        self.assertEqual(len(view.hatch), 2, "two cut walls either side of the bore")
        self.assertAlmostEqual(sum(polygon_area(lp) for lp in view.hatch), 2 * 3 * 10, places=4)
        x0, y0, x1, y1 = view.bbox()
        self.assertAlmostEqual(x0, -5.0, places=5)
        self.assertAlmostEqual(x1, 5.0, places=5)

    def test_snap_closes_sub_micron_gaps_only(self):
        """Imported STEP cut faces can leave sub-micron gaps between edges: ``snap`` closes them
        and records each one; the default refuses them, and a snap above 2 microns is refused."""
        g = 0.0004
        pts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        edges = [Part.makeLine(V(*pts[0], 0), V(*pts[1], 0)), Part.makeLine(V(10 + g, 0, 0), V(*pts[2], 0)),
                 Part.makeLine(V(*pts[2], 0), V(*pts[3], 0)), Part.makeLine(V(*pts[3], 0), V(*pts[0], 0))]

        class Gapped:
            Edges = edges
        with self.assertRaises(RuntimeError):
            VW._wire_loop(Gapped)
        snaps = []
        loop = VW._wire_loop(Gapped, 0.002, snaps)
        self.assertEqual(len(loop), 4)
        self.assertAlmostEqual(polygon_area(loop), 50.0, places=2)
        self.assertEqual(len(snaps), 1)
        self.assertAlmostEqual(snaps[0], g, places=9)
        with self.assertRaises(ValueError):
            VW.section(bored_cylinder(), *FRONT, snap=0.01)
        self.assertEqual(VW.section(bored_cylinder(), *FRONT, snap=0.002).meta["snaps"], [])

    def test_section_without_material_on_the_plane_fails_loudly(self):
        far = Part.makeBox(2, 2, 2, V(0, 5, 0))            # entirely behind the plane: nothing is cut
        with self.assertRaises(RuntimeError):
            VW.section(far, *FRONT)


@unittest.skipIf(SH is None, "drawing dependency missing; run tools/setup-drawing-deps.ps1")
class SheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = support.TEST_TMP / "drawing"
        cls.dir.mkdir(parents=True, exist_ok=True)
        doc = ezdxf.new("R2018")
        msp = doc.modelspace()
        title = msp.add_mtext("----", dxfattribs={"insert": (300, 30), "char_height": 3.0})
        msp.add_line((330, 25), (330, 35))                  # the title cell's right border
        msp.add_lwpolyline([(SHEET_BOX[0], SHEET_BOX[1]), (SHEET_BOX[2], SHEET_BOX[1]),
                            (SHEET_BOX[2], SHEET_BOX[3]), (SHEET_BOX[0], SHEET_BOX[3])], close=True)
        cls.template = cls.dir / "template.dxf"
        doc.saveas(str(cls.template))
        cls.map = cls.dir / "template.json"
        cls.map.write_text(json.dumps({
            "fields": {"TITLE": {"handle": title.dxf.handle}},
            "sheet_box": SHEET_BOX, "logo_box": [400, 10, 420, 30],
            "revision_table": {"first_row_y": [250.0, 258.0], "row_height": 8.0, "data_ch": 2.5,
                               "columns_x": {"REV": [300, 310], "DESCRIPTION": [310, 380], "APPROVED": [380, 420]}},
            "lineweights": {}, "projection_symbol_handles": []}), encoding="utf-8")
        cls.view = VW.section(bored_cylinder(), *FRONT, name="A-A")

    def sheet(self, lang="en"):
        return SH.Sheet(self.template, template_map=str(self.map), lang=lang, standard=False)

    def map_variant(self, name, **changes):
        m = json.loads(self.map.read_text(encoding="utf-8"))
        m.update(changes)
        p = self.dir / f"template-{name}.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        return str(p)

    def test_inch_sheet_prints_inch_values_without_leading_zero(self):
        """A map with units 'in' prints model millimetres as inches to three decimals, ASME style
        (no leading zero), with tolerances given in inches by the spec; mm sheets are unchanged."""
        sh = SH.Sheet(self.template, template_map=self.map_variant("inch", units="in"), standard=False)
        self.assertEqual((sh.units, sh.dec), ("in", 3))
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        dim = sh.dim_linear(pv, (-5.0, 10.0), (5.0, 10.0), base=(0.0, 12.0), tol=("sym", 0.005), what="OD",
                            expect=".394±.005")                       # 10 mm = .3937 in
        lfac = dim.dimension.get_dim_style().dxf.dimlfac
        self.assertAlmostEqual(dim.dimension.get_measurement() * lfac, 10.0 / 25.4, places=6)
        mm = self.sheet()
        mm.dim_linear(mm.place(self.view, (100.0, 100.0), 5.0, "A-A"), (-5.0, 10.0), (5.0, 10.0), base=(0.0, 12.0),
                      what="OD", expect="10.00")

    def test_inch_sheet_prints_radii_in_inches(self):
        """dim_radius used to override DIMLFAC with 1/scale and printed an inch sheet's radius in
        millimetres; it now converts as dimstyle() does, at any view scale. ezdxf writes the 'R'
        itself, so the default text no longer doubles it."""
        top = VW.project(bored_cylinder(), (1, 0, 0), (0, 1, 0), name="top")      # R5 and R2 circles
        for scale in (1.0, 2.0, 5.0):
            sh = SH.Sheet(self.template, template_map=self.map_variant("inch-r", units="in"), standard=False)
            pv = sh.place(top, (100.0, 100.0), scale, "top")
            sh.dim_radius(pv, (0.0, 0.0), 5.0, 45.0, what="R5", expect="R.197")   # 5 mm = .1969 in
        sh.dim_radius(pv, (0.0, 0.0), 2.0, 200.0, text="4X <>", what="4X R2", expect="4X R.079")
        mm = self.sheet()
        mm.dim_radius(mm.place(top, (100.0, 100.0), 2.0, "top"), (0.0, 0.0), 2.0, 45.0, what="R2", expect="R2.00")

    def test_revision_row_fills_a_date_column_under_the_header(self):
        """The Aerial Hedra templates ship an empty revision table: rows start at next_row_top,
        every column boundary gets its line, and a DATE column is filled when given."""
        rt = {"next_row_top": 256.0, "first_row_y": [249.0, 256.0], "row_height": 7.0, "data_ch": 2.5,
              "text_inset": 1.2, "columns_x": {"REV": [275.4, 288.1], "DESCRIPTION": [288.1, 373.1],
                                               "DATE": [373.1, 395.1], "APPROVED": [395.1, 419.1]}}
        sh = SH.Sheet(self.template, template_map=self.map_variant("rev", revision_table=rt), standard=False)
        sh.revision_row(1, "A", "INITIAL RELEASE", "KZ", date="2026-10-28")
        sh.revision_row(2, "B", "SECOND", date="2026-10-29")
        texts = {e.plain_text(): e.dxf.insert for e in sh.msp.query("MTEXT[layer=='TABLES']")}
        self.assertAlmostEqual(texts["2026-10-28"].y, 252.5, places=6)      # centred in the first row
        self.assertAlmostEqual(texts["2026-10-29"].y, 245.5, places=6)      # the row below it
        lines = list(sh.msp.query("LINE[layer=='TABLES']"))
        ys = sorted({round(e.dxf.start.y, 3) for e in lines if abs(e.dxf.start.y - e.dxf.end.y) < 1e-9})
        xs = sorted({round(e.dxf.start.x, 3) for e in lines if abs(e.dxf.start.x - e.dxf.end.x) < 1e-9})
        self.assertEqual(ys, [242.0, 249.0])                                # row bottoms; the header is the template's
        self.assertEqual(xs, [275.4, 288.1, 373.1, 395.1, 419.1])
        with self.assertRaises(SH.DrawingError):                            # the Onshape map has no DATE column
            self.sheet().revision_row(1, "A", "X", date="2026-10-28")

    def test_set_fixed_rewrites_a_template_text_by_name(self):
        handle = json.loads(self.map.read_text(encoding="utf-8"))["fields"]["TITLE"]["handle"]
        sh = SH.Sheet(self.template, template_map=self.map_variant("fixed", fixed_texts={"UNITS": {"handle": handle}}), standard=False)
        e = sh.set_fixed("UNITS", "DIMENSIONS ARE IN INCHES")
        self.assertEqual(e.plain_text(), "DIMENSIONS ARE IN INCHES")
        self.assertIn(handle, sh._touched)                                  # lint tests it like drawing text
        with self.assertRaises(SH.DrawingError):
            sh.set_fixed("NO_SUCH_TEXT", "x")

    def test_dimension_reads_true_size_at_any_scale(self):
        sh = self.sheet()
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        dim = sh.dim_linear(pv, (-5.0, 10.0), (5.0, 10.0), base=(0.0, 12.0), angle=0, text="%%c<>",
                            tol=("sym", 0.03), what="OD")
        measured = dim.dimension.get_measurement()
        lfac = dim.dimension.get_dim_style().dxf.dimlfac
        self.assertAlmostEqual(measured, 50.0, places=6)            # 10 mm drawn at 5:1
        self.assertAlmostEqual(measured * lfac, 10.0, places=6)     # reads 10.00 in any CAD program
        self.assertEqual(dim.dimension.dxf.layer, "AH_DIM")

    def test_dimension_off_the_geometry_is_refused(self):
        sh = self.sheet()
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        with self.assertRaises(SH.DrawingError):
            sh.dim_linear(pv, (-5.0, 10.0), (4.5, 5.0), base=(0.0, 12.0), what="not an edge")
        self.assertTrue(any(c["dim"] == "not an edge" and c["distance"] > 0.01 for c in sh.checks))

    def test_unilateral_tolerance_prints_zero(self):
        sh = self.sheet()
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        dim = sh.dim_linear(pv, (2.0, 0.0), (5.0, 0.0), base=(0.0, -2.0), tol=("dev", 0.0, -0.05))
        self.assertEqual(dim["dimtol"], 1)
        self.assertAlmostEqual(dim["dimtp"], 0.0)
        self.assertAlmostEqual(dim["dimtm"], 0.05)          # DXF stores the lower deviation as a positive number
        self.assertEqual(dim["dimtzin"], 8)                 # the zero deviation prints as '0'
        with self.assertRaises(SH.DrawingError):
            sh.dim_linear(pv, (2.0, 0.0), (5.0, 0.0), base=(0.0, -2.0), tol=("dev", 0.05, 0.02))

    def test_cjk_text_uses_the_cjk_style(self):
        sh = self.sheet("zh")
        e = sh.text((20, 200), "技术要求", h=3.0)
        self.assertEqual(e.dxf.style, SH.CJK_FONT[0])
        sh.fill({"TITLE": "螺栓"})
        title = sh.doc.entitydb.get(json.loads(self.map.read_text())["fields"]["TITLE"]["handle"])
        self.assertEqual(title.dxf.style, SH.CJK_FONT[0])
        self.assertTrue(SH._has_cjk("O 形圈"))
        self.assertFalse(SH._has_cjk("O-RING"))
        lines = SH._wrap("材料：17-4PH 不锈钢，按 ASTM A564，H1150 时效状态。", 10)
        self.assertGreater(len(lines), 1)
        self.assertFalse(any(ln.startswith(("，", "。")) for ln in lines), "no line starts with punctuation")
        with self.assertRaises(SH.DrawingError):
            sh.fill({"NOT_A_FIELD": "x"})

    def test_dimension_text_is_checked_against_the_spec(self):
        sh = self.sheet()
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        sh.dim_linear(pv, (-5.0, 10.0), (5.0, 10.0), base=(0.0, 12.0), text="%%c<>", tol=("sym", 0.03),
                      expect="Ø10.00±0.03")
        with self.assertRaises(SH.DrawingError):
            sh.dim_linear(pv, (-5.0, 10.0), (5.0, 10.0), base=(0.0, 13.0), text="%%c<>", tol=("sym", 0.03),
                          expect="Ø10.50±0.03")

    def test_lint_tests_turned_text_by_its_own_rectangle(self):
        """An aligned dimension's value is turned off the sheet axes. Lint tests it by its real
        rectangle: a line running alongside it is clear (its axis-aligned box would have hit it),
        a line across it, and a text overlapping it, are still found."""
        a = math.radians(30.0)
        ux, uy, nx, ny = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
        sh = self.sheet()
        sh.text((100.0, 100.0), "3X 1.250 ALONG THE ARM", h=3.0, attach="MIDDLE_CENTER", rotation=30.0)
        off = 4.0                                    # mm beside the text's middle line
        sh.line((100.0 - 25 * ux + off * nx, 100.0 - 25 * uy + off * ny), (100.0 + 25 * ux + off * nx, 100.0 + 25 * uy + off * ny))
        self.assertEqual([c for c in sh.lint() if c["kind"] == "text-line"], [])
        sh.line((100.0 - 6 * nx, 100.0 - 6 * ny), (100.0 + 6 * nx, 100.0 + 6 * ny))      # straight across it
        self.assertEqual(len([c for c in sh.lint() if c["kind"] == "text-line"]), 1)
        sh2 = self.sheet()
        sh2.text((100.0, 100.0), "3X 1.250 ALONG THE ARM", h=3.0, attach="MIDDLE_CENTER", rotation=30.0)
        sh2.text((100.0 + 9 * nx, 100.0 + 9 * ny), "OTHER", h=3.0, attach="MIDDLE_CENTER")   # clear of it
        self.assertEqual([c for c in sh2.lint() if c["kind"] == "text-text"], [])
        sh2.text((100.0 + 8 * ux, 100.0 + 8 * uy), "ON IT", h=3.0, attach="MIDDLE_CENTER")
        self.assertTrue([c for c in sh2.lint() if c["kind"] == "text-text"])

    def test_a_turned_value_moved_outside_gets_its_line_carried_to_its_edge(self):
        """A value moved past the extension lines of an aligned dimension is turned with it; the
        dimension line carried to it stops at its real edge, not at its axis-aligned box."""
        sh = self.sheet()
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        a = math.radians(60.0)
        base = (5.0 + 3.0 * -math.sin(a), 0.0 + 3.0 * math.cos(a))
        far = (base[0] + 18.0 * math.cos(a), base[1] + 18.0 * math.sin(a))
        sh.dim_linear(pv, (5.0, 0.0), (5.0, 2.0), base=base, angle=60.0, text="3X <>", text_pos=far,
                      what="turned", expect="3X 1.73")             # 2 mm measured along 60 degrees
        own = [c for c in sh.lint() if c["kind"] == "text-line" and "/own" in c["with"]]
        self.assertEqual(own, [])

    def test_radius_on_a_bspline_fillet_edge_needs_a_close_fit(self):
        """A fillet modelled as a B-spline surface projects as a polyline: with fit_tol it counts
        as the arc when every point lies that close to the circle, and the deviation is recorded."""
        sh = SH.Sheet(self.template, template_map=self.map_variant("inch-fit", units="in"), standard=False)
        pts = [(6.35 * math.cos(math.radians(a)) + 0.004 * math.sin(math.radians(7 * a)),
                6.35 * math.sin(math.radians(a))) for a in range(0, 91, 3)]
        view = VW.View("blend", curves=[VW.Curve("poly", "section", pts=pts)])
        pv = sh.place(view, (100.0, 100.0), 2.0, "blend")
        with self.assertRaises(SH.DrawingError):
            sh.dim_radius(pv, (0.0, 0.0), 6.35, 45.0, what="no fit asked")
        with self.assertRaises(SH.DrawingError):
            sh.dim_radius(pv, (0.0, 0.0), 6.35, 45.0, what="too loose", fit_tol=0.05)
        with self.assertRaises(SH.DrawingError):
            sh.dim_radius(pv, (0.0, 0.0), 6.30, 45.0, what="wrong radius", fit_tol=0.01)
        sh.dim_radius(pv, (0.0, 0.0), 6.35, 45.0, text="3X <>", what="R.250", expect="3X R.250", fit_tol=0.01)
        rec = [c for c in sh.checks if c.get("dim") == "R.250" and "fitted_bspline_arcs" in c][0]
        self.assertLessEqual(rec["fitted_bspline_arcs"][0]["max_deviation_mm"], 0.005)

    def test_diameter_and_bolt_circle(self):
        """dim_diameter needs the circle in the view; with pattern=n it dimensions a bolt circle
        through n hole centres and draws its centre-line circle."""
        plate = Part.makeBox(40, 40, 5, V(-20, -20, 0)).cut(Part.makeCylinder(8, 5))
        for k in range(3):
            a = math.radians(90 + 120 * k)
            plate = plate.cut(Part.makeCylinder(1.5, 5, V(12.7 * math.cos(a), 12.7 * math.sin(a), 0)))
        top = VW.project(plate, (1, 0, 0), (0, 1, 0), name="top")
        sh = SH.Sheet(self.template, template_map=self.map_variant("inch-dia", units="in"), standard=False)
        pv = sh.place(top, (100.0, 100.0), 2.0, "top")
        sh.dim_diameter(pv, (0.0, 0.0), 8.0, 30.0, what="bore", expect="Ø.630")
        with self.assertRaises(SH.DrawingError):
            sh.dim_diameter(pv, (0.0, 0.0), 9.0, 30.0, what="no such circle")
        n0 = len(sh.msp.query("CIRCLE[layer=='AH_CENTER']"))
        sh.dim_diameter(pv, (0.0, 0.0), 12.7, 150.0, what="B.C.", expect="Ø1.000", pattern=3)
        self.assertEqual(len(sh.msp.query("CIRCLE[layer=='AH_CENTER']")), n0 + 1)
        with self.assertRaises(SH.DrawingError):
            sh.dim_diameter(pv, (0.0, 0.0), 12.0, 150.0, what="off the centres", pattern=3)

    def test_diameter_called_out_from_outside_meets_the_near_side(self):
        """A diameter whose value sits outside the circle gets one radial leader to the near side
        (arrow pointing in), no line across the circle, whatever ``angle`` says."""
        view = VW.View("end", curves=[VW.Curve("circle", "visible", c=(0.0, 0.0), r=10.0)])
        sh = SH.Sheet(self.template, template_map=self.map_variant("inch-dia-out", units="in"), standard=False)
        pv = sh.place(view, (100.0, 100.0), 2.0, "end")
        with self.assertRaises(SH.DrawingError):            # a value inside the circle is no callout from outside
            sh.dim_diameter(pv, (0.0, 0.0), 10.0, 0.0, location=(105.0, 105.0), what="inside")
        dim = sh.dim_diameter(pv, (0.0, 0.0), 10.0, 225.0, location=(140.0, 140.0), what="OD", expect="Ø.787")
        block = sh.doc.blocks.get(dim.dimension.dxf.geometry)
        for e in block.query("LINE"):
            for p in (e.dxf.start, e.dxf.end):
                d = math.hypot(p[0] - 100.0, p[1] - 100.0)
                self.assertGreater(d, 20.0 - 0.01, "a dimension line runs inside the circle")
                self.assertGreater((p[0] - 100.0) + (p[1] - 100.0), 0.0, "the leader is not on the near side")

    def test_hole_split_into_bspline_pieces_needs_full_coverage(self):
        """A radial hole in a tube projects its saddle edge as two open B-spline halves: with
        fit_tol the pieces count as the hole only when together they go all the way round."""
        half = lambda a0: [(3.0 * math.cos(math.radians(a)), 3.0 * math.sin(math.radians(a)))  # noqa: E731
                           for a in range(a0, a0 + 181, 5)]
        both = VW.View("both", curves=[VW.Curve("poly", "visible", pts=half(0)),
                                       VW.Curve("poly", "visible", pts=half(180))])
        one = VW.View("one", curves=[VW.Curve("poly", "visible", pts=half(0))])
        sh = SH.Sheet(self.template, template_map=self.map_variant("inch-halves", units="in"), standard=False)
        lines = sh.callout(qty=6, dia=0.236, thru=True)
        p1 = sh.place(one, (100.0, 100.0), 2.0, "one")
        with self.assertRaises(SH.DrawingError):            # half a circle is not a hole
            sh.hole_callout(p1, (0.0, 0.0), 3.0, (130.0, 130.0), lines, fit_tol=0.01)
        p2 = sh.place(both, (250.0, 100.0), 2.0, "both")
        with self.assertRaises(SH.DrawingError):            # not without fit_tol
            sh.hole_callout(p2, (0.0, 0.0), 3.0, (280.0, 130.0), lines)
        sh.hole_callout(p2, (0.0, 0.0), 3.0, (280.0, 130.0), lines, fit_tol=0.01)
        rec = [c for c in sh.checks if c.get("fitted_bspline_pieces")][0]
        self.assertEqual(rec["fitted_bspline_pieces"], 2)

    def test_bspline_loops_count_as_holes_only_when_asked(self):
        """A hole edge that a STEP file carries as a B-spline projects as a closed polyline: with
        fit_tol, hole_callout and dim_diameter take it as the circle and lint checks the leader
        against it; a boss outline broken into arcs takes a diameter whose ends lie on the arcs."""
        loop = [(4.0 * math.cos(math.radians(a)), 4.0 * math.sin(math.radians(a))) for a in range(0, 361, 5)]
        arcs = [VW.Curve("arc", "visible", c=(0.0, 0.0), r=10.0, a0=0.0, a1=200.0),
                VW.Curve("arc", "visible", c=(0.0, 0.0), r=10.0, a0=200.0, a1=360.0)]
        view = VW.View("end", curves=[VW.Curve("poly", "visible", pts=loop)] + arcs)
        sh = SH.Sheet(self.template, template_map=self.map_variant("inch-loop", units="in"), standard=False)
        pv = sh.place(view, (100.0, 100.0), 2.0, "end")
        lines = sh.callout(qty=3, thread="7/8-14 UNF-3B", depth=0.7)
        with self.assertRaises(SH.DrawingError):
            sh.hole_callout(pv, (0.0, 0.0), 4.0, (140.0, 130.0), lines)
        sh.hole_callout(pv, (0.0, 0.0), 4.0, (140.0, 130.0), lines, fit_tol=0.005)
        self.assertEqual(len(sh._fitted_circles), 1)
        # a hole accepted with fit_tol locates dimensions by its centre, like any circle
        lone = VW.View("lone", curves=[VW.Curve("poly", "visible", pts=loop),
                                       VW.Curve("line", "visible", p=(10.0, -5.0), q=(10.0, 5.0))])
        sl = SH.Sheet(self.template, template_map=self.map_variant("inch-lone", units="in"), standard=False)
        pl = sl.place(lone, (100.0, 100.0), 2.0, "lone")
        with self.assertRaises(SH.DrawingError):           # not yet a known hole: its centre is off the geometry
            sl.dim_linear(pl, (10.0, 0.0), (0.0, 0.0), base=(0.0, -14.0), what="to the loop's centre")
        sl.hole_callout(pl, (0.0, 0.0), 4.0, (140.0, 130.0), lines, fit_tol=0.005)
        sl.dim_linear(pl, (10.0, 0.0), (0.0, 0.0), base=(0.0, -14.0), what="to the hole's centre", expect=".394")
        sh.dim_diameter(pv, (0.0, 0.0), 4.0, 200.0, what="loop", expect="Ø.315", fit_tol=0.005)
        sh.dim_diameter(pv, (0.0, 0.0), 10.0, 250.0, what="arcs", expect="Ø.787")
        std = SH.Sheet(self.template, template_map=self.map_variant("inch-loop", units="in"), standard=True)
        std.set_scale(2.0)
        p2 = std.place(view, (100.0, 100.0), 2.0, "end")
        std.hole_callout(p2, (0.0, 0.0), 4.0, (140.0, 130.0), lines, fit_tol=0.005)
        std.leader((100.0 + 8.0 * math.cos(1.0), 100.0 + 8.0 * math.sin(1.0)), (60.0, 140.0), "X")   # not radial
        self.assertIn("leader-not-radial", {c["kind"] for c in std.lint()})

    def test_radius_needs_a_real_arc_and_angles_check_their_legs(self):
        sh = self.sheet()
        cone = Part.makeCone(5, 2, 6).cut(Part.makeCylinder(1, 6))
        view = VW.section(cone, *FRONT, name="cone")
        pv = sh.place(view, (100.0, 100.0), 5.0, "cone")
        with self.assertRaises(SH.DrawingError):     # the corner at (5, 0) is not an arc
            sh.dim_radius(pv, (4.0, 0.0), 1.0, 0.0, what="no arc here")
        half = math.degrees(math.atan2(3.0, 6.0))
        apex = (0.0, 5.0 / math.tan(math.radians(half)))
        dim = sh.dim_angle(pv, apex, (-5.0, 0.0), (5.0, 0.0), base=(0.0, -3.0), leg_check=-1.0, what="cone",
                           dec=1)
        self.assertAlmostEqual(dim.dimension.get_measurement(), 2 * half, places=6)   # degrees
        with self.assertRaises(SH.DrawingError):     # a wrong apex sends the legs off the cone
            sh.dim_angle(pv, (0.0, 20.0), (-5.0, 0.0), (5.0, 0.0), base=(0.0, -3.0), leg_check=-1.0, what="bad")

    def test_roughness_never_reads_upside_down(self):
        sh = self.sheet()
        sh.roughness((50.0, 50.0), "Ra 1.6", direction=-90.0)
        sh.roughness((50.0, 80.0), "Ra 1.6", direction=0.0)
        for bad in (90.0, 180.0):
            with self.assertRaises(SH.DrawingError):
                sh.roughness((50.0, 110.0), "Ra 1.6", direction=bad)
        sh.roughness_leader((80.0, 50.0), (90.0, 40.0), "Ra 0.8")

    def test_measured_wrap_keeps_words_and_punctuation(self):
        sh = self.sheet("zh")
        text = "驱动槽：内六角花形 T40，按 ISO 10664（GB/T 6188），通规插入深度 t=2.3~2.7；槽形仅供参考。"
        lines = sh.wrap(text, 40.0, 3.0)
        self.assertGreater(len(lines), 1)
        for ln in lines:
            self.assertLessEqual(sh.text_width(ln, 3.0), 40.0 + sh.text_width("，", 3.0))
            self.assertFalse(ln[0] in "，。；：、）", ln)
            self.assertNotEqual(ln[-1], "（", ln)
        self.assertIn("t=2.3~2.7", "".join(lines))          # Latin runs are never split
        self.assertEqual("".join(lines).replace(" ", ""), text.replace(" ", ""))
        en = self.sheet().wrap("BREAK OTHER SHARP EDGES 0.1–0.2, PARTS FREE OF CRACKS AND BURRS.", 50.0, 3.0)
        self.assertTrue(all(w in " ".join(en).split() for w in ("0.1–0.2,", "CRACKS")))

    def test_lint_finds_text_on_text_and_on_geometry(self):
        sh = self.sheet()
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        self.assertEqual([c for c in sh.lint() if c["kind"] != "text-text" or "----" not in c["text"]], [])
        sh.text((60.0, 200.0), "FIRST NOTE", h=3.0)
        sh.text((62.0, 199.0), "SECOND NOTE", h=3.0)
        sh.text((pv.s((-5.0, 5.0))[0] - 4.0, pv.s((0, 5.0))[1]), "ON THE EDGE", h=3.0, attach="MIDDLE_LEFT")
        kinds = {(c["kind"], c["text"]) for c in sh.lint()}
        self.assertIn(("text-text", "FIRST NOTE"), kinds)
        self.assertTrue(any(k == "text-line" and t == "ON THE EDGE" for k, t in kinds) or
                        any(k == "text-hatch" and t == "ON THE EDGE" for k, t in kinds))
        masked = self.sheet()
        pv2 = masked.place(self.view, (100.0, 100.0), 5.0, "A-A")
        masked.dim_linear(pv2, (2.0, 0.0), (2.0, 10.0), base=(1.0, 0.0), angle=90, text="(<>)", mask=True)
        self.assertFalse([c for c in masked.lint() if c["kind"] == "text-line" and "(10.00)" in c["text"]])

    def test_save_audits_and_renders_a_b_size_pdf(self):
        sh = self.sheet()
        pv = sh.place(self.view, (150.0, 120.0), 5.0, "A-A")
        sh.dim_linear(pv, (-5.0, 10.0), (5.0, 10.0), base=(0.0, 12.0), text="%%c<>", tol=("sym", 0.03))
        sh.fcf(pv.s((6.0, 5.0)), "runout", "0.05", ("A",))
        sh.roughness(pv.s((5.0, 10.0)), "Ra 1.6", direction=-90.0)
        sh.notes((15, 260), "NOTES:", ["FIRST NOTE.", "SECOND NOTE THAT IS LONG ENOUGH TO WRAP ONTO A LINE."],
                 width_mm=60.0, bottom=150.0)
        dxf = sh.save(self.dir / "sheet.dxf")
        doc = ezdxf.readfile(str(dxf))
        self.assertFalse(doc.audit().has_errors)
        self.assertEqual(doc.header["$INSUNITS"], 4)
        self.assertEqual(len(doc.modelspace().query("DIMENSION")), 1)
        self.assertEqual(len(doc.modelspace().query("HATCH[layer=='AH_HATCH']")), 1)
        self.assertEqual(len(doc.modelspace().query("WIPEOUT")), 1)
        pdf = self.dir / "sheet.pdf"
        sh.render(pdf, self.dir / "sheet.png", dpi=150, title="TEST SHEET")
        # masks (the frame's WIPEOUT) print white, nothing prints in colour
        self.assertFalse([i for i in sh.issues if i.startswith("render")], sh.issues)
        raw = pdf.read_bytes()
        self.assertTrue(raw.startswith(b"%PDF"))
        box = [float(v) for v in re.search(rb"/MediaBox\s*\[\s*([\d.\s]+)\]", raw).group(1).split()]
        self.assertAlmostEqual(box[2] - box[0], 17 * 72, delta=0.5)
        self.assertAlmostEqual(box[3] - box[1], 11 * 72, delta=0.5)
        self.assertIn(b"TEST SHEET", raw)
        # line widths in points: 0.50 mm visible lines print 1.42 pt, nothing under 0.13 mm
        import zlib
        widths = set()
        for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
            try:
                data = zlib.decompress(m.group(1))
            except zlib.error:
                continue
            widths.update(float(w) for w in re.findall(rb"([\d.]+) w\b", data))
        self.assertIn(round(0.50 * 72 / 25.4, 2), {round(w, 2) for w in widths})
        stroked = [w for w in widths if w > 0]               # '0 w' belongs to filled shapes
        self.assertGreaterEqual(min(stroked), 0.13 * 72 / 25.4 - 0.01)

    def test_glyph_counters_print_white(self):
        """Ø's counter is split by its stroke; ezdxf's hole detection used to fill one half."""
        from PIL import Image
        for lang in ("en", "zh"):
            sh = self.sheet(lang)
            e = sh.text((100.0, 100.0), "Ø", h=10.0, attach="MIDDLE_CENTER")
            x0, y0, x1, y1 = SH._mtext_box(e)
            png = self.dir / f"glyph_{lang}.png"
            sh.render(self.dir / f"glyph_{lang}.pdf", png, dpi=200)
            img = Image.open(png).convert("L")
            W, H = img.size
            px = W / (SHEET_BOX[2] - SHEET_BOX[0])
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            for dx in (-0.22, 0.22):
                x = (cx + dx * (x1 - x0) - SHEET_BOX[0]) * px
                y = H - (cy - SHEET_BOX[1]) * px
                self.assertGreater(img.getpixel((int(x), int(y))), 200, f"{lang}: Ø counter at {dx:+} is filled")

    def test_glue_and_back_off_wrapping(self):
        self.assertEqual(SH._tokens("硬度 630 型 钢"), ["硬", "度", " ", "630 型", " ", "钢"])
        self.assertIn("3 件", SH._tokens("试验 3 件（"))
        sh = self.sheet("zh")
        text = "膜厚 10~20 µm（ISO 2178），涂层光滑均匀"
        w = sh.text_width("膜厚 10~20 µm（ISO 2178）", 3.5) + 0.5   # '，' would overflow this width
        lines = sh.wrap(text, w, 3.5)
        self.assertFalse(lines[1].startswith("，"))
        self.assertTrue(all(sh.text_width(ln, 3.5) <= w + 1e-6 for ln in lines), lines)
        # two closing marks in a row: neither may start the next line
        text = "模型螺纹及大径为名义值（大于 2A 上限），螺纹按技术要求 3 加工"
        for cut in range(4, 30):
            w = sh.text_width(text[:cut], 3.5) + 0.2
            for ln in sh.wrap(text, w, 3.5)[1:]:
                self.assertFalse(ln[0] in "，。；：、）", (cut, ln))

    def test_arrows_must_fit_between_extension_lines(self):
        sh = self.sheet()
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        with self.assertRaises(SH.DrawingError):            # 0.5 mm at 5:1 = 2.5 mm: no room for two arrows
            sh.dim_linear(pv, (5.0, 10.0), (5.0, 9.5), base=(7.0, 0.0), angle=90, what="tiny")

    def test_lint_finds_symbols_and_masks_over_geometry(self):
        sh = self.sheet()
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        self.assertFalse([c for c in sh.lint() if c["kind"] in ("symbol-line", "mask-geometry", "mask-hatch")])
        sh.roughness(pv.s((-3.5, 6.0)), "Ra 1.6", direction=-90.0)      # standing across the bore wall
        sh.fcf(pv.s((4.0, 4.0)), "runout", "0.05", ("A",))               # a mask over the outline
        kinds = {c["kind"] for c in sh.lint()}
        self.assertIn("symbol-line", kinds)
        self.assertTrue({"mask-geometry", "mask-hatch"} & kinds, kinds)

    def test_masked_text_may_not_hide_geometry(self):
        sh = self.sheet()
        pv = sh.place(self.view, (100.0, 100.0), 5.0, "A-A")
        # a masked value right on the outer wall (x = 5): its mask would blank the outline
        sh.dim_linear(pv, (2.0, 10.0), (5.0, 0.0), base=(4.3, 0.0), angle=90, text="(<>)", mask=True,
                      what="masked over the wall")
        self.assertTrue(any(c["kind"] in ("mask-geometry", "mask-hatch") for c in sh.lint()))

    def test_rewritten_template_text_is_linted(self):
        """A title-block text the drawing rewrote is tested against the template's own cell lines
        (untouched template texts are not, so this fails if rewritten texts lose their group)."""
        sh = self.sheet()
        sh.fill({"TITLE": "A TITLE LONG ENOUGH TO RUN OUT OF ITS CELL"})
        title = sh.doc.entitydb.get(json.loads(self.map.read_text())["fields"]["TITLE"]["handle"])
        x0, y0, x1, y1 = SH._mtext_box(title)
        self.assertTrue(any(c["kind"] == "text-line" and "A TITLE" in c["text"] and "template" in c["with"]
                            for c in sh.lint()), (x0, x1))
        quiet = self.sheet()
        quiet.fill({"TITLE": "SHORT"})
        self.assertFalse([c for c in quiet.lint() if "SHORT" in c["text"]])

    def test_bracket_ink_counts_against_lines(self):
        sh = self.sheet()
        e = sh.text((50.0, 50.0), "(2.50)", h=3.0, attach="BOTTOM_LEFT")
        x0, y0, x1, y1 = SH._mtext_box(e)
        sh.line((x0 - 5.0, y1 + 0.25), (x1 + 5.0, y1 + 0.25), layer="AH_VISIBLE")   # just over the cap line
        self.assertTrue(any(c["kind"] == "text-line" and "(2.50)" in c["text"] for c in sh.lint()))

    def test_detail_clip_that_splits_a_face_is_refused(self):
        u = [(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (4.0, 4.0), (4.0, 1.0), (2.0, 1.0), (2.0, 4.0), (0.0, 4.0)]
        clipped = SH._clip_polygon_circle(u, (3.0, 3.0), 1.6)
        self.assertFalse(SH._is_simple(clipped))                          # two legs joined by a bridge
        self.assertTrue(SH._is_simple(SH._clip_polygon_circle(u, (3.0, 0.5), 1.0)))

    def test_missing_glyphs_fail_the_save(self):
        sh = self.sheet()
        # A reserved Unicode noncharacter avoids assuming which real symbols
        # the machine's Noto Sans (or resolved fallback font) supports.
        missing = "\U0010FFFF"
        sh.text((50.0, 50.0), "MISSING " + missing, h=3.0)
        self.assertTrue(any(ch == missing for ch, _, _ in sh.missing_glyphs()))
        destination = self.dir / "tofu.dxf"
        with self.assertRaises(SH.DrawingError):
            sh.save(destination)
        self.assertFalse(destination.exists())
        ok = self.sheet()
        ok.text((50.0, 50.0), "Ø11.00 ±0.03 40° µm – ×", h=3.0)
        self.assertEqual(ok.missing_glyphs(), [])

    def test_render_check_flags_a_black_block(self):
        sh = self.sheet()
        h = sh.msp.add_hatch(color=7)                       # a 4 mm solid square: a mask gone black
        h.paths.add_polyline_path([(100, 100), (104, 100), (104, 104), (100, 104)], is_closed=True)
        sh.render(self.dir / "block.pdf", self.dir / "block.png", dpi=150)
        self.assertTrue(any("solid black block" in i for i in sh.issues), sh.issues)

    def test_detail_clip_keeps_only_the_circle(self):
        square = [(-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0)]
        clipped = SH._clip_polygon_circle(square, (0.0, 0.0), 1.0, n=256)
        self.assertAlmostEqual(polygon_area(clipped), math.pi, delta=0.01)
        runs = SH._clip_samples([(-3.0, 0.0), (3.0, 0.0)], (0.0, 0.0), 1.0)
        self.assertEqual(len(runs), 1)
        self.assertAlmostEqual(runs[0][0][0], -1.0, delta=0.01)
        self.assertAlmostEqual(runs[0][-1][0], 1.0, delta=0.01)


@unittest.skipIf(SH is None, "drawing dependency missing; run tools/setup-drawing-deps.ps1")
class StandardTests(unittest.TestCase):
    """The Aerial Hedra engineering drawing standard of 2026-11-11, as the sheet enforces it
    (Documents/Dodec/Drawing Template/Engineering Drawing Standard.md)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = support.TEST_TMP / "drawing-standard"
        cls.dir.mkdir(parents=True, exist_ok=True)
        doc = ezdxf.new("R2018")
        msp = doc.modelspace()
        fields = {}
        for k, key in enumerate(("TITLE", "SCALE", "WEIGHT", "SHEET", "MATERIAL", "FINISH")):
            e = msp.add_mtext("----", dxfattribs={"insert": (330.0, 20.0 + 6.0 * k), "char_height": 2.5})
            fields[key] = {"handle": e.dxf.handle}
        edges = msp.add_mtext("BREAK SHARP EDGES, REMOVE BURRS", dxfattribs={"insert": (220.0, 34.0), "char_height": 1.7})
        noscale = msp.add_mtext("DO NOT SCALE DRAWING", dxfattribs={"insert": (220.0, 30.0), "char_height": 1.7})
        cls.template = cls.dir / "template.dxf"
        doc.saveas(str(cls.template))
        base = {"fields": fields,
                "fixed_texts": {"EDGES": {"handle": edges.dxf.handle}, "NO_SCALE": {"handle": noscale.dxf.handle}},
                "sheet_box": SHEET_BOX, "logo_box": [400, 10, 420, 30], "frame_box": [12.7, 12.7, 419.1, 266.7],
                "title_block_box": [215.9, 12.7, 419.1, 63.5], "revision_table_box": [275.4, 256.0, 419.1, 266.7],
                "revision_table": None, "notes_label": {"insert": [15.3, 262.5]}, "placeholders": ["----", "-"],
                "lineweights": {}, "projection_symbol_handles": [], "units": "in", "sheet": "1"}
        cls.maps = {}
        for name, changes in (("in", {}), ("mm", {"units": "mm"}), ("cont", {"notes_label": None, "sheet": "N"})):
            p = cls.dir / f"template-{name}.json"
            p.write_text(json.dumps(dict(base, **changes)), encoding="utf-8")
            cls.maps[name] = p
        plate = Part.makeBox(40, 30, 10).cut(Part.makeCylinder(4, 10, V(12, 15, 0)))
        cls.top = VW.project(plate, (1, 0, 0), (0, 1, 0), name="TOP")       # the hole end-on at (12, 15), r 4
        cls.sec = VW.section(plate, *FRONT, offset=-15.0, name="A-A")       # cut through the hole axis

    def std(self, variant="in", scale="1:1", sheet="1 OF 1", weight=True, standard=True):
        sh = SH.Sheet(self.template, template_map=str(self.maps[variant]), standard=standard)
        sh.fill({"TITLE": "PLATE", "SCALE": scale, "SHEET": sheet, "MATERIAL": "6061-T6 ALUMINUM",
                 "FINISH": "CLEAR ANODIZE"})
        if weight:
            sh.set_weight(11500.0, 2.70)            # 31.05 g
        return sh

    def kinds(self, sh):
        return {c["kind"] for c in sh.lint() if c["kind"] in SH.STANDARD_KINDS}

    def test_a_sheet_that_follows_the_standard_saves(self):
        sh = self.std()
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        sh.hole_callout(pt, (12.0, 15.0), 4.0, (150.0, 200.0), sh.callout(dia=0.315, thru=True))
        sh.notes((20.0, 250.0), None, ["DIMENSIONS APPLY AFTER ANODIZING."], h=2.5, width_mm=110.0)
        self.assertEqual(self.kinds(sh), set(), sh.lint())
        sh.save(self.dir / "clean.dxf")
        report = sh.standard_report()
        self.assertEqual(report["sheet_scale"], "1:1")
        self.assertEqual(report["weight"], "0.068 lb")

    def test_notes_go_on_sheet_one_only(self):
        sh = self.std("cont", sheet="2 OF 2")
        with self.assertRaises(SH.DrawingError):
            sh.notes((20.0, 250.0), None, ["DIMENSIONS APPLY AFTER ANODIZING."], h=2.5, width_mm=110.0)

    def test_notes_may_not_repeat_the_title_block_a_thread_or_a_sheet_index(self):
        sh = self.std()
        sh.notes((20.0, 250.0), None, ["MATERIAL: 6061-T6 ALUMINUM.", "REMOVE ALL BURRS.",
                                       "6X 1/4-28 UNF-2B THRU, THREADS RIGHT HAND.", "SEE SHEET 2 FOR THE POCKETS.",
                                       "DO NOT SCALE DRAWING."], h=2.5, width_mm=110.0)
        found = [c for c in sh.lint() if c["kind"] in SH.STANDARD_KINDS]
        self.assertEqual(sum(c["kind"] == "note-title-block" for c in found), 3, found)
        self.assertEqual({c["kind"] for c in found},
                         {"note-title-block", "note-thread", "note-sheet-reference", "right-hand"})
        self.assertTrue(all(c["rule"] in (1, 3) for c in found))
        with self.assertRaises(SH.DrawingError):
            sh.save(self.dir / "notes.dxf")

    def test_loose_text_and_free_labels_are_refused(self):
        sh = self.std()
        sh.text((50.0, 100.0), "END DETAILS - BOTH ENDS IDENTICAL", h=3.0)
        self.assertIn("loose-text", self.kinds(sh))
        with self.assertRaises(SH.DrawingError):
            sh.label((50.0, 80.0), ["TOP VIEW", "SCALE 1:1"])

    def test_view_label_is_the_name_and_the_scale_only_when_it_differs(self):
        sh = self.std(scale="2:1")
        pt = sh.place(self.top, (40.0, 150.0), 2.0, "TOP")
        sh.view_label(pt, (80.0, 140.0), "TOP VIEW")
        written = [m.plain_text() for m in sh.msp.query("MTEXT")]
        self.assertIn("TOP VIEW", written)
        self.assertFalse([s for s in written if s.startswith("SCALE")], "a view at the sheet scale prints none")
        pi = sh.place(self.top, (160.0, 100.0), 1.0, "ISO", scale_reason="does not fit beside the title block at 2:1")
        sh.view_label(pi, (180.0, 95.0), "ISOMETRIC")
        self.assertIn("SCALE 1:1", [m.plain_text() for m in sh.msp.query("MTEXT")])
        self.assertEqual(self.kinds(sh), set(), sh.lint())
        for name in ("TOP VIEW - ONE POCKET FACING VIEWER", "Top view", "SECTION THROUGH THE CENTRAL AXIS"):
            with self.assertRaises(SH.DrawingError):
                sh.view_label(pt, (80.0, 120.0), name)

    def test_one_scale_from_the_standard_series(self):
        sh = self.std()
        with self.assertRaises(SH.DrawingError):
            sh.place(self.top, (100.0, 150.0), 1.7, "TOP")                 # 17:10
        self.assertIn("scale", self.kinds(self.std(scale="AS SHOWN")))
        sh = self.std(scale="2:1")
        sh.place(self.top, (40.0, 150.0), 2.0, "TOP")
        sh.place(self.top, (160.0, 100.0), 1.0, "SIDE")                    # off the sheet scale, no reason given
        found = self.kinds(sh)
        self.assertIn("scale", found)
        self.assertIn("view-label", found)

    def test_a_section_needs_its_cutting_plane_line(self):
        sh = self.std()
        with self.assertRaises(SH.DrawingError):
            sh.place(self.sec, (100.0, 100.0), 1.0, "A-A")                 # a section without its letter
        ps = sh.place(self.sec, (100.0, 100.0), 1.0, "A-A", letter="A")
        self.assertIn("view-label", self.kinds(sh))
        sh.view_label(ps, (120.0, 95.0))
        self.assertIn("SECTION A-A", [m.plain_text() for m in sh.msp.query("MTEXT")])
        self.assertEqual(self.kinds(sh), {"section-line"})
        with self.assertRaises(SH.DrawingError):
            sh.save(self.dir / "section.dxf")
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        sh.cutting_plane(pt, (-5.0, 15.0), (45.0, 15.0), "A", toward=(0.0, 1.0))
        self.assertEqual(self.kinds(sh), set(), sh.lint())
        lone = self.std()
        pt = lone.place(self.top, (100.0, 150.0), 1.0, "TOP")
        lone.cutting_plane(pt, (-5.0, 15.0), (45.0, 15.0), "B", toward=(0.0, 1.0))
        self.assertEqual(self.kinds(lone), {"section-line"}, "a cutting plane without its section view")

    def test_a_detail_needs_its_circle_on_the_parent_view(self):
        sh = self.std()
        pt = sh.place(self.top, (40.0, 150.0), 1.0, "TOP")
        pd = sh.place(self.top, (150.0 - 12.0 * 4.0, 150.0 - 15.0 * 4.0), 4.0, "hole", clip=((12.0, 15.0), 6.0),
                      letter="B")                                          # a detail may be larger: no reason needed
        sh.view_label(pd, (150.0, 120.0))
        written = [m.plain_text() for m in sh.msp.query("MTEXT")]
        self.assertIn("DETAIL B", written)
        self.assertIn("SCALE 4:1", written)
        self.assertEqual(self.kinds(sh), {"detail-circle"})
        sh.detail_circle(pt, (12.0, 15.0), 6.0, "B", (62.0, 174.0))
        self.assertEqual(self.kinds(sh), set(), sh.lint())

    def test_weight_is_stated_in_the_sheets_units_without_ref(self):
        self.assertIn("weight", self.kinds(self.std(weight=False)))
        sh = self.std()
        self.assertEqual(sh._field_text("WEIGHT"), "0.068 lb")
        self.assertNotIn("weight", self.kinds(sh))
        for bad in ("0.068 lb REF", "31 g", "0.07 lb"):
            sh.fill({"WEIGHT": bad})
            self.assertIn("weight", self.kinds(sh), bad)
        mm = self.std("mm")
        self.assertEqual(mm._field_text("WEIGHT"), "31 g")
        self.assertNotIn("weight", self.kinds(mm))
        mm.fill({"WEIGHT": "0.031 kg"})                                    # under 0.100 kg reads in grams
        self.assertIn("weight", self.kinds(mm))
        self.assertEqual(SH.weight_text(250.0, "mm"), "0.250 kg")
        self.assertEqual(SH.weight_text(4.2, "mm"), "4.2 g")
        self.assertEqual(SH.weight_text(453.59237, "in"), "1.000 lb")

    def test_title_block_revision_table_and_frame_are_kept_clear(self):
        for origin, kind in (((300.0, 40.0), "title-block"), ((300.0, 230.0), "revision-table"),
                             ((400.0, 150.0), "outside-frame")):
            sh = self.std()
            sh.place(self.top, origin, 1.0, "TOP")
            self.assertIn(kind, self.kinds(sh), origin)
        clear = self.std()
        clear.place(self.top, (100.0, 150.0), 1.0, "TOP")
        self.assertEqual(self.kinds(clear), set())

    def test_leaders_cross_neither_leaders_nor_dimension_lines(self):
        sh = self.std()
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        sh.leader((0.0, 0.0), (180.0, 200.0), "ONE", pv=pt)
        self.assertEqual(self.kinds(sh), set())
        sh.leader((40.0, 0.0), (60.0, 200.0), "TWO", pv=pt, side="left")   # crosses the first near (120, 162)
        self.assertEqual(self.kinds(sh), {"leader-leader"})
        sh = self.std()
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        sh.dim_linear(pt, (0.0, 30.0), (40.0, 30.0), base=(0.0, 45.0))     # dimension line at sheet y 195
        sh.leader((20.0, 30.0), (125.0, 215.0), "THREE", pv=pt)
        self.assertEqual(self.kinds(sh), {"leader-dimension"})

    def test_a_leader_over_an_extension_line_needs_a_stated_reason(self):
        sh = self.std()
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        sh.dim_linear(pt, (0.0, 30.0), (40.0, 30.0), base=(0.0, 45.0))     # extension lines at sheet x 100 and 140
        sh.leader((30.0, 30.0), (160.0, 190.0), "FOUR", pv=pt)
        found = [c for c in sh.lint() if c["kind"] in SH.STANDARD_KINDS]
        self.assertEqual([c["kind"] for c in found], ["leader-extension"], found)
        self.assertAlmostEqual(found[0]["at"][0], 140.0, delta=0.05)
        with self.assertRaises(SH.DrawingError):
            sh.allow("leader-leader", found[0]["at"], "leaders may never cross each other")
        with self.assertRaises(SH.DrawingError):
            sh.allow("leader-extension", found[0]["at"], "")
        sh.allow("leader-extension", found[0]["at"], "the callout has no other clear route to this edge")
        self.assertEqual(self.kinds(sh), set())
        self.assertEqual(len(sh.standard_report()["waivers"]), 1)
        sh.allow("leader-extension", (30.0, 30.0), "a waiver that waives nothing at all")
        self.assertEqual(self.kinds(sh), {"unused-waiver"})

    def test_a_leader_to_a_hole_is_radial_and_the_hole_has_its_centre_mark(self):
        sh = self.std()
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        sh.leader((16.0, 15.0), (150.0, 200.0), "Ø.315 THRU", pv=pt)       # to the hole's right edge, askew
        self.assertEqual(self.kinds(sh), {"leader-not-radial", "hole-no-centre-mark"})
        sh = self.std()
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        sh.hole_callout(pt, (12.0, 15.0), 4.0, (150.0, 200.0), sh.callout(dia=0.315, thru=True))
        self.assertEqual(self.kinds(sh), set(), sh.lint())
        leader = sh.msp.query("LEADER")[0]
        tip, elbow = [tuple(v)[:2] for v in leader.vertices][:2]
        centre = (112.0, 165.0)
        self.assertAlmostEqual(math.hypot(tip[0] - centre[0], tip[1] - centre[1]), 4.0, places=6)
        cross = (tip[0] - centre[0]) * (elbow[1] - centre[1]) - (tip[1] - centre[1]) * (elbow[0] - centre[0])
        self.assertAlmostEqual(cross, 0.0, places=6)                       # centre, tip and elbow in one line
        self.assertEqual(len(sh._centre_dirs(centre)), 2)
        with self.assertRaises(SH.DrawingError):
            sh.hole_callout(pt, (20.0, 15.0), 4.0, (150.0, 200.0), ["Ø.315 THRU"])   # no hole there

    def test_a_hole_is_dimensioned_to_its_centre(self):
        sh = self.std()
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        sh.dim_linear(pt, (0.0, 30.0), (12.0, 15.0), base=(0.0, 40.0), expect=".472")     # edge to the hole centre
        self.assertTrue(any(c.get("on") == "centre of a circle or arc" for c in sh.checks))
        with self.assertRaises(SH.DrawingError):
            sh.dim_linear(pt, (0.0, 30.0), (13.0, 15.0), base=(0.0, 46.0))                # beside the centre: on nothing

    def test_callouts_are_complete_and_use_the_symbols(self):
        sh = self.std()
        self.assertEqual(sh.callout(qty=3, thread="1/4-20 UNC-2B", depth=0.5, depth_qual="MIN"),
                         ["3X 1/4-20 UNC-2B {depth}.500 MIN"])
        self.assertEqual(sh.callout(qty=3, dia=0.286, thru=True, cbore=(0.469, 0.143, "+.005/-0")),
                         ["3X Ø.286 THRU", "{cbore} Ø.469 +.005/-0 {depth}.143"])
        self.assertEqual(sh.callout(thread="7/8-14 UNF-3A"), ["7/8-14 UNF-3A"])       # external: no depth
        self.assertEqual(sh.callout(dia=0.25, thru=True, csink=(0.5, 82)), ["Ø.250 THRU", "{csink} Ø.500 × 82°"])
        self.assertEqual(self.std("mm").callout(thread="M6x1-6H", depth=12.5), ["M6x1-6H {depth}12.5"])
        for bad in ({"thread": "1/4-20"}, {"thread": "1/4-20 UNC-2B"}, {"thread": "1/4-20 UNC-2B RIGHT HAND", "thru": True},
                    {"dia": 0.25}, {"dia": 0.25, "thru": True, "depth": 0.5}, {}):
            with self.assertRaises(SH.DrawingError, msg=str(bad)):
                sh.callout(**bad)
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        before = len(sh.msp.query("LINE"))
        sh.hole_callout(pt, (12.0, 15.0), 4.0, (150.0, 200.0),
                        sh.callout(dia=0.315, thru=True, cbore=(0.469, 0.143)))
        self.assertGreaterEqual(len(sh.msp.query("LINE")) - before, 2 + 3 + 2)   # centre mark, cbore, depth
        self.assertFalse([m.plain_text() for m in sh.msp.query("MTEXT") if "{" in m.plain_text()])
        self.assertEqual(sh.missing_glyphs(), [])
        self.assertEqual(self.kinds(sh), set(), sh.lint())
        sh.save(self.dir / "callout.dxf")
        sh.render(self.dir / "callout.pdf", self.dir / "callout.png", dpi=150)
        self.assertFalse(sh.issues, sh.issues)

    def test_save_refuses_findings_and_the_legacy_switch_turns_the_standard_off(self):
        sh = self.std(weight=False)
        with self.assertRaises(SH.DrawingError) as caught:
            sh.save(self.dir / "refused.dxf")
        self.assertIn("drawing standard", str(caught.exception))
        self.assertIn("standard=False", str(caught.exception))
        old = self.std("cont", scale="AS SHOWN", weight=False, standard=False)
        ps = old.place(self.sec, (100.0, 100.0), 1.7, "A-A")
        old.label((120.0, 95.0), ["LONGITUDINAL SECTION A-A", "SCALE 17:10"])
        old.text((50.0, 240.0), "END DETAILS - BOTH ENDS IDENTICAL", h=3.0)
        old.notes((20.0, 220.0), None, ["6X 1/4-28 UNF-2B THRU TO BORE."], h=2.5, width_mm=110.0)
        self.assertEqual(self.kinds(old), set())
        old.save(self.dir / "legacy.dxf")
        self.assertIsNone(old.standard_report()["standard"])
        self.assertIsNotNone(ps)
        late = self.std(weight=False)               # opened by a shared helper, then switched off by the script
        late.standard = False
        late.label((120.0, 95.0), ["TOP VIEW - ONE POCKET FACING VIEWER", "SCALE 4:5"])
        late.save(self.dir / "legacy-late.dxf")
        with self.assertRaises(SH.DrawingError) as caught:
            self.std().label((120.0, 95.0), ["TOP VIEW"])
        self.assertIn("sheet.standard = False", str(caught.exception))
        self.assertIn("Engineering Drawing Standard.md", str(caught.exception))

    def test_an_auxiliary_view_needs_its_viewing_arrow(self):
        """A view placed with a letter is an auxiliary view: it is labelled VIEW B (with its
        rotation when turned) and needs view_arrow() with the same letter, and the reverse."""
        sh = self.std()
        pt = sh.place(self.top, (100.0, 150.0), 1.0, "TOP")
        pb = sh.place(self.top, (250.0, 150.0), 1.0, "AUX", letter="B")
        self.assertIn("view-arrow", self.kinds(sh))
        self.assertIn("view-label", self.kinds(sh))
        sh.view_label(pb, (270.0, 120.0), rotated="30° CCW")
        self.assertIn("VIEW B", [m.plain_text() for m in sh.msp.query("MTEXT")])
        sh.view_arrow(pt, (40.0, 15.0), (-1.0, 0.0), "B")
        self.assertEqual(self.kinds(sh), set())
        orphan = self.std()
        orphan.view_arrow(orphan.place(self.top, (100.0, 150.0), 1.0, "TOP"), (40.0, 15.0), (-1.0, 0.0), "C")
        self.assertIn("view-arrow", self.kinds(orphan))

    def test_check_set_pairs_a_section_with_its_cutting_plane_across_sheets(self):
        s1 = self.std(sheet="1 OF 2")
        pt = s1.place(self.top, (100.0, 150.0), 1.0, "TOP")
        s1.cutting_plane(pt, (-5.0, 15.0), (45.0, 15.0), "A", toward=(0.0, 1.0), view_sheet=2)
        s2 = self.std("cont", sheet="2 OF 2")
        ps = s2.place(self.sec, (100.0, 100.0), 1.0, "A-A", letter="A", parent_sheet=1)
        s2.view_label(ps, (120.0, 95.0))
        self.assertIn("SECTION A-A (SHEET 1)", [m.plain_text() for m in s2.msp.query("MTEXT")])
        self.assertEqual(self.kinds(s1) | self.kinds(s2), set())
        self.assertEqual(SH.check_set([s1, s2]), [])
        s3 = self.std("cont", sheet="2 OF 2")
        pb = s3.place(self.sec, (100.0, 100.0), 1.0, "B-B", letter="B", parent_sheet=1)
        s3.view_label(pb, (120.0, 95.0))
        kinds = {c["kind"] for c in SH.check_set([s1, s3])}
        self.assertEqual(kinds, {"section-line"})                          # B has no line on sheet 1; A has no view
        s3.fill({"WEIGHT": "0.070 lb"})
        self.assertIn("set-field", {c["kind"] for c in SH.check_set([s1, s3])})


if __name__ == "__main__":
    unittest.main()
