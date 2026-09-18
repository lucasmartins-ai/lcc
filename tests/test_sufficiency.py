"""Sufficiency verification tests: candidate compression -> verify -> restore."""

from lcc.relevance import RelevanceCompactionRequest, compact_context
from lcc.relevance.sufficiency import verify_sufficiency


class _Judge:
    """Scores the general rule high and the payment exception low (the naive mistake)."""

    model = "fake"

    def evaluate(self, state, questions):
        answers = {}
        for qid in questions:
            bid = qid[len("keep_") :]
            text = next(b["text"] for b in state["blocks"] if b["id"] == bid)
            if "30 seconds" in text:
                score = 0.95
            elif "payment" in text.lower():
                score = 0.05
            else:
                score = 0.02
            answers[qid] = {"type": "noul", "noul": score}
        return {"answers": answers}


TEXT = (
    "Timeout is 30 seconds for every request in the standard fleet deployment.\n\n"
    "Unrelated office chatter about plants and coffee machines needing water daily.\n\n"
    "For payment requests, timeout is 60 seconds instead of the standard fleet value.\n"
)


def test_naive_drop_is_caught_and_restored():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT, question="What is the request timeout?", provider="jev", client=_Judge()
        )
    )
    assert "60 seconds" in result.compacted_text  # restored, not dropped
    assert result.report.blocks_restored >= 1
    assert result.report.sufficiency_checks >= 1
    assert any("sufficiency" in w for w in result.report.warnings)


def test_no_missing_evidence_stays_sufficient():
    verdict = verify_sufficiency(dropped_ids=[], kept_ids={"a"}, reasons={}, relationships={})
    assert verdict.sufficient and verdict.missing_evidence == []


def test_multiple_missing_blocks_all_restored():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT, question="What is the request timeout?", provider="jev", client=_Judge()
        )
    )
    assert result.report.sufficiency_failures >= 1 or result.report.blocks_restored >= 1


def test_restoration_budget_exceeded_warns():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT,
            question="What is the request timeout?",
            provider="jev",
            client=_Judge(),
            max_restorations=0,
        )
    )
    assert "60 seconds" not in result.compacted_text
    assert any("budget" in w for w in result.report.warnings)


def test_verifier_unavailable_fails_closed():
    verdict = verify_sufficiency(
        dropped_ids=["b1"], kept_ids={"a"}, reasons={"b1": "score_below_threshold"},
        relationships={"b1": "supports:evidence"}, confidence=0.0,
    )
    assert not verdict.sufficient
    assert verdict.critical_dropped_blocks == ["b1"]


def test_contradictory_evidence_is_flagged():
    verdict = verify_sufficiency(
        dropped_ids=["b"],
        kept_ids={"a"},
        reasons={"b": "score_below_threshold"},
        relationships={"b": "contradicts:a"},
    )
    assert not verdict.sufficient


def test_sufficiency_can_be_disabled():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT, question="What is the request timeout?", provider="jev",
            client=_Judge(), enable_sufficiency=False,
        )
    )
    assert "60 seconds" not in result.compacted_text
    assert result.report.sufficiency_checks == 0
