"""provider="rules", rules_mode="lossless": tool-call compaction whose removals are provable.

The lossy rules (head/tail trims, stale-read drops, superseded drops whose outputs differ)
failed two session-disjoint blind audits (bench v0.4: 21/150 flagged; v0.5: 36/132), and the
LLM judges used to grade them are noisy. This mode removes only what can be checked
mechanically, so no judge is needed:

- A tool result is replaced by a one-line pointer (``[identical output kept at <id>]`` or
  ``[output contained in <id>]``) only when every one of its lines appears, contiguously and
  in order, in a LATER result that is itself kept unchanged and carries the same ``is_error``
  flag. Matching is whole-line: ``ok`` is not found inside ``not ok``.
- The tool call (input), every user/assistant text, every message and every other result
  stay byte for byte. Nothing is trimmed. A pointer never targets a result that was itself
  replaced, so chains resolve to the last kept copy.
- The only normalization: Codex ``exec_command`` header lines that change on every run of
  the same command — ``Chunk ID:``, ``Wall time:``, ``Original token count:`` — are ignored
  when they sit in the leading header block that ends with the ``Output:`` line. ``Process
  exited with code`` is compared (it is the command's result, not metadata), and the same
  words in a body line are compared like any other text.

:func:`verify_lossless` re-checks a compaction from the two payloads alone;
:func:`lcc.relevance.transcript.compact_transcript` runs it on its own output and keeps
everything if it ever reports a violation.
"""

from __future__ import annotations

import re
from typing import Any

_HEADER_RE = re.compile(
    r"^(?:Chunk ID|Wall time|Process exited with code|Process running with session ID"
    r"|Original token count)\b.*$"
)
_VOLATILE_RE = re.compile(r"^(?:Chunk ID|Wall time|Original token count):")


def comparable_lines(text: str) -> list[str]:
    """The lines a pointer must preserve: all of them, minus Codex volatile header lines."""
    lines = text.split("\n")
    end = 0
    while end < len(lines) and _HEADER_RE.match(lines[end]):
        end += 1
    if end < len(lines) and lines[end] == "Output:":
        return [line for line in lines[:end] if not _VOLATILE_RE.match(line)] + lines[end:]
    return lines


def _framed(text: str) -> str:
    """Comparable lines joined and framed by newlines: ``a in b`` is whole-line containment.

    ``split("\n")`` leaves no newline inside a line, so a substring hit that starts and ends
    on a frame newline is a contiguous run of whole lines, in order.
    """
    return "\n" + "\n".join(comparable_lines(text)) + "\n"


def _has_content(message: Any) -> bool:
    return bool(message.text or message.tool_calls or message.tool_results)


def _flat_results(messages: list[Any]) -> list[Any]:
    return [result for message in messages for result in message.tool_results]


def lossless_decisions(messages: list[Any], candidates: list[Any]) -> list[dict[str, Any]]:
    """One decision per candidate call (same order): ``dedupe`` with ``kept_at``, or ``keep``."""
    candidate_ids = {call.result.id for call in candidates if call.result is not None}
    results = _flat_results(messages)
    # ponytail: O(results^2) substring scans; index outputs by line hash if transcripts grow.
    framed = [_framed(result.text) for result in results]
    kept = [True] * len(results)
    found: dict[str, tuple[str, str, str]] = {}

    for index in range(len(results) - 1, -1, -1):
        result = results[index]
        if result.id not in candidate_ids or framed[index] == "\n\n":
            continue
        for later in range(index + 1, len(results)):
            other = results[later]
            if not kept[later] or other.is_error != result.is_error:
                continue
            if framed[index] not in framed[later]:
                continue
            if framed[index] == framed[later]:
                note = f"[identical output kept at {other.id}]"
                reason = "identical_output_kept_later"
            else:
                note = f"[output contained in {other.id}]"
                reason = "output_contained_in_later"
            if len(note) < len(result.text):
                kept[index] = False
                found[result.id] = (other.id, note, reason)
            break

    decisions: list[dict[str, Any]] = []
    for call in candidates:
        base = {
            "id": call.id,
            "score": None,
            "keep_call": None,
            "keep_result": None,
            "source": "rules",
            "message_index": call.message_index,
            "tool": call.tool,
        }
        hit = found.get(call.result.id) if call.result is not None else None
        if hit is None:
            decisions.append(base | {"decision": "keep", "reason": "no_lossless_superseder"})
        else:
            kept_at, note, reason = hit
            decisions.append(
                base | {"decision": "dedupe", "reason": reason, "kept_at": kept_at, "note": note}
            )
    return decisions


def verify_lossless(original_payload: Any, compacted_payload: Any) -> list[str]:
    """Violations of the lossless contract between two transcript payloads; ``[]`` is a pass.

    Every message, role, text, tool call (id, tool, input) and result id/``is_error`` must be
    unchanged, and every result whose text changed must have all its comparable lines, in
    order, inside a later result that did not change.
    """
    from lcc.relevance.transcript import parse_transcript

    # A message with no text, call or result carries nothing; dropping it loses nothing.
    before = [m for m in parse_transcript(original_payload) if _has_content(m)]
    after = [m for m in parse_transcript(compacted_payload) if _has_content(m)]
    if len(before) != len(after):
        return [f"message count changed: {len(before)} -> {len(after)}"]

    violations: list[str] = []
    for old, new in zip(before, after, strict=True):
        where = f"message {old.message_index}"
        if old.role != new.role:
            violations.append(f"{where}: role changed")
        if old.text != new.text:
            violations.append(f"{where}: text changed")
        if [(c.id, c.tool, c.input) for c in old.tool_calls] != [
            (c.id, c.tool, c.input) for c in new.tool_calls
        ]:
            violations.append(f"{where}: tool calls changed")
        if [(r.id, r.is_error) for r in old.tool_results] != [
            (r.id, r.is_error) for r in new.tool_results
        ]:
            violations.append(f"{where}: tool result ids or error flags changed")
    if violations:
        return violations

    old_results = _flat_results(before)
    new_results = _flat_results(after)
    unchanged = [o.text == n.text for o, n in zip(old_results, new_results, strict=True)]
    framed = [_framed(result.text) for result in new_results]
    for index, (old_result, same) in enumerate(zip(old_results, unchanged, strict=True)):
        if same:
            continue
        needed = _framed(old_result.text)
        if not any(
            unchanged[later]
            and new_results[later].is_error == old_result.is_error
            and needed in framed[later]
            for later in range(index + 1, len(new_results))
        ):
            violations.append(
                f"result {old_result.id} changed and its text is not in any later unchanged result"
            )
    return violations
