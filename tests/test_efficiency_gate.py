"""The efficiency gate passes unchanged code and fails a planted O(n^2) loop."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

import efficiency_gate as gate  # noqa: E402

GOOD = {"tokens_out": 1000, "prefix_share": 0.9, "cost": 1.0}


def _one(**changes: float) -> dict:
    return {"paths": {"p": {**GOOD, **changes}}}


def test_compare_names_path_and_delta() -> None:
    base = _one()
    assert gate.compare(base, _one()) == []
    assert gate.compare(base, _one(tokens_out=1005)) == []  # inside the 1% tolerance
    (tokens,) = gate.compare(base, _one(tokens_out=1200))
    assert tokens.startswith("p: tokens_out 1000 -> 1200")
    (prefix,) = gate.compare(base, _one(prefix_share=0.5))
    assert prefix.startswith("p: prefix_share")
    (cost,) = gate.compare(base, _one(cost=1.6))
    assert cost.startswith("p: cost 1.0 -> 1.6")
    assert gate.compare(_one(cost=0.04), _one(cost=0.09)) == []  # +125% but inside the floor
    assert gate.compare(base, {"paths": {"new": GOOD}}) != []


def test_planted_quadratic_loop_fails_the_gate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    baseline = gate.run_all(["rules-lossless"])
    assert gate.compare(baseline, gate.run_all(["rules-lossless"])) == []

    real = gate.compact_transcript

    def quadratic(request):  # type: ignore[no-untyped-def]
        items = list(range(3000))
        assert sum(1 for a in items for b in items if a == b) == 3000  # the planted O(n^2)
        return real(request)

    monkeypatch.setattr(gate, "compact_transcript", quadratic)
    problems = gate.compare(baseline, gate.run_all(["rules-lossless"]))
    assert any(p.startswith("rules-lossless: cost") for p in problems), problems
