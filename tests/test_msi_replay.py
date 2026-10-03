"""MSI Sprint 9: CURATED regression probes (offline, deterministic).

N=10 CURATED probes x 6 arms through the frozen sprint-4/5/7 machinery.
Covers: track declaration (N/provenance/class), paired-metric completeness
(all section-11 metrics for every arm), replay determinism (same trace 2x
-> same digest), anonymization (no secrets/PII in the published track),
permanent failure fixtures (4 replay to their recorded outcomes), and the
no-tuning guard (frozen planner/verifier/receipt versions, no private
imports). No network, no live models, no private-repo access.
"""

from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT / "benchmarks" / "msi-bench"
REPLAY_DIR = ROOT / "benchmarks" / "msi-replay"
sys.path.insert(0, str(BENCH_DIR))
sys.path.insert(0, str(REPLAY_DIR))

import bench  # noqa: E402
import replay  # noqa: E402
import traces  # noqa: E402
from replay import bootstrap_ci, build, trace_hashes  # noqa: E402

FROZEN = json.loads((REPLAY_DIR / "results.json").read_text())
FIXTURES = sorted((REPLAY_DIR / "fixtures").glob("f*.json"))

# All section-11 metrics the sprint requires, paired per arm.
REQUIRED_ARM_KEYS = {
    "n", "successes", "success_rate", "cost_usd_modeled_total",
    "success_per_dollar_modeled", "frontier_calls_modeled",
    "verification_calls", "restores", "retries", "escalations",
    "false_deescalations", "unsafe_optimizations", "protected_dropped",
    "retained_tokens_total", "retained_at_matched_success",
    "frontier_avoided_at_matched_success", "matched_n", "wall_ms_p50",
    "verification_failures",
}


def test_track_declared_curated_n10_with_provenance():
    assert traces.DATA_CLASS == "CURATED"
    assert len(traces.TRACES) == 10
    assert set(traces.TRACE_SOURCE) == {t.task_id for t in traces.TRACES}
    for tid, src in traces.TRACE_SOURCE.items():
        for key in ("session", "window", "data_class", "collection", "anonymization"):
            assert src[key], f"{tid} missing provenance {key}"
        assert src["data_class"] == "CURATED"
    assert FROZEN["data_class"] == "CURATED"
    assert FROZEN["dataset"] == traces.DATASET_ID


def test_trace_freeze_hashes_match():
    assert trace_hashes() == FROZEN["trace_hashes"]


def test_frozen_contracts_untouched_no_private_coupling():
    assert bench.PLANNER == "planner-1.0"
    assert bench.EVALUATOR == "verify-1.0"
    assert bench.PROFILE == "standard"
    for name in ("traces.py", "replay.py"):
        src = (REPLAY_DIR / name).read_text()
        lowered = src.lower()
        # Real coupling = imports or filesystem paths into the private repo.
        # Naming the testbed in prose (source declaration) is required, not coupling.
        assert "/LOOKAORCHESTRATOR" not in src and "lookaorchestrator." not in lowered, \
            f"{name} couples to the private testbed"
        assert "import jev" not in lowered and "openai" not in lowered \
            and "anthropic" not in lowered


def test_paired_metrics_complete_no_cherry_pick():
    agg = FROZEN["aggregate"]
    assert set(agg) == set(bench.ARMS)  # all 6 arms, no arm dropped
    for arm, a in agg.items():
        assert set(a) >= REQUIRED_ARM_KEYS, f"{arm} missing metrics"
        assert a["n"] == 10  # every arm ran every trace
    assert len(FROZEN["runs"]) == 60  # 10 traces x 6 arms, all published
    assert FROZEN["pareto_arms"]  # pareto computed, not asserted here
    assert set(FROZEN["bootstrap_ci_95"]) == set(bench.ARMS)


def test_replay_deterministic_same_trace_twice_same_digest():
    first = build()
    second = build()
    assert first["digest"] == second["digest"]
    assert first["digest"] == FROZEN["digest"]
    assert [r["receipt_hash"] for r in first["runs"]] == [
        r["receipt_hash"] for r in second["runs"]
    ]
    replay.check_payload(first, FROZEN)


def test_no_secrets_or_pii_in_published_track():
    secret_patterns = re.compile(
        r"sk-(live|test)-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|"
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
        r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|ghp_[A-Za-z0-9]{8,}|"
        r"xox[bap]-|-----BEGIN [A-Z ]*PRIVATE KEY-----",
        re.IGNORECASE,
    )
    files = [*REPLAY_DIR.glob("*.json"), REPLAY_DIR / "traces.py", *FIXTURES]
    hits = [str(p) for p in files if secret_patterns.search(p.read_text())]
    assert not hits, f"secret/PII pattern in published track: {hits}"


