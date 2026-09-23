#!/usr/bin/env python3
"""Real-context test: does a Laya checkpoint drop anything a real session needed?

The corpora are synthetic by construction, so every claim they support is a claim about a
dossier factory. This harness measures the same shipping path (``compact_context``, blocks
mode) on a **real** transcript — this machine's Hermes store or a real Claude Code JSONL —
against a real objective, and it does not need a human to score relevance: the user turns of
the session are the must-keep set, and they are checked byte-for-byte in the emitted text.

What it reports per arm: exact tokens before/after, reduction, blocks dropped, how many
must-keep user turns survived verbatim, and (for Laya arms) calls + latency.

Run: python3 benchmarks/research/laya_real_context_test.py --hermes latest
     python3 benchmarks/research/laya_real_context_test.py --claude-code ~/.claude/projects/-x/y.jsonl \
       --laya-model ~/Models/laya-lcc-relevance-v1
"""

from __future__ import annotations

# ruff: noqa: I001, E402 — sys.path bootstrap must precede sibling imports.
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

import measure_session  # noqa: E402  (sibling research harness)

from lcc.relevance import RelevanceCompactionRequest, compact_context  # noqa: E402
from lcc.relevance.laya import DEFAULT_LAYA_MODEL  # noqa: E402
from lcc.token_budget import count_tokens  # noqa: E402

RESULTS = HERE / "results"
DEFAULT_OBJECTIVE = (
    "What did the user ask for, what was decided, and what is still open?"
)
MIN_MUST_KEEP_CHARS = 40


def _user_texts(messages: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        text = (message.get("text") or "").strip()
        if len(text) >= MIN_MUST_KEEP_CHARS:
            texts.append(text)
    return texts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--hermes", help="Hermes session id, or 'latest'.")
    source.add_argument("--claude-code", help="Claude Code transcript (.jsonl).")
    parser.add_argument("--objective", default=DEFAULT_OBJECTIVE)
    parser.add_argument("--laya-model", action="append", default=[], help="Extra Laya checkpoint (id or path); repeatable.")
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Blocks per Laya state. Sessions carry blocks larger than Laya's window, so 1 is "
        "the honest default twice over: see docs/LAYA.md §5.",
    )
    parser.add_argument("--out", default=str(RESULTS / "laya_real_context_test.json"))
    args = parser.parse_args()

    if args.hermes:
        messages, stats = measure_session.from_hermes(args.hermes)
        label = f"hermes:{args.hermes}"
    else:
        messages, stats = measure_session.from_claude_code(Path(args.claude_code).expanduser())
        label = f"claude-code:{Path(args.claude_code).name}"
    text = measure_session.flatten(messages)
    must_keep = _user_texts(messages)
    tokens_in = count_tokens(text, "gpt-4.1").value
    print(
        f"source={label} messages={len(messages)} user_turns={len(must_keep)} "
        f"chars={len(text)} tokens={tokens_in}"
    )
    print(f"objective: {args.objective}\n")

    arms: list[tuple[str, str | None]] = [("mechanical", None)]
    for model in [DEFAULT_LAYA_MODEL] + args.laya_model:
        arms.append(("laya", model))

    records: list[dict[str, Any]] = []
    for provider, model in arms:
        started = time.perf_counter()
        request = RelevanceCompactionRequest(
            text=text,
            question=args.objective,
            provider=provider,
            threshold=args.threshold,
            laya_model=model or DEFAULT_LAYA_MODEL,
            batch_size=args.batch_size,
        )
        result = compact_context(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        report = result.report
        tokens_out = count_tokens(result.compacted_text, "gpt-4.1").value
        kept = [t for t in must_keep if t in result.compacted_text]
        missing = [t for t in must_keep if t not in result.compacted_text]
        warnings = list(report.warnings)
        oversized = [w for w in warnings if "laya_context_limit_exceeded" in w]
        by_source: dict[str, int] = {}
        for decision in report.decisions:
            by_source[decision.source] = by_source.get(decision.source, 0) + 1
        record = {
            "source": label,
            "objective": args.objective,
            "provider": provider,
            "laya_model": model,
            "provider_used": report.provider_used,
            "degraded": report.degraded,
            "semantic_guarantee": report.semantic_guarantee,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "reduction_pct": round(100.0 * (1 - tokens_out / max(1, tokens_in)), 2),
            "blocks_total": report.blocks_total,
            "blocks_scored": report.blocks_scored,
            "blocks_dropped": report.blocks_dropped,
            "blocks_trimmed": report.blocks_trimmed,
            "decisions_by_source": by_source,
            "oversized_blocks_kept_whole": len(oversized),
            "warnings_total": len(warnings),
            "must_keep_turns": len(must_keep),
            "must_keep_survived": len(kept),
            "must_keep_missing": len(missing),
            "missing_previews": [t[:90] for t in missing[:5]],
            "calls": report.calls,
            "latency_ms": report.latency_ms,
            "compilation_ms": getattr(report, "compilation_ms", None),
            "context_budget_used": report.context_budget_used,
            "laya_context_limit": report.laya_context_limit,
            "elapsed_ms": elapsed_ms,
            "warnings": warnings[:5],
        }
        records.append(record)
        print(
            f"{provider:11s} {str(model or DEFAULT_LAYA_MODEL):42s} "
            f"{tokens_in:>7d} -> {tokens_out:>7d} ({record['reduction_pct']:6.2f}%) "
            f"dropped {report.blocks_dropped:>3d}/{report.blocks_total} "
            f"(scored {report.blocks_scored}, oversized-kept {len(oversized)}) "
            f"user turns kept {len(kept)}/{len(must_keep)} "
            f"calls {report.calls} "
            f"{'degraded' if report.degraded else report.semantic_guarantee}"
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"\nrecords written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
