"""Tests for token counting and pricing math."""

from __future__ import annotations

from lcc.schemas import TokenCountMethod
from lcc.token_budget.counters import approximate_token_count, count_tokens
from lcc.token_budget.pricing import (
    BUILTIN_PRICING,
    estimate_input_cost,
    get_model_pricing,
)


def test_approximate_empty_is_zero():
    assert approximate_token_count("") == 0


def test_approximate_is_positive_and_grows_with_length():
    short = approximate_token_count("hello")
    longer = approximate_token_count("hello " * 100)
    assert short >= 1
    assert longer > short


def test_count_tokens_fallback_is_marked_approximate():
    tc = count_tokens("some text here", model="gpt-4.1", allow_exact=False)
    assert tc.method == TokenCountMethod.APPROXIMATE
    assert tc.counter == "heuristic"
    assert tc.value >= 1


def test_count_tokens_unknown_model_is_never_exact():
    tc = count_tokens("hello world", model="totally-unknown-model-xyz")
    assert tc.method == TokenCountMethod.APPROXIMATE


def test_get_model_pricing_found():
    info = get_model_pricing(BUILTIN_PRICING, "gpt-4.1")
    assert info.found is True
    assert info.input_per_million == 2.00
    assert info.currency == "USD"


def test_get_model_pricing_missing():
    info = get_model_pricing(BUILTIN_PRICING, "no-such-model")
    assert info.found is False
    assert info.input_per_million is None


def test_estimate_input_cost():
    assert estimate_input_cost(1_000_000, 2.00) == 2.00
    assert estimate_input_cost(500_000, 2.00) == 1.00
    assert estimate_input_cost(123, None) is None
