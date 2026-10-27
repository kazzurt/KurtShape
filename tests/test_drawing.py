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
        return SH.Sheet(self.template, template_map=str(self.map), lang=lang)

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
        sh.text((50.0, 50.0), "HARDENED ≥45 HRC", h=3.0)        # Noto Sans has no '≥'
        self.assertTrue(any(ch == "≥" for ch, _, _ in sh.missing_glyphs()))
        with self.assertRaises(SH.DrawingError):
            sh.save(self.dir / "tofu.dxf")
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


if __name__ == "__main__":
    unittest.main()
