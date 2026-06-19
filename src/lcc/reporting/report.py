"""Assemble the ``OptimizationReport`` and serialize it to JSON.

This module depends only on ``lcc.schemas`` (ADR 0002): the pipeline computes costs and
passes them in, so reporting never imports the token/pricing modules.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from lcc.schemas import (
    SCHEMA_VERSION,
    CleaningStep,
    CostEstimate,
    DedupMetrics,
    OptimizationReport,
    PricingInfo,
    TokenCount,
)


def build_report(
    *,
    tool_version: str,
    model: str,
    task_type: str,
    original_text: str,
    optimized_text: str,
    original_tokens: TokenCount,
    optimized_tokens: TokenCount,
    prompt_tokens: TokenCount,
    cleaning_steps: list[CleaningStep],
    dedup_metrics: DedupMetrics,
    cost: CostEstimate,
    pricing: PricingInfo,
    warnings: list[str],
) -> OptimizationReport:
    """Assemble a complete ``OptimizationReport`` from computed pieces.

    Derives the compression ratio and token-savings percentage from the token counts.
    ``token_count_method`` records the optimized count's method; the pipeline guarantees
    the original and optimized counts share that method (and warns if they ever differ).
    """
    original = original_tokens.value
    optimized = optimized_tokens.value
    ratio = (optimized / original) if original > 0 else 1.0
    savings_pct = (1.0 - ratio) * 100.0 if original > 0 else 0.0

    return OptimizationReport(
        schema_version=SCHEMA_VERSION,
        tool_version=tool_version,
        model=model,
        task_type=task_type,
        original_char_count=len(original_text),
        optimized_char_count=len(optimized_text),
        original_token_count=original,
        optimized_token_count=optimized,
        prompt_token_count=prompt_tokens.value,
        compression_ratio=round(ratio, 4),
        token_savings_percent=round(savings_pct, 2),
        token_count_method=optimized_tokens.method,
        token_counter=optimized_tokens.counter,
        token_encoding=optimized_tokens.encoding,
        cost=cost,
        pricing=pricing,
        cleaning_steps=cleaning_steps,
        dedup_metrics=dedup_metrics,
        warnings=warnings,
    )


def _normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def report_to_dict(report: OptimizationReport) -> dict[str, Any]:
    """Convert a report to a plain, JSON-serializable dict (enums become their values)."""
    return _normalize(asdict(report))


def report_to_json(report: OptimizationReport, *, indent: int = 2) -> str:
    """Serialize a report to a pretty-printed JSON string."""
    return json.dumps(report_to_dict(report), indent=indent, ensure_ascii=False)


def write_report(report: OptimizationReport, path: str | Path) -> None:
    """Write the report as pretty-printed JSON to ``path``."""
    Path(path).write_text(report_to_json(report) + "\n", encoding="utf-8")


def summary_rows(report: OptimizationReport) -> list[tuple[str, str]]:
    """Produce ``(label, value)`` rows for a human-readable summary (used by the CLI)."""
    cost = report.cost
    if cost.before is not None and cost.after is not None:
        before = f"{cost.before:.6f} {cost.currency}"
        after = f"{cost.after:.6f} {cost.currency}"
        savings = f"{(cost.savings or 0.0):.6f} {cost.currency}"
    else:
        before = after = savings = "n/a (no pricing for model)"
    return [
        ("Model", report.model),
        ("Token counting", f"{report.token_count_method.value} ({report.token_counter})"),
        ("Original tokens", f"{report.original_token_count:,}"),
        ("Optimized tokens", f"{report.optimized_token_count:,}"),
        ("Token savings", f"{report.token_savings_percent:.1f}%"),
        ("Compression ratio", f"{report.compression_ratio:.3f}"),
        ("Full prompt tokens", f"{report.prompt_token_count:,}"),
        ("Est. cost before", before),
        ("Est. cost after", after),
        ("Est. cost savings", savings),
    ]
