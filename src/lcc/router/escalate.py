"""MSI Sprint 5: bounded execute -> verify -> restore -> retry -> escalate.

Owns the escalation half of the sprint-4 plan: an ``InferencePlan`` (with
``escalation_policy`` budgets) drives a linear, fully counted chain. Every
transition emits a decision event (WHY) and every execution emits one
Inference Receipt v0 (``inference-receipt/0.1``) carrying the whole chain.

Chain (no unbounded loops; single re-verify per stage, sprint-3 rule):

1. ``routed``: plan engine/route recorded.
2. execute(0) -> verify. PASS -> receipt, outcome PASS.
3. FAIL/REVIEW with RESTORE_CONTEXT and restorations left -> ``restored``
   event, execute again, single re-verify (no further restore).
4. Still not PASS and action retry-like and retries left -> plan switch
   (INCREASE_REASONING / SWITCH_MODEL / ADD_TOOL recorded as a second
   ``routed`` event), ``retries`` counted, execute again, re-verify.
5. Still not PASS -> ``escalated`` (``escalate_to``) or ABORT. Retry beyond
   the maximum lands here: never silent, always counted.

Library-only (like the sprint-4 planner): no CLI, no network, no judge in
the default path. A transition without a recorded reason is a bug: the
machine cannot produce one (events are constructed with their reason).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from lcc.router.plan import InferencePlan
from lcc.router.verify import VerificationSubject, run_verification

RECEIPT_SCHEMA_VERSION = "inference-receipt/0.1"
ESCALATION_POLICY_VERSION = "escalation-1.0"

VALID_EVENTS = ("dropped", "restored", "routed", "failed", "escalated")
RETRYABLE_ACTIONS = ("RETRY", "INCREASE_REASONING", "SWITCH_MODEL", "ADD_TOOL")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class DecisionEvent:
    """One WHY entry. ``event`` uses the receipt's closed vocabulary."""

    event: str  # dropped | restored | routed | failed | escalated
    reason: str
    at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, str]:
        return {"event": self.event, "reason": self.reason, "at": self.at}


@dataclass(frozen=True)
class ReceiptVersions:
    compiler: str = "unknown"
    policy: str = "planner-1.0"
    model: str = "unset"
    schema: str = RECEIPT_SCHEMA_VERSION
    dataset: str = "n/a"
    evaluator: str = "verify-1.0"

    def to_dict(self) -> dict[str, str]:
        return {
            "compiler": self.compiler,
            "policy": self.policy,
            "model": self.model,
            "schema": self.schema,
            "dataset": self.dataset,
            "evaluator": self.evaluator,
        }


@dataclass(frozen=True)
class ExecutionReceipt:
    """Audit record of one execution. ``to_spec_dict`` is schema-valid."""

    receipt_id: str
    task_id: str
    selected_units: list[str] = field(default_factory=list)
    omitted_units: list[dict[str, str]] = field(default_factory=list)
    model_class: str = "local_small"
    reasoning_budget: str = "low"
    tools_used: list[str] = field(default_factory=list)
    verification_profile: str = "strict"
    verification_result: str = "PASS"
    restored: list[str] = field(default_factory=list)
    retries: int = 0
    escalations: list[str] = field(default_factory=list)
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    versions: ReceiptVersions = field(default_factory=ReceiptVersions)
    started_at: str = field(default_factory=_now)
    finished_at: str = field(default_factory=_now)
    decision_events: list[DecisionEvent] = field(default_factory=list)
    result: str = ""
    evaluation: str = "PASS"  # PASS | REVIEW | FAIL

    def to_spec_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "task_id": self.task_id,
            "selected_units": list(self.selected_units),
            "omitted_units": [dict(o) for o in self.omitted_units],
            "model": {"class": self.model_class, "reasoning_budget": self.reasoning_budget},
            "tools_used": list(self.tools_used),
            "verification": {
                "profile": self.verification_profile,
                "result": self.verification_result,
            },
            "restorations": {
                "restored": list(self.restored),
                "retries": self.retries,
                "escalations": list(self.escalations),
            },
            "cost": {
                "latency_ms": self.latency_ms,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "cost_usd": self.cost_usd,
            },
            "versions": self.versions.to_dict(),
            "timestamps": {"started_at": self.started_at, "finished_at": self.finished_at},
            "decision_events": [e.to_dict() for e in self.decision_events],
            "outcome": {"result": self.result, "evaluation": self.evaluation},
        }


@dataclass
class ExecutionRun:
    """Machine output: receipt + attempts count (budgets consumed, auditable)."""

    receipt: ExecutionReceipt
    attempts: int


def _switch_model(plan: InferencePlan, action: str) -> InferencePlan:
    """One bounded plan switch; returns the (possibly unchanged) plan."""
    if action == "INCREASE_REASONING":
        order = ("none", "low", "medium", "high")
        nxt = order[min(order.index(plan.reasoning_budget) + 1, 3)]
        return InferencePlan(
            model_class=plan.model_class,
            reasoning_budget=nxt,
            context_profile=plan.context_profile,
            verification_profile=plan.verification_profile,
            fallbacks=list(plan.fallbacks),
            escalation_policy=plan.escalation_policy,
            tools=list(plan.tools),
            route=plan.route,
            reasons=[*plan.reasons, f"escalation_switch:{action}"],
            policy_version=plan.policy_version,
            engine=plan.engine,
        )
    if action == "SWITCH_MODEL":
        order = ("local_tiny", "local_small", "fast_hosted", "frontier")
        nxt = order[min(order.index(plan.model_class) + 1, 3)]
        return InferencePlan(
            model_class=nxt,
            reasoning_budget=plan.reasoning_budget,
            context_profile=plan.context_profile,
            verification_profile=plan.verification_profile,
            fallbacks=list(plan.fallbacks),
            escalation_policy=plan.escalation_policy,
            tools=list(plan.tools),
            route=plan.route,
            reasons=[*plan.reasons, f"escalation_switch:{action}"],
            policy_version=plan.policy_version,
            engine=plan.engine,
        )
    return plan  # RETRY / ADD_TOOL keep the plan; the retry itself is the action


