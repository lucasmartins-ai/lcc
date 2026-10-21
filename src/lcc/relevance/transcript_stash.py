"""provider="rules", rules_mode="stashed": remove old outputs, keep their exact bytes recallable.

``recoverable`` only removes what a re-read of an unchanged file gives back; on real sessions
that is little. This mode stores the removed bytes at removal time instead: the result's UTF-8
text goes to a local content-addressed store (``<stash>/<sha256>``, dir 0700, files 0600;
``LCC_STASH_DIR`` overrides ``~/.cache/lcc/stash``) and is replaced by
``[removed: N tokens · lcc recall <sha12>]``. :func:`recall` (``lcc recall``, MCP ``recall``)
re-hashes on read, so what comes back is provably what was removed.

Eligible: every result ``lossy`` would drop or trim, plus every result ``recoverable`` replaces;
lossless dedupes win where they apply. Everything else is kept verbatim, as in those modes:
pinned turns, the latest error and the call before it, calls named in the goal, duplicate ids.
Calls, inputs and texts never change; a stashed result is replaced whole, never cut.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from lcc.relevance.transcript_lossless import duplicate_ids, lossless_decisions, verify_lossless
from lcc.relevance.transcript_recoverable import recoverable_decisions
from lcc.relevance.transcript_rules import rules_decisions
from lcc.token_budget import count_tokens

ENV_DIR = "LCC_STASH_DIR"
_ID = re.compile(r"^[0-9a-f]{12,64}$")
_FULL = re.compile(r"^[0-9a-f]{64}$")
_NOTE = re.compile(r"^\[removed: (\d+) tokens · lcc recall ([0-9a-f]{12})\]$")


class StashError(ValueError):
    """A recall that cannot return verified bytes (bad id, missing blob, hash mismatch)."""


def stash_dir() -> Path:
    return Path(os.environ.get(ENV_DIR) or Path.home() / ".cache" / "lcc" / "stash")


def put(text: str) -> str:
    """Store ``text``'s UTF-8 bytes; return their sha256. Idempotent; atomic per blob."""
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    root = stash_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    target = root / digest
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        return digest
    fd, tmp = tempfile.mkstemp(dir=root, prefix=".tmp-")  # mkstemp creates 0600
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return digest


def _blob(stash_id: str) -> tuple[str, bytes]:
    if not _ID.match(stash_id):
        raise StashError(f"not a stash id: {stash_id!r} (12-64 lowercase hex chars)")
    root = stash_dir()
    matches = (
        sorted(p for p in root.glob(f"{stash_id}*") if _FULL.match(p.name)) if root.is_dir() else []
    )
    if not matches:
        raise StashError(f"stash id {stash_id} not found in {root}")
    if len(matches) > 1:
        raise StashError(f"stash id {stash_id} is ambiguous; pass more of the sha256")
    data = matches[0].read_bytes()
    if hashlib.sha256(data).hexdigest() != matches[0].name:
        raise StashError(f"stash blob {matches[0].name} fails its hash check; not returned")
    return matches[0].name, data


def recall(stash_id: str, lines: tuple[int, int] | None = None) -> str:
    """The verified text behind ``stash_id``; ``lines`` is 1-based and inclusive."""
    text = _blob(stash_id)[1].decode("utf-8")
    if lines is None:
        return text
    first, last = lines
    rows = text.splitlines(keepends=True)
    if first < 1 or last < first or first > len(rows):
        raise StashError(f"line range {first}-{last} outside 1-{len(rows)}")
    return "".join(rows[first - 1 : last])


def recall_sha256(stash_id: str) -> str:
    return _blob(stash_id)[0]


def parse_lines(spec: str) -> tuple[int, int]:
    """``"a-b"`` (or ``"a"``) to a 1-based inclusive range."""
    first, _, last = spec.partition("-")
    try:
        return int(first), int(last or first)
    except ValueError:
        raise StashError(f"--lines must look like a-b, got {spec!r}") from None


