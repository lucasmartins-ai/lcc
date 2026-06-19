"""Compute a deterministic diagnostic report for a text input (ADR 0009).

This module sits *above* the deterministic core (like the CLI and the benchmark harness): it
composes the cleaning and token-budget utilities to measure an input and to project what the
safe cleaning in ``lcc optimize`` would remove. It is **diagnostic, not transformative** -- it
never builds or writes a prompt (it does not import ``lcc.prompt_builder``), never calls a
network, model, or embedding service, and never modifies the input. Given identical input it
produces an identical report (ADR 0006).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from lcc import __version__
from lcc.cleaning import deduplicate_paragraphs, normalize_text, remove_common_boilerplate
from lcc.cleaning.boilerplate import BoilerplateResult
from lcc.inspection.schemas import (
    INSPECT_SCHEMA_VERSION,
    DuplicationInfo,
    InputInfo,
    InspectionReport,
    SafeCleanupProjection,
    StructureInfo,
    TokenBudgetInfo,
)
from lcc.schemas import CleaningStep, TokenCountMethod
from lcc.token_budget import count_tokens
from lcc.token_budget.pricing import BUILTIN_PRICING, estimate_input_cost, get_model_pricing

# Same paragraph notion as ``lcc.cleaning.deduplicate``: blocks separated by blank lines.
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n")

_PROJECTION_NOTE = (
    "Projected savings from deterministic safe cleaning (normalize whitespace, conservative "
    "boilerplate removal, exact + near-duplicate paragraph removal) -- an estimate of what "
    "`lcc optimize` would remove, not a completed optimization. No prompt was generated and "
    "the input file was not modified."
)


@dataclass
class InspectionRequest:
    """All inputs for a single inspection run.

    The cleaning knobs mirror ``lcc optimize``'s safe defaults so the projection reflects what
    optimization would actually remove; inspection itself only measures.
    """

    raw_text: str
    source_type: str = "file"  # "file" | "stdin"
    model: str = "gpt-4.1"
    pricing: dict[str, Any] | None = None
    remove_boilerplate: bool = True
    remove_near_duplicates: bool = True
    similarity_threshold: float = 0.95


def _split_paragraphs(text: str) -> list[str]:
    """Split text into non-empty, stripped paragraph blocks (line-ending agnostic)."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = _PARAGRAPH_SPLIT.split(normalized)
    return [block.strip() for block in blocks if block.strip()]


def _input_info(raw: str, source_type: str) -> InputInfo:
    lines = raw.splitlines()
    return InputInfo(
        source_type=source_type,
        character_count=len(raw),
        line_count=len(lines),
        paragraph_count=len(_split_paragraphs(raw)),
        non_empty_line_count=sum(1 for line in lines if line.strip()),
    )


def _structure_info(raw: str) -> StructureInfo:
    lines = raw.splitlines()
    paragraphs = _split_paragraphs(raw)

    runs: list[int] = []
    current = 0
    for line in lines:
        if line.strip():
            if current:
                runs.append(current)
            current = 0
        else:
            current += 1
    if current:
        runs.append(current)

    para_lengths = [len(paragraph) for paragraph in paragraphs]
    average = round(sum(para_lengths) / len(para_lengths), 2) if para_lengths else 0.0
    return StructureInfo(
        blank_line_runs=len(runs),
        max_blank_line_run=max(runs, default=0),
        longest_line_chars=max((len(line) for line in lines), default=0),
        longest_paragraph_chars=max(para_lengths, default=0),
        average_paragraph_chars=average,
    )


