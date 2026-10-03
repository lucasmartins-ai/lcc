"""MSI Sprint 6 pilot: frozen deterministic baseline + runner (offline).

Run:  ``PYTHONPATH=src python3 benchmarks/ablation/pilot.py [--check]``

Writes ``benchmarks/ablation/pilot_results.json`` (frozen, committed):
seed, baseline hash, model/version, evaluator, per-experiment delta, per-unit
label + deciding invariant, and cost. ``--check`` recomputes and asserts the
digest matches the frozen file (reproducibility gate).

Baseline (8 units, task ``msi-pilot-6-001``): a bug-fix subject verified with
the sprint-5 ``standard`` profile (deterministic layers only, no semantic
client, no network). Designed to exercise every research label:

- blk_gold_fact .... unique required fact -> NECESSARY (task layer)
- blk_gold_cite .... unique required citation -> NECESSARY (citation layer)
- blk_pair_a/b ..... share one required fact -> CONDITIONALLY_NECESSARY each
- blk_red_a/b ...... identical duplicate noise -> REDUNDANT each
- blk_noise ........ unique noise -> UNNECESSARY
- blk_safety ....... protected -> PROTECTED (never ablated)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TASK_ID = "msi-pilot-6-001"
PROFILE = "standard"
SEED = 0

F1 = "null deref at auth.py line 42"
F2 = "api key lives in the vault"

RESULTS_PATH = Path(__file__).resolve().parent / "pilot_results.json"


def _units() -> list:
    from lcc.router.ablate import AblationUnit

    return [
        AblationUnit(
            id="blk_gold_fact",
            content="The crash is a null deref at auth.py line 42. Patch the guard.",
        ),
        AblationUnit(
            id="blk_gold_cite",
            content="See the auth audit note for the login flow before patching.",
        ),
        AblationUnit(
            id="blk_pair_a",
            content="The api key lives in the vault path prod/api-key.",
        ),
        AblationUnit(
            id="blk_pair_b",
            content="Deploy reads the api key lives in the vault entry at deploy time.",
        ),
        AblationUnit(
            id="blk_red_a",
            content="The team uses pytest for unit tests.",
        ),
        AblationUnit(
            id="blk_red_b",
            content="The team uses pytest for unit tests.",
        ),
        AblationUnit(
            id="blk_noise",
            content="Lunch is at noon on the rooftop terrace.",
        ),
        AblationUnit(
            id="blk_safety",
            content="Authz checks must never be dropped for admin routes.",
            protected=True,
        ),
    ]


def make_subject(selected_ids: list[str]):
    from lcc.router.verify import UnitResult, VerificationSubject

    by_id = {u.id: u.content for u in _units()}
    summary = "\n".join(by_id[i] for i in selected_ids)
    return VerificationSubject(
        output={"summary": summary, "labels": ["bug"]},
        required_fields=["summary"],
        required_facts=[F1, F2],
        citation_ids=["c1"] if "blk_gold_cite" in selected_ids else [],
        valid_citation_ids=frozenset({"c1"}),
        require_citations=True,
        tests=[UnitResult("unit", True)],
        latency_ms=10,
        max_latency_ms=100,
        cost_usd=0.001,
        max_cost_usd=0.01,
        tools_used=["retrieval.search"],
        allowed_tools=["retrieval.search"],
        required_tools=["retrieval.search"],
        objective="fix the crash",
        candidate_context="the crash blocks login",
    )


def build_baseline():
    from lcc.router.ablate import AblationBaseline

    return AblationBaseline(
        task_id=TASK_ID,
        units=tuple(_units()),
        profile=PROFILE,
        seed=SEED,
        make_subject=make_subject,
    )


def run() -> dict:
    from lcc.router.ablate import run_pilot

    return run_pilot(build_baseline(), repeats=2).to_dict()


def main(check: bool = False) -> None:
    payload = run()
    if check:
        frozen = json.loads(RESULTS_PATH.read_text())
        assert payload["digest"] == frozen["digest"], (
            f"pilot not reproducible: {payload['digest']} != {frozen['digest']}"
        )
        print(f"reproducible: digest {payload['digest']}")
        return
    RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    dist: dict[str, int] = {}
    for lb in payload["labels"]:
        dist[lb["label"]] = dist.get(lb["label"], 0) + 1
    print(f"baseline_hash {payload['baseline_hash']}")
    print(f"digest {payload['digest']}")
    print(f"distribution {json.dumps(dist, sort_keys=True)}")
    for lb in payload["labels"]:
        extra = f" [{lb['deciding_invariant']}]" if lb["deciding_invariant"] else ""
        cond = f" ({lb['condition']})" if lb["condition"] else ""
        print(f"  {lb['unit_id']}: {lb['label']}{extra}{cond}")
    print(
        f"cost: {payload['cost']['experiments']} experiments, "
        f"{payload['cost']['total_wall_ms']} ms wall, "
        f"{payload['cost']['model_calls']} model calls"
    )


if __name__ == "__main__":
    main(check="--check" in sys.argv[1:])
