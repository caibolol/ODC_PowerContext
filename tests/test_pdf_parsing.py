"""Complete-page parsing and revision identity regressions."""

import asyncio
import base64
import hashlib
import io
import zlib

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    IndirectObject,
    NameObject,
    NullObject,
    NumberObject,
)

from powercontext.sources import SourceDefinitionRegistry, SourceMaterialization, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFDocumentInput, parse_pdf_document
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def _writer(*texts):
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    for text in texts:
        page = writer.add_blank_page(width=300, height=400)
        if text:
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            })
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    return writer


def _bytes(writer):
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("chained", [False, True])
@pytest.mark.parametrize("encrypted", [False, True])
def test_text_numbers_blanks_hash_and_revision_identity(chained, encrypted):
    async def run():
        writer = _writer("Revenue 123.45 expense 67", "", "Cash 890 liabilities 12")
        stream = EncodedStreamObject()
        data = zlib.compress(b"BT /F1 12 Tf 20 200 Td (Revenue 123.45 expense 67) Tj ET")
        stream._data = base64.a85encode(data) + b"~>" if chained else data
        stream[NameObject("/Filter")] = (
            ArrayObject([NameObject("/ASCII85Decode"), NameObject("/FlateDecode")])
            if chained
            else NameObject("/FlateDecode")
        )
        if chained:
            stream[NameObject("/DecodeParms")] = ArrayObject([NullObject(), DictionaryObject()])
        writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)
        if encrypted:
            writer.encrypt(user_password="", owner_password="owner")  # noqa: S106
        raw = _bytes(writer)
        document_id = "财报: a/b?年度 " * 100
        pages = parse_pdf_document(PDFDocumentInput(document_id=document_id, content=raw))
        assert [(page.page_number, page.text) for page in pages] == [
            (1, "Revenue 123.45 expense 67"),
            (2, ""),
            (3, "Cash 890 liabilities 12"),
        ]
        assert all(page.document_sha256 == hashlib.sha256(raw).hexdigest() for page in pages)
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        sources = [await registry.resolve(page) for page in pages]
        assert len({source.name for source in sources}) == 3
        for page, source in zip(pages, sources, strict=True):
            assert len(source.name) <= 256 and source.materialization == SourceMaterialization.CAPTURED
            assert await registry.read(source) == page
            assert await registry.resolve(page) == source
            evidence = project_source_for_transport(registry, source).projection(TEXT_EVIDENCE_PROJECTION_KEY)
            assert isinstance(evidence, dict)
            assert evidence["content"] == f"{document_id}\n{page.text}"
            assert evidence["metadata"] == {
                "document_id": document_id,
                "document_sha256": page.document_sha256,
                "page_number": page.page_number,
            }
        writer.add_metadata({"/Title": "Revised report"})
        revised = parse_pdf_document(PDFDocumentInput(document_id=document_id, content=_bytes(writer)))
        assert (await registry.resolve(revised[0])).name != sources[0].name
        assert await registry.read(sources[0]) == pages[0]

    asyncio.run(run())


@pytest.mark.parametrize("corruption", ["missing-object", "invalid-flate", "truncated-flate", "truncated-chain"])
def test_corrupt_later_page_fails_atomically(corruption):
    writer = _writer("Valid first page 123", "Valid second page 456")
    if corruption == "missing-object":
        writer.pages[1][NameObject("/Contents")] = IndirectObject(9999, 0, writer)
    else:
        stream = EncodedStreamObject()
        data = (
            b"not zlib data"
            if corruption == "invalid-flate"
            else zlib.compress(b"BT /F1 12 Tf (Partial second page) Tj ET")[:-4]
        )
        chained = corruption == "truncated-chain"
        stream._data = base64.a85encode(data) + b"~>" if chained else data
        stream[NameObject("/Filter")] = (
            ArrayObject([NameObject("/ASCII85Decode"), NameObject("/FlateDecode")])
            if chained
            else NameObject("/FlateDecode")
        )
        writer.pages[1][NameObject("/Contents")] = writer._add_object(stream)
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="damaged", content=_bytes(writer)))


