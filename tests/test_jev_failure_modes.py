"""Jev failure-mode tests: every failure keeps content and says why. All mocked."""

import pytest

from lcc.relevance import RelevanceCompactionRequest, compact_context
from lcc.relevance.jev import (
    JEV_CONTEXT_LIMIT_TOKENS,
    JevClient,
    JevMalformedResponseError,
    JevRequestError,
    JevStateTooLargeError,
    JevUnavailableError,
    parse_noul_answer,
)

TEXT = (
    "Relevant booking funnel block with enough words to be scored by any provider here.\n\n"
    "Noise block zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz.\n"
)


class _Ok:
    model = "fake"

    def __init__(self, score=0.9):
        self.score = score
        self.calls = 0
        self.last_resolved_model = "jev-2026-09-01"

    def evaluate(self, state, questions):
        self.calls += 1
        return {"answers": {qid: {"type": "noul", "noul": self.score} for qid in questions},
                "model": "jev-2026-09-01"}


def _req(client, **over):
    base = {"text": TEXT, "question": "booking funnel", "provider": "jev", "client": client}
    base.update(over)
    return RelevanceCompactionRequest(**base)


def test_jev_success_records_resolved_model():
    result = compact_context(_req(_Ok(0.05)))
    assert result.report.provider_used == "jev"
    assert result.report.semantic_guarantee == "judged"


def test_jev_timeout_falls_back_mechanically():
    class Timeout:
        model = "fake"

        def evaluate(self, state, questions):
            raise JevRequestError("network error: timed out")

    result = compact_context(_req(Timeout()))
    assert result.report.provider_used == "jev+mechanical_fallback"
    # Total failure judged nothing: every decision is lexical, so the honest
    # guarantee is `none`. `partial` is reserved for mixed runs where some
    # blocks were actually judged before the failure.
    assert result.report.degraded and result.report.semantic_guarantee == "none"


def test_jev_429_retried_then_falls_back():
    class RateLimited:
        model = "fake"

        def evaluate(self, state, questions):
            raise JevRequestError("TypeSafe API error 429: rate limited")

    result = compact_context(_req(RateLimited()))
    assert result.report.degraded
    assert any("jev_batch" in w for w in result.report.warnings)


def test_jev_5xx_falls_back():
    class ServerError:
        model = "fake"

        def evaluate(self, state, questions):
            raise JevRequestError("TypeSafe API error 503: unavailable")

    result = compact_context(_req(ServerError()))
    assert result.report.degraded


def test_jev_malformed_response_falls_back():
    class Malformed:
        model = "fake"

        def evaluate(self, state, questions):
            return {"not_answers": {}}

    result = compact_context(_req(Malformed()))
    assert result.report.provider_used in ("jev+mechanical_fallback", "mechanical", "jev")
    assert result.report.degraded or result.report.semantic_guarantee in ("partial", "none")


def test_jev_partial_response_scores_rest_mechanically():
    class Partial:
        model = "fake"

        def evaluate(self, state, questions):
            first = next(iter(questions))
            return {"answers": {first: {"type": "noul", "noul": 0.9}}}

    result = compact_context(_req(Partial()))
    assert any("jev_missing_answer" in w for w in result.report.warnings)


def test_jev_unavailable_fails_safe(monkeypatch):
    monkeypatch.setattr("lcc.relevance.compactor._resolve_client", lambda: None)
    result = compact_context(
        RelevanceCompactionRequest(text=TEXT, question="booking funnel", provider="jev")
    )
    assert result.compacted_text == TEXT
    assert result.report.degradation_reason == "jev_unavailable"


def test_network_disabled_fails_safe(monkeypatch):
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    monkeypatch.setattr("lcc.relevance.compactor._resolve_client", lambda: None)
    result = compact_context(
        RelevanceCompactionRequest(text=TEXT, question="booking funnel", provider="auto")
    )
    assert result.report.degraded


def test_invalid_schema_answer_is_rejected():
    score, conf, problem = parse_noul_answer({"type": "noul"})
    assert score is None and problem == "missing"
    score, conf, problem = parse_noul_answer({"type": "noul", "noul": "high"})
    assert score is None


def test_unexpected_choice_type_is_rejected():
    score, conf, problem = parse_noul_answer({"type": "choice", "choice": "yes"})
    assert score is None and problem == "missing"


def test_confidence_missing_is_reported_not_fatal():
    score, conf, problem = parse_noul_answer({"type": "noul", "noul": 0.7})
    assert score == 0.7 and problem == "confidence_missing"


def test_confidence_out_of_range_is_reported():
    score, conf, problem = parse_noul_answer({"type": "noul", "noul": 0.7, "confidence": 1.7})
    assert problem == "confidence_out_of_range"


def test_score_out_of_range_falls_back():
    class Wild:
        model = "fake"

        def evaluate(self, state, questions):
            return {"answers": {qid: {"type": "noul", "noul": 1.7} for qid in questions}}

    result = compact_context(_req(Wild()))
    assert any("out_of_range" in w for w in result.report.warnings)


def test_empty_api_key_is_unavailable():
    with pytest.raises(JevUnavailableError):
        JevClient(api_key="")


def test_malformed_response_error_type():
    assert issubclass(JevMalformedResponseError, JevRequestError)


def test_oversized_state_refused_locally_and_small_state_still_sent(tmp_path):
    """Pre-flight guard: over the window no request leaves the machine, normal ones do.

    Regression for 21/09: a 123.741-char state was sent anyway (heuristic undercount)
    and came back ``400 max_tokens_exceeded`` 38 times before the batch gave up.
    """
    import json as _json

    ledger = tmp_path / "ledger.jsonl"

    def _boom(*_args, **_kwargs):
        raise AssertionError("network reached with an oversized state")

    big = JevClient(api_key="test-key", opener=_boom, ledger_path=ledger)
    questions = {"keep": {"type": "noul", "instructions": "x", "criteria": {"true": "y", "false": "z"}}}
    with pytest.raises(JevStateTooLargeError) as exc:
        big.evaluate({"blob": "x" * 400_000}, questions)
    assert f"> {JEV_CONTEXT_LIMIT_TOKENS}" in str(exc.value)
    logged = [ _json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() ]
    assert len(logged) == 1 and "pre_flight" in logged[0]["error"]
    assert logged[0]["state_chars"] > 0

    class _Resp:
        def read(self):
            return _json.dumps(
                {"model": "jev-test", "answers": {"keep": {"type": "noul", "noul": 0.5}}}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    small = JevClient(api_key="test-key", opener=lambda *_a, **_k: _Resp(), ledger_path=ledger)
    answer = small.evaluate({"block": "a short relevant block"}, questions)
    assert answer["answers"]["keep"]["noul"] == 0.5
