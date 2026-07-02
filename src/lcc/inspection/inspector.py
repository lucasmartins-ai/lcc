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
    CleanupStageContribution,
    DuplicationInfo,
    InputInfo,
    InspectionRecommendation,
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

_SMALL_INPUT_TOKENS = 80
_LOW_SAVINGS_PERCENT = 5.0
_LOW_SAVINGS_TOKENS = 20
_HIGH_DUPLICATION_RATIO = 0.2
_HIGH_SAVINGS_PERCENT = 15.0
_HIGH_SAVINGS_TOKENS = 50
_MAX_INPUT_RISK_TOKENS = 100_000


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


def _savings_percent(before: int, after: int) -> float:
    return round((1.0 - after / before) * 100.0, 2) if before > 0 else 0.0


def _stage_contribution(
    stage: str,
    *,
    before_text: str,
    after_text: str,
    before_tokens: int,
    after_tokens: int,
) -> CleanupStageContribution:
    return CleanupStageContribution(
        stage=stage,
        tokens_before=before_tokens,
        tokens_after=after_tokens,
        projected_tokens_removed=before_tokens - after_tokens,
        projected_token_savings_percent=_savings_percent(before_tokens, after_tokens),
        characters_before=len(before_text),
        characters_after=len(after_text),
        projected_characters_removed=len(before_text) - len(after_text),
        projected_character_savings_percent=_savings_percent(len(before_text), len(after_text)),
    )


def _suggested_optimize_command(
    *,
    source_type: str,
    model: str,
    action: str,
    reason_codes: list[str],
) -> str | None:
    if action not in {"optimize_safe", "optimize_with_flags"}:
        return None
    input_arg = "-" if source_type == "stdin" else "INPUT"
    command = f'lcc optimize {input_arg} --model {model} --question "..."'
    if "missing_pricing" in reason_codes:
        command = f"{command} --pricing <pricing.yaml>"
    return command


