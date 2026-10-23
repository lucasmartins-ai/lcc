"""Deterministic speech transcript, disfluency, and Whisper hallucination cleaning."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lcc.cleaning.normalize import _extract_protected_regions, placeholder_prefix
from lcc.schemas import CleaningStep

# Whisper / STT Audio event annotations
_AUDIO_TAGS = re.compile(
    r"\[(?:music|applause|silence|laughter|cheering|cough|coughing|sigh|sighing|gasp"
    r"|background\s+noise|inaudible|unintelligible|snort|screaming|bell|audio|screams"
    r"|groan|chuckle|applause\s+and\s+cheering|music\s+playing|upbeat\s+music|ambient\s+noise"
    r"|end\s+of\s+recording|m[uú]sica|aplausos|risos|sil[eê]ncio)\]|\((?:music|applause|cheering|laughter|silence|ambient\s+music"
    r"|upbeat\s+music|background\s+noise|inaudible|cough|sigh|chuckle)\)|[♪♫🎵♩♬]+",
    re.IGNORECASE,
)

# Whisper / STT hallucinated end lines, credits, and subtitle boilerplates
_HALLUCINATION_LINE_PATTERNS = [
    re.compile(
        r"^(?:subtitles?\s+by|subt[ií]tulos\s+por|legendas?\s+por|transcribed\s+by"
        r"|transcri[cç][aã]o\s+por|captions?\s+by|closed\s+captions?\s+by|encoded\s+by)\b.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:thank\s+you\s+for\s+watching|thanks\s+for\s+watching|obrigado\s+por\s+assistir"
        r"|valeu\s+por\s+assistir|please\s+subscribe(?:\s+to\s+(?:the\s+)?channel)?|don't\s+forget\s+to\s+subscribe"
        r"|like\s+and\s+subscribe|subscribe\s+to\s+(?:the\s+)?channel|subscribe(?:\s+now)?|inscreva-se(?:\s+no\s+canal)?"
        r"|curta\s+e\s+se\s+inscreva|deixe\s+seu\s+like|see\s+you\s+in\s+the\s+next\s+(?:video|one)"
        r"|at[eé]\s+o\s+pr[oó]ximo\s+v[ií]deo)[\s.!]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:(?:https?://)?(?:www\.)?(?:amara|mooji|opensubtitles)\.(?:org|com|net))\b.*$",
        re.IGNORECASE,
    ),
]

# SRT / VTT timestamp lines & sequence headers
_TIMING_LINE = re.compile(
    r"^\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}.*$"
)
_SRT_SEQ_NUM = re.compile(r"^\d+$")
_INLINE_TIMESTAMP = re.compile(
    r"^\[?\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?\]?\s*|"
    r"(?<=\s)\[\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?\]"
)
_SPEAKER_PREFIX = re.compile(
    # A speaker label is a short, capitalised, name-like token before a colon. Deliberately no
    # digits in the label, so a prose line such as "the deployment finished at 09:00" is not read
    # as "someone called 'the deployment finished at 09' spoke". The literal ``Speaker N`` form
    # is admitted separately because it is the conventional transcript label.
    r"^((?i:speaker\s*\d+)|[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,3})\s*:\s*(\S.*)$"
)

# Disfluency / Speech fillers patterns (compiled regexes). Only content-free forms: a marker
# between commas or opening a sentence. Bare "you know", "I mean", "kind of", "basically" can
# carry meaning ("Do you know the schema?", "what kind of index") and stay, and a tag question
# ("né?", "right?") is never turned into a statement.
_FILLERS: list[tuple[re.Pattern[str], str]] = [
    # English starter / standalone fillers. "Right," only opening a sentence ("turn right, then"
    # is content); it runs first so a following ", I mean," cannot glue onto it.
    (re.compile(r"(?:^|(?<=[.!?] ))Right\s*,\s*"), ""),
    (re.compile(r"(?i)\b(?:okay|ok)\s+so\s*,\s*"), ""),
    (re.compile(r"(?i)\b(?:okay|ok)\s+so\b\s*"), ""),
    (re.compile(r"(?i),\s*you\s+know\s*,\s*"), " "),
    (re.compile(r"(?i)\bYou\s+know\s*,\s*"), ""),
    (re.compile(r"(?i),\s*you\s+know\b"), ""),
    (re.compile(r"(?i),\s*I\s+mean\s*,\s*"), " "),
    (re.compile(r"(?i)\bI\s+mean\s*,\s*"), ""),
    (re.compile(r"(?i),\s*basically\s*,\s*"), " "),
    (re.compile(r"(?i)\bBasically\s*,\s*"), ""),
    (re.compile(r"(?i),\s*literally\s*,\s*"), " "),
    (re.compile(r"(?i)\bLiterally\s*,\s*"), ""),
    (re.compile(r"(?i),\s*(?:sort|kind)\s+of\s*,\s*"), " "),
    (re.compile(r"(?i),\s*like\s*,\s*"), " "),
    (re.compile(r"(?i)\bLike\s*,\s*"), ""),
    (re.compile(r"(?i),\s*right\s*,\s*"), " "),
    # Standalone interjections (uh, er, ah) with optional surrounding commas
    (re.compile(r"(?i)(?:,\s*)?\b(?:uh+|er+|ah+|ahh+|eh+)\b\s*[,.\u2026]*\s*"), " "),
    # English "Um" filler (case-sensitive to avoid matching Portuguese lowercase
    # 'um' as in 'um container')
    (re.compile(r"\bUm\b\s*[,.\u2026-]+\s*"), ""),
    (re.compile(r",\s*um\s*[,.\u2026-]+\s*"), " "),
    # Portuguese fillers
    (re.compile(r"(?i)\btipo\s+assim\s*,\s*"), ""),
    (re.compile(r"(?i),\s*tipo\s+assim\s*,\s*"), " "),
    (re.compile(r"(?i)\btipo\s+assim\b\s*"), ""),
    (re.compile(r"(?i),\s*tipo\s*,\s*"), " "),
    (re.compile(r"(?i)\bTipo\s*,\s*"), ""),
    (re.compile(r"(?i)\bent[aã]o\s+assim\s*,\s*"), ""),
    (re.compile(r"(?i),\s*ent[aã]o\s+assim\s*,\s*"), " "),
    (re.compile(r"(?i)\bent[aã]o\s+assim\b\s*"), ""),
    (re.compile(r"(?i)\bquer\s+dizer\s*,\s*"), ""),
    (re.compile(r"(?i),\s*quer\s+dizer\s*,\s*"), " "),
    (re.compile(r"(?i)\bpera[ií]\s*,\s*"), ""),
    (re.compile(r"(?i)\bpera\s+a[ií]\s*,\s*"), ""),
    (re.compile(r"(?i),\s*pera[ií]\s*,\s*"), " "),
    (re.compile(r"(?i),\s*pera\s+a[ií]\s*,\s*"), " "),
    (re.compile(r"(?i)\bou\s+seja\s*,\s*"), ""),
    (re.compile(r"(?i),\s*ou\s+seja\s*,\s*"), " "),
    (re.compile(r"(?i),\s*n[eé]\s*,\s*"), " "),
    (re.compile(r"(?i)\b[eé]\.\.\.\s*"), ""),
    (re.compile(r"(?i)\beh\.\.\.\s*"), ""),
    (re.compile(r"(?i)\b[eé]ee+\b\s*"), ""),
]

# Post-cleaning punctuation fixups
_DOUBLE_COMMA = re.compile(r",\s*,+")
_COMMA_PERIOD = re.compile(r",\s*\.")
_LEADING_PUNCT = re.compile(r"^[\s,;.-]+(?=[A-Za-z0-9])")
_MULTIPLE_SPACES = re.compile(r"[ \t]{2,}")
_EMPTY_PARENS = re.compile(r"\(\s*\)|\[\s*\]")


@dataclass
class SpeechCleanResult:
    """Cleaned text plus auditable actions performed."""

    text: str
    actions: list[CleaningStep] = field(default_factory=list)


def is_speech_transcript(text: str) -> bool:
    """Heuristic to detect if text looks like an audio/video transcript or voice input."""
    if not text or not text.strip():
        return False

    # Check SRT/VTT timing lines
    # Per line: an SRT file opens with its sequence number, so the first line is not the cue.
    if "-->" in text and any(_TIMING_LINE.match(line.strip()) for line in text.splitlines()):
        return True

    # Check audio tag annotations
    if _AUDIO_TAGS.search(text):
        return True

    # Check timestamps like [01:23] or (00:12:34)
    if _INLINE_TIMESTAMP.search(text):
        return True

    # Check speaker turns. Two *distinct* labels are required: a prose document that happens to
    # repeat one label-like word ("Note:", "Result:") is not a transcript, while a real one
    # alternates between speakers.
    speaker_labels: set[str] = set()
    for line in text.split("\n"):
        match = _SPEAKER_PREFIX.match(line.strip())
        if match:
            speaker_labels.add(match.group(0).split(":", 1)[0].strip().lower())
            if len(speaker_labels) >= 2:
                return True

    # Check filler density
    filler_signals = 0
    lowered = text.lower()
    for marker in [
        "tipo assim",
        "então assim",
        "quer dizer,",
        ", né?",
        " né?",
        "you know,",
        "basically,",
        "literally,",
        "subtitles by",
        "thank you for watching",
        "thanks for watching",
        "obrigado por assistir",
    ]:
        if marker in lowered:
            filler_signals += 1
            if filler_signals >= 2:
                return True

    return False


def _clean_line_text(line: str) -> str:
    """Clean disfluencies and audio tags from a single line of prose."""
    # Strip audio tags
    cleaned = _AUDIO_TAGS.sub("", line)
    # Strip inline bracketed timestamps
    cleaned = _INLINE_TIMESTAMP.sub("", cleaned)

    # Apply filler substitutions
    for pattern, repl in _FILLERS:
        cleaned = pattern.sub(repl, cleaned)

    # Fix punctuation
    cleaned = _DOUBLE_COMMA.sub(",", cleaned)
    cleaned = _COMMA_PERIOD.sub(".", cleaned)
    cleaned = _EMPTY_PARENS.sub("", cleaned)
    cleaned = _MULTIPLE_SPACES.sub(" ", cleaned).strip()
    cleaned = _LEADING_PUNCT.sub("", cleaned).strip()

    # No re-casing: cleaning only removes, it never rewrites what the user wrote.

    return cleaned


def clean_speech_transcript(text: str) -> str:
    """Clean speech disfluencies, Whisper hallucinations, and transcript noise.

    Deterministic and safe:
    - Preserves fenced code blocks and markdown tables exactly.
    - Strips Whisper audio tags ([Music], [Applause], [Silence], etc.).
    - Removes hallucinated subtitle/video closing lines.
    - Removes common English & Portuguese stand-alone disfluencies and filler words.
    - Collapses repeated sequential speaker tags into coherent speaker turns.
    - Never removes technical terminology or code structures.
    """
    if not text or not text.strip():
        return text

    # Step 1: Normalize line endings to LF
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # Step 2: Mask protected regions (fenced code blocks and tables)
    raw_lines = normalized.split("\n")
    all_ranges, blocks = _extract_protected_regions(raw_lines)
    prefix = placeholder_prefix(normalized)
    range_map: dict[int, tuple[int, int]] = {}
    for block_idx, (start, end) in enumerate(all_ranges):
        range_map[start] = (end, block_idx)

    # Step 3: Process unprotected lines
    processed_lines: list[str] = []
    line_idx = 0
    n = len(raw_lines)

    last_speaker: str | None = None

    while line_idx < n:
        if line_idx in range_map:
            end, block_idx = range_map[line_idx]
            processed_lines.append(f"{prefix}{block_idx}__\x00")
            last_speaker = None
            line_idx = end + 1
            continue

        line = raw_lines[line_idx]
        stripped = line.strip()

        # Skip SRT sequence numbers if followed by timing line
        if (
            _SRT_SEQ_NUM.match(stripped)
            and line_idx + 1 < n
            and _TIMING_LINE.match(raw_lines[line_idx + 1].strip())
        ):
            line_idx += 1
            continue

        # Skip timing lines and WEBVTT headers
        if _TIMING_LINE.match(stripped) or stripped == "WEBVTT":
            line_idx += 1
            continue

        # Check hallucination lines
        if any(pat.match(stripped) for pat in _HALLUCINATION_LINE_PATTERNS):
            line_idx += 1
            continue

        # Strip line-level audio tags before speaker prefix matching
        stripped = _AUDIO_TAGS.sub("", stripped).strip()

        if not stripped:
            line_idx += 1
            continue

        # Check for speaker prefix
        speaker_match = _SPEAKER_PREFIX.match(stripped)
        if speaker_match:
            speaker_label = speaker_match.group(1).strip()
            content = speaker_match.group(2).strip()
            cleaned_content = _clean_line_text(content)
            if not cleaned_content:
                line_idx += 1
                continue

            if speaker_label.lower() == (last_speaker or "").lower() and processed_lines:
                # Same speaker continuing turn - append to previous line
                processed_lines[-1] = f"{processed_lines[-1]} {cleaned_content}"
            else:
                last_speaker = speaker_label
                processed_lines.append(f"{speaker_label}: {cleaned_content}")
        else:
            cleaned_content = _clean_line_text(stripped)
            if cleaned_content:
                if last_speaker is not None and processed_lines:
                    processed_lines[-1] = f"{processed_lines[-1]} {cleaned_content}"
                else:
                    processed_lines.append(cleaned_content)

        line_idx += 1

    # Step 4: Reassemble document and restore protected blocks
    joined = "\n".join(processed_lines)
    # Collapse multiple blank lines
    joined = re.sub(r"\n{3,}", "\n\n", joined).strip("\n")

    for block_idx, block in enumerate(blocks):
        joined = joined.replace(f"{prefix}{block_idx}__\x00", block)

    return joined


#: How far ahead in the raw text an anchor is searched. ponytail: a removal longer than this
#: is reported as a valid but non-minimal edit; raise it if real transcripts need more.
SPEECH_DIFF_WINDOW = 4_000
_ANCHOR_LENGTHS = (32, 16, 8, 4, 2, 1)


def _common_prefix(a: str, i: int, b: str, j: int) -> int:
    n = 0
    step = 4096
    while i + n < len(a) and j + n < len(b):
        chunk_a, chunk_b = a[i + n : i + n + step], b[j + n : j + n + step]
        if chunk_a == chunk_b:
            n += min(len(chunk_a), len(chunk_b))
            continue
        for x, y in zip(chunk_a, chunk_b, strict=False):
            if x != y:
                return n
            n += 1
        return n
    return n


def speech_edits(raw: str, cleaned: str) -> list[dict[str, int | str]]:
    """Edits that turn ``raw`` into ``cleaned``, with positions in ``raw``.

    ``clean_speech_transcript`` rewrites line by line (merging speaker turns, fixing commas), so
    its edits are recovered by alignment. The cleaned text is nearly a subsequence of the raw
    one: at each divergence the next cleaned characters are found ahead in ``raw`` (longest
    anchor first) and the skipped raw text is a removal; a character found nowhere ahead is an
    insertion. Linear in practice. Applying every ``{start, end, removed, inserted}`` in order
    to ``raw`` gives ``cleaned`` exactly.
    """
    edits: list[list[int]] = []  # [raw_start, raw_end, clean_start, clean_end]

    def add(a1: int, a2: int, b1: int, b2: int) -> None:
        if edits and edits[-1][1] == a1 and edits[-1][3] == b1:
            edits[-1][1], edits[-1][3] = a2, b2
        else:
            edits.append([a1, a2, b1, b2])

    i = j = 0
    while True:
        k = _common_prefix(raw, i, cleaned, j)
        i, j = i + k, j + k
        if j >= len(cleaned):
            if i < len(raw):
                add(i, len(raw), j, j)
            break
        if i >= len(raw):
            add(i, i, j, len(cleaned))
            break
        limit = i + SPEECH_DIFF_WINDOW
        for length in _ANCHOR_LENGTHS:
            pos = raw.find(cleaned[j : j + length], i, limit + length)
            if pos > i:
                add(i, pos, j, j)
                i = pos
                break
        else:
            add(i, i, j, j + 1)
            j += 1
    return [
        {"start": a1, "end": a2, "removed": raw[a1:a2], "inserted": cleaned[b1:b2]}
        for a1, a2, b1, b2 in edits
    ]
