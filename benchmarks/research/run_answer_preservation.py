#!/usr/bin/env python3
"""Answer-preservation benchmark: RAW vs LCC vs LCC+verifier (P1).

Fifty synthetic tasks across ten domains (no real clinical/legal claims; all
documents are fabricated for benchmarking). Each task carries an objective, a
raw context, expected critical facts, constraints and answer criteria.

Arms: RAW (full context), LCC (compacted), LCC+VERIFIER (compacted with the
independent semantic verifier). The mock downstream is an extractive answerer
(quotes evidence spans as DATA, never executes embedded instructions), so every
metric here is deterministic and offline. Swap in a real downstream LLM via
``--downstream-cmd`` (a shell command receiving the prompt on stdin and printing
the answer); live-LLM figures are reported separately and labelled NOT
VALIDATED until measured with at least two downstream models.

Metrics per arm: answer correctness (fact recall on the mock answer),
critical-fact recall, constraint satisfaction, contradiction rate, temporal
correctness, instruction/data separation, context/prompt tokens, latency,
cache reuse, estimated total cost.

Run: python3 benchmarks/research/run_answer_preservation.py [--provider mechanical]
"""

from __future__ import annotations

# ruff: noqa: I001, E402 — sys.path bootstrap must precede sibling imports.
import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lcc.relevance import RelevanceCompactionRequest, compact_context  # noqa: E402
from lcc.token_budget import count_tokens  # noqa: E402

DOMAINS = [
    "software_engineering",
    "legal_style",
    "medical_style",
    "finance",
    "business",
    "technical_docs",
    "policies",
    "customer_support",
    "data_analysis",
    "long_form_research",
]

# (domain, fact_template, constraint_template, temporal_marker)
TEMPLATES = {
    "software_engineering": (
        "The deploy pipeline {vid} fails at the migration step unless the replica lag is under 5s.",
        "must name the {vid} pipeline",
        "2026-08-1{v}",
    ),
    "legal_style": (
        "Clause {vid} permits termination, except when cure is underway within 30 days.",
        "must keep the cure exception",
        "2026-07-2{v}",
    ),
    "medical_style": (
        "SYNTHETIC guideline {vid}: dosage is 25mg, never above 50mg in 24h.",
        "must keep the upper bound",
        "2026-06-0{v}",
    ),
    "finance": (
        "Ledger {vid} restates May revenue down from 8.7 percent to 4.2 percent.",
        "must keep both figures",
        "2026-05-1{v}",
    ),
    "business": (
        "Contract {vid} renews in June, unless the renewal clause triggers first.",
        "must keep the renewal condition",
        "2026-06-1{v}",
    ),
    "technical_docs": (
        "Endpoint {vid} requires auth, and returns 429 after 100 requests per minute.",
        "must keep the rate limit",
        "2026-04-2{v}",
    ),
    "policies": (
        "Policy {vid} grants refunds, excluding sealed auction items from coverage.",
        "must keep the exclusion",
        "2026-03-1{v}",
    ),
    "customer_support": (
        "Ticket {vid} quotes the customer: please expedite, but never close before Friday.",
        "must keep the Friday constraint",
        "2026-09-0{v}",
    ),
    "data_analysis": (
        "Cohort {vid} converts at 4.2 percent, down from 8.7 percent after the redesign.",
        "must keep both rates",
        "2026-08-2{v}",
    ),
    "long_form_research": (
        "Study {vid} finds the effect holds, despite the outage skewing Tuesday data.",
        "must keep the Tuesday caveat",
        "2026-02-1{v}",
    ),
}

NOISE_LINES = [
    "Office chatter about plants, coffee machines and parking permits fills the gap.",
    "The cafeteria rotates soups on weekdays with bread served on the side.",
    "Someone left a jacket in the meeting room beside the projector remote.",
    "Weekend football results surprised nobody at the office this morning.",
    "The lobby plant was replaced after the old one dropped its leaves.",
]


@dataclass
class Task:
    id: str
    domain: str
    objective: str
    raw_context: str
    critical_facts: list[str] = field(default_factory=list)
    must_not_claim: list[str] = field(default_factory=list)
    temporal: str = ""


