"""Tool-call compaction: pairing, recent-message pinning, decisions, and failure modes.

Every test runs offline: the Jev client is a stub injected through the request, so nothing
here touches the network. The rules under test are the ones the Claude Code hook relies on:
text is never touched, a call and its result are dropped together, and nothing is dropped
that was not judged.
"""

from __future__ import annotations

import pytest

import lcc.relevance.transcript as transcript_module
from lcc.relevance.jev import JevRequestError
from lcc.relevance.transcript import (
    TranscriptCompactionRequest,
    TranscriptError,
    TranscriptFitError,
    UnsupportedTranscriptProviderError,
    compact_transcript,
    parse_transcript,
)
from lcc.reporting.explain import render as render_explanation

OBJECTIVE = "finish the parser fix"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test in this module may reach the TypeSafe API, whatever the environment holds."""
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")


class ScoreMap:
    """Stub Jev: per-call ``(keep_call, keep_result)`` probabilities, or one default."""

    model = "fake"
    last_resolved_model = "jev-2026-09-21"

    def __init__(self, mapping=None, default=(0.9, 0.9)):
        self.mapping = mapping or {}
        self.default = default
        self.states = []
        self.question_batches = []

    def evaluate(self, state, questions):
        self.states.append(state)
        self.question_batches.append(questions)
        answers = {}
        for qid in questions:
            if qid.startswith("keep_call_"):
                cid, kind = qid[len("keep_call_") :], 0
            else:
                cid, kind = qid[len("keep_result_") :], 1
            pair = self.mapping.get(cid, self.default)
            answers[qid] = {"type": "noul", "noul": pair[kind]}
        return {"answers": answers, "model": "jev-2026-09-21"}


def build(
    *calls, result_chars: int = 40, text: str = "Work on the parser fix.", no_result: bool = False
) -> dict:
    """Transcript with one call/result pair per ``(tool, input)`` argument."""
    messages: list[dict] = [{"role": "user", "text": text}]
    for index, (tool, tool_input) in enumerate(calls, start=1):
        call_id = f"toolu_{index}"
        messages.append(
            {
                "role": "assistant",
                "text": "" if index > 1 else "Running the test suite now.",
                "toolUses": [{"tool_use_id": call_id, "tool": tool, "input": tool_input}],
            }
        )
        if not no_result:
            messages.append(
                {
                    "role": "user",
                    "text": "",
                    "toolResults": [{"tool_use_id": call_id, "text": "y" * result_chars}],
                }
            )
    return {"messages": messages}


def run(payload, client, **overrides):
    params = {
        "payload": payload,
        "question": OBJECTIVE,
        "provider": "jev",
        "preserve_recent": 0,
        "client": client,
    }
    params.update(overrides)
    return compact_transcript(TranscriptCompactionRequest(**params))


def decisions_of(result) -> dict[str, str]:
    return {entry["id"]: entry["decision"] for entry in result.decisions}


# --- pairing ---------------------------------------------------------------------------


def test_calls_pair_with_their_results_by_id():
    messages = parse_transcript(
        {
            "messages": [
                {"role": "user", "text": "go"},
                {
                    "role": "assistant",
                    "toolUses": [
                        {"tool_use_id": "a", "tool": "Read", "input": {"file": "x.py"}},
                        {"tool_use_id": "b", "tool": "Bash", "input": {"cmd": "pytest"}},
                    ],
                },
                {
                    "role": "user",
                    "toolResults": [
                        {"tool_use_id": "b", "text": "1 failed"},
                        {"tool_use_id": "a", "text": "file body"},
                    ],
                },
            ]
        }
    )
    calls = {call.id: call for message in messages for call in message.tool_calls}
    assert calls["a"].result is not None and calls["a"].result.text == "file body"
    assert calls["b"].result is not None and calls["b"].result.text == "1 failed"


def test_a_call_without_a_result_is_left_alone():
    result = run(build(("Bash", {"cmd": "pytest"}), no_result=True), ScoreMap(default=(0.0, 0.0)))
    # No result was recorded, so there is nothing to judge: the call is kept.
    assert decisions_of(result) == {}
    assert result.report["tool_calls_total"] == 1
    assert result.report["tool_calls_dropped"] == 0
    assert any("no result yet" in warning for warning in result.report["warnings"])


def test_malformed_payload_fails_loudly():
    with pytest.raises(TranscriptError):
        parse_transcript({"messages": [{"text": "no role here"}]})
    with pytest.raises(TranscriptError):
        parse_transcript({"messages": [{"role": "user", "toolUses": [{"tool": "Read"}]}]})


# --- pinning ---------------------------------------------------------------------------


def test_first_and_newest_messages_are_pinned_and_never_scored():
    payload = build(("Read", {"file": "a.py"}), ("Read", {"file": "b.py"}), ("Read", {"file": "c.py"}))
    client = ScoreMap(default=(0.0, 0.0))
    result = run(payload, client, preserve_recent=2)

    # Messages: [user, assistant_1, result_1, assistant_2, result_2, assistant_3, result_3].
    # The newest two messages are pinned, so the last pair is never judged.
    scored_ids = {entry["id"] for entry in result.decisions if entry["source"] == "jev"}
    assert scored_ids == {"toolu_1", "toolu_2"}
    pinned = [entry for entry in result.decisions if entry["source"] == "pin"]
    assert {entry["id"] for entry in pinned} == {"toolu_3"}
    assert all(entry["decision"] == "keep" for entry in pinned)
    assert client.states  # the judge was shown the conversation, not a slice of it


def test_pinned_calls_survive_a_drop_everything_pass():
    payload = build(("Read", {"file": "a.py"}), ("Read", {"file": "b.py"}))
    result = run(payload, ScoreMap(default=(0.0, 0.0)), preserve_recent=2)
    kept_ids = {call.id for message in result.messages for call in message.tool_calls}
    assert "toolu_2" in kept_ids  # newest messages, pinned
    assert "toolu_1" not in kept_ids  # judged and dropped


# --- decisions -------------------------------------------------------------------------


def test_result_still_needed_keeps_the_pair():
    result = run(build(("Read", {"file": "a.py"})), ScoreMap(default=(0.9, 0.9)))
    assert decisions_of(result) == {"toolu_1": "keep"}
    kept = [call for message in result.messages for call in message.tool_calls]
    assert len(kept) == 1 and kept[0].result is not None
    assert kept[0].result.text == "y" * 40
    assert result.report["semantic_guarantee"] == "judged"
    assert result.report["degraded"] is False


def test_call_kept_but_result_spent_trims_the_result():
    result = run(
        build(("Bash", {"cmd": "pytest"}), result_chars=400),
        ScoreMap(default=(0.9, 0.0)),
        trim_head_chars=100,
        threshold=0.5,
    )
    assert decisions_of(result) == {"toolu_1": "trim"}
    call = next(call for message in result.messages for call in message.tool_calls)
    assert call.result is not None
    assert call.result.text.startswith("y" * 100)
    assert "lcc: 300 chars of this tool result dropped" in call.result.text
    assert result.report["tool_calls_trimmed"] == 1
    assert result.report["chars_after"] < result.report["chars_before"]


def test_both_probabilities_low_drops_call_and_result_together():
    result = run(build(("Read", {"file": "a.py"})), ScoreMap(default=(0.1, 0.1)))
    assert decisions_of(result) == {"toolu_1": "drop"}
    # The call and its result are gone; the message that held them keeps its text, and a
    # message left with nothing disappears.
    assert [message.role for message in result.messages] == ["user", "assistant"]
    assert result.messages[1].text == "Running the test suite now."
    assert result.messages[1].tool_calls == []
    assert result.report["messages_after"] == 2
    assert result.report["tool_calls_dropped"] == 1


def test_user_and_assistant_text_is_never_touched():
    payload = build(("Read", {"file": "a.py"}), text="Please fix the parser and never edit src/generated.")
    result = run(payload, ScoreMap(default=(0.0, 0.0)))
    texts = [message.text for message in result.messages]
    assert texts[0] == "Please fix the parser and never edit src/generated."
    assert "Running the test suite now." in texts


# --- failure modes ---------------------------------------------------------------------


def test_without_a_client_every_call_is_kept_and_reported(monkeypatch):
    monkeypatch.setattr(transcript_module, "_resolve_client", lambda: None)
    result = run(build(("Read", {"file": "a.py"})), None)
    assert result.report["degraded"] is True
    assert result.report["degradation_reason"] == "jev_unavailable_fail_safe"
    assert result.report["semantic_guarantee"] == "none"
    assert decisions_of(result) == {"toolu_1": "keep"}
    assert any("fail-safe" in warning for warning in result.report["warnings"])


def test_a_failed_batch_keeps_what_it_could_not_judge():
    class Exploding(ScoreMap):
        def evaluate(self, state, questions):
            raise JevRequestError("network error: timed out")

    result = run(build(("Read", {"file": "a.py"})), Exploding())
    assert decisions_of(result) == {"toolu_1": "keep"}
    assert result.report["degraded"] is True
    assert result.report["provider_used"] == "degraded"
    assert result.report["semantic_guarantee"] == "none"


def test_out_of_range_answers_are_rejected_not_clamped():
    class Wild(ScoreMap):
        def evaluate(self, state, questions):
            return {
                "answers": {
                    qid: {"type": "noul", "noul": 1.7} for qid in questions
                },
                "model": "jev-2026-09-21",
            }

    result = run(build(("Read", {"file": "a.py"})), Wild())
    assert decisions_of(result) == {"toolu_1": "keep"}
    assert any("out_of_range" in warning for warning in result.report["warnings"])


def test_unsupported_provider_is_refused():
    with pytest.raises(UnsupportedTranscriptProviderError):
        run(build(("Read", {"file": "a.py"})), ScoreMap(), provider="mechanical")


def test_a_conversation_that_cannot_fit_is_refused_rather_than_judged_blind():
    payload = build(
        ("Read", {"file": "a.py"}), ("Read", {"file": "b.py"}), ("Read", {"file": "c.py"})
    )
    with pytest.raises(TranscriptFitError):
        run(payload, ScoreMap(), max_state_tokens=1)


def test_fitting_stages_are_reported_when_the_budget_is_tight():
    big_input = {"file": "x" * 4000, "offset": 1}
    payload = build(*[("Read", big_input) for _ in range(3)])
    generous = run(payload, ScoreMap(), max_state_tokens=100_000)
    tight = run(payload, ScoreMap(), max_state_tokens=300)
    assert generous.report["state_fit_stage"] == "full"
    assert tight.report["state_fit_stage"] in {"inputs-200", "calls-one-line"}
    assert tight.report["state_tokens"] <= 300
    assert tight.report["degraded"] is False


def test_batches_stay_inside_the_request_budget():
    payload = build(*[("Read", {"file": f"{name}.py"}) for name in "abcdef"])
    client = ScoreMap()
    result = run(payload, client, batch_calls=2)
    assert result.report["requests"] == 3
    assert len(client.question_batches) == 3


# --- audit trail -----------------------------------------------------------------------


def test_report_reads_through_lcc_explain():
    result = run(build(("Read", {"file": "a.py"}), ("Read", {"file": "b.py"})), ScoreMap(default=(0.9, 0.0)))
    text = render_explanation(result.report)
    assert "lcc explain" in text
    assert "DROPPED" in text and "TRIMMED" in text
    assert "call kept, result trimmed" in text.lower() or "trim" in text.lower()


def test_decisions_carry_what_an_auditor_needs():
    result = run(build(("Bash", {"cmd": "pytest"}), result_chars=400), ScoreMap(default=(0.9, 0.0)))
    entry = next(d for d in result.decisions if d["source"] == "jev")
    assert {"id", "decision", "score", "keep_call", "keep_result", "chars", "chars_after", "reason"} <= set(entry)
    assert entry["keep_call"] == 0.9 and entry["keep_result"] == 0.0
    assert entry["chars"] > entry["chars_after"]
