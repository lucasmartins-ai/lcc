"""Safety model: relevance, necessity, dependency and risk are four different things.

A single "relevance score" must never become a proxy for every semantic property. A
block can be highly relevant yet safely droppable (redundant), or only moderately
relevant yet mandatory (a unique exception, a qualifier another block depends on, a
contradiction that changes the meaning of what is kept). This module gives that
distinction an explicit representation so policy decisions can be audited.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BlockAssessment:
    """One block judged on four independent axes (all 0.0-1.0)."""

    relevance: float = 0.0
    necessity: float = 0.0
    dependency_risk: float = 0.0
    semantic_risk: float = 0.0
    redundancy: float = 0.0
    decision: str = "KEEP"  # KEEP | TRIM | DROP
    confidence: float = 0.0
    reasons: tuple[str, ...] = field(default_factory=tuple)


def decide_assessment(
    *,
    relevance: float,
    necessity: float = 0.0,
    dependency_risk: float = 0.0,
    semantic_risk: float = 0.0,
    redundancy: float = 0.0,
    confidence: float = 1.0,
    threshold: float = 0.4,
    trim_threshold: float | None = None,
    reasons: tuple[str, ...] = (),
) -> BlockAssessment:
    """Conservative policy over the four axes.

    Rules (in order):
    1. Anything another retained block depends on, or that carries high semantic risk
       (negation, exception, contradiction, qualifier), is kept regardless of relevance.
    2. Unique necessity beats a low relevance score.
    3. High redundancy with low necessity may drop even at high relevance.
    4. Otherwise fall back to the relevance threshold band.
    5. Low confidence degrades one step toward safety (DROP->TRIM->KEEP).
    """
    trim_lo = threshold * 0.5 if trim_threshold is None else trim_threshold
    if dependency_risk >= 0.5 or semantic_risk >= 0.7 or necessity >= 0.7:
        decision = "KEEP"
    elif redundancy >= 0.7 and necessity <= 0.3:
        decision = "DROP"
    elif relevance >= threshold:
        decision = "KEEP"
    elif trim_threshold is not False and relevance >= trim_lo:
        decision = "TRIM"
    else:
        decision = "DROP"
    if confidence < 0.5 and decision == "DROP":
        decision = "TRIM"
    if confidence < 0.3 and decision in ("DROP", "TRIM"):
        decision = "KEEP"
    return BlockAssessment(
        relevance=relevance,
        necessity=necessity,
        dependency_risk=dependency_risk,
        semantic_risk=semantic_risk,
        redundancy=redundancy,
        decision=decision,
        confidence=confidence,
        reasons=reasons,
    )
