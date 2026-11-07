"""Check that numbers published in the docs still match the result files they come from.

Each claim names a doc, a template (the doc's text with ``{}`` where the numbers go), the result
file, and how to read and print the numbers from it. The check fails when the rendered text is
not in the doc, so a changed result or an edited cell is caught. HTML comments do not count: a
stale row cannot hide there. Numbers that come from private
sessions have no result file in the repository. They are listed in ATTESTED and skipped, but
the check still fails if their phrase disappears, so the list cannot go stale.

    python scripts/check_claims.py      # exit 1 on any mismatch
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def delta(ratio: float, unit: str = " %", digits: int = 0) -> str:
    """A cost ratio as a signed change: 0.7012 -> "−30 %" (the docs use U+2212)."""
    change = round((ratio - 1) * 100, digits)
    return f"{'−' if change < 0 else '+'}{abs(change):.{digits}f}{unit}"


def share(value: float) -> str:
    """A share as a percentage, one decimal only when it has one: 0.117 -> "11.7 %"."""
    text = f"{value * 100:.1f}".removesuffix(".0")
    return f"{text} %"


def num(value: float) -> str:
    return f"{round(value):,}"


@dataclass(frozen=True)
class Claim:
    doc: str
    template: str
    source: str
    values: Callable[[Any], list[str]]


def _replay_row(key: str) -> Callable[[Any], list[str]]:
    def values(data: Any) -> list[str]:
        row = data["thresholds"][key]
        own = row["vs_own_default_affected"]
        return [
            delta(row["corpus_vs_builtin_default"]),
            share(round(row["affected_share"], 2)),
            f"{row['compactions_median_affected']:g}",
            delta(own["median"]),
            delta(own["q1"], ""),
            delta(own["q3"], ""),
            share(row["below_floor_share"]),
        ]

    return values


def _replay_cut(data: Any) -> list[str]:
    return [
        delta(data["thresholds"][f"lcc@{t}"]["corpus_vs_builtin_default"])
        for t in ("30%", "40%", "60%", "default")
    ]


REPLAY = "benchmarks/research/THRESHOLD_REPLAY.md"
REPLAY_25 = "benchmarks/research/results/threshold_replay_2026-11-07_r0.25.json"
ROW = "| {} | {} | {} | {} ({} to {}) | {} |"
JUDGE = "benchmarks/results/judge_bench.json"
CACHE = "benchmarks/research/results/cache_patterns.json"


def _cache(index: int) -> Callable[[Any], list[str]]:
    return lambda data: [
        delta(data["results"][index]["cost"] / data["results"][0]["cost"], digits=1)
    ]


def _full_pass(key: str, slow: Callable[[float], str]) -> Callable[[Any], list[str]]:
    def values(data: Any) -> list[str]:
        row = data["passes"][key]
        fixtures = row["fixtures"]
        return [
            str(row["must_keep_kept"]),
            str(row["must_keep_total"]),
            num(fixtures["synthetic_15_turns"]["median_ms"]),
            slow(fixtures["synthetic_56_turns"]["median_ms"]),
            num(row["peak_rss_mb"]),
        ]

    return values


CLAIMS = [
    Claim(REPLAY, "| built-in summary at 30 % " + ROW, REPLAY_25, _replay_row("summary@30%")),
    Claim(
        REPLAY,
        "| built-in summary at 40 % | **{}** | {} | {} | {} ({} to {}) | {} |",
        REPLAY_25,
        _replay_row("summary@40%"),
    ),
    Claim(REPLAY, "| built-in summary at 60 % " + ROW, REPLAY_25, _replay_row("summary@60%")),
    Claim(REPLAY, "| lcc verbatim, cut 25 %, at 30 % " + ROW, REPLAY_25, _replay_row("lcc@30%")),
    Claim(REPLAY, "| lcc verbatim, cut 25 %, at 40 % " + ROW, REPLAY_25, _replay_row("lcc@40%")),
    Claim(REPLAY, "| lcc verbatim, cut 25 %, at 60 % " + ROW, REPLAY_25, _replay_row("lcc@60%")),
    Claim(
        REPLAY,
        "| lcc verbatim, cut 25 %, at default | {} | {} | {} | 0 | {} |",
        REPLAY_25,
        lambda data: [
            delta(data["thresholds"]["lcc@default"]["corpus_vs_builtin_default"]),
            share(round(data["thresholds"]["lcc@default"]["affected_share"], 2)),
            f"{data['thresholds']['lcc@default']['compactions_median_affected']:g}",
            share(data["thresholds"]["lcc@default"]["below_floor_share"]),
        ],
    ),
    *(
        Claim(
            REPLAY,
            f"| {cut} % | {{}} | {{}} | {{}} | {{}} |",
            f"benchmarks/research/results/threshold_replay_2026-11-07_r0.{cut}.json",
            _replay_cut,
        )
        for cut in ("25", "40", "55")
    ),
    Claim(
        "README.md",
        "| cases with every must-keep block kept at a 30 / 50 / 70% cut (of 9) | "
        + " | ".join(["{} / {} / {}"] * 4)
        + " |",
        JUDGE,
        lambda data: [
            str(data["ranker"][judge][cut]["passes"])
            for judge in ("specialist-v3", "mechanical", "bm25", "recency")
            for cut in ("0.3", "0.5", "0.7")
        ],
    ),
    Claim(
        "README.md",
        "| full pass, default settings | must-keep kept | {} blocks | {} blocks | peak RSS |",
        JUDGE,
        lambda data: [
            num(data["passes"]["specialist-v3"]["fixtures"][name]["blocks"])
            for name in ("synthetic_15_turns", "synthetic_56_turns")
        ],
    ),
    Claim(
        "README.md",
        "| `specialist-v3`, tool-call mode | {}/{} | {} ms | {} s | {} MB |",
        JUDGE,
        _full_pass("specialist-v3", lambda ms: f"{ms / 1000:.1f}"),
    ),
    Claim(
        "README.md",
        "| `rules` lossless | {}/{} | {} ms | {} ms | {} MB |",
        JUDGE,
        _full_pass("rules-lossless", num),
    ),
    Claim(
        "docs/CACHE_ALIGNMENT.md",
        "| whole session, one pass | invalidates everything right of the first drop | **{}** |",
        CACHE,
        _cache(1),
    ),
    Claim(
        "docs/CACHE_ALIGNMENT.md",
        "| whole session, three passes | the same, three times | **{}** |",
        CACHE,
        _cache(2),
    ),
    Claim(
        "docs/CACHE_ALIGNMENT.md",
        "| **each payload before it is appended** | nothing, ever | **{}** |",
        CACHE,
        _cache(3),
    ),
]

# Published from the maintainer's private sessions: only aggregates leave the machine.
# Each phrase holds every number of its sentence, so editing one of them fails the check.
_LONG = "aggregates in docs/launch-plan.md"
ATTESTED = [
    ("README.md", "**Across all 299 of my long sessions** (100+ messages each,", _LONG),
    (
        "README.md",
        "36.3 M tokens) the median cut was **21.8%** (middle half 15% to 31%, best 65%), "
        "with 0 messages",
        _LONG,
    ),
]


def _visible(path: Path) -> str:
    return re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)


def check(
    root: Path = ROOT, claims: list[Claim] = CLAIMS, attested: list[tuple[str, str, str]] = ATTESTED
) -> list[str]:
    """Every mismatch, as one line each; empty when the docs agree with their result files."""
    failures = []
    for claim in claims:
        try:
            data = json.loads((root / claim.source).read_text(encoding="utf-8"))
            expected = claim.template.format(*claim.values(data))
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            failures.append(f"{claim.doc}: cannot render from {claim.source}: {error!r}")
            continue
        if expected not in _visible(root / claim.doc):
            failures.append(f"{claim.doc}: expected {expected!r} (from {claim.source})")
    for doc, phrase, _ in attested:
        if phrase not in _visible(root / doc):
            failures.append(f"{doc}: owner-attested phrase {phrase!r} is gone; update ATTESTED")
    return failures


def main() -> int:
    failures = check()
    for line in failures:
        print(f"MISMATCH {line}")
    for doc, phrase, why in ATTESTED:
        print(f"skipped  {doc}: {phrase} (owner-attested: {why})")
    print(
        f"{len(CLAIMS) - len(failures)}/{len(CLAIMS)} claims match"
        if not failures
        else f"{len(failures)} mismatches"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
