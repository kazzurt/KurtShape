"""Printable PDF text fields for drawing sign-off cells (paper millimetres).

The drawing stays vector. Fields have both a canonical AcroForm entry and a page
widget, with saved appearance streams, so their values survive ordinary saves
and appear in print. This is typed sign-off, not a cryptographic signature.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

from . import VENDOR_DIRNAME

# Also support the PDF-only merge entry point without importing the CAD renderer.
_VENDOR = Path(__file__).resolve().parents[3] / "runtime" / "vendor" / VENDOR_DIRNAME
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.append(str(_VENDOR))

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject, FloatObject,
    NameObject, NumberObject, TextStringObject,
)

PT_PER_MM = 72.0 / 25.4


def merge_drawing_pdfs(pdf_paths, output_path):
    """Join drawing PDFs while keeping each input's sign-off fields independent.

    Each input with fields is grouped under ``drawing_1``, ``drawing_2``, etc.,
    by its position in the input list. For example, the second input's checked
    name becomes ``drawing_2.CHECKED_NAME``. Existing values and appearances are
    preserved, including when the same PDF is included twice or an input is an
    already-merged packet. Field-free continuation pages need no group.

    Source files are read into memory and never modified; the destination must
    differ from every source. This does not preserve cryptographic signatures.
    """
    sources = [Path(path).resolve() for path in pdf_paths]
    output = Path(output_path).resolve()
    if not sources:
        raise ValueError("at least one drawing PDF is required")
    if output in sources:
        raise ValueError("the merged PDF must not replace a source drawing")
    writer = PdfWriter()
    for index, source in enumerate(sources, 1):
        reader = PdfReader(BytesIO(source.read_bytes()))
        if reader.get_fields():
            reader.add_form_topname(f"drawing_{index}")
        writer.append(reader)
    result = BytesIO()
    writer.write(result)
    output.write_bytes(result.getvalue())
    return output


def add_signoff_fields(pdf_path, specs, sheet_box):
    """Add mapped fields to a fresh, single-sheet drawing PDF.

    ``specs`` contain name, label, rect (paper mm), value, and optional height_mm
    and max_length. Existing AcroForms are refused rather than overwritten.
    """
    if not specs:
        return
    pdf_path = Path(pdf_path)
    reader = PdfReader(BytesIO(pdf_path.read_bytes()))
    if len(reader.pages) != 1 or reader.get_fields():
        raise ValueError("sign-off fields require a fresh single-sheet PDF without form fields")
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    page = writer.pages[0]
    sx, sy, ex, ey = sheet_box
    if abs(float(page.mediabox.width) - (ex - sx) * PT_PER_MM) > 0.05 or abs(
        float(page.mediabox.height) - (ey - sy) * PT_PER_MM
    ) > 0.05:
        raise ValueError("PDF page size does not match the drawing field map")
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    }))
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/Helv"): font})})
    fields = ArrayObject()
    form = DictionaryObject({
        NameObject("/Fields"): fields, NameObject("/DR"): resources,
        NameObject("/DA"): TextStringObject("/Helv 8 Tf 0 g"),
        NameObject("/NeedAppearances"): BooleanObject(False),
    })
    writer._root_object[NameObject("/AcroForm")] = writer._add_object(form)
    annotations = page.get("/Annots", ArrayObject())
    page[NameObject("/Annots")] = annotations
    values, names, masks = {}, set(), []
    for spec in specs:
        name = spec["name"]
        if name in names:
            raise ValueError(f"duplicate sign-off field: {name}")
        names.add(name)
        x0, y0, x1, y1 = spec["rect"]
        if not (sx <= x0 < x1 <= ex and sy <= y0 < y1 <= ey):
            raise ValueError(f"sign-off field outside sheet: {name}")
        rect = [(x0 - sx) * PT_PER_MM, (y0 - sy) * PT_PER_MM,
                (x1 - sx) * PT_PER_MM, (y1 - sy) * PT_PER_MM]
        # Remove the old printed value underneath an editable cell. Clearing or
        # replacing a field must never reveal the old outlined drawing text.
        masks.append(f"{rect[0]:.6f} {rect[1]:.6f} {rect[2]-rect[0]:.6f} {rect[3]-rect[1]:.6f} re f")
        value = str(spec.get("value") or "")
        size = spec.get("height_mm", 2.0) * PT_PER_MM / 0.718
        # Automatic sizing also applies to edits made later in a PDF viewer.
        # Cap its vertical space at Helvetica's full em bounds (-225..931),
        # keeping short names at the requested cap height while long names shrink.
        widget_rect = list(rect)
        widget_height = min(rect[3] - rect[1], size * 1.156)
        widget_rect[1] = (rect[1] + rect[3] - widget_height) / 2
        widget_rect[3] = widget_rect[1] + widget_height
        widget = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject(name),
            NameObject("/TU"): TextStringObject(spec.get("label", name)),
            NameObject("/Rect"): ArrayObject([FloatObject(v) for v in widget_rect]),
            NameObject("/F"): NumberObject(4), NameObject("/Ff"): NumberObject(0),
            NameObject("/Q"): NumberObject(0), NameObject("/P"): page.indirect_reference,
            NameObject("/V"): TextStringObject(value), NameObject("/DV"): TextStringObject(value),
            NameObject("/DA"): TextStringObject("/Helv 0 Tf 0 g"),
            NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
            NameObject("/MaxLen"): NumberObject(spec.get("max_length", 40)),
        })
        reference = writer._add_object(widget)
        fields.append(reference)
        annotations.append(reference)
        values[name] = value
    overlay = DecodedStreamObject()
    overlay.set_data(("q 1 1 1 rg\n" + "\n".join(masks) + "\nQ\n").encode("ascii"))
    contents = page.get("/Contents")
    if isinstance(contents, ArrayObject):
        page[NameObject("/Contents")] = ArrayObject([*contents, writer._add_object(overlay)])
    else:
        page[NameObject("/Contents")] = ArrayObject([contents, writer._add_object(overlay)])
    writer.update_page_form_field_values(None, values, auto_regenerate=False)
    result = BytesIO()
    writer.write(result)
    check = PdfReader(BytesIO(result.getvalue()))
    if set(check.get_fields() or {}) != names:
        raise ValueError("sign-off fields did not serialize correctly")
    for field in check.pages[0].get("/Annots", []):
        field = field.get_object()
        if field.get("/Subtype") == "/Widget" and not field.get("/AP", {}).get("/N"):
            raise ValueError("sign-off field has no printable appearance")
    pdf_path.write_bytes(result.getvalue())
