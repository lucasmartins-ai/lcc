"""MSI Sprint 4: auditable inference planner (plans, never executes).

Maps (Task Contract risk/type, TaskFeatures) to a spec-valid Inference Plan
(`inference-plan/0.1`). Three pluggable engines behind one interface:

- ``deterministic``: ports ``choose_route`` semantics + fail-closed risk overlay.
- ``jev-adapter``: triage gate ``(decision, confidence, escalate_risk)`` from
  cognitive-triage-benchmark (``escalate OR risk>=0.60 OR conf<0.65`` as
  defaults, not truth); escalated inputs force frontier+strict+ESCALATE,
  otherwise delegates to the deterministic baseline.
- ``rules``: static risk table (no feature inspection beyond tools).

Small-local-model engine is intentionally NOT implemented (YAGNI stub, see
``docs/lcc/inference-planning.md``). No provider calls here by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from lcc.router.config import PolicyConfig
from lcc.router.policy import choose_route
from lcc.router.schemas import RouteDecision, TaskFeatures

POLICY_VERSION = "planner-1.0"
SCHEMA_VERSION = "inference-plan/0.1"

# Triage-gate defaults inherited from cognitive-triage-benchmark
# scripts/integrate_agy_results.py:151 (SYNTHETIC-calibrated, defaults only).
JEV_DEFAULT_CONF_THRESHOLD = 0.65
JEV_DEFAULT_RISK_THRESHOLD = 0.60

CHEAP_MODELS = ("local_tiny", "local_small")
HIGH_RISKS = ("high", "unknown")

VALID_RISKS = ("low", "medium", "high", "unknown")
VALID_MODELS = ("local_tiny", "local_small", "fast_hosted", "frontier")
VALID_REASONING = ("none", "low", "medium", "high")
VALID_CONTEXT = ("full", "compiled", "minimal")
VALID_VERIFICATION = ("strict", "standard", "light")
VALID_TRIGGERS = ("VERIFY_FAIL", "TIMEOUT", "LOW_CONF")
VALID_ACTIONS = (
    "RESTORE_CONTEXT",
    "RETRY",
    "INCREASE_REASONING",
    "SWITCH_MODEL",
    "ADD_TOOL",
    "ESCALATE",
    "ABORT",
)
VALID_ESCALATE_TO = ("human", "frontier", "abort")


@dataclass(frozen=True)
class Fallback:
    trigger: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return {"trigger": self.trigger, "action": self.action}


@dataclass(frozen=True)
class EscalationPolicy:
    max_retries: int = 2
    max_restorations: int = 4  # matches verifier budget, ADR-0018
    escalate_to: str = "frontier"

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_retries": self.max_retries,
            "max_restorations": self.max_restorations,
            "escalate_to": self.escalate_to,
        }


@dataclass(frozen=True)
class JevTriage:
    """Pluggable triage signal. Never calls a provider; test-supplied only."""

    decision: str  # approve | escalate | reject (only "escalate" forces escalation)
    confidence: float = 1.0
    escalate_risk: float = 0.0


@dataclass(frozen=True)
class PlannerInput:
    task_id: str
    risk_level: str  # low | medium | high | unknown (contract)
    task_type: str = "other"
    features: TaskFeatures | None = None
    allowed_tools: list[str] = field(default_factory=list)
    triage: JevTriage | None = None  # read only by jev-adapter


@dataclass(frozen=True)
class InferencePlan:
    """Audit-carrying plan. ``to_spec_dict`` strips audit for schema validation."""

    model_class: str
    reasoning_budget: str
    context_profile: str
    verification_profile: str
    fallbacks: list[Fallback] = field(default_factory=list)
    escalation_policy: EscalationPolicy = field(default_factory=EscalationPolicy)
    tools: list[str] = field(default_factory=list)
    # audit envelope (NOT part of spec v0.1; receipt links it from sprint 5 on)
    route: str = ""
    reasons: list[str] = field(default_factory=list)
    policy_version: str = POLICY_VERSION
    engine: str = "deterministic"

    def to_spec_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_class": self.model_class,
            "reasoning_budget": self.reasoning_budget,
            "tools": list(self.tools),
            "context_profile": self.context_profile,
            "verification_profile": self.verification_profile,
            "fallbacks": [fb.to_dict() for fb in self.fallbacks],
            "escalation_policy": self.escalation_policy.to_dict(),
        }


class PlannerEngine(Protocol):
    engine_name: str
    policy_version: str

    def plan(self, inp: PlannerInput) -> InferencePlan: ...


def jev_gate_fires(
    triage: JevTriage | None,
    conf_threshold: float = JEV_DEFAULT_CONF_THRESHOLD,
    risk_threshold: float = JEV_DEFAULT_RISK_THRESHOLD,
) -> bool:
    if triage is None:
        return False
    return (
        triage.decision == "escalate"
        or triage.escalate_risk >= risk_threshold
        or triage.confidence < conf_threshold
    )


def _base_mapping(route: RouteDecision, risk: str) -> tuple[str, str, str, str]:
    """Return (model, reasoning, context, verification) before risk overlay."""
    if route == RouteDecision.LOCAL_ONLY:
        return ("local_tiny", "none", "minimal", "light")
    if route == RouteDecision.LOCAL_THEN_VERIFY:
        return ("local_small", "low", "minimal", "standard")
    if route == RouteDecision.COMPRESS_THEN_LOCAL:
        return ("local_small", "low", "compiled", "standard")
    if route == RouteDecision.COMPRESS_THEN_REMOTE:
        return ("fast_hosted", "medium", "compiled", "standard")
    # REMOTE_DIRECT
    if risk in HIGH_RISKS:
        return ("frontier", "high", "full", "strict")
    return ("fast_hosted", "medium", "full", "standard")


def _fallbacks(route: RouteDecision, risk: str, features: TaskFeatures | None) -> list[Fallback]:
    manual = features is not None and features.lcc_recommendation == "manual_review"
    external = features is not None and features.requires_external_knowledge
    if manual:
        return [
            Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
            Fallback("LOW_CONF", "ESCALATE"),
            Fallback("TIMEOUT", "ABORT"),
        ]
    if external:
        return [
            Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
            Fallback("LOW_CONF", "ADD_TOOL"),
            Fallback("TIMEOUT", "RETRY"),
        ]
    if route in (
        RouteDecision.LOCAL_ONLY,
        RouteDecision.LOCAL_THEN_VERIFY,
        RouteDecision.COMPRESS_THEN_LOCAL,
    ):
        return [
            Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
            Fallback("LOW_CONF", "INCREASE_REASONING"),
            Fallback("TIMEOUT", "RETRY"),
        ]
    if route == RouteDecision.COMPRESS_THEN_REMOTE:
        return [
            Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
            Fallback("LOW_CONF", "SWITCH_MODEL"),
            Fallback("TIMEOUT", "RETRY"),
        ]
    # REMOTE_DIRECT
    if risk in HIGH_RISKS:
        return [
            Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
            Fallback("LOW_CONF", "ESCALATE"),
            Fallback("TIMEOUT", "SWITCH_MODEL"),
        ]
    return [
        Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
        Fallback("LOW_CONF", "SWITCH_MODEL"),
        Fallback("TIMEOUT", "RETRY"),
    ]


def _escalation(route: RouteDecision, risk: str, features: TaskFeatures | None) -> EscalationPolicy:
    manual = features is not None and features.lcc_recommendation == "manual_review"
    if risk in HIGH_RISKS or manual:
        return EscalationPolicy(max_retries=2, max_restorations=4, escalate_to="human")
    return EscalationPolicy(max_retries=2, max_restorations=4, escalate_to="frontier")


def _fail_closed_overlay(
    model: str,
    verification: str,
    context: str,
    fallbacks: list[Fallback],
    risk: str,
    reasons: list[str],
) -> tuple[str, str, str, list[Fallback]]:
    """Cheap plans never go out silently on high/unknown risk: upgrade to frontier."""
    if risk in HIGH_RISKS and model in CHEAP_MODELS:
        reasons.append("fail_closed_risk_upgrade:cheap->frontier")
        model, verification, context = "frontier", "strict", "full"
    if risk in HIGH_RISKS and all(fb.action != "ESCALATE" for fb in fallbacks):
        reasons.append("fail_closed_added_escalate_fallback")
        fallbacks = [*fallbacks, Fallback("LOW_CONF", "ESCALATE")]
    if risk in HIGH_RISKS and verification != "strict":
        reasons.append("fail_closed_strict_verification")
        verification = "strict"
    return model, verification, context, fallbacks


def plan_deterministic(
    inp: PlannerInput,
    policy: PolicyConfig | None = None,
    engine_name: str = "deterministic",
) -> InferencePlan:
    risk = inp.risk_level if inp.risk_level in VALID_RISKS else "unknown"
    cfg = policy or PolicyConfig()
    features = inp.features or TaskFeatures(
        input_tokens=0,
        context_tokens=0,
        instruction_tokens=0,
        projected_savings_ratio=0.0,
        duplicate_ratio=0.0,
        has_strict_format=False,
        requires_calculation=False,
        requires_code=False,
        requires_external_knowledge=False,
        ambiguity_score=0.0,
        context_noise_score=0.0,
        lcc_recommendation="skip",
    )
    route_plan = choose_route(features, cfg)
    route = route_plan.decision
    model, reasoning, context, verification = _base_mapping(route, risk)
    reasons = [f"route:{route.value}", *[f"route_reason:{r}" for r in route_plan.reasons]]
    reasons.append(f"risk:{risk}")
    fallbacks = _fallbacks(route, risk, features)
    model, verification, context, fallbacks = _fail_closed_overlay(
        model, verification, context, fallbacks, risk, reasons
    )
    return InferencePlan(
        model_class=model,
        reasoning_budget=reasoning,
        context_profile=context,
        verification_profile=verification,
        fallbacks=fallbacks,
        escalation_policy=_escalation(route, risk, features),
        tools=list(inp.allowed_tools),
        route=route.value,
        reasons=reasons,
        policy_version=POLICY_VERSION,
        engine=engine_name,
    )


class DeterministicPlanner:
    engine_name = "deterministic"
    policy_version = POLICY_VERSION

    def __init__(self, policy: PolicyConfig | None = None) -> None:
        self._policy = policy or PolicyConfig()

    def plan(self, inp: PlannerInput) -> InferencePlan:
        return plan_deterministic(inp, self._policy, self.engine_name)


class JevAdapterPlanner:
    """Same interface; triage gate may force escalation, else baseline."""

    engine_name = "jev-adapter"
    policy_version = POLICY_VERSION

    def __init__(
        self,
        policy: PolicyConfig | None = None,
        conf_threshold: float = JEV_DEFAULT_CONF_THRESHOLD,
        risk_threshold: float = JEV_DEFAULT_RISK_THRESHOLD,
    ) -> None:
        self._policy = policy or PolicyConfig()
        self._conf = conf_threshold
        self._risk = risk_threshold

    def plan(self, inp: PlannerInput) -> InferencePlan:
        if jev_gate_fires(inp.triage, self._conf, self._risk):
            base = plan_deterministic(inp, self._policy, self.engine_name)
            reasons = [
                *base.reasons,
                "jev_escalation_gate:decision={}|conf={}|risk={}".format(
                    inp.triage.decision if inp.triage else "?",
                    inp.triage.confidence if inp.triage else -1,
                    inp.triage.escalate_risk if inp.triage else -1,
                ),
            ]
            fallbacks = base.fallbacks
            if all(fb.action != "ESCALATE" for fb in fallbacks):
                fallbacks = [*fallbacks, Fallback("LOW_CONF", "ESCALATE")]
            reasoning = base.reasoning_budget if base.reasoning_budget == "high" else "high"
            return InferencePlan(
                model_class="frontier",
                reasoning_budget=reasoning,
                context_profile="full",
                verification_profile="strict",
                fallbacks=fallbacks,
                escalation_policy=EscalationPolicy(2, 4, "human"),
                tools=list(inp.allowed_tools),
                route=base.route,
                reasons=reasons,
                policy_version=POLICY_VERSION,
                engine=self.engine_name,
            )
        base = plan_deterministic(inp, self._policy, self.engine_name)
        return InferencePlan(
            model_class=base.model_class,
            reasoning_budget=base.reasoning_budget,
            context_profile=base.context_profile,
            verification_profile=base.verification_profile,
            fallbacks=base.fallbacks,
            escalation_policy=base.escalation_policy,
            tools=base.tools,
            route=base.route,
            reasons=[*base.reasons, "jev_no_escalation"],
            policy_version=POLICY_VERSION,
            engine=self.engine_name,
        )


class RulesPlanner:
    """Static risk table. No feature inspection; auditable by construction."""

    engine_name = "rules"
    policy_version = POLICY_VERSION

    def plan(self, inp: PlannerInput) -> InferencePlan:
        risk = inp.risk_level if inp.risk_level in VALID_RISKS else "unknown"
        if risk == "low":
            model, reasoning, ctx, verif, route = (
                "local_tiny",
                "none",
                "minimal",
                "light",
                RouteDecision.LOCAL_ONLY.value,
            )
            fallbacks = [
                Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
                Fallback("TIMEOUT", "RETRY"),
            ]
            esc = EscalationPolicy(2, 4, "frontier")
        elif risk == "medium":
            model, reasoning, ctx, verif, route = (
                "fast_hosted",
                "medium",
                "compiled",
                "standard",
                RouteDecision.COMPRESS_THEN_REMOTE.value,
            )
            fallbacks = [
                Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
                Fallback("LOW_CONF", "SWITCH_MODEL"),
            ]
            esc = EscalationPolicy(2, 4, "frontier")
        else:  # high | unknown fail closed
            model, reasoning, ctx, verif, route = (
                "frontier",
                "high",
                "full",
                "strict",
                RouteDecision.REMOTE_DIRECT.value,
            )
            fallbacks = [
                Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
                Fallback("LOW_CONF", "ESCALATE"),
            ]
            esc = EscalationPolicy(2, 4, "human")
        return InferencePlan(
            model_class=model,
            reasoning_budget=reasoning,
            context_profile=ctx,
            verification_profile=verif,
            fallbacks=fallbacks,
            escalation_policy=esc,
            tools=list(inp.allowed_tools),
            route=route,
            reasons=[f"rules:risk={risk}", f"route:{route}"],
            policy_version=POLICY_VERSION,
            engine=self.engine_name,
        )


ENGINES: dict[str, type[DeterministicPlanner] | type[JevAdapterPlanner] | type[RulesPlanner]] = {
    "deterministic": DeterministicPlanner,
    "jev-adapter": JevAdapterPlanner,
    "rules": RulesPlanner,
}


def plan_with_engine(engine: str, inp: PlannerInput) -> InferencePlan:
    try:
        cls = ENGINES[engine]
    except KeyError:
        raise ValueError(f"unknown engine {engine!r}; expected one of {sorted(ENGINES)}") from None
    return cls().plan(inp)
