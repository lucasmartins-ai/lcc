"""Aider ``.aider.chat.history.md`` → lcc transcript (#63)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lcc.aider_history import (
    from_aider_chat_history,
    messages_payload,
    parse_aider_chat_history,
)
from lcc.cli import app
from lcc.relevance.transcript import parse_transcript

FIXTURE = Path(__file__).parent / "fixtures" / "aider_chat_history.md"
runner = CliRunner()


def test_fixture_maps_user_and_assistant_drops_tool_lines() -> None:
    messages = from_aider_chat_history(FIXTURE)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["text"].startswith("Fix the greeting in hello.py")
    assert 'print("goodbye")' in messages[1]["text"]
    assert messages[2]["text"].startswith("Run the file and show the output")
    joined = "\n".join(m["text"] for m in messages)
    assert "Tokens:" not in joined
    assert "Added hello.py" not in joined
    assert "toolUses" not in messages[0]
    assert "toolResults" not in messages[0]


def test_include_tool_keeps_blockquote_lines() -> None:
    messages = from_aider_chat_history(FIXTURE, include_tool=True)
    roles = [m["role"] for m in messages]
    assert roles.count("user") >= 3
    assert any("Added hello.py to the chat" in m["text"] for m in messages)
    assert any("Tokens:" in m["text"] for m in messages)


def test_parse_matches_string_and_path() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    assert parse_aider_chat_history(text) == from_aider_chat_history(FIXTURE)


def test_payload_parses_as_tool_calls_transcript() -> None:
    payload = messages_payload(from_aider_chat_history(FIXTURE))
    parsed = parse_transcript(payload)
    assert len(parsed) == 3
    assert all(not m.tool_calls and not m.tool_results for m in parsed)


def test_compact_tool_calls_accepts_converted_history(tmp_path: Path) -> None:
    payload = messages_payload(from_aider_chat_history(FIXTURE))
    src = tmp_path / "aider.json"
    out = tmp_path / "out.json"
    report = tmp_path / "report.json"
    src.write_text(json.dumps(payload), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "-q",
            "finish the greeting fix",
            "--mode",
            "tool-calls",
            "--provider",
            "rules",
            "--rules-mode",
            "lossless",
            "-o",
            str(out),
            "-r",
            str(report),
        ],
    )
    assert result.exit_code == 0, result.output
    messages = json.loads(out.read_text(encoding="utf-8"))
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["text"].startswith("Fix the greeting in hello.py")
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["mode"] == "tool-calls"
    assert data["tool_calls_dropped"] == 0
