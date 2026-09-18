"""Deterministic intake analysis, intent classification, and brief structuring.

Part of the unified LCC engine. Analyzes raw, unstructured, voice-like, or ambiguous
prompts before compression and model dispatch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class ReadinessState(StrEnum):
    """Readiness classification for incoming prompt context."""

    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    NEEDS_LIGHT_REFINEMENT = "NEEDS_LIGHT_REFINEMENT"
    NEEDS_INTAKE = "NEEDS_INTAKE"
    BLOCKED = "BLOCKED"


@dataclass
class StructuredBrief:
    """Extracted fields from unstructured input."""

    objective: str
    deliverable: str
    context: str
    audience: str
    constraints: list[str] = field(default_factory=list)
    format_requirements: list[str] = field(default_factory=list)
    critical_gaps: list[str] = field(default_factory=list)


@dataclass
class ParsedIntake:
    """Structured result from intake parsing."""

    raw_input: str
    intent: str
    readiness: ReadinessState
    readiness_score: int
    ambiguity_score: int
    questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    brief: StructuredBrief = field(
        default_factory=lambda: StructuredBrief(
            objective="",
            deliverable="",
            context="",
            audience="general",
            constraints=[],
            format_requirements=[],
            critical_gaps=[],
        )
    )


_UNSAFE_PATTERNS = [
    re.compile(
        r"\b(bypass\s+security|exploit\s+vulnerability|steal\s+credentials|dump\s+passwords)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(ignore\s+all\s+previous\s+instructions|jailbreak)\b", re.IGNORECASE),
]

_VAGUE_MARKERS = [
    "maybe",
    "something with",
    "not sure",
    "i guess",
    "kind of",
    "sort of",
    "alguma coisa",
    "talvez",
    "não sei bem",
    "algo assim",
]


def parse_intake(raw_input: str) -> ParsedIntake:
    """Parse and classify raw user input into a deterministic readiness state and brief."""
    text = (raw_input or "").strip()
    if not text:
        return ParsedIntake(
            raw_input="",
            intent="Empty request",
            readiness=ReadinessState.BLOCKED,
            readiness_score=0,
            ambiguity_score=100,
            questions=["Please provide a valid prompt, objective, or context file."],
            assumptions=[],
            brief=StructuredBrief(
                objective="None",
                deliverable="None",
                context="",
                audience="unknown",
                critical_gaps=["No input text provided."],
            ),
        )

    # Check unsafe/adversarial patterns
    for pattern in _UNSAFE_PATTERNS:
        if pattern.search(text):
            return ParsedIntake(
                raw_input=text,
                intent="Unsafe or blocked operation",
                readiness=ReadinessState.BLOCKED,
                readiness_score=0,
                ambiguity_score=100,
                questions=["Request violates safety boundary or operational constraints."],
                assumptions=[],
                brief=StructuredBrief(
                    objective="Blocked",
                    deliverable="None",
                    context=text,
                    audience="system",
                    critical_gaps=["Violates safety guardrails."],
                ),
            )

    words = text.split()
    word_count = len(words)
    has_question = "?" in text
    lowered = text.lower()

    # Detect ambiguity indicators
    vague_hits = [marker for marker in _VAGUE_MARKERS if marker in lowered]

    readiness = ReadinessState.READY_TO_EXECUTE
    readiness_score = 90
    ambiguity_score = 10
    questions: list[str] = []
    assumptions: list[str] = []
    critical_gaps: list[str] = []

    if vague_hits or (
        word_count < 6
        and not has_question
        and ("test" in lowered or "check" in lowered or "fix" in lowered)
    ):
        if vague_hits:
            readiness = ReadinessState.NEEDS_INTAKE
            readiness_score = 40
            ambiguity_score = 60
            questions.append("What is the exact deliverable and primary success criterion?")
            questions.append("Are there specific architectural or runtime constraints?")
            critical_gaps.append(f"Contains ambiguous phrasing: {', '.join(vague_hits)}")
        else:
            readiness = ReadinessState.NEEDS_LIGHT_REFINEMENT
            readiness_score = 70
            ambiguity_score = 30
            assumptions.append(f"Interpreted '{text}' as an operational technical directive.")
    elif word_count < 4 and not has_question:
        readiness = ReadinessState.NEEDS_LIGHT_REFINEMENT
        readiness_score = 75
        ambiguity_score = 25
        assumptions.append(f"Executing '{text}' with default technical guidelines.")

    intent_preview = text[:80] + ("..." if len(text) > 80 else "")

    brief = StructuredBrief(
        objective=intent_preview,
        deliverable="Code / Refactored Context / Direct Analysis",
        context=text,
        audience="developer",
        constraints=["Maintain codebase stability", "Preserve types and contracts"],
        format_requirements=["Clean diff or structured response"],
        critical_gaps=critical_gaps,
    )

    return ParsedIntake(
        raw_input=text,
        intent=intent_preview,
        readiness=readiness,
        readiness_score=readiness_score,
        ambiguity_score=ambiguity_score,
        questions=questions,
        assumptions=assumptions,
        brief=brief,
    )
