"""Dictation detection and filler removal for intake, with an exact receipt.

``lcc.cleaning.speech`` only recognises transcript markup (SRT/VTT, audio tags, speaker turns).
What users paste from whisper or phone dictation is usually plain prose: no line structure,
dense discourse fillers ("tipo", "né", "you know"). This module detects that and removes only
fillers that carry no content, recording every removed span against the raw input so nothing
is rewritten silently. Spans are deleted verbatim; nothing is inserted or re-cased.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from lcc.cleaning.speech import (
    _AUDIO_TAGS,
    _HALLUCINATION_LINE_PATTERNS,
    _SRT_SEQ_NUM,
    _TIMING_LINE,
    is_speech_transcript,
)

# --- detection -------------------------------------------------------------------------------

# ponytail: fixed word lists, not a model. Add a marker here when the corpus shows a miss.
_DETECT_MARKERS = re.compile(
    r"(?i)\b(?:"
    r"tipo(?!\s+d[eoa]s?\b)|n[eé](?=[\s,.?!]|$)|entendeu|sabe(?=\s*[,?])|cara(?=\s*,)|t[aá] ligado"
    r"|ahn|hum+|aí|ent[aã]o"
    r"|uh+|uhm+|umm+|hmm+|you know|i mean|basically|kinda|literally|so yeah|right(?=\?)"
    r")\b"
    r"|(?i:,\s*like\b|\blike\s*,)"
)
_TERMINATORS = re.compile(r"[.!?]")
_WORD = re.compile(r"\w+")
#: Fillers per 100 words above which plain prose reads as dictation.
MIN_FILLER_DENSITY = 3.0
MIN_FILLER_HITS = 3
#: Words per sentence terminator above which a single-line text reads as unpunctuated speech.
RUN_ON_WORDS_PER_TERMINATOR = 30
RUN_ON_MIN_WORDS = 40


@dataclass
class DictationDetection:
    detected: bool
    reasons: list[str] = field(default_factory=list)
    filler_hits: int = 0
    words: int = 0


def detect_dictation(text: str) -> DictationDetection:
    """Decide whether ``text`` is speech: transcript markup, filler density, a run-on line,
    a sentence said to someone else, or a disfluency (self-correction, repetition, false start).
    """
    words = len(_WORD.findall(text or ""))
    if not words:
        return DictationDetection(False)
    hits = len(_DETECT_MARKERS.findall(text))
    reasons: list[str] = []
    if is_speech_transcript(text):
        reasons.append("transcript_shape")
    if hits >= MIN_FILLER_HITS and hits * 100 / words >= MIN_FILLER_DENSITY:
        reasons.append("filler_density")
    terminators = len(_TERMINATORS.findall(text))
    run_on = (
        "\n" not in text.strip()
        and words >= RUN_ON_MIN_WORDS
        and words / max(terminators, 1) >= RUN_ON_WORDS_PER_TERMINATOR
    )
    if run_on and hits >= 2:
        reasons.append("run_on_with_fillers")
    kinds = {kind for _, _, kind in _speech_spans(text)}
    if "aside_phrase" in kinds:
        reasons.append("aside_phrase")
    if kinds - {"aside_phrase"}:
        reasons.append("disfluency")
    return DictationDetection(bool(reasons), reasons, hits, words)


# --- sentences -------------------------------------------------------------------------------

# A terminator run followed by whitespace, or a line break: "src/a.py" and "1.8.2" stay whole.
_SENT_END = re.compile(r"[.!?…]+(?=\s|$)|\n")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` of each sentence in ``text``, without surrounding whitespace."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_END.finditer(text):
        _add_trimmed(spans, text, start, m.start() if m.group() == "\n" else m.end())
        start = m.end()
    _add_trimmed(spans, text, start, len(text))
    return spans


def _add_trimmed(spans: list[tuple[int, int]], text: str, start: int, end: int) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        spans.append((start, end))


def sentence_cut(text: str, start: int, end: int) -> tuple[int, int]:
    """A whole-sentence removal: the sentence plus the spaces before it (after it when nothing
    precedes it on the line), so what is left reads with single spacing."""
    before = start
    while before > 0 and text[before - 1] in " \t":
        before -= 1
    if before < start:
        return before, end
    after = end
    while after < len(text) and text[after] in " \t":
        after += 1
    return start, after


# --- Layer 1: asides and disfluencies (spec frozen in benchmarks/research/intake-dictation-v1)

# ponytail: a closed list of whole sentences said to someone in the room. Anything else said to
# someone else is left for the opt-in Jev judgment (lcc.intake.roles).
_VOCATIVE = (
    r"meu amor|amor|querid[ao]|vida|m[ãa]e|pai|filh[ao]"
    r"|honey|babe|baby|love|sweetie|mom|dad|darling"
)
_ASIDE_CORE = (
    r"te amo|tamb[ée]m te amo|amo voc[êe]|j[áa] vou|j[áa] t[ôo] indo|t[ôo] indo"
    r"|i love you|love you(?: too)?|coming|be right there|on my way"
)
_ASIDE_SENTENCE = re.compile(
    rf"(?i)(?:(?:{_VOCATIVE})\s*,?\s*)?(?:{_ASIDE_CORE})(?:\s*,?\s*(?:{_VOCATIVE}))?\s*[.!…]*"
)
_STRONG_EDIT = (
    r"n[ãa]o,\s*quer dizer|ou melhor|digo"
    r"|no,\s*i mean|sorry,\s*i mean|no,?\s*wait|or rather|scratch that"
)
_WEAK_EDIT = r"quer dizer|n[ãa]o|i mean|no|sorry"
_EDIT_TERM = re.compile(rf"(?i),\s*(?:(?P<strong>{_STRONG_EDIT})|{_WEAK_EDIT}),\s*(?=\S)")
_CLAUSE_END = re.compile(r"[.!?;:…](?=\s)|\n")
_TOKEN = re.compile(r"\S+")
_KEY = re.compile(r"[^\W_]+")
#: Words looked back from an editing term for the start of the reparandum.
CORRECTION_WINDOW = 8
_LETTERS = r"[^\W\d_]+"
_REPEAT_PHRASE = re.compile(rf"(?i)\b((?:{_LETTERS}[ \t]+){{1,3}}{_LETTERS})(,?[ \t]+)(?=\1\b)")
_REPEAT_WORD = re.compile(rf"(?i)\b({_LETTERS})([,-][ \t]+)(?=\1\b)")
# One word said twice that is also normal emphasis or grammar: "that that", "muito, muito".
_CONTENT_DOUBLES = {"that", "had", "is", "muito", "very", "bem", "so", "really", "mais", "tão"}
_FALSE_START = re.compile(rf"(?i)\b({_LETTERS})-[ \t]+(?=\1)")


def _key(token: str) -> str:
    m = _KEY.search(token)
    return m.group(0).lower() if m else ""


def _corrections(text: str) -> list[tuple[int, int, str]]:
    """Self-corrections: cut the reparandum and the editing term, keep the repair."""
    found: list[tuple[int, int, str]] = []
    for m in _EDIT_TERM.finditer(text):
        repair = _key(text[m.end() :].split(None, 1)[0])
        clause = max((c.end() for c in _CLAUSE_END.finditer(text, 0, m.start())), default=0)
        tokens = list(_TOKEN.finditer(text, clause, m.start()))[-CORRECTION_WINDOW:]
        start = next((t.start() for t in reversed(tokens) if _key(t.group()) == repair), -1)
        if start < 0 and m.group("strong") and len(tokens) > 1:
            # "dez, não, quer dizer, oito": the one word before, never the clause's first word
            start = tokens[-1].start()
        if start >= 0:
            found.append((start, m.end(), "self_correction"))
    return found


def _speech_spans(text: str) -> list[tuple[int, int, str]]:
    """Asides, self-corrections, repetitions and false starts outside code, never a "?"."""
    found = [
        (*sentence_cut(text, s, e), "aside_phrase")
        for s, e in sentence_spans(text)
        if _ASIDE_SENTENCE.fullmatch(text, s, e) and aside_cut_allowed(text, s, e)
    ]
    found += _corrections(text)
    found += [(m.start(), m.end(2), "repetition") for m in _REPEAT_PHRASE.finditer(text)]
    found += [
        (m.start(), m.end(2), "repetition")
        for m in _REPEAT_WORD.finditer(text)
        if m.group(1).lower() not in _CONTENT_DOUBLES
    ]
    found += [(m.start(), m.end(), "false_start") for m in _FALSE_START.finditer(text)]
    return [f for f in _outside_code(text, found) if "?" not in text[f[0] : f[1]]]


def _outside_code(text: str, found: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    # Two scans, not one alternation: a quote must not swallow a backtick and unprotect the code.
    protected = [(m.start(), m.end()) for p in _PROTECTED for m in p.finditer(text)]
    return [f for f in found if not any(f[0] < pe and ps < f[1] for ps, pe in protected)]


def aside_cut_allowed(text: str, start: int, end: int) -> bool:
    """Whether the sentence ``text[start:end]`` may be cut as an aside: never a question, code,
    quoted text, or content a colon hands over ("Translate this into English:\\nTe amo.")."""
    sentence = text[start:end]
    if "?" in sentence or "`" in sentence or not _outside_code(text, [(start, end, "")]):
        return False
    # ponytail: only a colon marks handed-over content; "Translate the next line. Te amo." is
    # still cut. Quote the text, or add a cue here, if the corpus shows that phrasing.
    before = start
    while before > 0 and text[before - 1].isspace():
        before -= 1
    return text[before - 1 : before] != ":"


# --- cleaning --------------------------------------------------------------------------------

# Discourse markers removed only when they stand alone between commas (", né," / ", you know,").
# A marker followed by "?" is a question tag and is never touched.
_BOUNDED = (
    r"you know|i mean|like|basically|literally|um|tipo assim|tipo|n[eé]|sabe|entendeu|cara"
    r"|t[aá] ligado|ent[aã]o assim"
)
_FILLER_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("comma_bounded", re.compile(rf"(?i),\s*(?:{_BOUNDED})\s*,")),
    # Sentence-opening marker followed by a comma: "Tipo, ..." / "You know, ...".
    (
        "sentence_opener",
        re.compile(
            r"(?im)(?:^|(?<=[.!?] ))(?:you know|i mean|like|basically|tipo assim|tipo|cara"
            r"|ent[aã]o assim)\s*,\s*"
        ),
    ),
    # Pure interjections; "um" only capitalised with a comma (Portuguese "um" is a word).
    ("interjection", re.compile(r"(?i)\b(?:uh+|uhm+|umm+|hmm+|hum+|ahn|ãh+|erm)\b[,…]*\s+")),
    ("interjection", re.compile(r"\bUm,\s+")),
    # Bare "né" mid-sentence (not "né?", which marks a question).
    ("bare_ne", re.compile(r"(?i)(?<=\w) n[eé](?=[\s,.;:]|$)(?!\?)")),
    ("tipo_assim", re.compile(r"(?i)\btipo assim\b,?\s*")),
]
# "tipo" after a connector and not before "de/do/da": "e aí tipo primeiro", not "qual tipo de".
_BARE_TIPO = re.compile(r"(?i)\b(?:ent[aã]o|e|aí|mas|daí)( tipo)(?= (?!d[eoa]s?\b)\w)")
_AUDIO_TAG_WS = re.compile(rf"(?:{_AUDIO_TAGS.pattern})[ \t]*", _AUDIO_TAGS.flags)
# Code and double-quoted text are literal: "go, go" is a value, not a stutter.
_PROTECTED = (
    re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL),
    re.compile(r"\"[^\"\n]*\"|“[^”\n]*”"),
)


@dataclass(frozen=True)
class Removal:
    start: int
    end: int
    text: str
    kind: str


@dataclass
class DictationClean:
    text: str
    removals: list[Removal] = field(default_factory=list)

    @property
    def removed_chars(self) -> int:
        return sum(r.end - r.start for r in self.removals)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for removal in self.removals:
            out[removal.kind] = out.get(removal.kind, 0) + 1
        return out


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    """Whole-line removals: SRT/VTT timing, sequence numbers, headers, STT hallucinations."""
    spans: list[tuple[int, int, str]] = []
    lines = text.splitlines(keepends=True)
    offset = 0
    for i, line in enumerate(lines):
        s = line.strip()
        kind = ""
        if _TIMING_LINE.match(s):
            kind = "timing_line"
        elif s == "WEBVTT":
            kind = "vtt_header"
        elif (
            _SRT_SEQ_NUM.match(s)
            and i + 1 < len(lines)
            and _TIMING_LINE.match(lines[i + 1].strip())
        ):
            kind = "sequence_number"
        elif s and any(p.match(s) for p in _HALLUCINATION_LINE_PATTERNS):
            kind = "stt_hallucination"
        if kind:
            spans.append((offset, offset + len(line), kind))
        offset += len(line)
    return spans


def clean_dictation(text: str) -> DictationClean:
    """Remove transcript noise, content-free fillers, asides and disfluencies; every removal is
    a reported span."""
    found: list[tuple[int, int, str]] = _line_spans(text)
    found += [(m.start(), m.end(), "audio_tag") for m in _AUDIO_TAG_WS.finditer(text)]
    for kind, pattern in _FILLER_RULES:
        found += [(m.start(), m.end(), kind) for m in pattern.finditer(text)]
    found += [(m.start(1), m.end(1), "bare_tipo") for m in _BARE_TIPO.finditer(text)]
    return merge_removals(text, _outside_code(text, found) + _speech_spans(text))


def merge_removals(text: str, found: Sequence[tuple[int, int, str]]) -> DictationClean:
    """Cut ``(start, end, kind)`` spans from ``text``; overlapping spans become one removal."""
    merged: list[tuple[int, int, str]] = []
    for start, end, kind in sorted(found):
        if merged and start < merged[-1][1]:  # overlap: one span, both rule names
            s0, e0, k0 = merged[-1]
            kinds = k0 if kind in k0.split("+") else f"{k0}+{kind}"
            merged[-1] = (s0, max(e0, end), kinds)
        else:
            merged.append((start, end, kind))
    removals = [Removal(s, e, text[s:e], k) for s, e, k in merged]

    pieces: list[str] = []
    cursor = 0
    for r in removals:
        pieces.append(text[cursor : r.start])
        cursor = r.end
    pieces.append(text[cursor:])
    return DictationClean("".join(pieces), removals)


def rebuild_input(cleaned: str, removals: Sequence[Removal]) -> str:
    """The raw input, byte for byte, from the cleaned text and its receipt."""
    pieces: list[str] = []
    cursor = removed = 0
    for r in sorted(removals, key=lambda r: r.start):
        at = r.start - removed
        pieces += [cleaned[cursor:at], r.text]
        cursor, removed = at, removed + len(r.text)
    pieces.append(cleaned[cursor:])
    return "".join(pieces)


def raw_spans(start: int, end: int, removals: Sequence[Removal]) -> list[tuple[int, int]]:
    """Map ``[start, end)`` of the cleaned text back to the raw input, split around removals."""
    spans: list[tuple[int, int]] = []
    seg, shift = start, 0
    for r in sorted(removals, key=lambda r: r.start):
        at = r.start - shift  # where the removal sits in the cleaned text
        if at >= end:
            break
        if at > seg:
            spans.append((seg + shift, at + shift))
            seg = at
        shift += r.end - r.start
    spans.append((seg + shift, end + shift))
    return spans
