from __future__ import annotations

from lcc.router.config import PolicyConfig
from lcc.router.policy import choose_route
from lcc.router.schemas import RouteDecision, TaskFeatures


def _features(**overrides: object) -> TaskFeatures:
    values = {
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
    values.update(overrides)
    return TaskFeatures(**values)  # type: ignore[arg-type]


def test_short_simple_task_routes_local_then_verify() -> None:
    plan = choose_route(_features(), PolicyConfig())
    assert plan.decision == RouteDecision.LOCAL_THEN_VERIFY
    assert "short_simple_local_first" in plan.reasons


def test_noisy_context_routes_compress_then_local_when_small_enough() -> None:
    plan = choose_route(
        _features(
            projected_savings_ratio=0.3,
            context_noise_score=0.3,
            lcc_recommendation="optimize_safe",
        ),
        PolicyConfig(),
    )
    assert plan.decision == RouteDecision.COMPRESS_THEN_LOCAL


def test_external_knowledge_routes_remote_direct() -> None:
    plan = choose_route(_features(requires_external_knowledge=True), PolicyConfig())
    assert plan.decision == RouteDecision.REMOTE_DIRECT


def test_builtin_policy_matches_the_shipped_yaml(tmp_path):
    """``configs/`` is not in the wheel: a pip install must get the same risk keywords.

    Regression: outside the repo checkout ``load_policy`` found no YAML and every risk
    keyword list came back empty, silently turning risk detection off.
    """
    from pathlib import Path

    from lcc.router.config import load_policy

    shipped = load_policy(Path(__file__).resolve().parents[1] / "configs" / "router_policy.yaml")
    assert load_policy(tmp_path / "missing.yaml") == shipped
