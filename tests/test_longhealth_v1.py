"""LongHealth v1 harness (benchmarks/research/longhealth-v1): builder, compaction, verifier and scoring on a
synthetic benchmark. No LongHealth data and no model call is used here."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "longhealth-v1"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lh = _load("longhealth_v1")
shim = _load("recall_shim")


def _bench(n_patients: int = 9, n_texts: int = 8) -> dict:
    bench = {}
    for p in range(n_patients):
        pid = f"patient_{p:02d}"
        name = f"Name{p} Surname{p}"
        texts = {f"text_{j}": (f"Discharge letter for {name}. Visit {j}. Haemoglobin {10 + j}.{p} g/dl measured "
                               f"on day {j + 1} of the stay. ") * 8 for j in range(n_texts)}
        questions = []
        for q in range(20):
            j = q % n_texts
            questions.append({"question": f"Question {q} about visit {j}?", "answer_a": "none of these",
                                  "answer_b": f"{10 + j}.{p} g/dl", "answer_c": "7.7 g/dl", "answer_d": "unknown value",
                                  "answer_e": "a different visit", "correct": f"{10 + j}.{p} g/dl",
                                  "answer_location": {f"text_{j}": {"start": [0.1], "end": [0.2]}}})
        bench[pid] = {"texts": texts, "name": name, "birthday": f"0{p % 9 + 1}.01.1960", "diagnosis": "x", "questions": questions}
    return bench


def test_s_text_is_probe_eval_v1_frozen_text():
    # probe-eval-v1 hashes the fenced block body, which ends with its newline
    assert hashlib.sha256((lh.S_TEXT + "\n").encode()).hexdigest() == lh.S_SHA


def test_q0_is_qt_without_the_recall_sentence():
    assert "recall tool" in lh.Q_T and "recall tool" not in lh.Q_0
    assert lh.Q_0.replace(" ", "") == lh.Q_T.replace(lh.RECALL_SENTENCE, "").replace(" ", "")


def test_git_blob_sha_and_benchmark_guard(tmp_path):
    assert lh.git_blob_sha(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    bad = tmp_path / "benchmark_v5.json"
    bad.write_text("{}")
    with pytest.raises(SystemExit):
        lh.load_benchmark(bad)


def test_build_session_shape_and_determinism():
    bench = _bench()
    early = lh.build_session(bench, "patient_03", "ans_early")
    assert early == lh.build_session(bench, "patient_03", "ans_early")
    calls = [b for b in early["blocks"] if b["kind"] == "tool_use"]
    assert all(set(json.loads(b["content"])) == {"file_path"} for b in calls)
    assert all(json.loads(b["content"])["file_path"].startswith("records/p") for b in calls)
    first_read = early["reads"][calls[0]["id"]]
    assert first_read[0] == "patient_03"
    assert len(early["folders"]) == lh.K and all(len(f) == 3 for f in early["folders"].values())
    assert not any("Name" in b["content"] for b in calls)  # folders and file names never carry a name
    late = lh.build_session(bench, "patient_03", "ans_late")
    assert late["reads"][[b for b in late["blocks"] if b["kind"] == "tool_use"][-1]["id"]][0] == "patient_03"
    unans = lh.build_session(bench, "patient_03", "unans")
    assert "patient_03" not in unans["folders"] and len(unans["folders"]) == lh.K
    assert unans["P"].startswith("Questions about Name3 Surname3")
    assert f"F: {lh.F_TEXT}" in unans["P"] and "F: " not in unans["P_none"]


def test_compaction_stashes_early_target_keeps_late_and_checks_blobs(tmp_path, monkeypatch):
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "unused"))
    bench = _bench()
    for cond, want in (("ans_early", "stash_dependent"), ("ans_late", "in_view")):
        sess = lh.build_session(bench, "patient_03", cond)
        comp = lh.compact_session(sess, tmp_path / cond)
        assert comp["ok"], comp
        rows = lh.locate_session(sess, comp, bench["patient_03"])
        share = sum(r["where"] == want for r in rows) / len(rows)
        assert share >= 0.8, (cond, share)
    sess = lh.build_session(bench, "patient_03", "ans_early")
    comp = lh.compact_session(sess, tmp_path / "tamper")
    texts = {b["id"]: b["content"] for b in comp["blocks"] if b["kind"] == "tool_result"}
    pointers = [t for t in texts.values() if lh.NOTE_RE.fullmatch(t)]
    assert pointers and all(' · "' in t for t in pointers)  # head pointers, and the check parses every one
    assert len(pointers) == len(comp["stashed"])
    blob = next((tmp_path / "tamper").glob("[0-9a-f]" * 64))
    blob.write_bytes(b"changed")
    assert lh.independent_stash_check(sess["blocks"], texts, tmp_path / "tamper")


def test_parse_answers_lines_quotes_and_f():
    text = ('1: B: 10.3 g/dl | quote: "Haemoglobin 10.3 g/dl measured"\n'
            "**2**: F: Question cannot be answered with provided documents\n"
            "3. C: 7.7 g/dl | quote: one | quote: \"two words here\"\nnoise")
    got = lh.parse_answers(text)
    assert got[1] == ("B", ["Haemoglobin 10.3 g/dl measured"], '10.3 g/dl | quote: "Haemoglobin 10.3 g/dl measured"')
    assert got[2] == ("F", [], "Question cannot be answered with provided documents")
    assert got[3][0] == "C" and got[3][1] == ["one", "two words here"]


def test_check_line_quote_patient_and_numbers():
    records = {"p11": ["Haemoglobin 10.3 g/dl measured on day 1."], "p22": ["Haemoglobin 9.9 g/dl measured on day 2."]}
    ok = ["Haemoglobin 10.3 g/dl measured"]
    assert lh.check_line("B", ok, "10.3 g/dl", records, "p11") is None
    assert lh.check_line("F", [], lh.F_TEXT, records, None) is None
    assert lh.check_line("B", [], "10.3 g/dl", records, "p11") == "quote not found"
    assert lh.check_line("B", ["short"], "10.3 g/dl", records, "p11") == "quote not found"
    assert lh.check_line("B", ["Haemoglobin 9.9 g/dl measured"], "9.9 g/dl", records, "p11") == \
        "quote is not from this patient's records"
    # one right quote does not excuse a quote from another patient (check 2 is per quote)
    assert lh.check_line("B", ok + ["Haemoglobin 9.9 g/dl measured"], "9.9 g/dl", records, "p11") == \
        "quote is not from this patient's records"
    assert lh.check_line("B", ok, "11.0 g/dl", records, "p11") == "number not in quote"
    assert lh.check_line("B", ok, "10.3 g/dl", records, None) == "quote is not from this patient's records"


def test_verify_and_merge_reask():
    bench = _bench()
    sess = lh.build_session(bench, "patient_03", "unans")
    first = "\n".join(f"{i}: B: x" for i in range(1, 21))  # no quotes: every line fails check 1
    catches = lh.verify(sess, bench["patient_03"], first)
    assert sorted(catches) == list(range(1, 21)) and set(catches.values()) == {"quote not found"}
    other = next(f for p, f in sess["folders"].items() if p != "patient_03")
    quote = lh.records_by_folder(sess)[other][0][:60]
    second = ("1: F: Question cannot be answered with provided documents\n"
              f'2: C: 7.7 g/dl | quote: "{quote}"')
    final, forced = lh.merge_reask(sess, bench["patient_03"], first, second, catches)
    assert final[1] == ["F", lh.F_TEXT] and 1 not in forced
    # forced F records the check the re-asked line failed (here the patient check), not the first-pass one
    assert final[2] == ["F", lh.F_TEXT] and forced[2] == "quote is not from this patient's records"
    # a question the re-ask left out stays a response failure, never a free F
    assert final[3] == [None, ""] and 3 not in forced
    rows = lh.score_session("v", sess, bench["patient_03"], first, final)
    assert rows[2]["failure"] == 1 and rows[2]["correct"] == 0
    assert lh.verify(sess, bench["patient_03"], f'1: B: x | quote: "{quote}"', patient_check=False) == \
        {1: "number not in quote"}


def test_verdicts_are_withheld_for_invalid_or_incomplete_runs():
    ok = {"lo": 0.1, "hi": 0.2}
    tests = {"H1": ok, "H2_s": ok, "H2_clin": ok, "H3_UA": {"lo": -0.3, "hi": -0.1}, "H3_A": ok}
    assert lh.verdicts(tests, {"V1": True, "V6_not_contaminated": True}, True) == {"H1": True, "H2": True, "H3": True}
    assert lh.verdicts(tests, {"V1": False, "V6_not_contaminated": True}, True) is None
    assert lh.verdicts(tests, {"V1": True}, False) is None


def test_score_end_to_end_on_fake_answers(tmp_path, monkeypatch):
    """build -> compact -> locate -> (fake answers for every arm) -> score, with no model call."""
    monkeypatch.setattr(lh, "ROOT", tmp_path)
    monkeypatch.setattr(lh, "BOOT_N", 50)  # the contrasts are degenerate here; speed only
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "unused"))
    bench = _bench(n_texts=5)  # 6 patients x 5 reads still put the early target > 40 messages from the end
    lh.phase_build(bench, "pilot")
    lh.phase_compact(bench, "pilot")
    lh.phase_locate(bench, "pilot")
    good = "\n".join(f"{i}: B: x" for i in range(1, 21))
    for s in lh.sessions(bench, "pilot"):
        text = "\n".join(f"{i}: F: {lh.F_TEXT}" for i in range(1, 21)) if s["condition"] == "unans" else good
        for arm in lh.ARMS:
            if arm != "none":
                lh.wj(tmp_path / "answers" / arm / f"{s['id']}.json",
                      {"ok": True, "text": text, "in_tokens": 10, "out_tokens": 1})
        for k in ("summary_s", "summary_clin"):
            lh.wj(tmp_path / "summaries" / k / f"{s['id']}.json",
                  {"ok": True, "text": "<summary>s</summary>", "in_tokens": 5, "out_tokens": 1})
        lh.wj(tmp_path / "verify" / f"{s['id']}.json", {"catches": {}, "catches_no_patient_check": {},
                                                         "forced": {}, "reask": False, "final": None})
    for t in lh.targets(bench, "pilot"):
        lh.wj(tmp_path / "answers" / "none" / f"{t}.json",
              {"ok": True, "text": "\n".join(f"{i}: A: x" for i in range(1, 21)), "in_tokens": 3, "out_tokens": 1})
    lh.wj(tmp_path / "toolcheck" / "result.json", {"ok": True})
    lh.phase_score(bench, "pilot")
    res = lh.rj(tmp_path / "results-pilot.json")
    assert res["complete"] and not res["dropped"]
    assert res["table"]["full_t"]["A"] == [80, 80] and res["table"]["stashed_v"]["U"] == [40, 40]
    assert all(res["gates"].values()), res["gates"]
    assert res["verdict"] == {"H1": True, "H2": False, "H3": False}  # equal arms: no difference to detect
    assert res["sizes"]["C_prime_tokens"] < res["sizes"]["C_tokens"]
    assert res["sizes"]["cumulative_usage_tokens"]["summary_s"] == 6 * (11 + 6)
    first = lh.sessions(bench, "pilot")[0]["id"]
    # R3 counts failed recall attempts too
    lh.append(tmp_path / "recall-log" / "stashed_t" / f"{first}.jsonl", {"n": 1, "ok": False, "error": "missing"})
    lh.phase_score(bench, "pilot")
    r3 = lh.rj(tmp_path / "results-pilot.json")["secondary"]["S1_recall_behaviour"]["stashed_t"]
    assert r3["R3_calls_per_session"] == 1 / 6 and r3["R3_share_zero"] == 5 / 6
    # a never-run answer leaves the run incomplete (no verdict) and drops nothing
    answer = tmp_path / "answers" / "stashed_0" / f"{first}.json"
    answer.unlink()
    lh.phase_score(bench, "pilot")
    res = lh.rj(tmp_path / "results-pilot.json")
    assert not res["complete"] and res["dropped"] == [] and res["verdict"] is None
    # a terminal infrastructure failure (3 attempts) drops that session from every arm (V2)
    lh.wj(answer, {"ok": False, "attempts": 3, "error": "exit 1"})
    lh.phase_score(bench, "pilot")
    res = lh.rj(tmp_path / "results-pilot.json")
    assert res["complete"] and res["dropped"] == [first] and not res["gates"]["V2"] and res["verdict"] is None
    # consumed usage keeps the dropped session's calls; the cohort total does not
    assert res["sizes"]["cumulative_usage_tokens"]["summary_s"] == 6 * (11 + 6)
    assert res["sizes"]["cumulative_usage_cohort_tokens"]["summary_s"] == 5 * (11 + 6)


def test_reask_replays_the_emitted_recall_text(tmp_path):
    log = tmp_path / "log.jsonl"
    lh.append(log, {"n": 1, "ok": True, "id": "abc123abc123", "lines": None, "text": "head\n[recall truncated at 5]"})
    lh.append(log, {"n": 2, "ok": False, "id": "x", "error": "missing"})
    assert lh.recalled_texts(log) == "[recalled abc123abc123]\nhead\n[recall truncated at 5]"


def test_substring_rule_reads_the_whole_line():
    bench = _bench()
    s = {"target": "patient_03", "condition": "ans_early"}
    wrong_letter = '1: C: 7.7 g/dl | quote: "the value was 10.3 g/dl that day"'
    row = lh.score_session("a", s, bench["patient_03"], wrong_letter)[0]
    assert row["correct"] == 0 and row["substring"] == 1


def test_usage_limit_messages_are_recognised():
    assert lh.LIMIT_RE.search("You've hit your limit · resets 3pm (Europe/London)")
    assert lh.LIMIT_RE.search('{"type":"error","error":{"type":"rate_limit_error"}}')
    assert not lh.LIMIT_RE.search("connection reset by peer")


def _fake_cli(turns: str) -> dict:
    if turns == "2":
        raise lh.InfraError("summary: reply split over 2 turns without tools", 70_100)
    return {"text": "summary", "turns": 1, "in_tokens": 100, "out_tokens": 60_000}


def test_cli_rejects_a_reply_split_over_turns_without_tools(tmp_path, monkeypatch):
    """A fake `claude` on PATH: one turn passes (with the output cap in its env), two turns without tools fail."""
    monkeypatch.setattr(lh, "ROOT", tmp_path)
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\ncat >/dev/null\nprintf '{\"result\": \"cap=%s\", \"num_turns\": %s}' "
                    "\"$CLAUDE_CODE_MAX_OUTPUT_TOKENS\" \"$FAKE_TURNS\"\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_TURNS", "1")
    assert lh.cli("summary", "m", "sys", "p", "high")["text"] == f"cap={lh.MAX_OUTPUT}"
    monkeypatch.setenv("FAKE_TURNS", "2")
    with pytest.raises(lh.InfraError, match="split"):
        lh.cli("summary", "m", "sys", "p", "high")
    assert [r["ok"] for r in lh.jsonl(tmp_path / "calls-done.jsonl")] == [True, False]
    monkeypatch.setenv("LONGHEALTH_PAUSE_AT", "2")
    with pytest.raises(SystemExit, match="pause point 2"):
        lh.cli("summary", "m", "sys", "p", "high")
    assert lh.n_calls() == 2  # the paused call was never counted
    # A split attempt's tokens stay in the arm's cost after the retry succeeds.
    turns = iter(["2", "1"])
    monkeypatch.setattr(lh, "cli", lambda *a: _fake_cli(next(turns)))
    res = lh.cached(tmp_path / "summaries" / "summary_clin" / "s.json", lambda: lh.cli())
    assert res["attempts"] == 2 and res["retry_tokens"] == 70_100
    assert lh.consumed_usage()["summary_clin"] == 70_100 + 60_100
    # A summary gets SUMMARY_ATTEMPTS, two per run: still pending after 4 splits, terminal after the 5th.
    monkeypatch.setattr(lh, "cli", lambda *a: _fake_cli("2"))
    path = tmp_path / "summaries" / "summary_s" / "s.json"
    for want in ("pending", "pending", "terminal"):
        assert lh.cached(path, lambda: lh.cli(), max_attempts=lh.SUMMARY_ATTEMPTS) is None
        assert lh.status_of(path) == want
    assert lh.rj(path)["attempts"] == 5


def test_scoring_metrics_and_bootstrap():
    bench = _bench()
    rows = []
    for t in ("patient_01", "patient_02", "patient_03"):
        for cond in lh.CONDITIONS:
            s = {"target": t, "condition": cond}
            gold = "F" if cond == "unans" else "B"
            rows += lh.score_session("a", s, bench[t], "\n".join(f"{i}: {gold}: x" for i in range(1, 21)))
            rows += lh.score_session("b", s, bench[t], "\n".join(f"{i}: C: x" for i in range(1, 11)))
    assert lh.metric([r for r in rows if r["arm"] == "a"], "A") == (120, 120)
    assert lh.metric([r for r in rows if r["arm"] == "b"], "UA") == (30, 60)
    assert sum(r["failure"] for r in rows if r["arm"] == "b") == 90
    res = lh.bootstrap(rows, "a", "b", "A", n=200)
    assert res["diff"] == 1.0 and res["lo"] == 1.0 and res["clusters"] == 3


def test_recall_shim_returns_exact_bytes_and_caps(tmp_path, monkeypatch):
    from lcc.relevance.transcript_stash import put

    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path))
    monkeypatch.setenv("RECALL_LOG", str(tmp_path / "log.jsonl"))
    monkeypatch.setenv("RECALL_MAX_CALLS", "1")
    digest = put("exact record bytes\nsecond line")
    state = {"calls": 0}
    assert shim.do_recall({"id": digest[:12]}, state) == ("exact record bytes\nsecond line", False)
    assert shim.do_recall({"id": digest[:12]}, state)[1] is True
    assert len((tmp_path / "log.jsonl").read_text().splitlines()) == 2
    monkeypatch.setenv("RECALL_MAX_CALLS", "8")
    for bad in ({"id": digest[:12], "lines": 7}, {"id": 5}, {"id": digest[:12], "lines": "x-y"}):
        text, err = shim.do_recall(bad, state)
        assert err is True and text.startswith("recall failed")
    reply = shim.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "recall", "arguments": {"id": digest[:12], "lines": 7}}}, state)
    assert reply["result"]["isError"] is True  # the server answers and stays up