def test_nonempty_user_password_is_rejected():
    writer = _writer("Restricted 123")
    writer.encrypt(user_password="secret", owner_password="owner")  # noqa: S106
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="restricted", content=_bytes(writer)))


def test_truncated_final_marker_is_not_repaired():
    raw = _bytes(_writer("Complete page 123"))
    pages = parse_pdf_document(PDFDocumentInput(document_id="complete", content=raw.rstrip()))
    assert len(pages) == 1 and pages[0].text == "Complete page 123"
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="truncated", content=raw[:-3]))


@pytest.mark.parametrize("filter_name", ["/ASCII85Decode", "/ASCIIHexDecode", "/RunLengthDecode"])
def test_encoding_end_markers_are_required(filter_name):
    writer = _writer("Intact first page 123", "Second page 456")
    content = b"BT /F1 12 Tf (Second page 456) Tj ET"
    if filter_name == "/ASCII85Decode":
        encoded, ending = base64.a85encode(content), b"~>"
    elif filter_name == "/ASCIIHexDecode":
        encoded, ending = content.hex().encode(), b">"
    else:
        encoded, ending = bytes([len(content) - 1]) + content, b"\x80"
    stream = EncodedStreamObject()
    stream[NameObject("/Filter")] = NameObject(filter_name)
    stream._data = encoded + ending + (b"\x00\r\n " if filter_name == "/ASCII85Decode" else b"")
    writer.pages[1][NameObject("/Contents")] = writer._add_object(stream)
    pages = parse_pdf_document(PDFDocumentInput(document_id="complete", content=_bytes(writer)))
    assert [page.text for page in pages] == ["Intact first page 123", "Second page 456"]
    stream._data = encoded
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="incomplete", content=_bytes(writer)))


@pytest.mark.parametrize("corruption", ["dangling-form", "broken-form", "cyclic-form", "content-array", "no-resources"])
def test_extraction_cannot_silently_skip_corrupt_content(corruption):
    writer = _writer("Intact first page 123", "Second page 456")
    page = writer.pages[1]
    if corruption == "content-array":
        page[NameObject("/Contents")] = ArrayObject([page.raw_get("/Contents"), NumberObject(42)])
    elif corruption == "no-resources":
        page[NameObject("/Resources")] = DictionaryObject()
        stream = EncodedStreamObject()
        stream._data = b"not zlib data"
        stream[NameObject("/Filter")] = NameObject("/FlateDecode")
        page[NameObject("/Contents")] = writer._add_object(stream)
    else:
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf (Second page prefix) Tj ET /X1 Do")
        page[NameObject("/Contents")] = writer._add_object(stream)
        reference = IndirectObject(9999, 0, writer)
        if corruption != "dangling-form":
            form = DecodedStreamObject()
            form.set_data(b"BT /F1 12 Tf (unterminated Tj ET" if corruption == "broken-form" else b"/X1 Do")
            form[NameObject("/Type")] = NameObject("/XObject")
            form[NameObject("/Subtype")] = NameObject("/Form")
            form[NameObject("/BBox")] = ArrayObject([NumberObject(0)] * 4)
            form[NameObject("/Resources")] = page["/Resources"]
            reference = writer._add_object(form)
        page["/Resources"][NameObject("/XObject")] = DictionaryObject({NameObject("/X1"): reference})
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="damaged", content=_bytes(writer)))


