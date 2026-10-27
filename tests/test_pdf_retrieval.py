"""PDF retrieval regressions through persisted, reopened scoped Memory."""

import asyncio
import io

import pytest
from pypdf import PdfWriter

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
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
            (
                "3M_2022_10K",
                1,
                "CONSOLIDATED STATEMENTS OF CASH FLOWS\nCapital expenditures USD 3 million 999",
            ),
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
                memory, "What are Acme's FY2022 capital expenditures, in USD 3 million?", limit=1
            )
            entry = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
            assert entry.text.startswith("ACME_2022_10K\n")
            citations = await search_pdf_pages(
                memory,
                "Please find supporting evidence useful to investors evaluating uncertain exposures affecting future performance through difficult economic conditions especially contingencies",
                limit=1,
            )
            assert len(citations) == 1
            entry = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
            assert "Rare contingencies" in entry.text
            assert not await search_pdf_pages(runtime.memory.for_scope(other.scope_id), "Acme capex")
            assert not await search_pdf_pages(memory, "Acme capex", limit=0)
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


def test_calculated_metrics_retrieve_the_underlying_statements(tmp_path):
    async def run():
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        texts = [
            "CONSOLIDATED STATEMENTS\nOF INCOME\nNet sales 123 cost of sales 45 net earnings 67",
            "CONSOLIDATED BALANCE\nSHEETS\nCurrent assets 456 inventories 78 receivables 12 liabilities 34",
            "CONSOLIDATED STATEMENTS OF CASH FLOWS\nCash dividends paid 56 payments to acquire machinery 99 D&A 20",
            *[
                f"Management discussion {number}. Our current ratio, quick ratio, return on assets, dividend "
                "payout ratio, inventory turnover and days to collect receivables were satisfactory."
                for number in range(40)
            ],
        ]
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'metrics.db'}"))
        async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="Metrics", summary="Reports", idempotency_key="metrics")
            )
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            for number, text in enumerate(texts, 1):
                source = await registry.resolve(
                    PDFPageInput(document_id="ACME_2022_10K", document_sha256="a" * 64, page_number=number, text=text)
                )
                await runtime.ingestion.submit(
                    SubmitSourceObservation(
                        scope_id=scope.scope_id, observation=project_source_for_transport(registry, source)
                    )
                )
            memory = runtime.memory.for_scope(scope.scope_id)
            while (await memory.flush()).processed:
                pass
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            for question, required in (
                ("What is Acme's FY2022 current ratio?", (1,)),
                ("What is Acme's FY2022 quick ratio?", (1,)),
                ("What is Acme's FY2022 return on assets?", (0, 1)),
                ("What is Acme's FY2022 inventory turnover?", (0, 1)),
                ("What is Acme's FY2022 dividend payout ratio?", (0, 2)),
                ("How many days does Acme take to collect receivables in FY2022?", (0, 1)),
                ("What is Acme's FY2022 net income?", (0,)),
                ("What are Acme's FY2022 capital expenditures?", (2,)),
                ("What is Acme's FY2022 depreciation?", (2,)),
                ("How much did Acme earn in FY2022?", (0,)),
                ("What was Acme's FY2022 cash generated from operations?", (2,)),
            ):
                citations = await search_pdf_pages(memory, question, limit=20)
                returned = {
                    (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text for citation in citations
                }
                assert len(citations) == len(returned) == 20
                assert all(f"ACME_2022_10K\n{texts[index]}" in returned for index in required), question

    asyncio.run(run())


def test_primary_statement_titles_fall_back_per_document_and_keep_year_priority(tmp_path):
    async def run():
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        pages = []
        for document, titles in (
            (
                "ACME_2022_10K",
                (
                    "CONSOLIDATED STATEMENTS\nOF INCOME",
                    "CONDENSED CONSOLIDATED BALANCE\nSHEETS",
                    "COMBINED STATEMENTS OF CASH FLOWS",
                ),
            ),
            (
                "BETA_2022_10K",
                ("INCOME STATEMENTS", "BALANCE SHEETS", "CASH FLOWS STATEMENTS"),
            ),
            (
                "ACME_2021_10K",
                (
                    "CONSOLIDATED STATEMENTS OF INCOME",
                    "CONSOLIDATED BALANCE SHEETS",
                    "CONSOLIDATED STATEMENTS OF CASH FLOWS",
                ),
            ),
        ):
            pages.extend(
                (document, number, f"{title}\nNet income 100 assets 200 debt 50 cash from operations 75")
                for number, title in enumerate(titles, 1)
            )
            pages.extend(
                (
                    document,
                    number,
                    ("Balance Sheet\n" if document == "ACME_2022_10K" else "Notes and discussion\n")
                    + ("Net debt effective tax rate and financial performance " * 20).rstrip(),
                )
                for number in range(10, 50)
            )
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'titles.db'}"))
        source_pages = {}
        async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(ScopeDraft(title="Titles", summary="Reports", idempotency_key="titles"))
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            for document, number, text in pages:
                source = await registry.resolve(
                    PDFPageInput(document_id=document, document_sha256="a" * 64, page_number=number, text=text)
                )
                source_pages[source.name] = (document, number, text)
                await runtime.ingestion.submit(
                    SubmitSourceObservation(
                        scope_id=scope.scope_id, observation=project_source_for_transport(registry, source)
                    )
                )
            memory = runtime.memory.for_scope(scope.scope_id)
            while (await memory.flush()).processed:
                pass
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)

            async def locations(question, limit=20):
                citations = await search_pdf_pages(memory, question, limit=limit)
                found = []
                for citation in citations:
                    entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                    document, number, text = source_pages[entry.sources[0].source_id]
                    assert entry.text == f"{document}\n{text}"
                    found.append((document, number))
                assert len(citations) == len(set(found)) == limit
                return found

            for company, document in (("Acme", "ACME_2022_10K"), ("Beta", "BETA_2022_10K")):
                for limit in (1, 3, 20):
                    found = await locations(f"What is {company}'s FY2022 net debt?", limit)
                    assert found[0] == (document, 2)
                    assert all(doc == document for doc, _ in found)
                found = await locations(f"What was {company}'s FY2022 effective tax rate?")
                assert set(found[:3]) == {(document, number) for number in (1, 2, 3)}
                assert all(doc == document for doc, _ in found)
            found = await locations("What is Acme and Beta's FY2022 net debt?")
            assert set(found[:6]) == {
                (document, number) for document in ("ACME_2022_10K", "BETA_2022_10K") for number in (1, 2, 3)
            }
            assert all(document.endswith("2022_10K") for document, _ in found)

    asyncio.run(run())


