"""PDF retrieval regressions through persisted, reopened scoped Memory."""

import asyncio

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
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


def test_pdf_report_identity_vocabulary_and_plural_recall(tmp_path):
    async def run():
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        pages = [
            (
                "ACME_2022_10K",
                1,
                "CONSOLIDATED STATEMENTS OF CASH FLOWS\nPurchases of property plant and equipment 123",
            ),
            ("ACME_2022_10K", 2, "Risk factors. Rare contingencies and lawsuits pending before the courts."),
            ("ACME_2021_10K", 1, "Capital expenditures capex cash flow 2021"),
            (
                "ACME_2022_10K",
                3,
                "CONSOLIDATED STATEMENT OF INCOME\nNet revenue 1000 operating income 200\n" + "123 456 789 " * 100,
            ),
            *[
                (
                    "ACME_2022_10K",
                    n + 100,
                    "Notes and discussion. EBITDA margin income statement operating income depreciation amortization cash flow statement 2022",
                )
                for n in range(30)
            ],
            ("GENERIC_REPORT", 1, "Fictional Holdings capital expenditures purchases of property plant equipment 999"),
            *[("OTHER_2022_10K", n + 1, f"Capital expenditure capex cash flow 2022 item {n}") for n in range(30)],
        ]
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pdf.db'}"))
        async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="Evidence", idempotency_key="pdf"))
            other = await runtime.scopes.create(
                ScopeDraft(title="Private", summary="Other scope", idempotency_key="other")
            )
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            for document, number, text in pages:
                source = await registry.resolve(
                    PDFPageInput(document_id=document, document_sha256="a" * 64, page_number=number, text=text)
                )
                await runtime.ingestion.submit(
                    SubmitSourceObservation(
                        scope_id=scope.scope_id, observation=project_source_for_transport(registry, source)
                    )
                )
            memory = runtime.memory.for_scope(scope.scope_id)
            while (await memory.flush()).processed:
                pass
            await memory.remember(
                RememberMemoryRequest(
                    entries=(MemoryEntryInput(kind="note", text="FICTIONAL_2022_10K\nCapital expenditures 123"),)
                )
            )
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            citations = await search_pdf_pages(memory, "What is FY2022 capex for Acme?", limit=1)
            assert len(citations) == 1
            entry = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
            assert entry.text.startswith("ACME_2022_10K\n")
            assert "Purchases of property" in entry.text
            citations = await search_pdf_pages(
                memory,
                "Please find supporting evidence useful to investors evaluating uncertain exposures affecting future performance through difficult economic conditions especially contingencies",
                limit=1,
            )
            assert len(citations) == 1
            entry = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
            assert "Rare contingencies" in entry.text
            assert not await search_pdf_pages(runtime.memory.for_scope(other.scope_id), "Acme capex")
            citations = await search_pdf_pages(memory, "What is FY2022 capex for Fictional?", limit=1)
            assert len(citations) == 1
            entry = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
            assert entry.text.startswith("GENERIC_REPORT\n")
            citations = await search_pdf_pages(
                memory,
                "What is FY2022 EBITDA margin for Acme using the income statement and cash flow statement?",
                limit=20,
            )
            texts = [(await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text for citation in citations]
            assert any("CONSOLIDATED STATEMENT OF INCOME" in text for text in texts)
            assert any("CONSOLIDATED STATEMENTS OF CASH FLOWS" in text for text in texts)

    asyncio.run(run())


@pytest.mark.parametrize("document_id", ["", " ", "\t\n"])
def test_pdf_page_rejects_blank_document_id(document_id):
    with pytest.raises(ValueError):
        PDFPageInput(document_id=document_id, document_sha256="a" * 64, page_number=1, text="")
