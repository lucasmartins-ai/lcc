"""Part R of intake-objective-v1 on synthetic text only: the pool filter, the labelling rules,
Wilson and the scoring. No real dictation is read here."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

from lcc.intake.parser import parse_intake

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "intake-objective-v1"
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("part_r", HERE / "part_r.py")
part_r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(part_r)

LONG = " ".join(["The shop opens at nine and the van leaves at ten."] * 31)  # 341 words
SR = "<system-reminder>context the app adds</system-reminder>"
TEXT = (
    "Please rename the photo folder from the event. The photos sit on the shared drive. "
    "Another thing, please fix the checkout that freezes when a customer pays by card. "
    "The checkout froze twice."
)


def _entry(content, **extra):
    row = {"type": "user", "turnOrigin": "human", "message": {"role": "user", "content": content}}
    return {**row, **extra}


def test_the_filter_keeps_long_typed_messages_only():
    assert part_r.candidate(_entry(LONG)) == (LONG, "ok")
    assert part_r.candidate(_entry(LONG, turnOrigin=None, origin={"kind": "human"}))[1] == "ok"
    assert part_r.candidate(_entry("Fix the checkout."))[1] == "short"
    for row in (
        _entry(LONG, turnOrigin=None),  # no origin tag: left out
        _entry(LONG, isSidechain=True),
        _entry(LONG, isMeta=True),
        _entry(LONG, isCompactSummary=True),
        _entry([{"type": "tool_result", "content": LONG}]),
    ):
        assert part_r.candidate(row) == (None, "not a typed message")


def test_reminders_are_stripped_only_at_the_ends():
    assert part_r.candidate(_entry(f"{SR}\n{LONG}\n{SR}")) == (LONG, "ok")
    assert part_r.candidate(
        _entry([{"type": "text", "text": SR}, {"type": "text", "text": LONG}])
    ) == (LONG, "ok")
    # A reminder in the middle drops the message; the trailing strip never eats the human text.
    assert part_r.candidate(_entry(f"{LONG} {SR} {LONG} {SR}")) == (None, "markup")
    for pasted in (
        "<pasted_content id=1>x</pasted_content>",
        "```\ncode\n```",
        "<bash-stdout>x</bash-stdout>",
        "<user-prompt-submit-hook>x</user-prompt-submit-hook>",
        "<ci-monitor-event>x</ci-monitor-event>",
        "[Request interrupted by user]",
    ):
        assert part_r.candidate(_entry(f"{LONG} {pasted}")) == (None, "markup")


def test_collect_writes_a_private_seeded_pool(tmp_path):
    project = tmp_path / "projects" / "p"
    project.mkdir(parents=True)
    texts = [f"{LONG} Case {i}. Please fix the checkout." for i in range(5)] + [
        "x <!--<script> </script><b>y</b> 🙂 " + LONG
    ]
    rows = [_entry(t, sessionId="s", timestamp="2026-11-01T00:00:00Z") for t in texts] + [
        _entry(texts[0])
    ]
    (project / "a.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8"
    )
    out = tmp_path / "private" / "intake-objective-v1"
    counts = part_r.collect(tmp_path / "projects", out)
    assert counts == {"ok": 7, "duplicate": 1, "candidates": 6}
    assert (
        stat.S_IMODE(out.stat().st_mode) == 0o700
        and stat.S_IMODE(out.parent.stat().st_mode) == 0o700
    )
    for name in ("candidates.json", "label.html"):
        assert stat.S_IMODE((out / name).stat().st_mode) == 0o600
    pool = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
    first = [c["id"] for c in pool["items"]]
    with pytest.raises(SystemExit, match="drawn once"):
        part_r.collect(tmp_path / "projects", out)
    again = tmp_path / "again"
    part_r.collect(tmp_path / "projects", again)
    assert [c["id"] for c in json.loads((again / "candidates.json").read_text())["items"]] == first
    page = (out / "label.html").read_text(encoding="utf-8")
    data = page.split('<script id="data" type="application/json">')[1].split("</script>")[0]
    assert "<" not in data  # message text cannot end or reopen the script block
    assert json.loads(data)["items"][0]["sha256"] == pool["items"][0]["sha256"]
    assert not list(out.glob("*.tmp"))


def _pool(texts):
    items = []
    for t in texts:
        sha = hashlib.sha256(t.encode()).hexdigest()
        spans = [list(item.spans[0]) for item in parse_intake(t).extract]
        items.append({"id": sha[:12], "sha256": sha, "text": t, "sentences": spans})
    return {"parser_sha256": part_r.PARSER_SHA256, "items": items}


def _labels(pool, decisions):
    return {
        "items": [
            {"id": c["id"], "sha256": c["sha256"], **d}
            for c, d in zip(pool["items"], decisions, strict=False)
        ]
    }


def _use(pool, i, k=2):
    return {"decision": "use", "gold": [pool["items"][i]["sentences"][k]]}


def test_labels_follow_the_rules_or_the_run_refuses():
    pool = _pool([f"{TEXT} Case {i}." for i in range(23)])
    skip = {"decision": "skip", "reason": "sensível"}
    ok = [skip, *(_use(pool, i) for i in range(1, 21))]
    kept, skips = part_r.labelled(pool, _labels(pool, ok))
    assert len(kept) == 20 and skips == {"sensível": 1}
    bad = {
        "top down": _labels(pool, ok)["items"][1:],
        "listed reason": _labels(pool, [{"decision": "skip", "reason": "chato"}, *ok[1:]])["items"],
        "gold sentences": _labels(pool, [*ok[:-1], {"decision": "use", "gold": [[0, 3]]}])["items"],
        "20 to 30": _labels(pool, ok[:-1])["items"],
        "another text": [
            {**d, "sha256": "0" * 64} if n == 3 else d
            for n, d in enumerate(_labels(pool, ok)["items"])
        ],
    }
    for why, items in bad.items():
        with pytest.raises(SystemExit, match=why):
            part_r.labelled(pool, {"items": items})
    with pytest.raises(SystemExit):
        part_r.labelled({**pool, "parser_sha256": "x"}, _labels(pool, ok))


def test_wilson_matches_the_formula():
    assert part_r.wilson(10, 20) == {"k": 10, "n": 20, "rate": 0.5, "lo": 0.2993, "hi": 0.7007}
    assert part_r.wilson(0, 20)["lo"] == 0.0 and part_r.wilson(0, 20)["hi"] == 0.1611
    assert part_r.wilson(20, 20)["hi"] == 1.0 and part_r.wilson(20, 20)["lo"] == 0.8389


def test_scoring_reads_the_frozen_arms():
    pool = _pool([TEXT])
    case = {"id": "x", "text": TEXT, "main": [pool["items"][0]["sentences"][2]]}  # the checkout ask
    rows, summary = part_r.score([case] * 20)
    assert (
        rows[0]["A0"] is False and rows[0]["A1"] is True and rows[0]["D"] is False
    )  # D: tie, earlier
    assert rows[0]["D_hit3"] is True and rows[0]["gold_is_ask"] == 1.0 and summary["D_rebuilds_all"]
    assert summary["D"]["k"] == 0 and summary["A1"]["k"] == 20 and TEXT not in json.dumps(summary)


#: Amendment 4 pins the Part R code before the owner labels any dictation.
PART_R_SHA256 = "cc0da0564f8904f3b8094c737bdaa9fabf02af39bcbc0e659a5a5d17c7699659"


def test_part_r_is_frozen():
    assert hashlib.sha256((HERE / "part_r.py").read_bytes()).hexdigest() == PART_R_SHA256
