"""Programmatic interface for Local Context Compiler (lcc) compression engine.

Exports LccCompressor and LccOptimizer classes to provide a clean, local-first,
zero-network context compression API for Python applications and pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lcc.pipeline import OptimizationRequest, OptimizationResult, optimize
from lcc.schemas import CleaningStep, CostEstimate


@dataclass
class CompressionResult:
    """Structured response from LccCompressor."""

    raw_text: str
    compressed_text: str
    original_tokens: int
    compressed_tokens: int
    saved_tokens: int
    savings_percentage: float
    cleaning_steps: list[CleaningStep]
    cost: CostEstimate
    report: OptimizationResult


class LccCompressor:
    """Programmatic API for local context compression and token estimation."""

    def __init__(
        self,
        model: str = "gpt-4.1",
        strategy: str = "local-first",
        max_tokens: int | None = None,
        remove_boilerplate: bool = True,
        remove_near_duplicates: bool = True,
        similarity_threshold: float = 0.95,
        template_name: str = "default",
        pricing: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self.strategy = strategy
        self.max_tokens = max_tokens
        self.remove_boilerplate = remove_boilerplate
        self.remove_near_duplicates = remove_near_duplicates
        self.similarity_threshold = similarity_threshold
        self.template_name = template_name
        self.pricing = pricing

    def compress(
        self,
        raw_text: str,
        question: str = "",
        task_type: str = "general",
        constraints: list[str] | None = None,
    ) -> CompressionResult:
        """Compress raw text context locally using deterministic lcc pipeline."""
        req = OptimizationRequest(
            raw_text=raw_text,
            question=question,
            model=self.model,
            task_type=task_type,
            constraints=constraints or [],
            max_input_tokens=self.max_tokens,
            remove_boilerplate=self.remove_boilerplate,
            remove_near_duplicates=self.remove_near_duplicates,
            similarity_threshold=self.similarity_threshold,
            template_name=self.template_name,
            pricing=self.pricing,
        )
        res = optimize(req)

        orig_val = res.report.original_token_count
        comp_val = res.report.optimized_token_count
        saved_val = max(0, orig_val - comp_val)
        pct = res.report.token_savings_percent

        return CompressionResult(
            raw_text=raw_text,
            compressed_text=res.cleaned_context,
            original_tokens=orig_val,
            compressed_tokens=comp_val,
            saved_tokens=saved_val,
            savings_percentage=round(pct, 2),
            cleaning_steps=res.report.cleaning_steps,
            cost=res.report.cost,
            report=res,
        )

    def optimize(
        self,
        raw_text: str,
        question: str = "",
        task_type: str = "general",
        constraints: list[str] | None = None,
    ) -> OptimizationResult:
        """Run standard optimization pipeline returning complete OptimizationResult."""
        req = OptimizationRequest(
            raw_text=raw_text,
            question=question,
            model=self.model,
            task_type=task_type,
            constraints=constraints or [],
            max_input_tokens=self.max_tokens,
            remove_boilerplate=self.remove_boilerplate,
            remove_near_duplicates=self.remove_near_duplicates,
            similarity_threshold=self.similarity_threshold,
            template_name=self.template_name,
            pricing=self.pricing,
        )
        return optimize(req)


# Alias for backward compatibility / explicit terminology
LccOptimizer = LccCompressor
