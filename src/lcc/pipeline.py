"""Orchestrate the deterministic optimization pipeline (ADR 0002, 0006).

The pipeline is the only module that composes the others. It performs no network or LLM
calls; given identical input it produces an identical result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lcc import __version__
from lcc.cleaning import deduplicate_paragraphs, normalize_text, remove_common_boilerplate
from lcc.cleaning.boilerplate import BoilerplateResult
from lcc.prompt_builder import PromptSpec, build_prompt
from lcc.reporting.report import build_report
from lcc.schemas import CleaningStep, CostEstimate, OptimizationReport, TokenCountMethod
from lcc.token_budget import count_tokens
from lcc.token_budget.pricing import BUILTIN_PRICING, estimate_input_cost, get_model_pricing


@dataclass
class OptimizationRequest:
    """All inputs for a single optimization run."""

    raw_text: str
    question: str
    model: str = "gpt-4.1"
    task_type: str = "general"
    constraints: list[str] = field(default_factory=list)
    max_output_tokens: int | None = None
    max_input_tokens: int | None = None
    allow_external_knowledge: bool = False
    remove_boilerplate: bool = True
    remove_near_duplicates: bool = True
    similarity_threshold: float = 0.95
    template_name: str = "default"
    pricing: dict[str, Any] | None = None


@dataclass
class OptimizationResult:
    """The optimized prompt, the cleaned context, and the report."""

    prompt: str
    cleaned_context: str
    report: OptimizationReport


def optimize(request: OptimizationRequest) -> OptimizationResult:
    """Run the full deterministic pipeline.

    Steps: normalize -> remove boilerplate -> deduplicate -> count tokens -> build prompt
    -> estimate cost -> assemble report. Nothing is summarized or rewritten; cleaning only
    removes safe, redundant, or non-meaningful text.
    """
    warnings: list[str] = []
    raw = request.raw_text
    if not raw.strip():
        warnings.append("Input text is empty or whitespace-only; nothing to optimize.")

    normalized = normalize_text(raw)
    if request.remove_boilerplate:
        boilerplate = remove_common_boilerplate(normalized.text)
    else:
        boilerplate = BoilerplateResult(text=normalized.text, actions=[])
    dedup = deduplicate_paragraphs(
        boilerplate.text,
        remove_near_duplicates=request.remove_near_duplicates,
        similarity_threshold=request.similarity_threshold,
    )
    cleaned = dedup.text
    cleaning_steps: list[CleaningStep] = [*normalized.steps, *boilerplate.actions]

    original_tokens = count_tokens(raw, request.model)
    optimized_tokens = count_tokens(cleaned, request.model)

    spec = PromptSpec(
        question=request.question,
        context=cleaned,
        task_type=request.task_type,
        constraints=request.constraints,
        max_output_tokens=request.max_output_tokens,
        allow_external_knowledge=request.allow_external_knowledge,
    )
    prompt = build_prompt(spec, request.template_name)
    prompt_tokens = count_tokens(prompt, request.model)

    if request.max_input_tokens is not None and optimized_tokens.value > request.max_input_tokens:
        warnings.append(
            f"Optimized context is {optimized_tokens.value} tokens, above the "
            f"--max-input-tokens limit of {request.max_input_tokens}. lcc does not perform "
            "lossy summarization; reduce the input or raise the limit."
        )

    if TokenCountMethod.APPROXIMATE in (original_tokens.method, optimized_tokens.method):
        message = "Token counts are approximate; treat token and cost figures as estimates."
        reason = optimized_tokens.note or original_tokens.note
        if reason:
            message = f"{message} {reason}"
        warnings.append(message)

    pricing_doc = request.pricing if request.pricing is not None else BUILTIN_PRICING
    pricing = get_model_pricing(pricing_doc, request.model)
    if not pricing.found:
        warnings.append(
            f"No pricing entry for model {request.model!r}; cost estimates are omitted. "
            "Add it to your pricing config to enable cost output."
        )

    before = estimate_input_cost(original_tokens.value, pricing.input_per_million)
    after = estimate_input_cost(optimized_tokens.value, pricing.input_per_million)
    cost = CostEstimate(
        before=before,
        after=after,
        savings=(before - after) if (before is not None and after is not None) else None,
        currency=pricing.currency,
    )

    report = build_report(
        tool_version=__version__,
        model=request.model,
        task_type=request.task_type,
        original_text=raw,
        optimized_text=cleaned,
        original_tokens=original_tokens,
        optimized_tokens=optimized_tokens,
        prompt_tokens=prompt_tokens,
        cleaning_steps=cleaning_steps,
        dedup_metrics=dedup.metrics,
        cost=cost,
        pricing=pricing,
        warnings=warnings,
    )
    return OptimizationResult(prompt=prompt, cleaned_context=cleaned, report=report)
