"""Deterministic lexical chunk selection for ``lcc prepare``.

The selector is intentionally mechanical: it uses ``chunk_inventory`` offsets to inspect
literal source chunks and keeps chunks only for transparent lexical reasons. It performs no
summarization, rewriting, embeddings, model calls, or network access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lcc.inspection.schemas import ChunkInventoryItem

PREPARE_SCHEMA_VERSION = "prepare-1.0"

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list[str] | list[int]

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?")
_PROXIMITY_CHUNK_LIMIT = 3
_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "can",
    "for",
    "from",
    "has",
    "have",
    "how",
    "into",
    "its",
    "our",
    "should",
    "that",
    "the",
    "their",
    "this",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}


@dataclass(frozen=True)
class SelectedChunk:
    """One source chunk kept by the lexical selector, with auditable reasons."""

    id: str
    index: int
    label: str
    line_start: int
    line_end: int
    token_count: int
    token_count_method: str
    reason_codes: list[str]
    signals: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class LexicalSelectionReport:
    """Machine-readable explanation of a prepare-time lexical selection pass."""

    strategy: str
    applied: bool
    reason: str
    question_terms: list[str]
    source_chunk_count: int
    selected_chunk_count: int
    selected_token_count: int
    selected_chunks: list[SelectedChunk]
    skipped_duplicate_chunk_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LexicalSelectionResult:
    """Selected raw text plus the deterministic report explaining the selection."""

    applied: bool
    selected_text: str
    report: LexicalSelectionReport


@dataclass(frozen=True)
class _HeadingContext:
    id: str
    text: str
    terms: set[str]
    distance: int


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for match in _WORD_RE.finditer(text.lower()):
        term = match.group(0).strip("'")
        if len(term) < 3 or term in _STOPWORDS:
            continue
        terms.add(term)
    return terms


def _ordered_terms(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _WORD_RE.finditer(text.lower()):
        term = match.group(0).strip("'")
        if len(term) < 3 or term in _STOPWORDS or term in seen:
            continue
        seen.add(term)
        ordered.append(term)
    return ordered


def _chunk_text(raw_text: str, chunk: ChunkInventoryItem) -> str:
    return raw_text[chunk.character_start : chunk.character_end]


def _reasoned_chunk(
    chunk: ChunkInventoryItem,
    *,
    reason_codes: list[str],
    signals: dict[str, JsonValue],
) -> SelectedChunk:
    return SelectedChunk(
        id=chunk.id,
        index=chunk.index,
        label=chunk.label,
        line_start=chunk.line_start,
        line_end=chunk.line_end,
        token_count=chunk.token_count,
        token_count_method=chunk.token_count_method,
        reason_codes=reason_codes,
        signals=signals,
    )


def _inventory_heading_context(
    chunk_inventory: list[ChunkInventoryItem],
) -> dict[str, _HeadingContext]:
    contexts: dict[str, _HeadingContext] = {}
    current_heading: ChunkInventoryItem | None = None
    distance = 0
    for chunk in chunk_inventory:
        if chunk.label == "heading":
            current_heading = chunk
            distance = 0
            continue
        if current_heading is None or current_heading.heading_text is None:
            continue
        distance += 1
        contexts[chunk.id] = _HeadingContext(
            id=current_heading.id,
            text=current_heading.heading_text,
            terms=_terms(current_heading.heading_text),
            distance=distance,
        )
    return contexts


def _document_frequency(
    *,
    raw_text: str,
    chunk_inventory: list[ChunkInventoryItem],
) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for chunk in chunk_inventory:
        if chunk.is_duplicate:
            continue
        for term in _terms(_chunk_text(raw_text, chunk)):
            frequencies[term] = frequencies.get(term, 0) + 1
    return frequencies


def _not_applied_result(
    *,
    raw_text: str,
    reason: str,
    question_terms: list[str],
    source_chunk_count: int,
) -> LexicalSelectionResult:
    return LexicalSelectionResult(
        applied=False,
        selected_text=raw_text,
        report=LexicalSelectionReport(
            strategy="question_aware_lexical",
            applied=False,
            reason=reason,
            question_terms=question_terms,
            source_chunk_count=source_chunk_count,
            selected_chunk_count=0,
            selected_token_count=0,
            selected_chunks=[],
            skipped_duplicate_chunk_ids=[],
        ),
    )


def select_chunks_for_question(
    *,
    raw_text: str,
    question: str,
    chunk_inventory: list[ChunkInventoryItem],
) -> LexicalSelectionResult:
    """Select source chunks using only deterministic lexical/mechanical signals.

    The returned text is built from literal source slices, joined in original order. Exact
    duplicate chunks are not selected; the first copy remains eligible and duplicate chunk IDs
    with lexical matches are recorded in the report.
    """
    question_terms = _ordered_terms(question)
    question_term_set = set(question_terms)
    if not question_terms:
        return _not_applied_result(
            raw_text=raw_text,
            reason="no_question_terms",
            question_terms=question_terms,
            source_chunk_count=len(chunk_inventory),
        )

    heading_contexts = _inventory_heading_context(chunk_inventory)
    matched_heading_ids = {
        chunk.id
        for chunk in chunk_inventory
        if chunk.label == "heading"
        and chunk.heading_text is not None
        and (_terms(chunk.heading_text) & question_term_set)
    }
    frequencies = _document_frequency(raw_text=raw_text, chunk_inventory=chunk_inventory)
    rare_question_terms = {
        term for term in question_terms if frequencies.get(term, 0) > 0 and frequencies[term] <= 2
    }

    selected_by_id: dict[str, SelectedChunk] = {}
    skipped_duplicate_chunk_ids: list[str] = []

    for chunk in chunk_inventory:
        text_terms = _terms(_chunk_text(raw_text, chunk))
        keyword_terms = sorted(question_term_set & text_terms)
        rare_terms = sorted(set(keyword_terms) & rare_question_terms)
        heading_context = heading_contexts.get(chunk.id)
        is_near_matched_heading = (
            heading_context is not None
            and heading_context.id in matched_heading_ids
            and heading_context.distance <= _PROXIMITY_CHUNK_LIMIT
        )

        reason_codes: list[str] = []
        signals: dict[str, JsonValue] = {}

        if chunk.label == "heading" and chunk.heading_text is not None:
            heading_terms = sorted(_terms(chunk.heading_text) & question_term_set)
            if heading_terms:
                reason_codes.append("heading_match")
                signals["heading_terms"] = heading_terms
        elif keyword_terms:
            reason_codes.append("keyword_overlap")
            signals["keyword_terms"] = keyword_terms

        if rare_terms and chunk.label != "heading":
            reason_codes.append("rare_term_match")
            signals["rare_terms"] = rare_terms

        if chunk.label != "heading" and is_near_matched_heading and heading_context is not None:
            reason_codes.append("matched_heading_proximity")
            signals["matched_heading_id"] = heading_context.id
            signals["matched_heading_text"] = heading_context.text
            signals["distance_from_heading"] = heading_context.distance

        if not reason_codes:
            continue

        if chunk.is_duplicate:
            skipped_duplicate_chunk_ids.append(chunk.id)
            continue

        selected_by_id[chunk.id] = _reasoned_chunk(
            chunk,
            reason_codes=reason_codes,
            signals=signals,
        )

    if not selected_by_id:
        return _not_applied_result(
            raw_text=raw_text,
            reason="no_lexical_matches",
            question_terms=question_terms,
            source_chunk_count=len(chunk_inventory),
        )

    selected_chunks = [
        selected_by_id[chunk.id] for chunk in chunk_inventory if chunk.id in selected_by_id
    ]
    selected_text = "\n\n".join(
        _chunk_text(raw_text, chunk) for chunk in chunk_inventory if chunk.id in selected_by_id
    )
    selected_token_count = sum(chunk.token_count for chunk in selected_chunks)

    return LexicalSelectionResult(
        applied=True,
        selected_text=selected_text,
        report=LexicalSelectionReport(
            strategy="question_aware_lexical",
            applied=True,
            reason="lexical_matches",
            question_terms=question_terms,
            source_chunk_count=len(chunk_inventory),
            selected_chunk_count=len(selected_chunks),
            selected_token_count=selected_token_count,
            selected_chunks=selected_chunks,
            skipped_duplicate_chunk_ids=skipped_duplicate_chunk_ids,
        ),
    )
