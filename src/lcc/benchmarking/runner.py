"""Run benchmark cases through the deterministic pipeline and score them (ADR 0007).

Pure and deterministic: given the same cases and environment it returns the same results.
It calls only ``lcc.pipeline.optimize`` — no network, no model, no semantic scoring.
"""

from __future__ import annotations

from lcc.benchmarking.schemas import (
    BENCH_SCHEMA_VERSION,
    COMPRESSION_LEVELS,
    BenchmarkCase,
    CaseResult,
    SuiteResult,
)
from lcc.pipeline import OptimizationRequest, optimize


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


def run_case(case: BenchmarkCase) -> CaseResult:
    """Optimize one case and compute its mechanical metrics and pass/fail outcome.

    Markers are checked against the rendered optimized prompt (the artifact that would be
    sent to a model); the cleaned context is embedded in that prompt.
    """
    cleaning = COMPRESSION_LEVELS[case.compression_level]
    request = OptimizationRequest(
        raw_text=case.input_text,
        question=case.question,
        model=case.model,
        max_input_tokens=case.max_input_tokens,
        remove_boilerplate=cleaning.remove_boilerplate,
        remove_near_duplicates=cleaning.remove_near_duplicates,
        similarity_threshold=cleaning.similarity_threshold,
    )
    result = optimize(request)
    report = result.report
    prompt = result.prompt

    required_found, required_missing = find_markers(prompt, case.required_markers)
    forbidden_found, _ = find_markers(prompt, case.forbidden_markers)
    recall = _recall(len(required_found), len(case.required_markers))

    original_chars = report.original_char_count
    optimized_chars = report.optimized_char_count
    char_reduction = (
        round((1.0 - optimized_chars / original_chars) * 100.0, 2) if original_chars > 0 else 0.0
    )
    mode = report.token_count_method.value

    exp = case.expectations
    failures: list[str] = []
    if report.token_savings_percent < exp.min_token_savings_percent:
        failures.append(
            f"token_savings_percent {report.token_savings_percent} is below the minimum "
            f"{exp.min_token_savings_percent}"
        )
    if report.token_savings_percent > exp.max_token_savings_percent:
        failures.append(
            f"token_savings_percent {report.token_savings_percent} is above the maximum "
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
    if mode == "approximate" and not exp.allow_approximate_token_count:
        failures.append(
            "token counting was approximate but this case requires exact counting "
            "(install tiktoken, use a model tiktoken recognizes, or set "
            "allow_approximate_token_count: true)"
        )

    return CaseResult(
        id=case.id,
        description=case.description,
        model=case.model,
        original_char_count=original_chars,
        optimized_char_count=optimized_chars,
        char_reduction_percent=char_reduction,
        original_token_count=report.original_token_count,
        optimized_token_count=report.optimized_token_count,
        token_savings_percent=report.token_savings_percent,
        compression_ratio=report.compression_ratio,
        token_count_mode=mode,
        required_markers_total=len(case.required_markers),
        required_markers_found=required_found,
        required_markers_missing=required_missing,
        required_marker_recall=recall,
        forbidden_markers_total=len(case.forbidden_markers),
        forbidden_markers_found=forbidden_found,
        warnings=list(report.warnings),
        passed=not failures,
        failure_reasons=failures,
    )


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
