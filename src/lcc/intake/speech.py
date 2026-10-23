"""Dictation detection and filler removal for intake, with an exact receipt.

``lcc.cleaning.speech`` only recognises transcript markup (SRT/VTT, audio tags, speaker turns).
What users paste from whisper or phone dictation is usually plain prose: no line structure,
dense discourse fillers ("tipo", "né", "you know"). This module detects that and removes only
fillers that carry no content, recording every removed span against the raw input so nothing
is rewritten silently. Spans are deleted verbatim; nothing is inserted or re-cased.
"""

from __future__ import annotations

import re
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
    """Decide whether ``text`` is speech: transcript markup, filler density, or a run-on line."""
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
    return DictationDetection(bool(reasons), reasons, hits, words)


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
_PROTECTED = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)


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
    """Remove transcript noise and content-free fillers; every removal is a reported span."""
    found: list[tuple[int, int, str]] = _line_spans(text)
    found += [(m.start(), m.end(), "audio_tag") for m in _AUDIO_TAG_WS.finditer(text)]
    for kind, pattern in _FILLER_RULES:
        found += [(m.start(), m.end(), kind) for m in pattern.finditer(text)]
    found += [(m.start(1), m.end(1), "bare_tipo") for m in _BARE_TIPO.finditer(text)]

    protected = [(m.start(), m.end()) for m in _PROTECTED.finditer(text)]
    found = [f for f in found if not any(f[0] < pe and ps < f[1] for ps, pe in protected)]

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
