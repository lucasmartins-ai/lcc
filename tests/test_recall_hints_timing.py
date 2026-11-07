"""Recall hints stay bounded per prompt (nightly only: ``LCC_TIMING=1``).

``lcc hint`` runs on every prompt. ``find_hints`` reads at most ``MAX_BLOBS`` blobs and
``MAX_BYTES`` bytes, so a session with four times as many stashed outputs must take at most
``LIMIT`` times as long (best of ``REPEATS`` runs), and a prompt at the caps must finish within
``CEILING_S``. The ceiling only catches a gross regression; the 50 ms goal in the research notes
is not asserted here.
"""

from __future__ import annotations

import os
import random
import time
from pathlib import Path

import pytest

from lcc.relevance import recall_hints as rh
from lcc.relevance.transcript_stash import put

pytestmark = pytest.mark.skipif(
    not os.environ.get("LCC_TIMING"), reason="timing property: nightly only (LCC_TIMING=1)"
)

LIMIT = 2.5
REPEATS = 3
CEILING_S = 2.0
BLOB_BYTES = rh.MAX_BYTES // rh.MAX_BLOBS - 1_000  # MAX_BLOBS of them fit the byte budget
WORDS = [f"word{i}" for i in range(5_000)] + [f"src/mod{i}/file_{i}.py" for i in range(500)]
PROMPT = "Why does src/mod42/file_42.py fail after word123 and word4567 in the retry path?"


@pytest.fixture(autouse=True)
def _private_stash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))


def _stash_session(session: str, blobs: int, rng: random.Random) -> None:
    for n in range(blobs):
        lines: list[str] = []
        size = 0
        while size < BLOB_BYTES:
            line = " ".join(rng.choice(WORDS) for _ in range(12)) + f" {session}-{n}"
            lines.append(line)
            size += len(line) + 1
        put("\n".join(lines), session=session)


def _best(session: str) -> float:
    times = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        rh.hints_for(PROMPT, transcript=None, session_id=session)
        times.append(time.perf_counter() - start)
    return min(times)


def test_hint_cost_stays_bounded_by_the_caps() -> None:
    rng = random.Random(83)
    _stash_session("at-cap", rh.MAX_BLOBS, rng)
    _stash_session("four-times", 4 * rh.MAX_BLOBS, rng)
    at_cap = _best("at-cap")
    assert at_cap < CEILING_S, f"{at_cap:.2f}s for one prompt at the caps"
    four_times = _best("four-times")
    assert four_times <= LIMIT * at_cap, (
        f"4x the stashed outputs took {four_times / at_cap:.2f}x as long "
        f"({four_times:.3f}s vs {at_cap:.3f}s)"
    )