def _recommendation(
    *,
    source_type: str,
    budget: TokenBudgetInfo,
    duplication: DuplicationInfo,
    projection: SafeCleanupProjection,
) -> InspectionRecommendation:
    tokens_saved = projection.original_tokens - projection.projected_tokens_after_safe_cleaning
    is_small = projection.original_tokens < _SMALL_INPUT_TOKENS
    is_low_savings = (
        projection.projected_token_savings_percent < _LOW_SAVINGS_PERCENT
        or tokens_saved < _LOW_SAVINGS_TOKENS
    )
    is_high_duplication = (
        duplication.duplicate_ratio >= _HIGH_DUPLICATION_RATIO
        and (duplication.exact_duplicates_removed + duplication.near_duplicates_removed) > 0
    )
    is_high_savings = (
        projection.projected_token_savings_percent >= _HIGH_SAVINGS_PERCENT
        or tokens_saved >= _HIGH_SAVINGS_TOKENS
    )
    has_max_input_risk = projection.projected_tokens_after_safe_cleaning >= _MAX_INPUT_RISK_TOKENS
    has_missing_pricing = not budget.pricing_found

    reason_codes: list[str] = []
    if has_max_input_risk:
        action = "manual_review"
        reason_codes.append("max_input_risk")
        summary = "Review manually; projected context is still large."
    elif is_small:
        action = "skip"
        reason_codes.append("small_input")
        summary = "Skip optimization; projected savings are minor."
    elif is_low_savings:
        action = "skip"
        reason_codes.append("low_projected_savings")
        summary = "Skip optimization; projected token savings are low."
    elif is_high_duplication or is_high_savings:
        action = "optimize_with_flags" if has_missing_pricing else "optimize_safe"
        if is_high_duplication:
            reason_codes.append("high_duplication")
        else:
            reason_codes.append("high_projected_savings")
        if action == "optimize_with_flags":
            summary = "Optimization looks useful, but add missing configuration first."
        else:
            summary = "Run safe optimization; cleanup should help."
    else:
        action = "skip"
        reason_codes.append("low_projected_savings")
        summary = "Skip optimization; no strong cleanup opportunity was detected."

    if is_high_duplication and "high_duplication" not in reason_codes:
        reason_codes.append("high_duplication")
    if is_low_savings and "low_projected_savings" not in reason_codes:
        reason_codes.append("low_projected_savings")
    if budget.token_count_method == TokenCountMethod.APPROXIMATE.value:
        reason_codes.append("approximate_token_count")
    if has_missing_pricing:
        reason_codes.append("missing_pricing")

    return InspectionRecommendation(
        action=action,
        reason_codes=reason_codes,
        summary=summary,
        suggested_command=_suggested_optimize_command(
            source_type=source_type,
            model=budget.model,
            action=action,
            reason_codes=reason_codes,
        ),
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
    exact_dedup = deduplicate_paragraphs(
        boilerplate.text,
        remove_near_duplicates=False,
        similarity_threshold=request.similarity_threshold,
    )
    if request.remove_near_duplicates:
        near_dedup = deduplicate_paragraphs(
            exact_dedup.text,
            remove_near_duplicates=True,
            similarity_threshold=request.similarity_threshold,
        )
    else:
        near_dedup = deduplicate_paragraphs(
            exact_dedup.text,
            remove_near_duplicates=False,
            similarity_threshold=request.similarity_threshold,
        )
    projected_text = near_dedup.text

    original_count = count_tokens(raw, request.model)
    normalized_count = count_tokens(normalized.text, request.model)
    boilerplate_count = count_tokens(boilerplate.text, request.model)
    exact_dedup_count = count_tokens(exact_dedup.text, request.model)
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
    estimated_cost_after = estimate_input_cost(projected_count.value, pricing.input_per_million)
    estimated_cost_savings = (
        estimated_cost - estimated_cost_after
        if estimated_cost is not None and estimated_cost_after is not None
        else None
    )
    pricing_unit = str(pricing_doc.get("unit", "per_million_tokens"))

    original_tokens = original_count.value
    projected_tokens = projected_count.value
    token_savings_pct = _savings_percent(original_tokens, projected_tokens)
    char_savings_pct = _savings_percent(len(raw), len(projected_text))

    before = exact_dedup.metrics.paragraphs_before
    after_exact = exact_dedup.metrics.paragraphs_after
    final_after = near_dedup.metrics.paragraphs_after
    duplicate_ratio = round((before - final_after) / before, 4) if before > 0 else 0.0

    cleaning_actions: list[CleaningStep] = [*normalized.steps, *boilerplate.actions]
    exact_removed = exact_dedup.metrics.duplicates_removed
    near_removed = near_dedup.metrics.near_duplicates_removed
    if exact_removed or near_removed:
        cleaning_actions.append(
            CleaningStep(
                "deduplicate_paragraphs",
                f"Removed {exact_removed} exact and {near_removed} near-duplicate paragraph(s).",
                {
                    "exact_duplicates_removed": exact_removed,
                    "near_duplicates_removed": near_removed,
                },
            )
        )

    stage_contributions = [
        _stage_contribution(
            "normalization",
            before_text=raw,
            after_text=normalized.text,
            before_tokens=original_count.value,
            after_tokens=normalized_count.value,
        ),
        _stage_contribution(
            "boilerplate",
            before_text=normalized.text,
            after_text=boilerplate.text,
            before_tokens=normalized_count.value,
            after_tokens=boilerplate_count.value,
        ),
        _stage_contribution(
            "exact_deduplication",
            before_text=boilerplate.text,
            after_text=exact_dedup.text,
            before_tokens=boilerplate_count.value,
            after_tokens=exact_dedup_count.value,
        ),
        _stage_contribution(
            "near_deduplication",
            before_text=exact_dedup.text,
            after_text=projected_text,
            before_tokens=exact_dedup_count.value,
            after_tokens=projected_count.value,
        ),
    ]

    input_info = _input_info(raw, request.source_type)
    token_budget = TokenBudgetInfo(
        model=request.model,
        token_count=original_tokens,
        token_count_method=original_count.method.value,
        tokenizer=original_count.counter,
        token_encoding=original_count.encoding,
        estimated_input_cost=estimated_cost,
        pricing_currency=pricing.currency,
        pricing_unit=pricing_unit,
        pricing_found=pricing.found,
    )
    duplication = DuplicationInfo(
        paragraphs_before=before,
        paragraphs_after_exact_dedup=after_exact,
        exact_duplicates_removed=exact_removed,
        near_duplicates_removed=near_removed,
        duplicate_ratio=duplicate_ratio,
    )
    projection = SafeCleanupProjection(
        original_tokens=original_tokens,
        projected_tokens_after_safe_cleaning=projected_tokens,
        projected_token_savings_percent=token_savings_pct,
        projected_character_savings_percent=char_savings_pct,
        estimated_cost_after_safe_cleaning=estimated_cost_after,
        estimated_cost_savings=estimated_cost_savings,
        stage_contributions=stage_contributions,
        cleaning_actions_considered=cleaning_actions,
        projection_note=_PROJECTION_NOTE,
    )

    return InspectionReport(
        schema_version=INSPECT_SCHEMA_VERSION,
        tool_version=__version__,
        input=input_info,
        token_budget=token_budget,
        structure=_structure_info(raw),
        duplication=duplication,
        safe_cleanup_projection=projection,
        recommendation=_recommendation(
            source_type=request.source_type,
            budget=token_budget,
            duplication=duplication,
            projection=projection,
        ),
        warnings=warnings,
    )
