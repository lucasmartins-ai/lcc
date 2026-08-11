"""Unit tests for the unified LCC prompt intake engine."""

from __future__ import annotations

from lcc.intake import LccIntake, ParsedIntake, ReadinessState, parse_intake, process_intake


def test_parse_intake_empty_is_blocked():
    res = parse_intake("")
    assert res.readiness == ReadinessState.BLOCKED
    assert res.readiness_score == 0
    assert len(res.questions) > 0


def test_parse_intake_clear_request():
    clear_prompt = "Refactor the authentication middleware to use JWT tokens with 1-hour expiration and RS256 signing."
    res = parse_intake(clear_prompt)
    assert res.readiness == ReadinessState.READY_TO_EXECUTE
    assert res.readiness_score >= 80
    assert res.ambiguity_score <= 20


def test_parse_intake_ambiguous_request():
    ambiguous_prompt = "Maybe we should do something with the database or cache, not sure."
    res = parse_intake(ambiguous_prompt)
    assert res.readiness == ReadinessState.NEEDS_INTAKE
    assert res.readiness_score <= 50
    assert len(res.questions) > 0


def test_lcc_intake_pipeline_execution():
    pipeline = LccIntake(model="claude-sonnet-5", template_name="claude_xml")
    raw_context = """
    Sent from my iPhone
    CONFIDENTIAL NOTICE: Do not distribute.

    The user service handles authentication.
    The user service handles authentication.

    Please analyze the database queries for performance bottlenecks.
    """
    result = pipeline.process(raw_context, question="Find slow queries")

    assert result.parsed.readiness in {ReadinessState.READY_TO_EXECUTE, ReadinessState.NEEDS_LIGHT_REFINEMENT}
    assert result.compression is not None
    assert "Sent from my iPhone" not in result.formatted_prompt
    assert "<system_instructions>" in result.formatted_prompt
    assert "<context>" in result.formatted_prompt
    assert "<user_query>" in result.formatted_prompt
    assert result.compression.saved_tokens > 0


def test_process_intake_convenience_helper():
    res = process_intake("Fix bug in tokenizer", model="gemini-3.6-flash")
    assert res.formatted_prompt is not None
    assert "lcc-intake:readiness" in res.formatted_prompt
