"""Deterministic text normalization (line endings, whitespace, blank lines)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lcc.schemas import CleaningStep

_LEADING_WS = re.compile(r"^[ \t]+")
_INNER_RUNS = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")
_BLANK_RUNS = re.compile(r"\n{3,}")


@dataclass
class NormalizeResult:
    """Normalized text plus the list of cleaning steps that were applied."""

    text: str
    steps: list[CleaningStep]


def normalize_text(text: str) -> NormalizeResult:
    """Normalize whitespace and line structure without altering meaning.

    Steps applied (each recorded in the result):

    1. Convert CRLF / CR line endings to LF.
    2. Strip trailing whitespace from every line.
    3. Collapse runs of 2+ interior spaces/tabs to a single space, preserving leading
       indentation.
    4. Collapse 3+ consecutive newlines (multiple blank lines) to a single blank line.
    5. Trim leading/trailing blank lines from the whole document.

    Paragraph structure (a single blank line between blocks) is preserved.
    """
    steps: list[CleaningStep] = []

    crlf = text.count("\r\n")
    cr_only = text.count("\r") - crlf
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if crlf or cr_only:
        steps.append(
            CleaningStep(
                "normalize_line_endings",
                "Converted CR/CRLF line endings to LF.",
                {"crlf": crlf, "cr": cr_only},
            )
        )

    trimmed = 0
    collapsed_lines = 0
    out_lines: list[str] = []
    for line in normalized.split("\n"):
        stripped = line.rstrip()
        if stripped != line:
            trimmed += 1
        lead_match = _LEADING_WS.match(stripped)
        lead = lead_match.group(0) if lead_match else ""
        body = stripped[len(lead) :]
        collapsed = _INNER_RUNS.sub(" ", body)
        if collapsed != body:
            collapsed_lines += 1
        out_lines.append(lead + collapsed)

    if trimmed:
        steps.append(
            CleaningStep(
                "strip_trailing_whitespace",
                "Removed trailing whitespace from lines.",
                {"lines": trimmed},
            )
        )
    if collapsed_lines:
        steps.append(
            CleaningStep(
                "collapse_inner_spaces",
                "Collapsed repeated interior spaces to a single space.",
                {"lines": collapsed_lines},
            )
        )

    joined = "\n".join(out_lines)
    joined, blank_runs = _BLANK_RUNS.subn("\n\n", joined)
    if blank_runs:
        steps.append(
            CleaningStep(
                "collapse_blank_lines",
                "Collapsed runs of blank lines to a single blank line.",
                {"runs": blank_runs},
            )
        )

    return NormalizeResult(text=joined.strip("\n"), steps=steps)
