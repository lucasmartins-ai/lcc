"""Tool-call compaction: the message-level sibling of block compaction (ADR 0013/0014).

Block compaction scores text blocks inside one document. This mode scores the **tool calls**
of an agent transcript: it pairs each ``tool_use`` with its ``tool_result`` by id, pins the
first and the newest ``preserve_recent`` messages, and asks Jev two typed questions per
non-pinned call — does the call itself still matter, and does its result still need to be
there verbatim. Text written by the user or the assistant is never scored, never trimmed
and never rewritten.

Decisions per non-pinned call (``keep_call`` / ``keep_result`` are Jev keep-probabilities):

- ``keep_result >= threshold``: call and result both stay, byte for byte.
- ``keep_call >= threshold``: the call stays, its result is cut to ``trim_head_chars``
  plus a one-line note (the trim gear — the call is kept because knowing it happened still
  matters, the payload is not).
- otherwise: call and result are removed together. A result is never left without its call.

Fail-safe direction, unchanged from ADR 0013: **nothing is dropped that was not judged.**
A missing key, a failed batch, a malformed answer, or a history that cannot fit the state
budget leaves the call alone and is reported with a typed reason and ``degraded: true``.

``mechanical`` cannot answer "is this tool output still needed": a lexical overlap score is
not a judgement about whether work is finished. ``laya`` can, locally and offline. Tool-call
payloads are small — measured over real sessions, 97% fit Laya's window where only 31% of
prose blocks do — which is why the local judge is the practical choice for this mode.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from lcc.relevance.jev import JEV_CONTEXT_LIMIT_TOKENS, JevClient, jev_tokens, parse_noul_answer
from lcc.relevance.transcript_lossless import lossless_decisions, verify_lossless
from lcc.relevance.transcript_rules import rules_decisions
from lcc.token_budget import count_tokens

TRANSCRIPT_SCHEMA_VERSION = "transcript-compaction-1.0"

#: Why the local judge could not start, if it could not. Holds the most recent cause and
#: is surfaced by :func:`compact_transcript`, so a degraded run names the real reason
#: instead of leaving the operator with per-batch noise.
LAYA_INIT_ERROR: str | None = None
LOGGER = logging.getLogger("lcc.transcript")

#: Providers this mode accepts: a semantic judge (``auto`` prefers Jev), or ``rules`` — the
#: offline deterministic policy.
SUPPORTED_PROVIDERS = ("jev", "laya", "auto", "rules")
#: ``rules`` modes. ``lossless`` (default, :mod:`lcc.relevance.transcript_lossless`) only
#: replaces results whose text survives verbatim in a later kept result, and verifies it.
#: ``lossy`` (:mod:`lcc.relevance.transcript_rules`) is EXPERIMENTAL: it trims and drops
#: outputs an agent may still need and failed blind audits v0.4 (21/150) and v0.5 (36/132).
RULES_MODES = ("lossless", "lossy")
DEFAULT_THRESHOLD = 0.5
DEFAULT_PRESERVE_RECENT = 6
DEFAULT_TRIM_HEAD_CHARS = 300
DEFAULT_MAX_STATE_TOKENS = 25000
DEFAULT_MAX_REQUEST_TOKENS = 30000
DEFAULT_BATCH_CALLS = 8
DEFAULT_MIN_REDUCTION = 0.25

#: Input truncation applied to tool inputs while fitting the state into the budget.
_FIT_INPUT_CHARS = 200
#: Long non-pinned texts are abridged to this head (+ the same tail) while fitting.
_FIT_TEXT_HEAD = 400
_FIT_TEXT_TAIL = 200
#: Request keys around state + questions (``{"model": ..., "state": {"goal", "conversation"}``).
_ENVELOPE_TOKENS = 64


class TranscriptError(RuntimeError):
    """Base error for transcript compaction."""


class UnsupportedTranscriptProviderError(TranscriptError):
    """Asked for a provider that cannot judge tool-call relevance (mechanical)."""


class TranscriptFitError(TranscriptError):
    """The conversation does not fit the state budget even after every fitting stage."""


# --------------------------------------------------------------------------------------
# input model
# --------------------------------------------------------------------------------------


@dataclass
class ToolResult:
    """One ``tool_result``: the payload a tool returned for a call."""

    id: str
    text: str
    message_index: int
    is_error: bool = False


@dataclass
class ToolCall:
    """One ``tool_use`` plus the result it was paired with, when the transcript has one."""

    id: str
    tool: str
    input: dict[str, Any]
    message_index: int
    result: ToolResult | None = None

    @property
    def chars(self) -> int:
        """Characters the call and its result occupy (what a decision can remove)."""
        payload = len(json.dumps(self.input, ensure_ascii=False, default=str))
        result_chars = len(self.result.text) if self.result is not None else 0
        return payload + result_chars


@dataclass
class TranscriptMessage:
    """One turn: user/assistant text, plus the tool calls and results it carries."""

    role: str
    text: str
    message_index: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    pinned: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.text.strip() or self.tool_calls or self.tool_results)


@dataclass
class TranscriptCompactionRequest:
    """One tool-call compaction pass over a parsed (or raw) transcript payload."""

    payload: Any
    question: str
    provider: str = "jev"
    threshold: float = DEFAULT_THRESHOLD
    preserve_recent: int = DEFAULT_PRESERVE_RECENT
    trim_head_chars: int = DEFAULT_TRIM_HEAD_CHARS
    max_state_tokens: int = DEFAULT_MAX_STATE_TOKENS
    max_request_tokens: int = DEFAULT_MAX_REQUEST_TOKENS
    batch_calls: int = DEFAULT_BATCH_CALLS
    max_workers: int = 4
    min_reduction: float = DEFAULT_MIN_REDUCTION
    model: str = "gpt-4.1"
    jev_model: str = "jev-latest"
    laya_model: str | None = None
    client: Any = None
    rules_mode: str = "lossless"


@dataclass
class TranscriptCompactionResult:
    """Compacted messages, the per-call decision trail, and the audit report."""

    messages: list[TranscriptMessage]
    decisions: list[dict[str, Any]]
    report: dict[str, Any]


def messages_to_payload(messages: list[TranscriptMessage]) -> list[dict[str, Any]]:
    """Inverse of :func:`parse_transcript`: the conversation in the input's own shape.

    Callers that hand a transcript over (a Claude Code hook, the MCP tool) get their own
    field names back, so the compacted messages can be mapped onto the session directly.
    """
    payload: list[dict[str, Any]] = []
    for message in messages:
        entry: dict[str, Any] = {"role": message.role, "text": message.text}
        if message.tool_calls:
            entry["toolUses"] = [
                {"tool_use_id": call.id, "tool": call.tool, "input": call.input}
                for call in message.tool_calls
            ]
        if message.tool_results:
            entry["toolResults"] = [
                {"tool_use_id": result.id, "text": result.text}
                | ({"is_error": True} if result.is_error else {})
                for result in message.tool_results
            ]
        payload.append(entry)
    return payload


def _message_dicts(payload: Any) -> list[dict[str, Any]]:
    messages = payload.get("messages") if isinstance(payload, dict) else payload
    if not isinstance(messages, list):
        raise TranscriptError(
            "transcript payload must be a list of messages or {'messages': [...]}, "
            f"got {type(payload).__name__}"
        )
    for message in messages:
        if not isinstance(message, dict):
            raise TranscriptError(f"every message must be an object, got {type(message).__name__}")
    return messages


def _call_id(raw: dict[str, Any]) -> str | None:
    for key in ("tool_use_id", "id", "tool_call_id"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _blocks(message: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = message.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            raise TranscriptError(f"message field {key!r} must be a list")
        return [item for item in value if isinstance(item, dict)]
    return []


def parse_transcript(payload: Any) -> list[TranscriptMessage]:
    """Parse a transcript into messages, pairing calls with results by id.

    Accepts ``{"messages": [...]}`` or a bare list. Each message carries ``role`` and
    ``text`` plus tool blocks under the camelCase names a Claude Code hook hands over
    (``toolUses`` / ``toolResults``) or the snake_case equivalents
    (``tool_calls`` / ``tool_results``); a call's id may be ``tool_use_id`` or ``id``.

    Unknown fields are ignored, missing ones become empty. Malformed tool blocks (no id,
    or an id that is not a string) raise :class:`TranscriptError` rather than being
    silently dropped: a decision taken over a half-parsed transcript is not auditable.
    """
    messages: list[TranscriptMessage] = []
    results_by_id: dict[str, ToolResult] = {}

    for index, message in enumerate(_message_dicts(payload)):
        role = message.get("role")
        if not isinstance(role, str) or not role:
            raise TranscriptError(f"message {index} has no string 'role'")
        text = message.get("text", "")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise TranscriptError(f"message {index} 'text' must be a string")

        results: list[ToolResult] = []
        for raw in _blocks(message, "toolResults", "tool_results"):
            result_id = _call_id(raw)
            if result_id is None:
                raise TranscriptError(f"message {index} has a tool result without an id")
            inner = raw.get("text", "")
            results.append(
                ToolResult(
                    id=result_id,
                    text=inner if isinstance(inner, str) else json.dumps(inner, default=str),
                    message_index=index,
                    is_error=raw.get("is_error") is True,
                )
            )
            results_by_id[result_id] = results[-1]

        calls: list[ToolCall] = []
        for raw in _blocks(message, "toolUses", "tool_calls"):
            call_id = _call_id(raw)
            if call_id is None:
                raise TranscriptError(f"message {index} has a tool call without an id")
            tool = raw.get("tool") or raw.get("name") or "tool"
            tool_input = raw.get("input")
            calls.append(
                ToolCall(
                    id=call_id,
                    tool=str(tool),
                    input=tool_input if isinstance(tool_input, dict) else {},
                    message_index=index,
                )
            )

        messages.append(
            TranscriptMessage(
                role=role,
                text=text,
                message_index=index,
                tool_calls=calls,
                tool_results=results,
            )
        )

    for parsed_message in messages:
        for call in parsed_message.tool_calls:
            call.result = results_by_id.get(call.id)
    return messages


# --------------------------------------------------------------------------------------
# state fitting
# --------------------------------------------------------------------------------------


def _line_for_call(call: ToolCall) -> str:
    """One line standing in for a call whose input is not worth sending: what happened."""
    keys = ", ".join(f"{key}={value}" for key, value in list(call.input.items())[:2])
    outcome = f"ok {len(call.result.text)}ch" if call.result is not None else "pending"
    return f"{call.id} {call.tool} {keys} -> {outcome}".strip()


def _abridge(text: str) -> str:
    if len(text) <= _FIT_TEXT_HEAD + _FIT_TEXT_TAIL:
        return text
    removed = len(text) - _FIT_TEXT_HEAD - _FIT_TEXT_TAIL
    return f"{text[:_FIT_TEXT_HEAD]}\n[... {removed} chars omitted ...]\n{text[-_FIT_TEXT_TAIL:]}"


def _render_state(
    messages: list[TranscriptMessage],
    candidates: list[ToolCall],
    *,
    objective: str,
    stage: str,
) -> list[dict[str, Any]]:
    """Render the conversation for Jev at one fitting stage. Full text stays in the output."""
    candidates_by_message: dict[int, set[str]] = {}
    for call in candidates:
        candidates_by_message.setdefault(call.message_index, set()).add(call.id)

    rendered: list[dict[str, Any]] = []
    for message in messages:
        relevant_ids = candidates_by_message.get(message.message_index, set())
        if (
            stage == "calls-one-line"
            and not relevant_ids
            and not message.pinned
            and not message.text.strip()
            and (message.tool_calls or message.tool_results)
        ):
            # A call-only run with nothing to judge: one line is enough context.
            rendered.append(
                {
                    "role": message.role,
                    "tool_calls": [_line_for_call(call) for call in message.tool_calls],
                }
            )
            continue

        entry: dict[str, Any] = {"role": message.role}
        text = message.text
        if not message.pinned and (
            stage == "calls-one-line" or (stage == "inputs-200" and len(text) > _FIT_TEXT_HEAD)
        ):
            text = _abridge(text)
        if text.strip():
            entry["text"] = text

        calls_payload: list[dict[str, Any]] = []
        for call in message.tool_calls:
            if stage == "calls-one-line" and call.id not in relevant_ids and not message.pinned:
                calls_payload.append({"line": _line_for_call(call)})
                continue
            call_entry: dict[str, Any] = {"id": call.id, "tool": call.tool}
            if stage == "full":
                call_entry["input"] = call.input
            else:
                clipped = json.dumps(call.input, ensure_ascii=False, default=str)
                call_entry["input"] = (
                    call.input
                    if len(clipped) <= _FIT_INPUT_CHARS
                    else clipped[:_FIT_INPUT_CHARS] + "…"
                )
            calls_payload.append(call_entry)
        if calls_payload:
            entry["tool_calls"] = calls_payload

        results_payload = [
            {
                "id": result.id,
                "note": f"ok, {len(result.text)} chars" + ("" if result.text else " (empty)"),
            }
            for result in message.tool_results
        ]
        if results_payload:
            entry["tool_results"] = results_payload
        if entry.get("text") or calls_payload or results_payload:
            rendered.append(entry)

    return [{"goal": objective}] + rendered


_FIT_STAGES = ("full", "inputs-200", "calls-one-line")


def _budget_tokens(text: str) -> int:
    """Tokens a request will really cost, for budgeting — never an optimistic estimate.

    Uses the Jev client's calibrated bound (``jev.jev_tokens``), the same count its
    pre-flight applies: budgeting with anything smaller lets a batch be built that the API
    refuses (real-context bench v0.1: 77 x ``400 max_tokens_exceeded`` from requests the
    old tiktoken/heuristic count scored under 30k), and the pass degrades to keep-everything.
    """
    return jev_tokens(text)


def _fit_state(
    messages: list[TranscriptMessage],
    candidates: list[ToolCall],
    *,
    objective: str,
    max_state_tokens: int,
) -> tuple[list[dict[str, Any]], str, int]:
    """Fit the conversation into the state budget, cheapest stage first.

    Returns ``(state, stage, tokens)``. Raises :class:`TranscriptFitError` when even the
    last stage does not fit — the caller then keeps every call (fail-safe) instead of
    judging a transcript it could not show the judge.
    """
    last_tokens = 0
    for stage in _FIT_STAGES:
        state = _render_state(messages, candidates, objective=objective, stage=stage)
        tokens = _budget_tokens(json.dumps(state, ensure_ascii=False, default=str))
        last_tokens = tokens
        if tokens <= max_state_tokens:
            return state, stage, tokens
    raise TranscriptFitError(
        f"conversation does not fit the {max_state_tokens}-token state budget "
        f"(smallest rendering is {last_tokens} tokens); raise --max-state-tokens or "
        "compact fewer messages"
    )


def _batches(
    candidates: list[ToolCall],
    state_tokens: int,
    *,
    batch_calls: int,
    max_request_tokens: int,
) -> list[list[ToolCall]]:
    """Split candidates into requests that stay inside the request budget.

    Every request carries the whole state (the judge sees the conversation each time), so
    the room left for questions is ``max_request_tokens - state_tokens``.
    """
    room = max_request_tokens - state_tokens - _ENVELOPE_TOKENS
    if room <= 0:
        raise TranscriptFitError(
            f"state ({state_tokens} tokens) leaves no room for questions inside the "
            f"{max_request_tokens}-token request budget; raise --max-request-tokens"
        )
    batches: list[list[ToolCall]] = []
    current: list[ToolCall] = []
    current_tokens = 0
    size = max(1, batch_calls)
    for call in candidates:
        # What the request really carries for this call: both questions, instructions
        # included (+1 for the separator), not just the call's id and input.
        question_tokens = _budget_tokens(json.dumps(_questions([call]), ensure_ascii=False)) + 1
        if current and (len(current) >= size or current_tokens + question_tokens > room):
            batches.append(current)
            current, current_tokens = [], 0
        if not current and question_tokens > room:
            raise TranscriptFitError(
                f"a single question for {call.id} ({question_tokens} tokens) does not fit the "
                f"request budget; raise --max-request-tokens"
            )
        current.append(call)
        current_tokens += question_tokens
    if current:
        batches.append(current)
    return batches


def _questions(batch: list[ToolCall]) -> dict[str, Any]:
    questions: dict[str, Any] = {}
    for call in batch:
        questions[f"keep_call_{call.id}"] = {
            "type": "noul",
            "instructions": (
                f"Judge the probability that tool call {call.id} ({call.tool}, in the "
                "conversation state) still matters in this session: knowing that the call "
                "was made, with the input it was made with, still serves the goal. A call "
                "whose purpose is finished and whose input adds nothing should score low."
            ),
            "criteria": {
                "true": "The fact that this call happened, and its input, still matter.",
                "false": "The call is finished and its input adds nothing to the goal.",
            },
        }
        questions[f"keep_result_{call.id}"] = {
            "type": "noul",
            "instructions": (
                f"Judge the probability that the OUTPUT of tool call {call.id} ({call.tool}) "
                "still needs to be available verbatim in this session. Score low only when "
                "the work it was run for is finished and re-running the tool would produce "
                "the same information again if it were needed."
            ),
            "criteria": {
                "true": "The output's contents are still needed and re-running would not do.",
                "false": "The output is spent: the work it served is finished.",
            },
        }
    return questions


# --------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------


def _resolve_client(provider: str = "jev", laya_model: str | None = None) -> Any | None:
    """Resolve the judge for ``provider``; tests monkeypatch this seam to stay offline.

    Both judges expose the same ``evaluate(state, questions)`` contract, so ``_score``
    treats them identically. Laya is warmed here on purpose: without it, a missing
    checkpoint or an unimportable dependency surfaces as one ``laya_batch_N_failed``
    warning per batch, which reads like a flaky judge rather than an absent one.
    Warming once turns the real cause into a single typed degradation.
    """
    if provider == "laya":
        from lcc.relevance.laya import LayaClient

        try:
            client = LayaClient(model=laya_model)
            client._ensure_agent()
        except Exception as exc:  # missing extra, checkpoint, or weights
            global LAYA_INIT_ERROR
            LAYA_INIT_ERROR = str(exc)
            LOGGER.warning(
                "laya judge unavailable, degrading to keep-everything: %s", exc
            )
            return None
        return client

    from lcc.relevance.jev import default_ledger_path

    return JevClient.from_env(ledger_path=default_ledger_path())


def _score(
    client: Any,
    state: list[dict[str, Any]],
    batches: list[list[ToolCall]],
    *,
    timeout_note: str,
    judge: str = "jev",
) -> tuple[dict[str, tuple[float | None, float | None]], int, int, list[str], str | None]:
    """Ask the judge for both probabilities of every candidate; never raises on failure.

    Returns ``(answers, calls, latency_ms, warnings, resolved_model)`` where each entry is
    ``(keep_call, keep_result)``; an answer that is missing, malformed or out of range is
    left out so the caller keeps that call (fail-safe).
    """
    answers: dict[str, tuple[float | None, float | None]] = {}
    warnings: list[str] = []

    def score_batch(index: int, batch: list[ToolCall]) -> tuple[int, Any, int, str | None]:
        started = time.perf_counter()
        state_payload = {"goal": state[0].get("goal"), "conversation": state[1:]}
        try:
            response = client.evaluate(state_payload, _questions(batch))
        except Exception as exc:
            # Both judges are fail-safe here: LayaError and JevError both mean "this
            # batch was not judged", so the calls stay. Anything unexpected is caught too,
            # because dropping a call the user can still see is the worse failure.
            return (
                index,
                None,
                int((time.perf_counter() - started) * 1000),
                f"{judge}_batch_{index}_failed: {exc}",
            )
        return index, response, int((time.perf_counter() - started) * 1000), None

    workers = max(1, min(8, len(batches)))
    if workers <= 1:
        outcomes = [score_batch(index, batch) for index, batch in enumerate(batches, start=1)]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(score_batch, index, batch)
                for index, batch in enumerate(batches, start=1)
            ]
            outcomes = [future.result() for future in futures]

    calls = 0
    latency_ms = 0
    resolved_model: str | None = None
    for index, response, batch_latency, failure in outcomes:
        latency_ms += batch_latency
        if response is None:
            warnings.append((failure or f"{judge}_batch_{index}_failed") + f": {timeout_note}")
            continue
        calls += 1
        resolved_model = getattr(client, "last_resolved_model", None) or resolved_model
        payload = response.get("answers") if isinstance(response, dict) else None
        if not isinstance(payload, dict):
            warnings.append(f"{judge}_malformed_response:batch_{index}")
            continue
        for call in batches[index - 1]:
            keep_call: float | None = None
            keep_result: float | None = None
            for key, is_call in ((f"keep_call_{call.id}", True), (f"keep_result_{call.id}", False)):
                # Only a missing or out-of-range score is worth reporting. Laya
                # returns no per-question confidence, and confidence never gates a
                # decision here, so warning about it would add one line per question
                # to every local run without changing a single keep or drop.
                score, _confidence, problem = parse_noul_answer(payload.get(key))
                if score is None:
                    kind = "out_of_range" if problem == "out_of_range" else "missing"
                    warnings.append(f"{judge}_{kind}_answer:{key}")
                if is_call:
                    keep_call = score
                else:
                    keep_result = score
            answers[call.id] = (keep_call, keep_result)
    return answers, calls, latency_ms, warnings, resolved_model


# --------------------------------------------------------------------------------------
# decisions + application
# --------------------------------------------------------------------------------------


def _decide(
    call: ToolCall,
    answers: dict[str, tuple[float | None, float | None]],
    *,
    threshold: float,
    trim_head_chars: int,
    judge: str = "jev",
) -> dict[str, Any]:
    """Map one candidate's probabilities onto keep/trim/drop, failing safe when unjudged."""
    keep_call, keep_result = answers.get(call.id, (None, None))
    chars = call.chars
    if keep_call is None and keep_result is None:
        return {
            "id": call.id,
            "decision": "keep",
            "score": None,
            "keep_call": None,
            "keep_result": None,
            "chars": chars,
            "chars_after": chars,
            "source": "fail_safe",
            "reason": "not_judged_fail_safe",
            "message_index": call.message_index,
            "tool": call.tool,
        }

    effective_result = keep_result if keep_result is not None else keep_call
    if effective_result is not None and effective_result >= threshold:
        decision, reason = "keep", "result_still_needed"
    elif keep_call is not None and keep_call >= threshold:
        # The call is worth remembering, its payload is not — but only trim when trimming
        # actually removes characters. A result shorter than the head would grow the
        # transcript once the audit note is appended, and a trim that adds bytes is not a
        # trim (block mode calls this case `kept_whole`).
        original = call.result.text if call.result is not None else ""
        trimmed = (
            _trimmed_result_text(original, head_chars=trim_head_chars, tool=call.tool)
            if call.result is not None
            else None
        )
        if trimmed is not None and len(trimmed) < len(original):
            decision, reason = "trim", "call_kept_result_trimmed"
        else:
            decision, reason = "keep", "short_result_kept_whole"
    else:
        decision, reason = "drop", "call_and_result_not_needed"

    kept = chars
    if decision == "drop":
        kept = 0
    elif decision == "trim" and call.result is not None:
        kept = len(json.dumps(call.input, ensure_ascii=False, default=str)) + len(
            _trimmed_result_text(call.result.text, head_chars=trim_head_chars, tool=call.tool)
        )
    return {
        "id": call.id,
        "decision": decision,
        "score": effective_result,
        "keep_call": keep_call,
        "keep_result": keep_result,
        "chars": chars,
        "chars_after": kept,
        "source": judge,
        "reason": reason,
        "message_index": call.message_index,
        "tool": call.tool,
    }


