"""Deterministic, dependency-free text cleaning utilities (ADR 0006)."""

from __future__ import annotations

from lcc.cleaning.boilerplate import BoilerplateResult, remove_common_boilerplate
from lcc.cleaning.deduplicate import DedupResult, deduplicate_paragraphs
from lcc.cleaning.normalize import NormalizeResult, normalize_text

__all__ = [
    "BoilerplateResult",
    "DedupResult",
    "NormalizeResult",
    "deduplicate_paragraphs",
    "normalize_text",
    "remove_common_boilerplate",
]
