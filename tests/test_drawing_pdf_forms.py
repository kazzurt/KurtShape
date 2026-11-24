"""Drawing sign-off values, appearances and independent fields in merged packets."""
from pathlib import Path
import re
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    from kurtshape.drawing.pdf_forms import add_signoff_fields, merge_drawing_pdfs
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


@unittest.skipUnless(PDF_AVAILABLE, "drawing dependency missing; run tools/setup-drawing-deps.ps1")
class SignoffFormTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.scratch(self, "drawing-pdf-forms-")

    def make_pdf(self, name, values=None, field_width=85):
        path = self.folder / name
        writer = PdfWriter()
        page = writer.add_blank_page(width=100 * 72 / 25.4, height=100 * 72 / 25.4)
        content = DecodedStreamObject()
        content.set_data(b"0 0 0 RG 1 w 0 0 m 30 30 l S\n")
        page[NameObject("/Contents")] = writer._add_object(content)
        writer.write(path)
        if values is not None:
            specs = [{"name": key, "rect": [5, 10 + i * 10, 5 + field_width, 18 + i * 10], "value": value}
                     for i, (key, value) in enumerate(values.items())]
            add_signoff_fields(path, specs, [0, 0, 100, 100])
        return path

    def assert_fields(self, path, expected):
        reader = PdfReader(path)
        fields = {name: field for name, field in (reader.get_fields() or {}).items() if field.get("/FT") == "/Tx"}
        self.assertEqual({name: field.get("/V", "") for name, field in fields.items()}, expected)
        seen = set()
        for page in reader.pages:
            for reference in page.get("/Annots", []):
                widget = reference.get_object()
                if widget.get("/Subtype") != "/Widget":
                    continue
                chain, current = [], widget
                while current is not None:
                    chain.append(current)
                    current = current["/Parent"].get_object() if "/Parent" in current else None
                name = ".".join(str(item["/T"]) for item in reversed(chain) if "/T" in item)
                value = next((item["/V"] for item in chain if "/V" in item), "")
                self.assertIn(name, expected)
                self.assertEqual(value, expected[name])
                self.assertNotIn(name, seen)
                seen.add(name)
                self.assertTrue(widget.get("/F", 0) & 4, "field must print")
                self.assertTrue(widget["/AP"]["/N"].get_object().get_data(), "field must have a saved appearance")
        self.assertEqual(seen, set(expected))
        return reader

    def edit(self, source, name, values):
        writer = PdfWriter(clone_from=source)
        writer.update_page_form_field_values(None, values, auto_regenerate=False)
        target = self.folder / name
        writer.write(target)
        return target

    def test_blank_fill_clear_and_reopen_preserve_printable_fields(self):
        blank = self.make_pdf("blank.pdf", {"CHECKED_NAME": "", "CHECKED_DATE": ""})
        self.assert_fields(blank, {"CHECKED_NAME": "", "CHECKED_DATE": ""})
        filled = self.edit(blank, "filled.pdf", {"CHECKED_NAME": "TEST ONLY", "CHECKED_DATE": "2000-01-01"})
        self.assert_fields(filled, {"CHECKED_NAME": "TEST ONLY", "CHECKED_DATE": "2000-01-01"})
        cleared = self.edit(filled, "cleared.pdf", {"CHECKED_NAME": "", "CHECKED_DATE": ""})
        self.assert_fields(cleared, {"CHECKED_NAME": "", "CHECKED_DATE": ""})

    def test_merge_first_sheets_and_continuation_preserves_independent_edits(self):
        first = self.make_pdf("part-a.pdf", {"CHECKED_NAME": "FIRST TEST", "REV_1_APPROVED": "A TEST"})
        continuation = self.make_pdf("part-a-sheet2.pdf")
        second = self.make_pdf("part-b.pdf", {"CHECKED_NAME": "SECOND TEST", "REV_1_APPROVED": "B TEST"})
        originals = {path: path.read_bytes() for path in (first, continuation, second)}
        packet = merge_drawing_pdfs([first, continuation, second], self.folder / "packet.pdf")
        expected = {"drawing_1.CHECKED_NAME": "FIRST TEST", "drawing_1.REV_1_APPROVED": "A TEST",
                    "drawing_3.CHECKED_NAME": "SECOND TEST", "drawing_3.REV_1_APPROVED": "B TEST"}
        self.assertEqual(len(self.assert_fields(packet, expected).pages), 3)
        edited = self.edit(packet, "edited-packet.pdf", {"drawing_3.CHECKED_NAME": "EDITED TEST"})
        expected["drawing_3.CHECKED_NAME"] = "EDITED TEST"
        self.assert_fields(edited, expected)
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_long_names_get_smaller_saved_appearances_in_narrow_cells(self):
        source = self.make_pdf("short-name.pdf", {"CHECKED_NAME": "TEST"}, field_width=24)
        target = self.edit(source, "long-name.pdf", {"CHECKED_NAME": "SECOND TEST REVIEWER"})
        self.assert_fields(target, {"CHECKED_NAME": "SECOND TEST REVIEWER"})
        sizes = []
        for path in (source, target):
            field = PdfReader(path).pages[0]["/Annots"][0].get_object()
            appearance = field["/AP"]["/N"].get_object().get_data()
            sizes.append(float(re.search(rb"/Helv ([\d.]+) Tf", appearance).group(1)))
        self.assertLess(sizes[1], sizes[0])
        self.assertGreaterEqual(sizes[1], 4)
        self.assertLessEqual(sizes[0], 2 * 72 / 25.4 / 0.718 + 0.01)

    def test_repeated_input_and_nested_packet_keep_separate_fields(self):
        source = self.make_pdf("part.pdf", {"CHECKED_NAME": "TEST ONLY"})
        repeated = merge_drawing_pdfs([source, source], self.folder / "repeated.pdf")
        expected = {"drawing_1.CHECKED_NAME": "TEST ONLY", "drawing_2.CHECKED_NAME": "TEST ONLY"}
        self.assert_fields(repeated, expected)
        edited = self.edit(repeated, "edited-repeat.pdf", {"drawing_2.CHECKED_NAME": "SECOND TEST"})
        expected["drawing_2.CHECKED_NAME"] = "SECOND TEST"
        self.assert_fields(edited, expected)
        nested = merge_drawing_pdfs([edited, source], self.folder / "nested.pdf")
        self.assert_fields(nested, {"drawing_1." + name: value for name, value in expected.items()} |
                           {"drawing_2.CHECKED_NAME": "TEST ONLY"})

    def test_merge_rejects_empty_inputs_and_source_overwrite(self):
        source = self.make_pdf("source.pdf", {"CHECKED_NAME": "TEST ONLY"})
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "at least one"):
            merge_drawing_pdfs([], self.folder / "empty.pdf")
        with self.assertRaisesRegex(ValueError, "must not replace"):
            merge_drawing_pdfs([source], source)
        self.assertEqual(source.read_bytes(), before)
        target = self.folder / "existing-packet.pdf"
        target.write_bytes(b"existing output")
        with self.assertRaises(FileNotFoundError):
            merge_drawing_pdfs([source, self.folder / "missing.pdf"], target)
        self.assertEqual(target.read_bytes(), b"existing output")

    def test_sheet_render_keeps_historical_approvals_and_only_forms_pending_rows(self):
        from kurtshape.drawing.sheet import Sheet
        from make_drawing_templates import Template
        dxf, field_map = Template("AH-B-mm-sheet1", "mm", "1").build().save(self.folder)
        sheet = Sheet(dxf, template_map=str(field_map))
        sheet.fill({"SCALE": "1:1", "CHECKED_NAME": "", "CHECKED_DATE": ""})
        sheet.set_weight(1000, 1)
        sheet.revision_row(1, "A", "HISTORICAL TEST", approved="HISTORY TEST", date="2000-01-01")
        sheet.revision_row(2, "B", "PENDING TEST")
        sheet.save(self.folder / "signoff-template.dxf")
        target = self.folder / "signoff-template.pdf"
        sheet.render(target)
        self.assert_fields(target, {"CHECKED_NAME": "", "CHECKED_DATE": "", "REV_2_DATE": "", "REV_2_APPROVED": ""})
        texts = [entity.plain_text() for entity in sheet.msp.query("MTEXT")]
        self.assertIn("HISTORY TEST", texts)
        self.assertIn("2000-01-01", texts)


if __name__ == "__main__":
    unittest.main()
