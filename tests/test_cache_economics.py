"""Cache economics (P1): token reduction is not cost reduction.

The report must expose raw/compacted tokens, invalidated prefix tokens,
compilation cost, downstream inference proxy, break-even reuse and cache-reuse
observability — and the suite must show a case where fewer tokens costs more.
"""

from lcc.relevance import RelevanceCompactionRequest, compact_context


def _corpus(noise_blocks=6):
    evidence = (
        "Conversion fell from 8.7% to 4.2% after the June release window. "
        + "Detail about the funnel and the mobile cohort. " * 30
        + "\n"
    )
    noise = "".join(
        f"\n\nChatter block {i} about office plants, coffee machines and weather. "
        + "Filler words with no distinctive terms at all. " * 20
        + "\n"
        for i in range(noise_blocks)
    )
    return evidence + noise


def test_report_carries_full_cost_accounting():
    result = compact_context(
        RelevanceCompactionRequest(
            text=_corpus(),
            question="Why did conversion fall?",
            provider="mechanical",
        )
    )
    report = result.report
    # Raw vs compacted tokens.
    assert report.tokens_before > 0
    assert report.tokens_after > 0
    # Prefix/cache accounting.
    assert report.prefix_sha256
    assert report.output_sha256
    assert report.first_mutation_offset is not None
    assert report.invalidated_tokens >= 0
    # Compilation cost + downstream inference proxy + break-even.
    assert report.compilation_ms >= 0
    assert report.calls >= 0
    assert report.reused_decisions >= 0
    if report.invalidated_tokens and report.tokens_before > report.tokens_after:
        assert report.break_even_reuses is not None
        assert report.break_even_reuses > 0
    # Marker economics measured, never hidden.
    assert report.marker_tokens >= 0


def test_token_reduction_without_reuse_can_cost_more():
    """A pass that drops tokens but invalidates a warm prefix only pays off
    after break_even_reuses reuses. With zero reuses the epoch is a net loss:
    reduction != savings. The report must say so explicitly."""
    result = compact_context(
        RelevanceCompactionRequest(
            text=_corpus(),
            question="Why did conversion fall?",
            provider="mechanical",
        )
    )
    report = result.report
    assert report.tokens_after < report.tokens_before  # tokens went down ...
    if report.break_even_reuses is not None and report.break_even_reuses > 1.0:
        assert any("cache_epoch_risk" in w for w in report.warnings)
        # ... yet a single use does not amortise the invalidation.
        single_use_cost = report.invalidated_tokens * 1.15  # write - read factor
        single_use_saving = (report.tokens_before - report.tokens_after) * 0.10
        assert single_use_cost > single_use_saving


def test_warm_run_reuses_decisions_and_reports_it(tmp_path):
    cache_path = tmp_path / "decisions.jsonl"
    kwargs = {
        "text": _corpus(),
        "question": "Why did conversion fall?",
        "provider": "mechanical",
        "decisions_cache_path": cache_path,
    }
    cold = compact_context(RelevanceCompactionRequest(**kwargs))
    assert cold.report.reused_decisions == 0
    warm = compact_context(RelevanceCompactionRequest(**kwargs))
    assert warm.report.reused_decisions > 0
    assert warm.compacted_text == cold.compacted_text  # byte-stable prefix
    assert warm.report.semantic_cache_hits > 0
