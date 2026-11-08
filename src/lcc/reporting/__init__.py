"""Report assembly and JSON serialization."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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

# ponytail: names load on first use: `lcc hint` (every prompt) needs only `explain`.
_EXPORTS = {
    "lcc.reporting.explain": ("explain_reason", "render", "summarize"),
    "lcc.reporting.report": (
        "build_report",
        "report_to_dict",
        "report_to_json",
        "summary_rows",
        "write_report",
    ),
}
_HOME = {name: module for module, names in _EXPORTS.items() for name in names}


def __getattr__(name: str) -> Any:
    if name not in _HOME:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_HOME[name]), name)
    globals()[name] = value
    return value
