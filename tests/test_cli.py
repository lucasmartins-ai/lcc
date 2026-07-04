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


def test_cli_help_states_phase_1_7_boundaries():
    prepare = runner.invoke(app, ["prepare", "--help"])
    inspect = runner.invoke(app, ["inspect", "--help"])
    bench = runner.invoke(app, ["bench", "--help"])

    assert prepare.exit_code == 0
    assert inspect.exit_code == 0
    assert bench.exit_code == 0

    prepare_words = " ".join(prepare.stdout.split())
    inspect_words = " ".join(inspect.stdout.split())
    bench_words = " ".join(bench.stdout.split())

    assert "question-aware lexical selection" in prepare_words
    assert "does not summarize, rewrite, or paraphrase source content" in prepare_words
    assert (
        "no semantic selection, embeddings, network access, local model call, or remote LLM call"
    ) in prepare_words

    assert "diagnostic only" in inspect_words
    assert "never builds or writes an optimized prompt" in inspect_words
    assert "makes no network, LLM, embedding, local model, or remote model call" in inspect_words

    assert "mechanical optimization and prepare-selection metrics" in bench_words
    assert "exact-vs-approximate counting" in bench_words
    assert "not LLM answer quality" in bench_words
