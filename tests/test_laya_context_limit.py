"""Unit tests for Laya context window limit validation and token budgeting."""

from __future__ import annotations

import pytest

from lcc.relevance import (
    LayaClient,
    LayaContextLimitExceededError,
    RelevanceCompactionRequest,
    compact_context,
    get_laya_context_limit,
)
from lcc.relevance.compactor import _batch_blocks_for_laya
from lcc.relevance.laya import HEAD_RESERVATION_TOKENS


class MockLayaAgent:
    """Mock agent that succeeds for any valid call."""

    def predict(self, state, questions):
        return {
            "answers": {
                qid: {"type": "noul", "noul": 0.8, "confidence": 0.9}
                for qid in questions
            },
            "usage": {"tokens": 100},
            "model": "mock-laya",
        }


def test_context_limits_by_model():
    assert get_laya_context_limit("convaiinnovations/laya") == 512
    assert get_laya_context_limit("convaiinnovations/laya-multilingual") == 1024
    assert get_laya_context_limit("convaiinnovations/laya-typed-decisions") == 1024
    assert get_laya_context_limit("custom-model-unknown") == 1024


def test_head_reservation_and_available_tokens():
    client_512 = LayaClient(model="convaiinnovations/laya")
    assert client_512.context_limit == 512
    assert client_512.head_reservation == HEAD_RESERVATION_TOKENS
    assert client_512.available_state_tokens == 512 - 192 - 1  # 319

    client_1024 = LayaClient(model="convaiinnovations/laya-multilingual")
    assert client_1024.context_limit == 1024
    assert client_1024.available_state_tokens == 1024 - 192 - 1  # 831


def test_validate_context_budget_rejection_of_oversized_state():
    client = LayaClient(model="convaiinnovations/laya")  # 512 tokens limit, 319 available
    # Generate an oversized state of ~500 tokens (well over 319)
    oversized_text = "word " * 600

    with pytest.raises(LayaContextLimitExceededError) as exc_info:
        client.validate_context_budget(oversized_text)

    err = exc_info.value
    assert err.limit == 512
    assert err.compacted_tokens > 319
    assert "exceed Laya's context limit" in str(err)
    assert "will not naively truncate" in str(err)


def test_batch_blocks_for_laya_separates_oversized_blocks():
    from lcc.relevance.blocks import TextBlock

    client = LayaClient(model="convaiinnovations/laya")  # 319 available tokens

    # Normal small blocks
    block_normal_1 = TextBlock(
        id="blk_001",
        index=0,
        character_start=0,
        character_end=150,
        line_start=1,
        line_end=5,
        text="Normal block one with moderate length text for testing relevance batching.",
    )
    block_normal_2 = TextBlock(
        id="blk_002",
        index=1,
        character_start=151,
        character_end=300,
        line_start=6,
        line_end=10,
        text="Normal block two with moderate length text for testing relevance batching.",
    )
    # Huge block that exceeds 319 tokens
    huge_text = "Large block content that exceeds the maximum token limit. " * 50
    block_huge = TextBlock(
        id="blk_003_huge",
        index=2,
        character_start=301,
        character_end=301 + len(huge_text),
        line_start=11,
        line_end=50,
        text=huge_text,
    )

    batches, oversized = _batch_blocks_for_laya(
        [block_normal_1, block_normal_2, block_huge],
        client=client,
        objective="test question",
        max_batch_size=8,
    )

    # The huge block should be placed in oversized
    assert len(oversized) == 1
    assert oversized[0][0].id == "blk_003_huge"
    assert oversized[0][1] > client.available_state_tokens

    # The normal blocks should be in batches
    assert len(batches) == 1
    assert len(batches[0]) == 2
    assert batches[0][0].id == "blk_001"
    assert batches[0][1].id == "blk_002"


def test_compactor_safe_fallback_on_oversized_block():
    agent = MockLayaAgent()
    client = LayaClient(model="convaiinnovations/laya", agent=agent)

    # One normal block and one oversized block
    normal_block = (
        "Normal block: alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha "
        "alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha.\n\n"
    )
    huge_block = (
        "Huge block with massive repetitive content: "
        + ("token_budget_overflow_sample_content_repeated " * 400)
    )

    full_text = normal_block + huge_block

    req = RelevanceCompactionRequest(
        text=full_text,
        question="alpha objective",
        provider="laya",
        client=client,
    )
    result = compact_context(req)

    report = result.report
    assert report.provider_requested == "laya"

    # Find decision for huge block
    huge_decisions = [
        d for d in report.decisions if d.reason == "laya_context_limit_exceeded"
    ]
    assert len(huge_decisions) >= 1
    huge_dec = huge_decisions[0]

    # Must be kept fail-safe, never naively truncated
    assert huge_dec.decision == "keep"
    assert huge_dec.source == "fallback"
    assert huge_dec.reason == "laya_context_limit_exceeded"

    # Must have logged warning with status insufficient_context
    assert any(
        "laya_context_limit_exceeded" in w and "insufficient_context" in w
        for w in report.warnings
    )

    # Full text must remain intact without truncation
    assert "token_budget_overflow_sample_content_repeated" in result.compacted_text
