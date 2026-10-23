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

Eligible: every result ``lossy`` would drop or trim, plus every result ``recoverable`` replaces;
lossless dedupes win where they apply. Everything else is kept verbatim, as in those modes:
pinned turns, the latest error and the call before it, calls named in the goal, duplicate ids.
Calls, inputs and texts never change; a stashed result is replaced whole, never cut.

Lifecycle (:mod:`lcc.relevance.stash_lifecycle`): each blob has a ``<sha256>.json`` sidecar
with timestamps and truncated session-id hashes, never content. ``put`` and ``recall`` hold a
shared ``flock`` on ``<stash>/.lock`` and ``lcc stash gc --apply`` an exclusive one, so a blob
``put`` refreshes while gc runs is never deleted under it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import time
import warnings
from bisect import bisect_left
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from lcc.relevance.transcript_lossless import duplicate_ids, lossless_decisions, verify_lossless
from lcc.relevance.transcript_recoverable import recoverable_decisions
from lcc.relevance.transcript_rules import rules_decisions
from lcc.token_budget import count_tokens

ENV_DIR = "LCC_STASH_DIR"
_ID = re.compile(r"^[0-9a-f]{12,64}$")
_FULL = re.compile(r"^[0-9a-f]{64}$")
# Also accepts the earlier "N tokens" form: pointers already in a transcript stay fixed points.
_NOTE = re.compile(
    r"^\[removed: (?:\d+ tokens|\d+ lines?, \d+(?:\.\d)? K?B) · lcc recall (?P<id>[0-9a-f]{12})\]$"
)


class StashError(ValueError):
    """A recall that cannot return verified bytes (bad id, missing blob, hash mismatch)."""


class StashMissing(StashError):
    """No blob for the id: the stash was cleared, gc'd, or this is another machine."""


# The pointer is gone for good once its blob is: say what the user can still do.
RECOVERY_HINT = (
    "The removed output is not in this machine's stash (cache cleared, `lcc stash gc`, or the "
    "session was resumed elsewhere) and lcc cannot rebuild it: re-read the file or re-run the "
    "command that produced it."
)


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


