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
