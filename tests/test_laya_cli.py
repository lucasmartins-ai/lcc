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

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["provider_requested"] == "laya"
    assert data["provider_used"] == "laya+mechanical_fallback"
    assert data["degraded"] is True
    assert data["degradation_reason"] == "laya_unavailable_mechanical_fallback"
    assert data["semantic_guarantee"] == "none"
    assert any("laya_unavailable" in w for w in data["warnings"])
    # Observability fields are present even on the fallback path.
    for field in ("provider_used", "latency_ms", "laya_model_requested"):
        assert field in data, field


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


def test_cli_compact_help_guides_provider_choice():
    res = runner.invoke(app, ["compact", "--help"])
    assert res.exit_code == 0
    out = res.stdout.lower()
    for cue in ("mechanical", "laya", "jev", "docs/laya.md", "degraded"):
        assert cue in out, cue


def test_laya_docs_cover_limits_and_tradeoff():
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[1]
    doc = (root / "docs" / "LAYA.md").read_text(encoding="utf-8").lower()
    for cue in ("512", "1024", "319", "831", "latency_ms", "when to use",
                "conservative", "context_budget_used", "degraded"):
        assert cue in doc, cue
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "docs/LAYA.md" in readme
    assert "relevance-compaction-1.2" in readme
