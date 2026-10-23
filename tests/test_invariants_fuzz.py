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
import re
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
# Relative, absolute (the only ones the recoverable pointers accept), Windows and spaced paths.
PATHS = ["jobs/tenant_import.py", "docs/TOOL_CALLS.md", "src/a.py", "src/relatório.py",
         "C:\\repo\\win.py", "dir with spaces/x.md", "/work/src/a.py", "/work/docs/notes.md",
         "/work/pkg/mod.py"]
POINTER = "[removed: 12 lines, 1.3 KB · lcc recall 0123456789ab]"
SUMMARY = ("This session is being continued from a previous conversation that ran out of "
           "context. Summary:\n")
CODEX_HEADER = ("Chunk ID: {n}f3a\nWall time: 0.{n} seconds\nProcess exited with code {code}\n"
                "Original token count: {n}\nOutput:\n")
PATCH = "*** Begin Patch\n*** Update File: {path}\n@@\n-old\n+new\n*** End Patch\n"


@pytest.fixture(autouse=True)
def _private_stash(tmp_path, monkeypatch):
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))


def _run(char: str, count: int) -> str:
    return char * count


# One long run of word characters with no separator: the regression class of PR #103.
word_run = st.builds(_run, st.sampled_from("a1.-~/_"), st.sampled_from([2000, 8000, 20000]))
text_piece = st.one_of(
    st.sampled_from(FRAGMENTS),
    st.sampled_from(GOAL_WORDS),
    st.sampled_from(PATHS),
    st.just(POINTER),
    st.text(st.characters(blacklist_categories=("Cs",)), max_size=40),
)


@st.composite
def output(draw: Any, previous: list[str]) -> str:
    if previous and draw(st.integers(0, 4)) == 0:
        return draw(st.sampled_from(previous))  # an identical rerun or re-read
    if draw(st.integers(0, 12)) == 0:  # a hex dump / minified log: one long slashless run
        return draw(word_run)
    body = "".join(draw(st.lists(text_piece, max_size=12)))
    return body * draw(st.sampled_from([1, 1, 3, 40]))  # sometimes big enough to stash


def _numbered(body: str, offset: int) -> str:
    """The ``Read`` tool's ``N<tab>line`` output, starting at line ``offset``."""
    return "\n".join(f"{offset + i:>6}\t{line}" for i, line in enumerate(body.split("\n")))


@st.composite
def calls(draw: Any, previous: list[str]) -> tuple[str, dict[str, Any], str]:
    """One tool call as (tool, input, result text): Claude Code and Codex shapes."""
    path = draw(st.sampled_from(PATHS))
    text = draw(output(previous))
    kind = draw(st.sampled_from(
        ["read", "read", "read_range", "bash", "grep", "edit", "write", "multiedit",
         "exec", "stdin", "patch", "exec_patch", "run_command"]))
    code = draw(st.sampled_from([0, 0, 0, 1]))
    if kind == "read":
        return "Read", {"file_path": path}, text
    if kind == "read_range":
        offset, limit = draw(st.integers(1, 40)), draw(st.integers(1, 60))
        return "Read", {"file_path": path, "offset": offset, "limit": limit}, _numbered(text, offset)
    if kind == "bash":
        return "Bash", {"command": draw(st.sampled_from(
            ["ls", "pytest -q", "git diff", "git status", f"cat {path}"]))}, text
    if kind == "grep":
        return "Grep", {"pattern": draw(st.sampled_from(WORDS)), "path": path}, text
    if kind == "edit":
        return "Edit", {"file_path": path, "old_string": "a", "new_string": "b"}, "edited"
    if kind == "write":
        return "Write", {"file_path": path, "content": text[:200]}, "written"
    if kind == "multiedit":
        edits = [{"old_string": "a", "new_string": "b"}] * draw(st.integers(1, 3))
        return "MultiEdit", {"file_path": path, "edits": edits}, "edited"
    if kind == "exec":  # Codex exec_command: cmd + workdir, header lines on the result
        header = CODEX_HEADER.format(n=draw(st.integers(1, 9)), code=code)
        cmd = draw(st.sampled_from(["ls", "cat src/a.py", "git diff", "pytest -q", f"cat {path}"]))
        return "exec_command", {"cmd": cmd, "workdir": "/work"}, header + text
    if kind == "stdin":
        return "write_stdin", {"session_id": draw(st.integers(1, 3)), "chars": ""}, text
    if kind == "patch":  # Codex apply_patch: the body is the input
        return "apply_patch", {"input": PATCH.format(path=path)}, "Patch applied"
    if kind == "exec_patch":  # ... or sent through the shell
        body = PATCH.format(path=path)
        return "exec_command", {"cmd": f"apply_patch <<'EOF'\n{body}EOF", "workdir": "/work"}, "ok"
    return "mcp__srv__get_thing", {"query": path}, text


