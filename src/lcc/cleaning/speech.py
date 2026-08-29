"""Deterministic speech transcript, disfluency, and Whisper hallucination cleaning."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lcc.cleaning.normalize import _extract_protected_regions
from lcc.schemas import CleaningStep

# Whisper / STT Audio event annotations
_AUDIO_TAGS = re.compile(
    r"\[(?:music|applause|silence|laughter|cheering|cough|coughing|sigh|sighing|gasp"
    r"|background\s+noise|inaudible|unintelligible|snort|screaming|bell|audio|screams"
    r"|groan|chuckle|applause\s+and\s+cheering|music\s+playing|upbeat\s+music|ambient\s+noise"
    r"|end\s+of\s+recording)\]|\((?:music|applause|cheering|laughter|silence|ambient\s+music"
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
_SPEAKER_PREFIX = re.compile(r"^([A-Za-z0-9_ -]+|\bSpeaker\s+\d+)\s*:\s*(.*)$", re.IGNORECASE)

# Disfluency / Speech fillers patterns (compiled regexes)
_FILLERS: list[tuple[re.Pattern[str], str]] = [
    # English starter / standalone fillers
    (re.compile(r"(?i)\b(?:okay|ok)\s+so\s*,\s*"), ""),
    (re.compile(r"(?i)\b(?:okay|ok)\s+so\b\s*"), ""),
    (re.compile(r"(?i),\s*you\s+know\s*,\s*"), " "),
    (re.compile(r"(?i)\bYou\s+know\s*,\s*"), ""),
    (re.compile(r"(?i),\s*you\s+know\b"), ""),
    (re.compile(r"(?i)\byou\s+know\b\s*"), ""),
    (re.compile(r"(?i)\bRight\s*,\s*"), ""),
    (re.compile(r"(?i),\s*I\s+mean\s*,\s*"), " "),
    (re.compile(r"(?i)\bI\s+mean\s*,\s*"), ""),
    (re.compile(r"(?i)\bI\s+mean\b\s*"), ""),
    (re.compile(r"(?i),\s*basically\s*,\s*"), " "),
    (re.compile(r"(?i)\bBasically\s*,\s*"), ""),
    (re.compile(r"(?i)\bbasically\b\s*"), ""),
    (re.compile(r"(?i),\s*literally\s*,\s*"), " "),
    (re.compile(r"(?i)\bLiterally\s*,\s*"), ""),
    (re.compile(r"(?i)\bliterally\b\s*"), ""),
    (re.compile(r"(?i),\s*(?:sort|kind)\s+of\s*,\s*"), " "),
    (re.compile(r"(?i),\s*(?:sort|kind)\s+of\s*"), " "),
    (re.compile(r"(?i)\b(?:sort|kind)\s+of\s*"), ""),
    (re.compile(r"(?i)\b(?:sort|kind)\s+of\b\s*"), ""),
    (re.compile(r"(?i),\s*like\s*,\s*"), " "),
    (re.compile(r"(?i)\bLike\s*,\s*"), ""),
    (re.compile(r"(?i),\s*right\?"), "."),
    (re.compile(r"(?i),\s*right\s*,\s*"), " "),
    # Standalone interjections (uh, er, ah) with optional surrounding commas
    (re.compile(r"(?i)(?:,\s*)?\b(?:uh+|er+|ah+|ahh+|eh+)\b\s*[,.\u2026]*\s*"), " "),
    # English "Um" filler (case-sensitive to avoid matching Portuguese lowercase 'um' as in 'um container')
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
    (re.compile(r"(?i),\s*n[eé]\?"), "."),
    (re.compile(r"(?i),\s*n[eé]\s*,\s*"), " "),
    (re.compile(r"(?i)\s+n[eé]\?"), "."),
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
    if "-->" in text and _TIMING_LINE.search(text):
        return True

    # Check audio tag annotations
    if _AUDIO_TAGS.search(text):
        return True

    # Check timestamps like [01:23] or (00:12:34)
    if _INLINE_TIMESTAMP.search(text):
        return True

    # Check speaker turns
    lines = text.split("\n")
    speaker_turns = 0
    for line in lines:
        if _SPEAKER_PREFIX.match(line.strip()):
            speaker_turns += 1
            if speaker_turns >= 2:
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

    # Capitalize first letter if needed
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]

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
    range_map: dict[int, tuple[int, int, int]] = {}
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
            processed_lines.append(f"\x00__LCC_PROTECTED_BLOCK_{block_idx}__\x00")
            last_speaker = None
            line_idx = end + 1
            continue

        line = raw_lines[line_idx]
        stripped = line.strip()

        # Skip SRT sequence numbers if followed by timing line
        if _SRT_SEQ_NUM.match(stripped) and line_idx + 1 < n and _TIMING_LINE.match(raw_lines[line_idx + 1].strip()):
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
        joined = joined.replace(f"\x00__LCC_PROTECTED_BLOCK_{block_idx}__\x00", block)

    return joined