def inspect(request: InspectionRequest) -> InspectionReport:
    """Analyze ``request.raw_text`` and return a deterministic diagnostic report.

    Measures the input's size, structure, and token/cost profile, then projects what the safe
    deterministic cleaning would remove -- running the same cleaning sequence as
    ``lcc.pipeline.optimize`` (normalize -> remove boilerplate -> deduplicate) but only for
    measurement. No prompt is built and the input is never modified (ADR 0009).
    """
    raw = request.raw_text
    warnings: list[str] = []
    if not raw.strip():
        warnings.append("Input text is empty or whitespace-only; nothing to inspect.")

    # --- Safe-cleaning projection (mirrors lcc.pipeline.optimize's cleaning sequence) ---
    normalized = normalize_text(raw)
    if request.remove_boilerplate:
        boilerplate = remove_common_boilerplate(normalized.text)
    else:
        boilerplate = BoilerplateResult(text=normalized.text, actions=[])
    dedup = deduplicate_paragraphs(
        boilerplate.text,
        remove_near_duplicates=request.remove_near_duplicates,
        similarity_threshold=request.similarity_threshold,
    )
    projected_text = dedup.text
    metrics = dedup.metrics

    original_count = count_tokens(raw, request.model)
    projected_count = count_tokens(projected_text, request.model)

    if TokenCountMethod.APPROXIMATE in (original_count.method, projected_count.method):
        message = "Token counts are approximate; treat token and cost figures as estimates."
        reason = original_count.note or projected_count.note
        if reason:
            message = f"{message} {reason}"
        warnings.append(message)

    pricing_doc = request.pricing if request.pricing is not None else BUILTIN_PRICING
    pricing = get_model_pricing(pricing_doc, request.model)
    if not pricing.found:
        warnings.append(
            f"No pricing entry for model {request.model!r}; the cost estimate is omitted. "
            "Add it to your pricing config to enable cost output."
        )
    estimated_cost = estimate_input_cost(original_count.value, pricing.input_per_million)
    pricing_unit = str(pricing_doc.get("unit", "per_million_tokens"))

    original_tokens = original_count.value
    projected_tokens = projected_count.value
    token_savings_pct = (
        round((1.0 - projected_tokens / original_tokens) * 100.0, 2) if original_tokens > 0 else 0.0
    )
    char_savings_pct = round((1.0 - len(projected_text) / len(raw)) * 100.0, 2) if raw else 0.0

    before = metrics.paragraphs_before
    after_exact = before - metrics.duplicates_removed
    final_after = metrics.paragraphs_after
    duplicate_ratio = round((before - final_after) / before, 4) if before > 0 else 0.0

    cleaning_actions: list[CleaningStep] = [*normalized.steps, *boilerplate.actions]
    if metrics.duplicates_removed or metrics.near_duplicates_removed:
        cleaning_actions.append(
            CleaningStep(
                "deduplicate_paragraphs",
                f"Removed {metrics.duplicates_removed} exact and "
                f"{metrics.near_duplicates_removed} near-duplicate paragraph(s).",
                {
                    "exact_duplicates_removed": metrics.duplicates_removed,
                    "near_duplicates_removed": metrics.near_duplicates_removed,
                },
            )
        )

    return InspectionReport(
        schema_version=INSPECT_SCHEMA_VERSION,
        tool_version=__version__,
        input=_input_info(raw, request.source_type),
        token_budget=TokenBudgetInfo(
            model=request.model,
            token_count=original_tokens,
            token_count_method=original_count.method.value,
            tokenizer=original_count.counter,
            token_encoding=original_count.encoding,
            estimated_input_cost=estimated_cost,
            pricing_currency=pricing.currency,
            pricing_unit=pricing_unit,
            pricing_found=pricing.found,
        ),
        structure=_structure_info(raw),
        duplication=DuplicationInfo(
            paragraphs_before=before,
            paragraphs_after_exact_dedup=after_exact,
            exact_duplicates_removed=metrics.duplicates_removed,
            near_duplicates_removed=metrics.near_duplicates_removed,
            duplicate_ratio=duplicate_ratio,
        ),
        safe_cleanup_projection=SafeCleanupProjection(
            original_tokens=original_tokens,
            projected_tokens_after_safe_cleaning=projected_tokens,
            projected_token_savings_percent=token_savings_pct,
            projected_character_savings_percent=char_savings_pct,
            cleaning_actions_considered=cleaning_actions,
            projection_note=_PROJECTION_NOTE,
        ),
        warnings=warnings,
    )
