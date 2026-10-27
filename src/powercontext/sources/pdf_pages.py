"""Complete PDF page evidence with revision identities and lexical retrieval."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zlib
from collections import Counter

from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader, get_configuration
from pypdf.generic import ArrayObject, EncodedStreamObject, NameObject

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class PDFDocumentInput(BaseModel):
    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def require_document_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be blank")  # noqa: TRY003
        return value


class PDFPageInput(BaseModel):
    document_id: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1)
    text: str

    @field_validator("document_id")
    @classmethod
    def require_document_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be blank")  # noqa: TRY003
        return value


def _validate_compressed_streams(reader: PdfReader) -> None:
    # pypdf can silently return partial text from truncated Flate streams.
    for stream in tuple(reader.resolved_objects.values()):
        if not isinstance(stream, EncodedStreamObject):
            continue
        filters = stream["/Filter"]
        if not isinstance(filters, ArrayObject):
            filters = ArrayObject([filters])
        for index, name in enumerate(filters):
            if name not in ("/FlateDecode", "/Fl"):
                continue
            data = stream._data
            if index:
                prefix = EncodedStreamObject()
                prefix.update(stream)
                prefix._data = data
                prefix[NameObject("/Filter")] = ArrayObject(filters[:index])
                data = prefix.get_data()
            decoder = zlib.decompressobj()
            decoder.decompress(data, max_length=get_configuration().zlib_maximum_output_length)
            if not decoder.eof:
                raise ValueError("Incomplete compressed PDF stream")  # noqa: TRY003


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page, returning nothing until extraction succeeds."""
    if (
        not value.document_id.strip()
        or not value.content.startswith(b"%PDF-")
        or not value.content.rstrip().endswith(b"%%EOF")
    ):
        raise ValueError("Expected a named complete PDF document")  # noqa: TRY003
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a user password")  # noqa: TRY003, TRY301
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=number,
                text=page.extract_text() or "",
            )
            for number, page in enumerate(reader.pages, 1)
        )
        _validate_compressed_streams(reader)
    except Exception as error:
        raise ValueError("Unable to extract the complete PDF") from error  # noqa: TRY003
    return pages


class PDFPageSource(Source):
    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSourceAdapter:
    input_class: type[PDFPageInput] = PDFPageInput
    source_class: type[PDFPageSource] = PDFPageSource
    name = "pdf-page"

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = json.dumps([value.document_id, value.document_sha256, value.page_number], ensure_ascii=False)
        return PDFPageSource(
            name="pdf:" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput.model_validate(source.model_dump())


class PDFPageTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[PDFPageSource] = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDFPageSourceAdapter(), projections=(PDFPageTextEvidenceProjection(),)
)

_FUNCTION_WORDS = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "from",
    "with",
    "by",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "what",
    "which",
    "who",
    "how",
    "why",
    "when",
    "where",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "its",
    "it",
    "their",
    "this",
    "that",
    "these",
    "those",
    "company",
    "fiscal",
    "year",
    "years",
    "according",
    "report",
    "reported",
    "annual",
    "much",
    "many",
    "total",
    "amount",
    "percentage",
    "percent",
    "calculate",
    "ratio",
    "change",
    "between",
    "during",
])


# General accounting vocabulary, independent of any report or benchmark question.
_CONCEPTS = (
    (
        r"\b(?:capex|capital expenditure|capital spending)",
        "capital expenditures purchases property plant equipment additions",
    ),
    (r"\b(?:ebitda|d\s*&\s*a|depreciation|amortization)", "operating income depreciation amortization cash flows"),
    (
        r"\b(?:geograph|regions?|countries|operates? in)",
        "geographic segments countries international operations markets",
    ),
    (r"\b(?:legal|litigation|lawsuit)", "legal proceedings litigation contingencies claims"),
    (
        r"\b(?:income statement|p&l|profit|earnings|revenue|margin|ebitda)",
        "consolidated statements income operations earnings revenue net sales",
    ),
    (r"\b(?:cash flow|capex|ebitda|d\s*&\s*a)", "consolidated statements cash flows investing operating activities"),
    (
        r"\b(?:balance sheet|assets?|liabilit|equity|working capital)",
        "consolidated balance sheets financial position assets liabilities equity",
    ),
)

