"""Metamorphic properties of the rules modes' decisions (``lossy``, ``recoverable``, ``stashed``).

``tests/invariants.py`` checks that the output is well formed; these check that the rules decide
*correctly*: change the input in a way whose effect is known, and the decisions must move
(or not move) accordingly. Each is a hypothesis property over the transcripts of
``test_invariants_fuzz.py`` (unique tool ids; duplicate ids are covered there). Plain pytest runs
a fixed-seed batch; ``LCC_FUZZ_SECONDS`` switches to random seeds and a bigger batch.

1. renaming paths consistently (same length, same shape) changes no decision;
2. inserting an unrelated call away from the end changes no other call's decision, except for a
   call whose age crosses ``STALE_AFTER_MESSAGES`` / ``TRIM_MIN_AGE_MESSAGES`` (the documented
   position thresholds);
3. a Read followed by an Edit of the same file is never "recoverable from disk";
4. naming a file in the goal never removes more than before;
5. a later whole-file Read of X never turns a removal of another call back into a keep.
"""

from __future__ import annotations

import os
import re
from typing import Any

import pytest

pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, assume, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from invariants import Rejected, compact  # noqa: E402
from lcc.relevance.transcript_rules import (  # noqa: E402
    STALE_AFTER_MESSAGES,
    TRIM_MIN_AGE_MESSAGES,
)
from test_invariants_fuzz import PATHS, transcripts  # noqa: E402

MODES = ("lossy", "recoverable", "stashed")
REMOVALS = {"drop", "trim", "replace"}
RECOVERABLE = ("recoverable_file_read", "replace_disk_verified")
TAIL = 6  # preserve_recent: the newest messages are pinned and never change
BUDGET = float(os.environ.get("LCC_FUZZ_SECONDS") or 0)

PROPERTY = settings(
    max_examples=int(max(40, BUDGET * 3)), deadline=None, database=None,
    derandomize=not BUDGET, suppress_health_check=list(HealthCheck),
)
# Long enough (about 60-90 messages) for calls to cross the age thresholds.
LONG = transcripts(dup_ids=False, min_calls=25, max_calls=45)
Payload = list[dict[str, Any]]
Decisions = dict[str, tuple[str, str, int]]


@pytest.fixture(autouse=True)
def _private_stash(tmp_path, monkeypatch):
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))


def decide(payload: Payload, goal: str, mode: str) -> Decisions:
    """call id -> (decision, reason, message index) for every call the mode could change."""
    try:
        result = compact(payload, mode, goal)
    except Rejected:
        assume(False)
    return {d["id"]: (d["decision"], d["reason"], d["message_index"])
            for d in result.decisions if d["source"] != "pin"}


def pair(call_id: str, tool: str, args: dict[str, Any], text: str) -> Payload:
    return [{"role": "assistant", "text": "", "toolUses": [
                {"tool_use_id": call_id, "tool": tool, "input": args}]},
            {"role": "user", "text": "", "toolResults": [{"tool_use_id": call_id, "text": text}]}]


def slots(payload: Payload) -> list[int]:
    """Where a call pair can go: before an assistant message, clear of the pinned tail, with a
    call after it (so the pair is never the latest result)."""
    last_call = max((i for i, m in enumerate(payload) if m.get("toolUses")), default=0)
    return [i for i, m in enumerate(payload)
            if 1 <= i <= min(len(payload) - TAIL - 1, last_call) and m["role"] == "assistant"]


def insert(payload: Payload, at: int, extra: Payload) -> Payload:
    return [*payload[:at], *extra, *payload[at:]]


def rotate(text: str) -> str:
    """Shift ASCII letters by one: same length and shape, another name."""
    return re.sub(r"[A-Za-z]", lambda m: chr((ord(m.group()) - (65 if m.group() < "a" else 97) + 1)
                                              % 26 + (65 if m.group() < "a" else 97)), text)


NAMES = sorted({*PATHS, "/work", *(re.split(r"[/\\]", p)[-1] for p in PATHS)}, key=len, reverse=True)
NAME_RE = re.compile("|".join(map(re.escape, NAMES)))


def _renamed(match: re.Match[str]) -> str:
    stem, dot, ext = match.group().rpartition(".")
    return rotate(stem) + dot + ext if dot else rotate(ext)  # "/work", the workdir, has none


def rename(value: Any) -> Any:
    """Rename every known path, bare file name and the workdir (extension kept), in one pass."""
    if isinstance(value, str):
        return NAME_RE.sub(_renamed, value)
    if isinstance(value, list):
        return [rename(v) for v in value]
    if isinstance(value, dict):
        return {k: rename(v) for k, v in value.items()}
    return value


