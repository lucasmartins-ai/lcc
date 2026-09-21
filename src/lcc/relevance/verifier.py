"""Independent semantic verifier: can the objective still be answered?

Separation of concerns (feedback §5-§6):

- Selector asks "what can I remove?" (block-level relevance).
- Structural sufficiency asks "was a dependency link severed?" (graph).
- This verifier asks "given ONLY the objective and the candidate context,
  is any information required to answer correctly no longer present?"

It never receives scores, decisions, or the dropped blocks — only the
candidate context the downstream LLM would actually see. One Jev call with
two narrow questions (sufficiency + contradiction risk) over that state.
Fail-closed: any transport/malformed problem returns sufficient=False with
confidence 0.0 so the caller flags REVIEW instead of trusting the output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lcc.relevance.jev import parse_noul_answer

_VERIFIER_MAX_CONTEXT_CHARS = 12000

#: Policy identity for the independent semantic verifier. Bumped only when the
#: decision mapping below changes; participates in the decision-cache identity
#: when semantic verification is enabled so a verifier change is a cache epoch.
VERIFIER_POLICY_VERSION = "semantic-verifier-1.0"

#: Confidence at or above which a low sufficiency score is treated as concrete
#: evidence of insufficiency (FAIL). Below it the verifier cannot affirm either
#: way, so doubt degrades to REVIEW, never to PASS and never to FAIL.
FAIL_CONFIDENCE_THRESHOLD = 0.7

#: Contradiction risk at or above which the candidate is flagged for review even
#: when it looks sufficient (both sides were kept — downstream must adjudicate).
CONTRADICTION_REVIEW_THRESHOLD = 0.7


class VerifierDecision(StrEnum):
    """Explicit tri-state outcome of independent semantic verification."""

    PASS = "PASS"  # context semantically sufficient for the objective
    REVIEW = "REVIEW"  # not enough confidence to affirm sufficiency either way
    FAIL = "FAIL"  # concrete evidence the context is semantically insufficient


@dataclass(frozen=True)
class SemanticVerificationResult:
    sufficient: bool
    missing_evidence: list[str] = field(default_factory=list)
    contradiction_risk: float = 0.0
    confidence: float = 1.0
    reason: str = ""
    model_resolved: str | None = None


@dataclass(frozen=True)
class VerificationContract:
    """Standardised verifier output (P0.2 contract).

    ``decision`` is one of PASS | REVIEW | FAIL. Any transport error, timeout,
    malformed response, schema violation or out-of-range value degrades to
    REVIEW (fail-closed): the caller must preserve context, never drop on a
    verifier failure.
    """

    decision: str  # PASS | REVIEW | FAIL
    confidence: float  # 0.0-1.0, validated
    missing_information: list[str] = field(default_factory=list)
    critical_risks: list[str] = field(default_factory=list)
    reason: str = ""
    model: str | None = None
    resolved_model: str | None = None

    @property
    def sufficient(self) -> bool:
        return self.decision == VerifierDecision.PASS.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "missing_information": list(self.missing_information),
            "critical_risks": list(self.critical_risks),
            "reason": self.reason,
            "model": self.model,
            "resolved_model": self.resolved_model,
        }


def _clip(text: str, limit: int = _VERIFIER_MAX_CONTEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit - 1100]
    tail = text[-1000:]
    return f"{head}\n…[lcc-verifier: {len(text) - len(head) - len(tail)} chars clipped]…\n{tail}"


def _review(
    *,
    reason: str,
    confidence: float = 0.0,
    missing: list[str] | None = None,
    risks: list[str] | None = None,
    client: Any = None,
) -> VerificationContract:
    """Fail-closed constructor: every verifier problem degrades to REVIEW."""
    return VerificationContract(
        decision=VerifierDecision.REVIEW.value,
        confidence=confidence,
        missing_information=list(missing or []),
        critical_risks=list(risks or []),
        reason=reason,
        model=getattr(client, "model", None),
        resolved_model=getattr(client, "last_resolved_model", None),
    )


def verify_semantic_contract(
    *,
    objective: str,
    candidate_context: str,
    client: Any,
) -> VerificationContract:
    """Run the independent verification question over objective + candidate only.

    Independence (P0.1): the verifier receives exactly ``objective`` and the
    candidate context the downstream LLM would see — never block scores,
    KEEP/DROP decisions, rankings, selector justifications, graph scores or
    selector confidence. It judges the result, not the reasoning that produced
    it.

    Fail-closed (P0/P0.4): transport errors, timeouts, malformed or invalid
    responses all yield REVIEW. REVIEW ("don't know") is never conflated with
    FAIL ("concrete evidence of insufficiency"): FAIL requires a low
    sufficiency score delivered with high confidence.
    """
    state = {"objective": objective, "context": _clip(candidate_context)}
    questions = {
        "sufficient_to_answer": {
            "type": "noul",
            "instructions": (
                "Judge the probability that the context in the state contains all "
                "information required to answer the objective correctly. Score high "
                "only when nothing required is missing; when unsure, score low."
            ),
            "criteria": {
                "true": "The context is sufficient to answer the objective correctly.",
                "false": "Required information is missing from the context.",
            },
        },
        "contradiction_risk": {
            "type": "noul",
            "instructions": (
                "Judge the probability that the context contains contradictory or "
                "superseded claims where keeping only one side would mislead the answer."
            ),
            "criteria": {
                "true": "Contradictory claims present a real answer risk.",
                "false": "No contradiction risk in the context.",
            },
        },
    }
    try:
        response = client.evaluate(state, questions)
    except Exception as exc:
        return _review(
            reason="verifier_unavailable_fail_closed",
            missing=[f"verifier_unavailable:{exc}"],
            client=client,
        )
    answers = response.get("answers") if isinstance(response, dict) else None
    if not isinstance(answers, dict):
        return _review(
            reason="verifier_malformed_response",
            missing=["verifier_malformed_response"],
            client=client,
        )
    suff_score, suff_conf, suff_problem = parse_noul_answer(
        answers.get("sufficient_to_answer")
    )
    contra_score, contra_conf, _ = parse_noul_answer(answers.get("contradiction_risk"))
    if suff_score is None:
        return _review(
            reason="verifier_unjudged_fail_closed",
            missing=[f"verifier_{suff_problem or 'missing_answer'}"],
            client=client,
        )
    # Schema validation (P0.2): confidence must be a number in [0, 1].
    # Out-of-range is an invalid response -> REVIEW, never trust. Missing
    # confidence is neutral (0.5): measured live, jev-1.13.0 omits confidence
    # systematically (not per-judgment doubt), so absence carries no signal and
    # maximal doubt would make PASS unreachable — a verifier that REVIEWs 100%
    # of passes is noise, not safety. Explicit low confidence still REVIEWs via
    # the bands below; explicit out-of-range still REVIEWs here.
    if suff_problem == "confidence_out_of_range":
        return _review(
            reason="verifier_invalid_confidence",
            missing=["verifier_invalid_confidence"],
            client=client,
        )
    confidence = 0.5 if suff_conf is None else suff_conf
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        return _review(
            reason="verifier_invalid_confidence",
            missing=["verifier_invalid_confidence"],
            client=client,
        )
    if not 0.0 <= confidence <= 1.0:
        return _review(
            reason="verifier_invalid_confidence",
            missing=["verifier_invalid_confidence"],
            client=client,
        )
    contra = 0.0
    if contra_score is not None:
        try:
            contra = float(contra_score)
        except (TypeError, ValueError):
            contra = 0.0
    if not 0.0 <= contra <= 1.0:
        contra = 0.0
    model = getattr(client, "model", None)
    resolved = getattr(client, "last_resolved_model", None)
    if suff_score < 0.5:
        missing = [f"verifier_sufficiency_score:{suff_score:.2f}"]
        if confidence >= FAIL_CONFIDENCE_THRESHOLD:
            return VerificationContract(
                decision=VerifierDecision.FAIL.value,
                confidence=confidence,
                missing_information=missing,
                critical_risks=[],
                reason="verifier_flagged_missing",
                model=model,
                resolved_model=resolved,
            )
        # Low score without confident judgment: doubt -> REVIEW, not FAIL.
        return VerificationContract(
            decision=VerifierDecision.REVIEW.value,
            confidence=confidence,
            missing_information=missing,
            critical_risks=[],
            reason="verifier_uncertain_review",
            model=model,
            resolved_model=resolved,
        )
    if contra >= CONTRADICTION_REVIEW_THRESHOLD:
        return VerificationContract(
            decision=VerifierDecision.REVIEW.value,
            confidence=confidence,
            missing_information=[],
            critical_risks=[f"high_contradiction_risk:{contra:.2f}"],
            reason="high_contradiction_risk",
            model=model,
            resolved_model=resolved,
        )
    if confidence < 0.5:
        # Looks sufficient but the judge is unsure of itself: cannot affirm.
        return VerificationContract(
            decision=VerifierDecision.REVIEW.value,
            confidence=confidence,
            missing_information=[],
            critical_risks=[],
            reason="verifier_low_confidence_review",
            model=model,
            resolved_model=resolved,
        )
    return VerificationContract(
        decision=VerifierDecision.PASS.value,
        confidence=confidence,
        missing_information=[],
        critical_risks=(
            [f"contradiction_risk:{contra:.2f}"] if contra >= 0.5 else []
        ),
        reason="verifier_judged_sufficient",
        model=model,
        resolved_model=resolved,
    )


def verify_semantic(
    *,
    objective: str,
    candidate_context: str,
    client: Any,
) -> SemanticVerificationResult:
    """Back-compat wrapper: boolean view over :func:`verify_semantic_contract`.

    ``sufficient`` is True only on PASS. REVIEW and FAIL both read as
    ``sufficient=False`` so existing fail-closed callers keep their behaviour;
    new code should use the contract directly to tell REVIEW from FAIL.
    """
    contract = verify_semantic_contract(
        objective=objective, candidate_context=candidate_context, client=client
    )
    risks = 0.0
    for risk in contract.critical_risks:
        try:
            risks = max(risks, float(risk.rsplit(":", 1)[-1]))
        except (ValueError, IndexError):
            continue
    return SemanticVerificationResult(
        sufficient=contract.sufficient,
        missing_evidence=list(contract.missing_information)
        or ([contract.reason] if contract.decision != VerifierDecision.PASS.value else []),
        contradiction_risk=risks,
        confidence=contract.confidence,
        reason=contract.reason,
        model_resolved=contract.resolved_model,
    )


__all__ = [
    "CONTRADICTION_REVIEW_THRESHOLD",
    "FAIL_CONFIDENCE_THRESHOLD",
    "VERIFIER_POLICY_VERSION",
    "SemanticVerificationResult",
    "VerificationContract",
    "VerifierDecision",
    "verify_semantic",
    "verify_semantic_contract",
]
