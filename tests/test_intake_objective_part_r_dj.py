"""Arm DJ on Part R of intake-objective-v1 (Amendment 5), with a stand-in for Jev. No network,
no private data: every text here is synthetic, and the private paths point at tmp_path."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import math
import stat
import sys
import urllib.error
from pathlib import Path

import pytest

from lcc.intake.objective import analyse, choose

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "intake-objective-v1"
sys.path.insert(0, str(HERE))

#: Amendment 5 pins this file; a change needs a new amendment.
PART_R_DJ_SHA256 = "b028dca88f6ba4b5c0f13fe715324267aed86a8230218e461356ea1dd7ac5600"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prd = _load("part_r_dj")
run_dj = _load("run_dj")

TEXT = prd.SMOKE_TEXT
ONE_BLOCK = "Please fix the checkout that freezes when a customer pays by card."
PRIVATE_TEXT = "the checkout that freezes"


class FakeJev:
    model = "jev-latest"

    def __init__(self, label="B", p=0.9, fail=False, echo="jev-1.14.0", extra=None):
        self.label, self.p, self.fail, self.echo, self.calls = label, p, fail, echo, []
        self.extra = extra or {}

    def evaluate(self, state, questions):
        self.calls.append((json.dumps(state), json.dumps(questions)))
        if self.fail:
            raise RuntimeError("down")
        main = {"choice": self.label, "probabilities": {self.label: self.p}}
        return {"model": self.echo, "answers": {"main": main}, **self.extra}


def _case():
    a = analyse(TEXT)
    gold = next(i for i, (s, _) in enumerate(a.spans) if TEXT[s:].startswith("Another thing"))
    return {"id": "c1", "text": TEXT, "main": [list(a.spans[gold])]}, a, choose(a, prd.WEIGHTS)


def test_the_file_is_the_one_amendment_5_pins():
    assert hashlib.sha256((HERE / "part_r_dj.py").read_bytes()).hexdigest() == PART_R_DJ_SHA256


def test_the_wrapper_sends_what_the_frozen_dj_sends():
    case, a, pick = _case()
    direct, wrapped = FakeJev(), FakeJev()
    run_dj.dj_pick(direct, TEXT, a, pick)
    prd.dj_row(prd.Recorder(wrapped), case, a, pick)
    assert wrapped.calls == direct.calls and len(direct.calls) == 1
    failing = FakeJev(fail=True)
    prd.dj_row(prd.Recorder(failing), case, a, pick)
    assert len(failing.calls) == 1


def test_used_jev_reads_the_unrounded_probability():
    case, a, pick = _case()
    assert run_dj.dj_pick(FakeJev("B", 0.59996), TEXT, a, pick)["p"] == 0.6  # rounded display
    row = prd.dj_row(prd.Recorder(FakeJev("B", 0.59996)), case, a, pick)
    assert row["p"] == 0.59996 and row["used_jev"] is False and not row["DJ"]
    row = prd.dj_row(prd.Recorder(FakeJev("B", 0.6)), case, a, pick)
    assert row["used_jev"] is True and row["DJ"] and row["probabilities"] == {"B": 0.6}


def test_the_model_comes_only_from_this_answered_call():
    case, a, pick = _case()
    rec = prd.Recorder(FakeJev())
    assert prd.dj_row(rec, case, a, pick)["model"] == "jev-1.14.0"
    for client in (FakeJev(fail=True), FakeJev(label="Z")):
        row = prd.dj_row(prd.Recorder(client), case, a, pick)
        assert "model" not in row and "error" in row
    resolved = FakeJev(echo="jev-latest", extra={"resolved_model": "jev-1.15.0"})
    assert prd.dj_row(prd.Recorder(resolved), case, a, pick)["model"] == "jev-1.15.0"
    assert prd.dj_row(prd.Recorder(FakeJev(echo=None)), case, a, pick)["model"] == "unidentified"
    for echo in (PRIVATE_TEXT, "jev-checkout"):
        row = prd.dj_row(prd.Recorder(FakeJev(echo=echo)), case, a, pick)
        assert row["model"] == "unexpected"
    summary = prd.summarise([row], {"c1": False})
    assert "checkout" not in json.dumps(row) + json.dumps(summary)


def _ledger_after(tmp_path, opener):
    tmp_path.mkdir(exist_ok=True)
    ledger = tmp_path / "ledger.jsonl"
    client = prd.PrivateLedgerJev("k", ledger_path=ledger, attempts=1, opener=opener)
    case, a, pick = _case()
    row = prd.dj_row(prd.Recorder(client), case, a, pick)
    return json.loads(ledger.read_text(encoding="utf-8")), ledger, row


def _answer(body):
    return lambda request, timeout: io.BytesIO(json.dumps(body).encode())


def test_the_ledger_keeps_no_message_text(tmp_path):
    def http_error(request, timeout):
        body = json.dumps({"error": f"cannot parse: {PRIVATE_TEXT}"}).encode()
        raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, io.BytesIO(body))

    def network_error(request, timeout):
        raise urllib.error.URLError(PRIVATE_TEXT)

    echo = {
        "model": PRIVATE_TEXT,
        "usage": {"input_tokens": PRIVATE_TEXT, "output_tokens": 3},
        "answers": {
            "main": {"type": "choice", "choice": PRIVATE_TEXT, "confidence": 1e400},
            PRIVATE_TEXT: {"type": "free", "noul": PRIVATE_TEXT},
        },
    }
    cases = ((http_error, "api_error"), (network_error, "network"), (_answer(echo), None))
    for n, (opener, kind) in enumerate(cases):
        line, ledger, _ = _ledger_after(tmp_path / str(n), opener)
        assert PRIVATE_TEXT not in json.dumps(line) and line.get("error") == kind
        assert stat.S_IMODE(ledger.stat().st_mode) == 0o600
    assert line["resolved_model"] == "unexpected" and "input_tokens" not in line
    assert line["answers"] == {"main": {"choice": None, "confidence": None}}


def test_an_odd_extra_answer_does_not_change_a_valid_pick(tmp_path):
    main = {"type": "choice", "choice": "B", "probabilities": {"B": 0.9, "C": 1e400}}
    extra = {"type": "choice", "choice": ["x"], "confidence": "high"}
    body = {"model": "jev-1.14.0", "answers": {"main": main, "extra": extra}}
    line, _, row = _ledger_after(tmp_path, _answer(body))
    assert row["used_jev"] and row["DJ"] and "error" not in row
    assert row["probabilities"] == {"B": 0.9} and json.dumps(row, allow_nan=False)
    assert line["answers"] == {"main": {"choice": "B", "confidence": None}}


def test_a_rerun_neither_asks_again_nor_loses_a_row(tmp_path):
    journal = tmp_path / "journal.jsonl"
    case, _, pick = _case()
    second = {**case, "id": "c2"}
    done = {"id": "c1", "DJ": True, "called": True, "jev": "B", "used_jev": True}
    marker = json.dumps({"id": "c2", "pending": True})
    journal.write_text(json.dumps(done) + "\n" + marker + "\n" + '{"id": "c3", "DJ"', "utf-8")
    jev = FakeJev()
    rows = prd.run([case, second], prd.Recorder(jev), journal)
    assert jev.calls == [] and rows[0] == done
    assert rows[1]["error"] == "interrupted" and rows[1]["DJ_span"] == list(pick.objective_span)
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    # A fresh case is marked pending before its call, then finished.
    third = {**case, "id": "c3"}
    prd.run([case, second, third], prd.Recorder(jev), journal)
    lines = [json.loads(x) for x in journal.read_text("utf-8").splitlines()]
    assert lines[-2] == {"id": "c3", "pending": True} and lines[-1]["jev"] == "B"
    assert len(jev.calls) == 1
    # A case dj_pick makes no call for gets no pending marker, so a rerun cannot call it an error.
    one = {"id": "c4", "text": ONE_BLOCK, "main": [[0, len(ONE_BLOCK)]]}
    rows = prd.run([one], prd.Recorder(jev), journal)
    assert rows[0]["called"] is False and "error" not in rows[0] and len(jev.calls) == 1
    assert {"id": "c4", "pending": True} not in [json.loads(x) for x in journal.open("r")]


def test_a_finished_journal_needs_no_client(tmp_path):
    journal = tmp_path / "journal.jsonl"
    case, _, _ = _case()
    done = {"id": "c1", "DJ": True, "called": True, "jev": "B", "used_jev": True}
    journal.write_text(json.dumps(done) + '\n{"id": "c2", "pending": true}\n', "utf-8")
    rows = prd.run([case, {**case, "id": "c2"}], prd.Recorder(None), journal)
    assert rows[0] == done and rows[1]["error"] == "interrupted"


def test_only_a_cut_last_line_is_dropped(tmp_path):
    journal = tmp_path / "journal.jsonl"
    before = '{"id": "c1", "pending": true}\n{"id": "c1", "DJ"\n{"id": "c2", "DJ": true}\n'
    journal.write_text(before, encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        prd._journal_rows(journal)
    assert journal.read_text(encoding="utf-8") == before


def test_a_failed_journal_rewrite_leaves_the_old_journal(tmp_path, monkeypatch):
    journal = tmp_path / "journal.jsonl"
    before = '{"id": "c1", "DJ": true}\n{"id": "c2", "DJ"'
    journal.write_text(before, encoding="utf-8")

    def boom(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(prd.part_r.os, "replace", boom)
    with pytest.raises(OSError):
        prd._journal_rows(journal)
    assert journal.read_text(encoding="utf-8") == before
    assert [p.name for p in tmp_path.iterdir()] == ["journal.jsonl"]


def test_summary_counts_what_dj_fixed_lost_and_skipped():
    rows = [
        {"id": "a", "DJ": True, "called": True, "jev": "A", "used_jev": True, "model": "m"},
        {"id": "b", "DJ": False, "called": True, "jev": None, "used_jev": False, "error": "x"},
        {"id": "c", "DJ": True, "called": True, "jev": "B", "used_jev": False},
        {"id": "d", "DJ": True, "called": False, "jev": None, "used_jev": False},
        {"id": "e", "DJ": False, "called": True, "jev": "C", "used_jev": True, "model": "m"},
    ]
    # A failed call keeps D's pick (b: both miss); only an accepted Jev pick can lose a hit (e).
    s = prd.summarise(rows, {"a": False, "b": False, "c": True, "d": True, "e": True})
    assert (s["dj_fixed_d_misses"], s["dj_lost_d_hits"]) == (1, 1)
    assert (s["calls"], s["errors"], s["used_jev"], s["below_threshold"]) == (4, 1, 2, 1)
    assert s["DJ"]["k"] == 3 and s["D"]["k"] == 3 and s["model"] == "m"


def test_the_smoke_text_makes_one_call_and_needs_an_answer():
    jev = FakeJev()
    assert prd._smoke(prd.Recorder(jev)) and len(jev.calls) == 1
    bad = (FakeJev(fail=True), FakeJev(label="Z"), FakeJev(p=2), FakeJev(p=math.nan))
    for client in (*bad, FakeJev(echo="jev-1.15.0-rc1"), FakeJev(echo=None)):
        assert not prd._smoke(prd.Recorder(client))


def _no_reads(monkeypatch, tmp_path):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("read or network before the refusal")

    monkeypatch.setattr(prd, "_read_pinned", forbidden)
    monkeypatch.setattr(prd.PrivateLedgerJev, "from_env", forbidden)
    monkeypatch.setattr(prd, "LOCK", tmp_path / "lock")
    for name in ("RESULTS", "OUT", "JOURNAL", "LEDGER"):
        monkeypatch.setattr(prd, name, tmp_path / name)


@pytest.mark.parametrize("value", ["https://example.invalid", ""])
def test_it_refuses_another_endpoint_or_model_first(monkeypatch, tmp_path, capsys, value):
    _no_reads(monkeypatch, tmp_path)
    for var in ("TYPESAFE_ENDPOINT", "TYPESAFE_MODEL"):
        monkeypatch.setenv(var, value)
        assert prd.main(["--labels", str(tmp_path / "labels.json")]) == 2
        assert var in capsys.readouterr().out
        monkeypatch.delenv(var)


def test_after_its_results_it_only_publishes_the_summary(monkeypatch, tmp_path, capsys):
    _no_reads(monkeypatch, tmp_path)
    monkeypatch.delenv("TYPESAFE_ENDPOINT", raising=False)
    monkeypatch.delenv("TYPESAFE_MODEL", raising=False)
    summary = {"n": 1, "calls": 1}
    rows = [{"id": "c1", "DJ_span": [0, 9]}]
    (tmp_path / "RESULTS").write_text(json.dumps({"rows": rows, "summary": summary}), "utf-8")
    (tmp_path / "JOURNAL").write_text('{"id": "c1", "pending": true}\n', encoding="utf-8")
    args = ["--labels", str(tmp_path / "labels.json")]
    assert prd.main(args) == 0
    assert json.loads((tmp_path / "OUT").read_text("utf-8")) == summary
    assert not (tmp_path / "JOURNAL").exists()
    assert prd.main(args) == 2
    assert "already ran" in capsys.readouterr().out
