#!/usr/bin/env python3
"""Part R2 of intake-objective-v1: more of the owner's real dictations (PROTOCOL.md, Amendment 6).

    python benchmarks/research/intake-objective-v1/part_r2.py collect
    python benchmarks/research/intake-objective-v1/part_r2.py run [--labels PATH]

``collect`` draws a second pool from the owner's Claude Code transcripts: Part R's text rule with a
200-word floor, from Part R's tagged rows plus the untagged rows of Claude desktop versions that
tagged no row, minus every Part R candidate. It writes the pool and Part R's labelling page to
``~/.lcc-private/intake-objective-v1-r2/`` and runs no arm. ``run`` scores the frozen A0, A1 and
D on the labelled dictations, overall, by stratum and by split, with D against A0 paired. Texts
and per-case rows stay private; the repository gets ``stats_r2.json``. DJ is not here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import part_r  # noqa: E402
import run_arms  # noqa: E402
from run_arms import HERE, WEIGHTS  # noqa: E402

from lcc.intake import parser as intake_parser  # noqa: E402

#: part_r.py as Amendment 4 pins it: this file reuses its filter, labelling rules, scoring and page.
PART_R_SHA256 = "cc0da0564f8904f3b8094c737bdaa9fabf02af39bcbc0e659a5a5d17c7699659"
PRIVATE = part_r.PRIVATE.with_name("intake-objective-v1-r2")
PART_R_POOL = part_r.PRIVATE / "candidates.json"
PART_R_POOL_SHA256 = "d8f0691299647f1da608e6c2a8dc86dd1a5643dd7a1d117852323c3513131b88"
OUT = HERE / "stats_r2.json"
SEED = 20261118
MIN_WORDS = 200
MIN_KEPT = 60  # below this the intervals are too wide for the run to be worth it
#: In the owner's transcripts no Claude desktop row from a version before this one carries an
#: origin tag, so there a missing tag says nothing; from it on, rows the owner types are tagged and
#: an untagged row is the app's or a script's. An old untagged row may still be automated: the
#: owner skips it while labelling ("não foi ditado").
TAGGED_FROM = (2, 1, 187)
STRATA = {"band": ("300+", "200-299"), "source": ("tagged", "untagged"), "split": ("dev", "test")}
PAGE = (
    part_r.PAGE.replace("<title>Part R: rótulos</title>", "<title>Part R2: rótulos</title>")
    .replace("Baixar labels.json", "Baixar labels_r2.json")
    .replace('a.download = "labels.json"', 'a.download = "labels_r2.json"')
    # The page counts kept messages against no target, so it never nudges toward "use".
    .replace(
        '"Usados: " + n + " de " + D.goal + " | decididos: "', '"Usados: " + n + " | decididos: "'
    )
)


def _version(entry: dict[str, Any]) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in str(entry.get("version", "")).split("."))
    except ValueError:
        return None


def source(entry: dict[str, Any]) -> str | None:
    """``"tagged"`` for a row Part R takes, ``"untagged"`` for a Claude desktop row from a version
    that tagged no row, else None."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return None
    if entry.get("isCompactSummary"):
        return None
    origin = entry.get("origin")
    if entry.get("turnOrigin") == "human" or (
        isinstance(origin, dict) and origin.get("kind") == "human"
    ):
        return "tagged"
    if (
        entry.get("turnOrigin") is None
        and origin is None
        and entry.get("entrypoint") == "claude-desktop"
    ):
        version = _version(entry)
        if version is not None and version < TAGGED_FROM:
            return "untagged"
    return None


def candidate(entry: dict[str, Any]) -> tuple[str | None, str, str | None]:
    """``(text, why, source)``: Part R's text rule (app reminders stripped at either end, any other
    markup drops the message) with Part R2's floor and sources."""
    src = source(entry)
    message = entry.get("message") or {}
    text = part_r._text(message.get("content")) if src and message.get("role") == "user" else None
    if not text:
        return None, "not a typed message", None
    while True:
        stripped = part_r._TRAILING.sub("", part_r._LEADING.sub("", text, count=1), count=1)
        if stripped == text:
            break
        text = stripped
    if len(text.split()) < MIN_WORDS:
        return None, "short", src
    if part_r._MARKUP.search(text):
        return None, "markup", src
    return text, "ok", src


def collect(transcripts: Path, out: Path, exclude: set[str]) -> dict[str, int]:
    """Write ``candidates.json`` and ``label.html`` to ``out`` and return the filter counts. Runs
    no arm. Refuses when a pool exists: a new pool would reorder the one being labelled."""
    if (out / "candidates.json").exists():
        raise SystemExit("refused: candidates.json exists; the pool is drawn once")
    part_r._check_parser()
    pool: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for path in sorted(transcripts.glob("*/*.jsonl")):
        with path.open(
            encoding="utf-8", errors="replace"
        ) as lines:  # line by line: files are large
            for line in lines:
                if '"user"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                text, why, src = candidate(entry)
                if why != "not a typed message":
                    counts[why] += 1
                if text is None:
                    continue
                try:
                    sha = part_r._sha(text)
                except UnicodeEncodeError:  # a lone surrogate: no stable hash, left out
                    counts["unencodable"] += 1
                    continue
                if sha in exclude:
                    counts["in Part R"] += 1
                    continue
                if sha in pool:
                    counts["duplicate"] += 1
                    continue
                words = len(text.split())
                spans = [item.spans[0] for item in intake_parser.parse_intake(text).extract]
                pool[sha] = {
                    "id": sha[:12],
                    "sha256": sha,
                    "session": entry.get("sessionId", ""),
                    "timestamp": entry.get("timestamp", ""),
                    "words": words,
                    "source": src,
                    "band": "300+" if words >= 300 else "200-299",
                    "split": ("dev", "test")[int(sha, 16) % 2],  # fixed before any label
                    "text": text,
                    "sentences": [list(s) for s in spans],
                }
    items = sorted(pool.values(), key=lambda c: c["sha256"])
    random.Random(SEED).shuffle(items)  # the order the owner works through, top down
    counts["candidates"] = len(items)
    for folder in (out.parent, out):
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
    meta = {
        "seed": SEED,
        "min_words": MIN_WORDS,
        "parser_sha256": part_r.PARSER_SHA256,
        "counts": dict(counts),
    }
    part_r._write_private(
        out / "candidates.json", json.dumps({**meta, "items": items}, ensure_ascii=False, indent=1)
    )
    pool_id = part_r._sha("\n".join(c["sha256"] for c in items))[:16]
    page = {"instruction": part_r.INSTRUCTION, "reasons": part_r.SKIP_REASONS, "pool": pool_id}
    # The goal is the whole pool: the page says "done" only when every message is decided.
    page.update(goal=len(items), items=items)
    # No "<" may reach the script block raw: message text could otherwise end or reopen it.
    payload = json.dumps(page, ensure_ascii=False).replace("<", "\\u003c")
    part_r._write_private(out / "label.html", PAGE.replace("__DATA__", payload))
    return dict(counts)


