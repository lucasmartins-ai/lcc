"""Conservative removal of obvious boilerplate lines (signatures, page markers, rules)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lcc.schemas import CleaningStep

# Each pattern is matched against the FULL stripped line only, so partial content is never
# truncated. The set is intentionally conservative: it targets lines that are almost never
# meaningful content. See SECURITY.md and the README "Limitations" section.
_DEFAULT_PATTERNS: dict[str, re.Pattern[str]] = {
    "email_signature": re.compile(
        r"^sent from my (iphone|ipad|ipod|android|samsung|galaxy"
        r"|mobile device|mobile|blackberry|huawei|pixel)\b.*$",
        re.IGNORECASE,
    ),
    "page_marker": re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.IGNORECASE),
    "email_reply_header": re.compile(r"^on .+ wrote:$", re.IGNORECASE),
    # 4+ identical decorative characters; a 3-char Markdown rule ("---") is preserved.
    "decorative_rule": re.compile(r"^([-=_*~])\1{3,}$"),
}


@dataclass
class BoilerplateResult:
    """Cleaned text plus one cleaning step per pattern that removed at least one line."""

    text: str
    actions: list[CleaningStep]


def remove_common_boilerplate(
    text: str,
    *,
    patterns: dict[str, re.Pattern[str]] | None = None,
) -> BoilerplateResult:
    """Remove obvious boilerplate lines using a conservative, whole-line match.

    Only lines that match a boilerplate pattern *in full* (after stripping) are removed.
    The default patterns cover mobile email signatures ("Sent from my iPhone"), page
    markers ("Page 3 of 10"), quoted-reply headers ("On <date>, <name> wrote:"), and long
    decorative rules (``====``, ``----``, ``****``). Markdown thematic breaks of exactly
    three characters are preserved.

    Returns the cleaned text and a list of applied actions (one per matching pattern).
    """
    active = patterns if patterns is not None else _DEFAULT_PATTERNS
    counts: dict[str, int] = dict.fromkeys(active, 0)
    kept: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()
        matched: str | None = None
        if stripped:
            for name, pattern in active.items():
                if pattern.match(stripped):
                    matched = name
                    break
        if matched is not None:
            counts[matched] += 1
        else:
            kept.append(line)

    actions = [
        CleaningStep(
            f"remove_boilerplate:{name}",
            f"Removed {count} boilerplate line(s) matching '{name}'.",
            {"removed_lines": count},
        )
        for name, count in counts.items()
        if count > 0
    ]
    return BoilerplateResult(text="\n".join(kept), actions=actions)
