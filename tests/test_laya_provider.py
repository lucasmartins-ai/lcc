"""Unit tests for Laya local semantic decision provider."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest

from lcc.relevance import (
    LayaClient,
    LayaExecutionError,
    LayaProvider,
    LayaUnavailableError,
    RelevanceCompactionRequest,
    UnsupportedOperationError,
    calibrate_noul,
    clear_laya_client_cache,
    compact_context,
    get_semantic_provider,
)


class FakeLayaAgent:
    """Mock agent simulating laya.Agent for offline unit tests."""

    def __init__(self, score_func=None):
        self.score_func = score_func
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def predict(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((state, questions))
        if isinstance(state, dict) and "blocks" in state:
            texts = {b["id"]: b.get("text", "") for b in state["blocks"]}
        else:
            texts = {}

        answers = {}
        for qid, qdef in questions.items():
            qtype = qdef["type"]
            block_id = qid[len("keep_") :] if qid.startswith("keep_") else qid
            block_text = texts.get(block_id, qdef.get("context", ""))

            if self.score_func is not None:
                score = self.score_func(block_text)
            else:
                score = 0.9 if "relevant" in block_text.lower() else 0.05

            if qtype == "noul":
                answers[qid] = {
                    "type": "noul",
                    "noul": score,
                    "confidence": 0.85,
                    "action": "keep" if score >= 0.5 else "drop",
                }
            elif qtype == "choice":
                answers[qid] = {
                    "type": "choice",
                    "choice": "relevant",
                    "confidence": 0.9,
                    "probabilities": {"relevant": 0.9, "irrelevant": 0.1},
                }
            elif qtype == "score":
                answers[qid] = {
                    "type": "score",
                    "score": 4,
                    "confidence": 0.8,
                }
        return {
            "answers": answers,
            "usage": {"tokens": 120},
            "model": "mock-laya",
        }


SAMPLE_TEXT = (
    "Intro block: alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha.\n\n"
    "This block is relevant to the objective and must survive the entire pass without any edits.\n\n"
    "Noise block: zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz.\n\n"
    "Another relevant line about the objective and the booking funnel details across mobile users.\n"
)


def test_calibrate_noul_softens_overconfidence():
    assert calibrate_noul(0.9) == 0.9
    assert 0.5 < calibrate_noul(0.9, 2.0) < 0.9
    assert 0.1 < calibrate_noul(0.1, 2.0) < 0.5


def test_provider_registration():
    provider = get_semantic_provider("laya")
    assert isinstance(provider, LayaProvider)
    assert provider.name == "laya"
    assert provider.is_available() is True or provider.is_available() is False


def test_laya_client_initialization():
    client = LayaClient(model="convaiinnovations/laya", device="cpu")
    assert client.model == "convaiinnovations/laya"
    assert client.device == "cpu"
    assert client.context_limit == 512
    assert client.available_state_tokens == 512 - 192 - 1


def test_laya_client_1024_context_limit():
    client = LayaClient(model="convaiinnovations/laya-multilingual")
    assert client.context_limit == 1024
    assert client.available_state_tokens == 1024 - 192 - 1


def test_laya_client_offline_environment():
    agent = FakeLayaAgent()
    client = LayaClient(agent=agent, offline=True)
    client.evaluate("sample state", {"q1": {"type": "noul", "question": "relevant?"}})
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def test_laya_client_noul_evaluation():
    agent = FakeLayaAgent()
    client = LayaClient(agent=agent)
    result = client.evaluate(
        "sample state",
        {
            "q1": {"type": "noul", "question": "relevant?", "context": "relevant text"},
            "q2": {"type": "noul", "question": "relevant?", "context": "noise text"},
        },
    )
    assert len(agent.calls) == 1
    assert "answers" in result
    assert result["answers"]["q1"]["type"] == "noul"
    assert result["answers"]["q1"]["noul"] == 0.9
    assert result["answers"]["q1"]["confidence"] == 0.85
    assert result["answers"]["q2"]["noul"] == 0.05


def test_laya_client_unsupported_question_type():
    agent = FakeLayaAgent()
    client = LayaClient(agent=agent)
    with pytest.raises(UnsupportedOperationError) as exc_info:
        client.evaluate(
            "sample state",
            {"q1": {"type": "open_ended_generation", "question": "Write a poem"}},
        )
    assert "does not support question type 'open_ended_generation'" in str(exc_info.value)


def test_laya_unavailable_error():
    with patch.dict("sys.modules", {"laya": None}):
        client = LayaClient(model="nonexistent/model")
        with pytest.raises(LayaUnavailableError) as exc_info:
            client._ensure_agent()
        assert "Laya or PyTorch dependencies are not installed" in str(exc_info.value)


def test_laya_execution_error_handling():
    class FailingAgent:
        def predict(self, state, questions):
            raise RuntimeError("CUDA out of memory")

    client = LayaClient(agent=FailingAgent())
    with pytest.raises(LayaExecutionError) as exc_info:
        client.evaluate("state", {"q1": {"type": "noul", "question": "test"}})
    assert "CUDA out of memory" in str(exc_info.value)


def test_laya_compactor_integration():
    agent = FakeLayaAgent()
    client = LayaClient(agent=agent)

    req = RelevanceCompactionRequest(
        text=SAMPLE_TEXT,
        question="booking funnel objective",
        provider="laya",
        client=client,
        threshold=0.4,
    )
    result = compact_context(req)

    assert result.report.provider_requested == "laya"
    assert result.report.provider_used == "laya"
    assert result.report.blocks_dropped >= 1
    assert "This block is relevant" in result.compacted_text
    assert "zzz zzz" not in result.compacted_text
    assert "lcc-compact: dropped" in result.compacted_text

    # Verify decision metadata contains source='laya' and confidence is populated
    decisions = result.report.decisions
    for dec in decisions:
        if dec.decision == "drop":
            assert dec.source == "laya"
            assert dec.confidence is not None
            assert dec.confidence > 0.0


def test_laya_degraded_fail_safe_when_unavailable():
    # When laya is requested but unavailable (client=None and no deps),
    # fall back honestly to mechanical scoring with degraded=True —
    # never a fake `judged`, never a silent keep-all.
    req = RelevanceCompactionRequest(
        text=SAMPLE_TEXT,
        question="engineering specifications",
        provider="laya",
        client=None,
    )
    with patch("lcc.relevance.compactor._resolve_laya_client", return_value=None):
        result = compact_context(req)

    assert result.report.provider_requested == "laya"
    assert result.report.provider_used == "laya+mechanical_fallback"
    assert result.report.degraded is True
    assert result.report.degradation_reason == "laya_unavailable_mechanical_fallback"
    assert result.report.semantic_guarantee == "none"
    assert any("laya_unavailable" in w for w in result.report.warnings)
    # Mechanical fallback: no decision may claim a Laya source.
    for dec in result.report.decisions:
        assert dec.source != "laya"


def test_laya_report_carries_observability_fields():
    agent = FakeLayaAgent()
    client = LayaClient(agent=agent)
    req = RelevanceCompactionRequest(
        text=SAMPLE_TEXT,
        question="booking funnel objective",
        provider="laya",
        client=client,
        threshold=0.4,
    )
    result = compact_context(req)
    payload = result.report
    assert payload.provider_used == "laya"
    assert payload.laya_model_requested is not None
    assert payload.laya_model_resolved is not None
    assert payload.laya_context_limit in (512, 1024)
    assert payload.context_budget_used is not None
    assert payload.context_budget_used <= (payload.laya_context_limit or 1024)
    assert payload.latency_ms >= 0
    d = __import__("lcc.relevance.compactor", fromlist=["report_to_dict"]).report_to_dict(
        payload
    )
    for field in (
        "provider_used",
        "laya_model_requested",
        "laya_model_resolved",
        "laya_context_limit",
        "context_budget_used",
        "latency_ms",
    ):
        assert field in d, field


def test_laya_client_caching_across_compaction_calls():
    """Verify that _resolve_laya_client caches client instances (Issue #19)."""
    from lcc.relevance.compactor import _resolve_laya_client

    clear_laya_client_cache()

    req1 = RelevanceCompactionRequest(
        text=SAMPLE_TEXT,
        question="test",
        provider="laya",
        laya_model="convaiinnovations/laya-multilingual",
        laya_temperature=1.0,
    )
    client1 = _resolve_laya_client(req1)
    assert client1 is not None

    # Second call with identical config returns the exact same cached instance
    req2 = RelevanceCompactionRequest(
        text=SAMPLE_TEXT,
        question="test 2",
        provider="laya",
        laya_model="convaiinnovations/laya-multilingual",
        laya_temperature=1.0,
    )
    client2 = _resolve_laya_client(req2)
    assert client2 is client1

    # Different model or temperature produces a different client instance
    req3 = RelevanceCompactionRequest(
        text=SAMPLE_TEXT,
        question="test 3",
        provider="laya",
        laya_model="convaiinnovations/laya-typed-decisions",
        laya_temperature=1.0,
    )
    client3 = _resolve_laya_client(req3)
    assert client3 is not client1

    # Clearing the cache resets it
    clear_laya_client_cache()
    client4 = _resolve_laya_client(req1)
    assert client4 is not client1

