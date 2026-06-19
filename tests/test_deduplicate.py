"""Tests for deterministic paragraph deduplication."""

from __future__ import annotations

from lcc.cleaning.deduplicate import deduplicate_paragraphs

_A = "The quick brown fox jumps over the lazy dog near the river bank."
_B = "The quick brown fox jumps over the lazy dog near the river banks."


def test_exact_duplicate_paragraph_removed():
    text = "Alpha paragraph.\n\nBeta paragraph.\n\nAlpha paragraph."
    result = deduplicate_paragraphs(text, remove_near_duplicates=False)
    assert result.text == "Alpha paragraph.\n\nBeta paragraph."
    assert result.metrics.paragraphs_before == 3
    assert result.metrics.paragraphs_after == 2
    assert result.metrics.duplicates_removed == 1


def test_order_is_preserved():
    text = "One.\n\nTwo.\n\nThree.\n\nTwo."
    result = deduplicate_paragraphs(text, remove_near_duplicates=False)
    assert result.text == "One.\n\nTwo.\n\nThree."


def test_whitespace_only_difference_is_exact_duplicate():
    text = "Hello   world.\n\nHello world."
    result = deduplicate_paragraphs(text, remove_near_duplicates=False)
    assert result.metrics.duplicates_removed == 1


def test_near_duplicate_removed_when_enabled():
    result = deduplicate_paragraphs(f"{_A}\n\n{_B}", remove_near_duplicates=True)
    assert result.metrics.near_duplicates_removed == 1
    assert result.metrics.paragraphs_after == 1


def test_near_duplicate_kept_when_disabled():
    result = deduplicate_paragraphs(f"{_A}\n\n{_B}", remove_near_duplicates=False)
    assert result.metrics.paragraphs_after == 2
    assert result.metrics.near_duplicates_removed == 0


def test_short_paragraphs_not_treated_as_near_duplicates():
    result = deduplicate_paragraphs("Yes.\n\nYes!", remove_near_duplicates=True)
    assert result.metrics.paragraphs_after == 2


def test_empty_input():
    result = deduplicate_paragraphs("")
    assert result.text == ""
    assert result.metrics.paragraphs_before == 0
    assert result.metrics.paragraphs_after == 0


def test_single_paragraph():
    result = deduplicate_paragraphs("Just one paragraph here.")
    assert result.metrics.paragraphs_before == 1
    assert result.metrics.paragraphs_after == 1
    assert result.metrics.duplicates_removed == 0


def test_all_duplicates_keeps_one():
    result = deduplicate_paragraphs("Same.\n\nSame.\n\nSame.", remove_near_duplicates=False)
    assert result.text == "Same."
    assert result.metrics.paragraphs_after == 1
    assert result.metrics.duplicates_removed == 2


def test_unicode_paragraphs():
    text = "Café résumé details here.\n\nCafé résumé details here.\n\nDistinct naïve text block."
    result = deduplicate_paragraphs(text, remove_near_duplicates=False)
    assert result.metrics.paragraphs_after == 2


def test_crlf_separated_duplicates_are_handled():
    result = deduplicate_paragraphs(
        "Para A.\r\n\r\nPara A.\r\n\r\nDistinct block.", remove_near_duplicates=False
    )
    assert result.metrics.duplicates_removed == 1
    assert result.metrics.paragraphs_after == 2
