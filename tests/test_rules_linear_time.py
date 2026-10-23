"""Each rules pass is linear in input size (nightly only: ``LCC_TIMING=1``).

PR #103 fixed a quadratic regex that no output invariant could see. This doubles a fixed hostile
shape and requires at most ``LIMIT`` times the time (best of ``REPEATS`` runs, so a noisy
machine does not fail it). The shapes are the ones that hurt before or can: one long run of
word characters with no separator in a result, in the goal and in a command, and a long
transcript with many calls on the same files.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import pytest

from invariants import PRODUCT_MODES, compact

pytestmark = pytest.mark.skipif(
    not os.environ.get("LCC_TIMING"), reason="timing property: nightly only (LCC_TIMING=1)"
)

LIMIT = 2.5
REPEATS = 3
MODES = ("lossy", *PRODUCT_MODES[1:])
Shape = Callable[[int], tuple[list[dict[str, Any]], str]]


@pytest.fixture(autouse=True)
def _private_stash(tmp_path, monkeypatch):
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))


def _call(n: int, tool: str, args: dict[str, Any], text: str) -> list[dict[str, Any]]:
    return [{"role": "assistant", "text": "", "toolUses": [
                {"tool_use_id": f"c{n}", "tool": tool, "input": args}]},
            {"role": "user", "text": "", "toolResults": [{"tool_use_id": f"c{n}", "text": text}]}]


def _tail() -> list[dict[str, Any]]:
    return [{"role": "user", "text": f"next {i}"} for i in range(7)]


def run_in_result(size: int) -> tuple[list[dict[str, Any]], str]:
    return [{"role": "user", "text": "fix the parser"},
            *_call(0, "Bash", {"command": "cat dump"}, "a1" * (size // 2)), *_tail()], "parser"


def run_in_goal(size: int) -> tuple[list[dict[str, Any]], str]:
    return [{"role": "user", "text": "fix"}, *_call(0, "Read", {"file_path": "/w/a.py"}, "x\n" * 99),
            *_tail()], "a-" * (size // 2)


def run_in_command(size: int) -> tuple[list[dict[str, Any]], str]:
    return [{"role": "user", "text": "fix"},
            *_call(0, "Bash", {"command": "echo " + "a/" * (size // 2)}, "ok\n" * 99),
            *_tail()], "parser"


def many_calls(size: int) -> tuple[list[dict[str, Any]], str]:
    n = size // 100  # 100 chars of transcript per call
    messages = [{"role": "user", "text": "fix a.py"}]
    for i in range(n):
        path = f"/w/src/m{i % 9}.py"
        tool, args = [("Read", {"file_path": path}), ("Edit", {"file_path": path}),
                      ("Bash", {"command": f"grep -rn m{i % 9} src"})][i % 3]
        messages += _call(i, tool, args, f"line {i}\n" * 12)
    return [*messages, *_tail()], "a.py"


SHAPES = {"result": (run_in_result, 20_000), "goal": (run_in_goal, 20_000),
          "command": (run_in_command, 20_000), "calls": (many_calls, 80_000)}


def best_of(payload: list[dict[str, Any]], goal: str, mode: str) -> float:
    times = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        compact(payload, mode, goal)
        times.append(time.perf_counter() - started)
    return min(times)


@pytest.mark.parametrize("shape, mode", [(shape, mode) for shape in SHAPES for mode in MODES])
def test_doubling_the_input_at_most_doubles_the_time(shape: str, mode: str) -> None:
    build, size = SHAPES[shape]
    small, large = best_of(*build(size), mode), best_of(*build(size * 2), mode)
    assert large <= LIMIT * max(small, 0.005), (
        f"{mode} on '{shape}': {size} -> {size * 2} took {small:.3f}s -> {large:.3f}s "
        f"({large / small:.1f}x, limit {LIMIT}x)"
    )
