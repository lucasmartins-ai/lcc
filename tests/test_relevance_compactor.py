"""Unit tests for relevance compaction: fail-safe behavior, stickiness, cache alignment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lcc.relevance import RelevanceCompactionRequest, compact_context
from lcc.relevance.decisions import CachedDecision, DecisionCache, decision_key


class FakeJevClient:
    """Offline stand-in for JevClient; never touches the network."""

    def __init__(self, judge):
        self.model = "fake"
        self._judge = judge
        self.calls = 0

    def evaluate(self, state, questions):
        self.calls += 1
        texts = {block["id"]: block["text"] for block in state["blocks"]}
        answers = {}
        for qid in questions:
            block_id = qid[len("keep_") :]
            answers[qid] = {"type": "noul", "noul": self._judge(texts.get(block_id, ""))}
        return {"answers": answers}


def _judge(text: str) -> float:
    return 0.9 if "relevant" in text.lower() else 0.05


SAMPLE = (
    "Intro block: alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha.\n\n"
    "This block is relevant to the objective and must survive the entire pass without any edits.\n\n"
    "Noise block: zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz.\n\n"
    "Another relevant line about the objective and the booking funnel details across mobile users.\n"
)


def _request(**overrides: Any) -> RelevanceCompactionRequest:
    base: dict[str, Any] = {
        "text": SAMPLE,
        "question": "booking funnel objective",
        "threshold": 0.4,
        "provider": "jev",
    }
    base.update(overrides)
    return RelevanceCompactionRequest(**base)


def test_jev_drops_below_threshold():
    client = FakeJevClient(_judge)
    result = compact_context(_request(client=client))
    report = result.report
    assert report.provider_used == "jev"
    assert report.blocks_dropped >= 1
    assert "This block is relevant" in result.compacted_text
    assert "zzz zzz" not in result.compacted_text
    assert "lcc-compact: dropped" in result.compacted_text
    assert client.calls == 1


def test_degraded_keeps_everything_byte_identical(monkeypatch):
    monkeypatch.setattr("lcc.relevance.compactor._resolve_client", lambda: None)
    result = compact_context(_request(provider="jev", client=None))
    assert result.report.degraded is True
    assert result.report.provider_used == "degraded"
    assert result.compacted_text == SAMPLE
    assert result.report.first_mutation_offset is None


def test_auto_falls_back_to_mechanical(monkeypatch):
    monkeypatch.setattr("lcc.relevance.compactor._resolve_client", lambda: None)
    result = compact_context(_request(provider="auto", client=None, question="zzz"))
    assert result.report.provider_used == "mechanical"
    assert result.report.calls == 0
    # mechanical keeps blocks with lexical overlap and drops zero-overlap noise
    assert "relevant to the objective" not in result.compacted_text  # judged by overlap only


def test_mechanical_without_question_terms_keeps_everything():
    result = compact_context(_request(provider="mechanical", client=None, question="??"))
    assert result.compacted_text == SAMPLE


def test_protect_prefix_prevents_early_mutations():
    client = FakeJevClient(lambda text: 0.05)  # everything looks droppable
    boundary = len(SAMPLE.split("\n\n", 1)[0]) + 2
    result = compact_context(_request(client=client, protect_prefix_chars=boundary))
    report = result.report
    assert report.prefix_protected is True
    assert report.first_mutation_offset is not None
    assert report.first_mutation_offset >= boundary
    assert report.prefix_untouched is True
    assert result.compacted_text.startswith(SAMPLE[:boundary])


def test_keep_regex_never_dropped():
    client = FakeJevClient(lambda text: 0.01)
    result = compact_context(_request(client=client, keep_patterns=(r"must survive",)))
    assert (
        "This block is relevant to the objective and must survive the entire pass without any edits."
        in result.compacted_text
    )
    assert result.report.blocks_dropped >= 1


def test_sticky_decisions_are_reused_and_output_is_stable(tmp_path: Path):
    cache_path = tmp_path / "decisions.jsonl"
    client = FakeJevClient(_judge)
    first = compact_context(_request(client=client, decisions_cache_path=cache_path))
    assert client.calls == 1
    assert cache_path.exists()

    client2 = FakeJevClient(_judge)
    second = compact_context(_request(client=client2, decisions_cache_path=cache_path))
    assert client2.calls == 0  # every decision came from the sticky cache
    assert second.report.reused_decisions == second.report.blocks_scored
    assert second.compacted_text == first.compacted_text

    # Appending new content keeps the previous output as a byte-stable prefix.
    extended = SAMPLE + (
        "\n\nA new relevant block arrives for the next turn and it is long enough to be scored "
        "properly by the relevance pass.\n"
    )
    client3 = FakeJevClient(_judge)
    third = compact_context(_request(text=extended, client=client3, decisions_cache_path=cache_path))
    assert client3.calls == 1  # only the new block is scored
    assert third.compacted_text.startswith(first.compacted_text)
    assert "A new relevant block arrives" in third.compacted_text


def test_marker_is_deterministic():
    client_a = FakeJevClient(_judge)
    client_b = FakeJevClient(_judge)
    out_a = compact_context(_request(client=client_a)).compacted_text
    out_b = compact_context(_request(client=client_b)).compacted_text
    assert out_a == out_b
    assert "dropped 1 block" in out_a


def test_batching_respects_batch_size():
    lines = [f"Block number {i}: " + ("x " * 60) for i in range(5)]
    text = "\n\n".join(lines) + "\n"
    client = FakeJevClient(lambda text: 0.9)
    result = compact_context(_request(text=text, client=client, batch_size=2))
    assert client.calls == 3  # 5 scoreable blocks in batches of 2
    assert result.report.blocks_dropped == 0


def test_decision_cache_roundtrip(tmp_path: Path):
    path = tmp_path / "decisions.jsonl"
    cache = DecisionCache(path)
    key = decision_key("objective", "block text")
    cache.put(key, objective="objective", block_text="block text",
              entry=CachedDecision(score=0.2, decision="drop", provider="jev"))
    cache.flush()
    second = DecisionCache(path)
    second.load()
    entry = second.get(key)
    assert entry is not None and entry.decision == "drop"
