"""CLI tests for Laya local semantic decision backend."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from lcc.cli import app
from lcc.relevance.laya import LayaClient

runner = CliRunner()

SAMPLE_TEXT = (
    "Intro block: alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha.\n\n"
    "This block is relevant to the objective and must survive the entire pass without any edits.\n\n"
    "Noise block: zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz.\n\n"
    "Another relevant line about the objective and the booking funnel details across mobile users.\n"
)


class MockLayaAgent:
    """Mock agent for CLI testing without loading real PyTorch weights."""

    def predict(self, state, questions):
        answers = {}
        for qid in questions:
            # Drop the noise block
            is_noise = "zzz" in str(state) and "blk_0003" in qid
            answers[qid] = {
                "type": "noul",
                "noul": 0.05 if is_noise else 0.9,
                "confidence": 0.95,
                "action": "drop" if is_noise else "keep",
            }
        return {
            "answers": answers,
            "usage": {"tokens": 80},
            "model": "convaiinnovations/laya-multilingual",
        }


def test_cli_compact_provider_laya_fail_safe(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE_TEXT, encoding="utf-8")
    out = tmp_path / "out.md"
    report = tmp_path / "report.json"

    # Patch resolver to return None (simulating dependencies missing / model not downloaded)
    with patch("lcc.relevance.compactor._resolve_laya_client", return_value=None):
        result = runner.invoke(
            app,
            [
                "compact",
                str(src),
                "--question",
                "booking funnel objective",
                "--provider",
                "laya",
                "--output",
                str(out),
                "--report",
                str(report),
            ],
        )

    assert result.exit_code == 0
    assert out.exists()
    assert out.read_text(encoding="utf-8") == SAMPLE_TEXT

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["provider_requested"] == "laya"
    assert data["provider_used"] == "degraded"
    assert data["degraded"] is True
    assert data["degradation_reason"] == "laya_unavailable"
    assert data["blocks_dropped"] == 0


def test_cli_compact_provider_laya_with_mock_client(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE_TEXT, encoding="utf-8")
    out = tmp_path / "out.md"
    report = tmp_path / "report.json"

    mock_client = LayaClient(
        model="convaiinnovations/laya-multilingual",
        agent=MockLayaAgent(),
    )

    with patch("lcc.relevance.compactor._resolve_laya_client", return_value=mock_client):
        result = runner.invoke(
            app,
            [
                "compact",
                str(src),
                "--question",
                "booking funnel objective",
                "--provider",
                "laya",
                "--laya-model",
                "convaiinnovations/laya-multilingual",
                "--laya-device",
                "cpu",
                "--output",
                str(out),
                "--report",
                str(report),
            ],
        )

    assert result.exit_code == 0
    assert out.exists()

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["provider_requested"] == "laya"
    assert data["provider_used"] == "laya"
    assert data["blocks_dropped"] >= 1
    assert "This block is relevant" in out.read_text(encoding="utf-8")
    assert "zzz zzz" not in out.read_text(encoding="utf-8")


def test_cli_explain_with_laya_report(tmp_path: Path):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE_TEXT, encoding="utf-8")
    report_path = tmp_path / "report.json"

    mock_client = LayaClient(
        model="convaiinnovations/laya-multilingual",
        agent=MockLayaAgent(),
    )

    with patch("lcc.relevance.compactor._resolve_laya_client", return_value=mock_client):
        res = runner.invoke(
            app,
            [
                "compact",
                str(src),
                "--question",
                "booking funnel objective",
                "--provider",
                "laya",
                "--report",
                str(report_path),
            ],
        )
        assert res.exit_code == 0

    explain_res = runner.invoke(
        app,
        [
            "explain",
            str(report_path),
            "--source",
            str(src),
        ],
    )

    assert explain_res.exit_code == 0
    explain_out = explain_res.stdout
    assert "laya" in explain_out.lower()
