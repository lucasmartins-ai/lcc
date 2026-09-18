"""Independent semantic verifier: objective + candidate only, fail-closed."""

from lcc.relevance.verifier import verify_semantic


class _SufficientJudge:
    model = "fake"
    last_resolved_model = "fake-1"

    def evaluate(self, state, questions):
        assert "context" in state and "objective" in state
        assert "sufficient_to_answer" in questions
        # must NOT receive scores/decisions/dropped blocks
        assert "scores" not in state and "decisions" not in state
        return {
            "answers": {
                "sufficient_to_answer": {"type": "noul", "noul": 0.9, "confidence": 0.8},
                "contradiction_risk": {"type": "noul", "noul": 0.1, "confidence": 0.9},
            }
        }


class _InsufficientJudge:
    model = "fake"
    last_resolved_model = "fake-1"

    def evaluate(self, state, questions):
        return {
            "answers": {
                "sufficient_to_answer": {"type": "noul", "noul": 0.2, "confidence": 0.85},
                "contradiction_risk": {"type": "noul", "noul": 0.1, "confidence": 0.9},
            }
        }


class _Boom:
    model = "fake"
    last_resolved_model = "fake-1"

    def evaluate(self, state, questions):
        from lcc.relevance.jev import JevRequestError

        raise JevRequestError("down")


def test_sufficient_passes():
    r = verify_semantic(objective="q", candidate_context="ctx", client=_SufficientJudge())
    assert r.sufficient and r.confidence == 0.8


def test_insufficient_flags_missing():
    r = verify_semantic(objective="q", candidate_context="ctx", client=_InsufficientJudge())
    assert not r.sufficient and r.missing_evidence


def test_verifier_fails_closed():
    r = verify_semantic(objective="q", candidate_context="ctx", client=_Boom())
    assert not r.sufficient and r.confidence == 0.0


def test_compact_review_flag_signal_only():
    from lcc.relevance import RelevanceCompactionRequest, compact_context

    class _Judge:
        model = "fake"
        last_resolved_model = "fake-1"

        def __init__(self):
            self.calls = 0

        def evaluate(self, state, questions):
            self.calls += 1
            if "context" in state:  # verifier call
                return {
                    "answers": {
                        "sufficient_to_answer": {
                            "type": "noul",
                            "noul": 0.1,
                            "confidence": 0.9,
                        },
                        "contradiction_risk": {
                            "type": "noul",
                            "noul": 0.0,
                            "confidence": 0.9,
                        },
                    }
                }
            # scoring call: keep everything except chatter
            answers = {}
            for qid in questions:
                bid = qid[len("keep_") :]
                text = next(b["text"] for b in state["blocks"] if b["id"] == bid)
                score = 0.05 if "chatter" in text.lower() else 0.95
                answers[qid] = {"type": "noul", "noul": score, "confidence": 0.9}
            return {"answers": answers}

    text = (
        "Conversion fell from 8.7% to 4.2% after the June release window.\n\n"
        + "Chatter about plants and coffee machines needing water daily ".ljust(200) + "\n\n"
        "The decline occurred after the mobile redesign shipped to all users.\n\n"
    )
    result = compact_context(
        RelevanceCompactionRequest(
            text=text,
            question="Why did conversion fall?",
            provider="jev",
            client=_Judge(),
            enable_semantic_verify=True,
        )
    )
    assert result.report.needs_review is True
    assert result.report.semantic_verifier_sufficient is False
    # signal-only: review never drops extra bytes by itself
    assert any("needs_review" in w for w in result.report.warnings)
