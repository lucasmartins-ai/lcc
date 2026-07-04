"""Compute a deterministic diagnostic report for a text input (ADR 0009).

This module sits *above* the deterministic core (like the CLI and the benchmark harness): it
composes the cleaning and token-budget utilities to measure an input and to project what the
safe cleaning in ``lcc optimize`` would remove. It is **diagnostic, not transformative** -- it
never builds or writes a prompt (it does not import ``lcc.prompt_builder``), never calls a
network, model, or embedding service, and never modifies the input. Given identical input it
produces an identical report (ADR 0006).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from lcc import __version__
from lcc.cleaning import deduplicate_paragraphs, normalize_text, remove_common_boilerplate
from lcc.cleaning.boilerplate import BoilerplateResult
from lcc.inspection.schemas import (
    INSPECT_SCHEMA_VERSION,
    ChunkInventoryItem,
    CleanupStageContribution,
    DuplicationInfo,
    InputInfo,
    InspectionRecommendation,
    InspectionReport,
    RecommendationScoringSignal,
    SafeCleanupProjection,
    StructureInfo,
    TokenBudgetInfo,
)
from lcc.schemas import CleaningStep, TokenCountMethod
from lcc.token_budget import count_tokens
from lcc.token_budget.pricing import BUILTIN_PRICING, estimate_input_cost, get_model_pricing

# Same paragraph notion as ``lcc.cleaning.deduplicate``: blocks separated by blank lines.
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n")
_MARKDOWN_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)\s*$")

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
_TOKEN_BUDGET_PRESSURE_RATIO = 0.8


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


@dataclass(frozen=True)
class _RawChunk:
    text: str
    character_start: int
    character_end: int
    line_start: int
    line_end: int


def _split_paragraphs(text: str) -> list[str]:
    """Split text into non-empty, stripped paragraph blocks (line-ending agnostic)."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = _PARAGRAPH_SPLIT.split(normalized)
    return [block.strip() for block in blocks if block.strip()]


def _line_without_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\n", "\r")):
        return line[:-1]
    return line


def _raw_chunks(raw: str) -> list[_RawChunk]:
    """Return non-empty blocks separated by blank lines, preserving raw character offsets."""
    chunks: list[_RawChunk] = []
    start_char: int | None = None
    start_line: int | None = None
    end_char = 0
    end_line = 0
    offset = 0

    for line_number, line in enumerate(raw.splitlines(keepends=True), start=1):
        line_body = _line_without_ending(line)
        if line_body.strip():
            if start_char is None:
                start_char = offset
                start_line = line_number
            end_char = offset + len(line_body)
            end_line = line_number
        elif start_char is not None and start_line is not None:
            chunks.append(
                _RawChunk(
                    text=raw[start_char:end_char],
                    character_start=start_char,
                    character_end=end_char,
                    line_start=start_line,
                    line_end=end_line,
                )
            )
            start_char = None
            start_line = None
        offset += len(line)

    if start_char is not None and start_line is not None:
        chunks.append(
            _RawChunk(
                text=raw[start_char:end_char],
                character_start=start_char,
                character_end=end_char,
                line_start=start_line,
                line_end=end_line,
            )
        )
    return chunks


def _structural_label(chunk_text: str) -> tuple[str, str | None]:
    stripped_lines = [line.strip() for line in chunk_text.splitlines() if line.strip()]
    if len(stripped_lines) == 1:
        heading = _MARKDOWN_HEADING.match(stripped_lines[0])
        if heading:
            return "heading", heading.group(1).strip()
    if chunk_text.strip():
        return "paragraph_block", None
    return "unknown", None


def _stable_chunk_id(index: int, chunk: _RawChunk) -> str:
    digest_source = (
        f"{index}\0{chunk.character_start}\0{chunk.character_end}\0{chunk.text}"
    ).encode()
    digest = hashlib.sha256(digest_source).hexdigest()[:12]
    return f"chunk_{index + 1:04d}_{digest}"


