"""Tests for deterministic question-aware lexical chunk selection."""

from __future__ import annotations

from lcc.inspection import InspectionRequest, inspect
from lcc.lexical_selection import select_chunks_for_question

SELECTION_INPUT = (
    "# Billing Renewal\n\n"
    "Invoices renewal credits and payment collection notes for finance operations.\n\n"
    "# OAuth Token Rotation\n\n"
    "Rotate OAuth tokens for service accounts every quarter. "
    "Store token rotation evidence in the runbook.\n\n"
    "# General Notes\n\n"
    "Rotate OAuth tokens for service accounts every quarter. "
    "Store token rotation evidence in the runbook.\n"
)


def test_selects_question_matching_chunks_with_lexical_reasons() -> None:
    inspection = inspect(InspectionRequest(raw_text=SELECTION_INPUT, model="gpt-4.1"))

    result = select_chunks_for_question(
        raw_text=SELECTION_INPUT,
        question="What is the OAuth token rotation evidence?",
        chunk_inventory=inspection.chunk_inventory,
    )

    assert result.applied is True
    assert [chunk.index for chunk in result.report.selected_chunks] == [2, 3]
    assert result.selected_text == (
        "# OAuth Token Rotation\n\n"
        "Rotate OAuth tokens for service accounts every quarter. "
        "Store token rotation evidence in the runbook."
    )

    heading, evidence = result.report.selected_chunks
    assert heading.reason_codes == ["heading_match"]
    assert heading.signals["heading_terms"] == ["oauth", "rotation", "token"]
    assert set(evidence.reason_codes) == {
        "keyword_overlap",
        "rare_term_match",
        "matched_heading_proximity",
    }
    assert evidence.signals["keyword_terms"] == ["evidence", "oauth", "rotation", "token"]
    assert evidence.signals["rare_terms"] == ["evidence", "oauth", "rotation", "token"]
    assert evidence.signals["matched_heading_id"] == heading.id
    assert evidence.signals["distance_from_heading"] == 1


def test_selection_preserves_first_copy_and_skips_exact_duplicates() -> None:
    inspection = inspect(InspectionRequest(raw_text=SELECTION_INPUT, model="gpt-4.1"))
    duplicate = inspection.chunk_inventory[5]

    result = select_chunks_for_question(
        raw_text=SELECTION_INPUT,
        question="What is the OAuth token rotation evidence?",
        chunk_inventory=inspection.chunk_inventory,
    )

    assert duplicate.is_duplicate is True
    assert result.report.skipped_duplicate_chunk_ids == [duplicate.id]
    assert duplicate.id not in {chunk.id for chunk in result.report.selected_chunks}
    assert result.selected_text.count("Store token rotation evidence in the runbook.") == 1


def test_selection_is_not_applied_without_lexical_matches() -> None:
    inspection = inspect(InspectionRequest(raw_text=SELECTION_INPUT, model="gpt-4.1"))

    result = select_chunks_for_question(
        raw_text=SELECTION_INPUT,
        question="How should we plan the cafeteria menu?",
        chunk_inventory=inspection.chunk_inventory,
    )

    assert result.applied is False
    assert result.selected_text == SELECTION_INPUT
    assert result.report.reason == "no_lexical_matches"
    assert result.report.selected_chunks == []
