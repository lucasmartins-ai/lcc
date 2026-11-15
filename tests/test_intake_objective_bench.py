"""intake-objective-v1 cases (benchmarks/research/intake-objective-v1): the cases file is the
generator's output, and its gold lines up with the intake's own sentence split. No model call.

Failures name case ids only: the test-split phrasings come from Codex and stay unread by
whoever builds the ranking (PROTOCOL.md, Leakage controls). PYTEST_DONT_REWRITE turns off
pytest's assertion introspection here, so a failure never prints a case's text; do not run this
file with --showlocals either.
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

from lcc.intake.parser import sentence_role
from lcc.intake.speech import sentence_spans

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "intake-objective-v1"
_spec = importlib.util.spec_from_file_location(
    "intake_objective_v1", HERE / "intake_objective_v1.py"
)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

FILE = (HERE / "cases.json").read_text(encoding="utf-8")
CASES = json.loads(FILE)["cases"]


def _text(case: dict, span: list[int]) -> str:
    return case["text"][span[0] : span[1]]


def test_cases_file_is_the_generator_output():
    assert bench.dump(bench.generate()) == FILE, "cases.json is stale: run generate"
    assert len(CASES) == 600, len(CASES)


def test_design_counts():
    assert Counter(c["split"] for c in CASES) == {"dev": 300, "test": 300}
    assert Counter(c["family"] for c in CASES) == dict.fromkeys(bench.FAMILIES, 120)
    assert Counter(c["k"] for c in CASES) == dict.fromkeys(bench.LENGTHS, 200)
    assert Counter(c["lang"] for c in CASES) == {"pt": 300, "en": 300}
    for case in CASES:
        assert case["split"] == ("dev" if int(case["base"][2:]) % 2 else "test"), case["id"]
        assert len(case["blocks"]) == case["k"] + 1 + (case["family"] == "restate"), case["id"]


def test_the_intake_splits_every_case_into_the_emitted_sentences():
    bad = []
    for case in CASES:
        emitted = [tuple(s) for s in case["sentences"]]
        gold = case["main"] + case["support"] + case["recur"] + [s for g in case["asks"] for s in g]
        if sentence_spans(case["text"]) != emitted or not all(tuple(s) in emitted for s in gold):
            bad.append(case["id"])
    assert not bad, bad


def test_no_distractor_block_shares_a_topic_with_its_base():
    bases = {b["id"]: b for b in bench.BASES}
    pool = {b["id"]: b for lang in bench.POOL.values() for b in lang}
    bad = []
    for case in CASES:
        base = bases[case["base"]]
        own = bench.topic_stems([base["ask"], *base["support"], *base["recur"], base["restate"]])
        drawn = [pool[b["src"]] for b in case["blocks"] if b["kind"] not in ("base", "restate")]
        if any(own & bench.topic_stems(b["s"]) for b in drawn):
            bad.append(case["id"])
    assert not bad, bad


def test_main_asks_read_as_asks_and_the_rest_of_the_base_does_not():
    bad, recap_not_ask = [], []
    for case in CASES:
        if sentence_role(_text(case, case["main"][0])) != "ask":
            bad.append(("main", case["id"]))
        if any(sentence_role(_text(case, s)) == "ask" for s in case["support"] + case["recur"]):
            bad.append(("support/recur", case["id"]))
        if case["family"] == "restate" and sentence_role(_text(case, case["main"][1])) != "ask":
            recap_not_ask.append((case["split"], case["lang"], case["phrasing"]["index"]))
    assert not bad, bad
    # Two of Codex's Portuguese recap phrasings make the parser read the recap as a rule; they
    # stay as written (PROTOCOL.md, data-freeze amendment).
    assert len(recap_not_ask) == 8, len(recap_not_ask)
    assert set(recap_not_ask) == {
        ("test", "pt", 1),
        ("test", "pt", 9),
    }


def test_family_layout():
    for case in CASES:
        main, family, k = case["main"], case["family"], case["k"]
        base_block = next(b for b in case["blocks"] if b["kind"] == "base")
        assert case["blocks"].index(base_block) == case["position"], case["id"]
        assert len(main) == (2 if family == "restate" else 1), case["id"]
        assert base_block["span"][0] == main[0][0], case["id"]
        if family == "first":
            assert case["position"] == 0, case["id"]
        if family == "recurrence":
            assert case["position"] <= k - 2 and 2 <= len(case["recur"]) <= 3, case["id"]
            assert all(s[0] > base_block["span"][1] for s in case["recur"]), case["id"]
        else:
            assert case["recur"] == [], case["id"]
        if family == "restate":
            assert main[1][1] == len(case["text"]), case["id"]
        if family in ("marker", "restate"):
            assert case["phrasing"]["set"] == case["split"], case["id"]
            assert case["phrasing"]["kind"] == family, case["id"]
        else:
            assert case["phrasing"] is None, case["id"]


def test_each_test_phrasing_list_comes_from_codex():
    codex = json.loads((HERE / "codex_phrasings.json").read_text(encoding="utf-8"))
    assert codex["model"] and "Do not read or run anything" in codex["brief"]
    assert {k: len(v) for k, v in codex["phrasings"].items()} == {
        "marker_pt": 10,
        "marker_en": 10,
        "restate_pt": 10,
        "restate_en": 10,
    }
