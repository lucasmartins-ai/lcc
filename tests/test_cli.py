"""Tests for the Typer CLI (in-process, no subprocess)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from lcc.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "lcc" in result.stdout


def test_optimize_file(tmp_path: Path):
    src = tmp_path / "in.txt"
    src.write_text(
        "Hello world.\n\nHello world.\n\nKeep this distinct line of content here.",
        encoding="utf-8",
    )
    out = tmp_path / "prompt.md"
    rep = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "optimize",
            str(src),
            "--question",
            "Summarize.",
            "--model",
            "gpt-4.1",
            "--output",
            str(out),
            "--report",
            str(rep),
        ],
    )
    assert result.exit_code == 0
    assert out.exists()
    assert rep.exists()
    assert "Summarize." in out.read_text(encoding="utf-8")
    assert '"schema_version"' in rep.read_text(encoding="utf-8")


def test_optimize_stdin(tmp_path: Path):
    out = tmp_path / "prompt.md"
    result = runner.invoke(
        app,
        ["optimize", "-", "--question", "Q", "--output", str(out)],
        input="Some piped content.\n\nSome piped content.",
    )
    assert result.exit_code == 0
    assert out.exists()


def test_missing_file_exits_nonzero():
    result = runner.invoke(app, ["optimize", "/no/such/file.txt", "--question", "Q"])
    assert result.exit_code == 1


def test_unknown_template_exits_with_code_two(tmp_path: Path):
    src = tmp_path / "in.txt"
    src.write_text("content", encoding="utf-8")
    result = runner.invoke(app, ["optimize", str(src), "--template", "nope"])
    assert result.exit_code == 2
