"""Human-readable explanation of a relevance compaction report.

The report already records every decision, its score, its source and a reason code. This module
turns that into the answer to the question a person actually asks when a compaction pass looks
wrong: *why was this block dropped, and what was in it?*

Nothing here re-runs compaction or touches the network. It reads the report, and optionally the
source file, so a reviewer can audit a pass after the fact.
"""

from __future__ import annotations

from typing import Any

#: Reason code to plain-language explanation. Keys are exact codes; ``DYNAMIC_REASONS`` covers
#: the codes that carry a payload after a prefix.
REASON_EXPLANATIONS: dict[str, str] = {
    # model-scored path
    "score_above_threshold": "scored at or above the keep threshold",
    "score_in_trim_band": "borderline: only a bounded head of the block was kept",
    "score_in_trim_band_kept_whole": "borderline: too short to trim, so it was kept whole",
    "score_below_threshold": "scored below the drop threshold",
    # locally scored path
    "lexical_overlap": "shares words with the objective (local scorer)",
    "no_lexical_overlap": "shares no words with the objective (local scorer)",
    "short_block": "below the scoring floor, so it was never judged",
    "jev_unavailable_fail_safe": "the model scorer was unavailable, so nothing was dropped",
    # deterministic safety net
    "negation_or_exception_present": "carries a negation or an exception",
    "literal_value_present": "carries a literal value (number, unit, date or identifier)",
    "quoted_speech_present": "carries quoted third-party speech",
    # sufficiency + confidence + type-aware trim (ADR 0014)
    "semantic_sufficiency_restoration": "restored by sufficiency: linked to kept content",
    "high_risk_conservative_retention": "high-stakes content kept despite a low score",
    "low_confidence_kept": "low judge confidence, kept instead of dropped",
    "low_confidence_trimmed": "low judge confidence, trimmed instead of dropped",
    "trim_unsafe_kept_whole": "borderline but no safe trim boundary exists, kept whole",
}

#: Reason codes whose explanation depends on the payload after the prefix.
DYNAMIC_REASONS: dict[str, str] = {
    "evidence_in_": "written in another language than the objective ({payload}), kept because "
    "sharing no tokens with an English objective is not evidence of irrelevance",
    "link_terms:": "shares distinctive terms ({payload}) with a block that is being kept, so it "
    "is pulled in to avoid keeping a conclusion without its supporting evidence",
    "supersedes_value:": "revises or corrects a value carried by a kept block ({payload}), so it "
    "is kept to avoid leaving a superseded figure with no sign that it was replaced",
    "supports:": "supports kept content ({payload})",
    "qualifies:": "qualifies kept content ({payload})",
    "contradicts:": "contradicts kept content ({payload}), kept for review rather than dropped",
    "supersedes:": "supersedes kept content ({payload})",
    "duplicates:": "duplicates kept content ({payload})",
    "protected:": "explicitly protected ({payload}), never scored",
    "kept_by:": "kept by an explicit rule ({payload})",
    "sticky_decision:": "reused sticky decision first made by {payload}",
}


def explain_reason(reason: str | None) -> str:
    """Plain-language explanation for a decision reason code."""
    if not reason:
        return "no reason recorded"
    if reason in REASON_EXPLANATIONS:
        return REASON_EXPLANATIONS[reason]
    for prefix, template in DYNAMIC_REASONS.items():
        if reason.startswith(prefix):
            payload = reason[len(prefix) :].strip()
            return template.format(payload=payload or "unspecified")
    return f"recorded as {reason!r}"


def _block_preview(source_lines: list[str], start: int, end: int, width: int = 96) -> str:
    """First non-empty line of a block, trimmed to a readable width."""
    for line in source_lines[max(0, start - 1) : end]:
        text = line.strip()
        if text:
            return text if len(text) <= width else text[: width - 1] + "…"
    return ""


def _fmt_int(value: Any) -> str:
    return f"{value:,}".replace(",", " ") if isinstance(value, int) else str(value)


