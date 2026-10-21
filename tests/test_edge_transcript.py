"""Transcript (tool-call mode) edge cases: malformed, ambiguous and hostile JSON payloads.

Every case is either handled (and the test pins how) or rejected with ``TranscriptError`` and
a message naming the problem. Nothing may crash with another exception or silently lose
content: the invariant ``assert_transcript_invariants`` checks that text is never touched,
pinned messages and their calls survive, kept results are byte-identical and the report's
counters reconcile with the decisions.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from invariants import assert_transcript_invariants
from lcc.relevance.transcript import (
    TranscriptCompactionRequest,
    TranscriptError,
    compact_transcript,
    messages_to_payload,
    parse_transcript,
)
from specialist_synthetic import synthetic_payload

GOAL = "fix the tenant import crash in jobs/tenant_import.py"


class HashJev:
    """Deterministic stand-in for Jev in tool-call mode (scores hash the call id)."""

    model = "hash-jev"
    last_resolved_model = "hash-jev-1"

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        def score(name: str) -> float:
            return int(hashlib.sha256(name.encode()).hexdigest()[:4], 16) / 0xFFFF

        return {"answers": {q: {"noul": score(q), "confidence": 0.9} for q in questions}}


def call(cid: str, tool: str, args: dict[str, Any], output: str, *, error: bool = False):
    result: dict[str, Any] = {"tool_use_id": cid, "text": output}
    if error:
        result["is_error"] = True
    return [
        {"role": "assistant", "text": "", "toolUses": [{"tool_use_id": cid, "tool": tool,
                                                        "input": args}]},
        {"role": "user", "text": "", "toolResults": [result]},
    ]


def filler(n: int, start: int = 0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(start, start + n):
        out += call(f"f{i}", "Bash", {"command": f"echo step {i}"}, f"step {i} ok\n" * 3)
    return out


PROVIDERS: tuple[dict[str, Any], ...] = (
    {"provider": "rules", "rules_mode": "lossless"},
    {"provider": "rules", "rules_mode": "lossy"},
    {"provider": "rules", "rules_mode": "recoverable"},
    {"provider": "rules", "rules_mode": "stashed"},
    {"provider": "auto"},
    {"provider": "jev", "client": HashJev(), "max_workers": 1},
)
PROVIDER_IDS = ["lossless", "lossy", "recoverable", "stashed", "auto", "jev"]


@pytest.fixture(autouse=True)
def _private_stash(tmp_path, monkeypatch):
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))


def run(payload: Any, **options: Any):
    request = TranscriptCompactionRequest(payload=copy.deepcopy(payload), question=GOAL,
                                          **options)
    return compact_transcript(request)


def check_all_providers(payload: list[dict[str, Any]], **extra: Any) -> list[Any]:
    results = []
    for options in PROVIDERS:
        merged = {**options, **extra}
        first = run(payload, **merged)
        assert_transcript_invariants(payload, first, merged)
        second = run(payload, **merged)
        assert messages_to_payload(second.messages) == messages_to_payload(first.messages)
        stable = {k: v for k, v in first.report.items() if k != "latency_ms"}
        assert stable == {k: v for k, v in second.report.items() if k != "latency_ms"}
        results.append(first)
    return results


# --- shape errors: rejected with a clear message ---------------------------------------------


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not a transcript", "must be a list of messages"),
        ({"messages": "nope"}, "must be a list of messages"),
        ([1, 2], "every message must be an object"),
        ([{"text": "no role"}], "has no string 'role'"),
        ([{"role": ""}], "has no string 'role'"),
        ([{"role": "user", "text": 3}], "'text' must be a string"),
        ([{"role": "user", "toolResults": {"a": 1}}], "must be a list"),
        ([{"role": "user", "toolResults": [{"text": "x"}]}], "tool result without an id"),
        ([{"role": "assistant", "toolUses": [{"tool": "Read"}]}], "tool call without an id"),
        ([{"role": "assistant", "toolUses": [{"id": "a", "input": "{\"x\": 1}"}]}],
         "'input' that is not an object"),
        ([{"role": "user", "content": "hello"}], "under 'content'"),
        ([{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
         "unsupported content in 'content'"),
        ([{"role": "user", "text": "see image", "images": [{"source": "b64..."}]}],
         "unsupported content in 'images'"),
        ([{"role": "user", "text": "x", "attachments": [{"name": "a.pdf"}]}],
         "unsupported content in 'attachments'"),
        ([{"role": "user", "toolResults": [{"tool_use_id": "a", "content": [
            {"type": "image", "source": {"data": "..."}}]}]}], "content blocks"),
        ([{"role": "user", "text": json.loads('"bad \\ud800 text"')}], "unpaired surrogate"),
        ([{"role": "assistant", "toolUses": [{"tool_use_id": "a", "tool": "Read",
            "input": {"path": json.loads('"bad \\ud800 path"')}}]}], "unpaired surrogate"),
        # Codex rollout items (no role on function calls) are not a supported shape.
        ([{"type": "function_call", "name": "shell", "arguments": "{}", "call_id": "c1"}],
         "has no string 'role'"),
    ],
)
def test_malformed_payloads_are_rejected_with_a_clear_error(payload: Any, message: str) -> None:
    with pytest.raises(TranscriptError, match=message):
        run(payload, provider="rules")


def test_scalar_metadata_and_timestamps_are_ignored_and_order_is_array_order() -> None:
    payload = [
        {"role": "user", "text": "start", "timestamp": "2026-01-02T00:00:00Z", "uuid": "u1"},
        *filler(3),
        {"role": "assistant", "text": "late", "timestamp": "2025-01-01T00:00:00Z",
         "isSidechain": False, "cost": 0.1},
        {"role": "user", "text": GOAL, "timestamp": "2024-01-01T00:00:00Z"},
    ]
    for result in check_all_providers(payload, preserve_recent=1):
        texts = [m.text for m in result.messages if m.text]
        assert texts == ["start", "late", GOAL]


# --- handled shapes ----------------------------------------------------------------------------


def test_missing_text_and_null_text_are_empty() -> None:
    payload = [{"role": "user"}, {"role": "assistant", "text": None}, *filler(4),
               {"role": "user", "text": GOAL}]
    check_all_providers(payload, preserve_recent=1)


@pytest.mark.parametrize("role", ["system", "tool", "developer", "function", "Human"])
def test_unknown_roles_are_carried_through(role: str) -> None:
    payload = [{"role": "user", "text": "start"}, {"role": role, "text": f"{role} says hi"},
               *filler(6), {"role": role, "text": "late note"}, {"role": "user", "text": GOAL}]
    for result in check_all_providers(payload, preserve_recent=2):
        assert [m.role for m in result.messages if m.text][1] == role


def test_tool_use_without_result_and_orphan_result_are_untouched() -> None:
    payload = [
        {"role": "user", "text": "start"},
        {"role": "assistant", "text": "", "toolUses": [
            {"tool_use_id": "pending1", "tool": "Bash", "input": {"command": "sleep 100"}}]},
        {"role": "user", "text": "", "toolResults": [
            {"tool_use_id": "orphan1", "text": "a result whose call is gone\n" * 50}]},
        *filler(10),
        {"role": "user", "text": GOAL},
    ]
    for result in check_all_providers(payload, preserve_recent=1):
        flat = messages_to_payload(result.messages)
        assert any(u["tool_use_id"] == "pending1" for m in flat for u in m.get("toolUses", []))
        orphan = [r for m in flat for r in m.get("toolResults", []) if r["tool_use_id"] ==
                  "orphan1"]
        assert orphan and orphan[0]["text"] == "a result whose call is gone\n" * 50
        assert all(d["id"] not in ("pending1", "orphan1") for d in result.decisions)


def test_duplicate_ids_never_drop_the_pinned_namesake() -> None:
    payload = [{"role": "user", "text": "start"}]
    payload += call("dup", "Read", {"file_path": "a.py"}, "A = 1\n" * 900)
    payload += call("r2", "Read", {"file_path": "a.py"}, "A = 1\n" * 900)  # supersedes dup
    payload += filler(4)
    payload += call("dup", "Bash", {"command": "pytest -q"}, "1 passed\n")  # pinned namesake
    payload += call("last", "Bash", {"command": "git status"}, "clean\n")
    payload.append({"role": "user", "text": GOAL})
    for result in check_all_providers(payload, preserve_recent=5):
        flat = messages_to_payload(result.messages)
        assert any(u["tool_use_id"] == "dup" and u["tool"] == "Bash"
                   for m in flat for u in m.get("toolUses", []))
        assert any(r["tool_use_id"] == "dup" and r["text"] == "1 passed\n"
                   for m in flat for r in m.get("toolResults", []))
        for d in result.decisions:
            if d["id"] == "dup" and d["source"] != "pin":
                assert d["decision"] == "keep"


def test_interleaved_parallel_tool_calls_pair_by_id() -> None:
    uses = [{"tool_use_id": f"p{i}", "tool": "Read", "input": {"file_path": f"m{i}.py"}}
            for i in range(4)]
    results = [{"tool_use_id": f"p{i}", "text": f"content of m{i}.py\n" * (200 + i)}
               for i in (2, 0, 3, 1)]
    payload = [{"role": "user", "text": "start"},
               {"role": "assistant", "text": "reading four files", "toolUses": uses},
               {"role": "user", "text": "", "toolResults": results},
               *filler(8), {"role": "user", "text": GOAL}]
    parsed = parse_transcript(payload)
    for use in parsed[1].tool_calls:
        assert use.result is not None and use.result.text.startswith(
            f"content of {use.input['file_path']}")
    for result in check_all_providers(payload, preserve_recent=1):
        flat = messages_to_payload(result.messages)
        order = [r["tool_use_id"] for m in flat for r in m.get("toolResults", [])
                 if r["tool_use_id"].startswith("p")]
        assert order == [x for x in ("p2", "p0", "p3", "p1") if x in order]


def test_huge_tool_output_is_handled_in_bounded_time() -> None:
    huge = "".join(f"line {i:07d} of a very large build log\n" for i in range(60_000))  # 2.3 MB
    payload = [{"role": "user", "text": "start"}, *call("big", "Bash", {"command": "make"},
                                                         huge),
               *filler(45), {"role": "user", "text": GOAL}]
    for result in check_all_providers(payload, preserve_recent=1):
        decision = [d for d in result.decisions if d["id"] == "big"][0]
        out = [r for m in result.messages for r in m.tool_results if r.id == "big"]
        if decision["decision"] in ("keep", "trim"):
            assert huge.startswith(out[0].text.split("\n[... lcc:", 1)[0])


def test_non_string_result_text_is_serialized_deterministically() -> None:
    payload = [{"role": "user", "text": "start"},
               {"role": "assistant", "toolUses": [{"id": "j", "tool": "api", "input": {}}]},
               {"role": "user", "toolResults": [{"id": "j", "text": {"b": 2, "a": [1, 2]}}]},
               {"role": "user", "text": GOAL}]
    parsed = parse_transcript(payload)
    assert parsed[2].tool_results[0].text == json.dumps({"b": 2, "a": [1, 2]})


# --- pinned / latest user / newest error at any setting ---------------------------------------


@pytest.mark.parametrize("preserve_recent", [0, 1, 6, 1000])
def test_pins_and_latest_user_message_hold_at_every_window(preserve_recent: int) -> None:
    payload = synthetic_payload(seed=9, turns=8)
    payload += call("err", "Bash", {"command": "python -m jobs.tenant_import"},
                    "Traceback (most recent call last):\nKeyError: 'tenant_id'\nexit code 1",
                    error=True)
    payload += filler(3, start=100)
    payload.append({"role": "user", "text": GOAL})
    for result in check_all_providers(payload, preserve_recent=preserve_recent):
        assert result.messages[-1].text == GOAL
        if result.report["provider_used"] == "rules":
            kept = [r for m in result.messages for r in m.tool_results if r.id == "err"]
            assert kept and "KeyError" in kept[0].text  # latest_error_result


def test_preserve_recent_covering_everything_means_no_candidates() -> None:
    payload = [{"role": "user", "text": "start"}, *filler(3), {"role": "user", "text": GOAL}]
    for result in check_all_providers(payload, preserve_recent=1000):
        assert result.report["degradation_reason"] == "no_candidates"
        assert messages_to_payload(result.messages) == messages_to_payload(
            parse_transcript(payload))


def test_empty_transcript_is_handled() -> None:
    for options in PROVIDERS:
        result = run([], **options)
        assert result.messages == []
        assert result.report["chars_before"] == result.report["chars_after"] == 0
        assert result.report["worth_it"] is False


# --- supersession, re-reads, old root causes (rules policy) -----------------------------------


def _decision(result: Any, cid: str) -> dict[str, Any]:
    return next(d for d in result.decisions if d["id"] == cid and d["source"] != "pin")


def _session(*calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = [{"role": "user", "text": "start"}]
    for c in calls:
        payload += c
    payload += filler(4, start=500)
    payload.append({"role": "user", "text": "continue please"})
    return payload


def test_later_whole_read_supersedes_an_earlier_read() -> None:
    payload = _session(call("r1", "Read", {"file_path": "/r/a.py"}, "v1\n" * 400),
                       call("r2", "Read", {"file_path": "/r/a.py"}, "v2\n" * 400))
    result = run(payload, provider="rules", rules_mode="lossy", preserve_recent=1)
    assert _decision(result, "r1")["reason"] == "superseded_by_later_call:r2"


def test_partial_later_read_does_not_supersede_a_whole_read_after_an_edit() -> None:
    payload = _session(
        call("r1", "Read", {"file_path": "/r/a.py"}, "v1\n" * 400),
        call("e1", "Edit", {"file_path": "/r/a.py", "old_string": "v1", "new_string": "v2"},
             "edited"),
        call("r2", "Read", {"file_path": "/r/a.py", "offset": 10, "limit": 5}, "v2\n" * 5),
    )
    result = run(payload, provider="rules", rules_mode="lossy", preserve_recent=1)
    assert not _decision(result, "r1")["reason"].startswith("superseded")


def test_re_reads_of_different_ranges_do_not_supersede_each_other() -> None:
    payload = _session(
        call("r1", "Read", {"file_path": "/r/a.py", "offset": 0, "limit": 50}, "a\n" * 50),
        call("r2", "Read", {"file_path": "/r/a.py", "offset": 100, "limit": 50}, "b\n" * 50),
    )
    result = run(payload, provider="rules", rules_mode="lossy", preserve_recent=1)
    for cid in ("r1", "r2"):
        assert not _decision(result, cid)["reason"].startswith("superseded")


def test_a_failed_later_read_supersedes_nothing() -> None:
    payload = _session(call("r1", "Read", {"file_path": "/r/a.py"}, "v1\n" * 400),
                       call("r2", "Read", {"file_path": "/r/a.py"}, "EACCES", error=True))
    result = run(payload, provider="rules", rules_mode="lossy", preserve_recent=1)
    assert not _decision(result, "r1")["reason"].startswith("superseded")


def test_an_error_fixed_later_is_not_superseded_by_the_passing_rerun() -> None:
    failing = "FAILED tests/test_import.py::test_tenant - KeyError: 'tenant_id'\n1 failed"
    payload = _session(call("t1", "Bash", {"command": "pytest -q"}, failing),
                       call("t2", "Bash", {"command": "pytest -q"}, "1 passed"))
    result = run(payload, provider="rules", rules_mode="lossy", preserve_recent=1)
    assert _decision(result, "t1")["decision"] == "keep"  # old root cause stays readable


def test_identical_rerun_is_superseded() -> None:
    payload = _session(call("t1", "Bash", {"command": "ls src"}, "a.py\nb.py\n" * 50),
                       call("t2", "Bash", {"command": "ls src"}, "a.py\nb.py\n" * 50))
    result = run(payload, provider="rules", rules_mode="lossy", preserve_recent=1)
    assert _decision(result, "t1")["reason"] == "superseded_by_later_call:t2"


def test_reduction_gate_below_25_percent_is_reported_not_enforced() -> None:
    payload = _session(call("r1", "Read", {"file_path": "/r/a.py"}, "v1\n" * 30),
                       call("r2", "Read", {"file_path": "/r/a.py"}, "v2\n" * 30))
    result = run(payload, provider="rules", rules_mode="lossy", preserve_recent=1)
    assert 0 < result.report["reduction_ratio"] < 0.25
    assert result.report["worth_it"] is False
    assert _decision(result, "r1")["decision"] == "drop"  # the gate labels, never reverts