def stash_note(tokens: int, digest: str) -> str:
    return f"[removed: {tokens} tokens · lcc recall {digest[:12]}]"


def _too_short_to_stash(text: str, model: str) -> bool:
    return len(stash_note(count_tokens(text, model).value, "0" * 12)) >= len(text)


def stashed_decisions(
    messages: list[Any],
    candidates: list[Any],
    goal: str,
    *,
    model: str,
    root: str | None = None,
    disk_check: bool = True,
) -> list[dict[str, Any]]:
    """One decision per candidate: ``replace`` (``note`` + ``stash``), ``dedupe`` or ``keep``.

    Writes each replaced result to the stash as a side effect, before the pointer exists.
    """
    lossy = rules_decisions(messages, candidates, goal)
    recoverable = recoverable_decisions(
        messages, candidates, goal, root=root, disk_check=disk_check
    )
    duplicated = duplicate_ids(messages)
    eligible: dict[int, str] = {}
    for index, (call, lo, rec) in enumerate(zip(candidates, lossy, recoverable, strict=True)):
        if call.id in duplicated:
            continue
        if rec["decision"] == "replace":
            eligible[index] = rec["reason"]
        elif lo["decision"] in ("drop", "trim"):
            eligible[index] = lo["reason"]
    # A result too short for its pointer stays whole; leave it to lossless dedupe now, or the
    # next pass (where it is no longer eligible) dedupes it and the output is not a fixed point.
    eligible = {
        i: reason for i, reason in eligible.items()
        if not _too_short_to_stash(candidates[i].result.text, model)
    }
    unavailable = {candidates[i].result.id for i in eligible}
    lossless = lossless_decisions(messages, candidates, unavailable=unavailable)

    decisions: list[dict[str, Any]] = []
    for index, (call, base) in enumerate(zip(candidates, lossless, strict=True)):
        if base["decision"] == "dedupe" or call.id in duplicated:
            decisions.append(base)
            continue
        text = call.result.text
        if _NOTE.match(text):
            # Already a stash pointer (an earlier pass): stashing it again would replace the
            # pointer with a pointer to the pointer, rewrite early history for ~0 tokens and
            # invalidate a prompt cache from there. Placeholders are fixed points (I2).
            decisions.append(base | {"reason": "already_stashed"})
            continue
        if index not in eligible:
            decisions.append(base | {"reason": "not_stash_eligible"})
            continue
        tokens = count_tokens(text, model).value
        try:
            digest = put(text)
        except (OSError, UnicodeEncodeError) as exc:
            decisions.append(base | {"reason": f"stash_write_failed:{type(exc).__name__}"})
            continue
        decisions.append(
            base
            | {
                "decision": "replace",
                "reason": f"stashed:{eligible[index]}",
                "note": stash_note(tokens, digest),
                "stash": {"sha256": digest, "tokens": tokens, "bytes": len(text.encode("utf-8"))},
            }
        )
    return decisions


def _stash_holds(old: Any, note: str) -> bool:
    match = _NOTE.match(note)
    if match is None:
        return False
    try:
        digest, data = _blob(match.group(2))
    except StashError:
        return False
    return data == old.text.encode("utf-8", "surrogatepass") and digest.startswith(match.group(2))


def verify_stashed(original_payload: Any, compacted_payload: Any) -> list[str]:
    """Violations of the stashed contract; ``[]`` is a pass.

    Everything :func:`verify_lossless` checks, and every other changed result must be a stash
    pointer whose blob is present, passes its hash and holds the original text exactly.
    """
    from lcc.relevance.transcript import parse_transcript

    duplicated = duplicate_ids(parse_transcript(original_payload))
    return verify_lossless(
        original_payload,
        compacted_payload,
        allow=lambda old, note: old.id not in duplicated and _stash_holds(old, note),
    )
