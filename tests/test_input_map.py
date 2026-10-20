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


def _codex_session(tmp_path: Path) -> Path:
    def item(payload: dict) -> dict:
        return {"type": "response_item", "payload": payload}

    def count(last: dict, total: dict) -> dict:
        return {"type": "event_msg", "payload": {
            "type": "token_count", "info": {"last_token_usage": last, "total_token_usage": total}}}

    return _write(tmp_path, [
        {"type": "session_meta", "payload": {"id": "x"}},
        item({"type": "additional_tools", "tools": ["t1 t2 t3"]}),
        item({"type": "message", "role": "developer",
              "content": [{"type": "input_text", "text": "system words here"}]}),
        item({"type": "message", "role": "user",
              "content": [{"type": "input_text", "text": "<environment_context> cwd"}]}),
        item({"type": "message", "role": "user",
              "content": [{"type": "input_text", "text": f"do {MARKER}"}]}),
        count({"input_tokens": 40, "cached_input_tokens": 30}, {"input_tokens": 40}),
        count({"input_tokens": 40, "cached_input_tokens": 30}, {"input_tokens": 40}),  # repeat
        item({"type": "function_call", "name": "exec", "call_id": "c1", "arguments": "ls -la"}),
        item({"type": "function_call_output", "call_id": "c1", "output": f"a b {MARKER}"}),
        count({"input_tokens": 60, "cached_input_tokens": 50}, {"input_tokens": 100}),
    ], name="rollout.jsonl")


def test_codex_counts_system_prompt_and_schemas_directly(tmp_path: Path) -> None:
    report = imap.input_map(_codex_session(tmp_path))
    assert report["format"] == "codex"
    assert report["requests"] == 2  # the repeated token_count is not a new request
    assert report["billed_input"]["uncached"] == 20
    assert report["billed_input"]["cache_read"] == 80
    assert report["cost"]["uncached_share"] == round(20 / (20 + 8), 4)
    assert report["system_prompt_tokens"] == 3
    assert report["fixed_overhead_fit"] is None
    assert report["transcript_tokens"] == {
        "tool schemas": 3, "system prompt": 3, "instructions": 2, "user text": 2,
        "tool-call inputs": 2, "tool results": 3,
    }
    # request 1 sees 3+3+2+2 = 10; request 2 sees those plus the call (2) and result (3) = 15
    shares = {r["category"]: r["share"] for r in report["categories"]}
    assert shares["tool results"] == round(3 / 25, 4)
    assert shares["tool schemas"] == round(6 / 25, 4)
    assert report["drill_down"]["tool_inputs_by_tool"] == [{"name": "exec", "tokens": 2}]


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
