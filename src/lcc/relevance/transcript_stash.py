"""provider="rules", rules_mode="stashed": remove old outputs, keep their exact bytes recallable.

``recoverable`` only removes what a re-read of an unchanged file gives back; on real sessions
that is little. This mode stores the removed bytes at removal time instead: the result's UTF-8
text goes to a local content-addressed store (``<stash>/<sha256>``; on POSIX dir 0700 and
files 0600; on Windows ``%LOCALAPPDATA%\\lcc\\stash`` with no chmod dependency;
``LCC_STASH_DIR`` overrides both defaults) and is replaced by
``[removed: N lines, S KB · lcc recall <sha12>]`` (lines as ``recall --lines`` counts them, S the
UTF-8 size; neither depends on a tokenizer, so one output gives one placeholder on every machine).
:func:`recall` (``lcc recall``, MCP ``recall``)
re-hashes on read, so what comes back is provably what was removed.

``pointer="lean"`` (opt-in, ``--stash-pointer lean``) adds what the inline call does not say:
``[removed: N lines, S KB · exit X · <error type or failing test> · "<first line>" · lcc recall
<sha12>]``. Every field comes from the stashed bytes alone, so the note is still one fixed point
per output. The id stays last, so both forms parse the same way.

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

from lcc.relevance.transcript_lossless import (
    _HEADER_RE,
    duplicate_ids,
    lossless_decisions,
    verify_lossless,
)
from lcc.relevance.transcript_recoverable import recoverable_decisions
from lcc.relevance.transcript_rules import rules_decisions
from lcc.token_budget import count_tokens

ENV_DIR = "LCC_STASH_DIR"
_ID = re.compile(r"^[0-9a-f]{12,64}$")
_FULL = re.compile(r"^[0-9a-f]{64}$")
# Also accepts the earlier "N tokens" form and the lean fields: pointers already in a transcript
# stay fixed points whichever form wrote them.
_NOTE = re.compile(
    r"^\[removed: (?:\d+ tokens|\d+ lines?, \d+(?:\.\d)? K?B)(?: · [^\n]*)?"
    r" · lcc recall (?P<id>[0-9a-f]{12})\]$"
)
POINTERS = ("plain", "lean")
_EXIT = re.compile(r"^(?:Process exited with code|Exit code:?|exit code:?)\s*(-?\d+)\b")
_ERROR_TYPE = re.compile(r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception)\b")
_FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (\S+::\S+)", re.M)
_LEAN_FIRST = 60
_LEAN_ID = 60


class StashError(ValueError):
    """A recall that cannot return verified bytes (bad id, missing blob, hash mismatch)."""


def _is_windows() -> bool:
    return os.name == "nt"


def stash_dir() -> Path:
    """Default stash root; ``LCC_STASH_DIR`` always wins when set.

    POSIX: ``~/.cache/lcc/stash``. Windows: ``%LOCALAPPDATA%/lcc/stash`` (falls back to
    ``~/AppData/Local/lcc/stash`` when ``LOCALAPPDATA`` is unset).
    """
    override = os.environ.get(ENV_DIR)
    if override:
        return Path(override)
    if _is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "lcc" / "stash"
    return Path.home() / ".cache" / "lcc" / "stash"


def put(text: str) -> str:
    """Store ``text``'s UTF-8 bytes; return their sha256. Idempotent; atomic per blob."""
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    root = stash_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # On Windows os.chmod only toggles the read-only bit; owner-only modes are a POSIX claim.
    if not _is_windows():
        os.chmod(root, 0o700)
    target = root / digest
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        return digest
    fd, tmp = tempfile.mkstemp(dir=root, prefix=".tmp-")  # mkstemp creates 0600 on POSIX
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


def _size(nbytes: int) -> str:
    return f"{nbytes} B" if nbytes < 1024 else f"{nbytes / 1024:.1f} KB"


def stash_note(text: str, digest: str) -> str:
    """The placeholder for ``text``: line and byte counts, never a tokenizer's."""
    count = len(text.splitlines())
    unit = "line" if count == 1 else "lines"
    size = _size(len(text.encode("utf-8")))
    return f"[removed: {count} {unit}, {size} · lcc recall {digest[:12]}]"


def _lean_fields(text: str) -> list[str]:
    """Exit status, up to two identifiers and the first line, by fixed rules over ``text``."""
    lines = text.splitlines()
    fields: list[str] = []
    # Codex prints the status in its header, Claude Code's Bash at the end: look only there,
    # never mid-log where a test might print "exit code" itself.
    for line in lines[:4] + lines[-3:]:
        match = _EXIT.match(line.strip())
        if match:
            fields.append(f"exit {match.group(1)}")
            break
    found: list[str] = []
    for value in [*_FAILED_TEST.findall(text), *_ERROR_TYPE.findall(text)]:
        value = value[:_LEAN_ID]
        if value not in found:
            found.append(value)
        if len(found) == 2:
            break
    if found:
        fields.append(", ".join(found))
    # The first line of the output itself: Codex's header lines say nothing the fields above don't.
    body = (line.strip() for line in lines if not _HEADER_RE.match(line) and line != "Output:")
    first = next((line for line in body if line), "")
    first = "".join(ch for ch in first if ch.isprintable())  # no escapes, no control bytes
    if first:
        cut = len(first) > _LEAN_FIRST
        fields.append('"' + first[:_LEAN_FIRST] + ("…" if cut else "") + '"')
    return fields


def stash_note_lean(text: str, digest: str) -> str:
    """:func:`stash_note` plus exit status, identifiers and the first line (``pointer="lean"``)."""
    base = stash_note(text, digest)
    head, _, tail = base.rpartition(" · lcc recall ")
    return " · ".join([head, *_lean_fields(text)]) + " · lcc recall " + tail


def _note(text: str, digest: str, pointer: str) -> str:
    return stash_note_lean(text, digest) if pointer == "lean" else stash_note(text, digest)


def _too_short_to_stash(text: str, pointer: str = "plain") -> bool:
    return len(_note(text, "0" * 12, pointer)) >= len(text)


def stashed_decisions(
    messages: list[Any],
    candidates: list[Any],
    goal: str,
    *,
    model: str,
    root: str | None = None,
    disk_check: bool = True,
    pointer: str = "plain",
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
        i: reason
        for i, reason in eligible.items()
        if not _too_short_to_stash(candidates[i].result.text, pointer)
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
                "note": _note(text, digest, pointer),
                "stash": {"sha256": digest, "tokens": tokens, "bytes": len(text.encode("utf-8"))},
            }
        )
    return decisions


def _stash_holds(old: Any, note: str) -> bool:
    match = _NOTE.match(note)
    if match is None:
        return False
    try:
        digest, data = _blob(match.group("id"))
    except StashError:
        return False
    stash_id = match.group("id")
    return data == old.text.encode("utf-8", "surrogatepass") and digest.startswith(stash_id)


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