@PROPERTY
@given(case=LONG, mode=st.sampled_from(MODES))
def test_renaming_paths_changes_no_decision(case: tuple[Payload, str], mode: str) -> None:
    payload, goal = case
    assert decide(rename(payload), rename(goal), mode) == decide(payload, goal, mode)


@PROPERTY
@given(case=LONG, mode=st.sampled_from(MODES), data=st.data())
def test_an_unrelated_call_changes_no_other_decision(
    case: tuple[Payload, str], mode: str, data: st.DataObject
) -> None:
    payload, goal = case
    candidates = slots(payload)
    assume(candidates)
    at = data.draw(st.sampled_from(candidates))
    # `pwd` is read-only (no later write), its output is unique, and it names no file.
    extra = pair("zz-unrelated", "Bash", {"command": "pwd"}, "/zz/unrelated-output")
    before = decide(payload, goal, mode)
    after = decide(insert(payload, at, extra), goal, mode)
    last = len(payload) - 1  # last message index
    for call_id, (decision, reason, index) in before.items():
        # Two messages were inserted: a call before the slot ages by 2 and may cross a threshold.
        old_age = last - index
        crosses = index < at and old_age <= max(STALE_AFTER_MESSAGES, TRIM_MIN_AGE_MESSAGES) \
            < old_age + 2
        # `call_before_latest_error` is positional by design: a call inserted right before the
        # latest error becomes that "call before".
        if crosses or reason == "call_before_latest_error":
            continue
        assert after[call_id][:2] == (decision, reason), (
            f"{mode}: an unrelated call at {at} moved {call_id}: "
            f"{(decision, reason)} -> {after[call_id][:2]}"
        )


@PROPERTY
@given(case=LONG, mode=st.sampled_from(("recoverable", "stashed")),
       path=st.sampled_from([p for p in PATHS if p.startswith("/")]), data=st.data())
def test_a_read_then_an_edit_is_never_recoverable_from_disk(
    case: tuple[Payload, str], mode: str, path: str, data: st.DataObject
) -> None:
    payload, goal = case
    candidates = slots(payload)
    assume(candidates)
    first = data.draw(st.sampled_from(candidates))
    second = data.draw(st.sampled_from([c for c in candidates if c >= first]))
    body = "\n".join(f"line {n} of the file" for n in range(40))
    edited = insert(payload, second, pair("zz-edit", "Edit", {
        "file_path": path, "old_string": "line 3", "new_string": "line three"}, "edited"))
    edited = insert(edited, first, pair("zz-read", "Read", {"file_path": path}, body))
    reason = decide(edited, goal, mode)["zz-read"][1]
    assert not any(tag in reason for tag in RECOVERABLE), (
        f"{mode}: a Read of {path} followed by an Edit of it is {reason}"
    )


def test_a_read_without_an_edit_is_recoverable_in_the_same_setup() -> None:
    """The control for the property above: drop the Edit and the pointer is allowed."""
    path = "/work/src/a.py"
    body = "\n".join(f"line {n} of the file" for n in range(40))
    payload = [{"role": "user", "text": "router"},
               *pair("zz-read", "Read", {"file_path": path}, body),
               *({"role": "user", "text": f"next {i}"} for i in range(TAIL + 1))]
    assert decide(payload, "router", "recoverable")["zz-read"][1] == "recoverable_file_read"


@PROPERTY
@given(case=LONG, mode=st.sampled_from(MODES), named=st.sampled_from(
    [*PATHS, *(re.split(r"[/\\]", p)[-1] for p in PATHS)]))
def test_naming_a_file_in_the_goal_only_protects_more(
    case: tuple[Payload, str], mode: str, named: str
) -> None:
    payload, goal = case
    before = {i for i, (d, _r, _m) in decide(payload, goal, mode).items() if d in REMOVALS}
    after = {i for i, (d, _r, _m) in decide(payload, f"{goal} {named}", mode).items()
             if d in REMOVALS}
    assert after <= before, f"{mode}: naming {named!r} in the goal removed {sorted(after - before)}"


@PROPERTY
@given(case=LONG, mode=st.sampled_from(MODES),
       path=st.sampled_from(PATHS), data=st.data())
def test_a_later_whole_file_read_never_unstashes_anything_else(
    case: tuple[Payload, str], mode: str, path: str, data: st.DataObject
) -> None:
    payload, goal = case
    candidates = slots(payload)
    assume(candidates)
    at = data.draw(st.sampled_from(candidates))
    extra = pair("zz-reread", "Read", {"file_path": path}, "a whole file\n" * 20)
    before = decide(payload, goal, mode)
    after = decide(insert(payload, at, extra), goal, mode)
    for call_id, (decision, reason, _index) in before.items():
        if decision in REMOVALS:
            assert after[call_id][0] != "keep", (
                f"{mode}: a later read of {path} un-removed {call_id} ({reason} -> "
                f"{after[call_id][1]})"
            )
