"""`lcc measure-session`: counts-only report of what each mode would do to a local session."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from rich.text import Text
from typer.testing import CliRunner

from lcc.cli import app
from lcc.session_report import from_claude_code, measure_directory, measure_session

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


def test_approximate_count_says_why_in_every_output(tmp_path: Path, monkeypatch):
    # A shared result must not pass an estimate off as exact; the note says how to fix it.
    monkeypatch.setattr("lcc.token_budget.counters._HAS_TIKTOKEN", False)
    path = _session(tmp_path)
    report = measure_session(path)
    assert report["token_count_method"] == "approximate"
    assert "tiktoken is not installed" in report["token_count_note"]
    for flag in ("--markdown", None):
        out = CliRunner().invoke(app, ["measure-session", str(path), *([flag] if flag else [])])
        assert out.exit_code == 0, out.output
        assert "tiktoken is not installed" in " ".join(out.output.split())


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (
            ["--question", "Find the parser boundary — 합성 질문"],
            "Find the parser boundary — 합성 질문",
        ),
        (["-q", "Explain the retry failure"], "Explain the retry failure"),
        ([], "finish the task in this session"),
    ],
)
def test_measure_cli_question_reaches_compaction_request(
    tmp_path: Path, monkeypatch, options, expected
):
    from lcc.relevance import transcript

    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    seen = []
    original = transcript.compact_transcript

    def capture_request(request):
        seen.append(request.question)
        return original(request)

    monkeypatch.setattr(transcript, "compact_transcript", capture_request)
    result = CliRunner().invoke(
        app, ["measure-session", str(_session(tmp_path, 1)), "--json", *options]
    )
    assert result.exit_code == 0, result.output
    assert seen == [expected] * 3
    report = json.loads(result.output)
    assert all("error" not in mode for mode in report["modes"])
    assert expected not in result.output


@pytest.mark.parametrize("force_color", ["0", "1"])
def test_measure_cli_help_documents_question_option(monkeypatch, force_color):
    monkeypatch.setenv("FORCE_COLOR", force_color)
    result = CliRunner().invoke(app, ["measure-session", "--help"], color=False)
    assert result.exit_code == 0, result.output
    # Rich can emit ANSI styles even with CliRunner(color=False), notably in CI.
    help_text = Text.from_ansi(result.output).plain
    assert "--question" in help_text
    assert "-q" in help_text


def test_measure_directory_aggregates_median_and_p90_per_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    project = tmp_path / "project"
    project.mkdir()
    for i, n in enumerate((4, 8, 12)):
        folder = tmp_path / f"s{i}"
        folder.mkdir()
        _session(folder, n).rename(project / f"s{i}.jsonl")
    (project / "notes.txt").write_text("not a session", encoding="utf-8")
    report = measure_directory(project)
    assert report["sessions"] == 3
    modes = {row["mode"]: row for row in report["modes"]}
    assert set(modes) == {"rules:lossless", "rules:stashed", "auto"}
    singles = [measure_session(project / f"s{i}.jsonl") for i in range(3)]
    stashed = sorted(
        row["reduction"] for r in singles for row in r["modes"] if row["mode"] == "rules:stashed"
    )
    assert modes["rules:stashed"]["n"] == 3
    assert modes["rules:stashed"]["median_reduction"] == stashed[1]
    assert stashed[1] <= modes["rules:stashed"]["p90_reduction"] <= stashed[-1]
    assert MARKER not in json.dumps(report) and "parser" not in json.dumps(report)


def test_measure_directory_single_session_p90_is_its_value(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    _session(tmp_path)
    report = measure_directory(tmp_path)
    for row in report["modes"]:
        assert row["n"] == 1 and row["median_reduction"] == row["p90_reduction"]


def test_cli_measure_session_directory_prints_one_markdown_table(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    project = tmp_path / "project"
    project.mkdir()
    for i in range(2):
        folder = tmp_path / f"s{i}"
        folder.mkdir()
        _session(folder, 4 + i).rename(project / f"s{i}.jsonl")
    result = CliRunner().invoke(app, ["measure-session", str(project), "--markdown"])
    assert result.exit_code == 0, result.output
    assert result.output.count("| mode | n | median reduction | p90 reduction |") == 1
    assert "| rules:stashed | 2 |" in result.output and "2 sessions" in result.output
    assert MARKER not in result.output and str(project) not in result.output
    as_json = CliRunner().invoke(app, ["measure-session", str(project), "--json"])
    assert json.loads(as_json.output)["sessions"] == 2


def test_cli_measure_session_empty_directory_fails_cleanly(tmp_path: Path):
    result = CliRunner().invoke(app, ["measure-session", str(tmp_path), "--markdown"])
    assert result.exit_code == 2
    assert "no *.jsonl session files" in result.output


def _plant_session(tmp_path: Path, projects: Path, name: str, n: int, mtime: int) -> Path:
    folder = tmp_path / f"build-{name}"
    folder.mkdir()
    path = projects / name
    _session(folder, n).rename(path)
    os.utime(path, (mtime, mtime))
    return path


def test_measure_session_latest_picks_the_newest_session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))
    home = tmp_path / "config"
    projects = home / "projects" / "proj"
    projects.mkdir(parents=True)
    _plant_session(tmp_path, projects, "older.jsonl", n=4, mtime=1_000_000_000)
    newest = _plant_session(tmp_path, projects, "newer.jsonl", n=9, mtime=2_000_000_000)
    (projects / "notes.txt").write_text("not a session", encoding="utf-8")
    os.utime(projects / "notes.txt", (3_000_000_000, 3_000_000_000))
    sidechain = projects / "sidechain"
    sidechain.mkdir()
    (sidechain / "deeper.jsonl").write_text("", encoding="utf-8")
    os.utime(sidechain / "deeper.jsonl", (3_000_000_000, 3_000_000_000))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    result = CliRunner().invoke(app, ["measure-session", "--latest", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["tool_calls"] == 9  # the newest top-level *.jsonl won
    assert MARKER not in result.stdout and str(newest) not in result.stdout
    assert str(newest) in result.stderr  # the picked path goes to stderr, stdout stays counts


@pytest.mark.parametrize("config_dir", [None, ""])
def test_measure_session_latest_falls_back_to_home_without_config_dir(
    tmp_path: Path, monkeypatch, config_dir
):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    if config_dir is None:
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", config_dir)
    projects = tmp_path / "home" / ".claude" / "projects" / "proj"
    projects.mkdir(parents=True)
    _plant_session(tmp_path, projects, "session.jsonl", n=6, mtime=1_000_000_000)
    result = CliRunner().invoke(app, ["measure-session", "--latest", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["tool_calls"] == 6


def test_measure_session_latest_fails_cleanly_without_sessions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))  # no projects/ under it at all
    result = CliRunner().invoke(app, ["measure-session", "--latest"])
    assert result.exit_code == 2
    assert "no Claude Code sessions found" in result.output


def test_measure_session_rejects_passing_session_and_latest(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["measure-session", str(_session(tmp_path)), "--latest"])
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_measure_session_requires_session_or_latest():
    result = CliRunner().invoke(app, ["measure-session"])
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_p90_never_exceeds_the_largest_value():
    from lcc.session_report import _p90

    assert _p90([0.2, 0.3, 0.4]) <= 0.4
    assert _p90([0.5]) == 0.5