def summarize(report: dict[str, Any]) -> list[tuple[str, str]]:
    """Header rows: what the pass was asked to do and what it cost."""
    rows: list[tuple[str, str]] = [
        ("Objective", str(report.get("objective", ""))),
        (
            "Provider",
            f"{report.get('provider_used', '?')} "
            f"(requested {report.get('provider_requested', '?')})",
        ),
        ("Semantic guarantee", str(report.get("semantic_guarantee", "?"))),
    ]
    if report.get("degraded"):
        rows.append(("Degraded", str(report.get("degradation_reason") or "yes, reason unrecorded")))

    threshold = report.get("threshold")
    trim = report.get("trim_threshold")
    if threshold is not None:
        band = f"keep >= {threshold:.2f}" if trim is None else (
            f"keep >= {threshold:.2f}, trim {trim:.2f}-{threshold:.2f}"
        )
        rows.append(("Thresholds", band))

    decisions = report.get("decisions") or []
    counts = {"keep": 0, "trim": 0, "drop": 0}
    for decision in decisions:
        kind = decision.get("decision", "keep")
        counts[kind] = counts.get(kind, 0) + 1
    rows.append(
        (
            "Blocks",
            f"{_fmt_int(report.get('blocks_total', len(decisions)))} total | "
            f"{_fmt_int(report.get('blocks_scored', 0))} scored | "
            f"{_fmt_int(report.get('blocks_protected', 0))} protected",
        )
    )
    rows.append(
        ("Decisions", f"{counts['keep']} keep | {counts['trim']} trim | {counts['drop']} drop")
    )
    rows.append(
        (
            "Chars",
            f"{_fmt_int(report.get('chars_before'))} -> {_fmt_int(report.get('chars_after'))} "
            f"({float(report.get('reduction_ratio', 0.0)):.1%} smaller)",
        )
    )
    rows.append(
        (
            "Tokens",
            f"{_fmt_int(report.get('tokens_before'))} -> {_fmt_int(report.get('tokens_after'))} "
            f"({report.get('token_count_method', '?')})",
        )
    )

    mutation = report.get("first_mutation_offset")
    if mutation is not None:
        cache = f"first mutation at offset {_fmt_int(mutation)}"
        if report.get("prefix_protected"):
            cache += ", prefix protected" + (
                " and untouched" if report.get("prefix_untouched") else " but not untouched"
            )
        if report.get("invalidated_tokens"):
            cache += f", invalidates {_fmt_int(report['invalidated_tokens'])} tokens"
        if report.get("break_even_reuses") is not None:
            cache += f", pays off after ~{report['break_even_reuses']:g} reuses"
        rows.append(("Cache", cache))

    if report.get("provider_used") == "cache":
        reused = _fmt_int(report.get("reused_decisions", 0))
        rows.append(("Scoring", f"fully reused {reused} cached decisions"))
    elif report.get("calls"):
        rows.append(
            (
                "Scoring",
                f"{_fmt_int(report['calls'])} call(s) in {_fmt_int(report.get('latency_ms', 0))} ms"
                + (
                    f", {_fmt_int(report['reused_decisions'])} reused"
                    if report.get("reused_decisions")
                    else ""
                ),
            )
        )

    rows.append(
        (
            "Verdict",
            "worth a cache epoch" if report.get("worth_it", True) else "NOT worth a cache epoch",
        )
    )
    return rows


def render(
    report: dict[str, Any],
    *,
    only: str | None = None,
    limit: int | None = None,
    source_text: str | None = None,
) -> str:
    """Render the explanation as plain text.

    ``only`` filters to one decision kind, ``limit`` caps how many blocks are listed, and
    ``source_text`` adds a preview of each block read from the original input.
    """
    lines: list[str] = []
    lines.append("lcc explain — why every block was kept, trimmed or dropped")
    lines.append("")
    for label, value in summarize(report):
        lines.append(f"{label:<19} {value}")

    source_lines = source_text.splitlines() if source_text is not None else []
    decisions = list(report.get("decisions") or [])

    groups: list[tuple[str, str]] = [("drop", "DROPPED"), ("trim", "TRIMMED"), ("keep", "KEPT")]
    if only:
        wanted = only.strip().lower()
        if wanted not in {name for name, _ in groups}:
            raise ValueError(f"unknown decision {only!r}; expected keep, trim or drop")
        groups = [(name, title) for name, title in groups if name == wanted]

    total_shown = 0
    for name, title in groups:
        selected = [d for d in decisions if d.get("decision") == name]
        lines.append("")
        header = f"{title} ({len(selected)})"
        lines.append(header)
        lines.append("-" * len(header))
        if limit is not None:
            selected = selected[:limit]
        if not selected:
            lines.append("  (none)")
            continue
        for decision in selected:
            total_shown += 1
            score = decision.get("score")
            score_text = "  n/a " if score is None else f"{score:5.2f}"
            span = f"{decision.get('line_start', '?')}-{decision.get('line_end', '?')}"
            lines.append(
                f"  {decision.get('id', '?')[:22]:<22} {score_text}  "
                f"lines {span:<11} {decision.get('chars', 0):>6} chars  "
                f"{decision.get('source', '?')}"
            )
            lines.append(f"      why: {explain_reason(decision.get('reason'))}")
            if name == "trim" and decision.get("chars_after") is not None:
                kept = decision["chars_after"]
                lines.append(f"      kept {kept} of {decision.get('chars', 0)} chars")
            if source_lines:
                preview = _block_preview(
                    source_lines,
                    int(decision.get("line_start", 1)),
                    int(decision.get("line_end", 1)),
                )
                if preview:
                    lines.append(f"      text: {preview}")

    if limit is not None and total_shown:
        lines.append("")
        lines.append(f"(limited to {limit} per group; drop --limit for the full trail)")

    warnings = report.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append(f"WARNINGS ({len(warnings)})")
        lines.append("-" * 10)
        for warning in warnings:
            lines.append(f"  - {warning}")

    return "\n".join(lines)
