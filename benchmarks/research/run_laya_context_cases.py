#!/usr/bin/env python3
"""Laya context-budget validation — Cases A/B/C through the REAL backend.

Verifies the relationship between LCC context compilation and Laya's smaller
context window, with no mocks:

  A. budget already fits   : small block set -> LCC -> one computed state inside
                             the budget -> Laya judges it.
  B. larger than the budget: a multi-thousand-token corpus -> LCC batches blocks
                             into in-budget states (objective + batch <=
                             available_state_tokens) -> Laya judges each batch.
  C. single oversized block: one block larger than the whole state budget -> LCC
                             refuses naive slicing, keeps it whole with
                             ``laya_context_limit_exceeded`` and
                             ``status: insufficient_context`` (fail-safe).

Recorded per case (from the existing report, nothing invented):
raw_context_tokens, compacted_tokens, laya_context_limit, reserved_tokens
(head reservation), available_state_tokens, blocks kept/dropped/trimmed,
provider_used, degraded, semantic_guarantee, calls, latency_ms,
context_budget_used, warnings, and a sample of decisions (score/confidence).

Runs REAL Laya weights (HF cache). Select the checkpoint with ``LCC_LAYA_MODEL``.

Run:
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 benchmarks/research/run_laya_context_cases.py
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from lcc.relevance import LayaClient, RelevanceCompactionRequest, compact_context  # noqa: E402
from lcc.token_budget import count_tokens  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
CORPORA = ROOT / "corpora"
RESULTS = ROOT / "results"

OBJECTIVE = "What is wrong with the clinic's booking operation, and what limits what we can change?"

_FILLER = " Background context sentence with neutral filler vocabulary rounding out the block."

CASE_A_BLOCKS = [
    "The booking widget loses 63 percent of mobile visitors at the date picker step." + _FILLER,
    "Revised: May conversion is restated down from 8.7 percent to 4.2 percent." + _FILLER,
    "Support ticket 4471: checkout fails unless the coupon field is empty." + _FILLER,
    "The refund policy allows claims, but never for sealed auction items." + _FILLER,
    "Office chatter about plants needing water near the coffee machine daily." + _FILLER,
    "Parking permits renew in spring; the lot repaving starts someday soon." + _FILLER,
]

# Same shape as the comparative stress "giant" case: a block far above the budget.
GIANT_BLOCK = (
    "CRITICAL CONSTRAINT: The clinic cannot modify weekend hours under municipal license code ML-409.\n\n"
    "Giant data dump that vastly exceeds Laya 1024 context limit: "
    + ("unrelated_log_payload_segment_metric_alpha_beta_gamma " * 2500)
)


def _count(text: str) -> int:
    return count_tokens(text, "gpt-4.1").value


def _run_case(name: str, text: str, model: str | None = None) -> dict[str, Any]:
    client = LayaClient(model=model) if model else LayaClient()
    model_kw: dict[str, Any] = {"laya_model": model} if model else {}
    started = time.perf_counter()
    result = compact_context(
        RelevanceCompactionRequest(
            text=text,
            question=OBJECTIVE,
            provider="laya",
            client=client,
            threshold=0.4,
            **model_kw,
        )
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    report = result.report
    decisions = [
        {
            "id": d.id[:40],
            "decision": d.decision,
            "score": d.score,
            "confidence": d.confidence,
            "source": d.source,
            "reason": d.reason,
        }
        for d in report.decisions[:6]
    ]
    oversized_flags = [w for w in report.warnings if "laya_context_limit_exceeded" in w]
    return {
        "case": name,
        "raw_context_tokens": _count(text),
        "compacted_tokens": _count(result.compacted_text),
        "laya_context_limit": report.laya_context_limit,
        "reserved_tokens": client.head_reservation,
        "available_state_tokens": client.available_state_tokens,
        "context_budget_used": report.context_budget_used,
        "provider_requested": report.provider_requested,
        "provider_used": report.provider_used,
        "degraded": report.degraded,
        "degradation_reason": report.degradation_reason,
        "semantic_guarantee": report.semantic_guarantee,
        "laya_model_requested": report.laya_model_requested,
        "laya_model_resolved": report.laya_model_resolved,
        "blocks_total": report.blocks_total,
        "blocks_scored": report.blocks_scored,
        "blocks_protected": report.blocks_protected,
        "blocks_dropped": report.blocks_dropped,
        "blocks_trimmed": report.blocks_trimmed,
        "reduction_ratio": report.reduction_ratio,
        "calls": report.calls,
        "latency_ms": report.latency_ms,
        "compilation_ms": elapsed_ms,
        "warnings_count": len(report.warnings),
        "insufficient_context_blocks": len(oversized_flags),
        "sample_decisions": decisions,
        # Case-C integrity: the giant block must survive whole (never sliced).
        "giant_tail_present": (GIANT_BLOCK[-64:] in result.compacted_text) if name == "C_oversized_block" else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Laya context-budget cases A/B/C (real backend).")
    parser.add_argument("--out", default=str(RESULTS / "laya_context_cases.json"))
    parser.add_argument("--scales", nargs="+", default=["A", "B", "C"])
    parser.add_argument(
        "--model",
        default=None,
        help="Laya checkpoint (default: LCC_LAYA_MODEL or convaiinnovations/laya-multilingual). "
        "Passed into the request explicitly — the env var alone is stamped over by the default.",
    )
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []

    if "A" in args.scales:
        text_a = "\n\n".join(CASE_A_BLOCKS) + "\n"
        cases.append(_run_case("A_small_context_fits", text_a, model=args.model))
    if "B" in args.scales:
        medium = (CORPORA / "medium.md").read_text(encoding="utf-8")
        cases.append(_run_case("B_larger_than_budget", medium, model=args.model))
    if "C" in args.scales:
        text_c = GIANT_BLOCK + "\n\n" + CASE_A_BLOCKS[0] + "\n"
        cases.append(_run_case("C_oversized_block", text_c, model=args.model))

    print("\n" + "=" * 100)
    print("LAYA CONTEXT-BUDGET CASES (real backend)")
    print("=" * 100)
    for c in cases:
        print(
            f"[{c['case']:<26}] raw={c['raw_context_tokens']:>6} -> compacted={c['compacted_tokens']:>6} | "
            f"budget_used={c['context_budget_used']}/{c['laya_context_limit']} (avail={c['available_state_tokens']}) | "
            f"kept/dropped/trimmed={c['blocks_total'] - c['blocks_dropped']}/{c['blocks_dropped']}/{c['blocks_trimmed']} | "
            f"calls={c['calls']} | insuff={c['insufficient_context_blocks']} | guide={c['semantic_guarantee']} | "
            f"degraded={c['degraded']}"
        )
    out = pathlib.Path(args.out)
    out.write_text(json.dumps({"cases": cases}, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
