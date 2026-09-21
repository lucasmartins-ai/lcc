"""Live Laya integration test — REAL weights, gated behind LCC_LAYA_INTEGRATION=1.

Skipped by default: it loads the real checkpoint (hundreds of MB from the HF
cache, downloaded on first run) and runs CPU inference — too expensive for the
default suite. Run it explicitly:

    LCC_LAYA_INTEGRATION=1 LCC_LAYA_MODEL=convaiinnovations/laya-multilingual \
      pytest tests/test_laya_integration.py -q

This test pins the contract the mock-based unit tests cannot: the real backend
reports `judged`, stays inside the context budget, never degrades, and every
drop decision is attributed to the model (`source == "laya"`).

Live-validated 2026-09-21 on macOS/CPU (see benchmarks/research/RESEARCH_STATUS.md).
"""

from __future__ import annotations

import os

import pytest

from lcc.relevance import LayaClient, RelevanceCompactionRequest, compact_context

pytestmark = pytest.mark.skipif(
    os.environ.get("LCC_LAYA_INTEGRATION") != "1",
    reason="live Laya integration: set LCC_LAYA_INTEGRATION=1 (loads real weights)",
)

# Both blocks clear DEFAULT_MIN_BLOCK_CHARS (80) so they are judged, not protected.
_TEXT = (
    "The booking widget loses 63 percent of mobile visitors at the date picker step. "
    "Background filler sentence ends here.\n\n"
    "Office chatter about plants needing water near the coffee machine daily. "
    "Background filler sentence ends here.\n"
)


def test_laya_real_inference_through_lcc():
    client = LayaClient()
    assert client.available_state_tokens == client.context_limit - client.head_reservation - 1

    result = compact_context(
        RelevanceCompactionRequest(
            text=_TEXT,
            question="What is wrong with the clinic's booking operation?",
            provider="laya",
            client=client,
            threshold=0.4,
        )
    )
    report = result.report
    # The real backend ran: semantically judged, in budget, no fallback.
    assert report.provider_used == "laya"
    assert report.degraded is False
    assert report.semantic_guarantee == "judged"
    assert report.calls >= 1
    assert report.laya_model_resolved
    assert report.context_budget_used is not None
    assert report.context_budget_used <= (report.laya_context_limit or 1024)
    # Every scored block carries a model decision; drops are never silent.
    assert any(dec.source == "laya" for dec in report.decisions)
    for dec in report.decisions:
        if dec.decision == "drop":
            assert dec.source == "laya"