def _with_chars(
    decision: dict[str, Any], call: ToolCall, *, trim_head_chars: int
) -> dict[str, Any]:
    """Fill ``chars`` / ``chars_after`` for a decision made outside :func:`_decide`.

    A trim that would not shrink the result is turned back into a keep, as in ``_decide``.
    """
    chars = call.chars
    after = chars
    if decision["decision"] == "drop":
        after = 0
    elif decision["decision"] == "dedupe" and call.result is not None:
        after = chars - len(call.result.text) + len(decision["note"])
    elif decision["decision"] == "trim" and call.result is not None:
        trimmed = _trimmed_result_text(
            call.result.text,
            head_chars=decision.get("trim_head_chars") or trim_head_chars,
            tool=call.tool,
            tail_chars=decision.get("trim_tail_chars", 0),
        )
        if len(trimmed) < len(call.result.text):
            after = chars - len(call.result.text) + len(trimmed)
        else:
            decision = dict(decision, decision="keep", reason="short_result_kept_whole")
    return dict(decision, chars=chars, chars_after=after)


def _trimmed_result_text(text: str, *, head_chars: int, tool: str, tail_chars: int = 0) -> str:
    if head_chars <= 0:
        return ""
    tail = text[-tail_chars:] if tail_chars > 0 and len(text) > head_chars + tail_chars else ""
    removed = len(text) - head_chars - len(tail)
    note = f"[... lcc: {removed} chars of this tool result dropped; re-run {tool} for the rest ...]"
    return f"{text[:head_chars]}\n{note}" + (f"\n{tail}" if tail else "")


