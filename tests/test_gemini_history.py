"""Gemini CLI saved-chat import (#108), using a real offline recorder fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc.cli import app
from lcc.gemini_history import from_gemini_cli, parse_gemini_chat_history
from lcc.relevance.transcript import parse_transcript
from lcc.session_report import from_claude_code, messages_from_jsonl

FIXTURE = Path(__file__).parent / "fixtures" / "gemini_cli" / "session.jsonl"
HEADER = {"sessionId": "fixture", "projectHash": "fixture-project"}
runner = CliRunner()


def history(*records: dict) -> list[dict]:
    return parse_gemini_chat_history("\n".join(json.dumps(r) for r in (HEADER, *records)))


def test_actual_recorder_fixture_pairs_tools_and_preserves_user_text() -> None:
    messages = from_gemini_cli(FIXTURE)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "user", "assistant"]
    expected = "Keep spacing exactly:  café  \n\tsecond line\r\n"
    assert messages[0]["text"].encode("utf-8") == expected.encode("utf-8")
    assert messages[3]["text"] == "Keep the final summary short.\n"
    assert messages[4]["text"] == "The fixture greeting is hello.\n"
    parsed = parse_transcript({"messages": messages})
    assert len(parsed) == 5
    calls = parsed[1].tool_calls
    assert [(call.id, call.tool, call.input) for call in calls] == [
        ("call-1", "read_file", {"file_path": "hello.txt"}),
        ("call-2", "read_file", {"file_path": "other.txt"}),
    ]
    assert [call.result.text for call in calls] == ["hello\n", "world\n"]
    assert "discarded" not in json.dumps(messages)


def test_existing_session_reader_auto_detects_gemini() -> None:
    assert from_claude_code(FIXTURE) == from_gemini_cli(FIXTURE)
    lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    assert messages_from_jsonl(lines) == from_gemini_cli(FIXTURE)


def test_replay_content_result_patches_removal_and_order() -> None:
    messages = history(
        {"id": "u", "type": "user", "content": "old"},
        {
            "id": "g",
            "type": "gemini",
            "content": "before",
            "toolCalls": [
                {"id": "c", "name": "read_file", "args": {}, "status": "success", "result": "old"}
            ],
        },
        {"id": "gone", "type": "user", "content": "remove me"},
        {"$patch": {"id": "u", "content": "new\n"}},
        {
            "$patch": {
                "updates": [
                    {
                        "id": "g",
                        "content": "after",
                        "toolCalls": [
                            {
                                "id": "c",
                                "result": [
                                    {
                                        "functionResponse": {
                                            "id": "c",
                                            "response": {"output": "updated\n"},
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "removeIds": ["gone"],
                "orderIds": ["g", "u"],
            }
        },
    )
    assert messages[0]["text"] == "after"
    assert messages[1]["toolResults"] == [{"tool_use_id": "c", "text": "updated\n"}]
    assert messages[2]["text"] == "new\n"


def test_checkpoint_replaces_history_and_unknown_rewind_clears_it() -> None:
    assert history(
        {"id": "old", "type": "user", "content": "old"},
        {"$set": {"messages": [{"id": "new", "type": "user", "content": "new"}]}},
    ) == [{"role": "user", "text": "new"}]
    assert history({"id": "u", "type": "user", "content": "old"}, {"$rewindTo": "absent"}) == []


def test_legacy_snapshot_shape_and_text_parts_without_invented_separators() -> None:
    snapshot = HEADER | {
        "messages": [
            {
                "id": "u",
                "type": "user",
                "content": [{"text": "a"}, {"text": " b\n"}],
                "displayContent": "display-only",
                "thoughts": [{"text": "private reasoning"}],
            },
            {"id": "i", "type": "info", "content": "UI notification"},
            {"id": "g", "type": "gemini", "content": "answer\n"},
        ]
    }
    assert parse_gemini_chat_history(json.dumps(snapshot, indent=2)) == [
        {"role": "user", "text": "a b\n"},
        {"role": "assistant", "text": "answer\n"},
    ]


def test_pending_empty_and_error_results_are_distinct() -> None:
    messages = history(
        {
            "id": "g",
            "type": "gemini",
            "content": "",
            "toolCalls": [
                {"id": "pending", "name": "read_file", "args": {}, "status": "executing"},
                {"id": "empty", "name": "read_file", "args": {}, "status": "success", "result": ""},
                {
                    "id": "failed",
                    "name": "read_file",
                    "args": {},
                    "status": "error",
                    "result": [
                        {"functionResponse": {"id": "failed", "response": {"error": "not found\n"}}}
                    ],
                },
            ],
        }
    )
    assert len(messages[0]["toolUses"]) == 3
    assert messages[1]["toolResults"] == [
        {"tool_use_id": "empty", "text": ""},
        {"tool_use_id": "failed", "text": "not found\n", "is_error": True},
    ]


def test_unknown_records_incomplete_tail_and_empty_session() -> None:
    assert history({"future": True}, {"$patch": {"id": "missing", "content": "ignore"}}) == []
    text = json.dumps(HEADER) + '\n{"id":"u","type":"user","content":"keep"}\n{"id":'
    assert parse_gemini_chat_history(text) == [{"role": "user", "text": "keep"}]
    with pytest.raises(ValueError, match="missing sessionId/projectHash"):
        parse_gemini_chat_history('{"messages":[]}')


def test_unrelated_and_ambiguous_results_are_not_misattributed() -> None:
    def call(call_id: str, result: object, name: str = "read_file") -> dict:
        return {"id": call_id, "name": name, "args": {}, "status": "success", "result": result}

    def response(output: str, **fields: str) -> dict:
        return {"functionResponse": {"response": {"output": output}, **fields}}

    messages = history(
        {
            "id": "g",
            "type": "gemini",
            "content": "",
            "toolCalls": [
                call("orphan", [response("foreign", id="other")]),
                call("ambiguous", [response("a"), response("b")]),
                call(
                    "named", [response("right", name="read_file"), response("wrong", name="shell")]
                ),
                call("single", [response("one result")]),
                call("exact", [response("right", id="exact"), response("wrong")]),
            ],
        }
    )
    assert messages[1]["toolResults"] == [
        {"tool_use_id": "named", "text": "right"},
        {"tool_use_id": "single", "text": "one result"},
        {"tool_use_id": "exact", "text": "right"},
    ]


def test_malformed_call_types_and_nontext_results_are_not_invented() -> None:
    assert history({"id": "g", "type": "gemini", "content": "", "toolCalls": None}) == []
    messages = history(
        {
            "id": "g",
            "type": "gemini",
            "content": "",
            "toolCalls": [
                None,
                {"id": [], "name": "bad"},
                {"id": "bad", "name": "bad", "args": []},
                {
                    "id": "image",
                    "name": "read_file",
                    "args": {},
                    "result": [{"inlineData": {"data": "AA=="}}],
                },
            ],
        }
    )
    assert messages == [
        {
            "role": "assistant",
            "text": "",
            "toolUses": [{"tool_use_id": "image", "tool": "read_file", "input": {}}],
        }
    ]


def test_unicode_line_separators_survive_jsonl_string_and_file(tmp_path: Path) -> None:
    text = "Before\u0085middle\u2028next\u2029after\n"
    saved = "\n".join(
        json.dumps(record, ensure_ascii=False)
        for record in (HEADER, {"id": "u", "type": "user", "content": [{"text": text}]})
    )
    path = tmp_path / "unicode.jsonl"
    path.write_text(saved, encoding="utf-8")
    expected = [{"role": "user", "text": text}]
    assert parse_gemini_chat_history(saved) == expected
    assert from_gemini_cli(path) == expected
    assert from_claude_code(path) == expected


def test_sdk_thought_parts_do_not_become_text_or_results() -> None:
    messages = history(
        {
            "id": "g",
            "type": "gemini",
            "content": [{"text": "do not export", "thought": True}, {"text": "visible\n"}],
            "thoughts": [{"text": "also private"}],
            "toolCalls": [
                {
                    "id": "c",
                    "name": "read_file",
                    "args": {},
                    "result": [
                        {"text": "not a tool result", "thought": True},
                        {"text": "actual result\n"},
                    ],
                }
            ],
        }
    )
    assert messages[0]["text"] == "visible\n"
    assert messages[1]["toolResults"] == [{"tool_use_id": "c", "text": "actual result\n"}]


def test_deeply_malformed_line_is_ignored_like_other_jsonl_parse_errors() -> None:
    saved = json.dumps(HEADER) + "\n" + "[" * 1200 + "\n"
    assert parse_gemini_chat_history(saved) == []


def test_counts_only_measure_session_and_lossless_compaction(tmp_path: Path) -> None:
    measured = runner.invoke(app, ["measure-session", str(FIXTURE), "--json"])
    assert measured.exit_code == 0, measured.output
    report = json.loads(measured.output)
    assert report["messages"] == 5
    assert report["tool_calls"] == 2
    assert "café" not in measured.output
    assert "hello.txt" not in measured.output
    assert all(mode.get("texts_lost") == 0 for mode in report["modes"])
    source, out, report_path = (
        tmp_path / name for name in ("input.json", "out.json", "report.json")
    )
    source.write_text(json.dumps({"messages": from_gemini_cli(FIXTURE)}), encoding="utf-8")
    compacted = runner.invoke(
        app,
        [
            "compact",
            str(source),
            "-q",
            "finish",
            "--mode",
            "tool-calls",
            "--provider",
            "rules",
            "--rules-mode",
            "lossless",
            "-o",
            str(out),
            "-r",
            str(report_path),
        ],
    )
    assert compacted.exit_code == 0, compacted.output
    assert json.loads(out.read_text(encoding="utf-8")) == from_gemini_cli(FIXTURE)
