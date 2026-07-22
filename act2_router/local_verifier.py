"""Local quality gates for accepting or escalating local answers."""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from act2_router.config import PolicyConfig
from act2_router.prompt_builder import build_verifier_prompt
from act2_router.schemas import (
    LCCReportSummary,
    LocalAnswer,
    TaskFeatures,
    TaskInput,
    VerificationDecision,
    VerificationResult,
)


class RuleBasedVerifier:
    """Conservative structured gate. Uncertainty escalates."""

    def __init__(self, accept_confidence: float = 0.78) -> None:
        self.accept_confidence = accept_confidence

    def verify(
        self,
        task: TaskInput,
        candidate: LocalAnswer,
        lcc_report: LCCReportSummary,
        features: TaskFeatures,
    ) -> VerificationResult:
        missing: list[str] = []
        risks: list[str] = []
        answer = candidate.answer.strip()
        format_valid = True
        confidence = 0.88
        parsed_json = _json_value(answer) if _expects_json(task.expected_format) else None

        if not answer:
            missing.append("non-empty answer")
            risks.append("candidate_answer_empty")
            confidence -= 0.5

        if task.expected_format:
            valid, requirement = _format_valid(task.expected_format, answer)
            if not valid:
                format_valid = False
                missing.append(requirement)
                risks.append("strict_format_failed")
                confidence -= 0.3

        for field in task.metadata.get("required_fields", []) or []:
            if isinstance(parsed_json, dict):
                field_missing = str(field) not in parsed_json
            else:
                field_missing = str(field) not in answer
            if field_missing:
                missing.append(f"field:{field}")
                confidence -= 0.08

        if features.requires_calculation:
            expected_result = _simple_calculation_result(task)
            if expected_result is None:
                risks.append("calculation_not_deterministically_verified")
                confidence -= 0.12
            elif not _answer_contains_number(answer, expected_result):
                rendered = _render_decimal(expected_result)
                missing.append(f"calculated result:{rendered}")
                risks.append("calculation_result_mismatch")
                confidence -= 0.35

        if features.requires_external_knowledge:
            risks.append("external_knowledge_required")
            confidence -= 0.28
        if features.has_conflicting_instructions:
            risks.append("conflicting_instructions")
            confidence -= 0.25
        if features.ambiguity_score >= 0.45:
            if _acknowledges_ambiguity(answer):
                risks.append("ambiguity_acknowledged")
                confidence -= 0.04
            else:
                missing.append("ambiguity_acknowledgement")
                risks.append("overconfident_ambiguous_answer")
                confidence -= 0.25
        if features.ambiguity_score >= 0.65:
            risks.append("ambiguous_task")
            confidence -= 0.18
        if lcc_report.recommendation_action == "manual_review":
            risks.append("lcc_manual_review")
            confidence -= 0.25
        if _looks_unsupported(task, answer):
            risks.append("possible_unsupported_claims")
            confidence -= 0.12

        confidence = round(max(0.0, min(confidence, 1.0)), 2)
        decision = (
            VerificationDecision.ACCEPT_LOCAL
            if confidence >= self.accept_confidence and format_valid and not missing
            else VerificationDecision.ESCALATE_REMOTE
        )
        explanation = (
            "Local answer passed deterministic format and risk checks."
            if decision == VerificationDecision.ACCEPT_LOCAL
            else "Local answer did not clear the conservative acceptance gate."
        )
        return VerificationResult(
            decision=decision,
            confidence=confidence,
            format_valid=format_valid,
            missing_requirements=missing,
            risk_reasons=risks,
            explanation=explanation,
        )


class LocalLLMVerifier:
    """Optional local-model verifier with rule-based fallback."""

    def __init__(self, solver: Any, fallback: RuleBasedVerifier) -> None:
        self.solver = solver
        self.fallback = fallback

    def verify(
        self,
        task: TaskInput,
        candidate: LocalAnswer,
        lcc_report: LCCReportSummary,
        features: TaskFeatures,
    ) -> VerificationResult:
        try:
            verifier_task = TaskInput(
                task_id=f"{task.task_id}:verify",
                instruction="Return only verifier JSON.",
                context=build_verifier_prompt(task, candidate),
                expected_format="json",
            )
            raw = self.solver.solve(verifier_task, verifier_task.context).answer
            payload = _extract_json(raw)
            return VerificationResult(
                decision=VerificationDecision(str(payload["decision"])),
                confidence=float(payload["confidence"]),
                format_valid=bool(payload["format_valid"]),
                missing_requirements=[
                    str(item) for item in payload.get("missing_requirements", [])
                ],
                risk_reasons=[str(item) for item in payload.get("risk_reasons", [])],
                explanation=str(payload.get("explanation", "")),
            )
        except Exception:
            return self.fallback.verify(task, candidate, lcc_report, features)


def _format_valid(expected_format: str, answer: str) -> tuple[bool, str]:
    marker = expected_format.lower()
    if "json" in marker:
        try:
            value = json.loads(answer)
        except json.JSONDecodeError:
            return False, "valid JSON object"
        if "array" in marker:
            if not isinstance(value, list):
                return False, "valid JSON array"
        elif not isinstance(value, dict):
            return False, "valid JSON object"
    if "yaml" in marker and ":" not in answer:
        return False, "YAML-like key/value output"
    if "csv" in marker and "," not in answer:
        return False, "CSV output"
    if "markdown table" in marker and "|" not in answer:
        return False, "markdown table"
    if "exactly" in marker and not answer:
        return False, "exact requested output"
    return True, ""


def _expects_json(expected_format: str | None) -> bool:
    return bool(expected_format and "json" in expected_format.lower())


def _json_value(answer: str) -> Any | None:
    try:
        return json.loads(answer)
    except json.JSONDecodeError:
        return None


def _acknowledges_ambiguity(answer: str) -> bool:
    return bool(
        re.search(
            r"\b(ambiguous|unclear|unknown|cannot determine|not enough context|conflicting)\b",
            answer,
            flags=re.IGNORECASE,
        )
    )


def _simple_calculation_result(task: TaskInput) -> Decimal | None:
    text = f"{task.instruction}\n{task.context}"
    match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*([+\-*/×x])\s*(-?\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        left = Decimal(match.group(1))
        right = Decimal(match.group(3))
    except InvalidOperation:
        return None
    operator = match.group(2).lower()
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator in {"*", "x", "×"}:
        return left * right
    if operator == "/" and right != 0:
        return left / right
    return None


def _answer_contains_number(answer: str, expected: Decimal) -> bool:
    for raw in re.findall(r"-?\d+(?:\.\d+)?", answer):
        try:
            if Decimal(raw) == expected:
                return True
        except InvalidOperation:
            continue
    return False


def _render_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _looks_unsupported(task: TaskInput, answer: str) -> bool:
    if not task.context.strip():
        return False
    answer_terms = {
        item.lower()
        for item in re.findall(r"[A-Za-z][A-Za-z0-9_-]{5,}", answer)
        if item.lower() not in {"answer", "context", "because"}
    }
    context = task.context.lower()
    unknown = [term for term in answer_terms if term not in context]
    return len(unknown) >= 4


def _extract_json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("verifier output must be a JSON object")
    return value


def create_verifier(policy: PolicyConfig, solver: Any | None = None) -> Any:
    fallback = RuleBasedVerifier(policy.router.local_accept_confidence)
    if os.getenv("LOCAL_VERIFIER_BACKEND", "rule").lower() == "local_llm" and solver is not None:
        return LocalLLMVerifier(solver=solver, fallback=fallback)
    return fallback
