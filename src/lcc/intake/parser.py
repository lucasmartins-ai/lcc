"""Deterministic intake analysis: readiness, named reasons, risk flags and a derived brief.

Part of the unified LCC engine. Analyzes raw, unstructured, voice-like, or ambiguous
prompts before compression and model dispatch. Every readiness downgrade comes from a named
rule in ``reasons``; nothing in the brief is filled with text that did not come from the input.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import accumulate

from lcc.intake.category import classify
from lcc.intake.speech import sentence_spans


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
    #: Every ask, copied verbatim from the input in order; ``objective`` is the first.
    asks: list[str] = field(default_factory=list)


@dataclass
class BriefItem:
    """One sentence of the input with its role and the exact spans it was copied from."""

    role: str  # "ask", "context" or "constraint"
    text: str
    spans: list[tuple[int, int]] = field(default_factory=list)


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
    #: Advisory request category (``lcc.intake.category``); empty below its confidence threshold.
    category: str = ""
    category_probability: float = 0.0
    #: What the agent needs in context for that category; empty when ``category`` is.
    category_context: str = ""
    #: "pt" or "en", from a stopword count; readiness questions are written in it.
    lang: str = "en"
    #: Each sentence with its role. Spans index the text given to ``parse_intake``;
    #: ``LccIntake.process`` re-indexes them to its raw input.
    extract: list[BriefItem] = field(default_factory=list)


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
# Hedges a speaker uses to sound polite ("talvez você possa olhar"): ambiguity when typed,
# a speech habit when dictated. The other markers stay vague either way.
_SPOKEN_HEDGES = {"maybe", "perhaps", "i guess", "talvez"}

# ponytail: a request is counted by its cue words (desire verbs, imperatives), merged when they
# sit within ASK_MERGE_WINDOW words ("quero que você crie" is one ask). Ceiling: indicative verb
# forms and noun homographs; a parser would be the upgrade if the corpus shows misses.
_PT_VERBS = (
    r"arruma|arrume|corrige|corrija|cria|crie|faça|adiciona|adicione|coloca|coloque|muda|mude"
    r"|atualiza|atualize|remova|verifica|verifique|implementa|implemente|refatora|refatore"
    r"|mede|meça|abre|abra|escreve|escreva|documenta|documente|revisa|revise|rode|configura"
    r"|configure|migra|migre|explica|explique|gera|gere|analisa|analise|investiga|investigue"
    r"|compare|compara|resume|resuma|renomeia|renomeie|apaga|apague"
)
_PT_CUES = r"quero|queria|preciso|precisa|precisamos|gostaria|tem que|temos que|" + _PT_VERBS
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


# --- extractive brief ---------------------------------------------------------------------

# ponytail: cue words, not a parser. Ceiling: a context sentence holding a cue verb reads as an
# ask; Jev roles (lcc.intake.roles) replace these when the opt-in judgment answered.
_BRIEF_ROLES = ("ask", "context", "constraint")
_LEAD = r"(?:(?:depois|então|e|aí|agora|também|por favor|then|and|also|now|please|just)[,\s]+)*"
_IMPERATIVE_OPEN = re.compile(
    rf"(?i)^{_LEAD}(?:me\s+)?(?:"
    r"mande|manda|envie|envia|diga|diz|fala|fale|conta|conte|mostre|mostra|liste|lista"
    r"|esconda|esconde|traga|traz|descubra|confira|confere|teste|testa|suba|sobe|publique"
    r"|desfaça|volte|reverta|ajuste|ajusta|troque|troca|separe|monte|prepare|olhe|olha|veja"
    r"|você pode|você poderia|você consegue|pode|poderia"
    r"|send|tell|show|list|hide|find|roll back|revert|give|bring|let me know|look|test"
    r"|upload|publish|undo|set|turn|switch|replace|split|prepare|draft|translate|sort|clean"
    r"|copy|install|enable|disable|restore|ship|merge|push|pull"
    rf"|{_PT_VERBS}|{_EN_CUES})\b"
)
_ASK_ANYWHERE = re.compile(r"(?i)\b(?:precisava|precisaria|eu queria saber)\b")
_CONSTRAINT_OPEN = re.compile(
    r"(?i)^(?:não|nunca|jamais)\s+(?:me\s+)?(?:mexa|altere|apague|remova|faça|mude|use"
    r"|toque|crie|delete|suba|publique|envie|rode|quebre|deixe|esqueça|adicione|exponha)\b"
    r"|^(?:só|somente|apenas|mantenha|evite|sem|use|usa|do not|don't|never|only|keep|avoid"
    r"|without|must not)\b"
)
_CONSTRAINT_ANYWHERE = re.compile(
    r"(?i)\b(?:tem que ser|deve ser|precisa ser|must be|has to be|should be|needs to be)\b"
)
_CLAUSE_BREAK = re.compile(r"[;,:—–]")


def sentence_role(sentence: str, *, ask_cue: bool | None = None) -> str:
    """Deterministic role of one sentence: ask, constraint or context. An imperative stays an
    ask when the rule sits in a later clause ("Create X; it must be Y."); "Build must be
    reproducible." is a rule about the build. ``ask_cue`` is whether ``_ASK_CUE`` matches the
    sentence, when the caller already scanned it."""
    if sentence.rstrip().endswith("?"):
        return "ask"
    if _rule_constraint(sentence):
        return "constraint"
    if ask_cue is None:
        ask_cue = _ASK_CUE.search(sentence) is not None
    if ask_cue or _IMPERATIVE_OPEN.search(sentence):
        return "ask"
    return "ask" if _ASK_ANYWHERE.search(sentence) else "context"


def _rule_constraint(sentence: str) -> bool:
    """Whether the cue-word rules make ``sentence`` a constraint; ``_ASK_CUE`` plays no part."""
    if sentence.rstrip().endswith("?"):
        return False
    if _CONSTRAINT_OPEN.search(sentence):
        return True
    rule = _CONSTRAINT_ANYWHERE.search(sentence)
    return rule is not None and not (
        _IMPERATIVE_OPEN.search(sentence) and _CLAUSE_BREAK.search(sentence, 0, rule.start())
    )


def _extract(text: str, roles: Mapping[str, str]) -> tuple[list[BriefItem], int]:
    """Each sentence with its role, and the ask count over the non-constraint sentences.

    A constraint ("Não faça merge sem os testes") limits an ask; it is not one more ask. Being a
    constraint never depends on ``_ASK_CUE``, so those sentences are known first and one
    ``_ASK_CUE`` scan of the rest, joined by newlines, gives the count and each one's cue.
    """
    spans = sentence_spans(text)
    sentences = [text[s:e] for s, e in spans]
    fixed = []
    for sentence in sentences:
        role = roles.get(sentence, "")
        if role not in _BRIEF_ROLES:
            role = "constraint" if _rule_constraint(sentence) else ""
        fixed.append(role)
    kept = [i for i, role in enumerate(fixed) if role != "constraint"]
    joined = "\n".join(sentences[i] for i in kept)
    starts = list(accumulate((len(sentences[i]) + 1 for i in kept[:-1]), initial=0))
    ends = [m.end() for m in _ASK_CUE.finditer(joined)]
    # A cue ends on a word, so its last character sits in the sentence it belongs to.
    cued = {kept[bisect_right(starts, end - 1) - 1] for end in ends}
    items = [
        BriefItem(role or sentence_role(sentences[i], ask_cue=i in cued), sentences[i], [spans[i]])
        for i, role in enumerate(fixed)
    ]
    return items, _merge_asks(joined, ends)


_PT_STOP = {
    "o", "os", "de", "do", "da", "dos", "das", "que", "não", "é", "uma", "para", "com", "em",
    "na", "nos", "nas", "eu", "você", "isso", "mas", "por", "ele", "ela", "está", "tá", "foi",
    "como", "mais", "ou", "também", "já", "aí", "né", "tipo", "então", "esse", "essa", "aquele",
    "assim", "coisa", "sei", "aqui", "agora", "depois", "seu", "sua", "meu", "minha",
    "nada", "tudo", "quando", "onde", "porque", "pra", "pro", "ao", "pelo", "pela", "tem", "vai",
}  # fmt: skip
_EN_STOP = {
    "the", "to", "of", "and", "is", "it", "in", "that", "you", "for", "on", "with", "this",
    "not", "be", "are", "i", "we", "my", "your", "can", "what", "how", "if", "or", "but",
    "was", "at", "from", "just", "should", "would", "which", "there", "they", "have", "has",
    "an", "all", "any", "some", "about", "when", "where", "because", "will", "it's", "don't",
}  # fmt: skip
_VAGUE_QUESTIONS: dict[str, list[str]] = {
    "en": [
        "What is the exact deliverable and primary success criterion?",
        "Are there specific architectural or runtime constraints?",
    ],
    "pt": [
        "Qual é a entrega exata e o critério de sucesso principal?",
        "Há restrições de arquitetura ou de execução a respeitar?",
    ],
}
_VOICE_DUMP_QUESTION: dict[str, str] = {
    "en": "This dictation holds {n} separate asks: which comes first, and should "
    "each be its own task?",
    "pt": "Este ditado tem {n} pedidos separados: qual vem primeiro, e cada um deve "
    "virar uma tarefa?",
}


_PT_ACCENT = re.compile(r"[ãõçáéíóúâêôà]")


def detect_lang(text: str) -> str:
    """``"pt"`` or ``"en"`` by stopword count (a word with a Portuguese accent counts as pt);
    ties read as English."""
    words = re.findall(r"[^\W\d_]+(?:'[a-z]+)?", text.lower())
    pt = sum(w in _PT_STOP or bool(_PT_ACCENT.search(w)) for w in words)
    return "pt" if pt > sum(w in _EN_STOP for w in words) else "en"


def count_asks(text: str) -> int:
    """Count distinct requests: cue words, merged when within ``ASK_MERGE_WINDOW`` words."""
    return _merge_asks(text, [m.end() for m in _ASK_CUE.finditer(text)])


def _merge_asks(text: str, cue_ends: list[int]) -> int:
    word_starts = [m.start() for m in _WORD.finditer(text)]
    asks = 0
    last: int | None = None
    for pos in sorted(bisect_right(word_starts, end - 1) - 1 for end in cue_ends):
        if last is None or pos - last > ASK_MERGE_WINDOW:
            asks += 1
        last = pos
    return asks


def parse_intake(
    raw_input: str,
    *,
    dictation: bool | None = None,
    previous_turn: str | None = None,
    roles: Mapping[str, str] | None = None,
) -> ParsedIntake:
    """Classify ``raw_input`` into a readiness state with named reasons and a derived brief.

    ``dictation`` is the speech detection made on the raw text before filler cleaning; when
    ``None`` it is detected here. ``roles`` maps sentence text to a role judged elsewhere (Jev);
    other sentences get their role from cue words.
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
    extract, asks = _extract(raw_input, roles or {})
    vague_hits = sorted({m.group(0).lower() for m in _VAGUE.finditer(text)})
    if dictation:
        vague_hits = [h for h in vague_hits if h not in _SPOKEN_HEDGES]
    lang = detect_lang(text)

    states: list[ReadinessState] = [ReadinessState.READY_TO_EXECUTE]
    reasons: list[str] = []
    questions: list[str] = []
    assumptions: list[str] = []
    critical_gaps: list[str] = []

    if vague_hits:
        states.append(ReadinessState.NEEDS_INTAKE)
        reasons.append("vague_marker")
        questions.extend(_VAGUE_QUESTIONS[lang])
        critical_gaps.append(f"Contains ambiguous phrasing: {', '.join(vague_hits)}")
    if asks >= MULTI_ASK_THRESHOLD and dictation:
        states.append(ReadinessState.NEEDS_INTAKE)
        reasons.append("voice_dump")
        questions.append(_VOICE_DUMP_QUESTION[lang].format(n=asks))
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
    category = classify(text, previous_turn=previous_turn)
    score = _SCORES[readiness]
    intent_preview = text[:80] + ("..." if len(text) > 80 else "")
    ask_items = [i.text for i in extract if i.role == "ask"]
    return ParsedIntake(
        raw_input=text,
        intent=intent_preview,
        readiness=readiness,
        readiness_score=score,
        ambiguity_score=100 - score,
        questions=questions,
        assumptions=assumptions,
        brief=StructuredBrief(
            objective=ask_items[0] if ask_items else intent_preview,
            context=" ".join(i.text for i in extract if i.role == "context"),
            constraints=[i.text for i in extract if i.role == "constraint"],
            critical_gaps=critical_gaps,
            asks=ask_items,
        ),
        reasons=reasons,
        risk_flags=risk_flags,
        ask_count=asks,
        dictation=dictation,
        category=category.id if category else "",
        category_probability=category.probability if category else 0.0,
        category_context=category.context_needed if category else "",
        lang=lang,
        extract=extract,
    )
