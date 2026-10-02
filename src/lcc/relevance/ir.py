"""Versioned Context IR emission (MSI Sprint 2, ADR 0017).

Maps a finished relevance-compaction pass onto the provider-independent
``context-ir/0.1`` envelope (``minimum-sufficient-inference/spec``). Pure mapping:
no scoring, no thresholds, no network, no new dependencies. Reuses
``blocks.py`` (verbatim units), ``graph.py`` (typed edges) and ``decisions.py``
(policy identity) — it duplicates none of them.

Determinism: units follow block index order, id lists are index-ordered, edges are
sorted by ``(from, to, type)``, and serialization uses sorted keys. The only
timestamp in the body is ``provenance.collected_at``, which is caller-supplied
and defaults to :data:`DEFAULT_COLLECTED_AT` so identical inputs emit identical
bytes. Pass the real collection time when audit truth matters more than
byte-stability (golden fixtures always use the default).

``necessity`` is always ``UNKNOWN`` here: causal labels arrive with the ablation
harness (MSI Sprint 6), never from this emitter.
"""

from __future__ import annotations

import json
from typing import Any

from lcc.relevance.blocks import TextBlock
from lcc.relevance.decisions import POLICY_VERSION
from lcc.relevance.graph import ContextGraph

IR_SCHEMA_VERSION = "context-ir/0.1"
IR_VERSION = "0.1"

#: Deterministic default for ``provenance.collected_at`` (RFC3339). Real runs may
#: override it via ``collected_at``; tests and golden fixtures use this value.
DEFAULT_COLLECTED_AT = "2026-10-02T00:00:00Z"

#: Decision reasons that mean "this block was restored, not originally kept".
#: Kept in one place so emission and tests agree on what counts as restored.
RESTORATION_REASONS = frozenset(
    {
        "semantic_sufficiency_restoration",
        "semantic_verifier_fail_restoration",
    }
)

__all__ = [
    "DEFAULT_COLLECTED_AT",
    "IR_SCHEMA_VERSION",
    "IR_VERSION",
    "POLICY_VERSION",
    "RESTORATION_REASONS",
    "build_context_ir",
    "dumps_canonical",
    "is_context_ir",
    "render_ir_explanation",
    "restored_ids",
    "summarize_ir",
]


def _unit_source(origin: str, block: TextBlock) -> str:
    """Source pointer ``origin:lines`` for one block (spec ``path:lines`` form)."""
    return f"{origin}:{block.line_start}-{block.line_end}"


def _relevance_of(decision: Any) -> float:
    """Score in [0, 1]; unscored keeps count as 1.0, unscored drops as 0.0."""
    score = getattr(decision, "score", None)
    if isinstance(score, (int, float)):
        return max(0.0, min(1.0, float(score)))
    return 1.0 if getattr(decision, "decision", "") == "keep" else 0.0


def restored_ids(ordered: list[Any]) -> list[str]:
    """Ids flipped drop/trim -> keep by a bounded restoration, in index order."""
    return sorted(
        (d.id for d in ordered if getattr(d, "reason", "") in RESTORATION_REASONS),
        key=lambda bid: next(d.index for d in ordered if d.id == bid),
    )


def build_context_ir(
    *,
    task_id: str,
    blocks: list[TextBlock],
    ordered: list[Any],
    graph: ContextGraph | None,
    policy_version: str = POLICY_VERSION,
    restoration_budget: int = 0,
    sufficient: bool = True,
    missing_evidence: list[str] | None = None,
    confidence: float = 0.0,
    restored: list[str] | None = None,
    restoration_reason: str = "",
    origin: str = "inline",
    collected_at: str = DEFAULT_COLLECTED_AT,
    transform: str = "none",
) -> dict[str, Any]:
    """Build a ``context-ir/0.1`` dict from a finished compaction pass.

    ``blocks`` are the verbatim split units, ``ordered`` the final per-block
    decisions (same ids, index order), ``graph`` the typed relationship graph or
    ``None`` when analysis failed. Every decision carries a non-empty reason by
    construction (protected / scored / sanitized / restored), so every dropped
    unit is explainable via ``selection.rationale``.
    """
    decisions = {d.id: d for d in ordered}

    edges = sorted(
        (graph.edges if graph is not None else []),
        key=lambda e: (e.source, e.target, e.type.value),
    )
    outgoing: dict[str, list[dict[str, str]]] = {b.id: [] for b in blocks}
    for edge in edges:
        if edge.source in outgoing:
            outgoing[edge.source].append({"to": edge.target, "type": edge.type.value})

    units: list[dict[str, Any]] = []
    for block in blocks:
        decision = decisions[block.id]
        unit: dict[str, Any] = {
            "id": block.id,
            "content": block.text,
            "source": _unit_source(origin, block),
            "provenance": {
                "origin": origin,
                "collected_at": collected_at,
                "transform": transform,
            },
            "relevance": _relevance_of(decision),
            "necessity": "UNKNOWN",
            "protected": bool(block.protected),
        }
        deps = sorted({rel["to"] for rel in outgoing[block.id] if rel["type"] == "DEPENDS_ON"})
        if deps:
            unit["dependencies"] = deps
        if outgoing[block.id]:
            unit["relationships"] = outgoing[block.id]
        units.append(unit)

    kept = [d.id for d in ordered if d.decision == "keep"]
    trimmed = [d.id for d in ordered if d.decision == "trim"]
    dropped = [d.id for d in ordered if d.decision == "drop"]
    rationale = {d.id: d.reason for d in ordered}

    restored_list = list(restored) if restored is not None else []
    return {
        "schema_version": IR_SCHEMA_VERSION,
        "ir_version": IR_VERSION,
        "task_id": task_id,
        "units": units,
        "relationships": [{"from": e.source, "to": e.target, "type": e.type.value} for e in edges],
        "selection": {
            "kept": kept,
            "trimmed": trimmed,
            "dropped": dropped,
            "policy": policy_version,
            "rationale": rationale,
        },
        "sufficiency": {
            "sufficient": bool(sufficient),
            "missing_evidence": list(missing_evidence or []),
            "confidence": max(0.0, min(1.0, float(confidence))),
        },
        "restoration": {
            "restored": restored_list,
            "budget": max(0, int(restoration_budget)),
            "reason": restoration_reason,
        },
    }