_STATEMENT_HEADINGS = (
    (
        r"\b(?:income statements?|p&l|profit|earnings|revenue|margin|ebitda)\b",
        r"^(?:(?:consolidated|condensed|combined) )*(?:statements? of (?:income|operations|earnings)|income statements?)\b",
    ),
    (
        r"\b(?:cash flows?|capex|ebitda|d\s*&\s*a)\b",
        r"^(?:(?:consolidated|condensed|combined) )*(?:statements? of cash flows?|cash flows? statements?)\b",
    ),
    (
        r"\b(?:balance sheets?|assets?|liabilit\w*|equity|working capital)\b",
        r"^(?:(?:consolidated|condensed|combined) )*(?:balance sheets?|statements? of financial position)\b",
    ),
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+", text.lower())


def _terms(text: str) -> list[str]:
    return [word[:-1] if len(word) > 4 and word.endswith("s") else word for word in _words(text)]


def _document_match(document: str, question: str) -> tuple[int, int]:
    # The projection's first line is the document ID, not body text. Its company
    # and report year constrain relevance even when page text omits the company.
    company = re.split(r"(?:19|20)\d{2}", document.lower(), maxsplit=1)[0]
    company_words = [word for word in _words(company) if word not in {"inc", "corp", "corporation", "the"}]
    compact_company = "".join(company_words)
    company_pattern = r"\b" + r"\s*".join(re.escape(character) for character in compact_company) + r"\b"
    named = bool(compact_company and re.search(company_pattern, " ".join(_words(question))))
    years = set(re.findall(r"(?:19|20)\d{2}", document))
    requested = set(re.findall(r"(?:19|20)\d{2}", question))
    return int(named), int(bool(years & requested))


async def _pdf_candidates(memory, question: str, raw_terms: list[str], expansions: str):
    # Only PDF-backed entries may select a report; notes can contain the same headings.
    pdf_entries = {
        (record.entry.entry_id, record.entry.entry_version_id)
        for record in (await memory.list()).entries
        if any(reference.source_type == "pdf-page" for reference in record.entry.sources)
    }
    if not pdf_entries:
        return {}, set()
    candidates = {}
    # FTS indexes original tokens, not our ranking stems. Keep plural forms and
    # all query terms so long questions do not silently lose their final subject.
    queries = [question, *raw_terms, *dict.fromkeys(_words(expansions))]
    for query in dict.fromkeys(queries):
        result = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=10000))
        for hit in result.hits:
            if (hit.entry_id, hit.entry_version_id) in pdf_entries:
                candidates[(hit.entry_id, hit.entry_version_id)] = hit
    documents = {hit.text.partition("\n")[0] for hit in candidates.values()}
    named_documents = {doc for doc in documents if _document_match(doc, question)[0]}
    # Document IDs are indexed as whole underscore-delimited tokens. Querying
    # that exact observed ID recovers pages without repeated company names.
    for document in sorted(named_documents):
        result = await memory.search(SearchMemoryRequest(query=document, mode="fts", limit=10000))
        for hit in result.hits:
            if (hit.entry_id, hit.entry_version_id) in pdf_entries:
                candidates[(hit.entry_id, hit.entry_version_id)] = hit
    return candidates, named_documents


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Retrieve scoped evidence, then rank within the requested report offline."""
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be positive")  # noqa: TRY003
    raw_terms = [word for word in dict.fromkeys(_words(question)) if word not in _FUNCTION_WORDS]
    if not raw_terms:
        return ()
    expansions = " ".join(words for pattern, words in _CONCEPTS if re.search(pattern, question.lower()))
    candidates, named_documents = await _pdf_candidates(memory, question, raw_terms, expansions)
    if not candidates:
        return ()
    hits = list(candidates.values())
    if named_documents:
        hits = [hit for hit in hits if hit.text.partition("\n")[0] in named_documents]
    headings = [
        pattern for topic, pattern in _STATEMENT_HEADINGS if named_documents and re.search(topic, question.lower())
    ]
    # Primary tables often mention a requested metric only once among many numbers.
    statement_pages = [
        any(
            re.match(pattern, " ".join(_words(line)))
            for pattern in headings
            for line in hit.text.partition("\n")[2].splitlines()[:12]
        )
        for hit in hits
    ]
    document_terms = {term for doc in named_documents for term in _terms(doc)}
    terms = [term for term in dict.fromkeys(_terms(question)) if term not in _FUNCTION_WORDS | document_terms]
    weights = dict.fromkeys(terms, 1.0)
    for term in _terms(expansions):
        weights.setdefault(term, 0.45)
    counts = [Counter(_terms(hit.text.partition("\n")[2])) for hit in hits]
    average = sum(sum(count.values()) for count in counts) / len(counts) or 1
    frequency = Counter(term for count in counts for term in count)

    def score(index: int) -> float:
        count = counts[index]
        length = sum(count.values())
        return sum(
            weight
            * math.log(1 + (len(counts) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            * count[term]
            * 2.2
            / (count[term] + 1.2 * (0.25 + 0.75 * length / average))
            for term, weight in weights.items()
            if count[term]
        )

    citations = []
    pages = set()
    ranked = sorted(
        range(len(hits)),
        key=lambda index: (
            -_document_match(hits[index].text.partition("\n")[0], question)[1] if named_documents else 0,
            not statement_pages[index],
            -score(index),
            hits[index].entry_id,
        ),
    )
    for index in ranked:
        hit = hits[index]
        citation = MemoryCitation(
            memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
        )
        entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
        page_ids = {reference.source_id for reference in entry.sources if reference.source_type == "pdf-page"}
        if not page_ids or page_ids & pages:
            continue
        citations.append(citation)
        pages.update(page_ids)
        if len(citations) == limit:
            break
    return tuple(citations)
