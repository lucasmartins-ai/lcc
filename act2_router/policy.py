"""Policy-driven route selection."""

from __future__ import annotations

from dataclasses import dataclass, field

from act2_router.config import PolicyConfig
from act2_router.schemas import RouteDecision, TaskFeatures


@dataclass(frozen=True)
class RoutePlan:
    decision: RouteDecision
    reasons: list[str] = field(default_factory=list)


def choose_route(features: TaskFeatures, policy: PolicyConfig) -> RoutePlan:
    cfg = policy.router
    reasons: list[str] = []
    savings_high = features.projected_savings_ratio >= cfg.compress_if_projected_savings_above
    high_risk = (
        features.requires_external_knowledge
        or features.has_conflicting_instructions
        or features.ambiguity_score >= 0.65
        or (features.requires_code and features.input_tokens > cfg.local_first_max_tokens)
    )

    if features.lcc_recommendation == "manual_review" and cfg.escalate_if_manual_review:
        reasons.append("lcc_manual_review")
        return RoutePlan(RouteDecision.REMOTE_DIRECT, reasons)

    if features.input_tokens >= cfg.remote_direct_if_input_tokens_above:
        reasons.append("input_above_remote_direct_threshold")
        if cfg.compress_before_remote and savings_high:
            reasons.append("compress_before_remote_enabled")
            return RoutePlan(RouteDecision.COMPRESS_THEN_REMOTE, reasons)
        return RoutePlan(RouteDecision.REMOTE_DIRECT, reasons)

    if high_risk:
        reasons.append("high_accuracy_risk")
        if cfg.compress_before_remote and savings_high:
            reasons.append("compress_before_remote_enabled")
            return RoutePlan(RouteDecision.COMPRESS_THEN_REMOTE, reasons)
        return RoutePlan(RouteDecision.REMOTE_DIRECT, reasons)

    if savings_high and features.context_noise_score >= 0.15:
        reasons.append("lcc_projected_savings")
        if features.input_tokens <= cfg.local_first_max_tokens:
            return RoutePlan(RouteDecision.COMPRESS_THEN_LOCAL, reasons)
        return RoutePlan(RouteDecision.COMPRESS_THEN_REMOTE, reasons)

    if features.has_strict_format and cfg.strict_format_requires_verification:
        reasons.append("strict_format_requires_verification")
        return RoutePlan(RouteDecision.LOCAL_THEN_VERIFY, reasons)

    if features.input_tokens <= cfg.local_first_max_tokens:
        reasons.append("short_simple_local_first")
        return RoutePlan(RouteDecision.LOCAL_THEN_VERIFY, reasons)

    reasons.append("medium_risk_remote_after_compression")
    if cfg.compress_before_remote and savings_high:
        return RoutePlan(RouteDecision.COMPRESS_THEN_REMOTE, reasons)
    return RoutePlan(RouteDecision.REMOTE_DIRECT, reasons)
