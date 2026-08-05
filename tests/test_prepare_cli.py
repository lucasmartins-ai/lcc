"""Tests for the deterministic prepare CLI orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc.cli import app
from lcc.inspection import InspectionRecommendation, inspect
from lcc.inspection.inspector import InspectionRequest

runner = CliRunner()

SKIP_INPUT = "One short note."

OPTIMIZE_INPUT = (
    "The quarterly migration status includes the same operational paragraph "
    "for every regional service owner and should only be kept once.\n\n" * 6
)


def test_prepare_skip_writes_inspection_report_without_prompt(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(SKIP_INPUT, encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    report = tmp_path / "prepare_report.json"

    result = runner.invoke(
        app,
        [
            "prepare",
            str(src),
            "--question",
            "Summarize.",
            "--output",
            str(prompt),
            "--report",
            str(report),
        ],
    )

    assert result.exit_code == 0
    assert not prompt.exists()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["recommendation"]["action"] == "skip"
    assert "safe_cleanup_projection" in data
    assert "No prompt generated" in result.stderr


def test_prepare_optimize_writes_prompt_and_optimization_report(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(OPTIMIZE_INPUT, encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    report = tmp_path / "optimization_report.json"

    result = runner.invoke(
        app,
        [
            "prepare",
            str(src),
            "--question",
            "Summarize the migration status.",
            "--model",
            "gpt-4.1",
            "--output",
            str(prompt),
            "--report",
            str(report),
        ],
    )

    assert result.exit_code == 0
    assert "Inspection decision: optimize_safe" in result.stderr
    assert "Summarize the migration status." in prompt.read_text(encoding="utf-8")
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["schema_version"] == "prepare-1.0"
    assert "optimized_token_count" in data["optimization"]
    assert data["inspection"]["recommendation"]["action"] == "optimize_safe"


def test_prepare_applies_question_aware_lexical_selection_when_optimizing(
    tmp_path: Path,
) -> None:
    src = tmp_path / "in.txt"
    src.write_text(
        (
            "# Billing Renewal\n\n"
            "Invoices renewal credits and payment collection notes for finance operations across all enterprise accounts.\n\n"
            "# OAuth Token Rotation\n\n"
            "Rotate OAuth tokens for service accounts every quarter without exception. "
            "Store token rotation evidence and compliance logs in the runbook.\n\n"
            "# General Notes\n\n"
            "Rotate OAuth tokens for service accounts every quarter without exception. "
            "Store token rotation evidence and compliance logs in the runbook.\n\n"
            "# Billing Archive\n\n"
            "Invoices renewal credits and payment collection notes for finance operations across all enterprise accounts.\n"
        ),
        encoding="utf-8",
    )
    prompt = tmp_path / "prompt.md"
    report = tmp_path / "prepare_report.json"

    result = runner.invoke(
        app,
        [
            "prepare",
            str(src),
            "--question",
            "What is the OAuth token rotation evidence?",
            "--model",
            "gpt-4.1",
            "--output",
            str(prompt),
            "--report",
            str(report),
        ],
    )

    assert result.exit_code == 0
    prompt_text = prompt.read_text(encoding="utf-8")
    assert "OAuth Token Rotation" in prompt_text
    assert "Store token rotation evidence and compliance logs in the runbook." in prompt_text
    assert "Billing Renewal" not in prompt_text
    assert "payment collection notes" not in prompt_text

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["selection"]["applied"] is True
    assert [chunk["reason_codes"] for chunk in data["selection"]["selected_chunks"]] == [
        ["heading_match"],
        ["keyword_overlap", "rare_term_match", "matched_heading_proximity"],
    ]
    assert data["selection"]["skipped_duplicate_chunk_ids"]


def test_prepare_stdin_skip_emits_inspection_report_to_stdout() -> None:
    result = runner.invoke(
        app,
        ["prepare", "-", "--question", "Summarize."],
        input=SKIP_INPUT,
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["input"]["source_type"] == "stdin"
    assert data["recommendation"]["action"] == "skip"
    assert "No prompt generated" in result.stderr


def test_prepare_uses_only_recommendation_action_to_decide_skip(
    monkeypatch, tmp_path: Path
) -> None:
    src = tmp_path / "in.txt"
    src.write_text(OPTIMIZE_INPUT, encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    report_path = tmp_path / "report.json"
    inspection_report = inspect(InspectionRequest(raw_text="One short note.", model="gpt-4.1"))
    inspection_report.recommendation = InspectionRecommendation(
        action="skip",
        reason_codes=["high_duplication", "missing_pricing"],
        summary="Skip despite optimization-looking reasons.",
        suggested_command='lcc optimize INPUT --model gpt-4.1 --question "..."',
    )

    def fail_if_optimized(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("prepare must not optimize when recommendation.action is skip")

    monkeypatch.setattr("lcc.cli.run_inspection", lambda *_args, **_kwargs: inspection_report)
    monkeypatch.setattr("lcc.cli.run_pipeline", fail_if_optimized)

    result = runner.invoke(
        app,
        [
            "prepare",
            str(src),
            "--question",
            "Summarize.",
            "--output",
            str(prompt),
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 0
    assert not prompt.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["recommendation"]["action"] == "skip"
    assert data["recommendation"]["reason_codes"] == ["high_duplication", "missing_pricing"]


@pytest.mark.parametrize("flag", ["--output", "--report"])
def test_prepare_rejects_paths_that_would_overwrite_input(tmp_path: Path, flag: str) -> None:
    src = tmp_path / "in.txt"
    src.write_text(OPTIMIZE_INPUT, encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        ["prepare", str(src), "--question", "Summarize.", flag, str(src)],
    )

    assert result.exit_code == 1
    assert src.read_text(encoding="utf-8") == before
