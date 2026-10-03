"""MSI-Bench runner: one-command reproduction.

Run:   ``PYTHONPATH=src:benchmarks/msi-bench python3 benchmarks/msi-bench/run.py``
Check: ``... run.py --check`` (recomputes the matrix and asserts the frozen
       digest in results.json; fails loudly on any drift).

Writes ``benchmarks/msi-bench/results.json`` (frozen, committed): seeds,
versions, per-task content hashes, per-run records with receipts,
aggregates, Pareto, bootstrap CIs, predicted-vs-actual.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bench  # noqa: E402
import tasks  # noqa: E402

RESULTS_PATH = HERE / "results.json"
FREEZE_DATE = "2026-10-03"


def task_hashes() -> dict[str, str]:
    out = {}
    for t in tasks.TASKS:
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


def build() -> dict:
    runs = bench.run_matrix(seed=bench.SEED)
    agg = bench.aggregate(runs)
    ci = bench.bootstrap_ci(runs)
    front = bench.pareto(agg)
    actual = {(r["task_id"], r["arm"]): ("PASS" if r["success"] else "FAIL") for r in runs}
    mismatches = [
        {"task_id": tid, "arm": arm, "predicted": pred, "actual": actual[(tid, arm)]}
        for tid, arms in tasks.PREDICTED.items()
        for arm, pred in arms.items()
        if pred != actual[(tid, arm)]
    ]
    by_cat: dict[str, dict[str, str]] = {}
    for t in tasks.TASKS:
        by_cat.setdefault(t.category, {})[t.task_id] = t.category
    cat_table = {}
    for cat in tasks.CATEGORIES:
        cat_table[cat] = {
            arm: [actual[(t.task_id, arm)] for t in tasks.TASKS if t.category == cat]
            for arm in tasks.ARMS
        }
    payload = {
        "bench": bench.BENCH_VERSION,
        "seed": bench.SEED,
        "freeze_date": FREEZE_DATE,
        "evaluator": bench.EVALUATOR,
        "planner": bench.PLANNER,
        "tokenizer": bench.TOKENIZER,
        "profile": bench.PROFILE,
        "bootstrap_resamples": bench.BOOTSTRAP_RESAMPLES,
        "price_note": "MODELED illustrative USD/1k tokens; ordering-only claim",
        "prices_in_per_1k": bench.PRICE_IN_PER_1K,
        "prices_out_per_1k": bench.PRICE_OUT_PER_1K,
        "evidence_class": "BENCHMARK",
        "data_class": "CURATED",
        "task_hashes": task_hashes(),
        "runs": runs,
        "aggregate": agg,
        "bootstrap_ci_95": ci,
        "pareto_arms": front,
        "by_category": cat_table,
        "predicted_mismatches": mismatches,
        "digest": bench.digest_of(runs),
    }
    return payload


def check_payload(actual: dict, frozen: dict) -> None:
    assert bench._stable(actual) == bench._stable(frozen), (
        "payload drift (excluding receipt clocks/wall time)"
    )


def main(check: bool = False) -> None:
    payload = build()
    if check:
        frozen = json.loads(RESULTS_PATH.read_text())
        check_payload(payload, frozen)
        print(f"reproducible: digest {payload['digest']} "
              f"({len(payload['runs'])} runs, {len(tasks.TASKS)} tasks x {len(tasks.ARMS)} arms)")
        if payload["predicted_mismatches"] != frozen["predicted_mismatches"]:
            print("NOTE: predicted-vs-actual changed since freeze (see REPORT.md)")
        return
    RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"digest {payload['digest']}")
    for arm, a in payload["aggregate"].items():
        ci = payload["bootstrap_ci_95"][arm]
        print(f"  {arm:20} {a['successes']:2}/{a['n']} "
              f"rate={a['success_rate']:.3f} CI95=[{ci['lo']:.3f},{ci['hi']:.3f}] "
              f"cost=${a['cost_usd_modeled_total']:.4f} retained={a['retained_tokens_total']}")
    print(f"pareto: {payload['pareto_arms']}")
    print(f"mismatches vs predicted: {len(payload['predicted_mismatches'])}")
    for m in payload["predicted_mismatches"]:
        print(f"  MISMATCH {m['task_id']} {m['arm']}: "
              f"predicted {m['predicted']}, got {m['actual']}")


if __name__ == "__main__":
    main(check="--check" in sys.argv[1:])
