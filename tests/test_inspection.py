"""Tests for the deterministic inspection command and module (ADR 0009)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lcc.cli import app
from lcc.inspection import InspectionRequest, inspect, inspection_to_json
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
