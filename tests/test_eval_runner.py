from __future__ import annotations

import json
from pathlib import Path

from act2_router.eval_runner import run_evaluation, write_reports


def test_eval_runner_writes_json_and_markdown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    case = tmp_path / "case.json"
    case.write_text(
        json.dumps(
            {
                "task_id": "case",
                "instruction": "What is the status?",
                "context": "The status is green.",
                "required_markers": ["status is green"],
            }
        ),
        encoding="utf-8",
    )

    report = run_evaluation(tmp_path)
    out = write_reports(report, tmp_path / "report.json")

    assert report["result"]["total_cases"] == 1
    assert out.exists()
    assert out.with_suffix(".md").exists()
    assert "Local development proxy" in out.with_suffix(".md").read_text(encoding="utf-8")
