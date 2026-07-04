"""Serialize benchmark suite results to deterministic JSON and Markdown (ADR 0007, ADR 0010).

Like ``lcc.reporting.report``, this depends only on the benchmark schemas. Output is
deterministic: no timestamps, no random ordering, no machine-specific paths.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from lcc.benchmarking.schemas import SuiteResult


def _format_prepare_action(action: str | None) -> str:
    return action or "-"


def _format_selection_state(applied: bool | None, reason: str | None) -> str:
    if applied is None:
        return "-"
    state = "applied" if applied else "not applied"
    if reason is None:
        return state
    return f"{state}: {reason}"


def suite_to_dict(suite: SuiteResult) -> dict[str, Any]:
    """Convert a suite result to a plain, JSON-serializable dict."""
    return asdict(suite)


def suite_to_json(suite: SuiteResult, *, indent: int = 2) -> str:
    """Serialize a suite result to deterministic, pretty-printed JSON (no timestamps)."""
    return json.dumps(suite_to_dict(suite), indent=indent, ensure_ascii=False)


def write_suite_json(suite: SuiteResult, path: str | Path) -> None:
    """Write the suite report as pretty-printed JSON to ``path``."""
    Path(path).write_text(suite_to_json(suite) + "\n", encoding="utf-8")


def suite_to_markdown(suite: SuiteResult) -> str:
    """Render a human-readable Markdown report (deterministic, no timestamps)."""
    lines: list[str] = [
        "# Benchmark report",
        "",
        f"- Schema version: `{suite.schema_version}`",
        f"- Total cases: {suite.total_cases}",
        f"- Passed: {suite.passed_cases}",
        f"- Failed: {suite.failed_cases}",
        f"- Average token savings: {suite.average_token_savings_percent:.2f}%",
        f"- Average compression ratio: {suite.average_compression_ratio:.4f}",
        "",
        "> Mechanical optimization and prepare-selection metrics only: token/character "
        "reduction, literal marker checks, exact-vs-approximate token mode, prepare action, "
        "and selection state. This does **not** measure final LLM answer quality and does not "
        "perform semantic selection, embeddings, network access, model calls, summarization, "
        "rewriting, or paraphrasing (ADR 0007, ADR 0010).",
        "",
        "| Case | Status | Token savings % | Compression | Char reduction % | Token mode "
        "| Marker recall | Forbidden kept | Prepare action | Selection |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in suite.cases:
        status = "PASS" if case.passed else "FAIL"
        selection_state = _format_selection_state(case.selection_applied, case.selection_reason)
        lines.append(
            f"| {case.id} | {status} | {case.token_savings_percent:.2f} | "
            f"{case.compression_ratio:.4f} | {case.char_reduction_percent:.2f} | "
            f"{case.token_count_mode} | {case.required_marker_recall:.2f} | "
            f"{len(case.forbidden_markers_found)} | "
            f"{_format_prepare_action(case.prepare_action)} | {selection_state} |"
        )

    failed = [case for case in suite.cases if not case.passed]
    if failed:
        lines.extend(["", "## Failures", ""])
        for case in failed:
            lines.append(f"### {case.id}")
            lines.extend(f"- {reason}" for reason in case.failure_reasons)
            lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def write_suite_markdown(suite: SuiteResult, path: str | Path) -> None:
    """Write the human-readable Markdown report to ``path``."""
    Path(path).write_text(suite_to_markdown(suite), encoding="utf-8")
