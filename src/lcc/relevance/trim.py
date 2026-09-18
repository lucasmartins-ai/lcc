"""Type-aware trimming policy (TRIM safety).

Naive head-only character trimming is unsafe for structured content: it can emit
broken JSON/YAML/XML, cut a table mid-row, split a code function mid-statement, or
truncate a high-risk instruction into a misleading partial. This module classifies a
block and trims only at safe structural boundaries. When no safe boundary exists,
trimming is refused (``ok=False``) and the caller must KEEP the block whole — a
partial misleading context is worse than a longer safe one.

Content types: prose, logs, markdown_table, json, yaml, xml, markdown, code,
config, high_risk. Detection is deterministic and dependency-free (stdlib only).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

TRIM_POLICY_VERSION = "trim-1.0"

_CODE_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})", re.MULTILINE)
_TABLE_DELIM_RE = re.compile(
    r"^[ \t]*\|?([ \t]*:?-{1,}:?[ \t]*\|)+[ \t]*:?-{1,}:?[ \t]*\|?[ \t]*$",
    re.MULTILINE,
)
_HIGH_RISK_RE = re.compile(
    r"\b(indemnif\w*|liabilit\w*|lawsuit|arbitration|arbitrat\w*|dosage|prescri\w+|"
    r"diagnos\w*|contraindicat\w*|fiduciar\w*|malpractice|overdose|chemotherapy|"
    r"insider\s+trading|money\s+laundering)\b",
    re.IGNORECASE,
)
_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}|\d{2}:\d{2}(:\d{2})?|INFO|DEBUG|WARN|ERROR|TRACE|LOG\b)",
    re.MULTILINE,
)
_CODE_HINT_RE = re.compile(
    r"^\s*(def |class |function |import |from |const |let |var |fn |func |public |private |"
    r"if |for |while |return |#include|package |interface )",
    re.MULTILINE,
)
_CONFIG_HINT_RE = re.compile(r"^\s*[\w.\-_/]+(\s*[:=]\s*|\s*=\s*)\S+", re.MULTILINE)


def detect_content_type(text: str) -> str:
    """Classify a block for trimming. Order matters: most specific first."""
    stripped = text.strip()
    if not stripped:
        return "prose"
    if _HIGH_RISK_RE.search(text) and len(text) > 200:
        # High-risk is a modifier, but the pipeline treats it as a type so the
        # conservative policy (TRIM->KEEP) cannot be skipped by accident.
        return "high_risk"
    if _CODE_FENCE_RE.search(text):
        return "code"
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            return "json"
        except Exception:
            pass
        # Looks like JSON but broken: still treat as json so trimming is refused
        # rather than emitting a partial fragment as if it were prose.
        if re.match(r"^[\{\[]", stripped):
            return "json"
    if stripped.startswith("<") and re.search(r"<[a-zA-Z][^>]*>", stripped):
        try:
            ET.fromstring(stripped)
            return "xml"
        except Exception:
            return "xml"  # same reasoning as JSON: refuse unsafe trims
    lines = stripped.splitlines()
    if len(lines) >= 3 and any(_TABLE_DELIM_RE.match(line) for line in lines):
        return "markdown_table"
    # YAML: mapping-like lines with colons, no JSON braces
    colon_lines = sum(1 for line in lines if re.match(r"^\s*[\w.\-]+:\s*\S?", line))
    if len(lines) >= 2 and colon_lines >= max(2, len(lines) // 2):
        return "yaml"
    if _LOG_LINE_RE.search(text) and len(lines) >= 3:
        # Several timestamped/level-prefixed lines -> logs.
        log_hits = sum(1 for line in lines if _LOG_LINE_RE.match(line.strip()))
        if log_hits >= 2:
            return "logs"
    if _CODE_HINT_RE.search(text) and len(lines) >= 2:
        return "code"
    if _CONFIG_HINT_RE.search(text) and len(lines) >= 2 and "=" in text or ":" in text:
        # Config-like key=value / key: value blocks (conservative: line-safe).
        kv_hits = sum(1 for line in lines if _CONFIG_HINT_RE.match(line))
        if kv_hits >= 2:
            return "config"
    if stripped.startswith("#") or re.match(r"^#{1,6}\s", stripped):
        return "markdown"
    return "prose"


def _cut_at_word_boundary(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    cut = text.rfind(" ", 0, budget)
    if cut < max(20, budget // 2):
        cut = budget  # no good word boundary; hard cut is acceptable for prose
    return text[:cut]


def _cut_at_line_boundary(text: str, budget: int) -> str | None:
    """Cut at the last newline within budget; None when no safe line boundary exists."""
    if len(text) <= budget:
        return text
    newline = text.rfind("\n", 0, budget)
    if newline < 0:
        return None
    head = text[:newline].rstrip()
    return head if head else None


def trim_block_safe(
    text: str, head_chars: int, *, content_type: str | None = None
) -> tuple[str, bool, str]:
    """Trim a block safely. Returns ``(rendered_head, ok, content_type)``.

    ``ok=False`` means no safe trimmed form exists — the caller must KEEP the block.
    The audit note line is added by the caller (compactor), not here.
    """
    ctype = content_type or detect_content_type(text)
    if head_chars <= 0 or len(text) <= head_chars + 200:
        return text, False, ctype  # too small to trim; signal "keep whole"
    if ctype == "high_risk":
        return text, False, ctype  # TRIM -> KEEP for high-risk content
    if ctype in ("json", "yaml", "xml"):
        # Structured formats: only trim when the head remains parseable AND ends at a
        # line boundary. Otherwise refuse — a broken structure misleads more than it saves.
        head = _cut_at_line_boundary(text, head_chars)
        if head is None:
            return text, False, ctype
        try:
            if ctype == "json":
                json.loads(head)
            elif ctype == "xml":
                ET.fromstring(head)
            else:  # yaml: structural check without a dependency — balanced indent lines
                if not head.strip():
                    return text, False, ctype
        except Exception:
            return text, False, ctype
        return head, True, ctype
    if ctype == "markdown_table":
        # Row-aware: keep header + delimiter + as many full rows as fit.
        lines = text.splitlines()
        try:
            delim_idx = next(
                i for i, line in enumerate(lines) if _TABLE_DELIM_RE.match(line)
            )
        except StopIteration:
            return text, False, ctype
        keep = lines[: delim_idx + 1]
        budget = head_chars
        used = sum(len(line) + 1 for line in keep)
        for line in lines[delim_idx + 1 :]:
            if used + len(line) + 1 > budget:
                break
            keep.append(line)
            used += len(line) + 1
        if len(keep) <= delim_idx + 1:
            return text, False, ctype  # not even one data row fits
        return "\n".join(keep), True, ctype
    if ctype == "logs":
        # Head + tail: oldest context plus the most recent state (usually at the end).
        if head_chars < 120:
            return text, False, ctype
        lines = text.splitlines()
        head_budget = head_chars // 3
        tail_budget = head_chars - head_budget
        head_text = "\n".join(lines[: max(1, len(lines) // 4)])[:head_budget]
        tail_text = "\n".join(lines[-(len(lines) // 2 or 1) :])[-tail_budget:]
        # Re-cut both halves at line boundaries for clean edges.
        head_cut = head_text.rfind("\n")
        if head_cut > 20:
            head_text = head_text[:head_cut]
        tail_start = tail_text.find("\n")
        if 0 <= tail_start < len(tail_text) // 2:
            tail_text = tail_text[tail_start + 1 :]
        combined = (head_text.rstrip() + "\n" + tail_text.lstrip()).strip()
        if not combined or len(combined) >= len(text):
            return text, False, ctype
        return combined, True, ctype
    if ctype in ("code", "config", "markdown", "yaml"):
        head = _cut_at_line_boundary(text, head_chars)
        if head is None:
            return text, False, ctype
        return head, True, ctype
    # prose (default): word-boundary head cut; head+tail was evaluated and rejected as
    # default because stitching two prose halves mid-argument reads as a new claim.
    return _cut_at_word_boundary(text, head_chars), True, ctype
