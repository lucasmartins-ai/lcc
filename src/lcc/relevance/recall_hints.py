"""Recall hints: when a new prompt names a stashed output, say which ``lcc recall`` id holds it.

The LongHealth v1 pilot measured where stashing loses: the model rarely recalls on its own
(stashed lost 0.40 of accuracy where the answer had been stashed). This module is the
deterministic nudge. It matches the prompt's terms against the stashed outputs of this
session and, when one output clearly fits, returns one line naming its id. No model, no
embeddings, no network: the same prompt and stash give the same hints on every machine.

Candidates come from two places, so the same code serves every agent tool:

- ``refs_in(text)``: every ``lcc recall <id>`` pointer in a transcript, whatever its format;
- ``session_blobs(session_id)``: blobs whose sidecar names this session (the plugin passes
  its session id on every stash), which works even when the transcript on disk lags.

Scoring is lexical. Prompt terms carry a weight (identifiers, paths and numbers 3,
capitalised names and long words 2, other words 1; stop words and words under 4 characters
none), divided by how many candidates contain the term. A hint needs a score of at least
``MIN_SCORE`` with at least one term of weight 2 or more, and must beat the best candidate it
leaves out by ``GAP`` (so a prompt that fits three outputs equally gets no hint). At most
``MAX_HINTS`` per prompt, and an id hinted ``MUTE_AFTER`` times in a session is muted there.

Speed: this runs on every prompt. The session's index (:func:`read_index`) spares reading every
sidecar in the stash, and each blob's terms are tokenised once and kept in ``<sha256>.terms``.
Both are caches: when one is missing, damaged or from another tokeniser the slow path runs, and
the hints are the same either way.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from bisect import bisect_left
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from lcc.relevance.transcript_stash import (
    StashError,
    _blob,
    _opening,
    _stash_names,
    _write_private,
    append_index,
    read_index,
    read_sidecar,
    session_hash,
    stash_dir,
    stash_lock,
    terms_path,
)

MIN_SCORE = Fraction(3)
GAP = Fraction(3, 2)
MAX_HINTS = 2
MUTE_AFTER = 2
OPENING = 80
TERM = 40  # the longest matched term a hint line repeats; keeps the line far under 10,000 chars
# Every candidate blob is still read and hash-checked on each prompt (a corrupt one never
# hints); the caps bound that. Tokenising is what the terms cache saves.
MAX_BLOBS = 300
MAX_BYTES = 8_000_000
# Bump when _tokens or the casefolding changes: cached term sets from before then are ignored.
TERMS_VERSION = 1

_REF = re.compile(r"lcc recall ([0-9a-f]{12})(?![0-9a-f])")
_TOKEN = re.compile(r"\w[\w./:-]*")
_PARTS = re.compile(r"[/:]+")
_CAMEL = re.compile(r"[a-z][A-Z]")
_STOP = frozenset(
    [
        "what",
        "that",
        "this",
        "with",
        "from",
        "have",
        "were",
        "when",
        "where",
        "which",
        "there",
        "their",
        "about",
        "would",
        "could",
        "should",
        "please",
        "does",
        "into",
        "then",
        "than",
        "them",
        "they",
        "your",
        "been",
        "also",
        "just",
        "like",
        "some",
        "only",
        "over",
        "after",
        "before",
        "because",
        "while",
        "these",
        "those",
        "here",
        "make",
        "need",
        "want",
        "para",
        "como",
        "isso",
        "esse",
        "essa",
        "este",
        "esta",
        "porque",
        "quando",
        "onde",
        "qual",
        "quais",
        "mais",
        "fazer",
        "agora",
        "ainda",
        "sobre",
        "pelo",
        "pela",
        "entre",
        "depois",
        "antes",
        "também",
        "tambem",
        "então",
        "entao",
        "você",
        "voce",
        "pode",
        "deve",
        "tudo",
        "cada",
        "muito",
        "precisa",
        "preciso",
    ]
)


@dataclass(frozen=True)
class Hint:
    id: str
    score: float
    terms: tuple[str, ...]
    opening: str


def refs_in(text: str) -> list[str]:
    """Stash ids named by ``lcc recall <id>`` in ``text``, each once, most recent first."""
    last: dict[str, int] = {}
    for match in _REF.finditer(text):
        last[match.group(1)] = match.start()
    return sorted(last, key=last.__getitem__, reverse=True)


def _tokens(text: str) -> Iterator[str]:
    """Words and identifiers. A path or test id is also split at ``/`` and ``:``, so
    ``tests/test_api.py::test_refund_77`` matches a prompt that names ``test_refund_77``."""
    for match in _TOKEN.finditer(text):
        token = match.group(0).rstrip("./:-")
        if not token:
            continue
        yield token
        if "/" in token or ":" in token:
            for part in _PARTS.split(token):
                part = part.strip(".-")
                if part and part != token:
                    yield part


def terms(prompt: str) -> dict[str, int]:
    """The prompt's matchable terms, casefolded, with their weight (3, 2 or 1)."""
    weights: dict[str, int] = {}
    for index, token in enumerate(_tokens(prompt)):
        key = token.casefold()
        if (
            any(ch.isdigit() for ch in token)
            or any(ch in "_./:-" for ch in token)
            or _CAMEL.search(token)
        ):
            weight = 3 if len(token) >= 3 else 0
        elif len(token) < 4 or key in _STOP:
            weight = 0
        elif (token[0].isupper() and index > 0) or len(token) >= 8:
            weight = 2
        else:
            weight = 1
        if weight > weights.get(key, 0):
            weights[key] = weight
    return weights


