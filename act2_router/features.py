"""Deterministic feature extraction for routing."""

from __future__ import annotations

import re

from act2_router.config import RiskConfig
from act2_router.schemas import LCCReportSummary, TaskFeatures, TaskInput
from act2_router.token_accounting import estimate_tokens

_DEFAULT_STRICT = ["json", "csv", "yaml", "exactly", "schema", "markdown table"]
_DEFAULT_CALC = ["calculate", "compute", "exact", "numeric", "percentage"]
_DEFAULT_CODE = ["python", "javascript", "function", "bug", "error"]
_DEFAULT_EXTERNAL = ["latest", "current", "today", "internet", "web", "outside context"]
_CONFLICT_MARKERS = ["ignore previous", "disregard above", "instead answer", "contradict"]


def _contains_any(text: str, needles: list[str]) -> bool:
    haystack = text.lower()
    return any(needle.lower() in haystack for needle in needles)


def _ambiguity_score(task: TaskInput) -> float:
    text = f"{task.instruction}\n{task.context}".lower()
    score = 0.0
    if any(marker in text for marker in ["maybe", "ambiguous", "unclear", "unknown"]):
        score += 0.35
    if "?" not in task.instruction and len(task.instruction.split()) < 5:
        score += 0.25
    if _contains_any(text, _CONFLICT_MARKERS):
        score += 0.3
    return min(score, 1.0)


def _noise_score(task: TaskInput, report: LCCReportSummary) -> float:
    long_context = min(len(task.context) / 32_000.0, 1.0)
    repeated_lines = 0.0
    lines = [line.strip() for line in task.context.splitlines() if line.strip()]
    if lines:
        repeated_lines = 1.0 - (len(set(lines)) / len(lines))
    return min(
        max(report.duplicate_ratio, report.projected_savings_ratio, repeated_lines, long_context),
        1.0,
    )


def _has_conflicts(text: str) -> bool:
    lowered = text.lower()
    if _contains_any(lowered, _CONFLICT_MARKERS):
        return True
    return bool(re.search(r"\b(do not|never)\b.+\b(but|however|instead)\b", lowered))


def extract_features(
    task: TaskInput,
    lcc_report: LCCReportSummary,
    risk: RiskConfig | None = None,
) -> TaskFeatures:
    risk = risk or RiskConfig()
    strict = risk.strict_format_markers or _DEFAULT_STRICT
    calc = risk.calculation_keywords or _DEFAULT_CALC
    code = risk.code_keywords or _DEFAULT_CODE
    external = risk.external_knowledge_keywords or _DEFAULT_EXTERNAL

    combined = f"{task.instruction}\n{task.expected_format or ''}\n{task.context}"
    instruction_tokens = estimate_tokens(task.instruction)
    context_tokens = estimate_tokens(task.context)
    input_tokens = max(lcc_report.input_tokens, instruction_tokens + context_tokens)

    return TaskFeatures(
        input_tokens=input_tokens,
        context_tokens=context_tokens,
        instruction_tokens=instruction_tokens,
        projected_savings_ratio=lcc_report.projected_savings_ratio,
        duplicate_ratio=lcc_report.duplicate_ratio,
        has_strict_format=bool(task.expected_format) or _contains_any(combined, strict),
        requires_calculation=_contains_any(combined, calc),
        requires_code=_contains_any(combined, code),
        requires_external_knowledge=_contains_any(combined, external),
        ambiguity_score=_ambiguity_score(task),
        context_noise_score=_noise_score(task, lcc_report),
        lcc_recommendation=lcc_report.recommendation_action,
        has_conflicting_instructions=_has_conflicts(combined),
    )
