#!/usr/bin/env python3
"""Claude as a labeller, checked blind on Part R (PROTOCOL.md, Amendment 7).

    python benchmarks/research/intake-objective-v1/part_r_claude.py prepare
    # one fresh agent, model alias opus, labels the input with BRIEF (Amendment 7)
    python benchmarks/research/intake-objective-v1/part_r_claude.py score

``prepare`` writes the dictations the owner kept in Part R, as the labelling page shows them and with
no gold, to ``~/.lcc-private/intake-objective-v1-claude/``. ``score`` compares the agent's pick with
the owner's gold by Amendment 2's hit rule and writes ``stats_r_claude.json`` (aggregates only).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import part_r  # noqa: E402
import run_arms  # noqa: E402
from run_arms import HERE  # noqa: E402

#: Files this one reuses, as Amendments 4 and 2 pin them.
PINNED = {
    "part_r.py": "cc0da0564f8904f3b8094c737bdaa9fabf02af39bcbc0e659a5a5d17c7699659",
    "run_arms.py": "bf4e66b24d370d52baceb0520c6613907a2564c6e67dd00bf2561bd102647e82",
}
PRIVATE = part_r.PRIVATE.with_name("intake-objective-v1-claude")
INPUT = PRIVATE / "input_r.txt"
ANSWER = PRIVATE / "claude_labels_r.json"
OUT = HERE / "stats_r_claude.json"
PASS = 19  # of Part R's 22: the agent's pick is the owner's main ask in at least this many
WIDTH = 160  # short lines: a long line is where a file read can cut text without saying so
BRIEF = """You are labelling dictations for a study. Their owner authorised you to read one file,
{input}, and to write one file, {answer}. Read no other file, run no shell command, and use only
the Read and Write tools.

The input holds {n} messages. Each opens with a line "=== ITEM k/{n} · id ID · S frases ===". A line
"[j] ..." starts sentence j; indented lines continue it, and " ⏎ " marks a line break in the
original. Lines starting "--- " are text the owner's page showed between sentences without letting
it be picked. Read the whole file, in parts if needed, up to the line "=== FIM ===".

For each message, follow the instruction its owner followed when labelling, quoted verbatim:

{instruction}

Then decide one of:
- "use": "main" is the number of the one sentence that best carries the main ask, and "also" lists
  any other sentences that carry it too (repeated at the end, for example), or is empty;
- "skip", with exactly one of these reasons: {reasons}.

Write the answer file as JSON, one entry per message in file order, "sentences" copied from the
message's header:
{{"items": [{{"id": "ID", "sentences": S, "decision": "use", "main": 3, "also": [9]}},
           {{"id": "ID", "sentences": S, "decision": "skip", "reason": "..."}}]}}

Reply with only the number of entries written. Quote no message text in your reply."""


def _wrap(head: str, text: str) -> list[str]:
    flat = " ⏎ ".join(part.strip() for part in text.split("\n")).strip()  # a blank line: two ⏎
    if not flat:
        return []
    return textwrap.wrap(
        flat, WIDTH, initial_indent=head, subsequent_indent="    ", break_on_hyphens=False
    )


def render(items: list[dict[str, Any]]) -> str:
    """The messages as the page shows them: every sentence numbered, the text between sentences kept
    unnumbered, nothing about any label."""
    lines = []
    for k, c in enumerate(items, 1):
        text, at = c["text"], 0  # spans count code points, as Python indexes a str
        lines.append(f"=== ITEM {k}/{len(items)} · id {c['id']} · {len(c['sentences'])} frases ===")
        for j, (start, end) in enumerate(c["sentences"]):
            lines += _wrap("--- ", text[at:start])  # the page shows it, line breaks included
            lines += _wrap(f"[{j}] ", text[start:end]) or [f"[{j}]"]
            at = end
        lines += _wrap("--- ", text[at:])
    lines.append("=== FIM ===")
    return "\n".join(lines) + "\n"


def kept_items(
    candidates: dict[str, Any], labels: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The owner's kept dictations under Part R's rules, as pool items and with their gold. Skipped
    messages, the ones marked sensitive among them, never leave this function."""
    kept, _ = part_r.labelled(candidates, labels)
    pool = {c["id"]: c for c in candidates["items"]}
    if len(pool) != len(candidates["items"]):
        raise SystemExit("refused: two candidates share an id")
    return [pool[k["id"]] for k in kept], kept


