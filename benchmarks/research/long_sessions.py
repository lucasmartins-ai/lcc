"""Reproduce the README's "all long sessions" numbers on your own machine.

Walks every Claude Code session one level under a root (default ``~/.claude/projects``), keeps the ones
with at least ``--min-messages`` messages, runs ``lcc measure-session`` on each, and prints the
per-mode median, middle half and best reduction, plus the user/assistant texts lost.
Offline, counts only. Exact counts need the ``tiktoken`` extra with ``o200k_base`` cached.

    python benchmarks/research/long_sessions.py                 # README: 100+ messages
    python benchmarks/research/long_sessions.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from lcc.session_report import MODES, from_claude_code, measure_session


def _measure(path: Path, min_messages: int) -> dict | None:
    started = time.perf_counter()
    try:
        if len(from_claude_code(path)) < min_messages:
            return None
        report = measure_session(path)
    except Exception as error:  # noqa: BLE001 - one unreadable file is not the corpus
        print(f"skip {path.name}: {type(error).__name__}", file=sys.stderr)
        return None
    print(f"{time.perf_counter() - started:7.1f}s {path.name}", file=sys.stderr, flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--min-messages", type=int, default=100)
    parser.add_argument("--json", type=Path, help="write the aggregate here")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()

    paths = sorted(args.root.glob("*/*.jsonl"))  # sessions, not subagent transcripts
    with ProcessPoolExecutor(args.workers) as pool:
        found = pool.map(_measure, paths, [args.min_messages] * len(paths))
        reports = [report for report in found if report is not None]
    if not reports:
        print("no sessions matched", file=sys.stderr)
        return 1

    methods = sorted({r["token_count_method"] for r in reports})
    aggregate = {
        "sessions": len(reports),
        "min_messages": args.min_messages,
        "tokens_before": sum(r["tokens_before"] for r in reports),
        "token_count_method": methods,
        "modes": [],
    }
    for label, _provider, _rules_mode in MODES:
        rows = [row for r in reports for row in r["modes"] if row["mode"] == label]
        values = sorted(row["reduction"] for row in rows if "error" not in row)
        if not values:
            continue
        q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
        aggregate["modes"].append(
            {
                "mode": label,
                "n": len(values),
                "median": round(statistics.median(values), 4),
                "q1": round(q1, 4),
                "q3": round(q3, 4),
                "best": max(values),
                "texts_lost": sum(row.get("texts_lost", 0) for row in rows),
            }
        )

    print(
        f"{aggregate['sessions']} sessions with {args.min_messages}+ messages, "
        f"{aggregate['tokens_before']:,} tokens, counted {'/'.join(methods)}"
    )
    for m in aggregate["modes"]:
        print(
            f"{m['mode']:<15} n={m['n']:<4} median {m['median']:.1%}  "
            f"middle half {m['q1']:.1%} to {m['q3']:.1%}  best {m['best']:.1%}  "
            f"texts lost {m['texts_lost']}"
        )
    if args.json:
        args.json.write_text(json.dumps(aggregate, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
