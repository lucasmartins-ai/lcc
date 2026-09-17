"""Deterministic block segmentation for opt-in relevance compaction (ADR 0013).

Blocks are atomic slices of the source text identified by content-addressed ids
(``blk_0001_<12 hex>``). Segmentation never rewrites source bytes: every input character
belongs either to a block or to a gap between blocks, and blocks/gaps are emitted in order,
so kept regions can be re-emitted byte-for-byte.

Segmentation is local-only and deterministic: no model calls, no network access, no
tokenizer downloads. Fenced code runs (``` / ~~~) are kept intact as single segments;
everything else splits on blank lines. Oversized segments are split further at line
boundaries so a single huge dump can still be partially pruned.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

BLOCK_ID_RE = re.compile(r"^blk_[0-9]{4}_[0-9a-f]{12}$")
_FENCE_OPEN_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})")
DEFAULT_MIN_BLOCK_CHARS = 80
DEFAULT_MAX_BLOCK_CHARS = 6000


@dataclass(frozen=True)
class TextBlock:
    """One atomic source slice with provenance and protection state."""

    id: str
    index: int
    text: str
    character_start: int
    character_end: int
    line_start: int
    line_end: int
    protected: bool = False
    protected_reason: str | None = None


def block_id(index: int, text: str) -> str:
    """Content-addressed block id mirroring the inspection chunk id convention."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"blk_{index:04d}_{digest}"


def _split_lines(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` offsets for every line, end exclusive, newlines included."""
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        spans.append((offset, offset + len(line)))
        offset += len(line)
    if offset < len(text):  # defensive: text not ending in newline and splitlines gap
        spans.append((offset, len(text)))
    return spans


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _atomic_spans(text: str) -> list[tuple[int, int]]:
    """Split text into atomic spans: fenced code runs stay whole, plain text splits on blanks."""
    lines = _split_lines(text)
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        start = lines[i][0]
        line_text = text[lines[i][0] : lines[i][1]]
        if _is_blank(line_text):
            i += 1
            continue
        fence = _FENCE_OPEN_RE.match(line_text.rstrip("\r\n"))
        if fence:
            fence_marker = fence.group("fence")
            fence_char = fence_marker[0]
            j = i + 1
            closed = None
            closing_re = re.compile(
                rf"^[ \t]*{re.escape(fence_char)}{{{len(fence_marker)},}}[ \t]*$"
            )
            while j < n:
                inner = text[lines[j][0] : lines[j][1]].rstrip("\r\n")
                if closing_re.match(inner):
                    closed = j
                    break
                j += 1
            end_line = closed if closed is not None else n - 1
            spans.append((start, lines[end_line][1]))
            i = end_line + 1
            continue
        # Plain paragraph: consume lines until a blank line or a fence opener.
        j = i + 1
        while j < n:
            inner = text[lines[j][0] : lines[j][1]]
            if _is_blank(inner):
                break
            if _FENCE_OPEN_RE.match(inner.rstrip("\r\n")):
                break
            j += 1
        spans.append((start, lines[j - 1][1]))
        i = j
    return spans


def _split_oversized(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Split ``[start, end)`` at line boundaries into pieces of at most ``max_chars``."""
    pieces: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + max_chars, end)
        if window_end < end:
            newline = text.rfind("\n", cursor + max_chars // 2, window_end)
            if newline != -1:
                window_end = newline + 1
        pieces.append((cursor, window_end))
        cursor = window_end
    # Merge a tiny trailing piece back into its predecessor.
    if len(pieces) >= 2:
        last_start, last_end = pieces[-1]
        if last_end - last_start < DEFAULT_MIN_BLOCK_CHARS:
            prev_start, _ = pieces[-2]
            pieces = pieces[:-2] + [(prev_start, last_end)]
    return pieces


def _line_numbers(text: str, character_start: int, character_end: int) -> tuple[int, int]:
    line_start = text.count("\n", 0, character_start) + 1
    end_scan = max(character_start, character_end - 1)
    line_end = text.count("\n", 0, end_scan) + 1
    return line_start, line_end


def split_blocks(
    text: str,
    *,
    min_block_chars: int = DEFAULT_MIN_BLOCK_CHARS,
    max_block_chars: int = DEFAULT_MAX_BLOCK_CHARS,
) -> list[TextBlock]:
    """Split ``text`` into deterministic, content-addressed blocks.

    Blocks shorter than ``min_block_chars`` are marked protected with reason
    ``short_block`` (callers keep them without spending a model call). Fenced code runs are
    never split unless they exceed ``max_block_chars``, in which case they split at line
    boundaries like any other oversized segment.
    """
    spans: list[tuple[int, int]] = []
    for start, end in _atomic_spans(text):
        if end - start <= max_block_chars:
            spans.append((start, end))
        else:
            spans.extend(_split_oversized(text, start, end, max_block_chars))

    blocks: list[TextBlock] = []
    for index, (start, end) in enumerate(spans, start=1):
        chunk = text[start:end]
        line_start, line_end = _line_numbers(text, start, end)
        protected = len(chunk) < min_block_chars
        blocks.append(
            TextBlock(
                id=block_id(index, chunk),
                index=index,
                text=chunk,
                character_start=start,
                character_end=end,
                line_start=line_start,
                line_end=line_end,
                protected=protected,
                protected_reason="short_block" if protected else None,
            )
        )
    return blocks


def gaps_between(text: str, blocks: list[TextBlock]) -> list[str]:
    """Return the verbatim gap before each block plus the trailing gap.

    ``gaps[i]`` is the text between block ``i-1`` (or the start of the text for ``i == 0``)
    and block ``i``. ``gaps[-1]`` is the text after the last block. Concatenating
    ``gap[i] + block[i].text`` for all blocks followed by ``gaps[-1]`` reproduces the
    original text exactly.
    """
    gaps: list[str] = []
    cursor = 0
    for block in blocks:
        gaps.append(text[cursor : block.character_start])
        cursor = block.character_end
    gaps.append(text[cursor:])
    return gaps


def reconstruct(text: str, blocks: list[TextBlock], gaps: list[str]) -> str:
    """Rebuild the exact original text from blocks and gaps (byte-for-byte)."""
    out: list[str] = []
    for block, gap in zip(blocks, gaps[:-1], strict=False):
        out.append(gap)
        out.append(block.text)
    out.append(gaps[-1])
    return "".join(out)
