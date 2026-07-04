"""Run benchmark cases through deterministic lcc workflows and score them (ADR 0007).

Pure and deterministic: given the same cases and environment it returns the same results.
It uses local lcc orchestration only -- no network, no model, no semantic scoring.
"""

from __future__ import annotations

from lcc.benchmarking.schemas import (
    BENCH_SCHEMA_VERSION,
    COMPRESSION_LEVELS,
    BenchmarkCase,
    CaseResult,
    SuiteResult,
)
from lcc.inspection import InspectionRequest
from lcc.inspection import inspect as run_inspection
from lcc.lexical_selection import LexicalSelectionReport, select_chunks_for_question
from lcc.pipeline import OptimizationRequest, optimize

_PREPARE_OPTIMIZE_ACTIONS = {"optimize_safe", "optimize_with_flags"}


def find_markers(text: str, markers: list[str]) -> tuple[list[str], list[str]]:
    """Split ``markers`` into ``(found, missing)`` by literal substring match against ``text``.

    Matching is case-sensitive and order-preserving. This is a literal preservation check,
    not a semantic one (ADR 0007).
    """
    found = [marker for marker in markers if marker in text]
    missing = [marker for marker in markers if marker not in text]
    return found, missing


def _recall(found: int, total: int) -> float:
    return 1.0 if total == 0 else round(found / total, 4)


def _token_savings_percent(original_tokens: int, optimized_tokens: int) -> float:
    return (
        round((1.0 - optimized_tokens / original_tokens) * 100.0, 2) if original_tokens > 0 else 0.0
    )


def _compression_ratio(original_tokens: int, optimized_tokens: int) -> float:
    return round(optimized_tokens / original_tokens, 4) if original_tokens > 0 else 1.0


def _token_count_mode(*modes: str) -> str:
    return "approximate" if "approximate" in modes else "exact"


def _optimization_request(case: BenchmarkCase, raw_text: str) -> OptimizationRequest:
    cleaning = COMPRESSION_LEVELS[case.compression_level]
    return OptimizationRequest(
        raw_text=raw_text,
        question=case.question,
        model=case.model,
        max_input_tokens=case.max_input_tokens,
        remove_boilerplate=cleaning.remove_boilerplate,
        remove_near_duplicates=cleaning.remove_near_duplicates,
        similarity_threshold=cleaning.similarity_threshold,
    )


def _selected_chunk_ids(selection_report: LexicalSelectionReport | None) -> list[str]:
    if selection_report is None:
        return []
    return [chunk.id for chunk in selection_report.selected_chunks]


def _selected_chunk_reason_codes(
    selection_report: LexicalSelectionReport | None,
) -> list[list[str]]:
    if selection_report is None:
        return []
    return [chunk.reason_codes for chunk in selection_report.selected_chunks]


def _build_case_result(
    case: BenchmarkCase,
    *,
    prompt: str,
    original_char_count: int,
    optimized_char_count: int,
    original_token_count: int,
    optimized_token_count: int,
    token_count_mode: str,
    warnings: list[str],
    prepare_action: str | None = None,
    selection_report: LexicalSelectionReport | None = None,
    extra_failure_reasons: list[str] | None = None,
) -> CaseResult:
    """Build a deterministic case result and apply every expectation gate."""
    required_found, required_missing = find_markers(prompt, case.required_markers)
    forbidden_found, _ = find_markers(prompt, case.forbidden_markers)
    recall = _recall(len(required_found), len(case.required_markers))
    char_reduction = (
        round((1.0 - optimized_char_count / original_char_count) * 100.0, 2)
        if original_char_count > 0
        else 0.0
    )
    token_savings = _token_savings_percent(original_token_count, optimized_token_count)
    compression = _compression_ratio(original_token_count, optimized_token_count)

    selection_applied = None if selection_report is None else selection_report.applied
    selection_reason = None if selection_report is None else selection_report.reason
    selected_chunk_count = (
        None if selection_report is None else selection_report.selected_chunk_count
    )
    selected_token_count = (
        None if selection_report is None else selection_report.selected_token_count
    )
    skipped_duplicate_chunk_ids = (
        [] if selection_report is None else selection_report.skipped_duplicate_chunk_ids
    )

    exp = case.expectations
    failures: list[str] = list(extra_failure_reasons or [])
    if token_savings < exp.min_token_savings_percent:
        failures.append(
            f"token_savings_percent {token_savings} is below the minimum "
            f"{exp.min_token_savings_percent}"
        )
    if token_savings > exp.max_token_savings_percent:
        failures.append(
            f"token_savings_percent {token_savings} is above the maximum "
            f"{exp.max_token_savings_percent}"
        )
    if recall < exp.min_required_marker_recall:
        failures.append(
            f"required_marker_recall {recall} is below the minimum "
            f"{exp.min_required_marker_recall}; missing markers: {required_missing}"
        )
    if len(forbidden_found) > exp.max_forbidden_markers_found:
        failures.append(
            f"{len(forbidden_found)} forbidden marker(s) survived, exceeding the maximum "
            f"{exp.max_forbidden_markers_found}: {forbidden_found}"
        )
    if token_count_mode == "approximate" and not exp.allow_approximate_token_count:
        failures.append(
            "token counting was approximate but this case requires exact counting "
            "(install tiktoken, use a model tiktoken recognizes, or set "
            "allow_approximate_token_count: true)"
        )
    if exp.expected_prepare_action is not None and prepare_action != exp.expected_prepare_action:
        failures.append(
            f"prepare_action {prepare_action!r} did not match expected action "
            f"{exp.expected_prepare_action!r}"
        )
    if (
        exp.expected_selection_applied is not None
        and selection_applied != exp.expected_selection_applied
    ):
        failures.append(
            f"selection_applied {selection_applied!r} did not match expected value "
            f"{exp.expected_selection_applied!r}"
        )

    actual_selected_count = selected_chunk_count or 0
    if (
        exp.min_selected_chunk_count is not None
        and actual_selected_count < exp.min_selected_chunk_count
    ):
        failures.append(
            f"selected_chunk_count {actual_selected_count} is below the minimum "
            f"{exp.min_selected_chunk_count}"
        )
    if (
        exp.max_selected_chunk_count is not None
        and actual_selected_count > exp.max_selected_chunk_count
    ):
        failures.append(
            f"selected_chunk_count {actual_selected_count} is above the maximum "
            f"{exp.max_selected_chunk_count}"
        )
    if len(skipped_duplicate_chunk_ids) < exp.min_skipped_duplicate_chunk_count:
        failures.append(
            f"skipped_duplicate_chunk_count {len(skipped_duplicate_chunk_ids)} is below "
            f"the minimum {exp.min_skipped_duplicate_chunk_count}"
        )

    return CaseResult(
        id=case.id,
        description=case.description,
        workflow=case.workflow,
        model=case.model,
        original_char_count=original_char_count,
        optimized_char_count=optimized_char_count,
        char_reduction_percent=char_reduction,
        original_token_count=original_token_count,
        optimized_token_count=optimized_token_count,
        token_savings_percent=token_savings,
        compression_ratio=compression,
        token_count_mode=token_count_mode,
        required_markers_total=len(case.required_markers),
        required_markers_found=required_found,
        required_markers_missing=required_missing,
        required_marker_recall=recall,
        forbidden_markers_total=len(case.forbidden_markers),
        forbidden_markers_found=forbidden_found,
        warnings=warnings,
        prepare_action=prepare_action,
        selection_applied=selection_applied,
        selection_reason=selection_reason,
        selected_chunk_count=selected_chunk_count,
        selected_token_count=selected_token_count,
        selected_chunk_ids=_selected_chunk_ids(selection_report),
        selected_chunk_reason_codes=_selected_chunk_reason_codes(selection_report),
        skipped_duplicate_chunk_ids=list(skipped_duplicate_chunk_ids),
        passed=not failures,
        failure_reasons=failures,
    )


