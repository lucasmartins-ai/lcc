"""Arm D of intake-objective-v1 (``lcc.intake.objective``) and its runner.

Synthetic inputs and the dev split only: D never runs on the test split here (PROTOCOL.md,
Amendment 2). The runner's test-split guard is checked with a stand-in for ``run``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from lcc.intake.objective import WEIGHTS, pick_objective
from lcc.intake.parser import parse_intake

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "intake-objective-v1"
_spec = importlib.util.spec_from_file_location("run_arms", HERE / "run_arms.py")
arms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(arms)

ERRAND = "Please rename the photo folder from the event. The photos sit on the shared drive. "
CHECKOUT = "fix the checkout that freezes when a customer pays by card. The checkout froze twice. "


def _rebuilt(text: str, pick) -> str:
    return "".join(text[slice(*b.span)] for b in pick.blocks)


def test_a_priority_marker_beats_an_earlier_errand():
    text = ERRAND + "Another thing, the most important part: " + CHECKOUT
    pick = pick_objective(text)
    assert pick.objective.startswith("Another thing, the most important part: fix the checkout")
    assert text[slice(*pick.objective_span)] == pick.objective
    assert _rebuilt(text, pick) == text
    assert sorted([pick.ranking[0], *pick.linked, *pick.stash]) == list(range(len(pick.blocks)))
    # Without the marker the blocks tie and the earlier one wins, as the first ask would.
    assert pick_objective(text, drop="marker").objective.startswith("Please rename")


def test_a_closing_recap_lifts_the_block_it_repeats():
    # A recap that follows the block it repeats and shares a word with it joins that block, and
    # the restate signal is then off; this input keeps another block between them.
    text = ERRAND + "Another thing, please " + CHECKOUT + "One more thing, the van is booked. "
    text += "To sum up, fix the checkout first."
    assert pick_objective(text).objective.startswith("Another thing, please fix the checkout")
    assert pick_objective(text, drop="restate").objective.startswith("Please rename")


def test_no_ask_falls_back_to_the_parser_objective():
    text = "The checkout froze twice yesterday. The photos sit on the shared drive."
    pick = pick_objective(text)
    assert pick.fallback and pick.ranking == [] and pick.objective_span == (0, 0)
    assert pick.objective == parse_intake(text).brief.objective
    assert _rebuilt(text, pick) == text


def test_ask_cues_count_per_sentence_without_punctuation():
    text = "The checkout freezes\nFix the checkout\nAnother thing, please rename the photos."
    assert pick_objective(text).objective == "Fix the checkout"


def test_an_input_with_no_sentence_still_rebuilds():
    for text in ("", " \t\n "):
        pick = pick_objective(text)
        assert pick.fallback and _rebuilt(text, pick) == text and pick.stash == [0]


def test_d_is_the_frozen_d():
    result = arms.run("dev", WEIGHTS)
    summary = result["summary"]
    assert arms._code_sha256() == arms.FROZEN_OBJECTIVE_SHA256
    assert summary["d_sha256"] == arms.FROZEN_D_SHA256
    assert summary["D_rebuilds_all"] and summary["D_ask_recall_min"] == 1.0
    assert summary["D_fallbacks"] == 0


def test_the_test_split_is_refused_unless_d_is_frozen(monkeypatch, tmp_path):
    calls = []

    def fake_run(split, weights):
        calls.append(split)
        return {"rows": [], "summary": {"d_sha256": "not the frozen D"}}

    monkeypatch.setattr(arms, "run", fake_run)
    monkeypatch.setattr(arms, "HERE", tmp_path)
    assert arms.main(["run", "--split", "test"]) == 2
    assert "test" not in calls and not (tmp_path / "results_test.json").exists()
