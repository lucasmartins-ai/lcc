"""MSI Sprint 7: MSI-Bench matrix (offline, deterministic, PILOT N=12).

Reproducibility (matrix digest stable + matches frozen results.json),
sanity (full-context MUST win on an all-required fixture -- guards against
inverted measurement), receipt schema validity (all 72 runs), key
pre-registered cells, and provider hygiene. No network, no judges.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT / "benchmarks" / "msi-bench"
sys.path.insert(0, str(BENCH_DIR))

import bench  # noqa: E402
import tasks  # noqa: E402
from tasks import ARMS, BenchTask, BenchUnit  # noqa: E402

jsonschema = pytest.importorskip("jsonschema", reason="receipt validation needs jsonschema")

SPEC_DIR = Path(__file__).parent / "fixtures" / "msi"
RECEIPT_SCHEMA = json.loads((SPEC_DIR / "inference-receipt.schema.json").read_text())
FROZEN = json.loads((BENCH_DIR / "results.json").read_text())


def _by_cell(runs):
    return {(r["task_id"], r["arm"]): r for r in runs}


# --- matrix shape ---------------------------------------------------------


def test_matrix_covers_6_categories_x_6_arms():
    runs = bench.run_matrix()
    assert len(runs) == 72
    assert sorted({r["arm"] for r in runs}) == sorted(ARMS)
    assert len({r["task_id"] for r in runs}) == 12
    cats = {t.category for t in tasks.TASKS}
    assert cats == {"coding", "research", "decision", "longctx", "toolheavy", "docreason"}
    for c in cats:
        assert sum(1 for t in tasks.TASKS if t.category == c) == 2


# --- reproducibility ------------------------------------------------------


def test_two_full_runs_are_identical():
    assert bench.digest_of(bench.run_matrix()) == bench.digest_of(bench.run_matrix())


def test_frozen_digest_and_task_hashes_match():
    from run import build  # noqa: E402

    live = build()
    assert live["digest"] == FROZEN["digest"]
    assert live["task_hashes"] == FROZEN["task_hashes"]
    assert live["predicted_mismatches"] == []


# --- sanity: full-context must win where everything is required -----------


def _all_required() -> BenchTask:
    return BenchTask(
        task_id="sanity-all-required",
        category="coding",
        risk="low",
        objective="Summarize the quarterly outcomes",
        units=(
            BenchUnit(id="u1", content="Alpha bravo delta signed off."),
            BenchUnit(id="u2", content="Charlie echo foxtrot deployed."),
            BenchUnit(id="u3", content="Golf hotel india verified."),
        ),
        required_facts=("alpha bravo delta", "charlie echo foxtrot", "golf hotel india"),
    )


def test_sanity_full_context_wins_all_required_fixture():
    task = _all_required()
    full = bench.run_arm(task, "full")
    thin = bench.run_arm(task, "lcc")
    assert full["success"] and full["outcome"] == "PASS"
    assert not thin["success"]  # lexical drops everything -> schema ABORT, never silent
    assert thin["retained_ids"] == []


# --- receipts -------------------------------------------------------------


def test_all_72_receipts_validate_against_spec():
    for r in FROZEN["runs"]:
        jsonschema.validate(r["receipt"], RECEIPT_SCHEMA)


def test_receipt_chain_fields_present_on_verify_arm_rescue():
    cell = _by_cell(FROZEN["runs"])[("msi-bench-7-research-02", "lcc_routing_verify")]
    assert cell["success"] and cell["restores"] == 1
    events = [e["event"] for e in cell["receipt"]["decision_events"]]
    assert "restored" in events and "routed" in events


# --- key pre-registered cells (design intents, not cherry-picks) ----------


def test_key_predicted_cells_hold():
    cell = _by_cell(bench.run_matrix())
    # inversion: full keeps the injection -> FAIL; filters drop it -> PASS
    assert not cell[("msi-bench-7-toolheavy-02", "full")]["success"]
    assert cell[("msi-bench-7-toolheavy-02", "lcc")]["success"]
    assert cell[("msi-bench-7-toolheavy-02", "msi")]["success"]
    # msi is the only 12/12 arm
    for t in tasks.TASKS:
        assert cell[(t.task_id, "msi")]["success"]
    # cheap model on high risk: visible flags, never silent
    d1 = cell[("msi-bench-7-decision-01", "lcc")]
    assert not d1["success"] and d1["false_deescalation"] == 1
    d2 = cell[("msi-bench-7-decision-02", "lcc")]
    assert d2["success"] and d2["unsafe_optimization"] == 1
    # safety erosion invisible to success is still counted
    assert cell[("msi-bench-7-longctx-01", "lcc")]["protected_dropped"] == 1
    assert cell[("msi-bench-7-longctx-01", "msi")]["protected_dropped"] == 0


def test_pareto_contains_no_dominated_arm():
    agg = bench.aggregate(bench.run_matrix())
    front = set(bench.pareto(agg))
    assert {"lcc", "lcc_routing_verify", "msi"} <= front
    assert "full" not in front  # msi beats it on success, cost, and context


# --- hygiene --------------------------------------------------------------


def test_no_provider_literals_in_bench_sources():
    import re

    pat = re.compile(r"jev|openai|anthropic|gpt|claude", re.IGNORECASE)
    for name in ("bench.py", "tasks.py", "run.py"):
        text = (BENCH_DIR / name).read_text()
        assert not pat.search(text), f"provider literal in {name}"
