"""Replay real Claude Code sessions at other auto-compaction thresholds and compare input cost.

Question: does compacting earlier (30 %, 40 %, 60 % of the window) cost less input than
Claude Code's own threshold? Earlier compaction makes every later request read a shorter
prefix (cache reads, 0.1x), but each compaction re-writes the prefix after it (cache writes:
1.25x for the 5-minute cache, 2x for the 1-hour one), and the built-in summary reads the whole
context once more to write itself.

Inputs, per session (counts only; no text, path or tool output leaves the file):

- each request's context size and its billed split, from the provider's usage records
  (``message.usage`` per request; ``<synthetic>`` zero-usage records skipped). Exact;
- each real compaction (``compact_boundary``), its trigger and ``preTokens``, and the size of
  the first request after it.

Model (an approximation; the output says so):

- growth: the context grows by each request's size minus the previous one's; the request
  right after a real compaction adds 0, negative steps count as 0;
- window: ``median(preTokens) + 33k`` over the session's automatic compactions (Claude Code
  compacts about 33k under the window; a manual ``/compact`` says nothing about it), else 200k
  when the session fits under 167k, else 1M;
- fixed overhead ``F``: the first request's size;
- after a compaction the context is ``F + E`` for the built-in summary, ``E`` being the median
  of (first request after a real compaction minus ``F``) over the corpus: the summary plus
  what Claude Code re-attaches. For lcc's verbatim pass it is ``F + (1 - r)(s - F)``;
- a request is checked against the threshold with its new content included; when it is over,
  the compaction runs on that context and the request is sent compacted;
- cost of a request, in uncached-token units: ``0.1 * prefix + W * new``, where ``W`` is the
  session's own cache-write price (its billed mix of 5-minute and 1-hour writes). After a
  compaction it is ``0.1 * F + W * (the rest)``. The built-in summary also sends the whole
  context once to write itself (``0.1 * prefix + W * new``); lcc's pass runs locally and sends
  nothing. Output tokens (the summary itself) are not counted, which favours the summary.

    python benchmarks/research/threshold_replay.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

READ, WRITE_5M, WRITE_1H = 0.1, 1.25, 2.0
BUFFER = 33_000
THRESHOLDS = (0.30, 0.40, 0.60)
KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def session(path: Path) -> dict[str, Any] | None:
    """Requests (size, billed cost) in order, and real compactions, from one JSONL file."""
    order: list[str] = []
    usage: dict[str, dict[str, Any]] = {}
    after: set[str] = set()  # requests that follow a real compaction
    pre: list[int] = []
    pending = False
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"usage"' not in line and "compact_boundary" not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("type") == "system" and record.get("subtype") == "compact_boundary":
                meta = record.get("compactMetadata") or {}
                if meta.get("trigger") == "auto" and _int(meta.get("preTokens")):
                    pre.append(meta["preTokens"])
                pending = True
                continue
            message = record.get("message")
            if record.get("type") != "assistant" or not isinstance(message, dict):
                continue
            used = message.get("usage")
            if not isinstance(used, dict) or not sum(_int(used.get(k)) for k in KEYS):
                continue  # a local error writes zero usage: nothing was billed
            key = str(record.get("requestId") or message.get("id") or len(order))
            if key not in usage:
                order.append(key)
                if pending:
                    after.add(key)
                    pending = False
            usage[key] = used  # a split request's last record is complete
    if not order:
        return None
    sizes = [sum(_int(usage[k].get(f)) for f in KEYS) for k in order]
    billed = written = write_cost = 0.0
    for k in order:
        used = usage[k]
        writes = _int(used.get("cache_creation_input_tokens"))
        hour = min(
            writes, _int((used.get("cache_creation") or {}).get("ephemeral_1h_input_tokens"))
        )
        cost = WRITE_5M * (writes - hour) + WRITE_1H * hour
        written += writes
        write_cost += cost
        billed += (
            _int(used.get("input_tokens")) + cost + READ * _int(used.get("cache_read_input_tokens"))
        )
    return {
        "sizes": sizes,
        "after": [i for i, k in enumerate(order) if k in after],
        "pre": pre,
        "billed": billed,
        "write": write_cost / written if written else WRITE_5M,
    }


def window(data: dict[str, Any]) -> int:
    if data["pre"]:
        return int(statistics.median(data["pre"])) + BUFFER
    return 200_000 if max(data["sizes"]) <= 200_000 - BUFFER else 1_000_000


def deltas(data: dict[str, Any]) -> list[int]:
    sizes, after = data["sizes"], set(data["after"])
    return [0 if i in after else max(0, sizes[i] - sizes[i - 1]) for i in range(1, len(sizes))]


def replay(
    first: int, steps: list[int], limit: float, post: Any, fixed: int, write: float, summarize: bool
) -> tuple[float, int, bool]:
    """(modelled input cost, compactions, whether one landed at or over ``limit``)."""
    size, cost, compactions, floor = first, write * first, 0, False
    for step in steps:
        if size + step < limit:
            cost += READ * size + write * step
            size += step
            continue
        if summarize:  # the summary request sends the whole context once
            cost += READ * size + write * step
        size = post(size + step)
        compactions += 1
        floor = floor or size >= limit
        cost += READ * fixed + write * (size - fixed)
    return cost, compactions, floor


def quartiles(values: list[float]) -> dict[str, float]:
    q = statistics.quantiles(values, n=4) if len(values) > 1 else [values[0]] * 3
    return {"median": round(q[1], 4), "q1": round(q[0], 4), "q3": round(q[2], 4)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--min-requests", type=int, default=100)
    parser.add_argument(
        "--reduction",
        type=float,
        default=0.25,
        help="share of the context above F lcc's verbatim pass removes (the "
        "plugin's minReductionRatio; below it the built-in summary runs)",
    )
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    sessions = []
    for path in sorted(args.root.glob("*/*.jsonl")):  # sessions, not subagent transcripts
        try:
            data = session(path)
        except OSError:
            continue
        if data and len(data["sizes"]) >= args.min_requests:
            sessions.append(data)
    if not sessions:
        print("no sessions matched", file=sys.stderr)
        return 1
    extras = [
        data["sizes"][i] - data["sizes"][0]
        for data in sessions
        for i in data["after"]
        if data["sizes"][i] > data["sizes"][0]
    ]
    extra = int(statistics.median(extras)) if extras else 30_000

    rows: dict[str, dict[str, list[float]]] = {}
    model_error, builtins, writes = [], [], []
    for data in sessions:
        size_w, fixed, steps = window(data), data["sizes"][0], deltas(data)
        posts = {
            "summary": lambda s, f=fixed: f + extra,
            "lcc": lambda s, f=fixed: f + (1 - args.reduction) * (s - f),
        }
        write = data["write"]
        builtin = replay(fixed, steps, size_w - BUFFER, posts["summary"], fixed, write, True)[0]
        model_error.append(builtin / data["billed"] if data["billed"] else 1.0)
        builtins.append(builtin)
        writes.append(write)
        for name in posts:
            own = replay(
                fixed, steps, size_w - BUFFER, posts[name], fixed, write, name == "summary"
            )[0]
            for share in (*THRESHOLDS, None):
                limit = size_w - BUFFER if share is None else share * size_w
                cost, count, floor = replay(
                    fixed, steps, limit, posts[name], fixed, write, name == "summary"
                )
                label = "default" if share is None else f"{round(share * 100)}%"
                row = rows.setdefault(
                    f"{name}@{label}", {"own": [], "builtin": [], "n": [], "floor": [], "cost": []}
                )
                row["cost"].append(cost)
                row["own"].append(cost / own)
                row["builtin"].append(cost / builtin)
                row["n"].append(count)
                row["floor"].append(float(floor))

    def summary(row: dict[str, list[float]]) -> dict[str, Any]:
        hit = [i for i, n in enumerate(row["n"]) if n > 0]  # sessions this threshold changes
        return {
            "affected_share": round(len(hit) / len(row["n"]), 3),
            "compactions_median_affected": statistics.median([row["n"][i] for i in hit] or [0]),
            "below_floor_share": round(statistics.fmean(row["floor"]), 3),
            "vs_own_default_affected": quartiles([row["own"][i] for i in hit] or [1.0]),
            "vs_builtin_default_affected": quartiles([row["builtin"][i] for i in hit] or [1.0]),
            "vs_builtin_default_all": quartiles(row["builtin"]),
            # Same sessions for every row, weighted by size: the corpus' modelled input.
            "corpus_vs_builtin_default": round(sum(row["cost"]) / sum(builtins), 4),
        }

    report = {
        "sessions": len(sessions),
        "min_requests": args.min_requests,
        "requests": sum(len(d["sizes"]) for d in sessions),
        "real_compactions": sum(len(d["after"]) for d in sessions),
        "post_compaction_extra_tokens_median": extra,
        "lcc_reduction": args.reduction,
        "model_vs_billed_at_default": quartiles(model_error),
        "write_price_median": round(statistics.median(writes), 3),
        "thresholds": {name: summary(row) for name, row in rows.items()},
        "approximation": (
            "Billed input is exact (5-minute and 1-hour cache writes priced apart); the replay is a model: growth from usage deltas, one fixed "
            "overhead, one post-compaction size, no output tokens. Use it to compare thresholds, "
            "not as a bill."
        ),
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
