"""`lcc measure-session`: counts-only report of what each mode would do to a local session."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lcc.cli import app
from lcc.session_report import from_claude_code, measure_session

MARKER = "PRIVATE-4242"


def _session(tmp_path: Path, n: int = 12) -> Path:
    rows = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Fix the parser. Marker {MARKER} must stay private."}
                ],
            },
        }
    ]
    for i in range(n):
        rows.append(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "hmm"},
                        {
                            "type": "tool_use",
                            "id": f"t{i}",
                            "name": "Bash",
                            "input": {"command": f"cat log{i}.txt"},
                        },
                    ],
                },
            }
        )
        rows.append(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"t{i}",
                            "content": f"{MARKER} line\n" * 200,
                        }
                    ],
                },
            }
        )
    rows.append(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "orphan", "content": "no call"}],
            },
        }
    )
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    return path


def test_reader_pairs_calls_drops_thinking_and_orphans(tmp_path: Path):
    messages = from_claude_code(_session(tmp_path, 3))
    assert sum(len(m.get("toolUses") or []) for m in messages) == 3
    results = [r["tool_use_id"] for m in messages for r in m.get("toolResults") or []]
    assert results == ["t0", "t1", "t2"]


def test_measure_reports_counts_per_mode_and_never_text(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    stash_home = tmp_path / "home-stash"
    monkeypatch.setenv("LCC_STASH_DIR", str(stash_home))
    report = measure_session(_session(tmp_path))
    modes = {row["mode"]: row for row in report["modes"]}
    assert {"rules:lossless", "rules:stashed", "auto"} <= set(modes)
    assert report["messages"] > 0 and report["tool_calls"] == 12
    assert modes["rules:stashed"]["tokens_after"] < report["tokens_before"]
    assert all(row["texts_lost"] == 0 for row in modes.values())
    assert MARKER not in json.dumps(report) and "parser" not in json.dumps(report)
    assert not stash_home.exists()  # measuring never writes into the user's real stash


def test_cli_prints_markdown_ready_for_an_issue(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    result = CliRunner().invoke(app, ["measure-session", str(_session(tmp_path)), "--markdown"])
    assert result.exit_code == 0, result.output
    assert "| mode |" in result.output and "rules:stashed" in result.output
    assert MARKER not in result.output
    pretty = CliRunner().invoke(app, ["measure-session", str(_session(tmp_path))])
    assert pretty.exit_code == 0 and "rules:stashed" in pretty.output and "|" not in pretty.output
    as_json = CliRunner().invoke(app, ["measure-session", str(_session(tmp_path)), "--json"])
    assert json.loads(as_json.output)["schema"] == "lcc-session-report/1"


def test_compact_tool_calls_reads_a_claude_code_jsonl_directly(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))
    out = tmp_path / "out.json"
    result = CliRunner().invoke(
        app,
        [
            "compact",
            str(_session(tmp_path, 40)),
            "-q",
            "fix the parser",
            "--mode",
            "tool-calls",
            "--provider",
            "rules",
            "--rules-mode",
            "stashed",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())[0]["role"] == "user"
