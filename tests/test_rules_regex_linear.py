"""The reference patterns in ``transcript_rules`` must be linear on long runs of path characters.

A pasted hex dump or a minified log is one run of ``[\\w.~-]`` with no slash; a pattern that
retries from every position inside it takes seconds per 10k chars and stalls the hook.
"""

from __future__ import annotations

import time

import pytest

from lcc.relevance.transcript_rules import ERROR_RE, REF_RES, _refs

N = 200_000
HOSTILE = {
    "word": "a" * N,
    "digits": "1" * N,
    "mixed": "aA1" * (N // 3),
    "dots": "a." * (N // 2),
    "dashes": "a-" * (N // 2),
    "tilde": "~" * N,
    "dot-digit": "1." * (N // 2),
}


@pytest.mark.parametrize("name", HOSTILE)
def test_refs_and_error_scan_are_linear(name: str) -> None:
    text = HOSTILE[name]
    started = time.perf_counter()
    _refs(text)
    ERROR_RE.search(text)
    assert time.perf_counter() - started < 0.5, f"quadratic on {name!r}"


@pytest.mark.parametrize(
    ("text", "refs"),
    [
        ("see src/lcc/a.py and ./b/c.md", ["src/lcc/a.py", "./b/c.md", "a.py", "c.md"]),
        ("~/notes/x.txt, ../up/y", ["~/notes/x.txt", "../up/y"]),
        ("go to https://x.io/a/b now", ["https://x.io/a/b", "/x.io/a/b"]),
        ("edit my-module.test.ts", ["test.ts"]),
        ("flag -a.py", ["a.py"]),
        ("--x-y.py", ["x-y.py"]),
        ("a/b", ["a/b"]),
    ],
)
def test_refs_on_normal_input(text: str, refs: list[str]) -> None:
    assert set(refs) <= set(_refs(text)), _refs(text)


def test_every_pattern_still_exposed() -> None:
    assert len(REF_RES) == 3


def test_leading_dashes_stay_out_of_the_ref() -> None:
    assert "-a.py" not in _refs("flag -a.py")