def test_pdf_revisions_keep_exact_citations_after_restart(tmp_path):
    async def run():
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=200)
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'revisions.db'}"))
        scope_id, records, source_ids = None, [], []
        for title in ("Original", "Revised"):
            writer.add_metadata({"/Title": title})
            buffer = io.BytesIO()
            writer.write(buffer)
            page = parse_pdf_document(PDFDocumentInput(document_id="ACME_2022_10K", content=buffer.getvalue()))[0]
            source = await registry.resolve(page)
            source_ids.append(source.name)
            observation = project_source_for_transport(registry, source)
            async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as runtime:
                assert runtime.scopes is not None
                if scope_id is None:
                    scope = await runtime.scopes.create(
                        ScopeDraft(title="Revisions", summary="PDF revisions", idempotency_key="revisions")
                    )
                    scope_id = scope.scope_id
                await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
                for _ in range(2):
                    await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope_id, observation=observation))
                memory = runtime.memory.for_scope(scope_id)
                while (await memory.flush()).processed:
                    pass
                entries = (await memory.list()).entries
                assert len(entries) == len(records) + 1
                record = next(record for record in entries if record.entry.sources[0].source_id == source.name)
                records.append(record)
        assert scope_id is not None and source_ids[0] != source_ids[1]
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            for record, source_id in zip(records, source_ids, strict=True):
                restored = await memory.get(GetMemoryEntryRequest(citation=record.citation))
                assert restored == record and restored.entry.sources[0].source_id == source_id
        async with open_builtin_contexts(config) as contexts:
            journal = await (await contexts.get(scope_id)).sources.journal.entries()
            assert len(journal) == 2
            assert {entry.source_ref.source_id for entry in journal} == set(source_ids)

    asyncio.run(run())


def test_synonyms_short_fiscal_year_and_phrase_ranking(tmp_path):
    async def run():
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        pages = [
            ("ACME_2021_10K", "Legal contingencies lawsuit 2021"),
            ("ACME_2022_10K", "Pending legal contingencies 2022"),
            ("ACME_2022_10K", "Diluted earnings per share 4.20"),
            ("ACME_2022_10K", "Our supply chain disruptions affected shipments"),
            ("ACME_2022_10K", "Our supply increased; the retail chain grew; disruptions were minor"),
            ("ACME_2022_10K", "Inventories 123"),
            ("3M_2022_10K", "Diluted earnings per share 9.99"),
        ]
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'synonyms.db'}"))
        async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="Synonyms", summary="Reports", idempotency_key="synonyms")
            )
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            for number, (document, text) in enumerate(pages, 1):
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
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            for question, expected in (
                ("Acme FY22 lawsuit?", pages[1]),
                ("Acme FY22 diluted EPS?", pages[2]),
                ("Acme FY22 supply chain disruptions?", pages[3]),
                ("Acme FY22 inventory?", pages[5]),
                ("3M FY22 diluted EPS?", pages[6]),
            ):
                citations = await search_pdf_pages(memory, question, limit=1)
                assert len(citations) == 1
                entry = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
                assert entry.text == "\n".join(expected), question

    asyncio.run(run())