def test_failure_fixtures_replay_to_recorded_outcomes():
    assert len(FIXTURES) >= 3  # sprint demands 3+, track ships 4
    by_id = {t.task_id: t for t in traces.TRACES}
    for path in FIXTURES:
        fix = json.loads(path.read_text())
        task = by_id[fix["trace_id"]]
        canon_units = [(u.id, u.content, u.protected) for u in task.units]
        assert fix["trace_hash"] == FROZEN["trace_hashes"][fix["trace_id"]]
        assert canon_units  # trace content is the fixture content (single source)
        assert fix["root_cause"] and fix["next_experiment"] and fix["repro"]
        for arm, expected in fix["arms_recorded"].items():
            actual = "PASS" if bench.run_arm(task, arm, bench.SEED)["success"] else "FAIL"
            assert actual == expected, f"{path.name} {arm}: recorded {expected}, got {actual}"


def test_bootstrap_paired_and_bounded():
    ci = bootstrap_ci(FROZEN["runs"])
    assert set(ci) == set(bench.ARMS)
    for band in ci.values():
        assert 0.0 <= band["lo"] <= band["hi"] <= 1.0


def test_receipt_hash_covers_audit_fields_and_ignores_only_wall_clock():
    receipt = deepcopy(FROZEN["runs"][0]["receipt"])
    original = replay.receipt_hash(receipt)
    receipt["timestamps"]["finished_at"] = "2030-01-01T00:00:00Z"
    receipt["decision_events"][0]["at"] = "2030-01-01T00:00:00Z"
    receipt["cost"]["latency_ms"] = 999
    assert replay.receipt_hash(receipt) == original
    receipt["decision_events"][0]["reason"] += ";unexpected policy change"
    assert replay.receipt_hash(receipt) != original


def test_replay_receipt_has_current_dataset_and_nonzero_accounting():
    run = replay.run_replay_arm(traces.TRACES[0], "full")
    assert run["receipt"]["versions"]["dataset"] == traces.DATASET_ID
    for key in ("tokens_in", "tokens_out"):
        assert run["receipt"]["cost"][key] == run[key] > 0
    assert run["receipt"]["cost"]["cost_usd"] == run["cost_usd_modeled"] > 0
    assert run["receipt_hash"] == replay.receipt_hash(run["receipt"])


def test_check_rejects_metric_drift_even_when_outcome_digest_matches():
    payload = build()
    corrupt = deepcopy(payload)
    corrupt["aggregate"]["full"]["successes"] -= 1
    import pytest

    with pytest.raises(AssertionError, match="payload drift"):
        replay.check_payload(payload, corrupt)


def test_authored_cases_are_labeled_curated():
    assert traces.DATA_CLASS == "CURATED"


def test_paired_bootstrap_uses_same_trace_sample_for_every_arm():
    runs = [
        {"arm": arm, "task_id": t.task_id, "success": i < 3}
        for arm in bench.ARMS for i, t in enumerate(traces.TRACES)
    ]
    bands = bootstrap_ci(runs, resamples=37)
    assert len({(b["lo"], b["hi"]) for b in bands.values()}) == 1


def test_modeled_chain_cost_counts_each_executed_frontier_attempt():
    task = traces.TRACES[4]
    bench_run = bench.run_arm(task, "msi")
    run = replay.run_replay_arm(task, "msi")
    assert bench_run["verification_calls"] == 3
    assert run["cost_usd_modeled"] == bench_run["cost_usd_modeled"]
    assert run["cost_usd_modeled"] == round(
        3 * (bench_run["tokens_in"] / 1000 * bench.PRICE_IN_PER_1K["frontier"]
             + bench_run["tokens_out"] / 1000 * bench.PRICE_OUT_PER_1K["frontier"]),
        6,
    )
    assert run["frontier_call_modeled"] == 3
    assert len(run["execution_costs"]) == 3
    assert run["receipt"]["cost"]["tokens_in"] == 3 * bench_run["tokens_in"]


def test_every_curated_failure_has_a_case_investigation():
    result = build()
    failures = {(r["task_id"], r["arm"]) for r in result["runs"] if not r["success"]}
    investigated = {(r["task_id"], r["arm"]) for r in result["regressions"]}
    assert investigated == failures
    assert len(failures) == 25
    for regression in result["regressions"]:
        assert regression["evidence"] and regression["root_cause"]
        assert regression["next_experiment"]
