"""Semantic sufficiency verification: is the compiled context enough?

Relevance scoring answers "is this block worth keeping?". Sufficiency answers the
second, more important question: "after dropping these blocks, can the objective still
be solved safely from what remains?". The verifier never regenerates information — it
only names missing evidence so the caller can restore the dropped blocks that carried
it.

Deterministic today (graph links + protection reasons), Jev-assisted tomorrow through
the ``extra_missing`` hook. Fail-closed: when the verifier cannot run, the result is
``sufficient=False`` with ``confidence=0.0`` and the caller keeps more context.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SufficiencyResult:
    sufficient: bool
    missing_evidence: list[str] = field(default_factory=list)
    critical_dropped_blocks: list[str] = field(default_factory=list)
    confidence: float = 1.0
    reason: str = ""


def verify_sufficiency(
    *,
    dropped_ids: list[str],
    kept_ids: set[str],
    reasons: dict[str, str],
    relationships: dict[str, str],
    extra_missing: list[str] | None = None,
    confidence: float = 0.85,
) -> SufficiencyResult:
    """Check a candidate compiled context for missing evidence.

    A dropped block is critical when it is linked to kept content (any relationship) or
    when a deterministic protection reason kept it alive during scoring but the candidate
    decision dropped it anyway. ``extra_missing`` carries findings from an external
    (e.g. Jev) verifier in the same vocabulary.
    """
    critical: list[str] = []
    missing: list[str] = []
    for bid in dropped_ids:
        rel = relationships.get(bid)
        prot = reasons.get(bid)
        if rel is not None:
            critical.append(bid)
            missing.append(rel)
        elif prot is not None and prot not in ("no_lexical_overlap", "score_below_threshold"):
            critical.append(bid)
            missing.append(prot)
    if extra_missing:
        missing.extend(extra_missing)
    if critical or extra_missing:
        return SufficiencyResult(
            sufficient=False,
            missing_evidence=missing,
            critical_dropped_blocks=critical,
            confidence=confidence,
            reason="linked_evidence_dropped" if critical else "external_verifier_flagged",
        )
    return SufficiencyResult(sufficient=True, confidence=confidence, reason="no_links_severed")
