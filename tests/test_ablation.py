"""MSI Sprint 6: causal ablation harness (offline, deterministic).

Self-test on a trivial fixture (gold is NECESSARY, noise is UNNECESSARY),
frozen-pilot assertions (labels + deciding invariants + digest), UNKNOWN on
non-passing baselines, and PROTECTED-never-ablated. No network, no judge.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from lcc.router.ablate import (
    AblationBaseline,
    AblationUnit,
    run_pilot,
)
from lcc.router.verify import UnitResult, VerificationSubject

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "benchmarks" / "ablation" / "pilot.py"
FROZEN = ROOT / "benchmarks" / "ablation" / "pilot_results.json"


def _subject_factory(fact: str, cite_unit: str | None = None, texts: dict | None = None):
    texts = texts or {"gold": f"the answer hinges on {fact}.", "noise": "weather is sunny."}

    def make(selected: list[str]) -> VerificationSubject:
        return VerificationSubject(
            output={"summary": "\n".join(texts[i] for i in selected)},
            required_fields=["summary"],
            required_facts=[fact],
            citation_ids=(["c1"] if cite_unit in selected else []),
            valid_citation_ids=frozenset({"c1"}),
            require_citations=cite_unit is not None,
            tests=[UnitResult("unit", True)],
        )

    return make


def _trivial() -> AblationBaseline:
    return AblationBaseline(
        task_id="trivial-001",
        units=(
            AblationUnit(id="gold", content="the answer hinges on alpha bravo."),
            AblationUnit(id="noise", content="weather is sunny."),
        ),
        make_subject=_subject_factory("alpha bravo"),
    )


def _load_pilot():
    spec = importlib.util.spec_from_file_location("msi_pilot6", PILOT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- self-test: trivial fixture ---


def test_trivial_gold_necessary_noise_unnecessary():
    report = run_pilot(_trivial(), repeats=2)
    by_id = {lb.unit_id: lb.label for lb in report.labels}
    assert by_id == {"gold": "NECESSARY", "noise": "UNNECESSARY"}


def test_trivial_necessary_carries_deciding_invariant():
    report = run_pilot(_trivial(), repeats=1)
    gold = next(lb for lb in report.labels if lb.unit_id == "gold")
    assert gold.deciding_invariant == "required_facts_present"


def test_trivial_two_runs_identical():
    assert run_pilot(_trivial(), repeats=2).digest() == run_pilot(
        _trivial(), repeats=2
    ).digest()


# --- fail-closed ---


def test_non_passing_baseline_labels_everything_unknown():
    bad = AblationBaseline(
        task_id="broken-001",
        units=(AblationUnit(id="u1", content="nothing relevant here."),),
        make_subject=_subject_factory(
            "absent fact xyz", texts={"u1": "nothing relevant here."}
        ),
    )
    report = run_pilot(bad, repeats=1)
    assert [lb.label for lb in report.labels] == ["UNKNOWN"]


def test_protected_never_ablated():
    base = AblationBaseline(
        task_id="prot-001",
        units=(
            AblationUnit(id="gold", content="the answer hinges on alpha bravo."),
            AblationUnit(id="guard", content="never drop.", protected=True),
        ),
        make_subject=_subject_factory(
            "alpha bravo",
            texts={
                "gold": "the answer hinges on alpha bravo.",
                "guard": "never drop.",
            },
        ),
    )
    report = run_pilot(base, repeats=1)
    assert next(lb for lb in report.labels if lb.unit_id == "guard").label == "PROTECTED"
    assert all("guard" not in e.removed_ids for e in report.experiments)


def test_crashing_make_subject_is_unknown_not_silent():
    def boom(selected: list[str]) -> VerificationSubject:
        raise RuntimeError("executor down")

    base = AblationBaseline(
        task_id="crash-001",
        units=(AblationUnit(id="u1", content="x"),),
        make_subject=boom,
    )
    report = run_pilot(base, repeats=1)
    assert report.labels[0].label == "UNKNOWN"
    assert any(e.outcome == "CRASH" for e in report.experiments)


# --- frozen pilot ---


def test_pilot_baseline_passes_and_hash_frozen():
    mod = _load_pilot()
    base = mod.build_baseline()
    assert len(base.units) == 8  # N=8 <= 30 (PILOT)
    assert base.run(base.unit_ids()).status == "PASS"
    frozen = json.loads(FROZEN.read_text())
    assert base.baseline_hash() == frozen["baseline_hash"]


def test_pilot_labels_match_frozen_distribution():
    mod = _load_pilot()
    report = run_pilot(mod.build_baseline(), repeats=2)
    frozen = json.loads(FROZEN.read_text())
    assert report.digest() == frozen["digest"]
    by_id = {lb.unit_id: lb.label for lb in report.labels}
    assert by_id == {
        "blk_gold_fact": "NECESSARY",
        "blk_gold_cite": "NECESSARY",
        "blk_pair_a": "CONDITIONALLY_NECESSARY",
        "blk_pair_b": "CONDITIONALLY_NECESSARY",
        "blk_red_a": "REDUNDANT",
        "blk_red_b": "REDUNDANT",
        "blk_noise": "UNNECESSARY",
        "blk_safety": "PROTECTED",
    }


def test_pilot_conditional_names_companion_and_invariant():
    mod = _load_pilot()
    report = run_pilot(mod.build_baseline(), repeats=1)
    conds = [lb for lb in report.labels if lb.label == "CONDITIONALLY_NECESSARY"]
    assert len(conds) == 2
    for lb in conds:
        assert lb.deciding_invariant == "required_facts_present"
        companion = "blk_pair_b" if lb.unit_id == "blk_pair_a" else "blk_pair_a"
        assert companion in lb.condition


def test_pilot_experiments_all_record_provenance():
    mod = _load_pilot()
    report = run_pilot(mod.build_baseline(), repeats=2)
    assert len(report.experiments) == 1 + 2 * (7 + 10)  # baseline + 2x(singles+pairs)
    for e in report.experiments:
        assert e.baseline_hash == report.baseline_hash
        assert e.seed == 0 and e.model and e.evaluator
