"""Tests for the deterministic benchmark harness (ADR 0007)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc.benchmarking import (
    BenchmarkCase,
    BenchmarkCaseError,
    BenchmarkExpectations,
    find_markers,
    load_case,
    load_suite,
    run_case,
    run_suite,
    suite_to_json,
)
from lcc.cli import app
from lcc.schemas import TokenCountMethod
from lcc.token_budget.counters import count_tokens

HAS_TIKTOKEN = importlib.util.find_spec("tiktoken") is not None
REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_CASES = REPO_ROOT / "benchmarks" / "cases"

runner = CliRunner()


def _exact_available_offline() -> bool:
    """True only when tiktoken can build gpt-4.1's encoding from a local cache (no network).

    Exact-mode benchmark cases require cached tokenizer assets (ADR 0008); lcc never fetches
    them over the network, so without a populated cache counting falls back to approximate.
    """
    if not HAS_TIKTOKEN:
        return False
    return count_tokens("probe", model="gpt-4.1").method is TokenCountMethod.EXACT


def _write_case(case_dir: Path, *, case_yaml: str, input_text: str = "x\n") -> Path:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "case.yaml").write_text(case_yaml, encoding="utf-8")
    (case_dir / "input.txt").write_text(input_text, encoding="utf-8")
    return case_dir


def _case(**kwargs: object) -> BenchmarkCase:
    """Build an in-memory case. Defaults to an unknown model (always approximate) so unit
    tests do not depend on whether tiktoken is installed."""
    fields: dict[str, object] = {
        "id": "t",
        "description": "d",
        "question": "Q",
        "input_text": "x\n",
        "model": "local-unknown-model",
    }
    fields.update(kwargs)
    expectations = fields.pop("expectations", None) or BenchmarkExpectations(
        allow_approximate_token_count=True
    )
    return BenchmarkCase(expectations=expectations, **fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- loading


def test_load_case_parses_fields(tmp_path: Path) -> None:
    cdir = _write_case(
        tmp_path / "demo",
        case_yaml=(
            "id: demo\n"
            "description: A demo case.\n"
            "question: What changed?\n"
            "model: gpt-4.1\n"
            "max_input_tokens: 6000\n"
            "compression_level: safe\n"
            "required_markers:\n"
            "  - KEEP-ME\n"
            "forbidden_markers:\n"
            "  - DROP-ME\n"
            "expectations:\n"
            "  min_token_savings_percent: 10.0\n"
            "  max_token_savings_percent: 90.0\n"
            "  min_required_marker_recall: 1.0\n"
            "  allow_approximate_token_count: true\n"
        ),
        input_text="KEEP-ME line.\n",
    )
    case = load_case(cdir)
    assert case.id == "demo"
    assert case.model == "gpt-4.1"
    assert case.max_input_tokens == 6000
    assert case.required_markers == ["KEEP-ME"]
    assert case.forbidden_markers == ["DROP-ME"]
    assert case.expectations.allow_approximate_token_count is True
    assert case.input_text == "KEEP-ME line.\n"


def test_missing_input_file_raises(tmp_path: Path) -> None:
    cdir = tmp_path / "noinput"
    cdir.mkdir()
    (cdir / "case.yaml").write_text("id: x\ndescription: d\nquestion: q\n", encoding="utf-8")
    with pytest.raises(BenchmarkCaseError):
        load_case(cdir)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    cdir = _write_case(tmp_path / "bad", case_yaml="description: d\nquestion: q\n")
    with pytest.raises(BenchmarkCaseError):
        load_case(cdir)


def test_unknown_compression_level_raises(tmp_path: Path) -> None:
    cdir = _write_case(
        tmp_path / "lvl",
        case_yaml="id: x\ndescription: d\nquestion: q\ncompression_level: extreme\n",
    )
    with pytest.raises(BenchmarkCaseError):
        load_case(cdir)


def test_unknown_expectation_key_raises(tmp_path: Path) -> None:
    cdir = _write_case(
        tmp_path / "exp",
        case_yaml="id: x\ndescription: d\nquestion: q\nexpectations:\n  bogus: 1\n",
    )
    with pytest.raises(BenchmarkCaseError):
        load_case(cdir)


# --------------------------------------------------------------------------- markers


def test_find_markers_literal_substring() -> None:
    found, missing = find_markers("alpha beta", ["alpha", "gamma"])
    assert found == ["alpha"]
    assert missing == ["gamma"]


def test_required_marker_preserved_and_forbidden_removed() -> None:
    text = (
        "Keep token ABC-123 in the evidence record.\n\n"
        "Keep token ABC-123 in the evidence record.\n\n"
        "Sent from my iPhone\n"
    )
    case = _case(
        input_text=text,
        required_markers=["ABC-123"],
        forbidden_markers=["Sent from my iPhone"],
    )
    result = run_case(case)
    assert result.required_marker_recall == 1.0
    assert result.required_markers_found == ["ABC-123"]
    assert result.forbidden_markers_found == []
    assert result.passed


# --------------------------------------------------------------------- threshold gates


def test_savings_below_min_fails() -> None:
    case = _case(
        input_text="Unique line one here.\n\nA different unique line two.\n",
        expectations=BenchmarkExpectations(
            min_token_savings_percent=50.0, allow_approximate_token_count=True
        ),
    )
    result = run_case(case)
    assert not result.passed
    assert any("below the minimum" in reason for reason in result.failure_reasons)


def test_savings_above_max_fails() -> None:
    case = _case(
        input_text="Repeated identical paragraph here for dedup.\n\n" * 4,
        expectations=BenchmarkExpectations(
            max_token_savings_percent=5.0, allow_approximate_token_count=True
        ),
    )
    result = run_case(case)
    assert not result.passed
    assert any("above the maximum" in reason for reason in result.failure_reasons)


def test_missing_required_marker_fails() -> None:
    case = _case(
        input_text="some content without the marker phrase\n",
        required_markers=["NOPE-999"],
        expectations=BenchmarkExpectations(allow_approximate_token_count=True),
    )
    result = run_case(case)
    assert not result.passed
    assert result.required_marker_recall == 0.0
    assert any("recall" in reason for reason in result.failure_reasons)


def test_surviving_forbidden_marker_fails() -> None:
    case = _case(
        input_text="This SECRET stays inside normal content.\n",
        forbidden_markers=["SECRET"],
        expectations=BenchmarkExpectations(allow_approximate_token_count=True),
    )
    result = run_case(case)
    assert result.forbidden_markers_found == ["SECRET"]
    assert not result.passed
    assert any("forbidden" in reason for reason in result.failure_reasons)


def test_approximate_not_allowed_fails() -> None:
    case = _case(
        model="totally-unknown-model",
        input_text="dup paragraph\n\ndup paragraph\n\na unique closing line\n",
        expectations=BenchmarkExpectations(allow_approximate_token_count=False),
    )
    result = run_case(case)
    assert result.token_count_mode == "approximate"
    assert not result.passed
    assert any("approximate" in reason for reason in result.failure_reasons)


# ------------------------------------------------------------------------ determinism


def test_suite_report_deterministic_and_sorted() -> None:
    cases = [
        _case(id="b", input_text="dup\n\ndup\n\nunique line b\n"),
        _case(id="a", input_text="dup\n\ndup\n\nunique line a\n"),
    ]
    first = run_suite(cases)
    second = run_suite(cases)
    assert suite_to_json(first) == suite_to_json(second)
    assert [c.id for c in first.cases] == ["a", "b"]


def test_json_has_no_unstable_fields() -> None:
    case = _case(input_text="dup line\n\ndup line\n\nunique closing line\n")
    payload = suite_to_json(run_suite([case]))
    lowered = payload.lower()
    for banned in ("timestamp", "generated_at", "datetime", "created", "hostname", "/users/"):
        assert banned not in lowered
    assert '"schema_version": "1.0"' in payload


# -------------------------------------------------------------------------------- cli


def test_cli_bench_success(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    _write_case(
        cases_dir / "demo",
        case_yaml=(
            "id: demo\n"
            "description: d\n"
            "question: Q\n"
            "model: gpt-4.1\n"
            "required_markers:\n"
            "  - KEEPER\n"
            "expectations:\n"
            "  min_token_savings_percent: 10.0\n"
            "  max_token_savings_percent: 95.0\n"
            "  allow_approximate_token_count: true\n"
        ),
        input_text="KEEPER paragraph here.\n\nKEEPER paragraph here.\n\nKEEPER paragraph here.\n",
    )
    out = tmp_path / "rep.json"
    md = tmp_path / "rep.md"
    result = runner.invoke(
        app, ["bench", str(cases_dir), "--output", str(out), "--markdown", str(md)]
    )
    assert result.exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["total_cases"] == 1
    assert data["passed_cases"] == 1
    assert md.exists()


def test_cli_bench_failure(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    _write_case(
        cases_dir / "hard",
        case_yaml=(
            "id: hard\n"
            "description: d\n"
            "question: Q\n"
            "model: gpt-4.1\n"
            "expectations:\n"
            "  min_token_savings_percent: 99.0\n"
            "  allow_approximate_token_count: true\n"
        ),
        input_text="No redundancy at all in this single line.\n",
    )
    out = tmp_path / "rep.json"
    result = runner.invoke(app, ["bench", str(cases_dir), "--output", str(out)])
    assert result.exit_code != 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["failed_cases"] == 1


def test_cli_bench_invalid_path_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["bench", str(tmp_path / "does_not_exist")])
    assert result.exit_code != 0


def test_cli_bench_empty_dir_exits_nonzero(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["bench", str(empty)])
    assert result.exit_code != 0


# ------------------------------------------------------------------- bundled fixtures


def test_bundled_fixtures_load_and_are_sufficient() -> None:
    cases = load_suite(BUNDLED_CASES)
    assert len(cases) >= 4
    ids = {c.id for c in cases}
    assert {
        "basic_redundancy",
        "boilerplate_cleanup",
        "evidence_preservation",
        "approximate_token_fallback",
    } <= ids


def test_bundled_suite_is_deterministic() -> None:
    cases = load_suite(BUNDLED_CASES)
    assert suite_to_json(run_suite(cases)) == suite_to_json(run_suite(cases))


@pytest.mark.skipif(
    not _exact_available_offline(),
    reason="exact-mode benchmark cases require tiktoken encoding assets cached offline (ADR 0008)",
)
def test_bundled_suite_passes_with_tiktoken() -> None:
    suite = run_suite(load_suite(BUNDLED_CASES))
    failed = [(c.id, c.failure_reasons) for c in suite.cases if not c.passed]
    assert suite.failed_cases == 0, failed


def test_bundled_exact_case_fails_honestly_when_counting_is_approximate(monkeypatch) -> None:
    # Exact-required bundled cases (model gpt-4.1, allow_approximate_token_count: false) must
    # FAIL — not silently pass as exact — when token counting degrades to approximate (e.g.
    # tiktoken assets are unavailable offline). Forcing the fallback proves the honest gate.
    from lcc.token_budget import counters

    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", False)
    exact_cases = [
        case
        for case in load_suite(BUNDLED_CASES)
        if not case.expectations.allow_approximate_token_count
    ]
    assert exact_cases, "expected at least one exact-required bundled case"
    for case in exact_cases:
        result = run_case(case)
        assert result.token_count_mode == "approximate"
        assert not result.passed
        assert any("approximate" in reason for reason in result.failure_reasons)
