"""Tests for the deterministic inspection command and module (ADR 0009)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lcc.cli import app
from lcc.inspection import InspectionRequest, inspect, inspection_to_json
from lcc.inspection import inspector as inspector_module
from lcc.inspection.schemas import INSPECT_SCHEMA_VERSION
from lcc.token_budget.counters import count_tokens

runner = CliRunner()

# A small input with exact duplicates, a near-duplicate (trailing "!"), and boilerplate.
SAMPLE = (
    "The migration is now eighty percent complete across the reporting service.\n\n"
    "The migration is now eighty percent complete across the reporting service.\n\n"
    "The migration is now eighty percent complete across the reporting service!\n\n"
    "Sent from my iPhone\n\n"
    "A genuinely distinct closing remark about the on-call runbook.\n"
)

INVENTORY_SAMPLE = (
    "# Overview\n\n"
    "First paragraph spans\n"
    "two lines.\n\n"
    "# Details\n\n"
    "Repeated paragraph for inventory.\n\n"
    "Repeated paragraph for inventory.\n"
)


def _req(text: str = SAMPLE, **kwargs: object) -> InspectionRequest:
    fields: dict[str, object] = {"raw_text": text, "model": "gpt-4.1"}
    fields.update(kwargs)
    return InspectionRequest(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- module


def test_file_input_success_shape() -> None:
    report = inspect(_req())
    assert report.schema_version == INSPECT_SCHEMA_VERSION == "1.0"
    assert report.input.source_type == "file"
    assert report.input.character_count == len(SAMPLE)
    assert report.input.paragraph_count == 5
    assert report.token_budget.model == "gpt-4.1"
    assert report.token_budget.token_count > 0
    # Exact duplicates + the near-duplicate should be projected away.
    assert report.duplication.exact_duplicates_removed >= 1
    assert report.duplication.near_duplicates_removed >= 1


def test_stdin_source_type() -> None:
    report = inspect(_req(source_type="stdin"))
    assert report.input.source_type == "stdin"


def test_empty_input_is_valid_report_with_warning() -> None:
    report = inspect(_req(text=""))
    assert report.input.character_count == 0
    assert report.token_budget.token_count == 0
    assert report.safe_cleanup_projection.projected_token_savings_percent == 0.0
    assert report.duplication.duplicate_ratio == 0.0
    assert any("empty" in warning.lower() for warning in report.warnings)


def test_whitespace_only_input_does_not_crash() -> None:
    report = inspect(_req(text="   \n\n\t\n"))
    assert report.safe_cleanup_projection.projected_tokens_after_safe_cleaning == 0
    assert any("empty" in warning.lower() for warning in report.warnings)


def test_report_is_deterministic_across_runs() -> None:
    assert inspection_to_json(inspect(_req())) == inspection_to_json(inspect(_req()))


def test_report_has_no_timestamps_or_unstable_fields() -> None:
    payload = inspection_to_json(inspect(_req())).lower()
    for banned in ("timestamp", "generated_at", "datetime", "created", "hostname"):
        assert banned not in payload
    assert '"schema_version": "1.0"' in inspection_to_json(inspect(_req()))


def test_report_has_no_absolute_paths(tmp_path: Path) -> None:
    src = tmp_path / "secret_dir" / "in.txt"
    src.parent.mkdir(parents=True)
    src.write_text(SAMPLE, encoding="utf-8")
    result = runner.invoke(app, ["inspect", str(src), "--report", str(tmp_path / "r.json")])
    assert result.exit_code == 0
    payload = (tmp_path / "r.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in payload
    assert "secret_dir" not in payload
    assert "/Users/" not in payload and "/home/" not in payload


def test_chunk_inventory_exposes_stable_structural_spans() -> None:
    report = inspect(_req(text=INVENTORY_SAMPLE))
    inventory = report.chunk_inventory

    assert [chunk.index for chunk in inventory] == [0, 1, 2, 3, 4]
    assert [chunk.label for chunk in inventory] == [
        "heading",
        "paragraph_block",
        "heading",
        "paragraph_block",
        "paragraph_block",
    ]
    assert all(chunk.id.startswith(f"chunk_{chunk.index + 1:04d}_") for chunk in inventory)

    first = inventory[0]
    assert first.heading_text == "Overview"
    assert first.character_start == 0
    assert INVENTORY_SAMPLE[first.character_start : first.character_end] == "# Overview"
    assert first.line_start == 1
    assert first.line_end == 1
    assert first.line_count == 1
    assert first.paragraph_count == 0
    assert first.character_count == len("# Overview")

    paragraph = inventory[1]
    assert INVENTORY_SAMPLE[paragraph.character_start : paragraph.character_end] == (
        "First paragraph spans\ntwo lines."
    )
    assert paragraph.line_start == 3
    assert paragraph.line_end == 4
    assert paragraph.line_count == 2
    assert paragraph.paragraph_count == 1
    assert paragraph.heading_text is None

    expected_tokens = count_tokens(
        INVENTORY_SAMPLE[paragraph.character_start : paragraph.character_end],
        "gpt-4.1",
    )
    assert paragraph.token_count == expected_tokens.value
    assert paragraph.token_count_method == expected_tokens.method.value


def test_chunk_inventory_marks_exact_duplicate_blocks() -> None:
    inventory = inspect(_req(text=INVENTORY_SAMPLE)).chunk_inventory

    first_repeated = inventory[3]
    second_repeated = inventory[4]

    assert first_repeated.is_duplicate is False
    assert first_repeated.duplicate_of is None
    assert second_repeated.is_duplicate is True
    assert second_repeated.duplicate_of == first_repeated.id


def test_chunk_inventory_is_machine_readable_additive_and_deterministic() -> None:
    first_json = inspection_to_json(inspect(_req(text=INVENTORY_SAMPLE)))
    second_json = inspection_to_json(inspect(_req(text=INVENTORY_SAMPLE)))
    data = json.loads(first_json)

    assert first_json == second_json
    assert data["schema_version"] == "1.0"
    assert "chunk_inventory" in data
    assert data["chunk_inventory"][0]["heading_text"] == "Overview"
    assert "First paragraph spans" not in first_json


def test_token_method_is_surfaced_honestly() -> None:
    # The report must echo exactly what count_tokens determined (exact or approximate),
    # never upgrade an approximation to exact (ADR 0005, ADR 0008).
    report = inspect(_req())
    truth = count_tokens(SAMPLE, "gpt-4.1")
    assert report.token_budget.token_count_method == truth.method.value
    assert report.token_budget.token_count == truth.value
    assert report.token_budget.tokenizer == truth.counter
    assert report.token_budget.token_encoding == truth.encoding


def test_unknown_model_is_approximate_with_warning() -> None:
    report = inspect(_req(model="totally-unknown-model"))
    assert report.token_budget.token_count_method == "approximate"
    assert any("approximate" in warning.lower() for warning in report.warnings)


def test_approximate_fallback_emits_warning(monkeypatch) -> None:
    # Force the heuristic fallback (as if tiktoken were unavailable) and confirm the report
    # both labels the mode approximate and warns honestly.
    from lcc.token_budget import counters

    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", False)
    report = inspect(_req())
    assert report.token_budget.token_count_method == "approximate"
    assert report.token_budget.tokenizer == "heuristic"
    assert any("approximate" in warning.lower() for warning in report.warnings)


def test_projection_reduces_or_preserves_tokens() -> None:
    projection = inspect(_req()).safe_cleanup_projection
    assert projection.projected_tokens_after_safe_cleaning <= projection.original_tokens
    assert projection.projected_token_savings_percent >= 0.0


def test_already_clean_text_preserves_tokens() -> None:
    clean = "One unique sentence.\n\nA different unique sentence.\n"
    projection = inspect(_req(text=clean)).safe_cleanup_projection
    assert projection.projected_tokens_after_safe_cleaning == projection.original_tokens
    assert projection.projected_token_savings_percent == 0.0


def test_missing_pricing_omits_cost_with_warning() -> None:
    report = inspect(_req(model="totally-unknown-model"))
    assert report.token_budget.estimated_input_cost is None
    assert report.token_budget.pricing_found is False
    assert any("pricing" in warning.lower() for warning in report.warnings)


def test_small_input_recommends_skip() -> None:
    report = inspect(_req(text="One short note."))
    assert report.recommendation.action == "skip"
    assert "small_input" in report.recommendation.reason_codes
    assert report.recommendation.suggested_command is None


def test_high_duplication_recommends_optimize_safe() -> None:
    duplicated = (
        "The quarterly migration status includes the same operational paragraph "
        "for every regional service owner and should only be kept once.\n\n" * 6
    )
    report = inspect(_req(text=duplicated))
    assert report.recommendation.action == "optimize_safe"
    assert "high_duplication" in report.recommendation.reason_codes
    assert report.recommendation.suggested_command is not None
    assert report.recommendation.suggested_command.startswith("lcc optimize INPUT")


def _signal(report, code: str):
    signals = {signal.code: signal for signal in report.recommendation.scoring_signals}
    return signals[code]


def test_recommendation_scoring_signals_are_stable_and_auditable() -> None:
    duplicated = (
        "The quarterly migration status includes the same operational paragraph "
        "for every regional service owner and should only be kept once.\n\n" * 6
    )

    report = inspect(_req(text=duplicated))

    assert [signal.code for signal in report.recommendation.scoring_signals] == [
        "duplication_pressure",
        "projected_token_savings",
        "token_budget_pressure",
        "missing_pricing",
        "approximate_token_count",
        "manual_review_risk",
    ]
    duplication = _signal(report, "duplication_pressure")
    assert duplication.reason_code == "high_duplication"
    assert duplication.triggered is True
    assert duplication.thresholds["high_duplication_ratio"] == 0.2
    assert duplication.evidence["duplicate_ratio"] == report.duplication.duplicate_ratio

    projected_savings = _signal(report, "projected_token_savings")
    assert projected_savings.reason_code in {"high_projected_savings", "low_projected_savings"}
    assert projected_savings.thresholds["high_savings_percent"] == 15.0
    assert projected_savings.thresholds["high_savings_tokens"] == 50
    assert projected_savings.thresholds["low_savings_percent"] == 5.0
    assert projected_savings.thresholds["low_savings_tokens"] == 20
    assert (
        projected_savings.evidence["projected_token_savings_percent"]
        == report.safe_cleanup_projection.projected_token_savings_percent
    )


def test_missing_pricing_signal_carries_reason_threshold_and_suggestion() -> None:
    duplicated = (
        "The quarterly migration status includes the same operational paragraph "
        "for every regional service owner and should only be kept once.\n\n" * 6
    )

    report = inspect(_req(text=duplicated, pricing={}))
    signal = _signal(report, "missing_pricing")

    assert report.recommendation.action == "optimize_with_flags"
    assert signal.triggered is True
    assert signal.reason_code == "missing_pricing"
    assert signal.thresholds["pricing_required_for_cost_estimate"] is True
    assert signal.evidence["pricing_found"] is False
    assert report.recommendation.suggested_command is not None
    assert "--pricing <pricing.yaml>" in report.recommendation.suggested_command


def test_approximate_token_count_signal_carries_reason_threshold_and_evidence(monkeypatch) -> None:
    from lcc.token_budget import counters

    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", False)
    report = inspect(_req())
    signal = _signal(report, "approximate_token_count")

    assert signal.triggered is True
    assert signal.reason_code == "approximate_token_count"
    assert signal.thresholds["trigger_when_token_count_method"] == "approximate"
    assert signal.evidence["token_count_method"] == "approximate"


def test_token_budget_and_manual_review_thresholds_are_auditable(monkeypatch) -> None:
    monkeypatch.setattr(inspector_module, "_MAX_INPUT_RISK_TOKENS", 10)
    monkeypatch.setattr(inspector_module, "_TOKEN_BUDGET_PRESSURE_RATIO", 0.5, raising=False)
    text = " ".join(f"term{i}" for i in range(40))

    report = inspect(_req(text=text))
    budget_pressure = _signal(report, "token_budget_pressure")
    manual_review = _signal(report, "manual_review_risk")

    assert report.recommendation.action == "manual_review"
    assert budget_pressure.triggered is True
    assert budget_pressure.reason_code == "token_budget_pressure"
    assert budget_pressure.thresholds["pressure_ratio"] == 0.5
    assert budget_pressure.thresholds["max_input_risk_tokens"] == 10
    assert manual_review.triggered is True
    assert manual_review.reason_code == "max_input_risk"
    assert manual_review.thresholds["max_input_risk_tokens"] == 10


def test_low_projected_savings_recommends_skip() -> None:
    clean = "\n\n".join(
        [
            "Architecture notes describe module boundaries and import direction.",
            "Release planning lists packaging checks and changelog responsibilities.",
            "Security guidance focuses on local files, reports, and prompt artifacts.",
            "Benchmark fixtures preserve literal evidence markers during cleanup.",
            "Pricing documentation says bundled values are editable examples.",
            "Tokenizer behavior falls back honestly when cached assets are absent.",
            "CLI output keeps machine-readable JSON separate from terminal summaries.",
            "Roadmap entries keep future retrieval and verification out of the MVP.",
            "Evaluation guidance separates mechanical savings from answer quality.",
            "Configuration defaults can be overridden without changing source code.",
            "Inspection reports avoid timestamps, hostnames, and absolute paths.",
            "Formatting rules rely on ruff with a one hundred character line length.",
        ]
    )
    report = inspect(_req(text=clean))
    assert report.recommendation.action == "skip"
    assert "low_projected_savings" in report.recommendation.reason_codes
    assert report.recommendation.suggested_command is None


def test_approximate_token_count_adds_recommendation_reason(monkeypatch) -> None:
    from lcc.token_budget import counters

    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", False)
    report = inspect(_req())
    assert report.token_budget.token_count_method == "approximate"
    assert "approximate_token_count" in report.recommendation.reason_codes


def test_stage_contributions_include_each_safe_cleanup_step() -> None:
    stages = inspect(_req()).safe_cleanup_projection.stage_contributions
    assert [stage.stage for stage in stages] == [
        "normalization",
        "boilerplate",
        "exact_deduplication",
        "near_deduplication",
    ]


def test_inspect_does_not_modify_input_file(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    before = src.read_bytes()
    inspect(_req())  # module call cannot touch a file at all
    result = runner.invoke(app, ["inspect", str(src), "--report", str(tmp_path / "r.json")])
    assert result.exit_code == 0
    assert src.read_bytes() == before


def test_cli_inspect_rejects_report_path_that_is_input_file(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    before = src.read_bytes()

    result = runner.invoke(app, ["inspect", str(src), "--report", str(src)])

    assert result.exit_code == 1
    assert src.read_bytes() == before


# ------------------------------------------------------------------------------- cli


def test_cli_inspect_file_success(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    rep = tmp_path / "report.json"
    result = runner.invoke(app, ["inspect", str(src), "--model", "gpt-4.1", "--report", str(rep)])
    assert result.exit_code == 0
    assert rep.exists()
    data = json.loads(rep.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["input"]["source_type"] == "file"
    assert "safe_cleanup_projection" in data
    assert "chunk_inventory" in data


def test_cli_inspect_json_to_stdout_when_no_report() -> None:
    result = runner.invoke(app, ["inspect", "-"], input=SAMPLE)
    assert result.exit_code == 0
    assert '"schema_version": "1.0"' in result.stdout


def test_cli_inspect_stdin_success() -> None:
    result = runner.invoke(app, ["inspect", "-", "--model", "gpt-4.1"], input="hello world content")
    assert result.exit_code == 0


def test_cli_inspect_empty_stdin_succeeds() -> None:
    result = runner.invoke(app, ["inspect", "-"], input="")
    assert result.exit_code == 0
    assert '"schema_version": "1.0"' in result.stdout


def test_cli_inspect_compact_summary(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(
        (
            "The quarterly migration status includes the same operational paragraph "
            "for every regional service owner and should only be kept once.\n\n" * 6
        ),
        encoding="utf-8",
    )
    rep = tmp_path / "report.json"

    result = runner.invoke(app, ["inspect", str(src), "--report", str(rep), "--summary", "compact"])

    assert result.exit_code == 0
    assert "Decision: optimize_safe" in result.stderr
    assert "Tokens:" in result.stderr
    assert "Projected savings:" in result.stderr
    assert "Next: lcc optimize INPUT" in result.stderr
    data = json.loads(rep.read_text(encoding="utf-8"))
    assert data["recommendation"]["action"] == "optimize_safe"


def test_cli_inspect_missing_file_exits_nonzero() -> None:
    result = runner.invoke(app, ["inspect", "/no/such/file.txt"])
    assert result.exit_code == 1


def test_cli_inspect_directory_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["inspect", str(tmp_path)])
    assert result.exit_code == 1


def test_cli_inspect_bad_report_path_exits_nonzero(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    bad = tmp_path / "no_such_dir" / "report.json"  # parent does not exist
    result = runner.invoke(app, ["inspect", str(src), "--report", str(bad)])
    assert result.exit_code == 1
