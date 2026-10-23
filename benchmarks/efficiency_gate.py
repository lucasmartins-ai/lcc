#!/usr/bin/env python3
# ruff: noqa: E501 — fixture rows and messages read better unwrapped (as in run_judge_bench).
"""Efficiency regression gate: tokens out, stable-prefix share and a machine-normalised cost.

Runs each product path on fixed synthetic inputs (seeded, offline, no model call) and compares
the result with ``benchmarks/results/efficiency_baseline.json``. A path fails when

* ``tokens_out`` grows more than ``--token-tolerance`` (default 1%; the count is deterministic),
* ``prefix_share`` (how much of the output for session N survives byte-identical at the head of
  the output for the same session plus a few turns, the share a prompt cache can reuse) drops
  more than ``--prefix-tolerance`` (default 0.02, absolute), or
* ``cost`` grows more than ``--cost-tolerance`` (default 50%).

``cost`` is wall time divided by a calibration loop timed in the same process (best of several
runs, calibration measured before and after), so a slower or busier machine moves both sides.
It is a proxy, not a benchmark: it catches a path going from O(n) to O(n^2), not a 10% tweak.

Tokens use the approximate counter on purpose: ``tiktoken`` needs a local encoding cache that
CI may not have, and the gate compares like with like, not absolute numbers.

    python benchmarks/efficiency_gate.py                       # print the measurements
    python benchmarks/efficiency_gate.py --check               # exit 1 on a regression
    python benchmarks/efficiency_gate.py --update-baseline --note "why the numbers moved"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
os.environ.setdefault("LCC_DISABLE_NETWORK", "1")

from lcc.intake.pipeline import LccIntake  # noqa: E402
from lcc.mcp_server import handle_message  # noqa: E402
from lcc.relevance import RelevanceCompactionRequest, compact_context  # noqa: E402
from lcc.relevance.cache_contract import prefix_stability  # noqa: E402
from lcc.relevance.specialist import render_transcript  # noqa: E402
from lcc.relevance.transcript import (  # noqa: E402
    TranscriptCompactionRequest,
    compact_transcript,
    messages_to_payload,
    parse_transcript,
)
from lcc.token_budget.counters import count_tokens  # noqa: E402
from specialist_synthetic import GOAL, synthetic_payload  # noqa: E402

BASELINE = ROOT / "benchmarks" / "results" / "efficiency_baseline.json"
CHANGELOG = ROOT / "CHANGELOG.md"
SCHEMA = "efficiency-gate-1.0"
SEED = 7
#: Turns appended to build the "related request" for the prefix share (about 4 messages each).
EXTRA_TURNS = 6
#: ~6.2 messages per turn: 400 turns is the 2,500-message transcript.
V3_TURNS = 400


def tokens(text: str) -> int:
    return count_tokens(text, allow_exact=False).value


def serialise(messages: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(m, sort_keys=True, ensure_ascii=False) for m in messages)


# --- paths: each takes a turn count and returns (input text, output text) -----------------------


def _rereads(turns: int) -> list[dict[str, Any]]:
    """Files re-read unchanged and read-only commands: what lossless/recoverable act on."""
    messages: list[dict[str, Any]] = [{"role": "user", "text": GOAL}]
    for i in range(turns):
        path = f"/repo/src/app/module_{i % 5}.py"
        body = "\n".join(f"{n}: def handler_{i % 5}_{n}(payload): return payload  # {n * 7}" for n in range(40))
        for tool, tool_input, text in (
            ("Read", {"file_path": path}, body),
            ("Bash", {"command": "git status"}, f"On branch main\n{i % 3} files changed"),
        ):
            cid = f"call_{i}_{tool}"
            messages.append({"role": "assistant", "text": f"step {i}",
                             "toolUses": [{"tool_use_id": cid, "tool": tool, "input": tool_input}]})
            messages.append({"role": "user", "text": "",
                             "toolResults": [{"tool_use_id": cid, "text": text}]})
    return messages


def _transcript_path(
    provider: str, rules_mode: str, build: Callable[[int], list[dict[str, Any]]] | None = None
) -> Callable[[int], tuple[str, str]]:
    def run(turns: int) -> tuple[str, str]:
        payload = build(turns) if build else synthetic_payload(SEED, turns)
        result = compact_transcript(
            TranscriptCompactionRequest(
                payload={"messages": payload},
                question=GOAL,
                provider=provider,
                rules_mode=rules_mode,
                cache_state="cold",
            )
        )
        if provider == "auto":
            assert result.report["provider_used"] == "specialist-v3", result.report["provider_used"]
        return serialise(payload), serialise(messages_to_payload(result.messages))

    return run


def _blocks_mechanical(turns: int) -> tuple[str, str]:
    text, segments = render_transcript(parse_transcript(synthetic_payload(SEED, turns)))
    result = compact_context(
        RelevanceCompactionRequest(text=text, question=GOAL, provider="mechanical", segments=segments)
    )
    return text, result.compacted_text


_BRIEF = (
    "um, so I need the checkout page to stop timing out on mobile. The goal is p95 under two "
    "seconds. Constraints: no new dependencies, keep the current API. Acceptance: Playwright "
    "test on a throttled 4G profile passes. Context: the release on Monday made it worse."
)


def _intake(turns: int) -> tuple[str, str]:
    # Longer inputs for longer "sessions": the same brief plus numbered notes.
    steps = ["cart", "payment", "address", "search", "login"]
    notes = "".join(f"\nNote {i}: the {steps[i % 5]} step is slow on mobile." for i in range(turns))
    raw = _BRIEF + notes
    return raw, LccIntake().process(raw).formatted_prompt


def _mcp(turns: int) -> tuple[str, str]:
    payload = _rereads(turns)
    args = {"messages": payload, "question": GOAL, "provider": "rules", "ledger": False}
    response = handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "compact_transcript", "arguments": args}}
    )
    assert response is not None and "error" not in response, response
    result = response["result"]
    assert not result.get("isError"), result
    out = json.loads(result["content"][0]["text"])["messages"]
    return serialise(payload), serialise(out)


#: name -> (runner, turns for tokens/cost, turns for the prefix pair, timing repeats)
PATHS: dict[str, tuple[Callable[[int], tuple[str, str]], int, int, int]] = {
    "rules-lossless": (_transcript_path("rules", "lossless", _rereads), 300, 60, 3),
    "rules-recoverable": (_transcript_path("rules", "recoverable", _rereads), 300, 60, 3),
    "rules-stashed": (_transcript_path("rules", "stashed"), 60, 60, 3),
    "specialist-v3-auto-2500": (_transcript_path("auto", "lossless"), V3_TURNS, 60, 1),
    "blocks-mechanical": (_blocks_mechanical, 60, 60, 3),
    "intake": (_intake, 1500, 60, 5),
    "mcp-compact-transcript": (_mcp, 300, 60, 3),
}


# --- measurement ---------------------------------------------------------------------------------


def _calibration_once() -> float:
    start = time.perf_counter()
    table: dict[str, int] = {}
    total = 0
    for i in range(120_000):
        key = f"k{i % 997}"
        table[key] = table.get(key, 0) + i
        total += len(key.split("k")) + len(str(table[key]))
    elapsed = time.perf_counter() - start
    assert total > 0
    return elapsed


def calibration() -> float:
    return min(_calibration_once() for _ in range(3))


def measure(name: str) -> dict[str, Any]:
    run, turns, pair_turns, repeats = PATHS[name]
    best = float("inf")
    text_in = text_out = ""
    for _ in range(repeats):
        before = calibration()
        start = time.perf_counter()
        text_in, text_out = run(turns)
        elapsed = time.perf_counter() - start
        best = min(best, elapsed / min(before, calibration()))
    base_out = text_out if turns == pair_turns else run(pair_turns)[1]
    grown_out = run(pair_turns + EXTRA_TURNS)[1]
    return {
        "tokens_in": tokens(text_in),
        "tokens_out": tokens(text_out),
        "prefix_share": prefix_stability(base_out, grown_out)["share"],
        "cost": round(best, 3),
    }


def run_all(only: list[str] | None = None) -> dict[str, Any]:
    names = only or list(PATHS)
    with tempfile.TemporaryDirectory() as stash:
        os.environ["LCC_STASH_DIR"] = stash
        results = {name: measure(name) for name in names}
    return {
        "schema_version": SCHEMA,
        "token_counter": "approximate (heuristic), same on every machine",
        "paths": results,
    }


# --- gate ----------------------------------------------------------------------------------------


def compare(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    token_tolerance: float = 0.01,
    prefix_tolerance: float = 0.02,
    cost_tolerance: float = 0.5,
) -> list[str]:
    problems: list[str] = []
    for name, now in current["paths"].items():
        base = baseline["paths"].get(name)
        if base is None:
            problems.append(f"{name}: not in the baseline; run --update-baseline --note ...")
            continue
        if now["tokens_out"] > base["tokens_out"] * (1 + token_tolerance):
            problems.append(
                f"{name}: tokens_out {base['tokens_out']} -> {now['tokens_out']} "
                f"(+{now['tokens_out'] / base['tokens_out'] - 1:.1%}, limit +{token_tolerance:.0%})"
            )
        if now["prefix_share"] < base["prefix_share"] - prefix_tolerance:
            problems.append(
                f"{name}: prefix_share {base['prefix_share']:.4f} -> {now['prefix_share']:.4f} "
                f"(limit -{prefix_tolerance})"
            )
        if now["cost"] > base["cost"] * (1 + cost_tolerance):
            problems.append(
                f"{name}: cost {base['cost']} -> {now['cost']} "
                f"(+{now['cost'] / base['cost'] - 1:.0%}, limit +{cost_tolerance:.0%})"
            )
    return problems


def _log_changelog(note: str) -> None:
    line = f"- **Efficiency baseline updated.** {note.strip()}\n"
    text = CHANGELOG.read_text(encoding="utf-8")
    unreleased = text.index("## [Unreleased]")
    nxt = re.search(r"^## \[", text[unreleased + 1 :], re.M)
    end = unreleased + 1 + nxt.start() if nxt else len(text)
    section = text[unreleased:end]
    if "### Changed\n" in section:
        at = unreleased + section.index("### Changed\n") + len("### Changed\n")
        text = text[:at] + "\n" + line + text[at:]
    else:
        at = unreleased + len("## [Unreleased]\n")
        text = text[:at] + "\n### Changed\n\n" + line + text[at:]
    CHANGELOG.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 on a regression")
    parser.add_argument("--update-baseline", action="store_true", help="rewrite the baseline")
    parser.add_argument("--note", help="why the baseline moves (required with --update-baseline)")
    parser.add_argument("--only", nargs="+", choices=list(PATHS), help="measure these paths only")
    parser.add_argument("--token-tolerance", type=float, default=0.01)
    parser.add_argument("--prefix-tolerance", type=float, default=0.02)
    parser.add_argument("--cost-tolerance", type=float, default=0.5)
    args = parser.parse_args(argv)
    if args.update_baseline and (not args.note or args.only):
        parser.error("--update-baseline needs --note and measures every path (no --only)")
    current = run_all(args.only)
    print(json.dumps(current, indent=2, sort_keys=True))
    if args.update_baseline:
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _log_changelog(args.note)
        print(f"baseline written to {BASELINE.relative_to(ROOT)}; CHANGELOG line added", file=sys.stderr)
        return 0
    if args.check:
        problems = compare(
            json.loads(BASELINE.read_text(encoding="utf-8")),
            current,
            token_tolerance=args.token_tolerance,
            prefix_tolerance=args.prefix_tolerance,
            cost_tolerance=args.cost_tolerance,
        )
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
