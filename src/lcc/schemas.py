"""Shared dataclass schemas and the JSON report contract.

These dataclasses are the cross-module contract (ADR 0001). Stdlib dataclasses are used
instead of Pydantic to keep the deterministic core dependency-free. The report is
serialized to JSON by ``lcc.reporting.report.report_to_dict``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

#: Bumped only on a breaking change to the JSON report shape (ADR 0004).
SCHEMA_VERSION = "1.0"


class TokenCountMethod(StrEnum):
    """Whether a token count is exact (a model-specific tokenizer) or approximate."""

    EXACT = "exact"
    APPROXIMATE = "approximate"


@dataclass(frozen=True)
class TokenCount:
    """Result of counting tokens for a piece of text.

    ``method`` states honestly whether the count is exact for the requested model or an
    approximation (ADR 0005). Callers must not treat an approximate count as exact.
    """

    value: int
    method: TokenCountMethod
    counter: str  # "tiktoken" | "heuristic"
    encoding: str | None = None
    note: str | None = None


@dataclass
class CleaningStep:
    """A single deterministic cleaning action that was applied, with its metrics."""

    name: str
    detail: str
    metrics: dict[str, int] = field(default_factory=dict)


@dataclass
class DedupMetrics:
    """Paragraph-level deduplication metrics."""

    paragraphs_before: int
    paragraphs_after: int
    duplicates_removed: int
    near_duplicates_removed: int = 0


@dataclass
class PricingInfo:
    """Pricing used for cost estimation. ``found`` is False when the model is unknown."""

    model: str
    input_per_million: float | None
    output_per_million: float | None
    currency: str
    source: str
    found: bool


@dataclass
class CostEstimate:
    """Estimated input cost before/after optimization. ``None`` when pricing is unknown."""

    before: float | None
    after: float | None
    savings: float | None
    currency: str


@dataclass
class OptimizationReport:
    """The machine-readable report emitted for every optimization run.

    The ``schema_version`` field lets downstream consumers detect format changes. The
    report is deterministic: identical input produces an identical report (no timestamps).
    """

    schema_version: str
    tool_version: str
    model: str
    task_type: str

    original_char_count: int
    optimized_char_count: int
    original_token_count: int
    optimized_token_count: int
    prompt_token_count: int

    compression_ratio: float
    token_savings_percent: float

    token_count_method: TokenCountMethod
    token_counter: str
    token_encoding: str | None

    cost: CostEstimate
    pricing: PricingInfo
    cleaning_steps: list[CleaningStep]
    dedup_metrics: DedupMetrics
    warnings: list[str]