def _run_optimize_case(case: BenchmarkCase) -> CaseResult:
    result = optimize(_optimization_request(case, case.input_text))
    report = result.report
    return _build_case_result(
        case,
        prompt=result.prompt,
        original_char_count=report.original_char_count,
        optimized_char_count=report.optimized_char_count,
        original_token_count=report.original_token_count,
        optimized_token_count=report.optimized_token_count,
        token_count_mode=report.token_count_method.value,
        warnings=list(report.warnings),
    )


def _run_prepare_case(case: BenchmarkCase) -> CaseResult:
    """Run deterministic prepare orchestration without CLI presentation concerns."""
    cleaning = COMPRESSION_LEVELS[case.compression_level]
    inspection = run_inspection(
        InspectionRequest(
            raw_text=case.input_text,
            model=case.model,
            remove_boilerplate=cleaning.remove_boilerplate,
            remove_near_duplicates=cleaning.remove_near_duplicates,
            similarity_threshold=cleaning.similarity_threshold,
        )
    )
    action = inspection.recommendation.action
    if action not in _PREPARE_OPTIMIZE_ACTIONS:
        return _build_case_result(
            case,
            prompt="",
            original_char_count=len(case.input_text),
            optimized_char_count=0,
            original_token_count=inspection.token_budget.token_count,
            optimized_token_count=0,
            token_count_mode=inspection.token_budget.token_count_method,
            warnings=list(inspection.warnings),
            prepare_action=action,
            extra_failure_reasons=[
                f"prepare action {action!r} did not generate a prompt for benchmarking"
            ],
        )

    selection = select_chunks_for_question(
        raw_text=case.input_text,
        question=case.question,
        chunk_inventory=inspection.chunk_inventory,
    )
    optimization = optimize(_optimization_request(case, selection.selected_text))
    report = optimization.report
    return _build_case_result(
        case,
        prompt=optimization.prompt,
        original_char_count=len(case.input_text),
        optimized_char_count=report.optimized_char_count,
        original_token_count=inspection.token_budget.token_count,
        optimized_token_count=report.optimized_token_count,
        token_count_mode=_token_count_mode(
            inspection.token_budget.token_count_method,
            report.token_count_method.value,
        ),
        warnings=[*inspection.warnings, *report.warnings],
        prepare_action=action,
        selection_report=selection.report,
    )


def run_case(case: BenchmarkCase) -> CaseResult:
    """Run one case and compute its mechanical metrics and pass/fail outcome.

    For ``workflow: prepare``, the runner mirrors ``lcc prepare``: inspect first, branch only
    on ``recommendation.action``, then apply deterministic lexical selection before the safe
    optimization path when the action says to optimize.
    """
    if case.workflow == "prepare":
        return _run_prepare_case(case)
    return _run_optimize_case(case)


def run_suite(cases: list[BenchmarkCase]) -> SuiteResult:
    """Run all cases (ordered by id for determinism) and aggregate a suite report."""
    ordered = sorted(cases, key=lambda case: case.id)
    results = [run_case(case) for case in ordered]
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    if total:
        avg_savings = round(sum(r.token_savings_percent for r in results) / total, 2)
        avg_ratio = round(sum(r.compression_ratio for r in results) / total, 4)
    else:
        avg_savings = 0.0
        avg_ratio = 0.0
    return SuiteResult(
        schema_version=BENCH_SCHEMA_VERSION,
        total_cases=total,
        passed_cases=passed,
        failed_cases=total - passed,
        average_token_savings_percent=avg_savings,
        average_compression_ratio=avg_ratio,
        cases=results,
    )
