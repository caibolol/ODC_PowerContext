"""Complete PDF page evidence with revision identities and lexical retrieval."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import unicodedata
import zlib
from collections import Counter
from copy import copy
from itertools import pairwise

from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader, get_configuration
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NullObject,
    StreamObject,
)

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.pdf_layout import extract_page_text
from powercontext.sources.pdf_text import prepare_page_for_extraction
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


def _complete_encoded_stream(name: str, data: bytes) -> bool:
    if name in ("/FlateDecode", "/Fl"):
        decoder = zlib.decompressobj()
        decoder.decompress(data, max_length=get_configuration().zlib_maximum_output_length)
        return decoder.eof
    if name in ("/ASCII85Decode", "/A85"):
        return data.rstrip(b"\x00\t\n\f\r ").endswith(b"~>")
    if name in ("/ASCIIHexDecode", "/AHx"):
        return b">" in data
    offset = 0
    while offset < len(data) and data[offset] != 128:
        length = data[offset]
        offset += length + 2 if length < 128 else 2
    return offset < len(data) and data[offset] == 128


def _validate_compressed_streams(reader: PdfReader) -> None:
    # pypdf tolerates missing stream end markers even in strict mode.
    for stream in tuple(reader.resolved_objects.values()):
        if not isinstance(stream, EncodedStreamObject):
            continue
        filters = stream["/Filter"]
        if not isinstance(filters, ArrayObject):
            filters = ArrayObject([filters])
        for index, name in enumerate(filters):
            if name not in (
                "/FlateDecode",
                "/Fl",
                "/ASCII85Decode",
                "/A85",
                "/ASCIIHexDecode",
                "/AHx",
                "/RunLengthDecode",
                "/RL",
            ):
                continue
            data = stream._data
            if index:
                prefix = EncodedStreamObject()
                prefix.update(stream)
                prefix._data = data
                prefix[NameObject("/Filter")] = ArrayObject(filters[:index])
                data = prefix.get_data()
            if not _complete_encoded_stream(name, data):
                raise ValueError("Incomplete encoded PDF stream")  # noqa: TRY003


def _validate_content(reader: PdfReader, content, resources, active: set[int]) -> DictionaryObject:
    content = content.get_object()
    if isinstance(content, NullObject):
        return resources
    streams = content if isinstance(content, ArrayObject) else (content,)
    if any(not isinstance(stream.get_object(), (StreamObject, NullObject)) for stream in streams):
        raise TypeError("Invalid PDF content stream")  # noqa: TRY003
    forms = {}
    for operands, operator in ContentStream(content, reader).operations:
        if operator not in (b"Tf", b"Do"):
            continue
        font = operator == b"Tf"
        if len(operands) != (2 if font else 1) or not isinstance(operands[0], NameObject):
            raise ValueError("Invalid PDF resource invocation")  # noqa: TRY003
        resource = resources["/Font" if font else "/XObject"][operands[0]]
        if not isinstance(resource, DictionaryObject if font else StreamObject) or not resource:
            raise TypeError("Invalid PDF resource")  # noqa: TRY003
        if font or resource["/Subtype"] != "/Form" or operands[0] in forms:
            continue
        identity = id(resource)
        if identity in active:
            raise ValueError("Cyclic PDF form invocation")  # noqa: TRY003
        # pypdf needs explicit resources; clone per caller so shared forms keep the right fonts.
        form = copy(resource)
        form[NameObject("/Resources")] = _validate_content(
            reader, resource, resource.get("/Resources", resources).get_object(), active | {identity}
        )
        forms[operands[0]] = form
    if forms:
        xobjects = DictionaryObject(resources["/XObject"])
        xobjects.update(forms)
        resources = DictionaryObject(resources)
        resources[NameObject("/XObject")] = xobjects
    return resources


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
        pages = []
        for number, page in enumerate(reader.pages, 1):
            # Extraction swallows broken Form XObjects; parse their operations first.
            if "/Contents" in page:
                resources = _validate_content(
                    reader, page["/Contents"], page.get_inherited("/Resources", DictionaryObject()), set()
                )
                page = copy(page)
                page[NameObject("/Resources")] = resources
            pages.append(
                PDFPageInput(
                    document_id=value.document_id,
                    document_sha256=digest,
                    page_number=number,
                    text=extract_page_text(prepare_page_for_extraction(page, reader), reader),
                )
            )
        _validate_compressed_streams(reader)
    except Exception as error:
        raise ValueError("Unable to extract the complete PDF") from error  # noqa: TRY003
    return tuple(pages)


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
    "s",
    "answer",
    "respond",
    "response",
    "give",
    "using",
    "use",
    "shown",
    "details",
    "perspective",
    "investment",
    "analyst",
    "assuming",
])


# Computed metrics need the underlying statements even when their names never appear there.
_COMPUTED_METRIC = (
    r"\b(?:ratios?|turnover|returns? on|yields?|liquidity|leverage|solvency|coverage|cash conversion)\b"
    r"|\bdays\b.*\b(?:sales|inventory|receivables?|payables?|collect)\b"
    r"|\b(?:sales|inventory|receivables?|payables?|collection)\b.*\bdays\b"
)

# General accounting vocabulary, independent of any report or benchmark question.
_CONCEPTS = (
    (
        _COMPUTED_METRIC,
        "consolidated statements income operations earnings cash flows balance sheets financial position",
    ),
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

# General accounting synonyms supplement computed-metric statement discovery.
_CONCEPTS += (
    (
        "\\bcapex\\b|\\bcapital expenditures?\\b|\\bcapital spending\\b|\\bcapital outlays?\\b",
        "capital expenditures purchases of property plant and equipment additions to property plant and equipment payments for property plant and equipment",
    ),
    (
        "\\bebitda\\b|\\boperating profit\\b|\\boperating income\\b",
        "operating income operating profit income from operations",
    ),
    (
        "\\bd\\s*&\\s*a\\b|\\bdepreciation and amortization\\b",
        "depreciation and amortization depreciation amortization",
    ),
    ("\\brevenues?\\b|\\bnet sales\\b|\\bsales\\b|\\bturnover\\b", "net revenue net sales total revenues sales"),
    (
        "\\bnet income\\b|\\bnet earnings\\b|\\bprofit\\b|\\bbottom line\\b",
        "net income net earnings net income attributable",
    ),
    ("\\bgross (?:profit|margin)\\b", "gross profit gross margin cost of sales"),
    (
        "\\bcogs?\\b|\\bcost of goods sold\\b|\\bcost of sales\\b",
        "cost of goods sold cost of sales cost of products sold",
    ),
    (
        "\\bsg\\s*&\\s*a\\b|\\bselling,? general and administrative\\b",
        "selling general and administrative selling general and administrative expenses",
    ),
    ("\\br\\s*&\\s*d\\b|\\bresearch and development\\b", "research and development research and development expenses"),
    (
        "\\bcash flows?\\b|\\bfree cash flow\\b|\\boperating cash flow\\b",
        "cash flows from operating activities net cash provided by operating activities free cash flow",
    ),
    ("\\bbalance sheets?\\b|\\bfinancial position\\b", "balance sheet financial position total assets"),
    (
        "\\bincome statements?\\b|\\bprofit and loss\\b|\\bp\\s*&\\s*l\\b",
        "statements of income statements of earnings income from operations",
    ),
    (
        "\\bassets?\\b|\\bliabilit(?:y|ies)\\b|\\bequity\\b|\\bshareholders'? equity\\b|\\bstockholders'? equity\\b",
        "total assets total liabilities total equity stockholders equity",
    ),
    (
        "\\bdebt\\b|\\bborrowings?\\b|\\bleverage\\b",
        "long-term debt short-term debt total debt borrowings notes payable",
    ),
    ("\\bdividends?\\b", "dividends cash dividends dividend payments"),
    ("\\beps\\b|\\bearnings per share\\b", "earnings per share diluted earnings per share basic earnings per share"),
    ("\\bshares? outstanding\\b|\\bshare count\\b", "shares outstanding weighted average shares outstanding"),
    (
        "\\btax(?:es)?\\b|\\beffective tax rate\\b|\\bincome taxes\\b",
        "income taxes provision for income taxes effective tax rate",
    ),
    ("\\binventor(?:y|ies)\\b", "inventories"),
    ("\\breceivables?\\b|\\baccounts receivable\\b", "accounts receivable receivables"),
    ("\\bgoodwill\\b|\\bintangible assets?\\b", "goodwill intangible assets"),
    ("\\brestructuring\\b", "restructuring restructuring charges severance"),
    (
        "\\blegal\\b|\\blitigation\\b|\\blawsuits?\\b|\\bproceedings?\\b|\\bcontingenc(?:y|ies)\\b",
        "legal proceedings legal matters litigation matters contingencies claims",
    ),
    (
        "\\bgeograph(?:y|ies)\\b|\\bregions?\\b|\\bcountries\\b|\\bterritor(?:y|ies)\\b",
        "geographic regions countries territories international operations reportable segments",
    ),
    ("\\bemployees?\\b|\\bheadcount\\b|\\bworkforce\\b", "employees headcount"),
    ("\\bcompetition\\b|\\bcompetitors?\\b", "competition competitors"),
    ("\\bacquisitions?\\b|\\bbusiness combinations?\\b", "acquisitions business combinations"),
    ("\\bpensions?\\b|\\bretirement plans?\\b", "pension retirement plans"),
    ("\\binterest (?:expense|income)\\b", "interest expense interest income"),
    ("\\bforeign exchange\\b|\\bcurrency\\b|\\bfx\\b", "foreign exchange currency"),
    ("\\bsupply chain\\b", "supply chain"),
    ("\\bbacklog\\b|\\borders\\b", "backlog orders"),
    ("\\bbuybacks?\\b|\\brepurchases?\\b", "share repurchases repurchases"),
    ("\\bworking capital\\b", "working capital"),
    ("\\bdeferred revenue\\b", "deferred revenue"),
    ("\\bimpairment\\b", "impairment"),
    ("\\brisk factors?\\b", "risk factors"),
    ("\\boperating leases?\\b", "operating lease"),
)

_STATEMENT_HEADINGS = (
    (
        r"\b(?:income|p&l|profit|earnings|revenue|sales|margin|ebitda)\b",
        r"^(?P<prefix>(?:(?:consolidated|condensed|combined) )*)(?:statements? of (?:income|operations|earnings)(?: and (?:comprehensive income|retained earnings))?|income statements?)\b(?P<suffix>.*)$",
    ),
    (
        r"\b(?:cash flows?|capex|capital expenditures?|capital spending|ebitda|d\s*&\s*a|depreciation|amortization|dividends?)\b",
        r"^(?P<prefix>(?:(?:consolidated|condensed|combined) )*)(?:statements? of cash flows?|cash flows? statements?)\b(?P<suffix>.*)$",
    ),
    (
        r"\b(?:balance sheets?|assets?|liabilit\w*|equity|working capital|receivables?|payables?|inventor(?:y|ies)|debt)\b",
        r"^(?P<prefix>(?:(?:consolidated|condensed|combined) )*)(?:balance sheets?|statements? of financial position)\b(?P<suffix>.*)$",
    ),
)


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"-\s*\n\s*", "", text)
    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)


def _normalize_token(token: str) -> str:
    match = re.fullmatch(r"fy(\d{2,4})", token)
    if match is None:
        return token
    digits = match.group(1)
    if len(digits) == 4:
        return digits
    if len(digits) == 2:
        return "20" + digits
    return token


def _words(value: str) -> list[str]:
    return [_normalize_token(token) for token in re.findall(r"[a-z0-9]+", _fold(value))]


def _canon(token: str) -> str:  # noqa: C901
    if token.isdigit():
        return token
    current = token
    if len(current) > 4 and current.endswith("ies"):
        current = current[:-3] + "y"
    elif current.endswith("sses") or (len(current) > 4 and current.endswith("es") and current[-3] in "sxz"):
        current = current[:-2]
    elif len(current) > 3 and current.endswith("s") and not current.endswith(("ss", "us", "is")):
        current = current[:-1]
    if len(current) > 5 and current.endswith("ing"):
        current = current[:-3]
    elif len(current) > 4 and current.endswith("ed"):
        current = current[:-2]
    if len(current) > 5 and current.endswith("ation"):
        current = current[:-5] + "at"
    elif len(current) > 6 and current.endswith("ment"):
        current = current[:-4]
    if len(current) > 4 and current.endswith("ly"):
        current = current[:-2]
    if len(current) > 4 and current.endswith("e"):
        current = current[:-1]
    if len(current) > 4 and current.endswith("y"):
        current = current[:-1] + "i"
    return current


def _variants(token: str) -> tuple[str, ...]:
    if token.isdigit():
        return (token,)
    forms = [token]
    if token.endswith("ies") and len(token) > 4:
        forms.append(token[:-3] + "y")
    elif token.endswith("y") and len(token) > 3:
        forms.append(token[:-1] + "ies")
    if token.endswith("s") and not token.endswith("ss"):
        forms.append(token[:-1])
    else:
        forms.append(token + "s")
    if token.endswith("ing") and len(token) > 5:
        forms.extend((token[:-3], token[:-3] + "e"))
    elif token.endswith("ed") and len(token) > 4:
        forms.extend((token[:-2], token[:-1]))
    elif token.endswith("e") and len(token) > 3:
        forms.extend((token[:-1] + "ing", token + "d"))
    return tuple(dict.fromkeys(form for form in forms if len(form) > 1))[:5]


def _terms(text: str) -> list[str]:
    return [_canon(word) for word in _words(text)]


_COMPANY_SUFFIXES = frozenset({
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "holdings",
    "ltd",
    "plc",
    "the",
})


def _name_pattern(name: str) -> str:
    compact = "".join(_words(name))
    return r"\b" + r"\s*".join(re.escape(character) for character in compact) + r"\b"


def _company_name(document: str) -> str:
    company = re.split(r"(?:19|20)\d{2}", document.lower(), maxsplit=1)[0]
    return " ".join(word for word in _words(company) if word not in _COMPANY_SUFFIXES)


def _document_match(document: str, question: str) -> tuple[int, int]:
    # The projection's first line is the document ID, not body text. Its company
    # and report year constrain relevance even when page text omits the company.
    company = _company_name(document)
    named = bool(company and re.search(_name_pattern(company), " ".join(_words(question))))
    years = set(re.findall(r"(?:19|20)\d{2}", document))
    requested = set(re.findall(r"(?:19|20)\d{2}", question))
    return int(named), int(bool(years & requested))


def _report_aliases(document: str, bodies: list[str]) -> set[str]:
    """Use names declared by the report, without a company or ticker dictionary."""
    company = _company_name(document)
    if not company:
        return set()
    text = _fold("\n".join(bodies)).replace("\u201c", '"').replace("\u201d", '"')
    text = " ".join(text.split())
    # A defined name follows the registrant name, optionally after legal suffixes.
    company_pattern = _name_pattern(company).replace(r"\s*", r"[^\w]*")
    declarations = re.finditer(company_pattern + r"[^()\n]{0,80}\(([^()]{1,160})\)", text)
    aliases = {name for declaration in declarations for name in re.findall(r'"([^"\n]+)"', declaration[1])}
    # Stock-symbol declarations refer to the registrant's own common stock.
    aliases.update(
        match[1]
        for match in re.finditer(
            r"(?:our|the company['\u2019]s) common stock[^.]{0,240}\b(?:under (?:the )?|trading )?symbol\s+\"([a-z0-9.\-]{1,8})\"",
            text,
        )
    )
    return {
        name
        for name in aliases
        if len("".join(_words(name))) >= 2
        and set(_words(name))
        - _FUNCTION_WORDS
        - _COMPANY_SUFFIXES
        - {"firm", "group", "registrant", "parent", "we", "us"}
    }


def _statement_suffix(suffix: str, document: str) -> bool:
    suffix = re.sub(r"^(?:(?:continued|unaudited|audited)\b\s*)+", "", suffix.strip())
    if not suffix:
        return True
    company = _company_name(document)
    if company and re.match(_name_pattern(company), suffix):
        return True
    return bool(
        re.match(
            r"(?:in |dollars |amounts |thousands |millions |billions |as of |at [a-z]+ \d|for the years? |years? ended |[a-z]+ \d{1,2} (?:19|20)\d{2})",
            suffix,
        )
    )


def _statement_headings(body: str, document: str) -> list[tuple[str, bool]]:
    lines = [" ".join(_words(line)) for line in body.splitlines() if line.strip()]
    # Contents pages list statements and numbered notes without their data tables.
    if re.search(r"\bindex to (?:consolidated )?financial statements\b", " ".join(lines[:12])):
        return []
    if sum(bool(re.match(r"(?:note|item) \d+\b", line)) for line in lines) >= 3:
        return []
    headings = []
    for start in range(min(10, len(lines))):
        for end in range(start + 1, min(start + 3, len(lines)) + 1):
            header = " ".join(lines[start:end])
            for topic, pattern in _STATEMENT_HEADINGS:
                match = re.match(pattern, header)
                # A standalone number following a heading is a contents-page locator.
                if (
                    match
                    and _statement_suffix(match["suffix"], document)
                    and (end == len(lines) or not re.fullmatch(r"\d{1,3}", lines[end]))
                ):
                    headings.append((topic, bool(match["prefix"])))
    return list(dict.fromkeys(headings))


async def _pdf_candidates(memory, question: str, raw_terms: list[str], expansions: str):
    # Only PDF-backed entries may select a report; notes can contain the same headings.
    pdf_entries, report_bodies = {}, {}
    for record in (await memory.list()).entries:
        if any(reference.source_type == "pdf-page" for reference in record.entry.sources):
            document, _, body = record.entry.text.partition("\n")
            pdf_entries[(record.entry.entry_id, record.entry.entry_version_id)] = document
            report_bodies.setdefault(document, []).append(body)
    if not pdf_entries:
        return {}, set(), set()
    candidates = {}
    # FTS indexes original tokens, not our ranking stems. Keep plural forms and
    # all query terms so long questions do not silently lose their final subject.
    queries = [question, *raw_terms, *dict.fromkeys(_words(expansions))]
    queries.extend(form for term in raw_terms for form in _variants(term))
    for query in dict.fromkeys(queries):
        result = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=10000))
        for hit in result.hits:
            if (hit.entry_id, hit.entry_version_id) in pdf_entries:
                candidates[(hit.entry_id, hit.entry_version_id)] = hit
    documents = set(pdf_entries.values())
    normalized_question = " ".join(_words(question))
    named_documents = {
        doc
        for doc in documents
        if _document_match(doc, question)[0]
        or any(
            re.search(_name_pattern(alias), normalized_question) for alias in _report_aliases(doc, report_bodies[doc])
        )
    }
    # Document IDs are indexed as whole underscore-delimited tokens. Querying
    # that exact observed ID recovers pages without repeated company names.
    for document in sorted(named_documents or (documents if len(documents) == 1 else set())):
        result = await memory.search(SearchMemoryRequest(query=document, mode="fts", limit=10000))
        for hit in result.hits:
            if (hit.entry_id, hit.entry_version_id) in pdf_entries:
                candidates[(hit.entry_id, hit.entry_version_id)] = hit
    return candidates, named_documents, documents


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Retrieve scoped evidence, then rank within the requested report offline."""
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be nonnegative")  # noqa: TRY003
    question = re.sub(r"\bfy(\d{2})\b", r"20\1", _fold(question))
    raw_terms = [word for word in dict.fromkeys(_words(question)) if word not in _FUNCTION_WORDS]
    if not raw_terms or limit == 0:
        return ()
    expansions = " ".join(words for pattern, words in _CONCEPTS if re.search(pattern, question.lower()))
    candidates, named_documents, documents = await _pdf_candidates(memory, question, raw_terms, expansions)
    if not candidates:
        return ()
    hits = list(candidates.values())
    if named_documents:
        hits = [hit for hit in hits if hit.text.partition("\n")[0] in named_documents]
    # Primary tables often mention a requested metric only once among many numbers.
    matched_headings = [_statement_headings(hit.text.partition("\n")[2], hit.text.partition("\n")[0]) for hit in hits]
    prefixed_documents = {
        hit.text.partition("\n")[0]
        for hit, page_headings in zip(hits, matched_headings, strict=True)
        if any(prefixed for _, prefixed in page_headings)
    }
    # Bare statement titles can be note tables; use them only in reports without prefixed titles.
    primary_headings = [
        [
            topic
            for topic, prefixed in page_headings
            if prefixed or hit.text.partition("\n")[0] not in prefixed_documents
        ]
        for hit, page_headings in zip(hits, matched_headings, strict=True)
    ]
    focused_report = bool(named_documents) or len(documents) == 1
    statement_pages = [
        focused_report
        and any(
            re.search(topic, question.lower()) or re.search(_COMPUTED_METRIC, question.lower())
            for topic in page_headings
        )
        for page_headings in primary_headings
    ]
    primary_pages = [bool(page_headings) for page_headings in primary_headings]
    document_terms = {term for doc in named_documents for term in _terms(doc)}
    terms = [term for term in dict.fromkeys(_terms(question)) if term not in _FUNCTION_WORDS | document_terms]
    weights = dict.fromkeys(terms, 1.0)
    for term in _terms(expansions):
        weights.setdefault(term, 0.45)
    body_terms = [_terms(hit.text.partition("\n")[2]) for hit in hits]
    query_numbers = {term for term in _words(question) if term.isdigit()}
    number_matches = [len(query_numbers.intersection(tokens)) for tokens in body_terms]
    body_terms = [[term for term in tokens if not term.isdigit()] for tokens in body_terms]
    counts = [Counter(tokens) for tokens in body_terms]
    phrases = set(pairwise(term for term in _terms(question) if term not in _FUNCTION_WORDS | document_terms))
    page_phrases = [Counter(pairwise(term for term in tokens if term not in _FUNCTION_WORDS)) for tokens in body_terms]
    average = sum(sum(count.values()) for count in counts) / len(counts) or 1
    frequency = Counter(term for count in counts for term in count)

    def score(index: int) -> float:
        count = counts[index]
        length = sum(count.values())
        lexical = sum(
            weight
            * math.log(1 + (len(counts) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            * count[term]
            * 2.2
            / (count[term] + 1.2 * (0.25 + 0.75 * length / average))
            for term, weight in weights.items()
            if count[term]
        )

        phrase_score = sum(
            min(page_phrases[index][pair], 2)
            * sum(math.log(1 + (len(counts) - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in pair)
            * 0.55
            for pair in phrases
            if page_phrases[index][pair]
        )
        return lexical + phrase_score + 0.5 * min(number_matches[index], 2)

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
    # Reserve part of the page budget for primary tables when a metric is phrased indirectly.
    reserved = [index for index in ranked if primary_pages[index]][: limit // 3]
    ranked = sorted(
        dict.fromkeys([*reserved, *ranked]),
        key=lambda index: -_document_match(hits[index].text.partition("\n")[0], question)[1] if named_documents else 0,
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
