"""MSI Sprint 9: replay runner (offline, deterministic, no network).

Replays 10 CURATED regression probes through the frozen sprint-4/5/7
machinery (``bench.run_arm``: DeterministicPlanner + run_execution over
verify-1.0, profile ``standard``). Scoring, cost model, Pareto and digest
are the sprint-7 functions verbatim — the only new code is the trace set
(``traces.py``), paired bootstrap, full-chain modeled accounting and this CLI.

Run:   ``PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay \\
         python3 benchmarks/msi-replay/replay.py``
Check: ``... replay.py --check`` (asserts all stable payload fields,
        including full receipt hashes and aggregates).
One fixture: ``... replay.py --fixture msi-replay-9-t05`` (full vs msi on
        one trace; the permanent-failure-fixture repro).

Writes ``benchmarks/msi-replay/results.json`` (frozen, committed).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "msi-bench"))
sys.path.insert(0, str(HERE))

import bench  # noqa: E402
import traces  # noqa: E402

RESULTS_PATH = HERE / "results.json"


def _stable(value):
    """Exclude measured wall time and receipt clocks, preserving audit fields."""
    if isinstance(value, dict):
        clocks = {"timestamps", "at", "latency_ms", "wall_ms_measured", "wall_ms_p50"}
        return {k: _stable(v) for k, v in value.items() if k not in clocks}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def receipt_hash(receipt: dict) -> str:
    return hashlib.sha256(json.dumps(_stable(receipt), sort_keys=True).encode()).hexdigest()


def check_payload(actual: dict, frozen: dict) -> None:
    assert _stable(actual) == _stable(frozen), "payload drift (excluding receipt clocks/wall time)"


def run_replay_arm(task, arm: str) -> dict:
    """Reuse frozen bench policy; repair the replay-specific receipt envelope.

    Model each actually executed attempt using its routed model and context.
    Terminal escalation records a request, not an additional model execution.
    """
    run = bench.run_arm(task, arm, bench.SEED)
    receipt = run["receipt"]
    receipt["versions"]["dataset"] = traces.DATASET_ID
    by_id = {u.id: u.content for u in task.units}
    selected = list(receipt["selected_units"])
    model = receipt["model"]["class"]
    costs = []

    def account():
        summary = "\n".join(by_id[uid] for uid in selected)
        tin = bench.approximate_token_count(task.objective + "\n" + summary)
        tout = bench.approximate_token_count(summary)
        return {"model": model, "tokens_in": tin, "tokens_out": tout,
                "cost_usd_modeled": round(
                    tin / 1000 * bench.PRICE_IN_PER_1K[model]
                    + tout / 1000 * bench.PRICE_OUT_PER_1K[model], 6)}

    for event in receipt["decision_events"]:
        if event["event"] == "routed":
            match = re.search(r"model=([a-z_]+)", event["reason"])
            assert match is not None, "routed model missing from receipt"
            model = match.group(1)
        elif event["event"] == "restored":
            selected += [uid for uid in receipt["restorations"]["restored"] if uid not in selected]
        elif event["event"] == "failed":
            costs.append(account())
    if run["success"]:
        costs.append(account())
    assert len(costs) == run["verification_calls"], "attempt accounting drift"
    run["execution_costs"] = costs
    run["cost_usd_modeled"] = round(sum(c["cost_usd_modeled"] for c in costs), 6)
    run["frontier_call_modeled"] = sum(c["model"] == "frontier" for c in costs)
    receipt["cost"].update(tokens_in=sum(c["tokens_in"] for c in costs),
                           tokens_out=sum(c["tokens_out"] for c in costs),
                           cost_usd=run["cost_usd_modeled"])
    run["verification_failures"] = sum(e["event"] == "failed" for e in receipt["decision_events"])
    run["receipt_hash"] = receipt_hash(receipt)
    return run


def trace_hashes() -> dict[str, str]:
    out = {}
    for t in traces.TRACES:
        canon = {
            "task_id": t.task_id, "category": t.category, "risk": t.risk,
            "objective": t.objective,
            "units": [{"id": u.id, "content": u.content, "protected": u.protected}
                      for u in t.units],
            "required_facts": list(t.required_facts),
            "forbidden_claims": list(t.forbidden_claims),
            "citation_carrier": t.citation_carrier,
        }
        out[t.task_id] = hashlib.sha256(
            json.dumps(canon, sort_keys=True).encode()).hexdigest()[:16]
    return out


def bootstrap_ci(runs: list[dict], resamples: int = 2000, seed: int = 7) -> dict:
    """Percentile 95% CI per arm success rate, resampling replay traces with
    replacement (paired across arms: same trace ids per resample). Same
    method as bench.bootstrap_ci, over replay ids (that function hardcodes
    the bench task list, so it cannot be reused here)."""
    tids = [t.task_id for t in traces.TRACES]
    by_arm = {a: {r["task_id"]: r["success"] for r in runs if r["arm"] == a}
              for a in bench.ARMS}
    rng = random.Random(seed)
    samples = [[rng.choice(tids) for _ in tids] for _ in range(resamples)]
    out: dict[str, dict] = {}
    for arm in bench.ARMS:
        rates = []
        for sample in samples:
            rates.append(sum(by_arm[arm][t] for t in sample) / len(sample))
        rates.sort()
        out[arm] = {"lo": round(rates[int(0.025 * resamples)], 4),
                    "hi": round(rates[int(0.975 * resamples) - 1], 4),
                    "resamples": resamples}
    return out


def build() -> dict:
    runs = [run_replay_arm(t, a) for t in traces.TRACES for a in bench.ARMS]
    agg = bench.aggregate(runs)
    for arm, metrics in agg.items():
        metrics["verification_failures"] = sum(
            r["verification_failures"] for r in runs if r["arm"] == arm
        )
    ci = bootstrap_ci(runs)
    front = bench.pareto(agg)
    investigations = {
        "t02": ("Zero-overlap fact unit dropped; empty summary fails schema and ABORTs",
                "Evaluate bilingual retrieval on a disjoint trace split"),
        "t03": ("Zero-overlap citation carrier dropped; plain arms have no restoration budget",
                "Evaluate citation-aware protection without using evaluation fact labels"),
        "t04": ("Deadline carrier dropped; RETRY reuses the same incomplete context",
                "Evaluate restore-before-retry on disjoint deadline traces"),
        "t05": ("All-units/protection arms forward co-located injection; lexical arms drop "
                "the entire fact unit and ABORT on empty summary",
                "Evaluate instruction-span isolation while preserving fact spans"),
        "t06": ("All-units arms forward zero-overlap injection",
                "Evaluate adversarial paraphrases on a disjoint injection split"),
        "t08": ("Query vocabulary causes every selector to retain injection",
                "Evaluate source-aware instruction isolation "
                "without excluding legitimate evidence"),
        "t10": ("Zero-overlap opt-out carrier dropped; RETRY cannot recover it",
                "Evaluate dependency protection without evaluation-label access"),
    }
    regressions = []
    for run in runs:
        if run["success"]:
            continue
        cause, experiment = investigations[run["task_id"].split("-")[-1]]
        regressions.append({
            "task_id": run["task_id"], "arm": run["arm"], "root_cause": cause,
            "next_experiment": experiment,
            "evidence": [e["reason"] for e in run["receipt"]["decision_events"]
                         if e["event"] == "failed"],
        })
    payload = {
        "replay": traces.REPLAY_VERSION,
        "bench_functions": bench.BENCH_VERSION,
        "seed": bench.SEED,
        "freeze_date": traces.FREEZE_DATE,
        "dataset": traces.DATASET_ID,
        "evidence_class": "CURRENT",
        "data_class": traces.DATA_CLASS,
        "evaluator": bench.EVALUATOR,
        "planner": bench.PLANNER,
        "tokenizer": bench.TOKENIZER,
        "profile": bench.PROFILE,
        "price_note": "MODELED illustrative USD/1k tokens; all executed attempts; "
                      "terminal escalation is a request, not an execution; no CPU/energy cost",
        "trace_hashes": trace_hashes(),
        "trace_source": traces.TRACE_SOURCE,
        "runs": runs,
        "aggregate": agg,
        "bootstrap_ci_95": ci,
        "pareto_arms": front,
        "regressions": regressions,
        "digest": bench.digest_of(runs),
    }
    return payload


def main(check: bool = False, fixture: str | None = None) -> None:
    if fixture:
        tids = [t.task_id for t in traces.TRACES]
        assert fixture in tids, f"unknown trace {fixture!r} (have {tids})"
        task = next(t for t in traces.TRACES if t.task_id == fixture)
        for arm in ("full", "msi"):
            r = run_replay_arm(task, arm)
            print(f"{fixture} {arm}: outcome={r['outcome']} "
                  f"retained={r['retained_tokens']} cost=${r['cost_usd_modeled']:.4f} "
                  f"restores={r['restores']} retries={r['retries']} "
                  f"escalations={r['escalations']}")
        return
    payload = build()
    if check:
        frozen = json.loads(RESULTS_PATH.read_text())
        check_payload(payload, frozen)
        print(f"reproducible: digest {payload['digest']} "
              f"({len(payload['runs'])} runs, "
              f"{len(traces.TRACES)} traces x {len(bench.ARMS)} arms)")
        return
    RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"digest {payload['digest']}")
    for arm, a in payload["aggregate"].items():
        ci = payload["bootstrap_ci_95"][arm]
        print(f"  {arm:20} {a['successes']:2}/{a['n']} "
              f"rate={a['success_rate']:.3f} CI95=[{ci['lo']:.3f},{ci['hi']:.3f}] "
              f"cost=${a['cost_usd_modeled_total']:.4f} retained={a['retained_tokens_total']}")
    print(f"pareto: {payload['pareto_arms']}")


if __name__ == "__main__":
    _fixture = None
    if "--fixture" in sys.argv[1:]:
        _fixture = sys.argv[sys.argv.index("--fixture") + 1]
    main(check="--check" in sys.argv[1:], fixture=_fixture)
