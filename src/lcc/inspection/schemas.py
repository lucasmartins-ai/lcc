"""Dataclass schemas for the deterministic inspection report (ADR 0009, ADR 0001).

Stdlib dataclasses (no Pydantic), matching the rest of the project. The inspection report
carries its own ``schema_version``, independent of the optimization report's version
(ADR 0004): the two evolve separately. The report is deterministic -- identical input
produces an identical report (no timestamps, no random values, no machine-specific paths).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lcc.schemas import CleaningStep

#: Bumped only on a breaking change to the inspection report shape (ADR 0009, ADR 0004).
INSPECT_SCHEMA_VERSION = "1.0"


@dataclass
class InputInfo:
    """Structural facts about the raw input (source kind and size). ``source_type`` is only
    ``"file"`` or ``"stdin"`` -- never a path -- so the report stays machine-independent."""

    source_type: str  # "file" | "stdin"
    character_count: int
    line_count: int
    paragraph_count: int
    non_empty_line_count: int


@dataclass
class TokenBudgetInfo:
    """Token and cost profile of the raw input, honest about exact vs approximate.

    ``token_count_method`` is ``"exact"`` only when ``tiktoken`` maps the model and its
    encoding loads from a local cache; otherwise ``"approximate"`` (ADR 0005, ADR 0008).
    ``estimated_input_cost`` is ``None`` when the model has no pricing entry.
    """

    model: str
    token_count: int
    token_count_method: str  # "exact" | "approximate"
    tokenizer: str  # "tiktoken" | "heuristic"
    token_encoding: str | None
    estimated_input_cost: float | None
    pricing_currency: str
    pricing_unit: str
    pricing_found: bool


@dataclass
class StructureInfo:
    """Whitespace and shape metrics that hint at cleanup opportunity (measured on the input)."""

    blank_line_runs: int
    max_blank_line_run: int
    longest_line_chars: int
    longest_paragraph_chars: int
    average_paragraph_chars: float


@dataclass
class DuplicationInfo:
    """Paragraph-level duplication measured by the safe-cleaning projection.

    ``paragraphs_before`` is the paragraph count entering deduplication (after normalization
    and boilerplate removal), so it may differ from ``InputInfo.paragraph_count`` (the raw
    input's paragraphs).
    """

    paragraphs_before: int
    paragraphs_after_exact_dedup: int
    exact_duplicates_removed: int
    near_duplicates_removed: int
    duplicate_ratio: float


@dataclass
class SafeCleanupProjection:
    """Estimated effect of the deterministic safe cleaning, clearly labelled as a projection.

    These numbers describe what ``lcc optimize`` would remove. Inspection never writes an
    optimized prompt and never modifies the input (ADR 0009); ``projection_note`` says so.
    """

    original_tokens: int
    projected_tokens_after_safe_cleaning: int
    projected_token_savings_percent: float
    projected_character_savings_percent: float
    cleaning_actions_considered: list[CleaningStep] = field(default_factory=list)
    projection_note: str = ""


@dataclass
class InspectionReport:
    """The machine-readable diagnostic report emitted by ``lcc inspect``.

    Diagnostic, not transformative: it measures the input and projects safe-cleaning savings
    without generating a prompt. ``schema_version`` lets consumers branch on the format; the
    report is deterministic (no timestamps, no random values, no absolute paths).
    """

    schema_version: str
    tool_version: str
    input: InputInfo
    token_budget: TokenBudgetInfo
    structure: StructureInfo
    duplication: DuplicationInfo
    safe_cleanup_projection: SafeCleanupProjection
    warnings: list[str]
