"""Stash lifecycle: ``lcc stash ls``, ``lcc stash gc`` and ``lcc stash verify``.

The transcripts are the only source of truth for what is still referenced: gc scans every file
under the given roots for ``recall <sha12>`` and never trusts the sidecars for that. A blob is
removed only when no scanned file names it **and** it was neither put nor recalled within the
age threshold. gc fails closed: a missing root or an unreadable file aborts it before anything
is deleted, and it deletes nothing without ``apply=True``.

Concurrency: ``put`` refreshes a blob's mtime under a shared lock before any pointer to it
exists; gc re-checks each candidate's age under the exclusive lock, right before ``unlink``.
A pointer written after the scan therefore names a blob too young to delete.
"""

from __future__ import annotations

import os
import re
import stat
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from lcc.relevance.transcript_stash import (
    _FULL,
    StashError,
    StashMissing,
    _blob,
    _is_windows,
    read_sidecar,
    sidecar_path,
    stash_dir,
    stash_lock,
)

# Matches the pointer in plain text and inside JSON strings alike ("lcc recall" is ASCII).
_REF = re.compile(rb"recall ([0-9a-f]{12})")
_AGE = re.compile(r"^(\d+)([dhm]?)$")
# What ``tempfile.mkstemp(prefix=".tmp-")`` names: 8 chars of its alphabet, no suffix.
_TMP = re.compile(r"^\.tmp-[a-z0-9_]{8}$")
DEFAULT_ROOTS = (Path.home() / ".claude" / "projects", Path.home() / ".codex" / "sessions")
DEFAULT_OLDER_THAN = "30d"
MIN_AGE = 3600  # a younger threshold races a compaction whose pointer is not on disk yet


def parse_age(spec: str) -> float:
    """``"30d"``, ``"12h"``, ``"90m"`` or bare days, in seconds."""
    match = _AGE.match(spec.strip())
    if match is None:
        raise StashError(f"--older-than must look like 30d, 12h or 90m, got {spec!r}")
    unit = {"": 86400, "d": 86400, "h": 3600, "m": 60}[match.group(2)]
    return _floor(int(match.group(1)) * unit)


def _floor(seconds: float) -> float:
    if seconds < MIN_AGE:
        raise StashError("--older-than must be at least 1h")
    return seconds


def resolve_roots(explicit: list[Path] | None) -> list[Path]:
    """``explicit`` as given (each must then exist), or the default roots that exist."""
    if explicit:
        return list(explicit)
    return [root for root in DEFAULT_ROOTS if root.exists()] or list(DEFAULT_ROOTS)


def _is_plain_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _files(root: Path) -> Iterator[Path]:
    """Regular files under ``root``, following directory symlinks once each (no loops).

    FIFOs, sockets and devices are skipped (reading one blocks or means nothing); so are
    dangling symlinks, which cannot hold a pointer. An unlistable directory raises.
    """
    if not root.is_dir():
        yield root
        return

    def fail(exc: OSError) -> None:
        raise exc

    seen: set[tuple[int, int]] = set()
    for here, dirs, names in os.walk(root, onerror=fail, followlinks=True):
        info = os.stat(here)
        if (info.st_dev, info.st_ino) in seen:
            dirs[:] = []
            continue
        seen.add((info.st_dev, info.st_ino))
        for name in names:
            yield Path(here) / name


def referenced_ids(roots: list[Path]) -> Counter[str]:
    """``sha12 -> number of files`` naming it under ``roots``. Raises on anything unreadable
    and on a root that does not exist: a mistyped ``--root`` must not unprotect its blobs.

    ponytail: reads each file whole; stream in chunks if transcripts outgrow memory.
    """
    if not roots:
        raise StashError("no transcript roots to scan; pass --root. Nothing was deleted.")
    for root in roots:
        if not root.exists():
            raise StashError(
                f"transcript root {root} does not exist; fix or drop that --root. "
                "Nothing was deleted."
            )

    counts: Counter[str] = Counter()
    for root in roots:
        try:
            for path in _files(root):
                try:
                    info = path.stat()
                except FileNotFoundError:
                    if path.is_symlink():
                        continue  # dangling
                    raise
                if not stat.S_ISREG(info.st_mode):
                    continue
                data = path.read_bytes()
                counts.update({m.group(1).decode() for m in _REF.finditer(data)})
        except OSError as exc:
            raise StashError(
                f"cannot read {exc.filename or root} ({exc.strerror or exc}); gc deletes "
                "nothing while a transcript is unreadable"
            ) from None
    return counts