@st.composite
def transcripts(draw: Any, dup_ids: bool = True, min_calls: int = 0, max_calls: int = 24) -> tuple[list[dict[str, Any]], str]:
    """A transcript in the hook shape: parallel calls, split results, compaction boundaries.

    ``dup_ids=False`` gives every call its own id (the metamorphic tests need that);
    ``min_calls``/``max_calls`` above ~20 reach the age thresholds (``STALE_AFTER_MESSAGES``).
    """
    pieces = draw(st.lists(st.sampled_from(GOAL_WORDS), min_size=1, max_size=8))
    if draw(st.integers(0, 2)) == 0:  # name a file, by path or by bare name, in the goal
        named = draw(st.sampled_from(PATHS))
        pieces.append(draw(st.sampled_from([named, re.split(r"[/\\]", named)[-1]])))
    if draw(st.integers(0, 15)) == 0:
        pieces.append(draw(word_run))
    goal = " ".join(pieces)
    messages: list[dict[str, Any]] = [{"role": "user", "text": goal}]
    outputs: list[str] = []
    ids = draw(st.lists(st.sampled_from(["a", "b", "c", "d", "e", "f", "g", "h"]),
                        min_size=min_calls, max_size=max_calls))
    n = 0
    position = 0
    while position < len(ids):
        width = min(draw(st.sampled_from([1, 1, 1, 2, 3])), len(ids) - position)  # parallel calls
        uses, results = [], []
        for cid in ids[position:position + width]:
            tool, args, text = draw(calls(outputs))
            outputs.append(text)
            n += 1
            call_id = cid if dup_ids and draw(st.integers(0, 9)) == 0 else f"{cid}{n}"
            uses.append({"tool_use_id": call_id, "tool": tool, "input": args})
            result: dict[str, Any] = {"tool_use_id": call_id, "text": text}
            if draw(st.integers(0, 7)) == 0:
                result["is_error"] = True
            results.append(result)
        position += width
        messages.append({"role": "assistant", "text": "", "toolUses": uses})
        if draw(st.booleans()):  # all results in one message, or one message per result
            messages.append({"role": "user", "text": "", "toolResults": results})
        else:
            messages.extend({"role": "user", "text": "", "toolResults": [r]} for r in results)
        if draw(st.integers(0, 5)) == 0:
            messages.append({"role": "user", "text": draw(text_piece)})
        if draw(st.integers(0, 25)) == 0:  # a compaction boundary: summary, sometimes a marker
            if draw(st.booleans()):
                messages.append({"role": "system", "text": "Conversation compacted"})
            messages.append({"role": "user", "text": SUMMARY + draw(text_piece)})
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
                    {"note": f"fuzz seed {batch_seed}: {(str(exc).splitlines() or [repr(exc)])[0]}",
                     "goal": goal, "payload": payload}, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
            raise AssertionError(f"LCC_FUZZ_SEED={batch_seed} reproduces: {exc}") from exc
        if fixed or time.monotonic() - started >= budget:
            break
    sys.stderr.write(f"fuzz: {len(seeds)} batch(es) of {BATCH}, seeds {seeds[:5]}...\n")
