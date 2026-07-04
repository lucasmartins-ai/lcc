"""Adapter over existing LCC capabilities.

This module may call LCC inspection/optimization APIs, but LCC never imports this module.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from act2_router.schemas import LCCReportSummary, PreparedContext, TaskInput


def _failure_summary(task: TaskInput, message: str) -> LCCReportSummary:
    from act2_router.token_accounting import estimate_tokens

    tokens = estimate_tokens(task.context)
    return LCCReportSummary(
        input_tokens=tokens,
        optimized_tokens=tokens,
        projected_savings_ratio=0.0,
        duplicate_ratio=0.0,
        recommendation_action="lcc_failed",
        warnings=[message],
        selected_chunks_count=0,
    )


def inspect_context(task: TaskInput) -> LCCReportSummary:
    """Run deterministic LCC inspection and return the router subset."""
    try:
        from lcc.inspection import InspectionRequest
        from lcc.inspection import inspect as run_inspection

        report = run_inspection(
            InspectionRequest(
                raw_text=task.context,
                source_type="file",
                model=str(task.metadata.get("token_model", "gpt-4.1")),
            )
        )
        original = report.safe_cleanup_projection.original_tokens
        optimized = report.safe_cleanup_projection.projected_tokens_after_safe_cleaning
        savings = ((original - optimized) / original) if original > 0 else 0.0
        return LCCReportSummary(
            input_tokens=original,
            optimized_tokens=optimized,
            projected_savings_ratio=round(max(savings, 0.0), 4),
            duplicate_ratio=report.duplication.duplicate_ratio,
            recommendation_action=report.recommendation.action,
            warnings=list(report.warnings),
            selected_chunks_count=0,
        )
    except Exception as exc:  # fail closed: route can still proceed on original context
        return _failure_summary(task, f"LCC inspection failed; original context preserved: {exc}")


def prepare_context(task: TaskInput) -> PreparedContext:
    """Run deterministic LCC prepare-like behavior with Python APIs."""
    try:
        from lcc.inspection import InspectionRequest
        from lcc.inspection import inspect as run_inspection
        from lcc.lexical_selection import select_chunks_for_question
        from lcc.pipeline import OptimizationRequest
        from lcc.pipeline import optimize as run_optimize

        model = str(task.metadata.get("token_model", "gpt-4.1"))
        inspection = run_inspection(
            InspectionRequest(raw_text=task.context, source_type="file", model=model)
        )
        action = inspection.recommendation.action
        selected_text = task.context
        selected_count = 0
        selection_applied = False
        if action in {"optimize_safe", "optimize_with_flags"}:
            selection = select_chunks_for_question(
                raw_text=task.context,
                question=task.instruction,
                chunk_inventory=inspection.chunk_inventory,
            )
            selected_text = selection.selected_text
            selected_count = selection.report.selected_chunk_count
            selection_applied = selection.applied

        optimized = run_optimize(
            OptimizationRequest(
                raw_text=selected_text,
                question=task.instruction,
                model=model,
                constraints=[task.expected_format] if task.expected_format else [],
            )
        )
        original = inspection.safe_cleanup_projection.original_tokens
        optimized_tokens = optimized.report.optimized_token_count
        savings = ((original - optimized_tokens) / original) if original > 0 else 0.0
        summary = LCCReportSummary(
            input_tokens=original,
            optimized_tokens=optimized_tokens,
            projected_savings_ratio=round(max(savings, 0.0), 4),
            duplicate_ratio=inspection.duplication.duplicate_ratio,
            recommendation_action=action,
            warnings=[*inspection.warnings, *optimized.report.warnings],
            selected_chunks_count=selected_count,
        )
        return PreparedContext(
            context=optimized.cleaned_context,
            prompt=optimized.prompt,
            lcc_summary=summary,
            compression_applied=selection_applied or optimized_tokens < original,
            warnings=summary.warnings,
        )
    except Exception as exc:
        summary = _failure_summary(task, f"LCC prepare failed; original context preserved: {exc}")
        return PreparedContext(
            context=task.context,
            prompt=f"{task.instruction}\n\n{task.context}",
            lcc_summary=summary,
            compression_applied=False,
            warnings=summary.warnings,
        )


def optimize_context_if_needed(task: TaskInput, policy: Any) -> PreparedContext:
    """Return optimized context when LCC predicts enough savings, otherwise original context."""
    summary = inspect_context(task)
    threshold = getattr(
        getattr(policy, "router", policy),
        "compress_if_projected_savings_above",
        0.15,
    )
    if summary.recommendation_action in {"optimize_safe", "optimize_with_flags"} and (
        summary.projected_savings_ratio >= threshold
    ):
        return prepare_context(task)
    return PreparedContext(
        context=task.context,
        prompt=f"{task.instruction}\n\n{task.context}",
        lcc_summary=replace(summary),
        compression_applied=False,
        warnings=summary.warnings,
    )