@pytest.mark.parametrize("encrypted", [False, True])
def test_nested_forms_and_content_arrays_remain_readable(encrypted):
    writer = _writer("First page 123", "")
    resources = writer.pages[0]["/Resources"]
    inner = DecodedStreamObject()
    inner.set_data(b"BT /F1 12 Tf (Nested revenue 456) Tj ET")
    inner[NameObject("/Type")] = NameObject("/XObject")
    inner[NameObject("/Subtype")] = NameObject("/Form")
    inner[NameObject("/BBox")] = ArrayObject([NumberObject(0), NumberObject(0), NumberObject(100), NumberObject(100)])
    inner[NameObject("/Resources")] = resources
    outer = DecodedStreamObject()
    outer.set_data(b"/Inner Do")
    outer.update(inner)
    outer[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Inner"): writer._add_object(inner)}),
    })
    page = writer.pages[1]
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Outer"): writer._add_object(outer)}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"/Outer Do")
    page[NameObject("/Contents")] = ArrayObject([NullObject(), writer._add_object(stream)])
    if encrypted:
        writer.encrypt(user_password="", owner_password="owner")  # noqa: S106
    pages = parse_pdf_document(PDFDocumentInput(document_id="nested", content=_bytes(writer)))
    assert [page.text.strip() for page in pages] == ["First page 123", "Nested revenue 456"]


@pytest.mark.parametrize("font_resource", ["no-resources", "no-fonts", "missing-name", "null-font"])
def test_missing_font_resources_cannot_become_empty_or_replacement_text(font_resource):
    writer = _writer("Intact first page 123", "Revenue 456")
    page = writer.pages[1]
    if font_resource == "no-resources":
        page[NameObject("/Resources")] = DictionaryObject()
    elif font_resource == "no-fonts":
        del page["/Resources"]["/Font"]
    elif font_resource == "missing-name":
        page["/Resources"]["/Font"][NameObject("/F2")] = page["/Resources"]["/Font"].pop("/F1")
    else:
        page["/Resources"]["/Font"][NameObject("/F1")] = NullObject()
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="damaged-font", content=_bytes(writer)))


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("context", ["page", "shared-pages", "shared-nested"])
def test_forms_inherit_each_callers_resources(context, encrypted):
    writer = _writer("Revenue 123", "")
    first_resources = writer.pages[0]["/Resources"]
    second_font = DictionaryObject(first_resources["/Font"]["/F1"])
    second_font[NameObject("/Encoding")] = DictionaryObject({
        NameObject("/BaseEncoding"): NameObject("/WinAnsiEncoding"),
        NameObject("/Differences"): ArrayObject([NumberObject(82), NameObject("/X")]),
    })
    second_resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): second_font}),
    })
    form = DecodedStreamObject()
    form.set_data(b"BT /F1 12 Tf (Revenue 123) Tj ET")
    form[NameObject("/Type")] = NameObject("/XObject")
    form[NameObject("/Subtype")] = NameObject("/Form")
    form[NameObject("/BBox")] = ArrayObject([NumberObject(0), NumberObject(0), NumberObject(100), NumberObject(100)])
    shared = writer._add_object(form)
    stream = DecodedStreamObject()
    stream.set_data(b"/Shared Do")
    for resources in (first_resources, second_resources):
        resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Shared"): shared})
    if context == "shared-nested":
        callers = DictionaryObject()
        for name, resources in (("/First", first_resources), ("/Second", second_resources)):
            caller = DecodedStreamObject()
            caller.update(form)
            caller.set_data(b"/Shared Do")
            caller[NameObject("/Resources")] = resources
            callers[NameObject(name)] = writer._add_object(caller)
        writer.pages[1][NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): callers})
        stream.set_data(b"/First Do /Second Do /First Do")
    else:
        writer.pages[1][NameObject("/Resources")] = second_resources if context == "shared-pages" else first_resources
        if context == "shared-pages":
            writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)
    writer.pages[1][NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt(user_password="", owner_password="owner")  # noqa: S106
    raw = _bytes(writer)
    pages = parse_pdf_document(PDFDocumentInput(document_id="inherited-form", content=raw))
    expected = ["Revenue 123", "Revenue 123"]
    if context == "shared-pages":
        expected[1] = "Xevenue 123"
    elif context == "shared-nested":
        expected[1] = "Revenue 123 Xevenue 123 Revenue 123"
    assert [" ".join(page.text.split()) for page in pages] == expected
    assert [page.page_number for page in pages] == [1, 2]
    assert all(page.document_sha256 == hashlib.sha256(raw).hexdigest() for page in pages)
