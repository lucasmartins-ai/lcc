"""CLI tests for `lcc compact --mode tool-calls` (offline; the judge is a stub)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import lcc.relevance.transcript as transcript_module
from lcc.cli import app

runner = CliRunner()


class Stub:
    """Per-call probabilities, as the real client would return them."""

    model = "fake"
    last_resolved_model = "jev-2026-09-21"

    def __init__(self, keep_call: float, keep_result: float) -> None:
        self.keep_call = keep_call
        self.keep_result = keep_result

    def evaluate(self, state, questions):
        answers = {}
        for qid in questions:
            value = self.keep_call if qid.startswith("keep_call_") else self.keep_result
            answers[qid] = {"type": "noul", "noul": value}
        return {"answers": answers, "model": "jev-2026-09-21"}


TRANSCRIPT = {
    "messages": [
        {"role": "user", "text": "Fix the failing parser test. Never edit src/generated."},
        {
            "role": "assistant",
            "text": "Running the suite.",
            "toolUses": [{"tool_use_id": "toolu_1", "tool": "Bash", "input": {"command": "pytest -q"}}],
        },
        {"role": "user", "toolResults": [{"tool_use_id": "toolu_1", "text": "1 failed, 24 passed"}]},
    ]
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")


def write(tmp_path: Path, payload=TRANSCRIPT, name: str = "transcript.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_tool_calls_mode_runs_offline_and_keeps_everything_without_a_key(tmp_path: Path):
    src = write(tmp_path)
    out = tmp_path / "out.json"
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "-q",
            "finish the parser fix",
            "--mode",
            "tool-calls",
            "--preserve-recent",
            "0",
            "-o",
            str(out),
            "-r",
            str(report),
        ],
    )
    assert result.exit_code == 0, result.output
    messages = json.loads(out.read_text(encoding="utf-8"))
    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    assert messages[0]["text"] == "Fix the failing parser test. Never edit src/generated."
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["schema_version"] == "transcript-compaction-1.0"
    assert data["mode"] == "tool-calls"
    assert data["degraded"] is True
    assert data["degradation_reason"] == "jev_unavailable_fail_safe"
    assert data["semantic_guarantee"] == "none"
    assert data["tool_calls_dropped"] == 0


def test_a_judged_pass_drops_the_spent_pair(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(transcript_module, "_resolve_client", lambda: Stub(0.1, 0.1))
    src = write(tmp_path)
    out = tmp_path / "out.json"
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "-q",
            "finish the parser fix",
            "--mode",
            "tool-calls",
            "--preserve-recent",
            "0",
            "-o",
            str(out),
            "-r",
            str(report),
        ],
    )
    assert result.exit_code == 0, result.output
    messages = json.loads(out.read_text(encoding="utf-8"))
    assert [(message["role"], message.get("text", "")) for message in messages] == [
        ("user", "Fix the failing parser test. Never edit src/generated."),
        ("assistant", "Running the suite."),
    ]
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["tool_calls_dropped"] == 1
    assert data["semantic_guarantee"] == "judged"
    assert data["degraded"] is False


def test_report_reads_through_lcc_explain(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(transcript_module, "_resolve_client", lambda: Stub(0.9, 0.0))
    src = write(tmp_path)
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "-q",
            "finish the parser fix",
            "--mode",
            "tool-calls",
            "--preserve-recent",
            "0",
            "--trim-head-chars",
            "5",
            "-r",
            str(report),
        ],
    )
    assert result.exit_code == 0, result.output
    explained = runner.invoke(app, ["explain", str(report)])
    assert explained.exit_code == 0, explained.output
    assert "TRIMMED" in explained.output


def test_block_only_flags_are_refused_not_ignored(tmp_path: Path):
    src = write(tmp_path)
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "-q",
            "x",
            "--mode",
            "tool-calls",
            "--preserve-tail",
            "3",
            "--decisions-cache",
            str(tmp_path / "cache.jsonl"),
        ],
    )
    assert result.exit_code == 2
    assert "do not apply to --mode tool-calls" in result.output
    assert "--preserve-tail" in result.output


def test_a_judge_is_required(tmp_path: Path):
    src = write(tmp_path)
    result = runner.invoke(
        app, ["compact", str(src), "-q", "x", "--mode", "tool-calls", "--provider", "mechanical"]
    )
    assert result.exit_code == 2
    assert "cannot answer" in result.output


def test_a_non_json_input_is_reported_as_such(tmp_path: Path):
    src = write(tmp_path, payload=None, name="broken.json")
    src.write_text("not json at all", encoding="utf-8")
    result = runner.invoke(app, ["compact", str(src), "-q", "x", "--mode", "tool-calls"])
    assert result.exit_code == 2
    assert "JSON transcript" in result.output


def test_unknown_mode_is_refused(tmp_path: Path):
    src = write(tmp_path)
    result = runner.invoke(app, ["compact", str(src), "-q", "x", "--mode", "banana"])
    assert result.exit_code == 2
    assert "--mode must be" in result.output


def test_dry_run_writes_the_report_but_no_transcript(tmp_path: Path):
    src = write(tmp_path)
    out = tmp_path / "out.json"
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "-q",
            "x",
            "--mode",
            "tool-calls",
            "--dry-run",
            "-o",
            str(out),
            "-r",
            str(report),
        ],
    )
    assert result.exit_code == 0, result.output
    assert not out.exists()
    assert json.loads(report.read_text(encoding="utf-8"))["mode"] == "tool-calls"
