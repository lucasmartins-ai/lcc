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
from typing import Any

from lcc.relevance.jev import JevClient, JevError, parse_noul_answer

_VERIFIER_MAX_CONTEXT_CHARS = 12000


@dataclass(frozen=True)
class SemanticVerificationResult:
    sufficient: bool
    missing_evidence: list[str] = field(default_factory=list)
    contradiction_risk: float = 0.0
    confidence: float = 1.0
    reason: str = ""
    model_resolved: str | None = None


def _clip(text: str, limit: int = _VERIFIER_MAX_CONTEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit - 1100]
    tail = text[-1000:]
    return f"{head}\n…[lcc-verifier: {len(text) - len(head) - len(tail)} chars clipped]…\n{tail}"


def verify_semantic(
    *,
    objective: str,
    candidate_context: str,
    client: JevClient,
) -> SemanticVerificationResult:
    """Run the independent verification question over objective + candidate only."""
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
    except JevError as exc:
        return SemanticVerificationResult(
            sufficient=False,
            missing_evidence=[f"verifier_unavailable:{exc}"],
            confidence=0.0,
            reason="verifier_unavailable_fail_closed",
            model_resolved=getattr(client, "last_resolved_model", None),
        )
    answers = response.get("answers") if isinstance(response, dict) else None
    if not isinstance(answers, dict):
        return SemanticVerificationResult(
            sufficient=False,
            missing_evidence=["verifier_malformed_response"],
            confidence=0.0,
            reason="verifier_malformed_response",
            model_resolved=getattr(client, "last_resolved_model", None),
        )
    suff_score, suff_conf, suff_problem = parse_noul_answer(
        answers.get("sufficient_to_answer")
    )
    contra_score, _, _ = parse_noul_answer(answers.get("contradiction_risk"))
    resolved = getattr(client, "last_resolved_model", None)
    if suff_score is None:
        return SemanticVerificationResult(
            sufficient=False,
            missing_evidence=[f"verifier_{suff_problem or 'missing_answer'}"],
            contradiction_risk=float(contra_score or 0.0),
            confidence=0.0,
            reason="verifier_unjudged_fail_closed",
            model_resolved=resolved,
        )
    confidence = float(suff_conf) if suff_conf is not None else 0.5
    contra = float(contra_score) if contra_score is not None else 0.0
    sufficient = bool(suff_score >= 0.5)
    missing: list[str] = []
    if not sufficient:
        missing.append(f"verifier_sufficiency_score:{suff_score:.2f}")
    return SemanticVerificationResult(
        sufficient=sufficient,
        missing_evidence=missing,
        contradiction_risk=contra,
        confidence=confidence,
        reason="verifier_judged_sufficient" if sufficient else "verifier_flagged_missing",
        model_resolved=resolved,
    )


__all__ = ["SemanticVerificationResult", "verify_semantic"]