@contextlib.contextmanager
def stash_lock(root: Path, *, exclusive: bool = False) -> Iterator[bool]:
    """``flock`` on ``<root>/.lock`` (0600): shared for put/recall, exclusive for gc.

    Yields whether the lock is held. A shared lock that cannot be taken (``ENOTSUP`` on some
    network filesystems, a read-only stash) yields ``False`` so put and recall keep working;
    an exclusive one raises :class:`StashError`, so gc deletes nothing unlocked. Windows has no
    flock: yields ``False`` (``lcc stash gc --apply`` refuses to run there).
    """
    if _is_windows():
        yield False
        return
    import fcntl

    try:
        fd = os.open(root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        if exclusive:
            raise StashError(f"cannot open the stash lock ({exc}); nothing was deleted") from None
        yield False
        return
    try:
        with contextlib.suppress(OSError):
            os.fchmod(fd, 0o600)  # a .lock left by an older umask
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        except OSError as exc:
            if exclusive:
                raise StashError(f"cannot lock the stash ({exc}); nothing was deleted") from None
            yield False
            return
        yield True
    finally:
        os.close(fd)  # closing releases the lock


def _write_private(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")  # mkstemp creates 0600 on POSIX
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def sidecar_path(blob: Path) -> Path:
    return blob.with_name(blob.name + ".json")


def read_sidecar(blob: Path) -> dict[str, Any]:
    """Provenance for ``blob``; ``{}`` when absent or unreadable (it is advisory only)."""
    try:
        meta = json.loads(sidecar_path(blob).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _touch_sidecar(blob: Path, **fields: Any) -> None:
    """Merge ``fields`` into the sidecar. Counts and times only, never content or paths.

    ponytail: read-modify-write under a shared lock, so two concurrent puts of one blob can
    lose a session hash; gc never trusts the sidecar for references, only for display.
    """
    meta = read_sidecar(blob)
    now = time.time()
    meta.setdefault("created_at", now)
    session = fields.pop("session", None)
    if session:
        meta["sessions"] = sorted({*meta.get("sessions", []), session})
    meta.update({key: now for key, on in fields.items() if on})
    # Provenance is best effort; the blob and the pointer are what recall needs.
    with contextlib.suppress(OSError):
        _write_private(sidecar_path(blob), json.dumps(meta, sort_keys=True).encode("utf-8"))


def session_hash(session_id: Any) -> str | None:
    """Truncated SHA-256 of a session id, as the ledger stores it."""
    from lcc.receipt import session_key

    return session_key(session_id)


def put(text: str, *, session: str | None = None) -> str:
    """Store ``text``'s UTF-8 bytes; return their sha256. Idempotent; atomic per blob.

    ``session`` (a raw session id) is stored only as :func:`session_hash`. A blob that already
    exists gets its mtime refreshed: gc measures age from it, so a pointer written right after
    this call is never older than the blob it names.
    """
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    root = stash_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # On Windows os.chmod only toggles the read-only bit; owner-only modes are a POSIX claim.
    if not _is_windows():
        os.chmod(root, 0o700)
    target = root / digest
    with stash_lock(root) as locked:
        if not locked and not _is_windows():
            warnings.warn(
                f"lcc stash: writing {digest[:12]} without the stash lock (flock unavailable); "
                "`lcc stash gc --apply` refuses to run on this stash",
                RuntimeWarning,
                stacklevel=2,
            )
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            os.utime(target)
        else:
            _write_private(target, data)
        _touch_sidecar(target, session=session_hash(session), last_put_at=True)
    return digest


def _stash_names() -> list[str]:
    """Sorted blob names now in the stash: one listing for a batch of ``_blob`` lookups."""
    root = stash_dir()
    return sorted(p.name for p in root.iterdir() if _FULL.match(p.name)) if root.is_dir() else []


def _blob(stash_id: str, names: list[str] | None = None) -> tuple[str, bytes]:
    """The blob ``stash_id`` names. ``names`` (from ``_stash_names``) spares the directory scan
    per lookup; a prefix it does not hold falls back to the scan, so a blob written since the
    listing is still found."""
    if not _ID.match(stash_id):
        raise StashError(f"not a stash id: {stash_id!r} (12-64 lowercase hex chars)")
    root = stash_dir()
    matches: list[Path] = []
    if names:
        at = bisect_left(names, stash_id)
        while at < len(names) and names[at].startswith(stash_id):
            matches.append(root / names[at])
            at += 1
    if not matches:
        matches = (
            sorted(p for p in root.glob(f"{stash_id}*") if _FULL.match(p.name))
            if root.is_dir() else []
        )
    if not matches:
        raise StashMissing(f"stash id {stash_id} not found in {root}. {RECOVERY_HINT}")
    if len(matches) > 1:
        raise StashError(f"stash id {stash_id} is ambiguous; pass more of the sha256")
    try:
        data = matches[0].read_bytes()
    except FileNotFoundError:  # removed between glob and read
        raise StashMissing(f"stash id {stash_id} not found in {root}. {RECOVERY_HINT}") from None
    if hashlib.sha256(data).hexdigest() != matches[0].name:
        raise StashError(
            f"stash blob {matches[0].name} fails its hash check; not returned. {RECOVERY_HINT}"
        )
    return matches[0].name, data


def recall(stash_id: str, lines: tuple[int, int] | None = None) -> str:
    """The verified text behind ``stash_id``; ``lines`` is 1-based and inclusive."""
    name, data = _blob(stash_id)
    root = stash_dir()
    # Bookkeeping only: a read-only or unlockable stash must still answer.
    with contextlib.suppress(OSError), stash_lock(root):
        if (root / name).is_file():
            _touch_sidecar(root / name, last_recalled_at=True)
    text = data.decode("utf-8")
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


def _too_short_to_stash(text: str) -> bool:
    return len(stash_note(text, "0" * 12)) >= len(text)


def stashed_decisions(
    messages: list[Any],
    candidates: list[Any],
    goal: str,
    *,
    model: str,
    root: str | None = None,
    disk_check: bool = True,
    session: str | None = None,
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
        if not _too_short_to_stash(candidates[i].result.text)
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
            digest = put(text, session=session)
        except (OSError, UnicodeEncodeError) as exc:
            decisions.append(base | {"reason": f"stash_write_failed:{type(exc).__name__}"})
            continue
        decisions.append(
            base
            | {
                "decision": "replace",
                "reason": f"stashed:{eligible[index]}",
                "note": stash_note(text, digest),
                "stash": {"sha256": digest, "tokens": tokens, "bytes": len(text.encode("utf-8"))},
            }
        )
    return decisions


def _stash_holds(old: Any, note: str, names: list[str] | None = None) -> bool:
    match = _NOTE.match(note)
    if match is None:
        return False
    try:
        digest, data = _blob(match.group("id"), names)
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
    names: list[str] = []  # listed once, on the first pointer: one scan for the whole check

    def allow(old: Any, note: str) -> bool:
        if old.id in duplicated:
            return False
        if not names:
            names.extend(_stash_names())
        return _stash_holds(old, note, names)

    return verify_lossless(original_payload, compacted_payload, allow=allow)
