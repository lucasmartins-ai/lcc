"""Deterministic, fixture-based benchmark harness for lcc (ADR 0007).

Runs the existing optimization pipeline over committed local fixtures and measures
mechanical behavior — token savings, compression ratio, character reduction, exact/
approximate token mode, literal marker preservation, and warnings. It makes **no claim**
about final LLM answer quality and performs no network or model calls.

This package sits above ``lcc.pipeline`` (like the CLI); it composes the pipeline and does
not change any deterministic-core contract (ADR 0002, ADR 0006).
"""

from __future__ import annotations

from lcc.benchmarking.case_loader import (
    BenchmarkCaseError,
    discover_case_dirs,
    load_case,
    load_suite,
)
from lcc.benchmarking.report import (
    suite_to_dict,
    suite_to_json,
    suite_to_markdown,
    write_suite_json,
    write_suite_markdown,
)
from lcc.benchmarking.runner import find_markers, run_case, run_suite
from lcc.benchmarking.schemas import (
    BENCH_SCHEMA_VERSION,
    BenchmarkCase,
    BenchmarkExpectations,
    CaseResult,
    SuiteResult,
)

__all__ = [
    "BENCH_SCHEMA_VERSION",
    "BenchmarkCase",
    "BenchmarkCaseError",
    "BenchmarkExpectations",
    "CaseResult",
    "SuiteResult",
    "discover_case_dirs",
    "find_markers",
    "load_case",
    "load_suite",
    "run_case",
    "run_suite",
    "suite_to_dict",
    "suite_to_json",
    "suite_to_markdown",
    "write_suite_json",
    "write_suite_markdown",
]
