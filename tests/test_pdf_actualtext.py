"""PDF-owned ActualText replaces its marked span without touching shared evidence."""

import hashlib
import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf._font import Font
from pypdf._text_extraction._layout_mode._text_state_params import TextStateParams
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from powercontext.sources.pdf_text import prepare_page_for_extraction


def _font():
    return DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    })


def _document(content, *, properties=None, forms=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font()})})
    if properties:
        resources[NameObject("/Properties")] = properties
    if forms:
        resources[NameObject("/XObject")] = DictionaryObject({
            NameObject(name): writer._add_object(form) for name, form in forms.items()
        })
    page[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    raw = output.getvalue()
    reader = PdfReader(io.BytesIO(raw))
    return reader, reader.pages[0], raw


def _form(content, resources=None):
    form = DecodedStreamObject()
    form.set_data(content)
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(600), NumberObject(800)]),
    })
    if resources is not None:
        form[NameObject("/Resources")] = resources
    return form


def _words(page, mode="plain"):
    return (page.extract_text(extraction_mode=mode) or "").split()


@pytest.mark.parametrize("mode", ["plain", "layout"])
def test_same_glyph_has_independent_replacements_and_original_remains_unchanged(mode):
    reader, page, raw = _document(
        b"BT /F1 12 Tf 20 700 Td "
        b"/Span << /ActualText (financial) >> BDC (X) Tj EMC ( ) Tj "
        b"/Span << /ActualText (profit) >> BDC (X) Tj EMC ( X) Tj ET"
    )
    original_contents = page["/Contents"].get_data()
    original_fonts = tuple(page["/Resources"]["/Font"])
    digest = hashlib.sha256(raw).digest()
    prepared = prepare_page_for_extraction(page, reader)
    assert _words(prepared, mode) == ["financial", "profit", "X"]
    assert page["/Contents"].get_data() == original_contents
    assert tuple(page["/Resources"]["/Font"]) == original_fonts
    assert _words(page) == ["X", "X", "X"]
    assert hashlib.sha256(raw).digest() == digest


@pytest.mark.parametrize("mode", ["plain", "layout"])
def test_outer_span_replaces_nested_text_once_and_empty_span_suppresses_text(mode):
    reader, page, _ = _document(
        b"BT /F1 12 Tf 20 700 Td "
        b"/Span << /ActualText (outer replacement) >> BDC "
        b"(one) Tj /Span << /ActualText (inner) >> BDC [(two) -250 (three)] TJ EMC "
        b"(four) Tj EMC ( tail ) Tj "
        b"/Span << /ActualText () >> BDC (hidden secret) Tj EMC ET"
    )
    prepared = prepare_page_for_extraction(page, reader)
    assert _words(prepared, mode) == ["outer", "replacement", "tail"]


@pytest.mark.parametrize("mode", ["plain", "layout"])
def test_named_properties_utf16_and_pdfdocencoding(mode):
    properties = DictionaryObject({
        NameObject("/Replacement"): DictionaryObject({NameObject("/ActualText"): TextStringObject("财报 123")})
    })
    reader, page, _ = _document(
        b"BT /F1 12 Tf 20 700 Td /Span /Replacement BDC (X) Tj EMC ( ) Tj "
        b"/Span << /ActualText <FEFF00630061006600E9> >> BDC (Y) Tj EMC ( ) Tj "
        b"/Span << /ActualText (caf\\351) >> BDC (Z) Tj EMC ET",
        properties=properties,
    )
    assert _words(prepare_page_for_extraction(page, reader), mode) == ["财报", "123", "café", "café"]


@pytest.mark.parametrize("mode", ["plain", "layout"])
def test_actualtext_without_text_show_operators_is_not_lost(mode):
    reader, page, _ = _document(
        b"/Span << /ActualText (graphic description) >> BDC 20 700 40 10 re f EMC "
        b"/Span << /ActualText () >> BDC 20 650 40 10 re f EMC"
    )
    assert _words(prepare_page_for_extraction(page, reader), mode) == ["graphic", "description"]


def test_shared_form_inherits_each_calling_span_and_font_without_mutating_form():
    form = _form(b"BT 20 700 Td (X) Tj ET")
    reader, page, _ = _document(
        b"/F1 12 Tf /Span << /ActualText (first) >> BDC /Shared Do EMC "
        b"/Span << /ActualText (second) >> BDC /Shared Do EMC /Shared Do",
        forms={"/Shared": form},
    )
    original = page["/Resources"]["/XObject"]["/Shared"]
    original_data = original.get_data()
    prepared = prepare_page_for_extraction(page, reader)
    assert _words(prepared) == ["first", "second", "X"]
    assert original.get_data() == original_data
    assert "/Resources" not in original