def _chunk_inventory(raw: str, model: str) -> list[ChunkInventoryItem]:
    """Build a deterministic diagnostic inventory without selecting or rewriting content."""
    inventory: list[ChunkInventoryItem] = []
    first_seen_by_text: dict[str, str] = {}

    for index, chunk in enumerate(_raw_chunks(raw)):
        label, heading_text = _structural_label(chunk.text)
        chunk_id = _stable_chunk_id(index, chunk)
        token_count = count_tokens(chunk.text, model)
        duplicate_key = chunk.text.strip()
        duplicate_of = first_seen_by_text.get(duplicate_key)
        if duplicate_of is None:
            first_seen_by_text[duplicate_key] = chunk_id
        paragraph_count = 0 if label == "heading" else len(_split_paragraphs(chunk.text))

        inventory.append(
            ChunkInventoryItem(
                id=chunk_id,
                index=index,
                label=label,
                character_start=chunk.character_start,
                character_end=chunk.character_end,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                line_count=chunk.line_end - chunk.line_start + 1,
                paragraph_count=paragraph_count,
                character_count=chunk.character_end - chunk.character_start,
                token_count=token_count.value,
                token_count_method=token_count.method.value,
                is_duplicate=duplicate_of is not None,
                duplicate_of=duplicate_of,
                heading_text=heading_text,
            )
        )
    return inventory


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


def _score(value: float) -> float:
    return round(value, 4)


def _add_reason(reason_codes: list[str], reason_code: str) -> None:
    if reason_code not in reason_codes:
        reason_codes.append(reason_code)


def _recommendation_scoring_signals(
    *,
    budget: TokenBudgetInfo,
    duplication: DuplicationInfo,
    projection: SafeCleanupProjection,
) -> list[RecommendationScoringSignal]:
    tokens_saved = projection.original_tokens - projection.projected_tokens_after_safe_cleaning
    duplicates_removed = duplication.exact_duplicates_removed + duplication.near_duplicates_removed
    is_high_duplication = (
        duplication.duplicate_ratio >= _HIGH_DUPLICATION_RATIO and duplicates_removed > 0
    )
    is_low_savings = (
        projection.projected_token_savings_percent < _LOW_SAVINGS_PERCENT
        or tokens_saved < _LOW_SAVINGS_TOKENS
    )
    is_high_savings = (
        projection.projected_token_savings_percent >= _HIGH_SAVINGS_PERCENT
        or tokens_saved >= _HIGH_SAVINGS_TOKENS
    )
    pressure_tokens = int(_MAX_INPUT_RISK_TOKENS * _TOKEN_BUDGET_PRESSURE_RATIO)
    has_budget_pressure = projection.original_tokens >= pressure_tokens
    has_missing_pricing = not budget.pricing_found
    has_approximate_count = budget.token_count_method == TokenCountMethod.APPROXIMATE.value
    has_max_input_risk = projection.projected_tokens_after_safe_cleaning >= _MAX_INPUT_RISK_TOKENS

    projected_savings_reason = None
    if is_high_savings:
        projected_savings_reason = "high_projected_savings"
    elif is_low_savings:
        projected_savings_reason = "low_projected_savings"

    return [
        RecommendationScoringSignal(
            code="duplication_pressure",
            score=_score(duplication.duplicate_ratio / _HIGH_DUPLICATION_RATIO)
            if _HIGH_DUPLICATION_RATIO
            else 0.0,
            triggered=is_high_duplication,
            reason_code="high_duplication" if is_high_duplication else None,
            thresholds={
                "high_duplication_ratio": _HIGH_DUPLICATION_RATIO,
                "minimum_duplicates_removed": 1,
            },
            evidence={
                "duplicate_ratio": duplication.duplicate_ratio,
                "exact_duplicates_removed": duplication.exact_duplicates_removed,
                "near_duplicates_removed": duplication.near_duplicates_removed,
            },
        ),
        RecommendationScoringSignal(
            code="projected_token_savings",
            score=_score(
                max(
                    projection.projected_token_savings_percent / _HIGH_SAVINGS_PERCENT,
                    tokens_saved / _HIGH_SAVINGS_TOKENS,
                )
            ),
            triggered=projected_savings_reason is not None,
            reason_code=projected_savings_reason,
            thresholds={
                "high_savings_percent": _HIGH_SAVINGS_PERCENT,
                "high_savings_tokens": _HIGH_SAVINGS_TOKENS,
                "low_savings_percent": _LOW_SAVINGS_PERCENT,
                "low_savings_tokens": _LOW_SAVINGS_TOKENS,
            },
            evidence={
                "tokens_saved": tokens_saved,
                "original_tokens": projection.original_tokens,
                "projected_tokens_after_safe_cleaning": (
                    projection.projected_tokens_after_safe_cleaning
                ),
                "projected_token_savings_percent": (projection.projected_token_savings_percent),
            },
        ),
        RecommendationScoringSignal(
            code="token_budget_pressure",
            score=_score(projection.original_tokens / _MAX_INPUT_RISK_TOKENS)
            if _MAX_INPUT_RISK_TOKENS
            else 0.0,
            triggered=has_budget_pressure,
            reason_code="token_budget_pressure" if has_budget_pressure else None,
            thresholds={
                "max_input_risk_tokens": _MAX_INPUT_RISK_TOKENS,
                "pressure_ratio": _TOKEN_BUDGET_PRESSURE_RATIO,
                "pressure_tokens": pressure_tokens,
            },
            evidence={
                "original_tokens": projection.original_tokens,
                "projected_tokens_after_safe_cleaning": (
                    projection.projected_tokens_after_safe_cleaning
                ),
            },
        ),
        RecommendationScoringSignal(
            code="missing_pricing",
            score=1.0 if has_missing_pricing else 0.0,
            triggered=has_missing_pricing,
            reason_code="missing_pricing" if has_missing_pricing else None,
            thresholds={"pricing_required_for_cost_estimate": True},
            evidence={
                "model": budget.model,
                "pricing_found": budget.pricing_found,
                "estimated_input_cost": budget.estimated_input_cost,
            },
        ),
        RecommendationScoringSignal(
            code="approximate_token_count",
            score=1.0 if has_approximate_count else 0.0,
            triggered=has_approximate_count,
            reason_code="approximate_token_count" if has_approximate_count else None,
            thresholds={"trigger_when_token_count_method": TokenCountMethod.APPROXIMATE.value},
            evidence={
                "token_count_method": budget.token_count_method,
                "tokenizer": budget.tokenizer,
                "token_encoding": budget.token_encoding,
            },
        ),
        RecommendationScoringSignal(
            code="manual_review_risk",
            score=_score(projection.projected_tokens_after_safe_cleaning / _MAX_INPUT_RISK_TOKENS)
            if _MAX_INPUT_RISK_TOKENS
            else 0.0,
            triggered=has_max_input_risk,
            reason_code="max_input_risk" if has_max_input_risk else None,
            thresholds={"max_input_risk_tokens": _MAX_INPUT_RISK_TOKENS},
            evidence={
                "projected_tokens_after_safe_cleaning": (
                    projection.projected_tokens_after_safe_cleaning
                ),
                "projected_token_savings_percent": (projection.projected_token_savings_percent),
            },
        ),
    ]


