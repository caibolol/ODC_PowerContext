"""PDF geometry must recover words without losing chart/form text."""

import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document


def _font():
    return DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Courier"),
    })


def _stream(data):
    stream = DecodedStreamObject()
    stream.set_data(data)
    return stream


def _raw(writer):
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_individually_positioned_characters_remain_complete_words():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=400)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font()}),
    })
    # Each BT starts at an absolute glyph position. The trailing TJ displacement
    # is not a word boundary: the next BT resets the text position.
    operators = "/F1 12 Tf " + " ".join(
        f"BT {20 + 7.2 * index} 200 Td [({character}) -50000] TJ ET" for index, character in enumerate("Revenue 123")
    )
    page[NameObject("/Contents")] = writer._add_object(_stream(operators.encode()))
    raw = _raw(writer)
    assert "R e v e n u e" in PdfReader(io.BytesIO(raw)).pages[0].extract_text()
    assert parse_pdf_document(PDFDocumentInput(document_id="positioned-glyphs", content=raw))[0].text == "Revenue 123"


def test_nested_chart_forms_keep_fonts_rotations_and_repeated_labels():
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=600)
    font = _font()
    chart_font = _font()
    chart_font[NameObject("/Encoding")] = DictionaryObject({
        NameObject("/BaseEncoding"): NameObject("/WinAnsiEncoding"),
        NameObject("/Differences"): ArrayObject([NumberObject(82), NameObject("/X")]),
    })
    inner = _stream(b"BT /F1 12 Tf 10 100 Td (Revenue 456) Tj ET BT /F1 12 Tf 0 1 -1 0 0 0 Tm (Axis 789) Tj ET")
    inner.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(n) for n in (0, 0, 150, 150)]),
        NameObject("/Resources"): DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): chart_font}),
        }),
    })
    outer = _stream(b"/Chart Do q 1 0 0 1 200 0 cm /Chart Do Q")
    outer.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(n) for n in (0, 0, 400, 300)]),
        NameObject("/Matrix"): ArrayObject([NumberObject(n) for n in (1, 0, 0, 1, 0, 100)]),
        NameObject("/Resources"): DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Chart"): writer._add_object(inner)}),
        }),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        NameObject("/XObject"): DictionaryObject({NameObject("/Outer"): writer._add_object(outer)}),
    })
    page[NameObject("/Contents")] = writer._add_object(_stream(b"BT /F1 12 Tf 20 500 Td (Revenue 123) Tj ET /Outer Do"))
    text = parse_pdf_document(PDFDocumentInput(document_id="charts", content=_raw(writer)))[0].text
    assert "Revenue 123" in text
    assert text.count("Xevenue 456") == 2
    assert text.count("Axis 789") == 2


@pytest.mark.parametrize("state", [b"q 50 Tc Q", b"q 500 Tz Q", b"/Form Do"])
def test_graphics_scopes_restore_text_spacing(state):
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=600)
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font()})})
    form = _stream(b"50 Tc")
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(n) for n in (0, 0, 100, 100)]),
        NameObject("/Resources"): DictionaryObject(),
    })
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Form"): writer._add_object(form)})
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = writer._add_object(
        _stream(state + b" BT /F1 12 Tf 20 400 Td (Net) Tj 28.8 0 Td (income) Tj ET")
    )
    assert (
        parse_pdf_document(PDFDocumentInput(document_id="restored-spacing", content=_raw(writer)))[0].text
        == "Net income"
    )


def test_top_level_coordinate_transforms_keep_character_positions():
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=600)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font()}),
    })
    operations = b"/F1 12 Tf " + b" ".join(
        b"BT 20 300 Td (" + character.encode() + b") Tj ET 1 0 0 1 7.2 0 cm" for character in "Revenue"
    )
    page[NameObject("/Contents")] = writer._add_object(_stream(operations))
    assert (
        parse_pdf_document(PDFDocumentInput(document_id="transformed-glyphs", content=_raw(writer)))[0].text
        == "Revenue"
    )
