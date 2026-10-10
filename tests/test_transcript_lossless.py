"""provider="rules", rules_mode="lossless" (the default): removals that are provably lossless.

A result may only be replaced by a pointer note when its whole non-volatile text survives,
line for line and in order, inside a later result that is kept unchanged. The verifier checks
that mechanically, so no judge is needed to trust the output.
"""

from __future__ import annotations

import copy

import pytest

import lcc.relevance.transcript as transcript_module
from lcc.relevance.transcript import (
    TranscriptCompactionRequest,
    compact_transcript,
    messages_to_payload,
    verify_lossless,
)

BODY = "\n".join(f"{n:>6}\tline {n} of the parser" for n in range(1, 40))


@pytest.fixture(autouse=True)
def _no_judge(monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")

    def refuse(*_args, **_kwargs):
        raise AssertionError("provider='rules' must never resolve a judge")

    monkeypatch.setattr(transcript_module, "_resolve_client", refuse)


def convo(*calls: tuple[str, dict, str]) -> list[dict]:
    messages: list[dict] = [{"role": "user", "text": "fix the parser"}]
    for n, (tool, tool_input, output) in enumerate(calls, start=1):
        messages.append(
            {"role": "assistant", "text": f"step {n}",
             "toolUses": [{"id": f"c{n}", "tool": tool, "input": tool_input}]}
        )
        messages.append({"role": "user", "text": "", "toolResults": [{"id": f"c{n}", "text": output}]})
    messages.append({"role": "assistant", "text": "done"})
    return messages


def run(messages: list[dict], **kwargs):
    original = copy.deepcopy(messages)
    result = compact_transcript(
        TranscriptCompactionRequest(
            payload={"messages": messages}, question="fix the parser", provider="rules",
            preserve_recent=1, **kwargs,
        )
    )
    assert messages == original, "the input payload must not be mutated"
    compacted = messages_to_payload(result.messages)
    return result, compacted, {d["id"]: d for d in result.decisions}


def result_text(payload: list[dict], call_id: str) -> str:
    for message in payload:
        for item in message.get("toolResults", []):
            if item["tool_use_id"] == call_id:
                return item["text"]
    raise KeyError(call_id)


def test_lossless_is_the_default_rules_mode():
    messages = convo(("Bash", {"command": "pytest"}, BODY), ("Bash", {"command": "pytest"}, BODY))
    result, compacted, d = run(messages)
    assert result.report["rules_mode"] == "lossless"
    assert result.report["semantic_guarantee"] == "lossless"
    assert d["c1"]["decision"] == "dedupe"


def test_identical_rerun_is_replaced_by_a_pointer_and_verifies():
    messages = convo(("Bash", {"command": "pytest"}, BODY), ("Bash", {"command": "pytest"}, BODY))
    result, compacted, d = run(messages)
    assert d["c1"]["decision"] == "dedupe"
    assert d["c1"]["kept_at"] == "c2"
    assert result_text(compacted, "c1") == "[identical output kept at c2]"
    assert result_text(compacted, "c2") == BODY
    # the call itself (input) and every text stay
    assert compacted[1]["toolUses"][0]["input"] == {"command": "pytest"}
    assert [m["text"] for m in compacted] == [m["text"] for m in messages]
    assert result.report["tool_calls_deduped"] == 1
    assert verify_lossless({"messages": messages}, compacted) == []


def test_differing_rerun_is_kept():
    messages = convo(
        ("Bash", {"command": "pytest"}, BODY + "\n1 failed"),
        ("Bash", {"command": "pytest"}, BODY + "\n1 passed"),
    )
    _result, compacted, d = run(messages)
    assert d["c1"]["decision"] == "keep"
    assert result_text(compacted, "c1") == BODY + "\n1 failed"


def test_partial_read_is_not_used_as_superseder():
    partial = "\n".join(BODY.splitlines()[:10])
    messages = convo(
        ("Read", {"file_path": "p.py"}, BODY),
        ("Read", {"file_path": "p.py", "offset": 1, "limit": 10}, partial),
    )
    _result, _compacted, d = run(messages)
    assert d["c1"]["decision"] == "keep"


def test_earlier_output_contained_in_a_later_one_is_deduped():
    partial = "\n".join(BODY.splitlines()[5:20])
    messages = convo(
        ("Read", {"file_path": "p.py", "offset": 6, "limit": 15}, partial),
        ("Read", {"file_path": "p.py"}, BODY),
    )
    _result, compacted, d = run(messages)
    assert d["c1"]["decision"] == "dedupe"
    assert result_text(compacted, "c1") == "[output = lines 6-20 of c2]"
    assert verify_lossless({"messages": messages}, compacted) == []


def test_contained_pointer_names_the_exact_lines_so_it_can_be_reversed():
    # prod returned X, a later read of another file returned X+Y: the note must say which.
    x = "\n".join(f"10.0.0.{n} prod-{n}" for n in range(1, 8))
    y = "\n".join(f"10.1.0.{n} dev-{n}" for n in range(1, 8))
    messages = convo(
        ("Read", {"file_path": "prod.hosts"}, x),
        ("Read", {"file_path": "dev.hosts"}, x + "\n" + y),
    )
    _result, compacted, d = run(messages)
    assert result_text(compacted, "c1") == "[output = lines 1-7 of c2]"
    kept = result_text(compacted, "c2").split("\n")
    assert "\n".join(kept[0:7]) == x
    assert verify_lossless({"messages": messages}, compacted) == []

    # a pointer with the wrong range, or the old range-less form, is a violation
    for bad in ("[output = lines 8-14 of c2]", "[output contained in c2]",
                "[output = lines 1-6 of c2]"):
        forged = copy.deepcopy(messages)
        forged[2]["toolResults"][0]["text"] = bad
        assert any("c1" in v for v in verify_lossless({"messages": messages}, forged)), bad


def test_identical_pointer_must_really_be_identical():
    partial = "\n".join(BODY.splitlines()[5:20])
    messages = convo(("Read", {"file_path": "p.py"}, partial), ("Read", {"file_path": "p.py"}, BODY))
    forged = copy.deepcopy(messages)
    forged[2]["toolResults"][0]["text"] = "[identical output kept at c2]"
    assert any("c1" in v for v in verify_lossless({"messages": messages}, forged))


def test_mid_line_substring_is_not_a_match():
    messages = convo(
        ("Bash", {"command": "echo"}, "ok " * 20),
        ("Bash", {"command": "cat"}, "not ok " * 20 + "\nmore"),
    )
    _result, _compacted, d = run(messages)
    assert d["c1"]["decision"] == "keep"


def test_chained_duplicates_resolve_to_the_last_kept_copy():
    cmd = {"command": "git status"}
    messages = convo(("Bash", cmd, BODY), ("Bash", cmd, BODY), ("Bash", cmd, BODY))
    _result, compacted, d = run(messages)
    assert d["c1"]["kept_at"] == "c3"
    assert d["c2"]["kept_at"] == "c3"
    assert d["c3"]["decision"] == "keep"
    assert verify_lossless({"messages": messages}, compacted) == []


def test_codex_volatile_header_lines_are_ignored_but_exit_code_is_not():
    def codex(wall: str, code: int) -> str:
        return (
            f"Chunk ID: {wall}x\nWall time: {wall} seconds\nProcess exited with code {code}\n"
            f"Original token count: 99\nOutput:\n{BODY}"
        )

    same = convo(("exec_command", {"cmd": "ls"}, codex("0.1", 0)),
                 ("exec_command", {"cmd": "ls"}, codex("0.2", 0)))
    _r, compacted, d = run(same)
    assert d["c1"]["decision"] == "dedupe"
    assert verify_lossless({"messages": same}, compacted) == []

    differ = convo(("exec_command", {"cmd": "ls"}, codex("0.1", 1)),
                   ("exec_command", {"cmd": "ls"}, codex("0.2", 0)))
    _r, _c, d = run(differ)
    assert d["c1"]["decision"] == "keep"


def test_volatile_looking_line_in_the_body_is_not_ignored():
    messages = convo(
        ("Read", {"file_path": "a.txt"}, BODY + "\nWall time: 3"),
        ("Read", {"file_path": "a.txt"}, BODY + "\nWall time: 4"),
    )
    _r, _c, d = run(messages)
    assert d["c1"]["decision"] == "keep"


def test_error_flag_must_match():
    messages = convo(("Bash", {"command": "make"}, BODY), ("Bash", {"command": "make"}, BODY))
    messages[2]["toolResults"][0]["is_error"] = True
    _r, _c, d = run(messages)
    assert d["c1"]["decision"] == "keep"


def test_lossy_mode_is_still_available():
    messages = convo(("Bash", {"command": "pytest"}, BODY), ("Bash", {"command": "pytest"}, BODY))
    result, _c, d = run(messages, rules_mode="lossy")
    assert result.report["rules_mode"] == "lossy"
    assert d["c1"]["decision"] == "drop"


def test_unknown_rules_mode_is_refused():
    with pytest.raises(transcript_module.TranscriptError):
        run(convo(), rules_mode="maybe")


def test_verifier_catches_hand_made_violations():
    messages = convo(
        ("Bash", {"command": "pytest"}, BODY + "\n1 failed"),
        ("Bash", {"command": "pytest"}, BODY + "\n1 passed"),
    )
    original = {"messages": messages}

    dropped = copy.deepcopy(messages)
    dropped[2]["toolResults"][0]["text"] = "[identical output kept at c2]"
    assert any("c1" in v for v in verify_lossless(original, dropped))

    edited_text = copy.deepcopy(messages)
    edited_text[1]["text"] = "rewritten"
    assert verify_lossless(original, edited_text)

    edited_input = copy.deepcopy(messages)
    edited_input[1]["toolUses"][0]["input"] = {"command": "pytest -x"}
    assert verify_lossless(original, edited_input)

    removed = copy.deepcopy(messages)
    del removed[2]
    assert verify_lossless(original, removed)

    # chaining onto a result that was itself changed is not lossless either
    same = convo(("Bash", {"command": "x"}, BODY), ("Bash", {"command": "x"}, BODY))
    chained = copy.deepcopy(same)
    chained[2]["toolResults"][0]["text"] = "[identical output kept at c2]"
    chained[4]["toolResults"][0]["text"] = "[identical output kept at c1]"
    assert verify_lossless({"messages": same}, chained)


def test_a_policy_bug_is_caught_by_the_runtime_verifier(monkeypatch):
    messages = convo(
        ("Bash", {"command": "pytest"}, BODY + "\n1 failed"),
        ("Bash", {"command": "pytest"}, BODY + "\n1 passed"),
    )
    real = transcript_module.lossless_decisions

    def buggy(msgs, candidates):
        out = real(msgs, candidates)
        out[0] = out[0] | {"decision": "dedupe", "kept_at": "c2", "note": "[bogus]"}
        return out

    monkeypatch.setattr(transcript_module, "lossless_decisions", buggy)
    result, compacted, d = run(messages)
    assert result.report["degraded"] is True
    assert result.report["lossless_violations"]
    assert result.report["semantic_guarantee"] == "none"
    assert d["c1"]["decision"] == "keep"
    assert compacted == transcript_module.messages_to_payload(
        transcript_module.parse_transcript({"messages": messages})
    )


def test_empty_messages_do_not_trip_the_verifier():
    messages = convo(("Bash", {"command": "pytest"}, BODY), ("Bash", {"command": "pytest"}, BODY))
    messages.insert(3, {"role": "assistant", "text": ""})
    result, compacted, d = run(messages)
    assert d["c1"]["decision"] == "dedupe"
    assert result.report["lossless_violations"] == []
    assert result.report["degraded"] is False