def run_execution(
    *,
    task_id: str,
    plan: InferencePlan,
    execute: Callable[[int], VerificationSubject],
    restore: Callable[[list[str]], list[str]] | None = None,
    receipt_id: str = "receipt-1",
    selected_units: list[str] | None = None,
    omitted_units: list[dict[str, str]] | None = None,
    result_text: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    versions: ReceiptVersions | None = None,
    clock: Callable[[], str] | None = None,
) -> ExecutionRun:
    """Drive the bounded chain; return the receipt (never silent on failure)."""
    now = clock or _now
    started = now()
    events: list[DecisionEvent] = [
        DecisionEvent(
            event="routed",
            reason=f"engine={plan.engine} route={plan.route} "
            f"model={plan.model_class} reasons={';'.join(plan.reasons)}",
            at=started,
        )
    ]
    policy = plan.escalation_policy
    restored: list[str] = []
    retries = 0
    escalations: list[str] = []
    current = plan
    attempt = 0

    subject = execute(attempt)
    outcome = run_verification(subject, current.verification_profile)
    if outcome.status != "PASS":
        events.append(
            DecisionEvent(
                event="failed",
                reason=f"attempt={attempt} status={outcome.status} "
                f"action={outcome.recommended_action} failures={';'.join(outcome.failures)}",
                at=now(),
            )
        )

    # Stage 1: bounded restore (own budget, single re-verify).
    if outcome.status != "PASS" and outcome.recommended_action == "RESTORE_CONTEXT":
        budget = policy.max_restorations
        if budget > 0:
            restored = list((restore or (lambda _fails: []))(list(outcome.failures)))
            events.append(
                DecisionEvent(
                    event="restored",
                    reason=f"restored={restored} budget={budget}",
                    at=now(),
                )
            )
            attempt += 1
            subject = execute(attempt)
            outcome = run_verification(subject, current.verification_profile)
            if outcome.status != "PASS":
                events.append(
                    DecisionEvent(
                        event="failed",
                        reason=f"attempt={attempt} status={outcome.status} "
                        f"action={outcome.recommended_action} "
                        f"failures={';'.join(outcome.failures)}",
                        at=now(),
                    )
                )

    # Stage 2: bounded retry with at most one plan switch per retry.
    while (
        outcome.status != "PASS"
        and outcome.recommended_action in RETRYABLE_ACTIONS
        and retries < policy.max_retries
    ):
        action = outcome.recommended_action
        current = _switch_model(current, action)
        retries += 1
        events.append(
            DecisionEvent(
                event="routed",
                reason=f"retry={retries}/{policy.max_retries} action={action} "
                f"model={current.model_class} reasoning={current.reasoning_budget}",
                at=now(),
            )
        )
        attempt += 1
        subject = execute(attempt)
        outcome = run_verification(subject, current.verification_profile)
        if outcome.status != "PASS":
            events.append(
                DecisionEvent(
                    event="failed",
                    reason=f"attempt={attempt} status={outcome.status} "
                    f"action={outcome.recommended_action} "
                    f"failures={';'.join(outcome.failures)}",
                    at=now(),
                )
            )

    # Stage 3: terminal. Retry exhausted or terminal action -> ESCALATE/ABORT.
    if outcome.status != "PASS":
        if outcome.recommended_action == "ABORT" or policy.escalate_to == "abort":
            escalations = ["abort"]
            evaluation = "FAIL"
        else:
            escalations = [policy.escalate_to]
            evaluation = "REVIEW" if outcome.status == "REVIEW" else "FAIL"
        events.append(
            DecisionEvent(
                event="escalated",
                reason=f"terminal status={outcome.status} "
                f"action={outcome.recommended_action} "
                f"retries={retries}/{policy.max_retries} "
                f"restored={len(restored)} target={escalations[0]}",
                at=now(),
            )
        )
    else:
        evaluation = "PASS"

    finished = now()
    receipt = ExecutionReceipt(
        receipt_id=receipt_id,
        task_id=task_id,
        selected_units=list(selected_units or []),
        omitted_units=[dict(o) for o in (omitted_units or [])],
        model_class=current.model_class,
        reasoning_budget=current.reasoning_budget,
        tools_used=list(subject.tools_used),
        verification_profile=current.verification_profile,
        verification_result=outcome.status,
        restored=restored,
        retries=retries,
        escalations=escalations,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        versions=versions or ReceiptVersions(model=current.model_class),
        started_at=started,
        finished_at=finished,
        decision_events=events,
        result=result_text or outcome.status,
        evaluation=evaluation,
    )
    return ExecutionRun(receipt=receipt, attempts=attempt + 1)
