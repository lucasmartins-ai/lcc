"""Deterministic, dependency-free text cleaning utilities (ADR 0006)."""

from __future__ import annotations

from lcc.cleaning.boilerplate import BoilerplateResult, remove_common_boilerplate
from lcc.cleaning.deduplicate import DedupResult, deduplicate_paragraphs
from lcc.cleaning.normalize import NormalizeResult, normalize_text
from lcc.cleaning.speech import (
    SpeechCleanResult,
    clean_speech_transcript,
    is_speech_transcript,
)


def safe_clean_text(text: str) -> str:
    """Apply minimal, safe, lossless cleaning (normalize, boilerplate, exact dedup)."""
    if not text or not text.strip():
        return text or ""
    # If transcript markers are present, strip audio noise and fillers first
    if is_speech_transcript(text):
        text = clean_speech_transcript(text)
    norm = normalize_text(text)
    bp = remove_common_boilerplate(norm.text)
    dedup = deduplicate_paragraphs(bp.text, remove_near_duplicates=False)
    return dedup.text


__all__ = [
    "BoilerplateResult",
    "DedupResult",
    "NormalizeResult",
    "SpeechCleanResult",
    "clean_speech_transcript",
    "deduplicate_paragraphs",
    "is_speech_transcript",
    "normalize_text",
    "remove_common_boilerplate",
    "safe_clean_text",
]

