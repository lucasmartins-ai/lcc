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
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
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
    read_sidecar,
    session_hash,
    stash_dir,
)

MIN_SCORE = Fraction(3)
GAP = Fraction(3, 2)
MAX_HINTS = 2
MUTE_AFTER = 2
OPENING = 80
TERM = 40  # the longest matched term a hint line repeats; keeps the line far under 10,000 chars
# ponytail: every candidate blob is read and tokenised on each prompt; the caps bound that to
# a few hundred ms on a large session. Cache each blob's term set in its sidecar if it is not.
MAX_BLOBS = 300
MAX_BYTES = 8_000_000

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
    openings: dict[str, str] = {}
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
            _, data = _blob(stash_id, names)
        except StashError:
            continue  # gone, corrupt or ambiguous: recall would fail too
        budget -= len(data)
        text = data.decode("utf-8", errors="replace")
        found = {key for key in (t.casefold() for t in _tokens(text)) if key in weights}
        if found:
            matched[stash_id] = found
            openings[stash_id] = text
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
            _snippet(openings[stash_id]),
        )
        for stash_id in order[:shown]
    ]


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
    """Stash ids whose sidecar names ``session_id``, newest first."""
    key = session_hash(session_id)
    if not key:
        return []
    root = stash_dir()
    rows: list[tuple[float, str]] = []
    for name in _stash_names():
        meta = read_sidecar(root / name)
        if key in meta.get("sessions", []):
            when = meta.get("last_put_at") or meta.get("created_at") or 0.0
            rows.append((float(when), name[:12]))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [stash_id for _, stash_id in rows]


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
