"""Tests for `lcc explain` and the report explanation renderer."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lcc.cli import app
from lcc.reporting.explain import explain_reason, render, summarize

runner = CliRunner()

CORPUS = (
    "SYSTEM CONTRACT (stable reference, must never be dropped)\n"
    "You are the analyst. Answer only from the evidence.\n\n"
    "The clinic booking widget loses 63 percent of mobile visitors before the second step.\n\n"
    "LOG 1: queue worker heartbeat ok in 554ms, backlog 287 jobs, retry budget untouched.\n\n"
    "LOG 2: cron job lead-sync finished with 366 records processed and 3377 ms elapsed.\n"
)

REPORT = {
    "schema_version": "relevance-compaction-1.1",
    "objective": "what is the mobile conversion problem",
    "provider_requested": "jev",
    "provider_used": "jev",
    "degraded": False,
    "semantic_guarantee": "judged",
    "threshold": 0.4,
    "trim_threshold": 0.2,
    "trim_head_chars": 300,
    "blocks_total": 3,
    "blocks_scored": 3,
    "blocks_protected": 0,
    "blocks_dropped": 2,
    "blocks_trimmed": 0,
    "chars_before": 1000,
    "chars_after": 400,
    "chars_removed": 600,
    "tokens_before": 250,
    "tokens_after": 100,
    "token_count_method": "exact",
    "reduction_ratio": 0.6,
    "worth_it": True,
    "min_reduction": 0.25,
    "calls": 2,
    "latency_ms": 900,
    "reused_decisions": 0,
    "prefix_protected": False,
    "prefix_untouched": False,
    "first_mutation_offset": 120,
    "invalidated_tokens": 80,
    "break_even_reuses": 4.2,
    "prefix_sha256": "a" * 64,
    "output_sha256": "b" * 64,
    "degradation_reason": None,
    "warnings": ["cache_epoch_risk: example warning"],
    "decisions": [
        {
            "id": "blk_0001_aaaaaaaaaaaa",
            "index": 1,
            "line_start": 1,
            "line_end": 2,
            "chars": 120,
            "decision": "keep",
            "source": "jev",
            "score": 0.91,
            "reason": "score_above_threshold",
            "chars_after": None,
        },
        {
            "id": "blk_0002_bbbbbbbbbbbb",
            "index": 2,
            "line_start": 4,
            "line_end": 4,
            "chars": 90,
            "decision": "drop",
            "source": "jev",
            "score": 0.04,
            "reason": "score_below_threshold",
            "chars_after": None,
        },
        {
            "id": "blk_0003_cccccccccccc",
            "index": 3,
            "line_start": 6,
            "line_end": 6,
            "chars": 110,
            "decision": "drop",
            "source": "mechanical",
            "score": 0.0,
            "reason": "evidence_in_pt_not_en",
            "chars_after": None,
        },
    ],
}


def test_explain_reason_covers_known_dynamic_unknown_and_missing():
    assert "keep threshold" in explain_reason("score_above_threshold")
    assert "another language" in explain_reason("evidence_in_pt_not_en")
    assert "pt_not_en" in explain_reason("evidence_in_pt_not_en")
    assert "distinctive terms" in explain_reason("link_terms:checkout,flow,june")
    assert explain_reason("something_new") == "recorded as 'something_new'"
    assert explain_reason(None) == "no reason recorded"


def test_summarize_reports_the_headline_numbers():
    rows = dict(summarize(REPORT))
    assert rows["Objective"] == "what is the mobile conversion problem"
    assert "jev" in rows["Provider"]
    assert rows["Semantic guarantee"] == "judged"
    assert "keep >= 0.40" in rows["Thresholds"] and "trim 0.20-0.40" in rows["Thresholds"]
    assert rows["Decisions"] == "1 keep | 0 trim | 2 drop"
    assert "60.0% smaller" in rows["Chars"]
    assert "(exact)" in rows["Tokens"]
    assert "pays off after ~4.2 reuses" in rows["Cache"]
    assert rows["Verdict"] == "worth a cache epoch"


def test_summarize_flags_degrades_and_bad_verdicts():
    degraded = dict(REPORT, degraded=True, degradation_reason="jev_unavailable", worth_it=False)
    rows = dict(summarize(degraded))
    assert rows["Degraded"] == "jev_unavailable"
    assert "NOT worth" in rows["Verdict"]


def test_render_lists_every_group_with_a_reason():
    text = render(REPORT)
    assert "DROPPED (2)" in text
    assert "KEPT (1)" in text
    assert "scored below the drop threshold" in text
    assert "another language" in text
    assert "WARNINGS (1)" in text
    assert "cache_epoch_risk" in text


def test_render_only_filters_to_one_group():
    text = render(REPORT, only="drop")
    assert "DROPPED (2)" in text
    assert "KEPT" not in text
    assert "blk_0001_aaaaaaaaaaaa" not in text


def test_render_rejects_an_unknown_group():
    try:
        render(REPORT, only="maybe")
    except ValueError as exc:
        assert "expected keep, trim or drop" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("an unknown --only value must be rejected")


def test_render_limit_caps_each_group():
    text = render(REPORT, limit=1)
    assert "blk_0002_bbbbbbbbbbbb" in text
    assert "blk_0003_cccccccccccc" not in text
    assert "limited to 1 per group" in text


def test_render_shows_the_text_behind_each_decision_when_given_the_source():
    text = render(REPORT, source_text=CORPUS)
    assert "text: SYSTEM CONTRACT" in text
    assert "63 percent" in text


def test_render_omits_previews_without_a_source():
    assert "text:" not in render(REPORT)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_explains_a_real_report_end_to_end(tmp_path: Path):
    corpus = _write(tmp_path, "in.md", CORPUS)
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "compact", str(corpus),
            "--question", "mobile conversion problem booking",
            "--provider", "mechanical",
            "-o", str(tmp_path / "out.md"),
            "-r", str(report),
        ],
    )
    assert result.exit_code == 0, result.output

    explained = runner.invoke(
        app, ["explain", str(report), "--source", str(corpus), "--limit", "2"]
    )
    assert explained.exit_code == 0, explained.output
    assert "why every block was kept" in explained.output
    assert "Semantic guarantee" in explained.output
    assert "why:" in explained.output


def test_cli_rejects_a_file_that_is_not_a_report(tmp_path: Path):
    not_a_report = _write(tmp_path, "other.json", json.dumps({"schema_version": "1.0"}))
    result = runner.invoke(app, ["explain", str(not_a_report)])
    assert result.exit_code == 1
    assert "no 'decisions' key" in result.output


def test_cli_rejects_malformed_json(tmp_path: Path):
    broken = _write(tmp_path, "broken.json", "{not json")
    result = runner.invoke(app, ["explain", str(broken)])
    assert result.exit_code == 1
    assert "not valid JSON" in result.output


def test_cli_rejects_an_unknown_group_and_a_zero_limit(tmp_path: Path):
    report = _write(tmp_path, "report.json", json.dumps(REPORT))
    bad_group = runner.invoke(app, ["explain", str(report), "--only", "maybe"])
    assert bad_group.exit_code == 2
    bad_limit = runner.invoke(app, ["explain", str(report), "--limit", "0"])
    assert bad_limit.exit_code == 2
    assert "--limit must be at least 1" in bad_limit.output


def test_explain_is_registered_in_the_cli():
    listed = runner.invoke(app, ["--help"])
    assert "explain" in listed.output
