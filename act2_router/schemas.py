"""Router data contracts.

These schemas intentionally live outside ``src/lcc``. LCC remains the deterministic context
compiler; this package owns hackathon-specific model routing, verification, and evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RouteDecision(StrEnum):
    """Allowed first-hop route decisions."""

    LOCAL_ONLY = "LOCAL_ONLY"
    LOCAL_THEN_VERIFY = "LOCAL_THEN_VERIFY"
    COMPRESS_THEN_LOCAL = "COMPRESS_THEN_LOCAL"
    COMPRESS_THEN_REMOTE = "COMPRESS_THEN_REMOTE"
    REMOTE_DIRECT = "REMOTE_DIRECT"


class VerificationDecision(StrEnum):
    """Verifier outcome."""

    ACCEPT_LOCAL = "ACCEPT_LOCAL"
    ESCALATE_REMOTE = "ESCALATE_REMOTE"


@dataclass(frozen=True)
class TaskInput:
    """One hackathon task."""

    task_id: str
    instruction: str
    context: str = ""
    expected_format: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> TaskInput:
        return cls(
            task_id=str(data.get("task_id") or data.get("id") or "task"),
            instruction=str(data.get("instruction") or data.get("question") or ""),
            context=str(data.get("context") or ""),
            expected_format=(
                str(data["expected_format"]) if data.get("expected_format") is not None else None
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LCCReportSummary:
    """Small router-facing subset of an LCC inspection/prepare report."""

    input_tokens: int
    optimized_tokens: int
    projected_savings_ratio: float
    duplicate_ratio: float
    recommendation_action: str
    warnings: list[str] = field(default_factory=list)
    selected_chunks_count: int = 0


@dataclass(frozen=True)
class TaskFeatures:
    """Transparent deterministic features used by the routing policy."""

    input_tokens: int
    context_tokens: int
    instruction_tokens: int
    projected_savings_ratio: float
    duplicate_ratio: float
    has_strict_format: bool
    requires_calculation: bool
    requires_code: bool
    requires_external_knowledge: bool
    ambiguity_score: float
    context_noise_score: float
    lcc_recommendation: str
    has_conflicting_instructions: bool = False


@dataclass(frozen=True)
class LocalAnswer:
    """Answer produced by a local solver."""

    answer: str
    model_name: str
    latency_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    """Structured local acceptance gate result."""

    decision: VerificationDecision
    confidence: float
    format_valid: bool
    missing_requirements: list[str] = field(default_factory=list)
    risk_reasons: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass(frozen=True)
class RemoteAnswer:
    """Answer produced by Fireworks or the mock remote fallback."""

    answer: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    usage_estimated: bool = False
    error: str | None = None


@dataclass(frozen=True)
class FinalAnswer:
    """Final response returned by the router."""

    task_id: str
    answer: str
    route_taken: str
    remote_tokens_used: int
    local_steps_used: list[str]
    verification: VerificationResult | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationResult:
    """Aggregate local development evaluation metrics."""

    total_cases: int
    remote_tokens_total: int
    remote_tokens_mean: float
    local_accept_rate: float
    remote_escalation_rate: float
    format_pass_rate: float
    estimated_accuracy_proxy: float
    failures: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PreparedContext:
    """Context/prompt prepared by LCC for a router step."""

    context: str
    prompt: str
    lcc_summary: LCCReportSummary
    compression_applied: bool
    warnings: list[str] = field(default_factory=list)