def labelled(
    candidates: dict[str, Any], labels: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Part R's labelling rules (top down with no gap, listed skip reasons, gold sentences from the
    page) with Part R2's size rule in place of Part R's 20 to 30."""
    saved, part_r.TARGET = part_r.TARGET, (0, len(candidates["items"]))
    try:
        kept, skips = part_r.labelled(candidates, labels)
    finally:
        part_r.TARGET = saved
    if len(kept) < MIN_KEPT:
        raise SystemExit(f"refused: {len(kept)} dictations kept, Part R2 needs {MIN_KEPT}")
    return kept, skips


def mcnemar(b: int, c: int) -> float:
    """Exact two-sided McNemar p: the binomial test on the ``b + c`` discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return float(f"{min(1.0, 2 * tail):.4g}")  # significant figures: a small p never reads as 0


def _arms(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    arms = ("A0", "A1", "D", "D_hit3")
    return {"n": n, **({a: part_r.wilson(sum(r[a] for r in rows), n) for a in arms} if n else {})}


def summarise(rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    """``part_r.score``'s summary, plus D against A0 paired and every stratum on its own."""
    d_only = sum(r["D"] and not r["A0"] for r in rows)
    a0_only = sum(r["A0"] and not r["D"] for r in rows)
    return {
        **summary,
        "D_vs_A0": {
            "D_only": d_only,
            "A0_only": a0_only,
            "p_exact_mcnemar": mcnemar(d_only, a0_only),
        },
        "by": {
            f"{key}={value}": _arms([r for r in rows if r[key] == value])
            for key, values in STRATA.items()
            for value in values
        },
        # Part R took the tagged 300+ messages up to its draw, so band and source overlap: crossed.
        "by_band_and_source": {
            f"band={band},source={src}": _arms(
                [r for r in rows if r["band"] == band and r["source"] == src]
            )
            for band in STRATA["band"]
            for src in STRATA["source"]
        },
    }


def _part_r_is_pinned() -> bool:
    if part_r._sha((HERE / "part_r.py").read_bytes()) == PART_R_SHA256:
        return True
    print("refused: part_r.py is not the file Amendment 4 pins")
    return False


def cmd_collect(args: argparse.Namespace) -> int:
    if not _part_r_is_pinned():
        return 2
    raw = PART_R_POOL.read_bytes()
    if part_r._sha(raw) != PART_R_POOL_SHA256:
        print("refused: Part R's candidates.json is not the pool Amendment 4 records")
        return 2
    exclude = {c["sha256"] for c in json.loads(raw)["items"]}
    print(json.dumps(collect(part_r.TRANSCRIPTS, PRIVATE, exclude)))
    print(f"label page: {PRIVATE / 'label.html'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if OUT.exists():
        print("refused: stats_r2.json exists; Part R2 runs once")
        return 2
    if not _part_r_is_pinned():
        return 2
    if run_arms._code_sha256() != run_arms.FROZEN_OBJECTIVE_SHA256 or (
        run_arms.run("dev", WEIGHTS)["summary"]["d_sha256"] != run_arms.FROZEN_D_SHA256
    ):
        print("refused: D is not the frozen D (code or dev output differ from Amendment 2)")
        return 2
    part_r._check_parser()
    pool_bytes = (PRIVATE / "candidates.json").read_bytes()
    labels_bytes = Path(args.labels).read_bytes()
    candidates = json.loads(pool_bytes)
    kept, skips = labelled(candidates, json.loads(labels_bytes))
    rows, summary = part_r.score(kept)
    strata = {c["id"]: c for c in candidates["items"]}
    for row in rows:
        row.update({key: strata[row["id"]][key] for key in STRATA})
    summary = {
        "pool": candidates["counts"],
        "candidates_sha256": part_r._sha(pool_bytes),
        "labels_sha256": part_r._sha(labels_bytes),
        "skipped": skips,
        **summarise(rows, summary),
    }
    part_r._write_private(
        PRIVATE / "results_r2.json", json.dumps({"rows": rows, "summary": summary}, indent=1)
    )
    part_r._write_private(OUT, json.dumps(summary, indent=1, ensure_ascii=False) + "\n", mode=0o644)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(required=True)
    sub.add_parser("collect").set_defaults(func=cmd_collect)
    run = sub.add_parser("run")
    run.add_argument("--labels", default=str(PRIVATE / "labels_r2.json"))
    run.set_defaults(func=cmd_run)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
