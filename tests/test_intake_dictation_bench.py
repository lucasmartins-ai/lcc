"""intake-dictation-v1 harness (benchmarks/research/intake-dictation-v1): the cases file is the
generator's output, and its gold is exact by construction. No model call."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "intake-dictation-v1"
_spec = importlib.util.spec_from_file_location(
    "intake_dictation_v1", HERE / "intake_dictation_v1.py"
)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

CASES = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"\w+", text)]


def _without_cuts(case: dict) -> str:
    text, out, cursor = case["text"], [], 0
    for start, end, _family in sorted(case["cuts"]):
        out.append(text[cursor:start])
        cursor = end
    return "".join(out) + text[cursor:]


def test_cases_file_is_the_generator_output():
    assert bench.generate()["cases"] == CASES
    assert len(CASES) == 280


def test_deleting_the_gold_cuts_gives_the_clean_request_back():
    clean = {c["base"]: c for c in CASES if c["family"] == "clean"}
    checked = 0
    for case in CASES:
        if {"distractor", "vague"} & set(case["families"]):
            continue  # those add keep sentences on purpose
        assert _tokens(_without_cuts(case)) == _tokens(clean[case["base"]]["text"]), case["id"]
        checked += 1
    assert checked > 200


def test_asks_are_never_inside_a_gold_cut():
    for case in CASES:
        for ask in case["asks"]:
            for s, e in ask:
                assert not any(cs < e and s < ce for cs, ce, _ in case["cuts"]), case["id"]


def test_open_asides_are_outside_the_layer1_lexicon():
    from lcc.intake.speech import _ASIDE_SENTENCE

    for lang in ("pt", "en"):
        assert all(_ASIDE_SENTENCE.fullmatch(p) for p in bench.ASIDE_LEXICON[lang])
        assert not any(_ASIDE_SENTENCE.fullmatch(p) for p in bench.ASIDE_OPEN[lang])
        assert not any(_ASIDE_SENTENCE.fullmatch(p) for p in bench.DISTRACTORS[lang])


def test_rebuild_inverts_a_cut():
    text = "a b c d"
    assert bench.rebuild("a d", [(1, 5, " b c")]) == text
