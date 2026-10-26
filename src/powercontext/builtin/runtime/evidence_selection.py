"""Query-driven selection of literal, cited Memory sentence spans."""

from __future__ import annotations

import json
import math
import re
from collections import Counter

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.models import PreparedContext
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    PreparedContextBuild,
    PreparedEvidenceFragment,
)
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_STOP = frozenset([
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
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "their",
    "our",
    "we",
    "you",
    "can",
    "could",
    "would",
    "should",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
])


def _tokens(value: str) -> list[str]:
    tokens = re.findall(r"[^\W_]+", value.lower())
    return [token[:-1] if len(token) > 4 and token.endswith("s") else token for token in tokens if token not in _STOP]


def _key(address: MemoryEntryAddress) -> tuple[str, str, str, str]:
    return (address.memory.scope_id, address.memory.artifact.artifact_id, address.entry_id, address.entry_version_id)


def _render(fragments: list[PreparedEvidenceFragment]) -> str:
    items = [
        {
            "citation": {
                "scope_id": fragment.address.memory.scope_id,
                "memory_ref": fragment.address.memory.artifact.model_dump(mode="json"),
                "entry_id": fragment.address.entry_id,
                "entry_version_id": fragment.address.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }
        for fragment in fragments
    ]
    encoded = json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
    return f"{TRUST_POLICY}\n\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n{encoded}\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1"


def _collect_spans(memory_candidates):
    spans = []
    texts = {}
    for group in memory_candidates:
        for hit in group.hits:
            address = MemoryEntryAddress(
                memory=ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref),
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            texts[_key(address)] = hit.text
            starts = [0, *(match.end() for match in re.finditer(r"(?<=[.!?])\s+|\n+", hit.text))]
            seen = set()
            for start, end in zip(starts, [*starts[1:], len(hit.text)], strict=True):
                while start < end and hit.text[start].isspace():
                    start += 1
                while end > start and hit.text[end - 1].isspace():
                    end -= 1
                sentence = hit.text[start:end]
                if not sentence or sentence in seen:
                    continue
                seen.add(sentence)
                spans.append((address, start, end, Counter(_tokens(sentence))))
    return spans, texts


def _merge_proposal(selected, fragment, text):
    # Adjacent sentences share a citation while retaining an exact original interval.
    for index, prior in enumerate(selected):
        if prior.address != fragment.address:
            continue
        lo, hi = min(fragment.start, prior.start), max(fragment.end, prior.end)
        gap = text[min(fragment.end, prior.end) : max(fragment.start, prior.start)]
        if not gap.strip():
            proposal = selected.copy()
            proposal[index] = PreparedEvidenceFragment(fragment.address, lo, hi, text[lo:hi])
            return proposal
    return [*selected, fragment]


def _fit_window(fragment, text, query, max_bytes):
    matches = [
        match
        for match in re.finditer(r"[^\W_]+", fragment.text)
        if _tokens(match.group()) and _tokens(match.group())[0] in query
    ]
    if not matches:
        return None
    anchor = fragment.start + matches[0].start()
    lo, hi = 1, fragment.end - fragment.start
    best = None
    while lo <= hi:
        width = (lo + hi) // 2
        left = max(fragment.start, min(anchor - width // 3, fragment.end - width))
        part = PreparedEvidenceFragment(fragment.address, left, left + width, text[left : left + width])
        if len(_render([part]).encode("utf-8")) <= max_bytes:
            best, lo = part, width + 1
        else:
            hi = width - 1
    return best


def select_evidence(request, memory_candidates) -> PreparedContextBuild:
    query = Counter(_tokens(request.query))
    spans, texts = _collect_spans(memory_candidates)
    frequency = Counter(term for _, _, _, count in spans for term in count)

    def score(span) -> float:
        count = span[3]
        return (
            sum(
                math.log(1 + (len(spans) + 0.5) / (frequency[term] + 0.5)) * (1 + math.log(count[term]))
                for term in query
                if count[term]
            )
            / max(1, sum(count.values())) ** 0.2
        )

    selected: list[PreparedEvidenceFragment] = []
    for address, start, end, count in sorted(spans, key=lambda span: -score(span)):
        if not query.keys() & count.keys():
            continue
        text = texts[_key(address)]
        fragment = PreparedEvidenceFragment(address, start, end, text[start:end])
        proposal = _merge_proposal(selected, fragment, text)
        if len(_render(proposal).encode("utf-8")) <= request.max_bytes:
            selected = proposal
        elif not selected:
            best = _fit_window(fragment, text, query, request.max_bytes)
            if best is not None:
                selected = [best]
    if not selected:
        return PreparedContextBuild(context=PreparedContext(status="empty", content=None, content_bytes=0), origins=())
    content = _render(selected)
    return PreparedContextBuild(
        context=PreparedContext(status="ready", content=content, content_bytes=len(content.encode("utf-8"))),
        origins=tuple(fragment.address for fragment in selected),
        fragments=tuple(selected),
    )
