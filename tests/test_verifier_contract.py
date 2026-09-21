"""Verifier output contract (P0.2) + REVIEW/FAIL separation (P0.4) + independence (P0.1)."""

from lcc.relevance.verifier import (
    VERIFIER_POLICY_VERSION,
    VerificationContract,
    VerifierDecision,
    verify_semantic,
    verify_semantic_contract,
)


def _judge(suff, conf, contra=0.0, contra_conf=0.9, model="fake-judge"):
    class _J:
        last_resolved_model = "fake-judge-1"

        def __init__(self):
            self.model = model
            self.seen_states = []

        def evaluate(self, state, questions):
            self.seen_states.append(state)
            return {
                "answers": {
                    "sufficient_to_answer": {
                        "type": "noul",
                        "noul": suff,
                        "confidence": conf,
                    },
                    "contradiction_risk": {
                        "type": "noul",
                        "noul": contra,
                        "confidence": contra_conf,
                    },
                }
            }

    return _J()


def test_contract_keys_match_spec():
    contract = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_judge(0.9, 0.8)
    )
    payload = contract.to_dict()
    assert set(payload) == {
        "decision",
        "confidence",
        "missing_information",
        "critical_risks",
        "reason",
        "model",
        "resolved_model",
    }
    assert payload["decision"] == "PASS"
    assert payload["model"] == "fake-judge"
    assert payload["resolved_model"] == "fake-judge-1"


def test_confident_insufficiency_is_fail():
    contract = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_judge(0.2, 0.85)
    )
    assert contract.decision == VerifierDecision.FAIL.value
    assert not contract.sufficient
    assert contract.missing_information
    assert 0.0 <= contract.confidence <= 1.0


def test_doubtful_insufficiency_is_review_not_fail():
    # Low score with low confidence: "don't know", not "wrong".
    contract = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_judge(0.2, 0.4)
    )
    assert contract.decision == VerifierDecision.REVIEW.value
    assert not contract.sufficient


def test_low_confidence_sufficiency_is_review():
    contract = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_judge(0.9, 0.3)
    )
    assert contract.decision == VerifierDecision.REVIEW.value


def test_high_contradiction_is_review_with_risk():
    contract = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_judge(0.9, 0.8, contra=0.85)
    )
    assert contract.decision == VerifierDecision.REVIEW.value
    assert contract.critical_risks


class _Boom:
    model = "fake"
    last_resolved_model = "fake-1"

    def evaluate(self, state, questions):
        raise RuntimeError("transport down")


class _Garbage:
    model = "fake"
    last_resolved_model = "fake-1"

    def evaluate(self, state, questions):
        return {"answers": "not-a-dict"}


class _OutOfRange:
    model = "fake"
    last_resolved_model = "fake-1"

    def evaluate(self, state, questions):
        return {
            "answers": {
                "sufficient_to_answer": {
                    "type": "noul",
                    "noul": 0.9,
                    "confidence": 42.0,  # invalid: outside [0, 1]
                },
                "contradiction_risk": {"type": "noul", "noul": 0.0, "confidence": 0.9},
            }
        }


def test_transport_error_is_review():
    contract = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_Boom()
    )
    assert contract.decision == VerifierDecision.REVIEW.value
    assert contract.confidence == 0.0
    assert not contract.sufficient


def test_malformed_response_is_review():
    contract = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_Garbage()
    )
    assert contract.decision == VerifierDecision.REVIEW.value
    assert contract.confidence == 0.0


def test_out_of_range_confidence_is_review():
    contract = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_OutOfRange()
    )
    assert contract.decision == VerifierDecision.REVIEW.value


def test_verifier_receives_only_objective_and_candidate():
    client = _judge(0.9, 0.8)
    verify_semantic_contract(
        objective="the objective", candidate_context="the candidate", client=client
    )
    assert len(client.seen_states) == 1
    state = client.seen_states[0]
    # Independence: exactly these two keys — no scores, decisions, rankings,
    # justifications, graph scores or selector confidence.
    assert set(state) == {"objective", "context"}
    assert state["objective"] == "the objective"
    assert "candidate" in state["context"]
    for forbidden in (
        "scores",
        "decisions",
        "ranking",
        "justification",
        "graph",
        "confidence",
        "dropped",
    ):
        assert forbidden not in state


def test_back_compat_wrapper_preserves_fail_closed_booleans():
    assert verify_semantic(
        objective="q", candidate_context="ctx", client=_judge(0.9, 0.8)
    ).sufficient
    assert not verify_semantic(
        objective="q", candidate_context="ctx", client=_judge(0.2, 0.85)
    ).sufficient
    # REVIEW also reads as not-sufficient for legacy callers.
    assert not verify_semantic(
        objective="q", candidate_context="ctx", client=_judge(0.2, 0.4)
    ).sufficient
    assert not verify_semantic(
        objective="q", candidate_context="ctx", client=_Boom()
    ).sufficient


class _NoConfidence:
    model = "fake"
    last_resolved_model = "fake-1"

    def evaluate(self, state, questions):
        # Mirrors live jev-1.13.0: score without a confidence field.
        return {
            "answers": {
                "sufficient_to_answer": {"type": "noul", "noul": 0.9},
                "contradiction_risk": {"type": "noul", "noul": 0.0},
            }
        }


def test_missing_confidence_is_neutral_not_maximal_doubt():
    # Live calibration: the backend omits confidence systematically, so absence
    # is neutral (0.5) — a sufficient candidate can still PASS, an insufficient
    # one still REVIEWs (0.5 < FAIL threshold). Out-of-range stays REVIEW.
    sufficient = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_NoConfidence()
    )
    assert sufficient.decision == VerifierDecision.PASS.value

    class _InsufficientNoConf(_NoConfidence):
        def evaluate(self, state, questions):
            return {
                "answers": {
                    "sufficient_to_answer": {"type": "noul", "noul": 0.2},
                    "contradiction_risk": {"type": "noul", "noul": 0.0},
                }
            }

    insufficient = verify_semantic_contract(
        objective="q", candidate_context="ctx", client=_InsufficientNoConf()
    )
    assert insufficient.decision == VerifierDecision.REVIEW.value


def test_policy_version_is_pinned():
    assert VERIFIER_POLICY_VERSION == "semantic-verifier-1.0"
    assert isinstance(VerificationContract(decision="PASS", confidence=1.0).to_dict(), dict)
