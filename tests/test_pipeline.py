"""End-to-end tests for the optimization pipeline."""

from __future__ import annotations

import json
import types

import pytest

from lcc.pipeline import OptimizationRequest, optimize
from lcc.reporting.report import report_to_dict, report_to_json
from lcc.schemas import SCHEMA_VERSION

SAMPLE = (
    "Intro paragraph about the project.\r\n\r\n"
    "Intro paragraph about the project.\n\n"  # exact duplicate
    "Sent from my iPhone\n\n"
    "A distinct second paragraph with real content worth keeping in the prompt."
)


def test_pipeline_reduces_tokens_and_populates_report():
    result = optimize(OptimizationRequest(raw_text=SAMPLE, question="Summarize.", model="gpt-4.1"))
    report = result.report
    assert report.schema_version == SCHEMA_VERSION
    assert report.original_token_count > 0
    assert report.optimized_token_count < report.original_token_count
    assert 0.0 <= report.compression_ratio <= 1.0
    assert report.dedup_metrics.duplicates_removed >= 1
    assert "Sent from my iPhone" not in result.cleaned_context
    assert "Summarize." in result.prompt
    assert "distinct second paragraph" in result.prompt


def test_pipeline_cost_for_known_model():
    report = optimize(OptimizationRequest(raw_text=SAMPLE, question="Q", model="gpt-4.1")).report
    assert report.cost.before is not None
    assert report.cost.after is not None
    assert report.cost.savings is not None
    assert report.cost.before >= report.cost.after


def test_pipeline_unknown_model_warns_and_omits_cost():
    report = optimize(
        OptimizationRequest(raw_text=SAMPLE, question="Q", model="mystery-model")
    ).report
    assert report.cost.before is None
    assert any("pricing" in warning.lower() for warning in report.warnings)


def test_pipeline_empty_input_warns():
    report = optimize(OptimizationRequest(raw_text="   \n  ", question="Q", model="gpt-4.1")).report
    assert any("empty" in warning.lower() for warning in report.warnings)


def test_pipeline_max_input_tokens_warning():
    text = "\n\n".join(f"Unique sentence number {i}." for i in range(50))
    report = optimize(
        OptimizationRequest(raw_text=text, question="Q", model="gpt-4.1", max_input_tokens=5)
    ).report
    assert any("max-input-tokens" in warning for warning in report.warnings)


def test_disabling_cleaning_keeps_more_content():
    full = optimize(
        OptimizationRequest(
            raw_text=SAMPLE,
            question="Q",
            model="gpt-4.1",
            remove_boilerplate=False,
            remove_near_duplicates=False,
        )
    )
    assert "Sent from my iPhone" in full.cleaned_context


def test_report_is_json_serializable():
    report = optimize(OptimizationRequest(raw_text=SAMPLE, question="Q", model="gpt-4.1")).report
    as_dict = report_to_dict(report)
    parsed = json.loads(report_to_json(report))
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["token_count_method"] in {"exact", "approximate"}
    assert isinstance(as_dict["cleaning_steps"], list)
    assert isinstance(parsed["dedup_metrics"]["paragraphs_before"], int)


def test_pipeline_warns_when_token_counts_are_approximate():
    # An unknown model has no tiktoken encoding, so counts are approximate.
    report = optimize(
        OptimizationRequest(raw_text=SAMPLE, question="Q", model="mystery-model")
    ).report
    assert report.token_count_method.value == "approximate"
    assert any("approximate" in warning.lower() for warning in report.warnings)


def test_pipeline_blocks_tiktoken_network_and_warns_honestly(monkeypatch):
    # Regression (ADR 0008): if tiktoken would fetch encoding assets, `lcc optimize`'s token
    # counting must block the attempt, fall back to approximate, and explain why in a warning
    # -- without propagating the network error or reaching the real network.
    requests = pytest.importorskip("requests")
    from lcc.token_budget import counters

    def _tripwire(*_args, **_kwargs):
        raise AssertionError("a real network call escaped the no-network guard")

    monkeypatch.setattr(requests, "get", _tripwire)

    class _FakeEncoding:
        name = "fake-enc"

        def encode(self, text):
            return list(text)

    def _encoding_for_model(_model):
        import requests as _r

        _r.get("https://openaipublic.blob.core.windows.net/encodings/fake.tiktoken")
        return _FakeEncoding()

    fake = types.SimpleNamespace(
        encoding_for_model=_encoding_for_model,
        get_encoding=lambda _name: _encoding_for_model(_name),
    )
    monkeypatch.setattr(counters, "tiktoken", fake)
    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", True)

    report = optimize(OptimizationRequest(raw_text=SAMPLE, question="Q", model="gpt-4.1")).report
    assert report.token_count_method.value == "approximate"
    assert any(
        "approximate" in warning.lower() and "offline" in warning.lower()
        for warning in report.warnings
    )