def dumps_canonical(ir: dict[str, Any]) -> str:
    """Deterministic serialization: sorted keys, stable indent, trailing newline."""
    return json.dumps(ir, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def is_context_ir(payload: Any) -> bool:
    """True when ``payload`` is a Context IR envelope (not a compaction report)."""
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == IR_SCHEMA_VERSION
        and isinstance(payload.get("units"), list)
        and isinstance(payload.get("selection"), dict)
    )


def summarize_ir(ir: dict[str, Any]) -> list[tuple[str, str]]:
    """Header rows for ``lcc inspect --ir``: what the IR holds and whether it suffices."""
    selection = ir.get("selection", {})
    kept = selection.get("kept", [])
    trimmed = selection.get("trimmed", [])
    dropped = selection.get("dropped", [])
    sufficiency = ir.get("sufficiency", {})
    restoration = ir.get("restoration", {})
    rows = [
        ("Task", str(ir.get("task_id", "?"))),
        ("IR version", f"{ir.get('ir_version', '?')} ({ir.get('schema_version', '?')})"),
        ("Units", str(len(ir.get("units", [])))),
        (
            "Selection",
            f"{len(kept)} keep | {len(trimmed)} trim | {len(dropped)} drop",
        ),
        ("Policy", str(selection.get("policy", "?"))),
        (
            "Sufficient",
            f"{bool(sufficiency.get('sufficient', False))} "
            f"(confidence {float(sufficiency.get('confidence', 0.0)):.2f})",
        ),
        (
            "Restored",
            f"{len(restoration.get('restored', []))} of budget {restoration.get('budget', 0)}",
        ),
        ("Edges", str(len(ir.get("relationships", [])))),
    ]
    missing = sufficiency.get("missing_evidence") or []
    if missing:
        rows.append(("Missing", "; ".join(missing[:3])))
    if restoration.get("reason"):
        rows.append(("Restore reason", str(restoration["reason"])))
    return rows


def _preview(text: str, width: int = 96) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped if len(stripped) <= width else stripped[: width - 1] + "…"
    return ""


def render_ir_explanation(
    ir: dict[str, Any],
    *,
    only: str | None = None,
    limit: int | None = None,
) -> str:
    """Plain-text audit of a Context IR: every unit, its verdict, and why.

    Reads the IR only — never re-runs compaction, never touches the network.
    Every dropped unit carries its rationale, so drop coverage is total by
    construction (asserted in ``tests/test_context_ir.py``).
    """
    from lcc.reporting.explain import explain_reason  # reuse reason vocabulary

    if only is not None:
        wanted = only.strip().lower()
        if wanted not in {"keep", "trim", "drop"}:
            raise ValueError(f"unknown decision {only!r}; expected keep, trim or drop")
    selection = ir.get("selection", {})
    rationale = selection.get("rationale", {})
    units = {u.get("id"): u for u in ir.get("units", [])}
    lines = ["lcc explain — context IR audit (every unit, its verdict, and why)", ""]
    for label, value in summarize_ir(ir):
        lines.append(f"{label:<19} {value}")
    groups = [("drop", "DROPPED"), ("trim", "TRIMMED"), ("keep", "KEPT")]
    if only is not None:
        only_norm = only.strip().lower()
        groups = [(name, title) for name, title in groups if name == only_norm]
    total_shown = 0
    for name, title in groups:
        key = {"keep": "kept", "trim": "trimmed", "drop": "dropped"}[name]
        ids = list(selection.get(key, []))
        lines.append("")
        header = f"{title} ({len(ids)})"
        lines.append(header)
        lines.append("-" * len(header))
        if limit is not None:
            ids = ids[:limit]
        if not ids:
            lines.append("  (none)")
            continue
        for uid in ids:
            total_shown += 1
            unit = units.get(uid, {})
            reason = rationale.get(uid, "")
            relevance = unit.get("relevance")
            score_text = "  n/a " if relevance is None else f"{float(relevance):5.2f}"
            source = unit.get("source", "?")
            content = unit.get("content", "")
            lines.append(
                f"  {uid[:22]:<22} {score_text}  {source}  protected={unit.get('protected', False)}"
            )
            lines.append(f"      why: {explain_reason(reason)}")
            preview = _preview(content)
            if preview:
                lines.append(f"      text: {preview}")
    if limit is not None and total_shown:
        lines.append("")
        lines.append(f"(limited to {limit} per group; drop --limit for the full trail)")
    sufficiency = ir.get("sufficiency", {})
    missing = sufficiency.get("missing_evidence") or []
    if missing:
        lines.append("")
        lines.append(f"MISSING EVIDENCE ({len(missing)})")
        lines.append("-" * 10)
        for item in missing:
            lines.append(f"  - {item}")
    return "\n".join(lines)
