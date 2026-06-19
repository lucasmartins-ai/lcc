"""Dataclass schemas for the deterministic benchmark harness (ADR 0007, ADR 0001).

Stdlib dataclasses (no Pydantic), matching the rest of the project. The benchmark suite
report carries its own ``schema_version``, independent of the optimization report's version
(ADR 0004): the two evolve separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Bumped only on a breaking change to the benchmark suite report shape (ADR 0007).
BENCH_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class CleaningOptions:
    """Deterministic pipeline cleaning settings selected by a case's compression level."""

    remove_boilerplate: bool
    remove_near_duplicates: bool
    similarity_threshold: float


#: Maps a case ``compression_level`` label to deterministic pipeline cleaning options. Only
#: ``"safe"`` exists today (the pipeline defaults); richer levels are roadmap, not built.
COMPRESSION_LEVELS: dict[str, CleaningOptions] = {
    "safe": CleaningOptions(
        remove_boilerplate=True,
        remove_near_duplicates=True,
        similarity_threshold=0.95,
    ),
}


@dataclass
class BenchmarkExpectations:
    """Explicit per-case pass/fail thresholds. A case passes only if all are satisfied."""

    min_token_savings_percent: float = 0.0
    max_token_savings_percent: float = 100.0
    min_required_marker_recall: float = 1.0
    allow_approximate_token_count: bool = False
    max_forbidden_markers_found: int = 0


@dataclass
class BenchmarkCase:
    """A single benchmark fixture: raw context plus how to optimize and judge it."""

    id: str
    description: str
    question: str
    input_text: str
    model: str = "gpt-4.1"
    max_input_tokens: int | None = None
    compression_level: str = "safe"
    required_markers: list[str] = field(default_factory=list)
    forbidden_markers: list[str] = field(default_factory=list)
    expectations: BenchmarkExpectations = field(default_factory=BenchmarkExpectations)


@dataclass
class CaseResult:
    """Mechanical metrics and pass/fail outcome for one case (no semantic judgment)."""

    id: str
    description: str
    model: str

    original_char_count: int
    optimized_char_count: int
    char_reduction_percent: float

    original_token_count: int
    optimized_token_count: int
    token_savings_percent: float
    compression_ratio: float

    token_count_mode: str  # "exact" | "approximate"

    required_markers_total: int
    required_markers_found: list[str]
    required_markers_missing: list[str]
    required_marker_recall: float

    forbidden_markers_total: int
    forbidden_markers_found: list[str]

    warnings: list[str]

    passed: bool
    failure_reasons: list[str]


@dataclass
class SuiteResult:
    """Aggregate report over all cases, with a versioned, deterministic shape."""

    schema_version: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    average_token_savings_percent: float
    average_compression_ratio: float
    cases: list[CaseResult]