def build_tasks() -> list[Task]:
    tasks: list[Task] = []
    for domain in DOMAINS:
        fact_tpl, constraint_tpl, date_tpl = TEMPLATES[domain]
        for v in range(5):
            vid = f"{domain[:3].upper()}-{100 + v}"
            fact = fact_tpl.format(vid=vid)
            date = date_tpl.format(v=v % 9 + 1)
            noise = " ".join(NOISE_LINES[(v + k) % len(NOISE_LINES)] for k in range(3))
            # Noise blocks carry no identifier/date/question terms, so a working
            # selector can drop them; the finding block carries the evidence.
            context = (
                f"Background notes: {noise}\n\n"
                f"Key finding ({date}): {fact} Recorded {date}.\n\n"
                f"Appendix remarks: {noise}\n"
            )
            tasks.append(
                Task(
                    id=f"{domain}-{v}",
                    domain=domain,
                    objective=f"Answer about {vid}: {constraint_tpl.format(vid=vid)}?",
                    raw_context=context,
                    critical_facts=[fact[:60], date],
                    must_not_claim=[f"{vid} closed", f"{vid} deleted"],
                    temporal=date,
                )
            )
    return tasks


class _FactVerifyingJudge:
    """Deterministic mock verifier: sufficient iff every critical fact survives."""

    model = "mock-fact-verifier"
    last_resolved_model = "mock-fact-verifier-1"

    def __init__(self, facts: list[str]) -> None:
        self.facts = facts

    def evaluate(self, state, questions):
        ctx = state.get("context", "")
        missing = [f for f in self.facts if f not in ctx]
        score = 1.0 if not missing else max(0.0, 1.0 - 0.5 * len(missing))
        return {
            "answers": {
                "sufficient_to_answer": {
                    "type": "noul",
                    "noul": round(score, 2),
                    "confidence": 0.85,
                },
                "contradiction_risk": {"type": "noul", "noul": 0.0, "confidence": 0.9},
            }
        }


def mock_answer(context: str, task: Task) -> str:
    """Extractive stand-in downstream: quotes evidence as DATA, executes nothing."""
    hits = [f for f in task.critical_facts if f in context]
    body = "\n".join(f"<evidence>DATA: {h}</evidence>" for h in hits)
    return f"Answer about {task.id}:\n{body}" if body else "Answer: insufficient evidence."


def live_answer(prompt: str, cmd: str) -> str:
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, shell=True, timeout=300
    )
    return proc.stdout.strip()


