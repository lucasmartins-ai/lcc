"""MSI Sprint 4: inference planner goldens + fail-closed invariant (offline only).

Engines: deterministic | jev-adapter | rules. No provider calls anywhere;
Jev triage is a test-supplied (decision, confidence, escalate_risk) signal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lcc.router.plan import (
    CHEAP_MODELS,
    HIGH_RISKS,
    POLICY_VERSION,
    DeterministicPlanner,
    JevAdapterPlanner,
    JevTriage,
    PlannerInput,
    RulesPlanner,
    plan_with_engine,
)
from lcc.router.schemas import RouteDecision, TaskFeatures

jsonschema = pytest.importorskip("jsonschema", reason="spec validation needs jsonschema")

SPEC = Path(__file__).parent / "fixtures" / "msi" / "inference-plan.schema.json"
DET = DeterministicPlanner()


def _f(**kw) -> TaskFeatures:
    base = {
        "input_tokens": 200,
        "context_tokens": 160,
        "instruction_tokens": 40,
        "projected_savings_ratio": 0.0,
        "duplicate_ratio": 0.0,
        "has_strict_format": False,
        "requires_calculation": False,
        "requires_code": False,
        "requires_external_knowledge": False,
        "ambiguity_score": 0.0,
        "context_noise_score": 0.0,
        "lcc_recommendation": "skip",
        "has_conflicting_instructions": False,
    }
    base.update(kw)
    return TaskFeatures(**base)  # type: ignore[arg-type]


# 12 frozen goldens: (name, risk, features, engine, model, reasoning, ctx, verif, route, fallbacks, escalate_to)
GOLDENS = [
    ("trivial-low-local", "low", _f(), "deterministic",
     "local_small", "low", "minimal", "standard", "LOCAL_THEN_VERIFY",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "INCREASE_REASONING"), ("TIMEOUT", "RETRY")], "frontier"),
    ("noisy-small-medium", "medium", _f(projected_savings_ratio=0.3, context_noise_score=0.3),
     "deterministic", "local_small", "low", "compiled", "standard", "COMPRESS_THEN_LOCAL",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "INCREASE_REASONING"), ("TIMEOUT", "RETRY")], "frontier"),
    ("external-medium", "medium", _f(requires_external_knowledge=True), "deterministic",
     "fast_hosted", "medium", "full", "standard", "REMOTE_DIRECT",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "ADD_TOOL"), ("TIMEOUT", "RETRY")], "frontier"),
    ("manual-review-high", "high", _f(lcc_recommendation="manual_review"), "deterministic",
     "frontier", "high", "full", "strict", "REMOTE_DIRECT",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "ESCALATE"), ("TIMEOUT", "ABORT")], "human"),
    ("huge-compress-remote", "medium",
     _f(input_tokens=20000, context_tokens=19000, instruction_tokens=1000,
         projected_savings_ratio=0.3, context_noise_score=0.3), "deterministic",
     "fast_hosted", "medium", "compiled", "standard", "COMPRESS_THEN_REMOTE",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "SWITCH_MODEL"), ("TIMEOUT", "RETRY")], "frontier"),
    ("huge-direct-medium", "medium",
     _f(input_tokens=20000, context_tokens=19000, instruction_tokens=1000), "deterministic",
     "fast_hosted", "medium", "full", "standard", "REMOTE_DIRECT",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "SWITCH_MODEL"), ("TIMEOUT", "RETRY")], "frontier"),
    ("high-risk-cheap-upgrade", "high", _f(), "deterministic",
     "frontier", "low", "full", "strict", "LOCAL_THEN_VERIFY",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "INCREASE_REASONING"),
      ("TIMEOUT", "RETRY"), ("LOW_CONF", "ESCALATE")], "human"),
    ("unknown-risk-cheap", "unknown", _f(), "deterministic",
     "frontier", "low", "full", "strict", "LOCAL_THEN_VERIFY",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "INCREASE_REASONING"),
      ("TIMEOUT", "RETRY"), ("LOW_CONF", "ESCALATE")], "human"),
    ("strict-format-low", "low", _f(has_strict_format=True), "deterministic",
     "local_small", "low", "minimal", "standard", "LOCAL_THEN_VERIFY",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "INCREASE_REASONING"), ("TIMEOUT", "RETRY")], "frontier"),
    ("conflict-high", "high",
     _f(has_conflicting_instructions=True, ambiguity_score=0.7), "deterministic",
     "frontier", "high", "full", "strict", "REMOTE_DIRECT",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "ESCALATE"), ("TIMEOUT", "SWITCH_MODEL")], "human"),
    ("code-large-medium", "medium",
     _f(requires_code=True, input_tokens=5000, context_tokens=4800, instruction_tokens=200),
     "deterministic", "fast_hosted", "medium", "full", "standard", "REMOTE_DIRECT",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("LOW_CONF", "SWITCH_MODEL"), ("TIMEOUT", "RETRY")], "frontier"),
    ("rules-low-local-only", "low", _f(), "rules",
     "local_tiny", "none", "minimal", "light", "LOCAL_ONLY",
     [("VERIFY_FAIL", "RESTORE_CONTEXT"), ("TIMEOUT", "RETRY")], "frontier"),
]


def _plan_for(name: str):
    (gname, risk, feat, engine, *_rest) = next(g for g in GOLDENS if g[0] == name)
    return plan_with_engine(engine, PlannerInput(gname, risk, "other", feat, []))


def test_golden_count_in_range():
    assert 10 <= len(GOLDENS) <= 15


@pytest.mark.parametrize("golden", GOLDENS, ids=[g[0] for g in GOLDENS])
def test_goldens_exact(golden):
    (name, _risk, feat, engine, model, reasoning, ctx, verif, route, fbs, esc) = golden
    plan = plan_with_engine(engine, PlannerInput(name, golden[1], "other", feat, []))
    assert plan.model_class == model, name
    assert plan.reasoning_budget == reasoning, name
    assert plan.context_profile == ctx, name
    assert plan.verification_profile == verif, name
    assert plan.route == route, name
    assert [(fb.trigger, fb.action) for fb in plan.fallbacks] == fbs, name
    assert plan.escalation_policy.escalate_to == esc, name
    assert plan.policy_version == POLICY_VERSION, name
    assert plan.engine == engine, name
    assert len(plan.reasons) >= 2, name  # route + risk/rules reason minimum


def test_goldens_validate_against_spec():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    for name, *_ in [(g[0],) for g in GOLDENS]:
        jsonschema.validate(_plan_for(name).to_spec_dict(), spec)


def test_all_routes_covered():
    routes = {plan_with_engine(g[3], PlannerInput(g[0], g[1], "other", g[2], [])).route for g in GOLDENS}
    expected = {r.value for r in RouteDecision}
    assert routes == expected, f"missing: {expected - routes}"


def test_all_fallback_actions_covered():
    actions: set[str] = set()
    for g in GOLDENS:
        actions.update(fb.action for fb in _plan_for(g[0]).fallbacks)
    assert actions == {"RESTORE_CONTEXT", "RETRY", "INCREASE_REASONING",
                       "SWITCH_MODEL", "ADD_TOOL", "ESCALATE", "ABORT"}, f"missing: {actions}"


def test_engine_swappable_mock_passes_contract():
    """A mock engine with the same interface yields schema-valid auditable plans."""
    spec = json.loads(SPEC.read_text(encoding="utf-8"))

    class MockEngine:
        engine_name = "mock"
        policy_version = POLICY_VERSION

        def plan(self, inp: PlannerInput):
            base = DET.plan(inp)
            return base

    mock = MockEngine()
    for g in GOLDENS:
        plan = mock.plan(PlannerInput(g[0], g[1], "other", g[2], []))
        jsonschema.validate(plan.to_spec_dict(), spec)
        assert plan.policy_version == POLICY_VERSION
        assert len(plan.reasons) >= 2


def test_all_three_engines_schema_valid_on_same_inputs():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    for g in GOLDENS:
        for engine in ("deterministic", "jev-adapter", "rules"):
            plan = plan_with_engine(engine, PlannerInput(g[0], g[1], "other", g[2], []))
            jsonschema.validate(plan.to_spec_dict(), spec)
            assert plan.policy_version == POLICY_VERSION
            assert plan.engine == engine


def test_jev_no_escalation_matches_deterministic():
    calm = JevTriage(decision="approve", confidence=0.9, escalate_risk=0.2)
    for g in GOLDENS[:6]:
        det = DET.plan(PlannerInput(g[0], g[1], "other", g[2], []))
        jev = JevAdapterPlanner().plan(PlannerInput(g[0], g[1], "other", g[2], [], calm))
        assert jev.model_class == det.model_class
        assert jev.route == det.route
        assert "jev_no_escalation" in jev.reasons


@pytest.mark.parametrize("decision,conf,risk", [
    ("escalate", 0.9, 0.1),   # explicit escalate
    ("approve", 0.5, 0.1),    # conf < 0.65
    ("approve", 0.9, 0.8),    # risk >= 0.60
])
def test_jev_escalation_forces_frontier_strict_escalate(decision, conf, risk):
    triage = JevTriage(decision=decision, confidence=conf, escalate_risk=risk)
    plan = JevAdapterPlanner().plan(PlannerInput("t", "low", "other", _f(), [], triage))
    assert plan.model_class == "frontier"
    assert plan.verification_profile == "strict"
    assert any(fb.action == "ESCALATE" for fb in plan.fallbacks)
    assert plan.escalation_policy.escalate_to == "human"
    assert any("jev_escalation_gate" in r for r in plan.reasons)


@pytest.mark.parametrize("risk", ["high", "unknown"])
def test_fail_closed_cheap_never_silent(risk):
    """Cheap model + high/unknown risk without escalation must never be emitted."""
    feats = [
        _f(),
        _f(projected_savings_ratio=0.3, context_noise_score=0.3),
        _f(has_strict_format=True),
        _f(requires_code=True, input_tokens=5000, context_tokens=4800, instruction_tokens=200),
    ]
    engines = [DeterministicPlanner(), JevAdapterPlanner(), RulesPlanner()]
    for feat in feats:
        for eng in engines:
            plan = eng.plan(PlannerInput("t", risk, "other", feat, []))
            if plan.model_class in CHEAP_MODELS:
                assert any(fb.action == "ESCALATE" for fb in plan.fallbacks), (eng.engine_name, risk)
            if risk in HIGH_RISKS:
                assert plan.verification_profile == "strict", (eng.engine_name, risk)


def test_invalid_risk_defaults_unknown_fail_closed():
    plan = DET.plan(PlannerInput("t", "nonsense", "other", _f(), []))
    assert plan.model_class not in CHEAP_MODELS
    assert plan.verification_profile == "strict"


def test_unknown_engine_raises():
    with pytest.raises(ValueError, match="unknown engine"):
        plan_with_engine("small-local-model", PlannerInput("t", "low", "other", _f(), []))


def test_no_provider_fields_in_spec_dict():
    import re

    for g in GOLDENS:
        blob = json.dumps(_plan_for(g[0]).to_spec_dict())
        assert re.search(r"jev|openai|anthropic|gpt|claude", blob, re.IGNORECASE) is None
