"""Tokenizer contract tests: identity, estimates, and multilingual robustness."""

import pytest

from lcc.schemas import TokenCountMethod
from lcc.token_budget import count_tokens, tokenizer_identity
from lcc.token_budget.counters import (
    approximate_token_count,
    tokenizer_identity_for_count,
)


def test_python_exact_tokenizer_when_cached():
    tc = count_tokens("hello world", model="gpt-4.1")
    # Exact when the encoding is cached offline, approximate otherwise — but never silent.
    assert tc.method in (TokenCountMethod.EXACT, TokenCountMethod.APPROXIMATE)
    assert tc.value >= 1
    if tc.method == TokenCountMethod.EXACT:
        assert tc.counter == "tiktoken" and tc.encoding and tc.note is None
    else:
        assert tc.note is not None


def test_python_approximate_tokenizer_is_labelled():
    tc = count_tokens("hello world", model="gpt-4.1", allow_exact=False)
    assert tc.method == TokenCountMethod.APPROXIMATE
    assert tc.counter == "heuristic"
    ident = tokenizer_identity_for_count(tc)
    assert ident["exact"] is False


def test_tokenizer_metadata_present():
    ident = tokenizer_identity("gpt-4.1")
    assert {"tokenizer", "tokenizer_id", "tokenizer_version", "exact"} <= set(ident)


def test_missing_tokenizer_metadata_is_explicit(monkeypatch):
    from lcc.token_budget import counters

    monkeypatch.setattr(counters, "_HAS_TIKTOKEN", False)
    ident = tokenizer_identity("gpt-4.1")
    assert ident["tokenizer"] == "heuristic"
    assert ident["exact"] is False


def test_mismatched_tokenizer_identities_are_not_equivalent():
    a = tokenizer_identity_for_count(count_tokens("hello", allow_exact=False))
    b = {"tokenizer": "other", "tokenizer_id": "other-v9", "exact": True}
    assert a["tokenizer_id"] != b["tokenizer_id"]


def test_cache_aware_accounting_marks_estimates():
    from lcc.relevance import RelevanceCompactionRequest, compact_context

    text = "Alpha block about booking friction with enough words to be scored here.\n\nZzz noise block with nothing relevant at all here zzz zzz zzz zzz.\n"
    result = compact_context(
        RelevanceCompactionRequest(
            text=text, question="booking friction", provider="mechanical"
        )
    )
    assert result.report.token_count_method in ("exact", "approximate")
    assert result.report.is_estimate == (result.report.token_count_method != "exact")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "x" * 500_000,
        "Hello world, this is plain English prose.",
        "Relato da clínica: cerca de 41% dos agendamentos são perdidos.",
        "混合语言内容 mixed English and 中文 CJK characters here",
        "Unicode test: naïve café résumé — emoji 🎉🚀👍 and symbols ©®™",
        "日本語のテスト文章です。トークン化が正しく動作します。",
        "def hello():\n    return 'world'\n",
        '{"key": "value", "n": 42}',
        "<root><a>1</a></root>",
        "# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    ],
)
def test_tokenizer_handles_content_classes(text):
    tc = count_tokens(text or "x", model="gpt-4.1")
    assert tc.value >= 0
    assert tc.method in (TokenCountMethod.EXACT, TokenCountMethod.APPROXIMATE)
    if not (text or "").strip():
        assert approximate_token_count(text) == 0


def test_zero_length_input_is_zero():
    assert approximate_token_count("") == 0
    tc = count_tokens("", model="gpt-4.1")
    assert tc.value == 0
