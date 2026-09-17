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


# ---------------------------------------------------------------------------
# 2026-09-18 upgrades (review of tamaratran/fast-jev-compaction): trim band,
# tail pinning, concurrent batches, reduction ratio.
# ---------------------------------------------------------------------------

BORDER = (
    "The borderline paragraph starts here with details that only partly match the "
    "objective but still carry some signal for the reader. " + ("Extra context sentence. " * 30)
) + "TAIL_MARKER_SHOULD_BE_GONE"

TRIM_SAMPLE = (
    "Intro block relevant to the objective and long enough to be scored without dropping it here.\n\n"
    f"{BORDER}\n\n"
    "Noise zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz zzz.\n"
)


def _trim_judge(text: str) -> float:
    lowered = text.lower()
    if "intro block" in lowered:
        return 0.9
    if "borderline" in lowered:
        return 0.3  # inside the default trim band [0.2, 0.4)
    return 0.05


def test_trim_band_keeps_head_and_note():
    client = FakeJevClient(_trim_judge)
    result = compact_context(_request(text=TRIM_SAMPLE, client=client))
    report = result.report
    assert report.blocks_trimmed == 1
    assert "The borderline paragraph starts here" in result.compacted_text
    assert "TAIL_MARKER_SHOULD_BE_GONE" not in result.compacted_text
    assert "lcc-compact: trimmed" in result.compacted_text
    assert "zzz zzz" not in result.compacted_text  # noise still dropped
    trimmed = [d for d in report.decisions if d.decision == "trim"]
    assert trimmed and trimmed[0].chars_after is not None
    assert trimmed[0].chars_after < trimmed[0].chars


def test_trim_disabled_with_zero_head_chars():
    client = FakeJevClient(_trim_judge)
    result = compact_context(_request(text=TRIM_SAMPLE, client=client, trim_head_chars=0))
    assert result.report.blocks_trimmed == 0
    assert "The borderline paragraph" not in result.compacted_text


def test_trim_decision_round_trips_through_sticky_cache(tmp_path: Path):
    cache = tmp_path / "decisions.jsonl"
    first = compact_context(
        _request(text=TRIM_SAMPLE, client=FakeJevClient(_trim_judge), decisions_cache_path=cache)
    )
    second_client = FakeJevClient(_trim_judge)
    second = compact_context(
        _request(text=TRIM_SAMPLE, client=second_client, decisions_cache_path=cache)
    )
    assert second_client.calls == 0
    assert second.compacted_text == first.compacted_text
    assert second.report.blocks_trimmed == 1


def test_preserve_tail_blocks_are_never_scored_or_mutated():
    client = FakeJevClient(lambda text: 0.02)  # everything would drop
    result = compact_context(_request(client=client, preserve_tail_blocks=1))
    report = result.report
    assert "Another relevant line" in result.compacted_text  # newest block survives
    assert "Intro block" not in result.compacted_text  # older blocks still drop
    tail = [d for d in report.decisions if d.reason == "tail_preserve"]
    assert len(tail) == 1 and tail[0].decision == "keep"


def test_batches_run_concurrently_when_workers_allow():
    import threading
    import time as _time

    class ProbeClient:
        model = "probe"

        def __init__(self):
            self.lock = threading.Lock()
            self.active = 0
            self.max_active = 0
            self.calls = 0

        def evaluate(self, state, questions):
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.calls += 1
            _time.sleep(0.05)
            with self.lock:
                self.active -= 1
            return {"answers": {qid: {"type": "noul", "noul": 0.9} for qid in questions}}

    lines = [f"Block {i}: " + ("y " * 60) for i in range(8)]
    text = "\n\n".join(lines) + "\n"

    parallel = ProbeClient()
    compact_context(_request(text=text, client=parallel, batch_size=1, max_workers=4))
    assert parallel.calls == 8
    assert parallel.max_active >= 2  # batches overlapped

    sequential = ProbeClient()
    compact_context(_request(text=text, client=sequential, batch_size=1, max_workers=1))
    assert sequential.calls == 8
    assert sequential.max_active == 1


def test_reduction_ratio_and_low_reduction_flag():
    client = FakeJevClient(_judge)
    low = compact_context(_request(client=client, min_reduction=0.99))
    assert low.report.worth_it is False
    assert any("low_reduction" in w for w in low.report.warnings)
    assert 0.0 < low.report.reduction_ratio < 1.0

    client2 = FakeJevClient(_judge)
    relaxed = compact_context(_request(client=client2, min_reduction=0.0))
    assert relaxed.report.worth_it is True
