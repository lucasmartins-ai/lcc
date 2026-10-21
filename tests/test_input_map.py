"""`lcc measure-session --input-map`: billed input by category, golden numbers on synthetic
sessions. Tokens are counted as whitespace-separated words so every figure is hand-checkable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc import input_map as imap
from lcc.cli import app

MARKER = "PRIVATE-7373"


@pytest.fixture(autouse=True)
def _word_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imap, "_tokens", lambda text: len(text.split()) if text else 0)


def _write(tmp_path: Path, rows: list[dict], name: str = "s.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _assistant(request_id: str, blocks: list[dict], usage: dict | None = None) -> dict:
    message: dict = {"role": "assistant", "content": blocks}
    if usage is not None:
        message["usage"] = usage
    return {"type": "assistant", "requestId": request_id, "message": message}


def _result(tool_id: str, text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": text}]}}


def _read(tool_id: str) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": "Read",
            "input": {"file_path": f"/{MARKER}/a.py"}}


def _claude_session(tmp_path: Path) -> Path:
    usage_1 = {"input_tokens": 10, "cache_creation_input_tokens": 100,
               "cache_read_input_tokens": 0, "output_tokens": 5,
               "output_tokens_details": {"thinking_tokens": 2}}
    usage_2 = {"input_tokens": 0, "cache_creation_input_tokens": 10,
               "cache_read_input_tokens": 110, "output_tokens": 0}
    return _write(tmp_path, [
        {"type": "attachment", "attachment": {"type": "prompt_snapshot",
                                              "systemPrompt": "you are an agent"}},
        {"type": "user", "message": {"role": "user", "content": f"fix {MARKER} bug"}},
        _assistant("r1", [{"type": "thinking", "thinking": "not counted here"},
                          {"type": "text", "text": "ok"}, _read("t1")], usage_1),
        _result("t1", f"l1 l2 l3 {MARKER}"),
        {"type": "attachment", "attachment": {"type": "skill_listing", "content": "s1 s2"}},
        {"type": "attachment", "attachment": {"type": "deferred_tools_record",
                                              "entries": ["never", "sent"]}},
        # one request split over two lines, as Claude Code writes it: counted once
        _assistant("r2", [{"type": "text", "text": "hmm"}], usage_2),
        _assistant("r2", [_read("t2")], usage_2),
        _result("t2", f"l1 l2 l3 {MARKER}"),
        {"type": "user", "isSidechain": True,
         "message": {"role": "user", "content": "a subagent's own context is ignored"}},
        {"type": "system", "subtype": "compact_boundary"},
        {"type": "user", "isCompactSummary": True,
         "message": {"role": "user", "content": "short summary"}},
        _assistant("r3", [{"type": "text", "text": "done"}],
                   {"input_tokens": 1, "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 50}),
    ])


def test_claude_code_golden_numbers(tmp_path: Path) -> None:
    report = imap.input_map(_claude_session(tmp_path))

    assert report["schema"] == imap.SCHEMA
    assert report["format"] == "claude-code"
    assert report["requests"] == 3
    assert report["billed_input"] == {"uncached": 11, "cache_write": 110, "cache_read": 160,
                                      "total": 281, "cache_read_share": round(160 / 281, 4)}
    # cost: 11 * 1.0 + 110 * 1.25 + 160 * 0.1 = 11 + 137.5 + 16 = 164.5
    assert report["cost"]["weighted"] == {"uncached": 11.0, "cache_write": 137.5,
                                          "cache_read": 16.0}
    assert report["cost"]["cache_write_share"] == round(137.5 / 164.5, 4)
    assert report["system_prompt_tokens"] == 4
    assert report["transcript_tokens"] == {
        "tool results": 8, "tool-call inputs": 4, "user text": 3, "assistant text": 3,
        "attachments": 2, "compaction summary": 2,
    }
    # Replay: r1 sees the user text (3); r2 sees user 3 + "ok" 1 + Read input 2 + result 4
    # + skill listing 2 = 12; r3 sees only the summary (2), after the boundary. Total 17.
    # Three requests are too few for the overhead fit, so there is no fixed-overhead row.
    assert report["fixed_overhead_fit"] is None
    assert report["categories"] == [
        {"category": "user text", "share": round(6 / 17, 4)},
        {"category": "tool results", "share": round(4 / 17, 4)},
        {"category": "tool-call inputs", "share": round(2 / 17, 4)},
        {"category": "attachments", "share": round(2 / 17, 4)},
        {"category": "compaction summary", "share": round(2 / 17, 4)},
        {"category": "assistant text", "share": round(1 / 17, 4)},
    ]
    drill = report["drill_down"]
    assert drill["re_read_tokens"] == 4 and drill["re_read_identical_tokens"] == 4
    assert drill["tool_results_by_tool"] == [{"name": "Read", "tokens": 8}]
    assert drill["attachments_by_type"] == [{"name": "skill_listing", "tokens": 2}]
    assert drill["duplicate_output_tokens"] == 0  # below DUPLICATE_MIN_TOKENS
    assert report["provider_output_tokens"] == {"output": 5, "thinking": 2}


def test_duplicate_outputs_are_counted_above_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imap, "DUPLICATE_MIN_TOKENS", 1)
    report = imap.input_map(_claude_session(tmp_path))
    assert report["drill_down"]["duplicate_output_tokens"] == 4


def test_overhead_fit_recovers_a_known_intercept(tmp_path: Path) -> None:
    # Each request: billed = 100 + 2 * transcript. The fit must return a=100, b=2.
    rows: list[dict] = []
    transcript = 0
    for i in range(12):
        words = i + 1
        rows.append({"type": "user", "message": {"role": "user", "content": "w " * words}})
        transcript += words
        rows.append(_assistant(f"r{i}", [], {"input_tokens": 0,
                                              "cache_creation_input_tokens": 0,
                                              "cache_read_input_tokens": 100 + 2 * transcript}))
    report = imap.input_map(_write(tmp_path, rows))
    assert report["fixed_overhead_fit"] == {"intercept_tokens": 100, "slope": 2.0}
    total = report["billed_input"]["total"]
    shares = {r["category"]: r["share"] for r in report["categories"]}
    assert shares[imap.FIXED] == round(100 * 12 / total, 4)
    assert shares["user text"] == round(1 - 100 * 12 / total, 4)


def _item(payload: dict) -> dict:
    return {"type": "response_item", "payload": payload}


def _count(total: int, **last: int) -> dict:
    return {"type": "event_msg", "payload": {"type": "token_count", "info": {
        "last_token_usage": last, "total_token_usage": {"input_tokens": total}}}}


def _msg(role: str, text: str) -> dict:
    return _item({"type": "message", "role": role,
                  "content": [{"type": "input_text", "text": text}]})


def _codex_session(tmp_path: Path) -> Path:
    # The real order: a response's calls and their outputs are written before its count.
    return _write(tmp_path, [
        {"type": "session_meta", "payload": {"id": "x", "base_instructions": {
            "text": "base rules here", "provenance": "default"}}},
        _item({"type": "additional_tools", "tools": ["t1 t2 t3"]}),
        _msg("developer", "base rules here extra"),  # repeats base: only "extra" is new
        _msg("user", "<environment_context> cwd"),
        _msg("user", f"do {MARKER}"),
        _item({"type": "function_call", "name": "exec", "call_id": "c1", "arguments": "ls -la"}),
        _item({"type": "function_call_output", "call_id": "c1", "output": f"a b {MARKER}"}),
        _count(40, input_tokens=40, cached_input_tokens=30, cache_write_input_tokens=4,
               output_tokens=7, reasoning_output_tokens=3),
        _count(40, input_tokens=40, cached_input_tokens=30),  # repeated count: not a request
        _item({"type": "local_shell_call", "call_id": "ls1", "action": {"command": ["pwd"]}}),
        _item({"type": "web_search_call", "action": {"query": "x"}}),
        _count(100, input_tokens=60, cached_input_tokens=50, output_tokens=2),
        {"type": "compacted", "payload": {"message": "", "replacement_history": [
            {"type": "message", "role": "developer",
             "content": [{"type": "input_text", "text": "base rules here extra"}]},
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "summary of work"}]},
        ]}},
        _count(120, input_tokens=20, output_tokens=1),
    ], name="rollout.jsonl")


def test_codex_charges_each_request_what_it_was_sent(tmp_path: Path) -> None:
    report = imap.input_map(_codex_session(tmp_path))
    assert report["format"] == "codex"
    assert report["requests"] == 3
    # uncached = input - cached - written: 40-30-4, 60-50-0, 20-0-0
    assert report["billed_input"] == {"uncached": 36, "cache_write": 4, "cache_read": 80,
                                      "total": 120, "cache_read_share": round(80 / 120, 4)}
    assert report["cost"]["uncached_share"] == round(36 / (36 + 4 * 1.25 + 80 * 0.1), 4)
    assert report["provider_output_tokens"] == {"output": 10, "thinking": 3}
    # base_instructions (3) once, plus the developer message's extra word (1)
    assert report["system_prompt_tokens"] == 4
    assert report["transcript_tokens"] == {
        "system prompt": 4, "tool schemas": 3, "instructions": 2, "user text": 2,
        "tool-call inputs": 6, "tool results": 3,
    }
    # Request 1 is sent 4+3+2+2 = 11: not its own call and output, written before its count.
    # Request 2 adds that call (2) and output (3) = 16; its own two calls wait.
    # Request 3, after compaction: base 3 + developer extra 1 + replacement user text 3 = 7.
    assert report["categories"] == [
        {"category": "system prompt", "share": round(12 / 34, 4)},
        {"category": "user text", "share": round(7 / 34, 4)},
        {"category": "tool schemas", "share": round(6 / 34, 4)},
        {"category": "instructions", "share": round(4 / 34, 4)},
        {"category": "tool results", "share": round(3 / 34, 4)},
        {"category": "tool-call inputs", "share": round(2 / 34, 4)},
    ]
    assert report["drill_down"]["tool_inputs_by_tool"] == [
        {"name": "exec", "tokens": 2}, {"name": "local_shell", "tokens": 2},
        {"name": "web_search", "tokens": 2},
    ]


def test_codex_uncached_never_goes_negative(tmp_path: Path) -> None:
    path = _write(tmp_path, [
        {"type": "session_meta", "payload": {"id": "x"}},
        _msg("user", "hi"),
        _count(10, input_tokens=10, cached_input_tokens=8, cache_write_input_tokens=5),
    ], name="rollout.jsonl")
    billed = imap.input_map(path)["billed_input"]
    assert billed["uncached"] == 0 and billed["cache_read"] == 8 and billed["cache_write"] == 5


def test_codex_legacy_compaction_message_and_base_without_copy(tmp_path: Path) -> None:
    path = _write(tmp_path, [
        {"type": "session_meta", "payload": {"base_instructions": {"text": "be good"}}},
        _msg("user", "one two three"),
        _count(10, input_tokens=10),
        {"type": "compacted", "payload": {"message": "short sum"}},
        _count(20, input_tokens=10),
    ], name="rollout.jsonl")
    report = imap.input_map(path)
    # request 1: base 2 + user 3; request 2: base 2 + summary 2 (the user text is gone)
    assert report["categories"] == [
        {"category": "system prompt", "share": round(4 / 9, 4)},
        {"category": "user text", "share": round(3 / 9, 4)},
        {"category": "compaction summary", "share": round(2 / 9, 4)},
    ]


def test_session_without_usage_records_reports_no_shares(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"type": "user", "message": {"role": "user", "content": "hi"}}])
    report = imap.input_map(path)
    assert report["requests"] == 0 and report["categories"] == []
    assert report["billed_input"]["cache_read_share"] is None
    assert "cannot be computed" in imap.to_markdown(report)


def test_report_holds_no_session_text_or_path(tmp_path: Path) -> None:
    for path in (_claude_session(tmp_path), _codex_session(tmp_path)):
        report = imap.input_map(path)
        assert MARKER not in json.dumps(report)
        assert MARKER not in imap.to_markdown(report)


def test_cli_input_map_json_and_markdown(tmp_path: Path) -> None:
    path = _claude_session(tmp_path)
    runner = CliRunner()
    as_json = runner.invoke(app, ["measure-session", str(path), "--input-map", "--json"])
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.output)["schema"] == imap.SCHEMA
    as_md = runner.invoke(app, ["measure-session", str(path), "--input-map", "--markdown"])
    assert as_md.exit_code == 0, as_md.output
    assert "| where billed input goes | share |" in as_md.output
    assert "not as exact percentages" in as_md.output
    plain = runner.invoke(app, ["measure-session", str(path), "--input-map"])
    assert plain.exit_code == 0, plain.output


# Review fixes (#84): each test failed before its fix.


def _usage(**fields: object) -> dict:
    return {"input_tokens": 0, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, **fields}


def test_assistant_records_without_request_id_still_count(tmp_path: Path) -> None:
    rows = [
        {"type": "user", "message": {"role": "user", "content": "hi there"}},
        {"type": "assistant", "uuid": "u1", "message": {
            "role": "assistant", "content": [], "usage": _usage(cache_read_input_tokens=10)}},
        {"type": "assistant", "uuid": "u2", "message": {
            "role": "assistant", "content": [], "usage": _usage(cache_read_input_tokens=12)}},
    ]
    report = imap.input_map(_write(tmp_path, rows))
    assert report["requests"] == 2
    assert report["billed_input"]["cache_read"] == 22


def test_split_request_uses_its_last_usage(tmp_path: Path) -> None:
    rows = [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        _assistant("r1", [{"type": "text", "text": "a"}],
                   _usage(cache_read_input_tokens=5, output_tokens=1)),
        _assistant("r1", [{"type": "text", "text": "b"}],
                   _usage(cache_read_input_tokens=5, output_tokens=9,
                          output_tokens_details={"thinking_tokens": 4})),
    ]
    report = imap.input_map(_write(tmp_path, rows))
    assert report["requests"] == 1
    assert report["billed_input"]["cache_read"] == 5
    assert report["provider_output_tokens"] == {"output": 9, "thinking": 4}


def test_malformed_usage_fields_count_as_zero(tmp_path: Path) -> None:
    rows = [
        _assistant("r1", [], _usage(cache_read_input_tokens="lots", input_tokens={"x": 1},
                                    cache_creation_input_tokens="7", output_tokens=None,
                                    output_tokens_details={"thinking_tokens": [1]})),
        {"type": "session_meta"},  # not first: ignored
    ]
    report = imap.input_map(_write(tmp_path, rows))
    assert report["billed_input"]["cache_read"] == 0
    assert report["billed_input"]["uncached"] == 0
    assert report["billed_input"]["cache_write"] == 7
    # json.loads accepts Infinity and NaN; a count like that is 0, not a crash
    bad = tmp_path / "nonfinite.jsonl"
    bad.write_text('{"type": "assistant", "requestId": "r", "message": {"role": "assistant", '
                   '"content": [], "usage": {"input_tokens": Infinity, '
                   '"cache_read_input_tokens": NaN, "cache_creation_input_tokens": 3}}}\n',
                   encoding="utf-8")
    assert imap.input_map(bad)["billed_input"] == {
        "uncached": 0, "cache_write": 3, "cache_read": 0, "total": 3, "cache_read_share": 0.0}
    codex = _write(tmp_path, [
        {"type": "session_meta", "payload": {}},
        _count(5, input_tokens="5", cached_input_tokens={"a": 1}, output_tokens="x"),
    ], name="rollout.jsonl")
    assert imap.input_map(codex)["billed_input"]["uncached"] == 5


def test_a_read_after_compaction_is_not_a_re_read(tmp_path: Path) -> None:
    rows = [
        _assistant("r1", [_read("t1")], _usage(cache_read_input_tokens=1)),
        _result("t1", "same bytes"),
        {"type": "system", "subtype": "compact_boundary"},
        _assistant("r2", [_read("t2")], _usage(cache_read_input_tokens=1)),
        _result("t2", "same bytes"),
    ]
    drill = imap.input_map(_write(tmp_path, rows))["drill_down"]
    assert drill["re_read_tokens"] == 0


def test_cli_rejects_question_with_input_map(tmp_path: Path) -> None:
    path = _claude_session(tmp_path)
    result = CliRunner().invoke(
        app, ["measure-session", str(path), "--input-map", "-q", "why did it fail"]
    )
    assert result.exit_code != 0
    assert "--question" in result.output


def test_mcp_tool_names_are_grouped(tmp_path: Path) -> None:
    rows = [
        _assistant("r1", [{"type": "tool_use", "id": "m1", "name": "mcp__acme_secret__query",
                           "input": {}}], _usage(cache_read_input_tokens=1)),
        _result("m1", "one two"),
    ]
    report = imap.input_map(_write(tmp_path, rows))
    assert "acme_secret" not in json.dumps(report)
    assert report["drill_down"]["tool_results_by_tool"] == [{"name": "mcp", "tokens": 2}]
    assert "tool names" in imap.to_markdown(report)


# Compaction (#84 follow-up): each test failed before its fix.


@pytest.mark.parametrize("meta", [
    {"preservedMessages": {"anchorUuid": "s", "uuids": ["u2"], "allUuids": ["u2"]}},
    {"preservedSegment": {"headUuid": "u2", "anchorUuid": "s", "tailUuid": "u2"}},
])
def test_claude_code_compaction_keeps_preserved_messages(tmp_path: Path, meta: dict) -> None:
    rows = [
        {"type": "user", "uuid": "u0", "message": {"role": "user", "content": "a b c"}},
        _assistant("r1", [], _usage(cache_read_input_tokens=1)),
        {"type": "user", "uuid": "u2", "message": {"role": "user", "content": "keep this"}},
        {"type": "system", "subtype": "compact_boundary", "compactMetadata": meta},
        {"type": "user", "uuid": "s", "isCompactSummary": True,
         "message": {"role": "user", "content": "sum"}},
        _assistant("r2", [], _usage(cache_read_input_tokens=1)),
    ]
    report = imap.input_map(_write(tmp_path, rows))
    # r1 is sent "a b c" (3); r2 the kept "keep this" (2) plus the summary (1)
    assert report["categories"] == [
        {"category": "user text", "share": round(5 / 6, 4)},
        {"category": "compaction summary", "share": round(1 / 6, 4)},
    ]


def _codex_compaction(tmp_path: Path) -> Path:
    usage = {"input_tokens": 50, "cached_input_tokens": 0}
    return _write(tmp_path, [
        {"type": "session_meta", "payload": {"id": "x"}},
        _msg("user", "one two three"),
        {"type": "token_usage_record", "payload": {"response_id": "r1",
                                                   "usage": {"input_tokens": 10}}},
        _count(10, input_tokens=10),
        _msg("user", "four five"),
        # the compaction call: a usage record with no token_count after it
        {"type": "token_usage_record", "payload": {"response_id": "r2", "usage": usage}},
        {"type": "compacted", "payload": {
            "message": "",
            "latest_token_usage_record": {"response_id": "r2", "usage": usage},
            "replacement_history": [
                {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "one two three"}]},
                {"type": "compaction", "encrypted_content": "gAAAA-opaque"},
            ]}},
        _count(30, input_tokens=20),
    ], name="rollout.jsonl")


def test_codex_compaction_call_is_billed_once(tmp_path: Path) -> None:
    report = imap.input_map(_codex_compaction(tmp_path))
    # token_count r1, the compaction call r2 (record + latest_token_usage_record: once), r3
    assert report["requests"] == 3
    assert report["billed_input"]["uncached"] == 10 + 50 + 20


def test_codex_opaque_summary_is_sized_from_the_billed_gap(tmp_path: Path) -> None:
    report = imap.input_map(_codex_compaction(tmp_path))
    # r1 sends 3; the compaction call sends all 5 user words; r3 sends the kept 3 words and
    # an opaque summary sized 20 - 3 = 17. Replay total 3 + 5 + 20 = 28.
    assert report["categories"] == [
        {"category": imap.OPAQUE, "share": round(17 / 28, 4)},
        {"category": "user text", "share": round(11 / 28, 4)},
    ]
    assert any("encrypted summary" in w for w in report["warnings"])
    assert "Warning:" in imap.to_markdown(report)


def test_warns_when_fixed_overhead_cannot_be_separated(tmp_path: Path) -> None:
    report = imap.input_map(_claude_session(tmp_path))  # 3 requests: no fit
    assert report["fixed_overhead_fit"] is None
    assert any("could not be separated" in w for w in report["warnings"])
    assert "could not be separated" in imap.to_markdown(report)


def test_codex_message_is_public() -> None:
    from lcc.session_report import codex_message

    entry = codex_message({"type": "function_call", "call_id": "c", "name": "exec",
                           "arguments": "{}"}, 0)
    assert entry is not None and entry["toolUses"][0]["tool"] == "exec"
