"""MSI Sprint 6: causal necessity harness (remove-and-replay ablation).

Answers "did this block affect the outcome?" instead of "does it look
relevant?". The harness freezes one deterministic offline baseline, removes
one unit (and selected pairs), replays verification, and labels each unit by
the observed outcome delta:

- ``NECESSARY``: removing it alone breaks the baseline (PASS -> FAIL).
- ``CONDITIONALLY_NECESSARY``: removing it alone is fine, but removing it
  together with a named companion breaks the baseline. The condition names
  the companion and the deciding invariant.
- ``REDUNDANT``: removing it (alone or with any tested pair) never breaks
  the baseline AND its meaningful content is fully covered by other units.
- ``UNNECESSARY``: removing it never breaks the baseline and it carries
  unique content (noise: contributes to no invariant, duplicated nowhere).
- ``PROTECTED``: never ablated (safety/policy units); label by declaration.
- ``UNKNOWN``: fail-closed. Baseline not PASS, or labels unstable across
  repeats, or an ablation crashes. Never force a category.

Research-only: labels are NOT consumed by any production path (no IR
``necessity`` wiring, no planner input). They become eligible for production
use only if a later sprint validates them. Deterministic layers only; the
opt-in semantic judge is excluded from the pilot (no network, no cost).

Correction rule (sprint prompt): a label that is unstable between runs is
``UNKNOWN``, never a forced category. A negative result (relevance tracks
necessity on the pilot) is publishable as-is, no HARKing.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lcc.router.verify import (
    EVALUATOR_VERSION,
    VerificationOutcome,
    VerificationSubject,
    run_verification,
)

HARNESS_VERSION = "ablate-1.0"
MODEL_VERSION = "deterministic-mechanical"

VALID_LABELS = (
    "NECESSARY",
    "UNNECESSARY",
    "CONDITIONALLY_NECESSARY",
    "REDUNDANT",
    "PROTECTED",
    "UNKNOWN",
)

# Tiny closed stopword set for the REDUNDANT token-coverage test. Fixed here
# (not configurable) so the pilot hash is stable across machines.
_STOPWORDS = frozenset(
    [
        "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for",
        "with", "is", "are", "was", "were", "be", "been", "it", "its",
        "this", "that", "these", "those", "as", "by", "from", "every",
        "reminder",
    ]
)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS
    )


@dataclass(frozen=True)
class AblationUnit:
    """One context block under test. ``content`` is verbatim context text."""

    id: str
    content: str
    protected: bool = False


@dataclass(frozen=True)
class AblationBaseline:
    """Frozen replayable baseline. ``make_subject`` rebuilds the verification
    subject from any subset of unit ids (deterministic, offline, no network).
    """

    task_id: str
    units: tuple[AblationUnit, ...]
    profile: str = "standard"
    seed: int = 0
    model: str = MODEL_VERSION
    evaluator: str = EVALUATOR_VERSION
    make_subject: Callable[[list[str]], VerificationSubject] | None = None

    def unit_ids(self) -> list[str]:
        return [u.id for u in self.units]

    def canonical(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "units": [
                {"id": u.id, "content": u.content, "protected": u.protected}
                for u in self.units
            ],
            "profile": self.profile,
            "seed": self.seed,
            "model": self.model,
            "evaluator": self.evaluator,
            "harness": HARNESS_VERSION,
        }

    def baseline_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.canonical(), sort_keys=True).encode()
        ).hexdigest()

    def run(self, selected_ids: list[str]) -> VerificationOutcome:
        assert self.make_subject is not None, "baseline needs make_subject"
        return run_verification(self.make_subject(list(selected_ids)), self.profile)


@dataclass(frozen=True)
class ExperimentRecord:
    """One recorded experiment: seed, baseline hash, model/version,
    evaluator, and the observed delta. Never silent on crash."""

    experiment_id: str
    removed_ids: list[str]
    outcome: str  # PASS | REVIEW | FAIL | CRASH
    deciding_check: str = ""
    failures: tuple[str, ...] = ()
    seed: int = 0
    baseline_hash: str = ""
    model: str = MODEL_VERSION
    evaluator: str = EVALUATOR_VERSION
    wall_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "removed_ids": list(self.removed_ids),
            "outcome": self.outcome,
            "deciding_check": self.deciding_check,
            "failures": list(self.failures),
            "seed": self.seed,
            "baseline_hash": self.baseline_hash,
            "model": self.model,
            "evaluator": self.evaluator,
            "wall_ms": round(self.wall_ms, 4),
        }


@dataclass(frozen=True)
class UnitLabel:
    unit_id: str
    label: str  # one of VALID_LABELS
    deciding_invariant: str = ""  # check id that decided, or "" when none
    condition: str = ""  # only for CONDITIONALLY_NECESSARY
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "unit_id": self.unit_id,
            "label": self.label,
            "deciding_invariant": self.deciding_invariant,
            "condition": self.condition,
            "reason": self.reason,
        }


@dataclass
class PilotReport:
    baseline_hash: str
    task_id: str
    seed: int
    labels: list[UnitLabel] = field(default_factory=list)
    experiments: list[ExperimentRecord] = field(default_factory=list)
    repeats: int = 2

    def digest(self) -> str:
        """Stable digest over labels + config (excludes wall-clock cost)."""
        payload = {
            "baseline_hash": self.baseline_hash,
            "task_id": self.task_id,
            "seed": self.seed,
            "labels": [lb.to_dict() for lb in self.labels],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def total_wall_ms(self) -> float:
        return round(sum(e.wall_ms for e in self.experiments), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness": HARNESS_VERSION,
            "task_id": self.task_id,
            "seed": self.seed,
            "baseline_hash": self.baseline_hash,
            "digest": self.digest(),
            "labels": [lb.to_dict() for lb in self.labels],
            "experiments": [e.to_dict() for e in self.experiments],
            "cost": {
                "experiments": len(self.experiments),
                "total_wall_ms": self.total_wall_ms(),
                "tokens_in": 0,
                "tokens_out": 0,
                "model_calls": 0,
            },
        }


def _run_one(
    baseline: AblationBaseline, exp_id: str, removed: list[str]
) -> ExperimentRecord:
    kept = [i for i in baseline.unit_ids() if i not in removed]
    start = time.perf_counter()
    try:
        outcome = baseline.run(kept)
        status, failures = outcome.status, tuple(outcome.failures)
    except Exception as exc:  # fail-closed: a crashing ablation is recorded
        status, failures = "CRASH", (f"ablation_crashed:{exc}",)
    wall_ms = (time.perf_counter() - start) * 1000.0
    deciding = ""
    if status != "PASS" and failures:
        deciding = failures[0].split(":", 1)[0]
    return ExperimentRecord(
        experiment_id=exp_id,
        removed_ids=list(removed),
        outcome=status,
        deciding_check=deciding,
        failures=failures,
        seed=baseline.seed,
        baseline_hash=baseline.baseline_hash(),
        model=baseline.model,
        evaluator=baseline.evaluator,
        wall_ms=wall_ms,
    )


def _label_once(
    baseline: AblationBaseline,
    base_outcome: VerificationOutcome,
    singles: dict[str, ExperimentRecord],
    pairs: dict[tuple[str, str], ExperimentRecord],
    token_sets: dict[str, frozenset[str]],
) -> dict[str, UnitLabel]:
    labels: dict[str, UnitLabel] = {}
    for unit in baseline.units:
        if unit.protected:
            labels[unit.id] = UnitLabel(
                unit_id=unit.id,
                label="PROTECTED",
                reason="protected unit: never ablated by declaration",
            )
            continue
        if base_outcome.status != "PASS":
            labels[unit.id] = UnitLabel(
                unit_id=unit.id,
                label="UNKNOWN",
                reason=f"baseline not PASS ({base_outcome.status}): no causal claim",
            )
            continue
        rec = singles[unit.id]
        if rec.outcome == "CRASH":
            labels[unit.id] = UnitLabel(
                unit_id=unit.id,
                label="UNKNOWN",
                deciding_invariant="ablation_crashed",
                reason="ablation crashed fail-closed",
            )
        elif rec.outcome == "FAIL":
            labels[unit.id] = UnitLabel(
                unit_id=unit.id,
                label="NECESSARY",
                deciding_invariant=rec.deciding_check,
                reason=f"single removal breaks baseline via {rec.deciding_check}",
            )
        elif rec.outcome == "REVIEW":
            labels[unit.id] = UnitLabel(
                unit_id=unit.id,
                label="CONDITIONALLY_NECESSARY",
                deciding_invariant=rec.deciding_check,
                condition=f"needed when {rec.deciding_check} is enforced",
                reason="single removal degrades to REVIEW",
            )
        else:  # single PASS: pair analysis decides conditional vs redundant/noise
            bad_pair: tuple[str, str] | None = None
            for (a, b), prec in pairs.items():
                if unit.id not in (a, b) or prec.outcome == "PASS":
                    continue
                if prec.outcome == "CRASH":
                    labels[unit.id] = UnitLabel(
                        unit_id=unit.id,
                        label="UNKNOWN",
                        deciding_invariant="ablation_crashed",
                        reason="pair ablation crashed fail-closed",
                    )
                    bad_pair = None
                    break
                bad_pair = (a, b)
                pair_rec = prec
                break
            if unit.id in labels:
                continue
            if bad_pair is not None:
                companion = bad_pair[1] if bad_pair[0] == unit.id else bad_pair[0]
                labels[unit.id] = UnitLabel(
                    unit_id=unit.id,
                    label="CONDITIONALLY_NECESSARY",
                    deciding_invariant=pair_rec.deciding_check,
                    condition=(
                        f"requires {companion} present "
                        f"(jointly cover {pair_rec.deciding_check})"
                    ),
                    reason=f"pair removal with {companion} breaks baseline",
                )
            else:
                own, rest = token_sets[unit.id], frozenset().union(
                    *(ts for uid, ts in token_sets.items() if uid != unit.id)
                ) or frozenset()
                if own and own <= rest:
                    labels[unit.id] = UnitLabel(
                        unit_id=unit.id,
                        label="REDUNDANT",
                        reason="content fully covered by other units, never decisive",
                    )
                else:
                    labels[unit.id] = UnitLabel(
                        unit_id=unit.id,
                        label="UNNECESSARY",
                        reason="unique content that no invariant requires",
                    )
    return labels


def run_pilot(baseline: AblationBaseline, repeats: int = 2) -> PilotReport:
    """Remove -> replay -> evaluate over every unit, plus pairs of units
    whose single removal passes. Repeats the whole sweep; a unit whose label
    disagrees across repeats is UNKNOWN (never forced)."""
    report = PilotReport(
        baseline_hash=baseline.baseline_hash(),
        task_id=baseline.task_id,
        seed=baseline.seed,
        repeats=repeats,
    )
    token_sets = {u.id: _tokens(u.content) for u in baseline.units}
    start = time.perf_counter()
    try:
        base = baseline.run(baseline.unit_ids())
    except Exception as exc:  # fail-closed: broken baseline -> everything UNKNOWN
        base = VerificationOutcome(
            status="CRASH",
            confidence=0.0,
            failures=[f"baseline_crashed:ablation_crashed:{exc}"],
            recommended_action="ESCALATE",
        )
    base_wall_ms = (time.perf_counter() - start) * 1000.0
    base_failures = tuple(base.failures)
    report.experiments.append(
        ExperimentRecord(
            experiment_id="baseline",
            removed_ids=[],
            outcome=base.status,
            deciding_check=base_failures[0].split(":", 1)[0] if base_failures else "",
            failures=base_failures,
            seed=baseline.seed,
            baseline_hash=baseline.baseline_hash(),
            model=baseline.model,
            evaluator=baseline.evaluator,
            wall_ms=base_wall_ms,
        )
    )
    per_repeat: list[dict[str, UnitLabel]] = []
    for rep in range(max(repeats, 1)):
        singles: dict[str, ExperimentRecord] = {}
        for u in baseline.units:
            if u.protected:
                continue
            rec = _run_one(baseline, f"single-{u.id}-r{rep}", [u.id])
            report.experiments.append(rec)
            singles[u.id] = rec
        passed = [uid for uid, r in singles.items() if r.outcome == "PASS"]
        pairs: dict[tuple[str, str], ExperimentRecord] = {}
        for i, a in enumerate(passed):
            for b in passed[i + 1 :]:
                rec = _run_one(baseline, f"pair-{a}-{b}-r{rep}", [a, b])
                report.experiments.append(rec)
                pairs[(a, b)] = rec
        per_repeat.append(_label_once(baseline, base, singles, pairs, token_sets))
    final: list[UnitLabel] = []
    for unit in baseline.units:
        seen = {per_repeat[r][unit.id].label for r in range(len(per_repeat))}
        if len(seen) > 1:
            final.append(
                UnitLabel(
                    unit_id=unit.id,
                    label="UNKNOWN",
                    reason=f"label unstable across repeats ({sorted(seen)}): not forced",
                )
            )
        else:
            final.append(per_repeat[0][unit.id])
    report.labels = final
    return report
