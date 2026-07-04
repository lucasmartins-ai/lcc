"""Prompt templates for local, verifier, remote, and final router steps."""

from __future__ import annotations

import json

from act2_router.schemas import LocalAnswer, TaskInput


def _format_expected(task: TaskInput) -> str:
    return f"\nExpected format: {task.expected_format}" if task.expected_format else ""


def build_local_prompt(task: TaskInput, context: str) -> str:
    return (
        f"Instruction: {task.instruction}{_format_expected(task)}\n\n"
        f"Context:\n{context}\n\n"
        "Answer using the context when it is relevant. Keep the answer concise."
    )


def build_remote_prompt(task: TaskInput, context: str) -> str:
    return (
        f"Task: {task.instruction}{_format_expected(task)}\n\n"
        f"Context:\n{context}\n\n"
        "Return only the requested answer. Do not include routing traces."
    )


def build_verifier_prompt(task: TaskInput, candidate: LocalAnswer) -> str:
    payload = {
        "instruction": task.instruction,
        "expected_format": task.expected_format,
        "candidate_answer": candidate.answer,
        "verifier_contract": {
            "decision": "ACCEPT_LOCAL or ESCALATE_REMOTE",
            "confidence": "0.0 to 1.0",
            "format_valid": "boolean",
            "missing_requirements": "list of strings",
            "risk_reasons": "list of strings",
            "explanation": "short string",
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def build_final_prompt(task: TaskInput, answer: str) -> str:
    return f"Task {task.task_id}\n\n{answer.strip()}"