def score(
    candidates: dict[str, Any], labels: dict[str, Any], answer: dict[str, Any]
) -> dict[str, Any]:
    """Agreement of the agent's pick with the owner's gold. A skip counts as a miss."""
    items, kept = kept_items(candidates, labels)
    got = answer.get("items")
    if not isinstance(got, list) or not all(isinstance(g, dict) for g in got):
        raise SystemExit("refused: the answer is not a list of entries")
    if [g.get("id") for g in got] != [c["id"] for c in items]:
        raise SystemExit("refused: the answer does not cover the kept dictations in order")
    hits = marked = skips = 0
    for k, (c, gold, g) in enumerate(zip(items, kept, got, strict=True), 1):
        sentences = c["sentences"]
        if g.get("sentences") != len(sentences):
            raise SystemExit(f"refused: item {k} was read with another sentence count")
        if g.get("decision") == "skip" and g.get("reason") in part_r.SKIP_REASONS:
            skips += 1
            continue
        also = g.get("also", [])
        picks = [g.get("main"), *also] if isinstance(also, list) else []
        if (
            g.get("decision") != "use"
            or not picks
            or not all(type(j) is int and 0 <= j < len(sentences) for j in picks)
        ):
            raise SystemExit(f"refused: item {k} has no valid decision")
        hits += run_arms.hit(sentences[picks[0]], gold["main"])
        marked += any(run_arms.hit(sentences[j], gold["main"]) for j in picks)
    n = len(items)
    return {
        "n": n,
        "labeller": "a fresh agent, model alias opus, with BRIEF (Amendment 7)",
        "agree": part_r.wilson(hits, n),
        "agree_any_marked": part_r.wilson(marked, n),
        "skipped": skips,
        "pass_at": PASS,
        "passed": hits >= PASS,
    }


def _reused_are_pinned() -> bool:
    for name, sha in PINNED.items():
        if part_r._sha((HERE / name).read_bytes()) != sha:
            print(f"refused: {name} is not the file the protocol pins")
            return False
    return True


def _part_r() -> tuple[dict[str, Any], dict[str, Any]]:
    part_r._check_parser()
    candidates = json.loads((part_r.PRIVATE / "candidates.json").read_text(encoding="utf-8"))
    labels = json.loads((part_r.PRIVATE / "labels.json").read_text(encoding="utf-8"))
    return candidates, labels


def cmd_prepare(args: argparse.Namespace) -> int:
    if INPUT.exists() or ANSWER.exists():
        print("refused: the input is written once; the labelling may be under way")
        return 2
    if not _reused_are_pinned():
        return 2
    items, _ = kept_items(*_part_r())
    for folder in (PRIVATE.parent, PRIVATE):
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
    text = render(items)
    part_r._write_private(INPUT, text)
    brief = BRIEF.format(
        input=INPUT,
        answer=ANSWER,
        n=len(items),
        instruction=part_r.INSTRUCTION,
        reasons=", ".join(f'"{r}"' for r in part_r.SKIP_REASONS),
    )
    part_r._write_private(PRIVATE / "brief.txt", brief + "\n")
    lines = text.splitlines()
    print(json.dumps({"items": len(items), "lines": len(lines), "longest": max(map(len, lines))}))
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    if OUT.exists():
        print("refused: stats_r_claude.json exists; the check runs once")
        return 2
    if not _reused_are_pinned():
        return 2
    candidates, labels = _part_r()
    answer_bytes = ANSWER.read_bytes()
    summary = {
        **score(candidates, labels, json.loads(answer_bytes)),
        "input_sha256": part_r._sha(INPUT.read_bytes()),
        "answer_sha256": part_r._sha(answer_bytes),
    }
    part_r._write_private(OUT, json.dumps(summary, indent=1, ensure_ascii=False) + "\n", mode=0o644)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(required=True)
    sub.add_parser("prepare").set_defaults(func=cmd_prepare)
    sub.add_parser("score").set_defaults(func=cmd_score)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
