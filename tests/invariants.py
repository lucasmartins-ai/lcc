"""The deterministic core's invariants, in one place (plan items B1 + B2).

Every invariant is a function that raises ``AssertionError`` naming itself. Unit tests, the
time-budgeted fuzz test (``test_invariants_fuzz.py``) and the adversarial corpus replay
(``tests/corpus/adversarial/``) all call :func:`check_transcript`, so a new invariant reaches
all three at once.

The seven invariants, over the product modes (``rules`` with ``lossless``, ``recoverable``,
``stashed``; see docs/EDGE_CASES.md):

1. idempotence: ``compact(compact(x)) == compact(x)``;
2. verbatim: texts, pinned messages and kept results are byte-identical, and every changed
   result is exactly the pointer its decision names;
3. recall round-trip: every stash pointer recalls the removed bytes, so replacing each pointer
   with its ``recall`` rebuilds the input;
4. no corruption: the output is valid UTF-8 (no lone surrogates) and survives a JSON round
   trip unchanged;
5. stable placeholder: the same input gives the same output and pointers in another stash
   directory (and, in ``test_placeholders_ignore_hash_seed``, another ``PYTHONHASHSEED``);
6. accounting: the report's counters reconcile with the decisions and the emitted text;
7. fail-closed: compaction either succeeds or raises ``ValueError`` / ``TranscriptError``, and
   it falls back to its keep-everything fail-safe only for a documented reason (today: duplicate
   tool ids, which output verification cannot pair). A broken pointer that the runtime check
   catches is safe for the user's bytes but silently removes nothing, so it fails here.

Run as a script, it prints one sha256 over the stashed output of every corpus case; the
hash-seed test compares that digest across interpreters.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from lcc.relevance.transcript import (
    TranscriptCompactionRequest,
    TranscriptError,
    _text_of,
    compact_transcript,
    messages_to_payload,
    parse_transcript,
)
from lcc.relevance.transcript_stash import recall, verify_stashed
from lcc.token_budget import count_tokens

PRODUCT_MODES = ("lossless", "recoverable", "stashed")
CORPUS = Path(__file__).parent / "corpus" / "adversarial"


class Rejected(Exception):
    """The input was refused the documented way (invariant 7 holds; nothing else to check)."""


def compact(payload: Any, mode: str, goal: str) -> Any:
    """One ``rules`` pass; invariant 7 (fail-closed) is checked here."""
    request = TranscriptCompactionRequest(
        payload=copy.deepcopy(payload), question=goal, provider="rules", rules_mode=mode
    )
    try:
        return compact_transcript(request)
    except (ValueError, TranscriptError) as exc:
        raise Rejected(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - anything else breaks invariant 7
        raise AssertionError(f"fail-closed: {mode} raised {type(exc).__name__}: {exc}") from exc


def assert_transcript_invariants(payload: list[dict[str, Any]], result: Any, options: dict):
    before = parse_transcript(copy.deepcopy(payload))
    after = result.messages
    report = result.report
    # Message order and text are untouched; only empty (call-less) messages may disappear.
    kept_index = [m.message_index for m in after]
    assert kept_index == sorted(kept_index)
    by_index = {m.message_index: m for m in before}
    for message in after:
        assert message.text == by_index[message.message_index].text
        assert message.role == by_index[message.message_index].role
    for message in before:
        if message.text.strip():
            assert message.message_index in kept_index
    # Pinned messages: the first and the newest preserve_recent come back unchanged.
    recent = options.get("preserve_recent", 6)
    pinned = {before[0].message_index} | {m.message_index for m in before[-recent:]} if recent \
        else {before[0].message_index}
    after_by_index = {m.message_index: m for m in after}
    for index in pinned:
        original = by_index[index]
        if not original.has_content:
            continue
        kept = after_by_index[index]
        assert [c.id for c in kept.tool_calls] == [c.id for c in original.tool_calls]
        assert [(r.id, r.text) for r in kept.tool_results] == [
            (r.id, r.text) for r in original.tool_results
        ]
    # Kept results are byte-identical; trims keep a byte-exact head.
    decisions = {d["id"]: d for d in result.decisions if d["source"] != "pin"}
    for message in after:
        originals = {r.id: r for r in by_index[message.message_index].tool_results}
        for res in message.tool_results:
            decision = decisions.get(res.id)
            if decision is None or decision["decision"] == "keep":
                assert res.text == originals[res.id].text
            elif decision["decision"] == "trim":
                head = res.text.split("\n[... lcc:", 1)[0]
                assert originals[res.id].text.startswith(head)
    # Accounting.
    counted = [d for d in result.decisions if d["source"] != "pin"]
    kinds = [d["decision"] for d in counted]
    assert report["tool_calls_kept"] == kinds.count("keep")
    assert report["tool_calls_trimmed"] == kinds.count("trim")
    assert report["tool_calls_dropped"] == kinds.count("drop")
    assert report["tool_calls_deduped"] == kinds.count("dedupe")
    assert report["tool_calls_replaced"] == kinds.count("replace")
    assert sum(1 for d in result.decisions if d["source"] == "pin") == report["blocks_protected"]
    assert report["chars_before"] == len(_text_of(before))
    assert report["chars_after"] == len(_text_of(after))
    assert report["tokens_before"] == count_tokens(_text_of(before), "gpt-4.1").value
    assert report["tokens_after"] == count_tokens(_text_of(after), "gpt-4.1").value
    assert report["messages_after"] == len(after)
    for d in counted:
        if d["decision"] == "keep":
            assert d["chars_after"] == d["chars"]
        if d["decision"] == "drop":
            assert d["chars_after"] == 0
    assert report["worth_it"] == (report["reduction_ratio"] >= report["min_reduction"])



def check_degraded_only_for_a_reason(payload: Any, result: Any, mode: str) -> None:
    if not result.report.get("degraded"):
        return
    ids = [r.id for m in parse_transcript(copy.deepcopy(payload)) for r in m.tool_results]
    assert len(ids) != len(set(ids)), (
        f"fail-closed: {mode} fell back to its fail-safe "
        f"({result.report.get('degradation_reason')}) on input without duplicate tool ids"
    )


def check_idempotence(result: Any, mode: str, goal: str) -> None:
    first = messages_to_payload(result.messages)
    second = messages_to_payload(compact(first, mode, goal).messages)
    assert second == first, f"idempotence: a second {mode} pass changed its own output"


def check_verbatim(payload: list[dict[str, Any]], result: Any) -> None:
    # by position, not id: duplicate ids are legal input and must both survive
    originals = {m.message_index: [r.text for r in m.tool_results]
                 for m in parse_transcript(copy.deepcopy(payload))}
    decisions = {d["id"]: d for d in result.decisions if d["source"] != "pin"}
    for message in result.messages:
        for position, res in enumerate(message.tool_results):
            original = originals[message.message_index][position]
            decision = decisions.get(res.id)
            if decision is None or decision["decision"] == "keep" or res.text == original:
                assert res.text == original, f"verbatim: kept result {res.id} changed"
                stray = sorted(set(decision or {}) & {"note", "stash", "kept_at", "recover"})
                assert not stray, f"verbatim: kept result {res.id} still names a pointer {stray}"
            else:
                assert res.text == decision.get("note"), (
                    f"verbatim: result {res.id} is not the pointer its decision names"
                )


def check_recall_round_trip(payload: list[dict[str, Any]], result: Any) -> None:
    originals = {r.id: r.text for m in parse_transcript(copy.deepcopy(payload))
                 for r in m.tool_results}
    for decision in result.decisions:
        if decision["decision"] != "replace" or not decision.get("stash"):
            continue
        pointer_id = decision["note"].rsplit(" ", 1)[-1].rstrip("]")
        try:
            recalled = recall(pointer_id)
        except ValueError as exc:
            raise AssertionError(f"recall round-trip: {decision['id']}: {exc}") from exc
        assert recalled == originals[decision["id"]], (
            f"recall round-trip: {decision['id']} recalls other bytes"
        )
    violations = verify_stashed(copy.deepcopy(payload), messages_to_payload(result.messages))
    assert not violations, f"recall round-trip: verify_stashed: {violations[:3]}"


def check_no_corruption(result: Any) -> None:
    out = messages_to_payload(result.messages)
    text = json.dumps(out, ensure_ascii=False)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AssertionError(f"no corruption: output is not valid UTF-8: {exc}") from exc
    assert json.loads(text) == out, "no corruption: output changes through JSON"


def check_stable_placeholders(payload: Any, result: Any, mode: str, goal: str) -> None:
    previous = os.environ.get("LCC_STASH_DIR")
    with tempfile.TemporaryDirectory(prefix="lcc-inv-") as other:
        os.environ["LCC_STASH_DIR"] = other
        try:
            again = compact(payload, mode, goal)
        finally:
            if previous is None:
                os.environ.pop("LCC_STASH_DIR", None)
            else:
                os.environ["LCC_STASH_DIR"] = previous
    assert messages_to_payload(again.messages) == messages_to_payload(result.messages), (
        f"stable placeholder: {mode} output differs in another stash directory"
    )


def check_transcript(payload: Any, goal: str) -> None:
    """All seven invariants, every product mode. Raises AssertionError naming the one broken."""
    for mode in PRODUCT_MODES:
        try:
            result = compact(payload, mode, goal)
        except Rejected:
            return  # refused the documented way: the same input is refused in every mode
        check_degraded_only_for_a_reason(payload, result, mode)  # 7
        assert_transcript_invariants(payload, result, {"preserve_recent": 6})  # 2 and 6
        check_verbatim(payload, result)
        if mode == "stashed":
            check_recall_round_trip(payload, result)
        check_no_corruption(result)
        check_stable_placeholders(payload, result, mode, goal)
        check_idempotence(result, mode, goal)


def corpus_cases() -> list[Path]:
    return sorted(CORPUS.glob("*.json"))


def load_case(path: Path) -> tuple[Any, str]:
    case = json.loads(path.read_text(encoding="utf-8"))
    return case["payload"], case["goal"]


def corpus_digest() -> str:
    """sha256 over the stashed output of every corpus case (for the hash-seed test)."""
    digest = hashlib.sha256()
    for path in corpus_cases():
        payload, goal = load_case(path)
        try:
            out = messages_to_payload(compact(payload, "stashed", goal).messages)
        except Rejected as exc:
            out = {"rejected": str(exc)}
        digest.update(json.dumps(out, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


if __name__ == "__main__":
    sys.stdout.write(corpus_digest() + "\n")
