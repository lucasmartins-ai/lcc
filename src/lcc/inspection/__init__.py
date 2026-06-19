"""Deterministic diagnostic inspection for lcc (ADR 0009).

Analyzes a text input and reports its token, structure, duplication, cleanup, and cost
profile, plus a clearly-labelled projection of what the safe deterministic cleaning in
``lcc optimize`` would remove. It is **diagnostic, not transformative**: it never builds or
writes a prompt, performs no network or model calls, and never modifies the input.

This package sits above ``lcc.pipeline`` (like the CLI and benchmark harness); it composes
the cleaning and token-budget utilities directly and does not change any deterministic-core
contract (ADR 0002, ADR 0006).
"""

from __future__ import annotations

from lcc.inspection.inspector import InspectionRequest, inspect
from lcc.inspection.report import (
    inspection_to_dict,
    inspection_to_json,
    summary_rows,
    write_inspection_report,
)
from lcc.inspection.schemas import (
    INSPECT_SCHEMA_VERSION,
    DuplicationInfo,
    InputInfo,
    InspectionReport,
    SafeCleanupProjection,
    StructureInfo,
    TokenBudgetInfo,
)

__all__ = [
    "INSPECT_SCHEMA_VERSION",
    "DuplicationInfo",
    "InputInfo",
    "InspectionReport",
    "InspectionRequest",
    "SafeCleanupProjection",
    "StructureInfo",
    "TokenBudgetInfo",
    "inspect",
    "inspection_to_dict",
    "inspection_to_json",
    "summary_rows",
    "write_inspection_report",
]
