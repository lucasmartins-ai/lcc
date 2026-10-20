"""Codex rollout fixtures are entirely synthetic; never open a user's session directory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import lcc
from lcc.cli import app
from lcc.session_report import from_claude_code, measure_session, messages_from_jsonl

PRIVATE = "SYNTHETIC-PRIVATE-4242"
USER_TEXT = f"Fix the parser.\nKeep café and 中文 intact. {PRIVATE}"
ASSISTANT_TEXT = "I will inspect the file.\nThen fix it."
PATCH = "*** Begin Patch\n*** Update File: synthetic.py\n@@\n-old\n+new\n*** End Patch"


def _rollout(tmp_path: Path, n: int = 3) -> Path:
    rows = [
        {"type": "session_meta", "payload": {"id": PRIVATE, "cwd": f"/synthetic/{PRIVATE}"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": USER_TEXT}},
        {"type": "turn_context", "payload": {"cwd": PRIVATE}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": "system excluded"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "reasoning excluded"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": USER_TEXT}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": ASSISTANT_TEXT}],
            },
        },
        {"type": "event_msg", "payload": {"type": "agent_message", "message": ASSISTANT_TEXT}},
    ]
    for i in range(n):
        rows.extend(
            [
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": f"call-{i}",
                        "arguments": json.dumps({"cmd": f"cat synthetic-{i}.txt"}),
                    },
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": f"call-{i}",
                        "output": f"{PRIVATE} line\n" * 200,
                    },
                },
            ]
        )
    rows.extend(
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "patch",
                    "input": PATCH,
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "patch",
                    "output": [
                        {"type": "input_text", "text": "Patch applied"},
                        {"type": "input_image", "image_url": "data:image/png;base64,synthetic"},
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "orphan",
                    "output": "orphan excluded",
                },
            },
        ]
    )
    path = tmp_path / f"{PRIVATE}-rollout.jsonl"
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\nmalformed tail\n", encoding="utf-8"
    )
    return path


def test_reader_maps_response_items_without_duplicate_events(tmp_path: Path):
    messages = from_claude_code(_rollout(tmp_path))
    assert len(messages) == 10
    assert messages[0] == {"role": "user", "text": USER_TEXT}
    assert messages[1] == {"role": "assistant", "text": ASSISTANT_TEXT}
    calls = [call for message in messages for call in message.get("toolUses", [])]
    results = [result for message in messages for result in message.get("toolResults", [])]
    assert [call["tool_use_id"] for call in calls] == ["call-0", "call-1", "call-2", "patch"]
    assert calls[0]["input"] == {"cmd": "cat synthetic-0.txt"}
    assert calls[-1] == {"tool_use_id": "patch", "tool": "apply_patch", "input": {"input": PATCH}}
    assert [result["tool_use_id"] for result in results] == [call["tool_use_id"] for call in calls]
    assert results[-1]["text"] == "Patch applied\n[image]"
    assert "excluded" not in json.dumps(messages)


def test_reader_keeps_function_and_custom_tool_namespaces():
    rows = [
        {"type": "session_meta"},
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "call_id": "command",
                "namespace": "functions",
                "name": "exec_command",
                "arguments": "{}",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": "patch",
                "namespace": "functions",
                "name": "apply_patch",
                "input": PATCH,
            },
        },
    ]
    messages = messages_from_jsonl(json.dumps(row) for row in rows)
    assert [message["toolUses"][0]["tool"] for message in messages] == [
        "functions.exec_command",
        "functions.apply_patch",
    ]


@pytest.mark.parametrize("id_field", ["id", "call_id"])
def test_reader_pairs_legacy_local_shell_with_function_output(id_field: str):
    action = {
        "type": "exec",
        "command": ["sh", "-c", "echo synthetic"],
        "working_directory": "/synthetic",
    }
    records = [
        {"type": "session_meta", "payload": {}},
        {
            "type": "response_item",
            "payload": {"type": "local_shell_call", id_field: "shell", "action": action},
        },
        {
            "type": "response_item",
            "payload": {"type": "function_call_output", "call_id": "shell", "output": "synthetic"},
        },
    ]
    messages = messages_from_jsonl(json.dumps(row) for row in records)
    assert messages[0]["toolUses"] == [
        {"tool_use_id": "shell", "tool": "local_shell", "input": action}
    ]
    assert messages[1]["toolResults"] == [{"tool_use_id": "shell", "text": "synthetic"}]


@pytest.mark.parametrize("arguments", ["not JSON", "[1, 2]", "null"])
def test_non_object_function_arguments_are_preserved(arguments: str):
    rows = [
        {"type": "session_meta"},
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "call_id": "call",
                "name": "tool",
                "arguments": arguments,
            },
        },
    ]
    message = messages_from_jsonl(json.dumps(row) for row in rows)[0]
    expected = arguments if arguments == "not JSON" else json.loads(arguments)
    assert message["toolUses"][0]["input"] == {"arguments": expected}


def test_measure_codex_preserves_text_and_reports_only_counts(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    stash = tmp_path / "unused-stash"
    monkeypatch.setenv("LCC_STASH_DIR", str(stash))
    report = measure_session(_rollout(tmp_path, n=12))
    assert report["messages"] == 28 and report["tool_calls"] == 13
    assert all(mode["texts_lost"] == 0 for mode in report["modes"])
    assert PRIVATE not in json.dumps(report)
    assert not stash.exists()


def test_cli_codex_report_does_not_expose_session_text_or_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    # The child must import this lcc, not another install on the same interpreter.
    monkeypatch.setenv("PYTHONPATH", str(Path(lcc.__file__).resolve().parents[1]))
    path = _rollout(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "lcc.cli", "measure-session", str(path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema"] == "lcc-session-report/1" and report["tool_calls"] == 4
    assert PRIVATE not in result.stdout + result.stderr
    table = CliRunner().invoke(app, ["measure-session", str(path)])
    assert table.exit_code == 0 and "rules:stashed" in table.output
    assert PRIVATE not in table.output


def test_compact_tool_calls_also_accepts_a_codex_rollout(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))
    output = tmp_path / "out.json"
    result = CliRunner().invoke(
        app,
        [
            "compact",
            str(_rollout(tmp_path)),
            "-q",
            "fix the parser",
            "--mode",
            "tool-calls",
            "--provider",
            "rules",
            "--rules-mode",
            "stashed",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text())[0] == {"role": "user", "text": USER_TEXT}


@pytest.mark.parametrize(
    "action",
    [
        {"type": "search", "query": "synthetic query"},
        {"type": "search", "queries": ["first query", "second query"]},
        {"type": "open_page", "url": "https://example.invalid"},
        {"type": "find_in_page", "url": "https://example.invalid", "pattern": "synthetic"},
        None,
    ],
)
def test_native_web_search_keeps_provider_id_and_action(action):
    rows = [
        {"type": "session_meta"},
        {
            "type": "response_item",
            "payload": {
                "type": "web_search_call",
                "id": "ws-synthetic",
                "status": "completed",
                "action": action,
            },
        },
    ]
    messages = messages_from_jsonl(json.dumps(row) for row in rows)
    assert len(messages) == 1
    assert messages[0]["toolUses"] == [
        {
            "tool_use_id": "ws-synthetic",
            "tool": "web_search",
            "input": action or {},
        }
    ]


def test_native_web_search_without_provider_ids_is_not_dropped():
    rows = [
        {"type": "session_meta"},
        {"type": "response_item", "payload": {"type": "web_search_call"}},
        {"type": "response_item", "payload": {"type": "web_search_call"}},
    ]
    lines = [json.dumps(row) for row in rows]
    first = messages_from_jsonl(lines)
    assert len(first) == 2
    assert first == messages_from_jsonl(lines)
    assert len({message["toolUses"][0]["tool_use_id"] for message in first}) == 2


def test_cli_counts_native_web_search_without_exposing_the_query(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    path = tmp_path / "web-rollout.jsonl"
    rows = [
        {"type": "session_meta"},
        {
            "type": "response_item",
            "payload": {
                "type": "web_search_call",
                "id": "ws-synthetic",
                "action": {"type": "search", "query": PRIVATE},
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    result = CliRunner().invoke(app, ["measure-session", str(path), "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["tool_calls"] == 1 and report["tokens_before"] > 0
    assert PRIVATE not in result.output