async def _persist_pdf_pages(tmp_path, pages):
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'statements.db'}"))
    locations = {}
    async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Reports", summary="Evidence", idempotency_key="statements")
        )
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for document, number, text in pages:
            source = await registry.resolve(
                PDFPageInput(document_id=document, document_sha256="a" * 64, page_number=number, text=text)
            )
            locations[source.name] = (document, number)
            await runtime.ingestion.submit(
                SubmitSourceObservation(
                    scope_id=scope.scope_id, observation=project_source_for_transport(registry, source)
                )
            )
        while (await runtime.memory.for_scope(scope.scope_id).flush()).processed:
            pass
    return config, scope.scope_id, locations


@pytest.mark.parametrize(
    ("document", "heading"),
    [
        ("ACME_2022_10K", "Consolidated Statements of Cash Flows Acme Incorporated and Subsidiary Companies"),
        ("ACME_2022_10K", "Consolidated Statements of Cash Flows (Dollars in millions)"),
        ("ACME_2022_10K", "Consolidated Statements of Cash Flows for the years ended December 31, 2022 and 2021"),
        ("ACME_2022_10K", "Consolidated\nStatements of\nCash Flows"),
        ("ANNUAL_REPORT", "Consolidated Statements of Cash Flows (Dollars in millions)"),
    ],
)
def test_statement_titles_survive_layout_suffixes_and_unnamed_reports(tmp_path, document, heading):
    async def run():
        table = (
            heading
            + "\nNet income 150\nDepreciation and amortization 50\nPurchases of property and equipment 100\n"
            + "Receipts 10 proceeds 30 adjustments 40 reconciliation 50\n" * 70
        )
        discussion = (
            "The consolidated statements of cash flows describe net income, depreciation and amortization, "
            "purchases of property and equipment. Unadjusted EBITDA less capex equals operating income plus "
            "depreciation and amortization less capital expenditure. We reconcile EBITDA margin and cash flow "
            "to income from operations and cash flows from investing and operating activities. "
        )
        pages = [
            (document, 1, "Index to Financial Statements\nConsolidated Statements of Cash Flows 2\nNotes 3"),
            (document, 2, table),
            *[(document, number + 3, f"Note {number}: Non-GAAP measures. " + discussion * 3) for number in range(30)],
        ]
        config, scope_id, locations = await _persist_pdf_pages(tmp_path, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            question = "What is Acme's FY2022 unadjusted EBITDA less capex?"
            for limit in (1, 20):
                citations = await search_pdf_pages(memory, question, limit=limit)
                found = []
                for citation in citations:
                    record = await memory.get(GetMemoryEntryRequest(citation=citation))
                    found.append(locations[record.entry.sources[0].source_id])
                assert len(found) == len(set(found)) == limit
                assert found[0] == (document, 2)

    asyncio.run(run())


def test_report_declared_name_and_stock_symbol_select_the_report(tmp_path):
    async def run():
        pages = [
            (
                "ACMEWATERWORKS_2022_10K",
                1,
                'Acme Water Works Company, Inc. (the "Company" or "Acme Water") provides water services. '
                'The Company\u2019s  common  stock trades on the stock exchange under\n  the symbol "AQW.".',
            ),
            (
                "ACMEWATERWORKS_2022_10K",
                2,
                "CONSOLIDATED STATEMENTS OF INCOME\nOperating income 100 net revenue 300",
            ),
            (
                "ACMEWATERWORKS_2022_10K",
                3,
                "CONSOLIDATED STATEMENTS OF CASH FLOWS\nDepreciation and amortization 50 capital expenditures 200",
            ),
            *[
                (
                    "OTHER_2022_10K",
                    number + 1,
                    "Unadjusted EBITDA less capex equals operating income plus depreciation and amortization "
                    "less capital expenditures. Cash flows and net revenue 2022.",
                )
                for number in range(30)
            ],
        ]
        config, scope_id, locations = await _persist_pdf_pages(tmp_path, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            for company in ("Acme Water", "AQW"):
                citations = await search_pdf_pages(
                    memory, f"What is {company}'s FY2022 unadjusted EBITDA less capex?", 20
                )
                found = {
                    locations[(await memory.get(GetMemoryEntryRequest(citation=citation))).entry.sources[0].source_id]
                    for citation in citations
                }
                assert {("ACMEWATERWORKS_2022_10K", 2), ("ACMEWATERWORKS_2022_10K", 3)} <= found
                assert all(document == "ACMEWATERWORKS_2022_10K" for document, _ in found)

    asyncio.run(run())
