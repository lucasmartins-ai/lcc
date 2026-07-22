from __future__ import annotations

from act2_router.local_verifier import RuleBasedVerifier
from act2_router.schemas import (
    LCCReportSummary,
    LocalAnswer,
    TaskFeatures,
    TaskInput,
    VerificationDecision,
)


def _summary() -> LCCReportSummary:
    return LCCReportSummary(10, 10, 0.0, 0.0, "skip")


def _features(**overrides: object) -> TaskFeatures:
    values = {
        "input_tokens": 10,
        "context_tokens": 8,
        "instruction_tokens": 2,
        "projected_savings_ratio": 0.0,
        "duplicate_ratio": 0.0,
        "has_strict_format": False,
        "requires_calculation": False,
        "requires_code": False,
        "requires_external_knowledge": False,
        "ambiguity_score": 0.0,
        "context_noise_score": 0.0,
        "lcc_recommendation": "skip",
        "has_conflicting_instructions": False,
    }
    values.update(overrides)
    return TaskFeatures(**values)  # type: ignore[arg-type]


def test_verifier_accepts_valid_json_answer() -> None:
    task = TaskInput("t", "Return JSON", "Status is green.", expected_format="json")
    answer = LocalAnswer('{"answer": "Status is green."}', "mock", 0)

    result = RuleBasedVerifier().verify(task, answer, _summary(), _features())

    assert result.decision == VerificationDecision.ACCEPT_LOCAL
    assert result.format_valid is True


def test_verifier_escalates_invalid_strict_format() -> None:
    task = TaskInput("t", "Return JSON", "Status is green.", expected_format="json")
    answer = LocalAnswer("Status is green.", "mock", 0)

    result = RuleBasedVerifier().verify(task, answer, _summary(), _features())

    assert result.decision == VerificationDecision.ESCALATE_REMOTE
    assert "valid JSON object" in result.missing_requirements


def test_verifier_requires_json_fields_as_keys() -> None:
    task = TaskInput(
        "t",
        "Return JSON with a status field",
        "Status is green.",
        expected_format="json object",
        metadata={"required_fields": ["status"]},
    )
    answer = LocalAnswer('{"answer": "status is green"}', "mock", 0)

    result = RuleBasedVerifier().verify(task, answer, _summary(), _features())

    assert result.decision == VerificationDecision.ESCALATE_REMOTE
    assert "field:status" in result.missing_requirements


def test_verifier_rejects_wrong_simple_calculation() -> None:
    task = TaskInput("t", "Calculate 17 + 25.", "Use 17 + 25 only.")
    answer = LocalAnswer("The total is 41.", "mock", 0)

    result = RuleBasedVerifier().verify(
        task,
        answer,
        _summary(),
        _features(requires_calculation=True),
    )

    assert result.decision == VerificationDecision.ESCALATE_REMOTE
    assert "calculated result:42" in result.missing_requirements


def test_verifier_rejects_overconfident_ambiguous_answer() -> None:
    task = TaskInput(
        "t",
        "What is the migration status?",
        "Plan A says approved, while incident notes say blocked.",
    )
    answer = LocalAnswer("The migration is approved.", "mock", 0)

    result = RuleBasedVerifier().verify(
        task,
        answer,
        _summary(),
        _features(ambiguity_score=0.5),
    )

    assert result.decision == VerificationDecision.ESCALATE_REMOTE
    assert "ambiguity_acknowledgement" in result.missing_requirements


def test_verifier_escalates_external_knowledge() -> None:
    task = TaskInput("t", "Latest status?", "No public status here.")
    answer = LocalAnswer("Looks fine.", "mock", 0)

    result = RuleBasedVerifier().verify(
        task,
        answer,
        _summary(),
        _features(requires_external_knowledge=True),
    )

    assert result.decision == VerificationDecision.ESCALATE_REMOTE
    assert "external_knowledge_required" in result.risk_reasons
