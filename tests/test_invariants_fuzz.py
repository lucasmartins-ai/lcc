"""Time-budgeted property/fuzz test of the seven invariants (``tests/invariants.py``).

Budget: ``LCC_FUZZ_SECONDS`` (PR CI 60, nightly 600). Unset, one fixed-seed batch runs, so a
plain ``pytest`` stays fast and deterministic. Each batch logs its seed; ``LCC_FUZZ_SEED``
replays one. A failing input is shrunk by hypothesis and, when ``LCC_FUZZ_ARTIFACTS`` is set,
written there as JSON (synthetic data only: everything is generated here). To keep a failure
forever, copy that file into ``tests/corpus/adversarial/`` with a one-line ``note``; the corpus
replay is ``test_invariants_corpus.py``.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("hypothesis")  # a dev dependency; the corpus replay runs without it

from hypothesis import HealthCheck, given, seed, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from edge_corpus import FRAGMENTS, PT_WORDS, WORDS  # noqa: E402
from invariants import check_transcript  # noqa: E402

BATCH = 25
GOAL_WORDS = WORDS + PT_WORDS
PATHS = ["jobs/tenant_import.py", "docs/TOOL_CALLS.md", "src/a.py", "src/relatório.py",
         "C:\\repo\\win.py", "dir with spaces/x.md"]
POINTER = "[removed: 12 tokens · lcc recall 0123456789ab]"


@pytest.fixture(autouse=True)
def _private_stash(tmp_path, monkeypatch):
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))


text_piece = st.one_of(
    st.sampled_from(FRAGMENTS),
    st.sampled_from(GOAL_WORDS),
    st.just(POINTER),
    st.text(st.characters(blacklist_categories=("Cs",)), max_size=40),
)


@st.composite
def output(draw: Any, previous: list[str]) -> str:
    if previous and draw(st.integers(0, 4)) == 0:
        return draw(st.sampled_from(previous))  # an identical rerun or re-read
    body = "".join(draw(st.lists(text_piece, max_size=12)))
    return body * draw(st.sampled_from([1, 1, 3, 40]))  # sometimes big enough to stash


@st.composite
def transcripts(draw: Any) -> tuple[list[dict[str, Any]], str]:
    goal = " ".join(draw(st.lists(st.sampled_from(GOAL_WORDS), min_size=1, max_size=8)))
    messages: list[dict[str, Any]] = [{"role": "user", "text": goal}]
    outputs: list[str] = []
    ids = draw(st.lists(st.sampled_from(["a", "b", "c", "d", "e", "f", "g", "h"]),
                        min_size=0, max_size=24))
    for n, cid in enumerate(ids):
        tool = draw(st.sampled_from(["Read", "Bash", "Grep", "Edit", "Write"]))
        args: dict[str, Any] = (
            {"file_path": draw(st.sampled_from(PATHS))} if tool in ("Read", "Edit", "Write")
            else {"command": draw(st.sampled_from(["ls", "pytest -q", "git diff", "cat x"]))}
        )
        text = draw(output(outputs))
        outputs.append(text)
        call_id = cid if draw(st.integers(0, 9)) == 0 else f"{cid}{n}"  # some duplicate ids
        messages.append({"role": "assistant", "text": "",
                         "toolUses": [{"tool_use_id": call_id, "tool": tool, "input": args}]})
        result: dict[str, Any] = {"tool_use_id": call_id, "text": text}
        if draw(st.integers(0, 7)) == 0:
            result["is_error"] = True
        messages.append({"role": "user", "text": "", "toolResults": [result]})
        if draw(st.integers(0, 5)) == 0:
            messages.append({"role": "user", "text": draw(text_piece)})
    messages.append({"role": "user", "text": draw(st.sampled_from(GOAL_WORDS))})
    return messages, goal


def _artifacts() -> Path | None:
    target = os.environ.get("LCC_FUZZ_ARTIFACTS")
    if not target:
        return None
    path = Path(target)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _batch(batch_seed: int, failing: list[Any]) -> None:
    @seed(batch_seed)
    @settings(max_examples=BATCH, deadline=None, database=None, derandomize=False,
              suppress_health_check=list(HealthCheck))
    @given(transcripts())
    def run(case: tuple[list[dict[str, Any]], str]) -> None:
        payload, goal = case
        try:
            check_transcript(payload, goal)
        except Exception:
            failing[:] = [case]  # hypothesis shrinks: the last failure is the smallest
            raise

    run()


def test_invariants_hold_on_generated_transcripts() -> None:
    budget = float(os.environ.get("LCC_FUZZ_SECONDS") or 0)
    fixed = os.environ.get("LCC_FUZZ_SEED")
    artifacts = _artifacts()
    started = time.monotonic()
    seeds: list[int] = []
    while True:
        batch_seed = int(fixed) if fixed else (
            random.SystemRandom().randrange(2**32) if budget else 0)
        seeds.append(batch_seed)
        if artifacts:
            (artifacts / "seeds.txt").write_text("\n".join(map(str, seeds)) + "\n")
        failing: list[Any] = []
        try:
            _batch(batch_seed, failing)
        except Exception as exc:  # any error is a finding; report the seed either way
            if artifacts and failing:
                payload, goal = failing[0]
                (artifacts / f"failing-{batch_seed}.json").write_text(json.dumps(
                    {"note": f"fuzz seed {batch_seed}: {str(exc).splitlines()[0]}",
                     "goal": goal, "payload": payload}, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
            raise AssertionError(f"LCC_FUZZ_SEED={batch_seed} reproduces: {exc}") from exc
        if fixed or time.monotonic() - started >= budget:
            break
    sys.stderr.write(f"fuzz: {len(seeds)} batch(es) of {BATCH}, seeds {seeds[:5]}...\n")
