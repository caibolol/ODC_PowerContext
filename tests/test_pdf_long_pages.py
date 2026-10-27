"""Dense PDF pages remain complete through durable Memory and exact citations."""

import asyncio
import hashlib
import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.builtin.artifacts.memory import InvalidMemoryCandidateError, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceObservation,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


class EvidencePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind="source-evidence",
                text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                sources=(source,),
            )
            for source in request.sources
        )


def _dense_report() -> PdfWriter:
    writer = PdfWriter()
    page = writer.add_blank_page(width=900, height=1200)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    lines = [
        "CONSOLIDATED STATEMENTS OF INCOME",
        *[
            f"Business unit {number}: revenue 12345 operating costs 6789 income 5556 assets 9000 liabilities 8000"
            for number in range(150)
        ],
        "Densefinalmarker 999888777",
    ]
    stream = DecodedStreamObject()
    stream.set_data(
        ("BT /F1 5 Tf 7 TL 20 1180 Td " + " T* ".join(f"({line}) Tj" for line in lines) + " ET").encode("ascii")
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    return writer


def test_long_pdf_page_survives_ingestion_restart_and_document_revision(tmp_path):
    async def run():
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        writer = _dense_report()
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'dense-pdf.db'}"))
        expected, citations = {}, []
        scope_id = None
        for revision in ("Original", "Revised"):
            writer.add_metadata({"/Title": revision})
            buffer = io.BytesIO()
            writer.write(buffer)
            raw = buffer.getvalue()
            pages = parse_pdf_document(PDFDocumentInput(document_id="ACME_2022_10K", content=raw))
            assert len(pages) == 1
            page = pages[0]
            assert page.document_sha256 == hashlib.sha256(raw).hexdigest()
            assert len(page.text.encode("utf-8")) > 8192
            assert "Business unit 149:" in page.text and "Densefinalmarker 999888777" in page.text
            source = await registry.resolve(page)
            observation = project_source_for_transport(registry, source)
            expected[source.name] = page
            async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as runtime:
                assert runtime.scopes is not None
                if scope_id is None:
                    scope = await runtime.scopes.create(
                        ScopeDraft(title="Dense reports", summary="Full-page evidence", idempotency_key="dense-pdf")
                    )
                    scope_id = scope.scope_id
                await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
                for _ in range(2):
                    await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope_id, observation=observation))
                memory = runtime.memory.for_scope(scope_id)
                while (await memory.flush()).processed:
                    pass
                records = (await memory.list()).entries
                assert len(records) == len(expected)
                record = next(record for record in records if record.entry.sources[0].source_id == source.name)
                assert record.entry.text == f"{page.document_id}\n{page.text}".strip()
                citations.append(record.citation)

        assert scope_id is not None and len(expected) == 2
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            returned = await search_pdf_pages(memory, "Acme FY2022 densefinalmarker", limit=20)
            assert len(returned) == 2
            for citation in (*citations, *returned):
                record = await memory.get(GetMemoryEntryRequest(citation=citation))
                assert len(record.entry.sources) == 1
                reference = record.entry.sources[0]
                page = expected[reference.source_id]
                assert reference.source_type == "pdf-page"
                assert record.entry.text == f"{page.document_id}\n{page.text}".strip()

            # 普通笔记仍受原有上限约束。完整来源页需要保留更长正文。
            with pytest.raises(InvalidMemoryCandidateError, match="8192"):
                await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text="x" * 8193),)))

        async with open_builtin_contexts(config) as contexts:
            context = await contexts.get(scope_id)
            journal = await context.sources.journal.entries()
            assert len(journal) == 2
            for entry in journal:
                page = expected[entry.source_ref.source_id]
                assert isinstance(entry.source, SourceObservation)
                evidence = entry.source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
                assert isinstance(evidence, dict)
                assert evidence["content"] == f"{page.document_id}\n{page.text}"
                assert evidence["metadata"] == {
                    "document_id": page.document_id,
                    "document_sha256": page.document_sha256,
                    "page_number": 1,
                }
            await context.artifacts.memory.rebuild_projections()

        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            hits = (await memory.search(SearchMemoryRequest(query="Densefinalmarker", mode="fts", limit=20))).hits
            assert len(hits) == 2
            assert {hit.entry_version_id for hit in hits} == {citation.entry_version_id for citation in citations}
            for citation in citations:
                record = await memory.get(GetMemoryEntryRequest(citation=citation))
                page = expected[record.entry.sources[0].source_id]
                assert record.entry.text == f"{page.document_id}\n{page.text}".strip()

    asyncio.run(run())
