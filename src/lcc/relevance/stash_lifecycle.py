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
import time
from collections import Counter
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
DEFAULT_ROOTS = (Path.home() / ".claude" / "projects",)
DEFAULT_OLDER_THAN = "30d"


def parse_age(spec: str) -> float:
    """``"30d"``, ``"12h"``, ``"90m"`` or bare days, in seconds."""
    match = _AGE.match(spec.strip())
    if match is None:
        raise StashError(f"--older-than must look like 30d, 12h or 90m, got {spec!r}")
    unit = {"": 86400, "d": 86400, "h": 3600, "m": 60}[match.group(2)]
    return int(match.group(1)) * unit


def referenced_ids(roots: list[Path]) -> Counter[str]:
    """``sha12 -> number of files`` naming it under ``roots``. Raises on anything unreadable.

    ponytail: reads each file whole; stream in chunks if transcripts outgrow memory.
    """
    existing = [root for root in roots if root.exists()]
    if not existing:
        raise StashError(
            f"none of the transcript roots exist ({', '.join(map(str, roots))}); "
            "pass --root where your transcripts live. Nothing was deleted."
        )

    def fail(exc: OSError) -> None:
        raise exc

    counts: Counter[str] = Counter()
    for root in existing:
        files = (
            [root] if root.is_file()
            else (Path(d) / f for d, _, names in os.walk(root, onerror=fail) for f in names)
        )
        for path in files:
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise StashError(
                    f"cannot read {path} ({exc.strerror or exc}); gc deletes nothing while a "
                    "transcript is unreadable"
                ) from None
            counts.update({m.group(1).decode() for m in _REF.finditer(data)})
    return counts


def _blobs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if _FULL.match(p.name)) if root.is_dir() else []


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
        if p.name.startswith(".tmp-")
        or (p.name.endswith(".json") and _FULL.match(p.name[:-5]) and p.name[:-5] not in names)
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
