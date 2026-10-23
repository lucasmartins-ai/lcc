#!/usr/bin/env python3
# ruff: noqa: E501 — fixture rows and the usage block read better unwrapped (as in run_judge_bench).
"""Prefix stability of compaction passes over growing sessions (no network, < 30 s).

Prompt caches reuse a request's byte-identical prefix. This benchmark grows seeded synthetic
sessions turn by turn, runs a compaction pass between turns, and measures how much of the
previous pass's output survives byte-identical at the head of the next one: the share a warm
provider cache can still serve. It checks the invariants in docs/CACHE_ALIGNMENT.md
("Invariants and tests"):

dossier      block-level ``lcc compact`` (mechanical provider, sticky decisions cache,
             ``previous_compacted_text``). I1/I4: every pass is append-only unless the report
             opens a cache epoch (``cache_effect.epoch_opened`` with ``sticky_flips``). A
             break the report does not flag, or one without a named sticky flip, is a failure. The ``legacy`` arm re-runs the same
             sessions with merged dropped-run markers (the behaviour before cache contract 1.0) for comparison.
transcript   tool-call ``rules_mode="stashed"`` passes (what the idle stash runs). A stash
             pass is a deliberate epoch, so its share is informational; I2 is checked: a
             second pass over a pass's output changes nothing (idempotence), and placeholders
             an earlier pass emitted are never rewritten by a later one.

    python benchmarks/cache/run_prefix_stability.py                 # print the summary
    python benchmarks/cache/run_prefix_stability.py --check         # exit 1 on a violation
    python benchmarks/cache/run_prefix_stability.py --out DIR       # also write DIR/prefix_stability.json

Everything is deterministic: seeded RNGs, fixed word lists, no timestamps in the JSON.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("LCC_DISABLE_NETWORK", "1")

from lcc.relevance import RelevanceCompactionRequest, compact_context  # noqa: E402
from lcc.relevance.cache_contract import prefix_stability  # noqa: E402
from lcc.relevance.transcript import (  # noqa: E402
    TranscriptCompactionRequest,
    compact_transcript,
    messages_to_payload,
)

OBJECTIVE = "Why did checkout conversion fall after the mobile release?"
_RELEVANT = ["conversion", "checkout", "mobile", "release", "funnel", "cohort", "regression"]
_NOISE = ["plants", "coffee", "weather", "parking", "lunch", "holiday", "printer", "music"]
_FILES = ["src/app/router.py", "src/app/cache.py", "src/lib/parser.ts", "docs/SETUP.md"]
_STASH_NOTE = re.compile(r"^\[removed: (?:\d+ tokens|\d+ lines?, \d+(?:\.\d)? K?B) · lcc recall [0-9a-f]{12}\]$")

#: --check floors. Unreported breaks, idempotence violations and placeholder rewrites must be
#: zero; the append-only rate floor guards against a regression that reports every pass as an
#: epoch (technically honest, useless for caching).
MIN_APPEND_ONLY_RATE = 0.9


# --- dossier: block-level compaction ----------------------------------------------------------


def _dossier_block(rng: random.Random, index: int) -> str:
    roll = rng.random()
    if roll < 0.35:
        words = rng.choices(_RELEVANT, k=28) + rng.choices(_NOISE, k=8)
    elif roll < 0.45:
        words = rng.choices(_NOISE, k=6)  # short: protected, never scored
    else:
        words = rng.choices(_NOISE, k=40)
    return f"Turn {index}: " + " ".join(words) + "."


def simulate_dossier(seed: int, turns: int, *, merge_dropped_runs: bool | None = None) -> list[dict[str, Any]]:
    """One growing dossier; a pass after every turn. Returns one record per pass after the first."""
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "decisions.jsonl"
        text = "System contract: answer questions about checkout conversion.\n"
        previous: str | None = None
        index = 0
        for turn in range(turns):
            for _ in range(rng.randint(1, 3)):
                index += 1
                text += "\n" + _dossier_block(rng, index) + "\n"
            result = compact_context(
                RelevanceCompactionRequest(
                    text=text,
                    question=OBJECTIVE,
                    provider="mechanical",
                    decisions_cache_path=cache,
                    previous_compacted_text=previous,
                    merge_dropped_runs=merge_dropped_runs,
                )
            )
            out = result.compacted_text
            if previous is not None:
                stability = prefix_stability(previous, out)
                effect = result.report.cache_effect or {}
                records.append(
                    {
                        "seed": seed,
                        "turn": turn,
                        **stability,
                        "epoch_opened": bool(effect.get("epoch_opened")),
                        "sticky_flips": len(effect.get("sticky_flips") or []),
                        "reported": bool(effect.get("epoch_opened")) or stability["append_only"],
                        # A break the contract allows: a sticky flip the report names (I1).
                        "explained": stability["append_only"] or bool(effect.get("sticky_flips")),
                    }
                )
            previous = out
    return records


# --- transcript: stashed tool-call passes ----------------------------------------------------


def _tool_call(rng: random.Random, n: int) -> tuple[str, dict[str, Any], str]:
    roll = rng.random()
    if roll < 0.45:
        path = rng.choice(_FILES)
        body = "\n".join(
            f"{n}:{line} " + " ".join(rng.choices(_NOISE + _RELEVANT, k=8))
            for line in range(rng.randint(20, 120))
        )
        return "Read", {"file_path": f"/repo/{path}"}, body
    if roll < 0.75:
        body = "\n".join(
            f"[{n}.{line}] build step " + " ".join(rng.choices(_NOISE, k=6))
            for line in range(rng.randint(10, 400))
        )
        return "Bash", {"command": f"make build-{n}"}, body
    return "Grep", {"pattern": rng.choice(_RELEVANT)}, f"src/app/router.py:{n}: match"


def _append_turns(rng: random.Random, messages: list[dict[str, Any]], start: int, count: int) -> int:
    for n in range(start, start + count):
        tool, tool_input, output = _tool_call(rng, n)
        messages.append(
            {"role": "assistant", "text": f"step {n}", "toolUses": [{"id": f"c{n}", "tool": tool, "input": tool_input}]}
        )
        messages.append({"role": "user", "text": "", "toolResults": [{"id": f"c{n}", "text": output}]})
    return start + count


def _stash_pass(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = compact_transcript(
        TranscriptCompactionRequest(
            payload={"messages": copy.deepcopy(messages)},
            question=OBJECTIVE,
            provider="rules",
            rules_mode="stashed",
            preserve_recent=4,
            cache_state="cold",
        )
    )
    return messages_to_payload(result.messages), result.report


def _placeholders(payload: list[dict[str, Any]]) -> dict[str, str]:
    found: dict[str, str] = {}
    for message in payload:
        for result in message.get("toolResults") or []:
            text = result.get("text") or ""
            if _STASH_NOTE.match(text):
                found[str(result.get("tool_use_id"))] = text
    return found


def _serialise(payload: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(message, sort_keys=True, ensure_ascii=False) for message in payload)


def simulate_transcript(seed: int, rounds: int) -> list[dict[str, Any]]:
    """One growing session; a stash pass after every round of turns."""
    rng = random.Random(seed)
    messages: list[dict[str, Any]] = [{"role": "user", "text": OBJECTIVE}]
    next_call = _append_turns(rng, messages, 1, 18)
    records: list[dict[str, Any]] = []
    previous: list[dict[str, Any]] | None = None
    for round_index in range(rounds):
        out, report = _stash_pass(messages)
        again, _ = _stash_pass(out)
        record: dict[str, Any] = {
            "seed": seed,
            "round": round_index,
            "idempotent": again == out,
            "stashed": int(report.get("tool_calls_stashed") or 0),
            "removed_tokens": int(report.get("tokens_before", 0)) - int(report.get("tokens_after", 0)),
            "recommended": bool((report.get("cache_effect") or {}).get("recommended")),
        }
        if previous is not None:
            before = _placeholders(previous)
            after = _placeholders(out)
            record["placeholder_rewrites"] = sum(
                1 for call_id, note in before.items() if after.get(call_id) != note
            )
            record.update(prefix_stability(_serialise(previous), _serialise(out)))
        records.append(record)
        previous = out
        messages = copy.deepcopy(out)
        next_call = _append_turns(rng, messages, next_call, rng.randint(3, 8))
    return records


# --- summary -----------------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 1.0


def run(seeds: int = 12, turns: int = 12, rounds: int = 5) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as stash:
        previous_stash = os.environ.get("LCC_STASH_DIR")
        os.environ["LCC_STASH_DIR"] = stash
        try:
            dossier = [r for seed in range(seeds) for r in simulate_dossier(seed, turns)]
            legacy = [
                r
                for seed in range(seeds)
                for r in simulate_dossier(seed, turns, merge_dropped_runs=True)
            ]
            transcript = [r for seed in range(seeds) for r in simulate_transcript(seed, rounds)]
        finally:
            if previous_stash is None:
                os.environ.pop("LCC_STASH_DIR", None)
            else:
                os.environ["LCC_STASH_DIR"] = previous_stash

    def dossier_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "passes": len(records),
            "append_only_rate": _mean([1.0 if r["append_only"] else 0.0 for r in records]),
            "mean_stable_prefix_share": _mean([r["share"] for r in records]),
            "min_stable_prefix_share": min((r["share"] for r in records), default=1.0),
            "epochs_reported": sum(1 for r in records if r["epoch_opened"]),
            "sticky_flips": sum(r["sticky_flips"] for r in records),
            "unreported_prefix_breaks": sum(1 for r in records if not r["reported"]),
            "unexplained_prefix_breaks": sum(1 for r in records if not r["explained"]),
        }

    later = [r for r in transcript if "share" in r]
    return {
        "schema_version": "prefix-stability-1.0",
        "config": {"seeds": seeds, "turns": turns, "rounds": rounds, "objective": OBJECTIVE},
        "dossier": dossier_summary(dossier),
        "dossier_legacy_merged_markers": dossier_summary(legacy),
        "transcript_stashed": {
            "passes": len(transcript),
            "idempotence_violations": sum(1 for r in transcript if not r["idempotent"]),
            "placeholder_rewrites": sum(r.get("placeholder_rewrites", 0) for r in transcript),
            "outputs_stashed": sum(r["stashed"] for r in transcript),
            "removed_tokens": sum(r["removed_tokens"] for r in transcript),
            "recommended_on_cold_cache": sum(1 for r in transcript if r["recommended"]),
            "mean_stable_prefix_share": _mean([r["share"] for r in later]),
            "min_stable_prefix_share": min((r["share"] for r in later), default=1.0),
        },
    }


def check(summary: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    dossier = summary["dossier"]
    if dossier["unreported_prefix_breaks"]:
        problems.append(f"{dossier['unreported_prefix_breaks']} unreported prefix break(s) (I1/I4)")
    if dossier["unexplained_prefix_breaks"]:
        problems.append(
            f"{dossier['unexplained_prefix_breaks']} prefix break(s) without a sticky flip (I4)"
        )
    if dossier["append_only_rate"] < MIN_APPEND_ONLY_RATE:
        problems.append(f"append-only rate {dossier['append_only_rate']} < {MIN_APPEND_ONLY_RATE}")
    stash = summary["transcript_stashed"]
    if stash["idempotence_violations"]:
        problems.append(f"{stash['idempotence_violations']} non-idempotent stash pass(es) (I2)")
    if stash["placeholder_rewrites"]:
        problems.append(f"{stash['placeholder_rewrites']} placeholder rewrite(s) (I2)")
    if not stash["outputs_stashed"]:
        problems.append("the transcript arm stashed nothing; the fixture no longer exercises I2")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 on an invariant violation")
    parser.add_argument("--out", type=Path, help="write prefix_stability.json into this directory")
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--turns", type=int, default=12)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args(argv)
    summary = run(seeds=args.seeds, turns=args.turns, rounds=args.rounds)
    text = json.dumps(summary, indent=2, sort_keys=True)
    print(text)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "prefix_stability.json").write_text(text + "\n", encoding="utf-8")
    if args.check:
        problems = check(summary)
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
