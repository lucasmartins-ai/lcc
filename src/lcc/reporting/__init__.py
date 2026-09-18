"""Report assembly and JSON serialization."""

from __future__ import annotations

from lcc.reporting.explain import explain_reason, render, summarize
from lcc.reporting.report import (
    build_report,
    report_to_dict,
    report_to_json,
    summary_rows,
    write_report,
)

__all__ = [
    "build_report",
    "explain_reason",
    "render",
    "report_to_dict",
    "report_to_json",
    "summarize",
    "summary_rows",
    "write_report",
]
