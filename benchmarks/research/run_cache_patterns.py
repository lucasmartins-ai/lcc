#!/usr/bin/env python3
"""Cache-pattern economics: whole-context compaction versus per-tool-call compaction.

The distinction this measures is where the compaction happens, not how much it removes.

**Whole-context** (`lcc compact session.md`): the pass rewrites the accumulated context, so the
first drop mutates a byte-stable prefix. Everything to the right of that offset stops being a
cache read and becomes a cache write. On a warm session that is the expensive case, and it is
the one the cache-alignment rules exist to avoid.

**Per-tool-call** (`lcc compact result.txt` before appending it): the tool result is compacted
while it is still a standalone payload, and only the compacted version is ever appended. The
prefix never changes, so no warm byte is invalidated, and the reduction is captured at the price
of fresh input rather than at the price of a cache epoch.

Price model, from the repository's own `docs/CACHE_ALIGNMENT.md`:

    cache read  0.10x   cache write  1.25x   fresh input  1.25x (a write is how new bytes land)

Cost is reported in read-token-equivalents, so 1.0 means "one token at full input price".

Run: python3 run_cache_patterns.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
CORPORA = ROOT / "corpora"
WORK = ROOT / "work_patterns"
OUT = ROOT / "results"
OBJECTIVE = "What is wrong with the clinic's booking operation, and what limits what we can change?"

CACHE_READ = 0.10
CACHE_WRITE = 1.25


def exact_tokens(text: str) -> int:
    import tiktoken

    return len(tiktoken.get_encoding("o200k_base").encode(text))


def compact_text(path: pathlib.Path, tag: str) -> str:
    """Run one real compaction pass and return the emitted bytes."""
    dest = WORK / f"{tag}.md"
    report = WORK / f"{tag}.json"
    proc = subprocess.run(
        [
            "lcc", "compact", str(path),
            "-q", OBJECTIVE,
            "--provider", "jev",
            "-o", str(dest),
            "-r", str(report),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout)[-300:])
    return dest.read_text(encoding="utf-8")


def first_divergence(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    i = 0
    while i < limit and a[i] == b[i]:
        i += 1
    return i


def simulate(
    prefix: str,
    turns: list[str],
    *,
    pattern: str,
    calls_per_turn: int = 2,
    passes: int = 1,
) -> dict:
    """Total cost of a session under one compaction pattern.

    `pattern`:
      "none"      no compaction at all
      "whole"     compact the accumulated context `passes` times across the session
      "perturn"   compact each turn's payload before appending it
    """
    cost = 0.0
    jev_tokens = 0
    processed = 0

    if pattern == "none":
        context = prefix
        warm = 0
        for turn in turns:
            context += turn
            for _ in range(calls_per_turn):
                total = exact_tokens(context)
                cost += warm * CACHE_READ + max(0, total - warm) * CACHE_WRITE
                processed += total
                warm = total
        return {"pattern": pattern, "cost": round(cost, 1), "tokens_processed": processed}

    if pattern == "whole":
        context = prefix
        warm = 0
        # Spread the passes across the session, which is what a long session actually does.
        pass_at = {
            max(1, round(len(turns) * (i + 1) / (passes + 1))) for i in range(passes)
        }
        for index, turn in enumerate(turns):
            context += turn
            if index in pass_at:
                src = WORK / "whole_in.md"
                src.write_text(context, encoding="utf-8")
                jev_tokens += _jev_pass_tokens(src)
                new_context = compact_text(src, "whole_out")
                divergence = first_divergence(context, new_context)
                warm = exact_tokens(context[:divergence])
                context = new_context
            for _ in range(calls_per_turn):
                total = exact_tokens(context)
                cost += warm * CACHE_READ + max(0, total - warm) * CACHE_WRITE
                processed += total
                warm = total
        return {
            "pattern": pattern,
            "cost": round(cost, 1),
            "tokens_processed": processed,
            "jev_tokens": jev_tokens,
        }

    if pattern == "perturn":
        # Only the compacted payload is ever appended, so the prefix is byte-stable forever.
        context = prefix
        warm = 0
        for index, turn in enumerate(turns):
            src = WORK / f"turn_in_{index}.md"
            src.write_text(turn, encoding="utf-8")
            jev_tokens += _jev_pass_tokens(src)
            payload = compact_text(src, f"turn_out_{index}")
            context += payload
            for _ in range(calls_per_turn):
                total = exact_tokens(context)
                cost += warm * CACHE_READ + max(0, total - warm) * CACHE_WRITE
                processed += total
                warm = total
        return {
            "pattern": pattern,
            "cost": round(cost, 1),
            "tokens_processed": processed,
            "jev_tokens": jev_tokens,
        }

    raise ValueError(pattern)


#: Measured per-call input tokens spent on the question text itself (Finding 11).
_JEV_SCAFFOLDING_TOKENS = 1445


def _jev_pass_tokens(src: pathlib.Path) -> int:
    """Tokens the compaction pass itself spends, from the shape of the real run.

    Reported in tokens rather than converted to read-equivalents: Jev is billed on its own
    schedule, which is not the main model's, and conflating the two would invent a number. The
    figures come from the measured per-call usage in Finding 11: one call over eight blocks
    costs about 1,765 input tokens, of which roughly 1,445 is the question scaffolding and the
    rest is the block content.
    """
    text = src.read_text(encoding="utf-8")
    blocks = len([b for b in text.split("\n\n") if b.strip()])
    calls = max(1, -(-blocks // 8))
    return exact_tokens(text) + calls * _JEV_SCAFFOLDING_TOKENS


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    corpus = (CORPORA / "medium.md").read_text(encoding="utf-8")
    block_list = corpus.split("\n\n")
    prefix = "\n\n".join(block_list[:6])
    rest = block_list[6:]
    size = max(1, len(rest) // 5)
    turns = ["\n\n".join(rest[i * size : (i + 1) * size]) for i in range(5)]

    print(f"prefix {exact_tokens(prefix)} tokens | {len(turns)} turns | "
          f"{sum(exact_tokens(t) for t in turns)} tokens of appended payload")
    print()
    header = (f"{'pattern':10} {'passes':>7} {'context cost':>13} {'tokens seen':>12} "
              f"{'jev tokens':>11} {'vs none':>9}")
    print(header)
    print("-" * len(header))
    results: list[dict] = []
    baseline = None
    for pattern, passes in (("none", 1), ("whole", 1), ("whole", 3), ("perturn", 5)):
        row = simulate(prefix, turns, pattern=pattern, passes=passes)
        row["passes"] = passes
        if baseline is None:
            baseline = row["cost"]
        results.append(row)
        delta = (row["cost"] - baseline) / baseline * 100
        print(f"{pattern:10} {passes:>7} {row['cost']:>13,.0f} {row['tokens_processed']:>12,} "
              f"{row.get('jev_tokens', 0):>11,} {delta:>8.1f}%")

    payload = {
        "corpus": "medium",
        "calls_per_turn": 2,
        "price_model": {"cache_read": CACHE_READ, "cache_write": CACHE_WRITE},
        "note": (
            "context cost is in read-token-equivalents for the main model only; jev_tokens are "
            "counted separately because Jev is billed on its own schedule"
        ),
        "results": results,
    }
    (OUT / "cache_patterns.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n-> {OUT / 'cache_patterns.json'}")


if __name__ == "__main__":
    main()
