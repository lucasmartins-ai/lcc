#!/usr/bin/env python3
"""End-to-end provider comparison: mechanical vs laya vs jev (offline-first).

Runs the same dossier through each `lcc compact` provider and prints one row
per provider: blocks dropped, reduction, guarantee, cost. No network, no key,
no Laya weights required:

- mechanical: real local scoring.
- laya: injected mock System 1 agent (same interface the real extra uses), so
  the semantic path, batching, budget accounting and fallback shape are all
  exercised without torch/transformers.
- jev: runs only with TYPESAFE_API_KEY set; otherwise honestly skipped.

Usage:  python3 examples/compact_providers.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, "src")

from lcc.relevance import LayaClient, RelevanceCompactionRequest, compact_context

OBJECTIVE = "reduce mobile booking friction"

DOSSIER = (
    "The clinic booking widget loses 63 percent of mobile visitors before the second step.\n\n"
    "A quoted complaint carries the evidence: the patient wrote: the form erased everything\n"
    "when I tapped back on my phone, so I gave up and called instead.\n\n"
    "LOG 1: queue worker heartbeat ok in 554ms, backlog 287 jobs, retry budget untouched.\n\n"
    "LOG 2: cron job lead-sync finished with 366 records processed and 3377 ms elapsed.\n\n"
    "Chatter about office plants and coffee machines needing water daily without fail.\n\n"
    "The decline occurred after the mobile redesign shipped to all users in June.\n\n"
)


class MockLayaAgent:
    """Tiny System 1 stand-in: keeps booking evidence, drops logs/chatter."""

    def predict(self, state, questions):
        texts = {b["id"]: b.get("text", "") for b in state.get("blocks", [])}
        answers = {}
        for qid in questions:
            bid = qid[len("keep_") :] if qid.startswith("keep_") else qid
            text = texts.get(bid, "").lower()
            keep = ("booking" in text or "wrote:" in text or "redesign" in text) and (
                "heartbeat" not in text and "cron job" not in text and "plants" not in text
            )
            answers[qid] = {
                "type": "noul",
                "noul": 0.92 if keep else 0.06,
                "confidence": 0.9,
                "action": "keep" if keep else "drop",
            }
        return {"answers": answers, "usage": {}, "model": "mock-laya"}


def run(provider: str, client=None) -> None:
    result = compact_context(
        RelevanceCompactionRequest(
            text=DOSSIER, question=OBJECTIVE, provider=provider, client=client
        )
    )
    r = result.report
    print(
        f"| {r.provider_used:26} | {r.blocks_dropped:>7} | "
        f"{r.reduction_ratio:>9.1%} | {r.semantic_guarantee:9} | "
        f"{r.calls:>5} | {r.degraded!s:8} |"
    )
    if provider == "laya" and client is not None:
        print(
            f"  budget: {r.context_budget_used}/{r.laya_context_limit} tokens, "
            f"model: {r.laya_model_resolved}, latency: {r.latency_ms} ms"
        )


def main() -> None:
    print(f"Objective: {OBJECTIVE}\n")
    print("| provider_used | dropped | reduction | guarantee | calls | degraded |")
    print("| :--- | ---: | ---: | :--- | ---: | :--- |")
    run("mechanical")
    run("laya", LayaClient(agent=MockLayaAgent()))
    # Honest fallback: requested laya, no extra installed.
    run("laya")
    if os.getenv("TYPESAFE_API_KEY"):
        run("jev")
    else:
        print("| jev (skipped: no TYPESAFE_API_KEY) |")
    print("\nLaya is the conservative middle: semantic judgment, offline, keeps more.")
    print("See docs/LAYA.md for limits, latency, and the full decision table.")


if __name__ == "__main__":
    main()
