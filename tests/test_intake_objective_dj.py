"""Arm DJ and the H1-H4 statistics of intake-objective-v1, with a stand-in for Jev. No network."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from lcc.intake.objective import analyse, choose

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "intake-objective-v1"
sys.path.insert(0, str(HERE))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dj = _load("run_dj")
stats = _load("stats")

TEXT = (
    "Please rename the photo folder from the event. The photos sit on the shared drive. "
    "Another thing, please fix the checkout that freezes when a customer pays by card. "
    "The checkout froze twice."
)


class FakeJev:
    def __init__(self, label="B", p=0.9, fail=False):
        self.label, self.p, self.fail, self.calls = label, p, fail, []

    def evaluate(self, state, questions):
        self.calls.append((state, questions))
        if self.fail:
            raise RuntimeError("down")
        return {"answers": {"main": {"choice": self.label, "probabilities": {self.label: self.p}}}}


def _pick(client):
    a = analyse(TEXT)
    pick = choose(a)
    return pick, dj.dj_pick(client, TEXT, a, pick)


def test_a_confident_jev_pick_replaces_d():
    pick, out = _pick(FakeJev("B", 0.9))
    assert pick.objective.startswith("Please rename")  # D: tie, earlier block
    assert TEXT[slice(*out["span"])].startswith("Another thing, please fix the checkout")
    assert out["called"] and out["jev"] == "B" and out["p"] == 0.9


def test_a_weak_or_failed_jev_answer_keeps_d():
    for client in (FakeJev("B", 0.59), FakeJev(fail=True), FakeJev("Z", 0.99)):
        pick, out = _pick(client)
        assert out["span"] == list(pick.objective_span) and out["called"]


def test_one_eligible_block_makes_no_call():
    client = FakeJev()
    a = analyse("Please fix the checkout. The checkout froze twice.")
    out = dj.dj_pick(client, a.text, a, choose(a))
    assert not out["called"] and client.calls == []


def test_the_options_follow_input_order_not_ds_ranking():
    client = FakeJev("A", 0.9)
    _pick(client)
    options = client.calls[0][1]["main"]["criteria"]
    assert list(options) == ["A", "B"] and options["A"].startswith("Please rename")


def test_cluster_interval_is_exact_on_constant_differences():
    out = stats.cluster_interval({"b1": [1.0, 1.0], "b2": [1.0]})
    assert out == {"diff": 1.0, "lo": 1.0, "hi": 1.0}
    wide = stats.cluster_interval({"b1": [1.0] * 3, "b2": [0.0] * 3})
    assert wide["diff"] == 0.5 and wide["lo"] == 0.0 and wide["hi"] == 1.0


def test_an_interrupted_run_resumes_without_asking_jev_again(tmp_path):
    class Stops(FakeJev):
        def evaluate(self, state, questions):
            if len(self.calls) == 2:
                raise KeyboardInterrupt
            return super().evaluate(state, questions)

    log = tmp_path / "results_dj_dev.partial.jsonl"
    first = Stops("A", 0.9)
    with pytest.raises(KeyboardInterrupt):
        dj.run("dev", first, log)
    log.write_text(log.read_text() + '{"id": "cut', encoding="utf-8")  # a write cut mid-line
    second = FakeJev("A", 0.9)
    result = dj.run("dev", second, log)
    assert len(first.calls) == 2 and len(second.calls) == result["summary"]["calls"] - 2
    assert result["summary"]["n"] == 300 and len(log.read_text().splitlines()) == 300


#: Amendment 3 pins DJ and the analysis before any arm runs on test.
FROZEN = {
    "run_dj.py": "cde9aa0584bc1c7976b59cee51c9c8a24cfc3b80ed5f2a9bfc9e9f9ac80b63ca",
    "stats.py": "8788754f505b63a693fbbcd44f56874af0723d1efa4b13728c298b0c7f18d875",
}


def test_dj_and_the_analysis_are_frozen():
    import hashlib

    for name, sha in FROZEN.items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == sha, name
