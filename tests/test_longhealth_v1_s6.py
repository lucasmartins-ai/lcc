"""LongHealth v1 S6 driver (PROTOCOL.md Amendment 5): frozen files, prompt parity with the frozen arms, the Codex
call path against a fake `codex` on PATH, and scoring. No LongHealth data and no model call is used here."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "longhealth-v1"
FROZEN = {"longhealth_v1.py": "44384a17fda811429d88be532e1571cfe02351d6ca9d315cc1327c5f8f3e3efb",
          "recall_shim.py": "110c8416760fcbd5c51afc7f2a27723898afef7f60d8799bfcb92c3601604443"}

_spec = importlib.util.spec_from_file_location("s6_codex", HERE / "s6_codex.py")
s6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s6)
lh = s6.lh


def _bench(n_patients: int = 9, n_texts: int = 5) -> dict:
    bench = {}
    for p in range(n_patients):
        name = f"Name{p} Surname{p}"
        texts = {f"text_{j}": (f"Discharge letter for {name}. Visit {j}. Haemoglobin {10 + j}.{p} g/dl measured "
                               f"on day {j + 1} of the stay. ") * 8 for j in range(n_texts)}
        questions = [{"question": f"Question {q} about visit {q % n_texts}?", "answer_a": "none of these",
                      "answer_b": f"{10 + q % n_texts}.{p} g/dl", "answer_c": "7.7 g/dl", "answer_d": "unknown",
                      "answer_e": "a different visit", "correct": f"{10 + q % n_texts}.{p} g/dl",
                      "answer_location": {f"text_{q % n_texts}": {"start": [0.1], "end": [0.2]}}} for q in range(20)]
        bench[f"patient_{p:02d}"] = {"texts": texts, "name": name, "birthday": f"0{p % 9 + 1}.01.1960",
                                     "diagnosis": "x", "questions": questions}
    return bench


def _pilot(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr(lh, "ROOT", tmp_path)
    monkeypatch.setattr(lh, "BOOT_N", 50)
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "unused"))
    bench = _bench()
    lh.phase_build(bench, "pilot")
    lh.phase_compact(bench, "pilot")
    lh.phase_locate(bench, "pilot")
    return bench


def test_frozen_harness_files_are_unchanged():
    for name, sha in FROZEN.items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == sha, name


def test_prompt_and_stash_match_the_frozen_tool_arms(tmp_path, monkeypatch):
    bench = _pilot(tmp_path, monkeypatch)
    seen = {}

    def fake_cli(role, model, system, prompt, effort, tool=None):
        seen[(role, prompt)] = (system, tool[0])
        return {"text": "1: F: x", "in_tokens": 1, "out_tokens": 1}

    monkeypatch.setattr(lh, "cli", fake_cli)
    for arm in s6.ARMS:
        lh.phase_run(bench, "pilot", arm)
        for s in lh.sessions(bench, "pilot"):
            prompt, stash = s6.prompt_of(s, arm)
            assert seen[(arm, prompt)] == (lh.SYSTEM_TOOL, stash)


def test_argv_isolates_the_answerer(tmp_path):
    argv = s6.argv_for(tmp_path / "system.txt", tmp_path, tmp_path / "stash", tmp_path / "log.jsonl")
    assert argv[:2] == ["codex", "exec"] and argv[-1] == "-"
    for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--json"):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only" and argv[argv.index("-m") + 1] == s6.MODEL
    assert {argv[i + 1] for i, a in enumerate(argv) if a == "--disable"} == set(s6.OFF)
    conf = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert 'mcp_servers.stash.tools.recall.approval_mode="approve"' in conf
    assert f"mcp_servers.stash.args={json.dumps([str(lh.SHIM)])}" in conf
    env = next(c for c in conf if c.startswith("mcp_servers.stash.env="))
    assert f'RECALL_LOG = {json.dumps(str(tmp_path / "log.jsonl"))}' in env
    assert f'LCC_STASH_DIR = {json.dumps(str(tmp_path / "stash"))}' in env
    assert not any("dangerously" in a for a in argv)


FAKE = r'''#!{python}
import json, os, sys
a = sys.argv[1:]
if a == ["--version"]:
    print("codex-cli 0.166.0")
    sys.exit()
if a[0] == "app-server":
    pct = os.environ["FAKE_PCT"]
    for line in sys.stdin:
        if json.loads(line).get("id") == 2:
            used = None if pct == "none" else int(pct)
            print(json.dumps({"id": 2, "result": {"rateLimits": {"primary": {"usedPercent": used},
                                                                 "secondary": {"usedPercent": 5}}}}), flush=True)
            break
    sys.exit()
prompt = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": a, "home": os.environ.get("HOME"), "codex_home": os.environ.get("CODEX_HOME"),
                        "leaked": sorted(k for k in os.environ if k.startswith(("OPENAI_", "ANTHROPIC_"))),
                        "prompt": prompt}) + "\n")
mode = os.environ["FAKE_MODE"]
out = lambda e: print(json.dumps(e))
if mode == "noturn":
    sys.exit(1)
out({"type": "thread.started"})
out({"type": "turn.started"})
if mode == "shell":
    out({"type": "item.completed", "item": {"type": "command_execution", "command": "cat gold"}})
if mode == "hang":  # starts a denied item, then outlives the driver's timeout before completing it
    out({"type": "item.started", "item": {"type": "command_execution", "command": "cat gold"}})
    sys.stdout.flush()
    import time
    time.sleep(10)
if mode == "nomsg":
    out({"type": "turn.failed"})
    sys.exit(1)
out({"type": "item.completed", "item": {"type": "mcp_tool_call", "tool": "recall"}})
if mode in ("ok", "shell"):
    out({"type": "item.completed", "item": {"type": "agent_message", "text": "1: B: x"}})
    out({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 7}})
    sys.exit()
msg = {"limit": "You've hit your usage limit", "transport": "stream disconnected before completion",
       "refusal": "cyber policy: This request has been flagged for possible cybersecurity risk.",
       "unauthorized": "401 Unauthorized"}[mode]
out({"type": "turn.failed", "error": {"message": msg}})
sys.exit(1)
'''


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(lh, "ROOT", tmp_path / "root")
    main = tmp_path / "main-codex"
    main.mkdir()
    (main / "auth.json").write_text("{}")
    monkeypatch.setattr(s6, "MAIN_CODEX_HOME", main)
    s6.check_version.cache_clear()
    exe = tmp_path / "bin" / "codex"
    exe.parent.mkdir()
    exe.write_text(FAKE.replace("{python}", sys.executable))
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{exe.parent}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "fake.jsonl"))
    monkeypatch.setenv("FAKE_PCT", "10")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-codex")
    yield tmp_path
    s6.check_version.cache_clear()


def _call(monkeypatch, mode):
    monkeypatch.setenv("FAKE_MODE", mode)
    return s6.codex_call("s6", "the prompt", (Path("/stash"), Path("/log.jsonl")))


def test_codex_call_outcomes_ledger_and_plan_window(fake_codex, monkeypatch):
    res = _call(monkeypatch, "ok")
    assert res["text"] == "1: B: x" and res["refusal"] is None
    assert res["in_tokens"] == 100 and res["usage"]["cached_input_tokens"] == 60
    assert res["kinds"] == {"mcp_tool_call": 1, "agent_message": 1}
    seen = lh.jsonl(fake_codex / "fake.jsonl")[0]
    assert seen["prompt"] == "the prompt" and seen["leaked"] == []
    assert seen["codex_home"] == str(s6.s6dir("codex-home")) and seen["home"] == str(s6.s6dir("home"))
    assert (s6.s6dir("codex-home") / "auth.json").resolve() == (fake_codex / "main-codex" / "auth.json").resolve()
    assert _call(monkeypatch, "refusal")["refusal"].startswith("cyber policy: ")
    for mode in ("transport", "noturn", "unauthorized", "nomsg"):  # only a stated refusal is scored; these retry
        with pytest.raises(lh.InfraError):
            _call(monkeypatch, mode)
    with pytest.raises(lh.LimitHit):
        _call(monkeypatch, "limit")
    with pytest.raises(SystemExit, match="isolation broke"):
        _call(monkeypatch, "shell")
    monkeypatch.setattr(lh, "TIMEOUT_S", -59)  # a 1 s timeout: what streamed before the kill is still checked
    with pytest.raises(SystemExit, match="isolation broke"):
        _call(monkeypatch, "hang")
    assert "command_execution" in (s6.s6dir("events") / "0009.jsonl").read_text()
    done = lh.jsonl(s6.s6dir("calls-done.jsonl"))
    assert [d["outcome"] for d in done] == ["ok", "refusal"] + ["InfraError"] * 4 + ["LimitHit", "stopped", "stopped"]
    assert done[0]["plan_before"] == {"primary": 10, "secondary": 5} == done[0]["plan_after"]
    assert done[2]["kinds"] == {"mcp_tool_call": 1}  # a retried attempt keeps its item kinds
    assert len(lh.jsonl(s6.s6dir("calls.jsonl"))) == 9
    # pacing: no call starts at or above the pause point, or when the windows cannot be read; neither is counted
    monkeypatch.setenv("FAKE_PCT", str(s6.PAUSE_AT))
    with pytest.raises(SystemExit, match="pause at"):
        _call(monkeypatch, "ok")
    monkeypatch.setenv("FAKE_PCT", "none")
    with pytest.raises(SystemExit, match="cannot read"):
        _call(monkeypatch, "ok")
    assert len(lh.jsonl(s6.s6dir("calls.jsonl"))) == 9
    monkeypatch.setenv("FAKE_PCT", "10")
    monkeypatch.setattr(s6, "S6_CAP", 9)
    with pytest.raises(SystemExit, match="cap 9"):
        _call(monkeypatch, "ok")


def test_only_the_cli_refusal_errors_are_refusals():
    def failed(message):
        return [{"type": "turn.started"}, {"type": "turn.failed", "error": {"message": message}}]

    for m in ("cyber policy: This request has been flagged for possible cybersecurity risk.",
              "bio policy: This content was flagged for possible biological risk.",
              "invalid prompt: your prompt was flagged as potentially violating our usage policy",
              "misalignment policy violation",
              # the provider's invalid_prompt text, as the CLI may pass it on without its own prefix
              "Your prompt was flagged as potentially violating our usage policy. Please try again.",
              "Invalid prompt: we've limited access to this content for safety reasons.",
              "stream disconnected before completion: Incomplete response returned, reason: content_filter"):
        assert s6.parse_events(failed(m), 1, "")["refusal"] == m
    # failures that only hold refusal-like words are infrastructure: retried, never scored as a refusal
    for m in ("This request was blocked by the content policy", "safety service unavailable, try again",
              "the request was flagged by an upstream classifier", "error echoing input: cyber attack refused",
              "Incomplete response returned, reason: max_output_tokens"):
        with pytest.raises(lh.InfraError):
            s6.parse_events(failed(m), 1, "")


def test_auth_link_guard(fake_codex):
    home = s6.codex_home()
    link = home / "auth.json"
    link.unlink()
    link.write_text("{}")  # what a token refresh that replaced the link would leave
    with pytest.raises(SystemExit, match="Codex replaced it"):
        s6.codex_home()


def test_version_pin(fake_codex, monkeypatch):
    monkeypatch.setattr(s6, "CODEX_VERSION", "codex-cli 9.9.9")
    with pytest.raises(SystemExit, match="pinned"):
        s6.check_version()


def _answer(text: str, refusal: str | None = None) -> dict:
    return {"ok": True, "attempts": 1, "text": text, "refusal": refusal, "in_tokens": 10, "out_tokens": 1,
            "usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 1},
            "kinds": {"mcp_tool_call": 2, "agent_message": 1}, "retry_tokens": 0, "max_attempts": 3}


def test_score_end_to_end_on_fake_answers(tmp_path, monkeypatch):
    bench = _pilot(tmp_path, monkeypatch)
    every = [s["id"] for s in lh.sessions(bench, "pilot")]
    lh.wj(tmp_path / "results-pilot.json", {"dropped": [every[-1]]})  # D's drops stay out of S6
    good = "\n".join(f"{i}: B: x" for i in range(1, 21))
    unans = "\n".join(f"{i}: F: {lh.F_TEXT}" for i in range(1, 21))
    for s in lh.sessions(bench, "pilot"):
        for arm in s6.ARMS:
            text = unans if s["condition"] == "unans" else good
            refused = arm == "stashed_t" and s["id"] == every[0]
            lh.wj(s6.s6dir("answers", arm, f"{s['id']}.json"), _answer("" if refused else text, "blocked" * refused))
    lh.append(s6.s6dir("recall-log", "stashed_t", f"{every[1]}.jsonl"), {"n": 1, "ok": False, "error": "missing"})
    lh.wj(s6.s6dir("toolcheck", "result.json"), {"ok": True})
    s6.phase_score(bench, "pilot", None)
    assert tmp_path == lh.ROOT  # restored after reading S6's recall logs
    res = lh.rj(s6.s6dir("results-pilot.json"))
    assert res["complete"] and res["dropped"] == [] and res["refusals"] == {"stashed_t": [every[0]]}
    assert res["table"]["full_t"]["A"] == [80, 80] and res["table"]["stashed_t"]["A"] == [60, 80]
    assert res["response_failures"]["stashed_t"][lh.sessions(bench, "pilot")[0]["condition"]] == 20
    assert res["usage_cohort"]["full_t"]["cached_input_tokens"] == 5 * 4
    assert res["item_kinds_cohort"]["stashed_t"]["mcp_tool_call"] == 10
    lh.append(s6.s6dir("calls-done.jsonl"), {"n": 1, "outcome": "InfraError", "kinds": {"collab_tool_call": 1}})
    s6.phase_score(bench, "pilot", None)  # a retried attempt's items still reach the audit
    res = lh.rj(s6.s6dir("results-pilot.json"))
    assert res["item_kinds_every_call"] == {"collab_tool_call": 1} and res["calls"]["outcomes"] == {"InfraError": 1}
    assert res["recall_behaviour"]["stashed_t"]["R3_calls_per_session"] == 1 / 5
    assert res["gates"]["V1"] and res["gates"]["V4"] and not res["gates"]["V5"]  # a refusal is 20 unparsed lines
    assert not res["valid"] and "verdict" not in res
    assert res["contrast_stashed_t_minus_full_t"]["A"]["diff"] < 0
    # a subset is scored to its own file and never overwrites the whole set's
    s6.phase_score(bench, "pilot", [every[1]])
    assert lh.rj(s6.s6dir("results-pilot-subset.json"))["subset"] == [every[1]]
    assert lh.rj(s6.s6dir("results-pilot.json"))["refusals"] == {"stashed_t": [every[0]]}
    # a never-run answer leaves S6 incomplete; once the S6 cap is spent it is dropped instead
    (s6.s6dir("answers", "full_t", f"{every[2]}.json")).unlink()
    s6.phase_score(bench, "pilot", None)
    assert not lh.rj(s6.s6dir("results-pilot.json"))["complete"]
    monkeypatch.setattr(s6, "S6_CAP", 0)
    s6.phase_score(bench, "pilot", None)
    res = lh.rj(s6.s6dir("results-pilot.json"))
    assert res["complete"] and res["dropped"] == [every[2]] and not res["gates"]["V2"]


def test_run_waits_for_approval_and_for_the_scored_d_run(tmp_path, monkeypatch):
    monkeypatch.setattr(lh, "ROOT", tmp_path)
    assert s6.APPROVED is None  # the commit that records the owner's approval sets it
    with pytest.raises(SystemExit, match="not approved"):
        s6.main(["run", "--set", "D", "--arm", "full_t"])
    with pytest.raises(SystemExit, match="results-D.json is missing"):
        s6.d_dropped("D")
    # once approved, the pilot is the 2 pre-registered sessions only, and D still waits for the pilot gate
    monkeypatch.setattr(s6, "APPROVED", "2026-11-07")
    with pytest.raises(SystemExit, match="the S6 pilot is"):
        s6.main(["run", "--set", "pilot", "--arm", "full_t", "--only", "patient_03__ans_late"])
    good = "\n".join(f"{i}: B: x" for i in range(1, 21))
    for sid in s6.PILOT:
        lh.wj(s6.s6dir("answers", "full_t", f"{sid}.json"), _answer(good))
        lh.wj(s6.s6dir("answers", "stashed_t", f"{sid}.json"), _answer("1: B: x"))
    with pytest.raises(SystemExit, match="pilot gate"):
        s6.main(["run", "--set", "D", "--arm", "full_t"])
    no_v4 = ["V4: the S6 toolcheck has not passed"]
    assert s6.pilot_failures() == no_v4 + [f"stashed_t/{sid}: {why}" for sid in s6.PILOT
                                           for why in ("under 95 % of lines parsed", "no recall returned text")]
    for sid in s6.PILOT:
        lh.wj(s6.s6dir("answers", "stashed_t", f"{sid}.json"), _answer(good))
        lh.append(s6.s6dir("recall-log", "stashed_t", f"{sid}.jsonl"), {"n": 1, "ok": True})
    # a good pilot still waits for V4: the toolcheck missing, then failed
    assert s6.pilot_failures() == no_v4
    lh.wj(s6.s6dir("toolcheck", "result.json"), {"ok": False})
    with pytest.raises(SystemExit, match="V4: the S6 toolcheck has not passed"):
        s6.main(["run", "--set", "D", "--arm", "full_t"])
    lh.wj(s6.s6dir("toolcheck", "result.json"), {"ok": True})
    assert s6.pilot_failures() == []
    lh.wj(s6.s6dir("answers", "full_t", f"{s6.PILOT[0]}.json"), _answer("", "refused by the classifier"))
    assert s6.pilot_failures() == [f"full_t/{s6.PILOT[0]}: refused"]
