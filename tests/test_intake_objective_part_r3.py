"""Part R3, the blind test (Amendment 10), on synthetic text only: the pool, the one-sentence
rewrite batches, the answers and their retry, the slots, the guess, the verdict rules, the
blindness check and the scoring. No real dictation is read here."""

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
spec = importlib.util.spec_from_file_location("part_r3", HERE / "part_r3.py")
r3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r3)

#: Amendment 10 pins this file; a change needs a new amendment.
PART_R3_SHA256 = "c2e6e0da5da6c77425174ad1a0d400e1e87d991f36d3857da3734feda46e8251"
TEXT = (  # D's objective is A0's sentence: one rewrite serves both
    "Please rename the photo folder from the event. The photos sit on the shared drive. "
    "Another thing, please fix the checkout that freezes when a customer pays by card. "
    "The checkout froze twice. "
)
SPLIT = (  # D picks another sentence than A0's
    "Please rename the photo folder. The photos sit on the drive. Most important: please fix the "
    "checkout that freezes on card. The checkout froze twice and the checkout matters. Again, the "
    "checkout freezes. "
)
NO_ASK = "The shop opens at nine. The van leaves at ten. "  # no A0; D falls back
SENTENCE = "The shop opens at nine and the van leaves at ten. "


def _item(i, text=TEXT, origin="r2"):
    text = f"{text}Ticket {i}."
    sha = hashlib.sha256(text.encode()).hexdigest()
    row = {"id": sha[:12], "sha256": sha, "text": text, "words": len(text.split())}
    return {**row, "timestamp": "2026-11-20T10:00:00Z", "origin": origin}


def _items():
    return [_item(0), _item(1, SPLIT), _item(2, NO_ASK, "new")]


def test_dictated_is_amendment_9s_one_paragraph_rule():
    assert r3.dictated("One line. Two sentences.") and r3.dictated("\n  One line.  \n\n")
    assert not r3.dictated("One.\n\nTwo.") and not r3.dictated("One.\nTwo.") and not r3.dictated("")


def test_the_file_is_the_one_amendment_10_pins():
    assert hashlib.sha256((HERE / "part_r3.py").read_bytes()).hexdigest() == PART_R3_SHA256
    assert r3._reused_are_pinned()  # part_r, run_arms, part_r2, part_r_claude, part_r2_verify
    assert set(r3.PINNED) == {
        "part_r.py",
        "run_arms.py",
        "part_r2.py",
        "part_r_claude.py",
        "part_r2_verify.py",
    }


def _entry(text, timestamp):
    row = {"type": "user", "turnOrigin": "human", "message": {"role": "user", "content": text}}
    return {**row, "timestamp": timestamp}


def _long(tag, text=TEXT):
    return (text + SENTENCE * 20 + f"Ticket {tag}.").strip()


def test_collect_joins_r2s_unread_tail_and_a_dated_one_paragraph_draw(tmp_path, monkeypatch):
    monkeypatch.setattr(r3, "PRIVATE", tmp_path / "private" / "r3")
    monkeypatch.setattr(r3, "POOL", r3.PRIVATE / "candidates.json")
    monkeypatch.setattr(r3, "R2_FROM", 2)
    r2_items = [
        {**_item(i), "text": t}
        for i, t in enumerate(["seen. ", "seen too. ", "One paragraph. ", "Two.\n\nParagraphs. "])
    ]
    texts = [_long(n) for n in range(6)]
    texts[1] = texts[1].replace(" Another", "\n\nAnother")  # two paragraphs: not dictated
    rows = [
        _entry(texts[0], "2026-11-20T10:00:00Z"),  # joins
        _entry(texts[1], "2026-11-20T10:00:00Z"),
        _entry(texts[2], "2026-11-23T00:00:00Z"),  # at the cutoff: out
        _entry(texts[3], ""),  # no timestamp: out
        _entry(texts[4], "2026-11-21T08:00:00Z"),  # in an earlier pool: out
        _entry(texts[5], "2026-11-22T23:59:59Z"),  # joins
    ]
    transcripts = tmp_path / "projects"
    (transcripts / "p").mkdir(parents=True)
    (transcripts / "p" / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows), "utf-8")
    seen = {hashlib.sha256(texts[4].encode()).hexdigest()}
    counts = r3.collect(transcripts, r2_items, seen)
    assert counts["r2_positions"] == 2 and counts["r2_one_paragraph"] == 1
    assert counts["draw"]["candidates"] == 5 and counts["draw"]["in Part R"] == 1
    assert counts["draw_before_cutoff"] == 3 and counts["draw_one_paragraph"] == 2
    assert counts["pool"] == 3
    pool = json.loads(r3.POOL.read_text("utf-8"))
    got = {c["text"]: c["origin"] for c in pool["items"]}
    assert got == {"One paragraph. ": "r2", texts[0]: "new", texts[5]: "new"}
    order = sorted(pool["items"], key=lambda c: c["sha256"])
    r3.random.Random(r3.SEED).shuffle(order)
    assert pool["items"] == order and pool["cutoff"] == r3.CUTOFF and pool["r2_from"] == 3
    assert stat.S_IMODE(r3.POOL.stat().st_mode) == 0o600
    assert stat.S_IMODE(r3.PRIVATE.stat().st_mode) == 0o700
    with pytest.raises(SystemExit, match="drawn once"):
        r3.collect(transcripts, r2_items, seen)


