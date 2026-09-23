#!/usr/bin/env python3
"""Benchmark comparison: Mechanical vs LCC -> Jev vs LCC -> Laya.

Evaluates the research hypothesis:
Can LCC's context compilation reduce a large context to a sufficiently small
decision-relevant representation that a local ~1K-context Laya model can make
useful semantic decisions without requiring a 32K-context remote decision model?

Measures across Small, Medium, and Large corpora:
  - Tokens in / Tokens out (exact token counts)
  - Compression ratio (%)
  - Ground truth recall (%)
  - Distractor leak (noise suppression)
  - Decision latency (ms)
  - Monetary cost ($)
  - Context budget compliance (insufficient_context alerts)

Outputs results to results/laya_comparison.jsonl and prints a Markdown comparison table.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import time
from typing import Any

from lcc.relevance import (
    LayaClient,
    RelevanceCompactionRequest,
    compact_context,
)
from lcc.relevance.laya import DEFAULT_LAYA_MODEL
from lcc.token_budget import count_tokens

ROOT = pathlib.Path(__file__).resolve().parent
CORPORA = ROOT / "corpora"
RESULTS = ROOT / "results"
OBJECTIVE = "What is wrong with the clinic's booking operation, and what limits what we can change?"
DISTRACTOR_PAT = r"DISTRACTOR \d"


class MockLayaDecisionAgent:
    """Offline mock agent simulating Laya inference for deterministic benchmarking."""

    def __init__(self, key_markers: list[str]) -> None:
        self.key_markers = key_markers

    def predict(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        texts = {}
        if isinstance(state, dict) and "blocks" in state:
            texts = {b["id"]: b.get("text", "") for b in state["blocks"]}

        answers = {}
        for qid, qdef in questions.items():
            block_id = qid[len("keep_") :] if qid.startswith("keep_") else qid
            text = texts.get(block_id, qdef.get("context", ""))

            # Highly relevant if it contains key markers or objective terms
            is_relevant = any(m in text for m in self.key_markers) or "booking" in text.lower()
            is_noise = bool(re.search(DISTRACTOR_PAT, text))

            if is_relevant and not is_noise:
                score = 0.95
                action = "keep"
            elif is_noise:
                score = 0.05
                action = "drop"
            else:
                score = 0.35
                action = "drop"

            answers[qid] = {
                "type": "noul",
                "noul": score,
                "confidence": 0.90,
                "action": action,
            }
        return {
            "answers": answers,
            "usage": {"tokens": 150},
            "model": "convaiinnovations/laya-multilingual",
        }


def load_ground_truth(scale: str) -> list[dict[str, str]]:
    index_file = CORPORA / "index.json"
    if not index_file.exists():
        return []
    index = json.loads(index_file.read_text(encoding="utf-8"))
    return index.get(scale, {}).get("items", [])


def compute_recall(text: str, items: list[dict[str, str]]) -> tuple[float, int]:
    if not items:
        return 1.0, 0
    found = sum(1 for item in items if re.search(item["marker"], text))
    recall_rate = round(found / len(items), 4)
    distractor_leak = len(re.findall(DISTRACTOR_PAT, text))
    return recall_rate, distractor_leak


def run_benchmark(
    scales: list[str],
    mock_laya: bool = False,
    laya_model: str | None = None,
    batch_size: int = 8,
) -> list[dict[str, Any]]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_file = RESULTS / "laya_comparison.jsonl"
    records = []

    print(f"\nRunning benchmark on scales: {', '.join(scales)}")
    print(f"Objective: {OBJECTIVE}\n")

    providers = ["mechanical", "laya"]
    if os.environ.get("TYPESAFE_API_KEY"):
        providers.insert(1, "jev")

    for scale in scales:
        corpus_path = CORPORA / f"{scale}.md"
        if not corpus_path.exists():
            print(f"Skipping missing corpus: {corpus_path}")
            continue

        raw_text = corpus_path.read_text(encoding="utf-8")
        tokens_in = count_tokens(raw_text, "gpt-4.1").value
        items = load_ground_truth(scale)
        key_markers = [item["marker"] for item in items]

        for provider in providers:
            client = None
            if provider == "laya" and mock_laya:
                mock_agent = MockLayaDecisionAgent(key_markers=key_markers)
                client = LayaClient(
                    model="convaiinnovations/laya-multilingual",
                    agent=mock_agent,
                )

            started = time.perf_counter()
            req = RelevanceCompactionRequest(
                text=raw_text,
                question=OBJECTIVE,
                provider=provider,
                client=client,
                threshold=0.4,
                # The request field is the only place a checkpoint is honoured: the compactor
                # stamps it over an injected client (see RESEARCH_STATUS, checkpoint selection).
                laya_model=laya_model if (provider == "laya" and laya_model) else DEFAULT_LAYA_MODEL,
                # Explicit in the row: a batched state collapses Laya's per-block judgement
                # (measured in docs/LAYA.md §5), so a run must say which batching it used.
                batch_size=batch_size,
            )
            result = compact_context(req)
            elapsed_ms = int((time.perf_counter() - started) * 1000)

            report = result.report
            tokens_out = count_tokens(result.compacted_text, "gpt-4.1").value
            reduction_pct = round(100.0 * (1.0 - (tokens_out / max(1, tokens_in))), 2)
            recall_rate, distractor_leak = compute_recall(result.compacted_text, items)

            cost_usd = 0.0
            if provider == "jev":
                # Jev remote pricing estimate: ~$0.0004 per 1k input tokens
                cost_usd = round(report.calls * 0.001, 4)

            record = {
                "scale": scale,
                "provider_requested": provider,
                "harness": "mock" if (provider == "laya" and mock_laya) else "real",
                "provider_used": report.provider_used,
                "degraded": report.degraded,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "reduction_pct": reduction_pct,
                "recall": recall_rate,
                "distractor_leak": distractor_leak,
                "blocks_dropped": report.blocks_dropped,
                "latency_ms": elapsed_ms,
                "cost_usd": cost_usd,
                "semantic_guarantee": report.semantic_guarantee,
                "warnings_count": len(report.warnings),
            }
            records.append(record)

    with open(out_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    return records


def print_table(records: list[dict[str, Any]]) -> None:
    headers = [
        "Corpus",
        "Provider",
        "Tokens In",
        "Tokens Out",
        "Reduction %",
        "Recall %",
        "Distractors",
        "Latency (ms)",
        "Cost ($)",
        "Guarantee",
    ]
    col_w = [10, 14, 11, 11, 13, 10, 13, 14, 10, 11]

    header_line = " | ".join(f"{h:<{w}}" for h, w in zip(headers, col_w, strict=False))
    separator = "-|-".join("-" * w for w in col_w)

    print("\n" + "=" * len(header_line))
    print("LAYA LOCAL SEMANTIC BACKEND EVALUATION RESULTS")
    print("=" * len(header_line))
    print(header_line)
    print(separator)

    for r in records:
        prov = r["provider_used"]
        if r.get("harness") == "mock":
            prov += " (mock)"
        if r["degraded"]:
            prov += "*"
        row = [
            r["scale"],
            prov,
            str(r["tokens_in"]),
            str(r["tokens_out"]),
            f"{r['reduction_pct']}%",
            f"{int(r['recall'] * 100)}%",
            str(r["distractor_leak"]),
            str(r["latency_ms"]),
            f"${r['cost_usd']:.4f}",
            r["semantic_guarantee"],
        ]
        print(" | ".join(f"{val:<{w}}" for val, w in zip(row, col_w, strict=False)))
    print("=" * len(header_line))
    print("* = degraded fail-safe retention (0 dropped blocks)\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LCC provider comparison benchmark")
    parser.add_argument(
        "--scales",
        nargs="+",
        default=["small", "medium", "large"],
        help="Corpora scales to evaluate",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Use the offline mock agent (harness check, NOT model evidence). "
        "Default runs the real Laya backend; the Jev arm runs live when TYPESAFE_API_KEY is set.",
    )
    parser.add_argument(
        "--laya-model",
        default=None,
        help="Laya checkpoint for the Laya arm (id or local directory), e.g. a fine-tuned "
        "checkpoint from benchmarks/research/laya_finetune_train.py.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Blocks per Laya state. 8 is the request default; 1 is the measured working "
        "configuration — a batched state collapses Laya's per-block judgement (docs/LAYA.md §5).",
    )
    parser.add_argument("--out", default=None, help="Write JSON records here (default: results/).")
    args = parser.parse_args()

    records = run_benchmark(
        args.scales,
        mock_laya=args.mock,
        laya_model=args.laya_model,
        batch_size=args.batch_size,
    )
    if args.out:
        pathlib.Path(args.out).write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
        )
        print(f"records written to {args.out}")
    print_table(records)


if __name__ == "__main__":
    main()
