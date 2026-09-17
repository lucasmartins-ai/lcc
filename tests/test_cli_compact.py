"""CLI tests for `lcc compact` and intake relevance wiring (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lcc.cli import app

runner = CliRunner()

SAMPLE = (
    "Mission: reduce mobile booking friction.\n\n"
    "Funnel metric block: 38% of mobile users abandon at the date picker step today.\n\n"
    "Office noise block: the coffee machine repair needs a part and the plants need water.\n"
)


def test_compact_mechanical_writes_output_and_report(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / "out.md"
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "--question",
            "reduce mobile booking friction funnel",
            "--provider",
            "mechanical",
            "--output",
            str(out),
            "--report",
            str(report),
        ],
    )
    assert result.exit_code == 0
    assert out.exists()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["schema_version"] == "relevance-compaction-1.1"
    assert data["provider_used"] == "mechanical"
    assert "first_mutation_offset" in data
    assert "prefix_sha256" in data
    assert data["reduction_ratio"] >= 0.0
    assert "worth_it" in data
    assert data["trim_head_chars"] == 300
    assert data["blocks_trimmed"] == 0


def test_compact_accepts_trim_tail_and_worker_flags(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    report = tmp_path / "r.json"
    result = runner.invoke(
        app,
        [
            "compact",
            str(src),
            "--question",
            "reduce mobile booking friction funnel",
            "--provider",
            "mechanical",
            "--trim-head-chars",
            "0",
            "--trim-threshold",
            "0.2",
            "--preserve-tail",
            "1",
            "--max-workers",
            "2",
            "--min-reduction",
            "0.1",
            "--report",
            str(report),
        ],
    )
    assert result.exit_code == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["trim_head_chars"] == 0
    assert data["trim_threshold"] is None
    assert data["blocks_trimmed"] == 0
    assert data["min_reduction"] == 0.1


def test_compact_rejects_bad_worker_count(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(
        app, ["compact", str(src), "--question", "x", "--max-workers", "99"]
    )
    assert result.exit_code == 2


def test_compact_requires_question(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(app, ["compact", str(src), "--provider", "mechanical"])
    assert result.exit_code != 0


def test_compact_rejects_unknown_provider(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(
        app, ["compact", str(src), "--question", "x", "--provider", "wat"]
    )
    assert result.exit_code == 2


def test_intake_with_mechanical_relevance(tmp_path: Path):
    src = tmp_path / "intake.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "intake",
            str(src),
            "--enable-relevance",
            "--relevance-provider",
            "mechanical",
        ],
    )
    assert result.exit_code == 0
    assert "lcc-intake:readiness" in result.stdout


def test_intake_without_relevance_unchanged(tmp_path: Path):
    src = tmp_path / "intake.md"
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(app, ["intake", str(src)])
    assert result.exit_code == 0