def test_collect_refuses_a_moved_earlier_pool(tmp_path, monkeypatch):
    pool = tmp_path / "candidates.json"
    pool.write_text(json.dumps({"items": []}), "utf-8")
    monkeypatch.setattr(r3.part_r2, "PART_R_POOL", pool)
    monkeypatch.setattr(
        r3.part_r2, "PART_R_POOL_SHA256", hashlib.sha256(pool.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(r3.r2v, "POOL", pool)
    with pytest.raises(SystemExit, match="candidates.json is not the pool"):
        r3._earlier_pools()  # Part R's matches, Part R2's does not
    monkeypatch.setattr(r3.r2v, "POOL_SHA256", hashlib.sha256(pool.read_bytes()).hexdigest())
    assert r3._earlier_pools() == ([], set())


def test_no_rewrite_agent_reads_two_sentences_of_one_message():
    items = _items()
    sets = r3.rewrites(items)
    assert sorted(e["text"] for e in sets["a0"]) == [  # NO_ASK has no ask
        "Please rename the photo folder from the event.",
        "Please rename the photo folder.",
    ]
    assert sorted(e["text"] for e in sets["d"]) == [  # TEXT's D is its A0 sentence: no entry
        "Most important: please fix the checkout that freezes on card.",
        r3.sentences(items[2])[1],  # NO_ASK's fallback
    ]
    for c in items:
        a0, d, _ = r3.sentences(c)
        in_a0 = [e for e in sets["a0"] if e["id"] == r3._rid("A0", c)]
        in_d = [e for e in sets["d"] if e["id"] == r3._rid("D", c)]
        assert len(in_a0) + len(in_d) <= 2 and len(in_a0) <= 1 and len(in_d) <= 1
        assert (len(in_d) == 0) == r3._shared(a0, d)
    ids = [e["id"] for s in sets.values() for e in s]
    assert len(set(ids)) == len(ids) and not set(ids) & {c["id"] for c in items}
    assert r3.rewrites(items) == sets  # seeded: prepare and page agree


def test_the_rewrite_input_shows_sentences_and_no_message():
    text = r3.render([{"id": "abc", "text": "Fix it. " * 40}, {"id": "def", "text": "Go."}])
    lines = text.splitlines()
    assert lines[0] == "=== FRASE 1/2 · id abc ===" and lines[-1] == "=== FIM ==="
    assert max(map(len, lines)) <= 160 and "MENSAGEM" not in text
    assert "{input}" in r3.REWRITE_BRIEF and "do not invent an ask" in r3.REWRITE_BRIEF


def _answer(entries, line="Fix the checkout."):
    return json.dumps({"items": [{"id": e["id"], "objective": line} for e in entries]})


def test_each_prefix_gets_one_retry_then_offers_nothing(tmp_path):
    entries = [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}]
    (tmp_path / "a0_answer_1.json").write_text("{}", "utf-8")
    lines, retry = r3.answers([entries], tmp_path, "a0")
    assert retry == [1] and (tmp_path / "a0_answer_1.rejected.json").exists()
    assert r3.answers([entries], tmp_path, "a0")[1] == [1]  # the retry has not written yet
    assert r3.answers([entries], tmp_path, "d")[1] == [1]  # another prefix, its own files
    (tmp_path / "a0_answer_1.json").write_text("", "utf-8")
    assert r3.answers([entries], tmp_path, "a0") == ({"a": None, "b": None}, [])
    (tmp_path / "a0_answer_1.json").write_text(_answer(entries), "utf-8")
    assert r3.answers([entries], tmp_path, "a0") == (
        {"a": "Fix the checkout.", "b": "Fix the checkout."},
        [],
    )
    assert stat.S_IMODE((tmp_path / "a0_answer_1.json").stat().st_mode) == 0o600


def _lines(
    items, c="Fix the checkout when a card payment freezes.", a0="Rename the folder.", d="Fix it."
):
    sets = r3.rewrites(items)
    return {
        "c": {x["id"]: c for x in items},
        "a0": {e["id"]: a0 for e in sets["a0"]},
        "d": {e["id"]: d for e in sets["d"]},
    }


def test_a_shared_sentence_gives_both_arms_one_rewrite_and_one_slot():
    items = _items()
    lines = _lines(items)
    offered, info = r3.offer(items[0], lines)
    assert offered == {
        "C": lines["c"][items[0]["id"]],
        "D": "Rename the folder.",
        "A0": "Rename the folder.",
    }
    assert info == {"shared": True, "no_ask": False, "D_fallback": False}
    texts, where = r3.slots(items[0], offered)
    assert len(texts) == 2 and where["D"] == where["A0"] != where["C"]
    offered, info = r3.offer(items[1], lines)
    assert offered["D"] == "Fix it." and not info["shared"]
    assert len(r3.slots(items[1], offered)[0]) == 3
    offered, info = r3.offer(items[2], lines)
    assert (
        offered["A0"] is None
        and offered["D"] == "Fix it."
        and info["no_ask"]
        and info["D_fallback"]
    )
    assert r3.slots(items[1], offered) == r3.slots(items[1], offered)  # seeded


def test_the_page_shows_texts_slots_and_the_guess_but_no_arm():
    items = [_item(0, TEXT + "a < b </script> end. ")]
    html = r3.page(items, _lines(items))
    data = json.loads(html.split('type="application/json">')[1].split("</script>")[0])
    assert (
        data["page"]
        == r3.page_id(items, _lines(items))
        != r3.page_id(items, _lines(items, c="Go."))
    )
    assert set(data["items"][0]) == {"id", "date", "words", "text", "slots"}
    assert data["guess"] == r3.GUESS and data["dont_know"] == "nao_sei"
    assert "</script> end" not in html and "\\u003c/script> end" in html
    assert '"lcc-r3-"' in html and "Não sei" in html and 'a.download = "verdicts.json"' in html
    assert "origin" not in data["items"][0] and "r2" not in json.dumps(data["items"][0]["slots"])


def _verdicts(items, lines, ratings="sim", guess=0):
    out = []
    for c in items:
        n = len(r3.slots(c, r3.offer(c, lines)[0])[0])
        out.append(
            {
                "id": c["id"],
                "decision": "use",
                "ratings": [ratings] * n,
                "guess": guess if n > 1 else None,
            }
        )
    return {"version": 1, "items": out}


@pytest.mark.parametrize("guess", [None, 3, -1, True, "0", "sei"])
def test_a_message_with_two_lines_needs_a_guess_in_range(guess):
    items = _items()[:1]
    lines = _lines(items)
    bad = _verdicts(items, lines)
    bad["items"][0]["guess"] = guess
    with pytest.raises(SystemExit, match="message 1"):
        r3.judged(items, lines, bad)


def test_one_line_takes_no_guess_and_a_skip_no_verdict():
    items = _items()
    lines = _lines(items, c="Fix it.")  # NO_ASK: C and D give one line
    good = _verdicts(items, lines)
    assert good["items"][2]["guess"] is None
    rows, skips = r3.judged(items, lines, good)
    assert len(rows) == 3 and rows[2]["slots"] == 1 and rows[2]["guess"] is None
    bad = json.loads(json.dumps(good))
    bad["items"][2]["guess"] = 0
    with pytest.raises(SystemExit, match="message 3"):
        r3.judged(items, lines, bad)
    bad["items"][2] = {
        "id": items[2]["id"],
        "decision": "skip",
        "reason": "sensível",
        "guess": None,
    }
    with pytest.raises(SystemExit, match="message 3"):
        r3.judged(items, lines, bad)
    del bad["items"][2]["guess"]
    rows, skips = r3.judged(items, lines, bad)
    assert len(rows) == 2 and skips["sensível"] == 1
    with pytest.raises(SystemExit, match="all 3 messages"):
        r3.judged(items, lines, {"items": good["items"][:2]})


def test_each_arm_takes_its_slots_rating_and_the_guess_is_scored_against_c():
    items = _items()
    lines = _lines(items)
    lines["c"][items[1]["id"]] = None  # C's batch failed twice
    v = _verdicts(items, lines, "nao")
    texts, where = r3.slots(items[0], r3.offer(items[0], lines)[0])
    v["items"][0]["ratings"][where["C"]] = "sim"
    v["items"][0]["guess"] = where["C"]
    v["items"][1]["guess"] = "nao_sei"
    rows, _ = r3.judged(items, lines, v)
    assert (rows[0]["C"], rows[0]["D"], rows[0]["A0"]) == ("sim", "nao", "nao")
    assert rows[0]["guess"] == "C" and rows[0]["C_own_slot"] and rows[0]["shared"]
    assert rows[1]["C"] == "nao" and rows[1]["missing"]["C"] and rows[1]["guess"] == "nao_sei"
    assert not rows[1]["C_own_slot"]
    assert rows[2]["A0"] == "nao" and not rows[2]["missing"]["A0"] and rows[2]["no_ask"]
    assert rows[0]["words"]["A0"] == 3 and rows[2]["words"]["A0"] is None


def _row(c, d, a0, guess="C", slots=2, own=True):
    return {
        "C": c,
        "D": d,
        "A0": a0,
        "slots": slots,
        "C_own_slot": own,
        "guess": guess,
        "origin": "r2",
        "shared": d == a0,
        "D_fallback": False,
        "no_ask": False,
        "missing": {"C": False, "D": False, "A0": False},
        "words": {"C": 10, "D": 6, "A0": 5},
    }


def test_blindness_reads_too_few_not_blind_or_not_refuted():
    few = [_row("sim", "nao", "nao")] * 4 + [_row("sim", "nao", "nao", "nao_sei")] * 6
    got = r3.blindness(few)
    assert got == {"eligible": 10, "dont_know": 6, "guessed": 4, "reading": "too few to read"}
    named = r3.blindness([_row("sim", "nao", "nao")] * 12)
    assert (
        named["reading"] == "not blind" and named["chance"] == 0.5 and named["named_C"]["k"] == 12
    )
    mixed = [_row("sim", "nao", "nao")] * 3 + [_row("sim", "nao", "nao", "other", 3)] * 3
    got = r3.blindness(mixed + [_row("sim", "sim", "sim", "C", 1, False)])  # one slot: not eligible
    assert got["reading"] == "blindness not refuted at this size" and got["eligible"] == 6
    assert got["chance"] == round((3 * 0.5 + 3 / 3) / 6, 4)


def test_summary_pairs_c_with_a0_first():
    rows = [_row("sim", "nao", "nao"), _row("sim", "sim", "sim"), _row("parte", "nao", "sim")]
    s = r3.summarise(rows, {"sensível": 1}, {"c": 1, "a0": 0, "d": 0})
    assert s["C_vs_A0"] == {"n": 3, "C_only": 1, "A0_only": 1, "p_exact_mcnemar": 1.0}
    assert s["C_vs_D"] == {"n": 3, "C_only": 1, "D_only": 0, "p_exact_mcnemar": 1.0}
    assert s["C_vs_A0_sim_or_part"]["C_only"] == 1 and s["sim"]["C"]["k"] == 2
    assert s["by_origin"]["new"] == {"n": 0} and s["by_origin"]["r2"]["n"] == 3
    assert s["words"]["C"] == {"n": 3, "mean": 10, "min": 10, "max": 10}
    assert s["retried_batches"] == {"c": 1, "a0": 0, "d": 0} and s["shared_rewrite"] == 2


def test_a_line_lost_after_its_retry_leaves_the_pair_instead_of_helping_the_other_arm():
    lost = _row("sim", "nao", "nao")
    lost["missing"] = {"C": False, "D": False, "A0": True}
    rows = [_row("sim", "sim", "sim"), lost]
    s = r3.summarise(rows, {}, {"c": 0, "a0": 1, "d": 0})
    assert s["C_vs_A0"] == {"n": 1, "C_only": 0, "A0_only": 0, "p_exact_mcnemar": 1.0}
    assert s["C_vs_D"]["n"] == 2 and s["C_vs_D"]["C_only"] == 1 and s["missing"]["A0"] == 1
    assert s["sim"]["A0"]["n"] == 1 and s["sim"]["C"]["n"] == 2  # nor does it count in the rates


def _private(tmp_path, monkeypatch):
    items = _items()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    pool = private / "candidates.json"
    pool.write_text(json.dumps({"items": items}), "utf-8")
    monkeypatch.setattr(r3, "PRIVATE", private)
    monkeypatch.setattr(r3, "POOL", pool)
    monkeypatch.setattr(r3, "OUT", tmp_path / "stats_r3.json")
    return items, private


def _answer_all(items, private, line="Fix the checkout."):
    for prefix, batches in r3.groups(items).items():
        for k, batch in enumerate(batches, 1):
            (private / f"{prefix}_answer_{k}.json").write_text(
                _answer(batch, f"{line} {prefix}"), "utf-8"
            )


def test_prepare_page_and_run_keep_texts_private(tmp_path, monkeypatch):
    items, private = _private(tmp_path, monkeypatch)
    assert r3.main(["prepare"]) == 0 and r3.main(["prepare"]) == 2  # written once
    first = (private / "d_input_1.txt").read_text("utf-8")
    (private / "d_input_1.txt").unlink()  # a prepare cut short resumes with the same inputs
    assert r3.main(["prepare"]) == 0 and (private / "d_input_1.txt").read_text("utf-8") == first
    (private / "d_input_1.txt").write_text(first + "x", "utf-8")
    assert r3.main(["prepare"]) == 2  # an input that differs is never overwritten
    (private / "d_input_1.txt").write_text(first, "utf-8")
    for name in ("c_input_1.txt", "a0_input_1.txt", "d_input_1.txt"):
        assert stat.S_IMODE((private / name).stat().st_mode) == 0o600
    a0_input = (private / "a0_input_1.txt").read_text("utf-8")
    assert "=== FRASE 1/2" in a0_input and "photos sit" not in a0_input  # one sentence each
    assert all(c["id"] not in a0_input for c in items)
    assert r3.main(["page"]) == 2  # no answer yet: every batch goes to its retry
    for path in private.glob("*.rejected.json"):
        path.unlink()
    _answer_all(items, private)
    assert r3.main(["page"]) == 0 and r3.main(["page"]) == 2  # built once
    html = (private / "verify.html").read_text("utf-8")
    page = json.loads(html.split('type="application/json">')[1].split("</script>")[0])["page"]
    lines = r3.collected(items, private)[0]
    verdicts = {**_verdicts(items, lines), "page": page}
    (private / "verdicts.json").write_text(json.dumps({**verdicts, "page": "x"}), "utf-8")
    assert r3.main(["run"]) == 2  # verdicts from another page
    (private / "verdicts.json").write_text("{", "utf-8")
    assert r3.main(["run"]) == 2  # not JSON
    assert r3.main(["run", "--verdicts", str(private / "absent.json")]) == 2  # missing
    (private / "verdicts.json").write_text(json.dumps(verdicts), "utf-8")
    good = (private / "d_answer_1.json").read_text("utf-8")
    (private / "d_answer_1.json").write_text(good.replace("Fix the checkout.", "Rename."), "utf-8")
    assert r3.main(["run"]) == 2  # an answer changed after the page: the slots would differ
    (private / "verify.html").unlink()
    assert r3.main(["page"]) == 0  # a page rebuilt on that answer, with as many slots
    assert r3.main(["run"]) == 2  # verdicts from the first page do not fit it
    (private / "d_answer_1.json").write_text(good, "utf-8")
    (private / "verify.html").unlink()
    assert r3.main(["page"]) == 0
    assert r3.main(["run"]) == 0 and r3.main(["run"]) == 2  # runs once
    stats = json.loads(r3.OUT.read_text("utf-8"))
    assert stats["n"] == 3 and stats["sim"]["C"]["k"] == 3 and stats["shared_rewrite"] == 1
    assert stats["retried_batches"] == {"c": 0, "a0": 0, "d": 0}
    assert (
        stats["blindness"]["eligible"] == 3 and stats["blindness"]["reading"] == "too few to read"
    )
    assert stat.S_IMODE(r3.OUT.stat().st_mode) == 0o644
    assert stat.S_IMODE((private / "results.json").stat().st_mode) == 0o600
    public = r3.OUT.read_text("utf-8")
    assert all(c["text"] not in public and c["id"] not in public for c in items)
    assert "Fix the checkout" not in public and "Ticket" not in public


def test_a_reused_file_that_moved_is_refused(tmp_path, monkeypatch, capsys):
    _private(tmp_path, monkeypatch)
    monkeypatch.setitem(r3.PINNED, "part_r2_verify.py", "0" * 64)
    for cmd in ("collect", "prepare", "page", "run"):
        assert r3.main([cmd]) == 2
    assert capsys.readouterr().out.count("part_r2_verify.py is not the file the protocol pins") == 4
    assert not r3.OUT.exists() and not list(r3.PRIVATE.glob("*_input_*"))
