"""Tests for token counting and pricing math.

Includes the no-network hardening tests (ADR 0008): the exact tiktoken path must never reach
the network, and must fall back to a clearly labelled approximate count when encoding assets
are unavailable offline. None of these tests require real network access.
"""

from __future__ import annotations

import types

import pytest

from lcc.schemas import TokenCountMethod
from lcc.token_budget import counters
from lcc.token_budget.counters import (
    TokenizerNetworkBlocked,
    _no_network_guard,
    approximate_token_count,
    count_tokens,
)
from lcc.token_budget.pricing import (
    BUILTIN_PRICING,
    estimate_input_cost,
    get_model_pricing,
)


def _exact_available_offline() -> bool:
    """True only when tiktoken can build gpt-4.1's encoding from a local cache (no network)."""
    return count_tokens("probe", model="gpt-4.1").method is TokenCountMethod.EXACT


def _fallback_encoding_available_offline() -> bool:
    """True when the default fallback encoding is locally cached (counted by tiktoken)."""
    return count_tokens("probe", model="unknown-model-xyz").counter == "tiktoken"


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


# ----------------------------------------------------------------- no-network hardening


def test_count_tokens_without_tiktoken_is_approximate(monkeypatch):
    # Token counting must still succeed (and stay honest) when tiktoken is unavailable.
    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", False)
    tc = count_tokens("hello world", model="gpt-4.1")
    assert tc.method == TokenCountMethod.APPROXIMATE
    assert tc.counter == "heuristic"
    assert tc.encoding is None
    assert tc.note is not None and "not installed" in tc.note
    assert tc.value >= 1


def test_count_tokens_when_tiktoken_raises_during_init(monkeypatch):
    # Any non-network failure while loading an encoding must degrade to a heuristic count.
    def _boom(*_args, **_kwargs):
        raise RuntimeError("encoding init exploded")

    fake = types.SimpleNamespace(encoding_for_model=_boom, get_encoding=_boom)
    monkeypatch.setattr(counters, "tiktoken", fake)
    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", True)

    tc = count_tokens("hello world", model="gpt-4.1")
    assert tc.method == TokenCountMethod.APPROXIMATE
    assert tc.counter == "heuristic"
    assert tc.note is not None
    assert "tiktoken failed" in tc.note and "RuntimeError" in tc.note


def test_no_network_guard_blocks_requests_get_and_restores():
    requests = pytest.importorskip("requests")
    original = requests.get
    with _no_network_guard(), pytest.raises(TokenizerNetworkBlocked):
        requests.get("https://example.invalid/encoding.tiktoken")
    assert requests.get is original  # the patch is scoped to the guard and fully restored


def test_no_network_guard_blocks_socket_connect_and_restores():
    import socket

    had_own = "connect" in vars(socket.socket)
    with _no_network_guard():
        sock = socket.socket()
        try:
            with pytest.raises(TokenizerNetworkBlocked):
                sock.connect(("127.0.0.1", 9))
        finally:
            sock.close()
    # The inherited connect is restored exactly (no leftover shadowing attribute).
    assert ("connect" in vars(socket.socket)) == had_own


def test_tiktoken_network_attempt_falls_back_without_real_network(monkeypatch):
    # Regression test: a tiktoken encoding load that attempts an HTTP fetch must be blocked
    # by the guard and fall back to approximate counting, never reaching the real network.
    requests = pytest.importorskip("requests")

    def _tripwire(*_args, **_kwargs):
        # Stands in for the real network: if the guard ever lets a fetch through, this fires.
        raise AssertionError("a real network call escaped the no-network guard")

    monkeypatch.setattr(requests, "get", _tripwire)

    class _FakeEncoding:
        name = "fake-enc"

        def encode(self, text):
            return list(text)

    def _encoding_for_model(_model):
        # Mirrors tiktoken.load.read_file: import requests, then GET the encoding asset.
        import requests as _r

        _r.get("https://openaipublic.blob.core.windows.net/encodings/fake.tiktoken")
        return _FakeEncoding()

    fake = types.SimpleNamespace(
        encoding_for_model=_encoding_for_model,
        get_encoding=lambda _name: _encoding_for_model(_name),
    )
    monkeypatch.setattr(counters, "tiktoken", fake)
    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", True)

    tc = count_tokens("hello", model="gpt-4o")  # does not raise; tripwire never fires
    assert tc.method == TokenCountMethod.APPROXIMATE
    assert tc.counter == "heuristic"
    assert tc.note == counters._NOTE_NETWORK_BLOCKED


def test_exact_mode_when_encoding_available_offline():
    if not _exact_available_offline():
        pytest.skip("tiktoken gpt-4.1 encoding assets are not cached offline")
    tc = count_tokens("hello world", model="gpt-4.1")
    assert tc.method == TokenCountMethod.EXACT
    assert tc.counter == "tiktoken"
    assert tc.encoding  # e.g. "o200k_base"
    assert tc.note is None
    assert tc.value >= 1


def test_unknown_model_uses_fallback_encoding_note_when_cached():
    if not _fallback_encoding_available_offline():
        pytest.skip("default tiktoken encoding assets are not cached offline")
    tc = count_tokens("hello world", model="totally-unknown-model-xyz")
    assert tc.method == TokenCountMethod.APPROXIMATE
    assert tc.counter == "tiktoken"
    assert tc.note is not None and "no known tiktoken encoding" in tc.note