def _unique(ids: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for stash_id in ids:
        seen.setdefault(stash_id, None)
    return list(seen)


def find_hints(
    prompt: str,
    ids: Iterable[str],
    *,
    muted: Iterable[str] = (),
    max_hints: int = MAX_HINTS,
) -> list[Hint]:
    """The stashed outputs among ``ids`` that ``prompt`` clearly names, best first."""
    weights = terms(prompt)
    if not weights:
        return []
    skip = set(muted)
    names = _stash_names()
    root = stash_dir()
    matched: dict[str, set[str]] = {}
    openings: dict[str, bytes] = {}
    fresh: dict[Path, list[str]] = {}
    budget = MAX_BYTES
    for stash_id in _unique(ids)[:MAX_BLOBS]:
        if stash_id in skip:
            continue
        # The blob _blob would read: exactly one stash name with this prefix (12-64 hex chars).
        at = bisect_left(names, stash_id)
        hits = names[at : at + 2]
        if (
            not hits
            or not hits[0].startswith(stash_id)
            or (len(hits) > 1 and hits[1].startswith(stash_id))
        ):
            continue  # missing or ambiguous: recall would fail too
        try:
            size = (root / hits[0]).stat().st_size
        except OSError:
            continue
        if size > budget:
            continue  # checked before reading: one huge log must not stall the prompt
        try:
            name, data = _blob(stash_id, names)
        except StashError:
            continue  # gone, corrupt or ambiguous: recall would fail too
        budget -= len(data)
        every = _cached_terms(root / name)
        if every is None:
            every = sorted({t.casefold() for t in _tokens(data.decode("utf-8", errors="replace"))})
            fresh[root / name] = every
        if len(weights) < len(every):  # from the smaller side: a pasted log can be the prompt
            found = {key for key in weights if _has(every, key)}
        else:
            found = {term for term in every if term in weights}
        if found:
            matched[stash_id] = found
            openings[stash_id] = data
    _store_terms(root, fresh)
    df: dict[str, int] = {}
    for found in matched.values():
        for key in found:
            df[key] = df.get(key, 0) + 1
    # Exact sums: a float total in set order could land either side of MIN_SCORE.
    scores = {
        stash_id: sum((Fraction(weights[key], df[key]) for key in found), Fraction(0))
        for stash_id, found in matched.items()
    }
    order = sorted(scores, key=lambda stash_id: (-scores[stash_id], stash_id))

    def eligible(stash_id: str) -> bool:
        found = matched[stash_id]
        return scores[stash_id] >= MIN_SCORE and max(weights[key] for key in found) >= 2

    # The largest prefix of the ranking in which every hint is eligible and the weakest one
    # shown still beats the best one left out (every candidate counts) by GAP.
    shown = 0
    for k in range(min(max_hints, len(order)), 0, -1):
        left_out = scores[order[k]] if k < len(order) else Fraction(0)
        if all(eligible(s) for s in order[:k]) and scores[order[k - 1]] >= GAP * left_out:
            shown = k
            break
    return [
        Hint(
            stash_id,
            round(float(scores[stash_id]), 4),
            tuple(sorted(matched[stash_id], key=lambda key: (-weights[key], key))),
            _snippet(openings[stash_id].decode("utf-8", errors="replace")),
        )
        for stash_id in order[:shown]
    ]


def _has(sorted_terms: list[str], key: str) -> bool:
    at = bisect_left(sorted_terms, key)
    return at < len(sorted_terms) and sorted_terms[at] == key


def _terms_head(blob: Path, body: bytes) -> bytes:
    # The Unicode version decides what \w and casefold mean, so a Python upgrade re-tokenises.
    # The blob's name keeps another blob's list, copied over this one, from passing.
    digest = hashlib.sha256(body).hexdigest()
    return f"lcc-terms {TERMS_VERSION} {unicodedata.unidata_version} {blob.name} {digest}".encode()


def _cached_terms(blob: Path) -> list[str] | None:
    """The blob's sorted casefolded terms from its cache, or ``None`` when absent, damaged (the
    body fails its hash), another blob's, or written by another tokeniser. Terms never hold a
    newline."""
    try:
        raw = terms_path(blob).read_bytes()
    except OSError:
        return None
    head, _, body = raw.partition(b"\n")
    if head != _terms_head(blob, body):
        return None
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:  # a planted file with a matching hash; _store_terms writes UTF-8
        return None
    return text.split("\n") if text else []


def _store_terms(root: Path, fresh: dict[Path, list[str]]) -> None:
    """Best effort, like the sidecars. Under the shared lock and only while the blob is there:
    gc (exclusive lock) removes a blob with its terms, so none outlives it."""
    if not fresh:
        return
    with contextlib.suppress(OSError), stash_lock(root):
        for blob, every in fresh.items():
            if blob.is_file():
                body = "\n".join(every).encode("utf-8")
                _write_private(terms_path(blob), _terms_head(blob, body) + b"\n" + body)


def _snippet(text: str) -> str:
    opening = _opening(iter(text.splitlines()))
    return opening if len(opening) <= OPENING else opening[:OPENING].rstrip() + "…"


def hint_line(hint: Hint) -> str:
    """One line for the agent: why, what it is, and the call that brings it back."""
    named = ", ".join(t if len(t) <= TERM else t[: TERM - 1] + "…" for t in hint.terms[:3])
    return (
        f'lcc hint: your prompt names a stashed output ({named}): "{hint.opening}"'
        f" · lcc recall {hint.id}"
    )


def session_blobs(session_id: str | None) -> list[str]:
    """Stash ids whose sidecar names ``session_id``, newest first.

    Only the sidecars of the blobs in the session's index are read. Without an index that vouches
    for itself every sidecar in the stash is, and the result is appended to the index as a full
    scan, so a session that never stashed scans once, not on every prompt.
    """
    key = session_hash(session_id)
    if not key:
        return []
    root = stash_dir()
    indexed = read_index(root, key)
    if indexed is None:
        rows = _scan_and_index(root, key)
    else:
        # lexists: the scan lists any entry with a blob's name, as _stash_names does.
        rows = _session_rows(root, key, [n for n in set(indexed) if os.path.lexists(root / n)])
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [name[:12] for _, name in rows]


def _scan_and_index(root: Path, key: str) -> list[tuple[float, str]]:
    """Every sidecar, then the session's blobs appended to its index as a full scan. Under the
    exclusive lock no put sits between its index record (or dropping the index) and its sidecar,
    which the scan would miss. Without that lock, or with a sidecar that is there but cannot be
    read (it may name the session), the scan still answers but does not vouch."""
    try:
        with stash_lock(root, exclusive=True) as locked:
            try:
                rows = _session_rows(root, key, _stash_names(), strict=True)
            except OSError:
                locked = False
                rows = _session_rows(root, key, _stash_names())
            if locked:
                with contextlib.suppress(OSError):
                    append_index(root, key, [name for _, name in rows], full=True)
            return rows
    except StashError:  # no stash yet, or it cannot be locked
        return _session_rows(root, key, _stash_names())


def _session_rows(
    root: Path, key: str, names: Iterable[str], *, strict: bool = False
) -> list[tuple[float, str]]:
    rows: list[tuple[float, str]] = []
    for name in names:
        meta = read_sidecar(root / name, strict=strict)
        if key in meta.get("sessions", []):
            when = meta.get("last_put_at") or meta.get("created_at") or 0.0
            rows.append((float(when), name))
    return rows


def _state_path(key: str) -> Path:
    return stash_dir().parent / "hints" / f"{key}.json"


def _load(key: str) -> dict[str, int]:
    try:
        data = json.loads(_state_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    shown = data.get("hinted") if isinstance(data, dict) else None
    return {k: v for k, v in shown.items() if isinstance(v, int)} if isinstance(shown, dict) else {}


def _save(key: str, hinted: dict[str, int]) -> None:
    """Counts per id only, never prompt text; best effort, like the stash sidecars."""
    path = _state_path(key)
    with contextlib.suppress(OSError):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "hinted": hinted}, f, sort_keys=True)
        os.replace(tmp, path)


def hints_for(
    prompt: str,
    *,
    transcript: str | None,
    session_id: str | None,
    max_hints: int = MAX_HINTS,
) -> list[Hint]:
    """Hints for ``prompt`` from the transcript's pointers and the session's stash.

    With a session id, each hint is counted and an id hinted ``MUTE_AFTER`` times is muted for
    that session (shown and not recalled twice is noise). Without one nothing is remembered.
    """
    ids = _unique([*refs_in(transcript or ""), *session_blobs(session_id)])
    key = session_hash(session_id)
    hinted = _load(key) if key else {}
    muted = {stash_id for stash_id, count in hinted.items() if count >= MUTE_AFTER}
    found = find_hints(prompt, ids, muted=muted, max_hints=max_hints)
    if key and found:
        for hint in found:
            hinted[hint.id] = hinted.get(hint.id, 0) + 1
        _save(key, hinted)
    return found