def test_nested_form_can_supply_named_properties_from_its_own_resources():
    inner = _form(
        b"BT /F1 12 Tf 20 700 Td /Span /P BDC (raw) Tj EMC ET",
        DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font()}),
            NameObject("/Properties"): DictionaryObject({
                NameObject("/P"): DictionaryObject({NameObject("/ActualText"): TextStringObject("nested value")})
            }),
        }),
    )
    outer = _form(
        b"/Inner Do", DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Inner"): inner})})
    )
    reader, page, _ = _document(b"/Outer Do", forms={"/Outer": outer})
    assert _words(prepare_page_for_extraction(page, reader)) == ["nested", "value"]


def test_synthetic_glyphs_preserve_character_word_spacing_and_text_advance():
    reader, page, _ = _document(
        b"BT /F1 12 Tf 2 Tc 5 Tw 80 Tz 20 700 Td /Span << /ActualText (replacement) >> BDC (A B) Tj EMC (tail) Tj ET"
    )
    prepared = prepare_page_for_extraction(page, reader)
    original_font = Font.from_font_resource(page["/Resources"]["/Font"]["/F1"])
    expected = TextStateParams(b"A B", original_font, 12, Tc=2, Tw=5, Tz=80).displaced_tx
    operations = ContentStream(prepared["/Contents"], reader, "bytes").operations
    synthetic = next(
        (args[0], operations[index + 1][0][0])
        for index, (args, op) in enumerate(operations)
        if op == b"Tf" and str(args[0]).startswith("/ActualText")
    )
    name, data = synthetic
    resources = prepared["/Resources"]
    assert isinstance(resources, DictionaryObject)
    fonts = resources["/Font"]
    assert isinstance(fonts, DictionaryObject)
    font_resource = fonts[name]
    assert isinstance(font_resource, DictionaryObject)
    font = Font.from_font_resource(font_resource)
    actual = TextStateParams(data, font, 12, Tc=2, Tw=0, Tz=80).displaced_tx
    assert actual == pytest.approx(expected)
    assert _words(prepared) == ["replacementtail"]


@pytest.mark.parametrize("content", [b"EMC", b"/Span << /ActualText (lost) >> BDC"])
def test_unbalanced_marked_content_is_rejected(content):
    reader, page, _ = _document(content)
    with pytest.raises(ValueError, match="marked-content"):
        prepare_page_for_extraction(page, reader)


@pytest.mark.parametrize("mode", ["plain", "layout"])
def test_quote_operators_and_font_changes_do_not_repeat_replacement(mode):
    reader, page, _ = _document(
        b"BT /F1 12 Tf 14 TL 20 700 Td "
        b"/Span << /ActualText (single replacement) >> BDC "
        b"(first) Tj (second) ' 3 1 (third) \" /F1 9 Tf (fourth) Tj EMC "
        b"0 Tw 0 Tc ( tail) Tj ET"
    )
    assert _words(prepare_page_for_extraction(page, reader), mode) == ["single", "replacement", "tail"]


def test_parent_replacement_dominates_actualtext_inside_a_form():
    child = _form(b"BT /F1 12 Tf 20 700 Td /Span << /ActualText (inner) >> BDC (X) Tj EMC ET")
    reader, page, _ = _document(
        b"/Span << /ActualText (outer) >> BDC /Shared Do /Shared Do EMC /Shared Do",
        forms={"/Shared": child},
    )
    assert _words(prepare_page_for_extraction(page, reader)) == ["outer", "inner"]


@pytest.mark.parametrize("mode", ["plain", "layout"])
def test_non_bmp_and_explicit_empty_text_are_preserved(mode):
    properties = DictionaryObject({
        NameObject("/Emoji"): DictionaryObject({NameObject("/ActualText"): TextStringObject("结果😀 456")})
    })
    reader, page, _ = _document(
        b"BT /F1 12 Tf 20 700 Td /Span /Emoji BDC (X) Tj EMC "
        b"/Span << /ActualText () >> BDC /Span << /ActualText (hidden) >> BDC (Y) Tj EMC EMC ET",
        properties=properties,
    )
    assert _words(prepare_page_for_extraction(page, reader), mode) == ["结果😀", "456"]
