"""Verifier FAIL triggers bounded restoration with consistent accounting (P0.3).

Setup forces the interesting path: three graph-linked evidence blocks are
dropped by the selector, structural restoration can only afford one
(``max_restorations=1``), and the verifier FAILs. The verifier must then
restore one more linked block within the remaining budget — exactly once, with
no re-verify loop — and every accounting figure in the report must describe
the FINAL bytes, not the pre-verifier candidate.
"""

from lcc.relevance import RelevanceCompactionRequest, compact_context
from lcc.token_budget import count_tokens


def _pad(text, i):
    uniq = " ".join(["uniq" + str(i) + "w" + str(k) for k in range(6)])
    return text + " background padding " + str(i) + " " + uniq + "."


KEPT = _pad(
    "The reactor incident report summarizes alpha beta coolant status for the review board.",
    0,
)
DROPS = [
    _pad("alpha beta valve pressure exceeded safe limits during the incident window.", 1),
    _pad("alpha beta pump vibration rose sharply before the incident alarm.", 2),
    _pad("alpha beta coolant flow dropped below minimum during the incident.", 3),
]
NOISE = [
    _pad("Office chatter about plants and coffee machines with disjoint words.", 9),
    _pad("Parking permits renew in spring while repaving starts someday soon.", 10),
    _pad("Cafeteria soups rotate on weekdays with bread served alongside.", 11),
    _pad("A jacket waits in the meeting room beside the projector remote.", 12),
    _pad("Weekend football results surprised nobody around the office.", 13),
]

TEXT = "\n\n".join([KEPT] + DROPS + NOISE) + "\n"
QUESTION = "Summarize the incident."


class _HarshJudge:
    model = "fake"
    last_resolved_model = "fake-1"

    def evaluate(self, state, questions):
        if "context" in state:  # verifier call: evidence is missing
            return {
                "answers": {
                    "sufficient_to_answer": {"type": "noul", "noul": 0.1, "confidence": 0.9},
                    "contradiction_risk": {"type": "noul", "noul": 0.0, "confidence": 0.9},
                }
            }
        answers = {}
        for qid in questions:
            bid = qid[len("keep_"):]
            text = next(b["text"] for b in state["blocks"] if b["id"] == bid)
            score = 0.95 if "reactor incident report" in text else 0.1
            answers[qid] = {"type": "noul", "noul": score, "confidence": 0.9}
        return {"answers": answers}


def test_fail_restores_within_budget_and_marks_review():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT,
            question=QUESTION,
            provider="jev",
            client=_HarshJudge(),
            max_restorations=1,
            verifier_max_restorations=4,
            enable_semantic_verify=True,
        )
    )
    report = result.report
    assert report.semantic_verifier_decision == "FAIL"
    assert report.needs_review is True
    # Bounded: structural 1 + verifier 2 (the remaining linked drops), never
    # more than max_restorations + verifier_max_restorations total.
    assert report.blocks_restored == 3
    assert report.blocks_restored <= 1 + 4
    restored = [d for d in report.decisions if d.reason == "semantic_verifier_fail_restoration"]
    assert len(restored) == 2
    # FAIL never clears to PASS without re-verification (and we never re-verify).
    assert report.semantic_verifier_sufficient is False


def test_report_accounting_describes_final_bytes():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT,
            question=QUESTION,
            provider="jev",
            client=_HarshJudge(),
            max_restorations=1,
            verifier_max_restorations=4,
            enable_semantic_verify=True,
        )
    )
    report = result.report
    assert report.chars_after == len(result.compacted_text)
    assert report.tokens_after == count_tokens(result.compacted_text, "gpt-4.1").value
    assert report.blocks_dropped == sum(1 for d in report.decisions if d.decision == "drop")
    assert report.blocks_trimmed == sum(1 for d in report.decisions if d.decision == "trim")
    assert report.chars_before - report.chars_after == report.chars_removed
    # The verifier-restored evidence is present in the final output.
    assert "valve pressure" in result.compacted_text or "pump vibration" in result.compacted_text
    # Prefix before the first mutation is byte-identical to the input.
    offset = report.first_mutation_offset
    assert offset is not None
    assert result.compacted_text.startswith(TEXT[:offset])


def test_no_verifier_means_no_verifier_restoration():
    result = compact_context(
        RelevanceCompactionRequest(
            text=TEXT,
            question=QUESTION,
            provider="jev",
            client=_HarshJudge(),
            max_restorations=1,
            enable_semantic_verify=False,
        )
    )
    assert result.report.semantic_verifier_decision is None
    assert result.report.blocks_restored == 1  # structural only
    assert not any(
        d.reason == "semantic_verifier_fail_restoration" for d in result.report.decisions
    )