def _recommendation(
    *,
    source_type: str,
    budget: TokenBudgetInfo,
    duplication: DuplicationInfo,
    projection: SafeCleanupProjection,
) -> InspectionRecommendation:
    tokens_saved = projection.original_tokens - projection.projected_tokens_after_safe_cleaning
    scoring_signals = _recommendation_scoring_signals(
        budget=budget,
        duplication=duplication,
        projection=projection,
    )
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
        _add_reason(reason_codes, "max_input_risk")
        summary = "Review manually; projected context is still large."
    elif is_small:
        action = "skip"
        _add_reason(reason_codes, "small_input")
        summary = "Skip optimization; projected savings are minor."
    elif is_low_savings:
        action = "skip"
        _add_reason(reason_codes, "low_projected_savings")
        summary = "Skip optimization; projected token savings are low."
    elif is_high_duplication or is_high_savings:
        action = "optimize_with_flags" if has_missing_pricing else "optimize_safe"
        if is_high_duplication:
            _add_reason(reason_codes, "high_duplication")
        else:
            _add_reason(reason_codes, "high_projected_savings")
        if action == "optimize_with_flags":
            summary = "Optimization looks useful, but add missing configuration first."
        else:
            summary = "Run safe optimization; cleanup should help."
    else:
        action = "skip"
        _add_reason(reason_codes, "low_projected_savings")
        summary = "Skip optimization; no strong cleanup opportunity was detected."

    if is_high_duplication:
        _add_reason(reason_codes, "high_duplication")
    if is_high_savings:
        _add_reason(reason_codes, "high_projected_savings")
    if is_low_savings:
        _add_reason(reason_codes, "low_projected_savings")
    for signal in scoring_signals:
        if signal.reason_code is not None:
            _add_reason(reason_codes, signal.reason_code)
    if budget.token_count_method == TokenCountMethod.APPROXIMATE.value:
        _add_reason(reason_codes, "approximate_token_count")
    if has_missing_pricing:
        _add_reason(reason_codes, "missing_pricing")

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
        scoring_signals=scoring_signals,
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
        chunk_inventory=_chunk_inventory(raw, request.model),
    )