def _apply(
    messages: list[TranscriptMessage],
    decisions: list[dict[str, Any]],
    *,
    trim_head_chars: int,
) -> list[TranscriptMessage]:
    """Rebuild the transcript: drop whole pairs, trim results, keep every text byte.

    New ``ToolResult`` objects are built for trimmed results instead of mutating the
    parsed input, so the caller can still account for the original bytes.
    """
    by_id = {decision["id"]: decision for decision in decisions}
    # Trimmed results are rendered once, up front: a call and its result usually live in
    # different messages, so a per-message map would trim the wrong copy.
    trimmed: dict[str, ToolResult] = {}
    for message in messages:
        for result in message.tool_results:
            replacement = _possibly_trimmed(
                result, by_id.get(result.id), trim_head_chars=trim_head_chars
            )
            if replacement is not result:
                trimmed[result.id] = replacement

    rebuilt: list[TranscriptMessage] = []
    for message in messages:
        calls: list[ToolCall] = []
        for call in message.tool_calls:
            decision = by_id.get(call.id)
            if decision is not None and decision["decision"] == "drop":
                continue
            kept_result = None if call.result is None else trimmed.get(call.result.id, call.result)
            calls.append(
                ToolCall(
                    id=call.id,
                    tool=call.tool,
                    input=call.input,
                    message_index=call.message_index,
                    result=kept_result,
                )
            )
        # Results stay in the message they arrived in: a transcript that comes back with its
        # blocks rearranged is not the transcript the caller handed over.
        results: list[ToolResult] = []
        for result in message.tool_results:
            decision = by_id.get(result.id)
            if decision is not None and decision["decision"] == "drop":
                continue
            results.append(trimmed.get(result.id, result))

        candidate = TranscriptMessage(
            role=message.role,
            text=message.text,
            message_index=message.message_index,
            tool_calls=calls,
            tool_results=results,
            pinned=message.pinned,
        )
        if candidate.has_content:
            rebuilt.append(candidate)
    return rebuilt


