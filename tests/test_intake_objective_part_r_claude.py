"""Claude as a labeller on Part R (Amendment 7), on synthetic text only: what the agent is shown,
and how its answer is scored. No real dictation is read here."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "intake-objective-v1"
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("part_r_claude", HERE / "part_r_claude.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

#: Amendment 7 pins this file; a change needs a new amendment.
PART_R_CLAUDE_SHA256 = "209e046a75b45eef1f8c0e1834703f93abb7743f690b1972b1aa7300813f2ac8"
TEXT = (
    "Please rename the photo folder from the event. The photos sit on the shared drive.\n"
    "Another thing, please fix the checkout that freezes when a customer pays by card. "
    "The checkout froze twice. " + "The shop opens at nine and the van leaves at ten. " * 30
)
SENSITIVE = "Sensitive note seventy seven."


def _pool():
    """21 messages; the owner keeps 20 with sentence 2 (the checkout ask) as gold and skips the
    sixth as sensitive."""
    items, decisions = [], []
    for i in range(21):
        text = f"{TEXT}Ticket {i}." + (f" {SENSITIVE}" if i == 5 else "")
        sha = hashlib.sha256(text.encode()).hexdigest()
        sentences = [list(s) for s in rc.part_r.analyse(text).spans]
        items.append({"id": sha[:12], "sha256": sha, "text": text, "sentences": sentences})
        decision = {"decision": "use", "gold": [sentences[2]]}
        if i == 5:
            decision = {"decision": "skip", "reason": "sensível"}
        decisions.append({"id": sha[:12], "sha256": sha, **decision})
    return {"parser_sha256": rc.part_r.PARSER_SHA256, "items": items}, {"items": decisions}


def _answer(items, main=2, **overrides):
    rows = [
        {"id": c["id"], "sentences": len(c["sentences"]), "decision": "use", "main": main}
        for c in items
    ]
    for k, row in overrides.items():
        rows[int(k[1:])].update(row)
    return {"items": rows}


def test_the_file_is_the_one_amendment_7_pins():
    assert hashlib.sha256((HERE / "part_r_claude.py").read_bytes()).hexdigest() == (
        PART_R_CLAUDE_SHA256
    )
    assert rc._reused_are_pinned()


def test_the_agent_sees_the_kept_messages_whole_and_nothing_else():
    pool, labels = _pool()
    items, kept = rc.kept_items(pool, labels)
    assert len(items) == 20 and [c["id"] for c in items] == [k["id"] for k in kept]
    shown = rc.render(items)
    assert SENSITIVE not in shown and shown.endswith("=== FIM ===\n")
    assert max(map(len, shown.splitlines())) <= rc.WIDTH
    blocks = re.split(r"^=== ITEM .*\n", shown.removesuffix("=== FIM ===\n"), flags=re.M)[1:]
    for c, block in zip(items, blocks, strict=True):
        lines = [re.sub(r"^(\[\d+\] |--- |    )", "", line) for line in block.splitlines()]
        assert " ".join(lines).replace(" ⏎ ", " ").split() == c["text"].split()  # all of it
        numbered = re.findall(r"^\[(\d+)\] ", block, flags=re.M)
        assert numbered == [str(j) for j in range(len(c["sentences"]))]
        assert f"· {len(c['sentences'])} frases ===" in shown
    assert "drive.\n--- ⏎\n[2] Another" in shown  # a line break the page showed stays visible


def test_the_pick_is_scored_against_the_owners_gold():
    pool, labels = _pool()
    items, _ = rc.kept_items(pool, labels)
    full = rc.score(pool, labels, _answer(items))
    assert full["agree"]["k"] == 20 and full["passed"] and full["skipped"] == 0
    off = rc.score(
        pool,
        labels,
        _answer(
            items,
            i0={"main": 0},
            i1={"main": 0, "also": [2]},
            i2={"decision": "skip", "reason": "sensível"},
        ),
    )
    assert off["agree"]["k"] == 17 and not off["passed"] and off["skipped"] == 1
    assert off["agree_any_marked"]["k"] == 18  # "also" is reported, not the criterion
    assert all(c["text"][:40] not in json.dumps(off) for c in items)


@pytest.mark.parametrize(
    "bad, why",
    [
        ({"i3": {"sentences": 1}}, "another sentence count"),
        ({"i3": {"main": 999}}, "no valid decision"),
        ({"i3": {"main": True}}, "no valid decision"),
        ({"i3": {"decision": "skip", "reason": "cansei"}}, "no valid decision"),
        ({"i3": {"id": "nope"}}, "in order"),
    ],
)
def test_a_malformed_answer_is_refused(bad, why):
    pool, labels = _pool()
    items, _ = rc.kept_items(pool, labels)
    with pytest.raises(SystemExit, match=why):
        rc.score(pool, labels, _answer(items, **bad))
    with pytest.raises(SystemExit, match="in order"):
        rc.score(pool, labels, {"items": _answer(items)["items"][:-1]})


def test_each_step_runs_once(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rc, "OUT", tmp_path / "stats_r_claude.json")
    monkeypatch.setattr(rc, "ANSWER", tmp_path / "claude_labels_r.json")
    (tmp_path / "stats_r_claude.json").write_text("{}", encoding="utf-8")
    (tmp_path / "claude_labels_r.json").write_text("{}", encoding="utf-8")
    assert rc.main(["score"]) == 2 and rc.main(["prepare"]) == 2
    out = capsys.readouterr().out
    assert "runs once" in out and "ran already" in out
