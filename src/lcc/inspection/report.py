"""Serialize inspection reports to deterministic JSON (ADR 0009).

Like ``lcc.reporting.report`` and ``lcc.benchmarking.report``, this depends only on the
inspection schemas. Output is deterministic: no timestamps, no random ordering, and no
machine-specific paths.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from lcc.inspection.schemas import InspectionReport


def inspection_to_dict(report: InspectionReport) -> dict[str, Any]:
    """Convert an inspection report to a plain, JSON-serializable dict."""
    return asdict(report)


def inspection_to_json(report: InspectionReport, *, indent: int = 2) -> str:
    """Serialize an inspection report to deterministic, pretty-printed JSON (no timestamps)."""
    return json.dumps(inspection_to_dict(report), indent=indent, ensure_ascii=False)


def write_inspection_report(report: InspectionReport, path: str | Path) -> None:
    """Write the inspection report as pretty-printed JSON to ``path``."""
    Path(path).write_text(inspection_to_json(report) + "\n", encoding="utf-8")


def summary_rows(report: InspectionReport) -> list[tuple[str, str]]:
    """Produce ``(label, value)`` rows for a concise human-readable summary (used by the CLI)."""
    budget = report.token_budget
    projection = report.safe_cleanup_projection
    duplication = report.duplication
    if budget.estimated_input_cost is not None:
        cost = f"{budget.estimated_input_cost:.6f} {budget.pricing_currency}"
    else:
        cost = "n/a (no pricing for model)"
    return [
        ("Source", report.input.source_type),
        ("Characters", f"{report.input.character_count:,}"),
        ("Model", budget.model),
        ("Token counting", f"{budget.token_count_method} ({budget.tokenizer})"),
        ("Input tokens", f"{budget.token_count:,}"),
        ("Est. input cost", cost),
        (
            "Duplicate paragraphs (projection)",
            f"{duplication.exact_duplicates_removed} exact + "
            f"{duplication.near_duplicates_removed} near",
        ),
        ("Projected token savings", f"{projection.projected_token_savings_percent:.1f}%"),
        ("Projected char savings", f"{projection.projected_character_savings_percent:.1f}%"),
    ]
