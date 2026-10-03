"""MSI Sprint 8: minimal Python API (offline, deterministic, no key).

One-call path for the 5-minute quickstart::

    from lcc.msi import compile

    result = compile("reduce mobile booking friction", open("dossier.md").read())
    print(result.context)            # compacted text, ready for a downstream model
    print(result.receipt.to_spec_dict())  # audit chain (plan + sufficiency)
    print(result.sufficiency)        # {"checks": n, "failures": n, "restored": n}

Design (YAGNI, ponytail full):

- Deterministic planner (``planner-1.0``) + mechanical compaction + local
  sufficiency restoration. No network, no key, no model call, no new deps.
- Semantic judgment (Jev/Laya) and full verification stay opt-in via the
  existing ``lcc.relevance`` / ``lcc.router`` APIs; this wrapper never hides
  them, it just defaults to the offline path.
- Library-only logging: ``logging.getLogger("lcc.msi")`` at DEBUG, no
  handlers configured here (callers own logging config).

Evidence classes: CURRENT (code), data REAL (caller-supplied text).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger("lcc.msi")

MSI_API_VERSION = "msi-api-1.0"


def _task_id_for(task: str) -> str:
    digest = hashlib.sha256(task.encode("utf-8")).hexdigest()[:12]
    return f"msi-{digest}"


@dataclass(frozen=True)
class MsiResult:
    """Return value of :func:`compile`."""

    context: str
    plan: Any
    receipt: Any
    sufficiency: dict[str, Any]
    provider_used: str
    degraded: bool

    def to_dict(self) -> dict[str, Any]:
        if hasattr(self.plan, "to_spec_dict"):
            plan_d = self.plan.to_spec_dict()
        elif hasattr(self.plan, "to_dict"):
            plan_d = self.plan.to_dict()
        else:
            plan_d = dict(self.plan)
        return {
            "api_version": MSI_API_VERSION,
            "context": self.context,
            "plan": plan_d,
            "receipt": self.receipt.to_spec_dict(),
            "sufficiency": dict(self.sufficiency),
            "provider_used": self.provider_used,
            "degraded": self.degraded,
        }


def compile(
    task: str,
    context: str,
    *,
    task_id: str | None = None,
    max_restorations: int = 8,
) -> MsiResult:
    """Compact ``context`` for ``task`` and return context + receipt + sufficiency.

    Offline and deterministic: mechanical scoring, deterministic protection on,
    sufficiency restoration bounded by ``max_restorations``. Same inputs give
    byte-identical ``context`` (receipt timestamps excepted).

    Args:
        task: objective the context must serve (also the planner input).
        context: raw context text (UTF-8 string, not a path).
        task_id: stable id linking plan and receipt; derived from ``task``
            when omitted (``msi-<sha12>``).
        max_restorations: structural restoration budget (sprint-3 rule).

    Returns:
        MsiResult with compacted ``context``, the deterministic ``plan``,
        the spec-valid ``receipt`` and a ``sufficiency`` summary dict.
    """
    from lcc import __version__ as compiler_version
    from lcc.relevance import RelevanceCompactionRequest, compact_context
    from lcc.router.escalate import DecisionEvent, ExecutionReceipt, ReceiptVersions
    from lcc.router.plan import DeterministicPlanner, PlannerInput

    if not task or not task.strip():
        raise ValueError("compile() needs a non-empty task; e.g. task='summarize the outage'")
    if not isinstance(context, str) or not context.strip():
        raise ValueError("compile() needs non-empty context text; pass the dossier string itself")
    if max_restorations < 0:
        raise ValueError("max_restorations must be >= 0")

    tid = task_id or _task_id_for(task)
    LOGGER.debug("msi.compile task_id=%s chars=%d", tid, len(context))

    plan = DeterministicPlanner().plan(PlannerInput(task_id=tid, risk_level="low"))
    comp = compact_context(
        RelevanceCompactionRequest(
            text=context,
            question=task,
            provider="mechanical",
            max_restorations=max_restorations,
            source_origin="msi.compile",
        )
    )
    report = comp.report
    kept = [d.id for d in report.decisions if d.decision in ("keep", "trim")]
    omitted = [
        {"id": d.id, "rationale": d.reason or "dropped"}
        for d in report.decisions
        if d.decision == "drop"
    ]
    verification_result = "PASS" if report.sufficiency_failures == 0 else "REVIEW"
    sufficiency = {
        "checks": report.sufficiency_checks,
        "failures": report.sufficiency_failures,
        "restored": report.blocks_restored,
        "result": verification_result,
    }
    receipt = ExecutionReceipt(
        receipt_id=f"{tid}-r1",
        task_id=tid,
        selected_units=kept,
        omitted_units=omitted,
        model_class=plan.model_class,
        reasoning_budget=plan.reasoning_budget,
        tools_used=list(plan.tools),
        verification_profile="standard",
        verification_result=verification_result,
        restored=(
            [
                d.id
                for d in report.decisions
                if d.decision == "keep" and "restor" in (d.reason or "")
            ][:max_restorations]
            if report.blocks_restored
            else []
        ),
        retries=0,
        escalations=[],
        tokens_in=report.tokens_before,
        tokens_out=report.tokens_after,
        cost_usd=0.0,
        versions=ReceiptVersions(
            compiler=f"lcc-{compiler_version}",
            policy=plan.policy_version,
            model=plan.model_class,
        ),
        decision_events=[
            DecisionEvent(event="routed", reason=f"msi.compile:{plan.engine}:{plan.route}"),
            DecisionEvent(
                event="dropped",
                reason=f"mechanical:{report.blocks_dropped}-dropped:{report.blocks_trimmed}-trimmed",
            ),
        ],
        result="",
        evaluation="PASS" if verification_result == "PASS" else "REVIEW",
    )
    return MsiResult(
        context=comp.compacted_text,
        plan=plan,
        receipt=receipt,
        sufficiency=sufficiency,
        provider_used=report.provider_used,
        degraded=report.degraded,
    )