def _possibly_trimmed(
    result: ToolResult,
    decision: dict[str, Any] | None,
    *,
    trim_head_chars: int,
) -> ToolResult:
    if decision is not None and decision["decision"] == "dedupe":
        return ToolResult(
            id=result.id,
            text=decision["note"],
            message_index=result.message_index,
            is_error=result.is_error,
        )
    if decision is None or decision["decision"] != "trim":
        return result
    tool = decision.get("tool") or "the tool"
    return ToolResult(
        id=result.id,
        text=_trimmed_result_text(
            result.text,
            head_chars=decision.get("trim_head_chars") or trim_head_chars,
            tool=tool,
            tail_chars=decision.get("trim_tail_chars", 0),
        ),
        message_index=result.message_index,
        is_error=result.is_error,
    )


# --------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------


def _text_of(messages: list[TranscriptMessage]) -> str:
    """Everything a decision can touch, as text, for exact before/after accounting."""
    parts: list[str] = []
    for message in messages:
        parts.append(message.text)
        for call in message.tool_calls:
            parts.append(f"{call.id} {call.tool} {json.dumps(call.input, default=str)}")
        for result in message.tool_results:
            parts.append(result.text)
    return "\n".join(parts)


def compact_transcript(request: TranscriptCompactionRequest) -> TranscriptCompactionResult:
    """Run one tool-call compaction pass over a transcript payload.

    Raises :class:`UnsupportedTranscriptProviderError` for a provider that cannot judge
    tool-call relevance, :class:`TranscriptError` for a malformed payload, and
    :class:`TranscriptFitError` when the history cannot be shown inside the budget. Every
    provider failure degrades to keeping the calls it could not judge.
    """
    if request.provider not in SUPPORTED_PROVIDERS:
        raise UnsupportedTranscriptProviderError(
            f"tool-call compaction needs a semantic judge; {request.provider!r} cannot answer "
            "'is this tool output still needed'. Use --provider jev, laya, auto, or "
            "rules (offline policy)."
        )
    if not 0.0 <= request.threshold <= 1.0:
        raise TranscriptError("threshold must be between 0 and 1")
    if request.trim_head_chars < 0:
        raise TranscriptError("trim_head_chars must be >= 0")
    if request.preserve_recent < 0:
        raise TranscriptError("preserve_recent must be >= 0")
    if request.rules_mode not in RULES_MODES:
        raise TranscriptError(f"rules_mode must be one of {RULES_MODES}")

    messages = parse_transcript(request.payload)
    for message in messages:
        message.pinned = False
    if messages:
        messages[0].pinned = True
    if request.preserve_recent:
        for message in messages[-request.preserve_recent :]:
            message.pinned = True

    candidates = [
        call
        for message in messages
        if not message.pinned
        for call in message.tool_calls
        if call.result is not None
    ]
    before_text = _text_of(messages)

    warnings: list[str] = []
    provider_requested = request.provider
    provider_used = "laya" if request.provider == "laya" else "jev"
    degraded = False
    degradation_reason: str | None = None
    calls = 0
    latency_ms = 0
    resolved_model: str | None = None
    state_tokens = 0
    fit_stage = "none"
    batch_count = 0
    decisions: list[dict[str, Any]] = []

    rules = request.provider == "rules"
    lossless = rules and request.rules_mode == "lossless"
    if rules:
        provider_used = "rules"
    client = (
        None
        if rules
        else request.client
        if request.client is not None
        else _resolve_client(request.provider, request.laya_model)
    )
    if client is not None and request.jev_model and request.provider != "laya":
        client.model = request.jev_model

    judge = "laya" if request.provider == "laya" else "jev"
    if not candidates:
        warnings.append("no_scorable_tool_calls: every call is pinned or has no result yet")
        degradation_reason = "no_candidates"
    elif rules:
        judge = "rules"
        raw_decisions = (
            lossless_decisions(messages, candidates)
            if lossless
            else rules_decisions(messages, candidates, request.question)
        )
        decisions = [
            _with_chars(decision, call, trim_head_chars=request.trim_head_chars)
            for decision, call in zip(raw_decisions, candidates, strict=True)
        ]
    elif client is None:
        degraded = True
        degradation_reason = f"{judge}_unavailable_fail_safe"
        if judge == "laya" and LAYA_INIT_ERROR:
            # Name the actual cause once instead of nine per-batch warnings.
            warnings.append(
                f"laya_unavailable: {LAYA_INIT_ERROR}; kept every tool call (fail-safe)"
            )
        else:
            warnings.append(
                f"{judge}_unavailable: no API key, missing local weights, or network "
                "disabled; kept every tool call (fail-safe)"
            )
        decisions = [
            _decide(call, {}, threshold=request.threshold, trim_head_chars=request.trim_head_chars)
            for call in candidates
        ]
    else:
        state, fit_stage, state_tokens = _fit_state(
            messages,
            candidates,
            objective=request.question,
            max_state_tokens=request.max_state_tokens,
        )
        batches = _batches(
            candidates,
            state_tokens,
            batch_calls=request.batch_calls,
            # A request over Jev's window would only be refused by the client pre-flight.
            max_request_tokens=request.max_request_tokens
            if judge == "laya"
            else min(request.max_request_tokens, JEV_CONTEXT_LIMIT_TOKENS),
        )
        batch_count = len(batches)
        answers, calls, latency_ms, score_warnings, resolved_model = _score(
            client,
            state,
            batches,
            timeout_note="those calls were kept (fail-safe)",
            judge=judge,
        )
        warnings.extend(score_warnings)
        decisions = [
            _decide(
                call,
                answers,
                threshold=request.threshold,
                trim_head_chars=request.trim_head_chars,
                judge=judge,
            )
            for call in candidates
        ]
        judged = sum(1 for decision in decisions if decision["source"] == judge)
        if judged == 0:
            degraded = True
            provider_used = "degraded"
            degradation_reason = f"{judge}_no_answers_fail_safe"
            warnings.append(
                f"{judge}_no_answers: every call was kept unjudged (fail-safe)"
            )
        elif judged < len(decisions):
            degraded = True
            provider_used = f"{judge}+partial_fail_safe"
            degradation_reason = f"{judge}_batch_failed"

    pinned_decisions = [
        {
            "id": call.id,
            "decision": "keep",
            "score": None,
            "keep_call": None,
            "keep_result": None,
            "chars": call.chars,
            "chars_after": call.chars,
            "source": "pin",
            "reason": "pinned_recent"
            if call.message_index != 0
            else "pinned_first_message",
            "message_index": call.message_index,
            "tool": call.tool,
        }
        for message in messages
        if message.pinned
        for call in message.tool_calls
    ]

    rebuilt = (
        _apply(messages, decisions, trim_head_chars=request.trim_head_chars)
        if decisions
        else list(messages)
    )
    lossless_violations: list[str] = []
    if lossless and decisions:
        # Belt and braces: the output is re-checked from the payloads alone. A violation
        # would be a bug in the policy, so the pass keeps everything instead of shipping it.
        lossless_violations = verify_lossless(request.payload, messages_to_payload(rebuilt))
        if lossless_violations:
            degraded = True
            degradation_reason = "lossless_verification_failed_fail_safe"
            warnings.append("lossless_verification_failed: kept every tool call (fail-safe)")
            decisions = [
                dict(d, decision="keep", reason="lossless_verification_failed",
                     chars_after=d["chars"])
                for d in decisions
            ]
            rebuilt = list(messages)

    after_text = _text_of(rebuilt)
    before_count = count_tokens(before_text, request.model)
    after_count = count_tokens(after_text, request.model)
    chars_before = len(before_text)
    chars_after = len(after_text)
    reduction = 0.0 if chars_before == 0 else max(0.0, 1.0 - chars_after / chars_before)

    scored = [decision for decision in decisions if decision["source"] == judge]
    judged_count = len(scored)
    if lossless and decisions and not lossless_violations:
        semantic_guarantee = "lossless"
    elif not candidates or client is None:
        semantic_guarantee = "none"
    elif decisions and judged_count == len(decisions):
        semantic_guarantee = "judged"
    elif judged_count:
        semantic_guarantee = "partial"
    else:
        semantic_guarantee = "none"

    tool_chars_before = sum(call.chars for call in candidates)
    tool_chars_after = sum(decision["chars_after"] for decision in decisions)
    tool_reduction = (
        0.0 if tool_chars_before == 0 else max(0.0, 1.0 - tool_chars_after / tool_chars_before)
    )

    report: dict[str, Any] = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "mode": "tool-calls",
        "objective": request.question,
        "provider_requested": provider_requested,
        "provider_used": provider_used,
        "rules_mode": request.rules_mode if rules else None,
        "lossless_violations": lossless_violations,
        "degraded": degraded,
        "degradation_reason": degradation_reason,
        "semantic_guarantee": semantic_guarantee,
        "jev_model_requested": request.jev_model,
        "jev_model_resolved": resolved_model,
        "threshold": request.threshold,
        "trim_threshold": None,
        "trim_head_chars": request.trim_head_chars,
        "preserve_recent": request.preserve_recent,
        "blocks_total": len(candidates) + len(pinned_decisions),
        "blocks_scored": len(scored),
        "blocks_protected": len(pinned_decisions),
        "calls": calls,
        "latency_ms": latency_ms,
        "chars_before": chars_before,
        "chars_after": chars_after,
        "reduction_ratio": reduction,
        "worth_it": reduction >= request.min_reduction,
        "min_reduction": request.min_reduction,
        "tool_chars_before": tool_chars_before,
        "tool_chars_after": tool_chars_after,
        "tool_reduction_ratio": tool_reduction,
        "tokens_before": before_count.value,
        "tokens_after": after_count.value,
        "token_count_method": before_count.method.value,
        "state_tokens": state_tokens,
        "state_fit_stage": fit_stage,
        "requests": batch_count,
        "messages_before": len(messages),
        "messages_after": len(rebuilt),
        "tool_calls_total": sum(len(message.tool_calls) for message in messages),
        "tool_calls_kept": sum(
            1 for decision in decisions if decision["decision"] == "keep"
        ),
        "tool_calls_trimmed": sum(1 for decision in decisions if decision["decision"] == "trim"),
        "tool_calls_dropped": sum(1 for decision in decisions if decision["decision"] == "drop"),
        "tool_calls_deduped": sum(
            1 for decision in decisions if decision["decision"] == "dedupe"
        ),
        "warnings": warnings,
        "decisions": pinned_decisions + decisions,
    }
    return TranscriptCompactionResult(
        messages=rebuilt, decisions=report["decisions"], report=report
    )