def _blobs(root: Path) -> list[Path]:
    """Blob files; a directory or symlink named like one is not lcc's and is left alone."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if _FULL.match(p.name) and _is_plain_file(p))


def last_used(blob: Path) -> float:
    """Latest put (the blob's mtime) or recall (the sidecar), in epoch seconds."""
    recalled = read_sidecar(blob).get("last_recalled_at")
    return max(blob.stat().st_mtime, recalled if isinstance(recalled, (int, float)) else 0.0)


def ls(roots: list[Path] | None) -> list[dict[str, Any]]:
    """One row per blob; ``refs`` is ``None`` when ``roots`` is ``None``."""
    refs = referenced_ids(roots) if roots is not None else None
    rows = []
    for blob in _blobs(stash_dir()):
        data = blob.read_bytes()
        meta = read_sidecar(blob)
        rows.append({
            "id": blob.name[:12],
            "bytes": len(data),
            "lines": len(data.decode("utf-8", "replace").splitlines()),
            "created_at": meta.get("created_at", blob.stat().st_mtime),
            "last_recalled_at": meta.get("last_recalled_at"),
            "sessions": len(meta.get("sessions", [])),
            "refs": refs[blob.name[:12]] if refs is not None else None,
        })
    return rows


def gc(
    roots: list[Path], older_than: float, *, apply: bool = False, now: float | None = None
) -> dict[str, Any]:
    """Unreferenced blobs unused for ``older_than`` seconds; removed only with ``apply``."""
    _floor(older_than)
    if apply and _is_windows():
        raise StashError("lcc stash gc --apply needs POSIX file locks; nothing was deleted")
    refs = referenced_ids(roots)  # before the lock: may be slow, and may raise
    root = stash_dir()
    blobs = _blobs(root)

    def expired(path: Path) -> bool:
        try:
            used = last_used(path) if _FULL.match(path.name) else path.stat().st_mtime
        except FileNotFoundError:
            return False
        return (now if now is not None else time.time()) - used >= older_than

    unreferenced = [b for b in blobs if b.name[:12] not in refs]
    names = {b.name for b in blobs}
    # Leftovers of a crashed put (.tmp-*) or a removed blob (<sha>.json) can hold a secret too.
    leftovers = [
        p for p in (root.iterdir() if root.is_dir() else [])
        if _is_plain_file(p)
        and (
            _TMP.match(p.name)
            or (p.name.endswith(".json") and _FULL.match(p.name[:-5]) and p.name[:-5] not in names)
        )
    ]
    report: dict[str, Any] = {
        "blobs": len(blobs),
        "referenced": len(blobs) - len(unreferenced),
        "candidates": [b.name for b in unreferenced if expired(b)],
        "leftovers": [p.name for p in leftovers if expired(p)],
        "removed": [],
        "applied": apply,
    }
    if not apply or not root.is_dir():
        return report
    with stash_lock(root, exclusive=True):
        for blob in unreferenced:
            # Re-checked under the lock: a put since the scan made it young again.
            if blob.name[:12] in refs or not expired(blob):
                continue
            blob.unlink(missing_ok=True)
            sidecar_path(blob).unlink(missing_ok=True)
            report["removed"].append(blob.name)
        for path in leftovers:
            if expired(path):
                path.unlink(missing_ok=True)
    return report


def verify(session: Path) -> list[dict[str, str]]:
    """Every pointer in ``session`` whose blob is missing, ambiguous or fails its hash."""
    try:
        data = session.read_bytes()
    except OSError as exc:
        raise StashError(f"cannot read {session}: {exc.strerror or exc}") from None
    problems = []
    for stash_id in dict.fromkeys(m.group(1).decode() for m in _REF.finditer(data)):
        try:
            _blob(stash_id)
        except StashMissing:
            problems.append({"id": stash_id, "problem": "missing"})
        except StashError as exc:
            problem = "ambiguous" if "ambiguous" in str(exc) else "hash_mismatch"
            problems.append({"id": stash_id, "problem": problem})
    return problems