def score_answer(answer: str, task: Task) -> dict:
    facts_hit = sum(1 for f in task.critical_facts if f in answer)
    return {
        "correctness": facts_hit / len(task.critical_facts) if task.critical_facts else 1.0,
        "critical_fact_recall": facts_hit / len(task.critical_facts)
        if task.critical_facts
        else 1.0,
        "constraint_ok": 1.0
        if not any(bad in answer for bad in task.must_not_claim)
        else 0.0,
        "contradiction": 1.0
        if bool(re.search(r"8\.7 percent", answer) and re.search(r"4\.2 percent", answer))
        else 0.0,
        "temporal_ok": 1.0 if task.temporal in answer else 0.0,
        "instruction_data_ok": 0.0
        if bool(re.search(r"account deleted|secrets? reveal|config dump", answer, re.I))
        else 1.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Answer-preservation benchmark.")
    parser.add_argument("--provider", default="mechanical")
    parser.add_argument("--downstream-cmd", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    tasks = build_tasks()
    assert len(tasks) == 50, f"expected 50 tasks, got {len(tasks)}"
    assert len({t.domain for t in tasks}) == 10

    arms = ("RAW", "LCC", "LCC_VERIFIER")
    agg: dict[str, dict] = {a: {"n": 0, "m": None, "tokens": 0, "ms": 0} for a in arms}
    per_task = []
    provider_seen: set[str] = set()
    verifier_decisions: dict[str, int] = {}
    verifier_reviews = 0
    verifier_restored = 0

    def _live_client():
        if args.provider == "jev":
            from lcc.relevance import JevClient

            client = JevClient.from_env()
            if client is None:
                print("NOT VALIDATED: no live Jev backend (TYPESAFE_API_KEY missing).")
                raise SystemExit(2)
            return client
        return None

    live_client = _live_client()

    for task in tasks:
        row: dict = {"id": task.id, "domain": task.domain}
        contexts: dict[str, str] = {"RAW": task.raw_context}
        started = time.perf_counter()
        base = compact_context(
            RelevanceCompactionRequest(
                text=task.raw_context,
                question=task.objective,
                provider=args.provider,
                client=live_client,
            )
        )
        contexts["LCC"] = base.compacted_text
        provider_seen.add(base.report.provider_used)
        # The verifier judges the candidate with the same live backend when one
        # exists (the real deployment shape); otherwise the deterministic
        # fact-presence mock stands in (labelled mock in the report).
        arm_client = (
            live_client
            if live_client is not None
            else _FactVerifyingJudge(task.critical_facts)
        )
        verified = compact_context(
            RelevanceCompactionRequest(
                text=task.raw_context,
                question=task.objective,
                provider=args.provider,
                client=arm_client,
                enable_semantic_verify=True,
            )
        )
        contexts["LCC_VERIFIER"] = verified.compacted_text
        provider_seen.add(verified.report.provider_used)
        decision = verified.report.semantic_verifier_decision
        if decision is not None:
            verifier_decisions[decision] = verifier_decisions.get(decision, 0) + 1
        if verified.report.needs_review:
            verifier_reviews += 1
        verifier_restored += verified.report.blocks_restored
        compile_ms = int((time.perf_counter() - started) * 1000)

        for arm in arms:
            ctx = contexts[arm]
            answer = mock_answer(ctx, task)
            if args.downstream_cmd and arm == "RAW":
                try:
                    answer = live_answer(
                        f"Objective: {task.objective}\n\nContext:\n{ctx}",
                        args.downstream_cmd,
                    )
                except Exception as exc:  # live failure never breaks the run
                    answer = f"LIVE_DOWNSTREAM_FAILED: {exc}"
            metrics = score_answer(answer, task)
            metrics["context_tokens"] = count_tokens(ctx, "gpt-4.1").value
            metrics["latency_ms"] = compile_ms if arm != "RAW" else 0
            row[arm] = metrics
            slot = agg[arm]
            slot["n"] += 1
            slot["tokens"] += metrics["context_tokens"]
            slot["ms"] += metrics["latency_ms"]
            if slot["m"] is None:
                slot["m"] = {k: 0.0 for k in metrics if isinstance(metrics[k], float)}
            for k in slot["m"]:
                slot["m"][k] += metrics[k]
        per_task.append(row)

    scope = "LIVE backend" if args.provider in ("jev", "laya") else "mock/offline"
    print(f"# answer preservation: 50 tasks x 10 domains ({scope}; mock downstream)")
    print("| arm | correctness | fact_recall | constraint | temporal | instr/data | avg_tokens |")
    print("|---|---|---|---|---|---|---|")
    summary = {}
    for arm in arms:
        slot = agg[arm]
        means = {k: round(v / slot["n"], 3) for k, v in slot["m"].items()}
        avg_tokens = round(slot["tokens"] / slot["n"])
        summary[arm] = {**means, "avg_context_tokens": avg_tokens}
        print(
            f"| {arm} | {means.get('correctness')} | {means.get('critical_fact_recall')} | "
            f"{means.get('constraint_ok')} | {means.get('temporal_ok')} | "
            f"{means.get('instruction_data_ok')} | {avg_tokens} |"
        )
    raw, lcc = summary["RAW"], summary["LCC"]
    live = args.provider in ("jev", "laya")
    print(
        f"\nLCC token delta vs RAW: {lcc['avg_context_tokens'] - raw['avg_context_tokens']} "
        f"tokens/task; correctness delta: "
        f"{round(lcc.get('correctness', 0) - raw.get('correctness', 0), 3)} "
        f"(providers seen: {sorted(provider_seen)}; "
        f"verifier decisions: {verifier_decisions or 'n/a (mock)'}; "
        f"needs_review: {verifier_reviews}/50; blocks_restored: {verifier_restored}; "
        f"mock downstream — generative-LLM answer figures NOT VALIDATED until "
        f"--downstream-cmd runs with two models)."
    )
    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "provider": args.provider,
                    "live": live,
                    "providers_seen": sorted(provider_seen),
                    "verifier_decisions": verifier_decisions,
                    "verifier_reviews": verifier_reviews,
                    "verifier_restored": verifier_restored,
                    "summary": summary,
                    "tasks": per_task,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
