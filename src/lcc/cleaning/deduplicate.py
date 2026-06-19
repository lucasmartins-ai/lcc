"""Deterministic paragraph deduplication (exact and conservative near-duplicate)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from lcc.schemas import DedupMetrics

_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n")
_WS = re.compile(r"\s+")


@dataclass
class DedupResult:
    """Deduplicated text plus paragraph-level metrics."""

    text: str
    metrics: DedupMetrics


def _normalize_key(paragraph: str) -> str:
    """Collapse all whitespace so trivial spacing differences count as exact duplicates."""
    return _WS.sub(" ", paragraph).strip()


def deduplicate_paragraphs(
    text: str,
    *,
    remove_near_duplicates: bool = True,
    similarity_threshold: float = 0.95,
    min_near_dup_chars: int = 40,
) -> DedupResult:
    """Remove duplicate paragraphs, keeping the first occurrence and preserving order.

    Paragraphs are blocks separated by one or more blank lines. Two paragraphs are *exact*
    duplicates when their whitespace-normalized text is identical (case-sensitive). When
    ``remove_near_duplicates`` is True, a paragraph is dropped as a *near* duplicate only
    if its similarity ratio (``difflib``) to an already-kept paragraph is at least
    ``similarity_threshold`` and both paragraphs are at least ``min_near_dup_chars`` long
    -- a deliberately conservative rule that avoids collapsing distinct short lines.

    This is safe cleaning, not summarization: no paragraph is ever shortened or rewritten.
    Line endings are normalized to LF first, so CRLF input is handled correctly.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_paragraphs = _PARAGRAPH_SPLIT.split(text)
    paragraphs = [block.strip() for block in raw_paragraphs if block.strip()]
    before = len(paragraphs)

    seen_exact: set[str] = set()
    kept: list[str] = []
    kept_keys: list[str] = []
    exact_removed = 0
    near_removed = 0

    for paragraph in paragraphs:
        key = _normalize_key(paragraph)
        if key in seen_exact:
            exact_removed += 1
            continue

        is_near_duplicate = False
        if remove_near_duplicates and len(key) >= min_near_dup_chars:
            lowered = key.lower()
            for existing in kept_keys:
                if len(existing) < min_near_dup_chars:
                    continue
                if SequenceMatcher(None, lowered, existing).ratio() >= similarity_threshold:
                    is_near_duplicate = True
                    break

        if is_near_duplicate:
            near_removed += 1
            continue

        seen_exact.add(key)
        kept.append(paragraph)
        kept_keys.append(key.lower())

    metrics = DedupMetrics(
        paragraphs_before=before,
        paragraphs_after=len(kept),
        duplicates_removed=exact_removed,
        near_duplicates_removed=near_removed,
    )
    return DedupResult(text="\n\n".join(kept), metrics=metrics)
