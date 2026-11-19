"""Part R2 verified by its owner (Amendment 8) on synthetic text only: the batches, the answer
check and its one retry, the blind slots, the page, the verdict rules and the scoring."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "intake-objective-v1"
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("part_r2_verify", HERE / "part_r2_verify.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

#: Amendment 8 pins this file; a change needs a new amendment.
PART_R2_VERIFY_SHA256 = "f2edc81b4f17d80611c4eff4762c2814dcb61f9fbcd00b36007ac41be4f6af4d"
TEXT = (
    "Please rename the photo folder from the event. The photos sit on the shared drive. "
    "Another thing, please fix the checkout that freezes when a customer pays by card. "
    "The checkout froze twice. "
)
NO_ASK = "The shop opens at nine. The van leaves at ten. "


def _item(i, text=TEXT, **extra):
    text = f"{text}Ticket {i}."
    sha = hashlib.sha256(text.encode()).hexdigest()
    row = {"id": sha[:12], "sha256": sha, "text": text, "words": len(text.split())}
    row.update(band="200-299", source=("tagged", "untagged")[i % 2], split="dev", timestamp="")
    return {**row, **extra}


def test_the_file_is_the_one_amendment_8_pins():
    assert hashlib.sha256((HERE / "part_r2_verify.py").read_bytes()).hexdigest() == (
        PART_R2_VERIFY_SHA256
    )
    assert v._reused_are_pinned()  # part_r.py, run_arms.py, part_r2.py and part_r_claude.py


def test_batches_keep_the_order_under_the_budget(monkeypatch):
    monkeypatch.setattr(v, "BUDGET", 500)
    items = [_item(i, TEXT * (6 if i == 2 else 1)) for i in range(6)]
    groups = v.batches(items)
    assert [c for b in groups for c in b] == items
    assert [len(b) for b in groups] == [2, 1, 2, 1]  # the long one goes alone
    assert all(sum(len(c["text"]) for c in b) <= 500 for b in groups if len(b) > 1)


def test_the_agent_reads_short_lines_and_no_label():
    text = v.render([_item(0, TEXT * 9 + "\n\nLast line.")])
    lines = text.splitlines()
    assert lines[0].startswith("=== MENSAGEM 1/1 · id ") and lines[-1] == "=== FIM ==="
    assert max(map(len, lines)) <= 160 and "⏎" in text and "Last line." in text


@pytest.mark.parametrize(
    ("answer", "ok"),
    [
        ({"items": [{"id": "a", "objective": " Fix it. "}, {"id": "b", "objective": "Go."}]}, True),
        ({"items": [{"id": "b", "objective": "Go."}, {"id": "a", "objective": "Fix."}]}, False),
        (
            {
                "items": [
                    {"id": "a", "objective": "Fix.\nAnd more."},
                    {"id": "b", "objective": "Go."},
                ]
            },
            False,
        ),
        ({"items": [{"id": "a", "objective": " "}, {"id": "b", "objective": "Go."}]}, False),
        ({"items": [{"id": "a", "objective": "w " * 31}, {"id": "b", "objective": "Go."}]}, False),
        ({"items": [{"id": "a"}, {"id": "b", "objective": "Go."}]}, False),
        ([], False),
    ],
)
def test_an_answer_needs_one_short_line_per_message_in_order(answer, ok):
    got = v.valid(json.dumps(answer).encode(), ["a", "b"])
    assert got == (["Fix it.", "Go."] if ok else None)
    assert v.valid(b"not json", ["a"]) is None and v.valid(None, ["a"]) is None


def test_slots_are_distinct_seeded_and_shared_by_equal_arms():
    item = _item(0)
    texts, where = v.slots(item, "Fix the checkout.")
    assert sorted(texts) == sorted(set(texts)) and len(texts) == 3
    assert where["D"] == where["A0"] and texts[where["C"]] == "Fix the checkout."
    assert v.slots(item, "Fix the checkout.") == (texts, where)  # the run re-derives the page
    texts, where = v.slots(_item(1, NO_ASK), None)  # no ask: D falls back, A0, A1 and C offer none
    assert len(texts) == 1 and where == {"C": None, "D": 0, "A0": None, "A1": None}


def _answer(batch, line="Fix the checkout."):
    return json.dumps({"items": [{"id": c["id"], "objective": line} for c in batch]})


def test_a_broken_answer_gets_one_retry_then_c_offers_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "BUDGET", 500)
    items = [_item(i) for i in range(4)]
    one, two = v.batches(items)
    (tmp_path / "answer_1.json").write_text(_answer(one), "utf-8")
    (tmp_path / "answer_2.json").write_text("{}", "utf-8")
    lines, retry = v.answers(items, tmp_path)
    assert retry == [2] and (tmp_path / "answer_2.rejected.json").exists()
    assert stat.S_IMODE((tmp_path / "answer_1.json").stat().st_mode) == 0o600
    assert v.answers(items, tmp_path)[1] == [2]  # the retry has not written yet: still due
    (tmp_path / "answer_2.json").write_text("", "utf-8")  # it wrote nothing: recorded as empty
    lines, retry = v.answers(items, tmp_path)
    assert retry == [] and lines == ["Fix the checkout."] * len(one) + [None] * len(two)
    (tmp_path / "answer_2.json").write_text(_answer(two, "Rename."), "utf-8")
    lines, retry = v.answers(items, tmp_path)
    assert retry == [] and lines[-1] == "Rename."


def test_the_page_shows_texts_and_slots_but_no_arm(monkeypatch):
    items = [_item(0, TEXT + "a < b </script> end. ")]
    html = v.page(items, ["Fix the checkout."])
    data = json.loads(html.split('type="application/json">')[1].split("</script>")[0])
    assert set(data["items"][0]) == {"id", "date", "words", "text", "slots"}
    assert "</script> end" not in html and "\\u003c/script> end" in html
    assert data["reasons"] == list(v.part_r.SKIP_REASONS) and len(data["levels"]) == 3
    assert 'a.download = "verdicts.json"' in html and '"lcc-r2-verify-"' in html


def _verdicts(items, lines, ratings="sim"):
    out = []
    for c, line in zip(items, lines, strict=True):
        n = len(v.slots(c, line)[0])
        out.append({"id": c["id"], "decision": "use", "ratings": [ratings] * n})
    return {"version": 1, "items": out}


def test_verdicts_must_decide_every_message_in_order():
    items = [_item(i) for i in range(3)]
    lines = ["Fix the checkout."] * 3
    good = _verdicts(items, lines)
    with pytest.raises(SystemExit, match="all 3 messages"):
        v.judged(items, lines, {"items": good["items"][:2]})
    bad = json.loads(json.dumps(good))
    bad["items"][1]["ratings"] = ["sim"]
    with pytest.raises(SystemExit, match="message 2"):
        v.judged(items, lines, bad)
    bad["items"][1] = {"id": items[1]["id"], "decision": "skip", "reason": "cansei"}
    with pytest.raises(SystemExit, match="message 2"):
        v.judged(items, lines, bad)
    bad["items"][1]["reason"] = "sensível"
    bad["items"][1]["ratings"] = ["sim"] * 3  # a skip carries no verdict
    with pytest.raises(SystemExit, match="message 2"):
        v.judged(items, lines, bad)
    del bad["items"][1]["ratings"]
    rows, skips = v.judged(items, lines, bad)
    assert len(rows) == 2 and skips["sensível"] == 1


def test_each_arm_takes_its_slots_rating_and_none_is_a_no():
    item = _item(0)
    texts, where = v.slots(item, None)  # C failed twice
    ratings = ["nao"] * len(texts)
    ratings[where["A1"]] = "sim"
    ratings[where["D"]] = "parte"
    rows, _ = v.judged(
        [item], [None], {"items": [{"id": item["id"], "decision": "use", "ratings": ratings}]}
    )
    row = rows[0]
    assert (row["C"], row["D"], row["A0"], row["A1"]) == ("nao", "parte", "parte", "sim")
    assert row["C_missing"] and row["D_is_A0"] and not row["D_fallback"]


def test_summary_pairs_d_with_a0_first_and_flags_a_small_run():
    def row(c, d, a0):
        return {
            "C": c,
            "D": d,
            "A0": a0,
            "A1": "nao",
            "band": "200-299",
            "source": "tagged",
            "split": "dev",
            "D_fallback": False,
            "D_is_A0": d == a0,
            "C_missing": False,
        }

    rows = [row("sim", "sim", "nao"), row("sim", "parte", "sim"), row("parte", "nao", "nao")]
    s = v.summarise(rows, {"sensível": 1}, 1)
    assert s["D_vs_A0"] == {"D_only": 1, "A0_only": 1, "p_exact_mcnemar": 1.0}
    assert s["C_vs_D"] == {"C_only": 1, "D_only": 0, "p_exact_mcnemar": 1.0}
    assert s["D_vs_A0_sim_or_part"]["D_only"] == 1 and s["sim"]["C"]["k"] == 2
    assert s["sim_or_part"]["C"]["k"] == 3 and s["underpowered"] and s["C_retried_batches"] == 1
    assert (
        s["by"]["source=untagged"] == {"n": 0} and s["by"]["band=200-299,source=tagged"]["n"] == 3
    )


def _private(tmp_path, monkeypatch, n=3):
    items = [_item(i) for i in range(n)]
    pool = tmp_path / "candidates.json"
    pool.write_text(json.dumps({"items": items}), "utf-8")
    private = tmp_path / "private"
    monkeypatch.setattr(v, "POOL", pool)
    monkeypatch.setattr(v, "POOL_SHA256", hashlib.sha256(pool.read_bytes()).hexdigest())
    monkeypatch.setattr(v, "PRIVATE", private)
    monkeypatch.setattr(v, "OUT", tmp_path / "stats_r2_verify.json")
    return items, private


def test_prepare_page_and_run_keep_texts_private(tmp_path, monkeypatch):
    items, private = _private(tmp_path, monkeypatch)
    assert v.main(["prepare"]) == 0 and v.main(["prepare"]) == 2  # written once
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    assert stat.S_IMODE((private / "input_1.txt").stat().st_mode) == 0o600
    assert v.main(["page"]) == 2  # no answer yet: the batch goes to its retry
    (private / "answer_1.json").write_text(_answer(items), "utf-8")
    assert v.main(["page"]) == 0 and v.main(["page"]) == 2  # built once
    assert stat.S_IMODE((private / "verify.html").stat().st_mode) == 0o600
    html = (private / "verify.html").read_text("utf-8")
    pool = json.loads(html.split('type="application/json">')[1].split("</script>")[0])["pool"]
    (private / "verdicts.json").write_text(
        json.dumps({**_verdicts(items, ["Fix the checkout."] * 3), "pool": "x"}), "utf-8"
    )
    assert v.main(["run"]) == 2  # verdicts from another page
    (private / "verdicts.json").write_text("[]", "utf-8")
    assert v.main(["run"]) == 2  # not an object
    (private / "verdicts.json").write_text("{", "utf-8")
    assert v.main(["run"]) == 2  # not JSON
    assert v.main(["run", "--verdicts", str(private / "absent.json")]) == 2  # missing
    (private / "verdicts.json").write_text(
        json.dumps({**_verdicts(items, ["Fix the checkout."] * 3), "pool": pool}), "utf-8"
    )
    good = (private / "answer_1.json").read_text("utf-8")
    (private / "answer_1.json").write_text(_answer(items, "Rename the folder."), "utf-8")
    assert v.main(["run"]) == 2  # an answer changed after the page: the slots would differ
    (private / "answer_1.json").write_text(good, "utf-8")
    assert v.main(["run"]) == 0 and v.main(["run"]) == 2  # runs once
    stats = json.loads(v.OUT.read_text("utf-8"))
    assert stats["n"] == 3 and stats["C_retried_batches"] == 1 and stats["sim"]["D"]["k"] == 3
    assert stat.S_IMODE(v.OUT.stat().st_mode) == 0o644
    assert stat.S_IMODE((private / "results.json").stat().st_mode) == 0o600
    public = v.OUT.read_text("utf-8")
    assert all(c["text"] not in public and c["id"] not in public for c in items)
    assert "Fix the checkout" not in public


def test_a_moved_pool_or_reused_file_is_refused(tmp_path, monkeypatch, capsys):
    _private(tmp_path, monkeypatch)
    monkeypatch.setattr(v, "POOL_SHA256", "0" * 64)
    with pytest.raises(SystemExit, match="not the pool"):
        v.main(["prepare"])
    monkeypatch.setitem(v.PINNED, "part_r2.py", "0" * 64)
    assert v.main(["page"]) == 2 and v.main(["run"]) == 2
    assert capsys.readouterr().out.count("part_r2.py is not the file the protocol pins") == 2
    assert not v.OUT.exists()
