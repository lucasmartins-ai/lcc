"""Feature extraction from task input and LCC context inspection."""

from __future__ import annotations

import re

from lcc.router.config import RiskConfig
from lcc.router.schemas import LCCReportSummary, TaskFeatures, TaskInput
from lcc.router.token_accounting import estimate_tokens

_DEFAULT_STRICT = ["json", "csv", "yaml", "exactly", "schema", "markdown table"]
_DEFAULT_CALC = [
    "calculate",
    "compute",
    "numeric",
    "percentage",
    "sum",
    "total",
    "add",
    "subtract",
    "multiply",
    "divide",
    "average",
    "ratio",
]
_DEFAULT_CODE = ["python", "javascript", "function", "bug", "error"]
_DEFAULT_EXTERNAL = ["latest", "current", "today", "internet", "web", "outside context"]
_CONFLICT_MARKERS = ["ignore previous", "disregard above", "instead answer", "contradict"]
_AMBIGUITY_MARKERS = [
    "maybe",
    "ambiguous",
    "unclear",
    "unknown",
    "not enough context",
    "cannot determine",
    "conflicting",
    "inconsistent",
]
_EXPLICIT_EXTERNAL_CONTEXT_MARKERS = [
    "outside context",
    "external source",
    "internet search",
    "web search",
    "public web",
    "look up online",
]
_ARITHMETIC_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s*(?:[+\-*/×x]|%)\s*\d+(?:\.\d+)?\b")
_SAYS_BUT_SAYS_PATTERN = re.compile(
    r"\b(?:say|says|state|states|report|reports)\b.+\b(?:but|while|however)\b.+\b(?:say|says|state|states|report|reports)\b",
    flags=re.DOTALL,
)


def _contains_any(text: str, needles: list[str]) -> bool:
    haystack = text.lower()
    for needle in needles:
        marker = needle.strip().lower()
        if not marker:
            continue
        escaped = re.escape(marker).replace(r"\ ", r"\s+")
        if re.fullmatch(r"[a-z0-9_\-\s]+", marker):
            pattern = rf"(?<![a-z0-9_-]){escaped}(?![a-z0-9_-])"
        else:
            pattern = escaped
        if re.search(pattern, haystack):
            return True
    return False


def _ambiguity_score(task: TaskInput) -> float:
    text = f"{task.instruction}\n{task.context}".lower()
    score = 0.0
    if _contains_any(text, _AMBIGUITY_MARKERS):
        score += 0.35
    if _SAYS_BUT_SAYS_PATTERN.search(text):
        score += 0.25
    if "?" not in task.instruction and len(task.instruction.split()) < 5:
        score += 0.25
    if _contains_any(text, _CONFLICT_MARKERS):
        score += 0.4
    return min(score, 1.0)


def _noise_score(task: TaskInput, lcc_report: LCCReportSummary) -> float:
    score = 0.0
    if lcc_report.duplicate_ratio > 0.1:
        score += min(lcc_report.duplicate_ratio, 0.5)
    if lcc_report.projected_savings_ratio > 0.15:
        score += min(lcc_report.projected_savings_ratio, 0.5)
    if "unbalanced" in " ".join(lcc_report.warnings).lower():
        score += 0.2
    return min(score, 1.0)


def _has_conflicts(text: str) -> bool:
    lowered = text.lower()
    if _contains_any(lowered, _CONFLICT_MARKERS):
        return True
    return bool(re.search(r"\b(do not|never)\b.+\b(but|however|instead)\b", lowered))


def _has_strict_format(task: TaskInput, strict_markers: list[str]) -> bool:
    expected = (task.expected_format or "").strip().lower()
    scope = f"{task.instruction}\n{expected}"
    if expected in {"", "plain", "plain text", "text", "prose"}:
        return _contains_any(task.instruction, strict_markers)
    return _contains_any(scope, strict_markers)


def _requires_external_knowledge(task: TaskInput, external_markers: list[str]) -> bool:
    request_scope = f"{task.instruction}\n{task.expected_format or ''}"
    if _contains_any(request_scope, external_markers):
        return True
    return _contains_any(task.context, _EXPLICIT_EXTERNAL_CONTEXT_MARKERS)


def _requires_calculation(text: str, calculation_markers: list[str]) -> bool:
    return _contains_any(text, calculation_markers) or bool(_ARITHMETIC_PATTERN.search(text))


def extract_features(
    task: TaskInput,
    lcc_report: LCCReportSummary,
    risk_config: RiskConfig | None = None,
) -> TaskFeatures:
    """Extract quantitative task features for routing policy decision."""
    cfg = risk_config or RiskConfig()
    strict = cfg.strict_format_markers or _DEFAULT_STRICT
    calc = cfg.calculation_keywords or _DEFAULT_CALC
    code = cfg.code_keywords or _DEFAULT_CODE
    external = cfg.external_knowledge_keywords or _DEFAULT_EXTERNAL

    combined = f"{task.instruction}\n{task.context}"
    context_tokens = estimate_tokens(task.context)
    instruction_tokens = estimate_tokens(task.instruction)

    return TaskFeatures(
        input_tokens=context_tokens + instruction_tokens,
        context_tokens=context_tokens,
        instruction_tokens=instruction_tokens,
        projected_savings_ratio=lcc_report.projected_savings_ratio,
        duplicate_ratio=lcc_report.duplicate_ratio,
        has_strict_format=_has_strict_format(task, strict),
        requires_calculation=_requires_calculation(combined, calc),
        requires_code=_contains_any(combined, code),
        requires_external_knowledge=_requires_external_knowledge(task, external),
        ambiguity_score=_ambiguity_score(task),
        context_noise_score=_noise_score(task, lcc_report),
        lcc_recommendation=lcc_report.recommendation_action,
        has_conflicting_instructions=_has_conflicts(combined),
    )
