"""Deterministic intake analysis: readiness, named reasons, risk flags and a derived brief.

Part of the unified LCC engine. Analyzes raw, unstructured, voice-like, or ambiguous
prompts before compression and model dispatch. Every readiness downgrade comes from a named
rule in ``reasons``; nothing in the brief is filled with text that did not come from the input.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from enum import StrEnum


class ReadinessState(StrEnum):
    """Readiness classification for incoming prompt context."""

    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    NEEDS_LIGHT_REFINEMENT = "NEEDS_LIGHT_REFINEMENT"
    NEEDS_INTAKE = "NEEDS_INTAKE"
    BLOCKED = "BLOCKED"


_SCORES = {
    ReadinessState.READY_TO_EXECUTE: 90,
    ReadinessState.NEEDS_LIGHT_REFINEMENT: 70,
    ReadinessState.NEEDS_INTAKE: 40,
    ReadinessState.BLOCKED: 0,
}
_ORDER = list(_SCORES)


@dataclass
class StructuredBrief:
    """Fields extracted from the input. Empty means "not stated", never a default guess."""

    objective: str
    deliverable: str = ""
    context: str = ""
    audience: str = ""
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
    brief: StructuredBrief = field(default_factory=lambda: StructuredBrief(objective=""))
    #: Named rules that set the readiness (``vague_marker``, ``voice_dump`` ...).
    reasons: list[str] = field(default_factory=list)
    #: Non-blocking notes: lcc is a token tool, not a policy engine.
    risk_flags: list[str] = field(default_factory=list)
    ask_count: int = 0
    dictation: bool = False


_RISK_PATTERNS = [
    (
        "mentions_security_bypass",
        re.compile(
            r"(?i)\b(?:bypass\s+security|exploit\s+(?:a\s+)?vulnerabilit(?:y|ies)"
            r"|steal\s+credentials|dump\s+passwords)\b"
        ),
    ),
    (
        "mentions_prompt_injection",
        re.compile(r"(?i)\b(?:ignore\s+all\s+previous\s+instructions|jailbreak)\b"),
    ),
]

# Word-boundary hedges that leave the request itself undecided. "kind of" / "sort of" are not
# here: "what kind of index" is a precise question.
_VAGUE = re.compile(
    r"(?i)\b(?:maybe|perhaps|not sure|i guess|something with|or something|somehow"
    r"|talvez|não sei bem|não sei se|sei lá|alguma coisa|algo assim|de algum jeito)\b"
)

# ponytail: a request is counted by its cue words (desire verbs, imperatives), merged when they
# sit within ASK_MERGE_WINDOW words ("quero que você crie" is one ask). Ceiling: indicative verb
# forms and noun homographs; a parser would be the upgrade if the corpus shows misses.
_PT_CUES = (
    r"quero|queria|preciso|precisa|precisamos|gostaria|tem que|temos que"
    r"|arruma|arrume|corrige|corrija|cria|crie|faça|adiciona|adicione|coloca|coloque|muda|mude"
    r"|atualiza|atualize|remova|verifica|verifique|implementa|implemente|refatora|refatore"
    r"|mede|meça|abre|abra|escreve|escreva|documenta|documente|revisa|revise|rode|configura"
    r"|configure|migra|migre|explica|explique|gera|gere|analisa|analise|investiga|investigue"
    r"|compare|compara|resume|resuma|renomeia|renomeie|apaga|apague"
)
_EN_CUES = (
    r"fix|add|create|write|update|remove|refactor|rename|implement|measure|open|document"
    r"|review|run|migrate|explain|summarize|summarise|build|check|investigate|delete|deploy"
    r"|change|move|bump|compare|analy[sz]e|optimi[sz]e|generate|make"
)
_ASK_CUE = re.compile(
    rf"\b(?:{_PT_CUES}|please|i want|i need|we need|need to|can you|could you|make sure)\b"
    rf"|(?:^|[.!?;:,\n]\s*|\b(?:and|also|then|just|now|please)\s+|^\s*\d+[.)]\s*)"
    rf"(?:{_EN_CUES})\b",
    re.IGNORECASE | re.MULTILINE,
)
ASK_MERGE_WINDOW = 4
MULTI_ASK_THRESHOLD = 3
_SHORT_DIRECTIVE = re.compile(r"(?i)\b(?:test|tests|check|fix)\b")
_WORD = re.compile(r"\S+")


def count_asks(text: str) -> int:
    """Count distinct requests: cue words, merged when within ``ASK_MERGE_WINDOW`` words."""
    word_starts = [m.start() for m in _WORD.finditer(text)]
    positions = [bisect_right(word_starts, m.end() - 1) - 1 for m in _ASK_CUE.finditer(text)]
    asks = 0
    last: int | None = None
    for pos in sorted(positions):
        if last is None or pos - last > ASK_MERGE_WINDOW:
            asks += 1
        last = pos
    return asks


def parse_intake(raw_input: str, *, dictation: bool | None = None) -> ParsedIntake:
    """Classify ``raw_input`` into a readiness state with named reasons and a derived brief.

    ``dictation`` is the speech detection made on the raw text before filler cleaning; when
    ``None`` it is detected here.
    """
    text = (raw_input or "").strip()
    if not text:
        return ParsedIntake(
            raw_input="",
            intent="Empty request",
            readiness=ReadinessState.BLOCKED,
            readiness_score=0,
            ambiguity_score=100,
            questions=["Please provide a valid prompt, objective, or context file."],
            brief=StructuredBrief(objective="", critical_gaps=["No input text provided."]),
            reasons=["empty_input"],
        )

    if dictation is None:
        from lcc.intake.speech import detect_dictation

        dictation = detect_dictation(text).detected

    risk_flags = [name for name, pattern in _RISK_PATTERNS if pattern.search(text)]
    word_count = len(text.split())
    has_question = "?" in text
    asks = count_asks(text)
    vague_hits = sorted({m.group(0).lower() for m in _VAGUE.finditer(text)})

    states: list[ReadinessState] = [ReadinessState.READY_TO_EXECUTE]
    reasons: list[str] = []
    questions: list[str] = []
    assumptions: list[str] = []
    critical_gaps: list[str] = []

    if vague_hits:
        states.append(ReadinessState.NEEDS_INTAKE)
        reasons.append("vague_marker")
        questions.append("What is the exact deliverable and primary success criterion?")
        questions.append("Are there specific architectural or runtime constraints?")
        critical_gaps.append(f"Contains ambiguous phrasing: {', '.join(vague_hits)}")
    if asks >= MULTI_ASK_THRESHOLD and dictation:
        states.append(ReadinessState.NEEDS_INTAKE)
        reasons.append("voice_dump")
        questions.append(
            f"This dictation holds {asks} separate asks: which comes first, and should each "
            "be its own task?"
        )
        critical_gaps.append(f"{asks} distinct asks in one dictated message.")
    elif asks >= MULTI_ASK_THRESHOLD:
        states.append(ReadinessState.NEEDS_LIGHT_REFINEMENT)
        reasons.append("multiple_asks")
        assumptions.append(f"Treating the {asks} asks as one ordered task list.")
    if word_count < 6 and not has_question and _SHORT_DIRECTIVE.search(text):
        states.append(ReadinessState.NEEDS_LIGHT_REFINEMENT)
        reasons.append("short_directive")
        assumptions.append(f"Interpreted '{text}' as an operational technical directive.")
    elif word_count < 4 and not has_question:
        states.append(ReadinessState.NEEDS_LIGHT_REFINEMENT)
        reasons.append("too_short")
        assumptions.append(f"Executing '{text}' with default technical guidelines.")

    readiness = max(states, key=_ORDER.index)
    score = _SCORES[readiness]
    intent_preview = text[:80] + ("..." if len(text) > 80 else "")
    return ParsedIntake(
        raw_input=text,
        intent=intent_preview,
        readiness=readiness,
        readiness_score=score,
        ambiguity_score=100 - score,
        questions=questions,
        assumptions=assumptions,
        brief=StructuredBrief(objective=intent_preview, critical_gaps=critical_gaps),
        reasons=reasons,
        risk_flags=risk_flags,
        ask_count=asks,
        dictation=dictation,
    )
