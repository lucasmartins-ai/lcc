"""Safety model tests: relevance != necessity != dependency != risk."""

from lcc.relevance.safety import BlockAssessment, decide_assessment


def test_high_relevance_redundant_can_drop():
    a = decide_assessment(relevance=0.9, necessity=0.1, redundancy=0.85, confidence=0.9)
    assert a.decision == "DROP"
    assert isinstance(a, BlockAssessment)


def test_moderate_relevance_unique_exception_must_keep():
    a = decide_assessment(relevance=0.5, necessity=0.9, confidence=0.9)
    assert a.decision == "KEEP"


def test_low_relevance_dependency_must_keep():
    a = decide_assessment(relevance=0.1, dependency_risk=0.8, confidence=0.9)
    assert a.decision == "KEEP"


def test_high_relevance_contradiction_requires_keep():
    a = decide_assessment(relevance=0.85, semantic_risk=0.9, confidence=0.9)
    assert a.decision == "KEEP"


def test_duplicated_high_relevance_one_can_drop():
    original = decide_assessment(relevance=0.9, necessity=0.9, redundancy=0.0)
    duplicate = decide_assessment(relevance=0.9, necessity=0.1, redundancy=0.9)
    assert original.decision == "KEEP"
    assert duplicate.decision == "DROP"


def test_qualifier_cannot_drop_independently():
    qualifier = decide_assessment(relevance=0.4, dependency_risk=0.7, semantic_risk=0.6)
    assert qualifier.decision == "KEEP"


def test_low_confidence_degrades_drop_to_trim_or_keep():
    drop = decide_assessment(relevance=0.1, confidence=0.9)
    assert drop.decision == "DROP"
    trimmed = decide_assessment(relevance=0.1, confidence=0.4)
    assert trimmed.decision == "TRIM"
    kept = decide_assessment(relevance=0.1, confidence=0.2)
    assert kept.decision == "KEEP"
