"""Tests for LccCompressor programmatic API."""

from lcc import CompressionResult, LccCompressor, LccOptimizer


def test_compressor_basic_compression() -> None:
    compressor = LccCompressor(model="gpt-4.1")
    text = (
        "CONFIDENTIAL AND PROPRIETARY INFORMATION.\n"
        "ALL RIGHTS RESERVED. DO NOT DISTRIBUTE.\n\n"
        "Here is the main analysis content.\n\n"
        "Here is the main analysis content.\n\n"
        "Sent from my iPhone"
    )

    res = compressor.compress(text, question="What is the content?")
    assert isinstance(res, CompressionResult)
    assert "main analysis content" in res.compressed_text
    assert "Sent from my iPhone" not in res.compressed_text
    assert res.original_tokens >= res.compressed_tokens
    assert res.saved_tokens >= 0


def test_compressor_alias() -> None:
    optimizer = LccOptimizer(model="gpt-4.1")
    res = optimizer.compress("Short test input.")
    assert isinstance(res, CompressionResult)
    assert res.compressed_text == "Short test input."
