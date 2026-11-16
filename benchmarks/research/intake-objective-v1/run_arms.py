#!/usr/bin/env python3
"""Run the offline arms of intake-objective-v1 (A0, A1, D and its ablations) on one split.

    python benchmarks/research/intake-objective-v1/run_arms.py run --split dev
    python benchmarks/research/intake-objective-v1/run_arms.py tune

``tune`` searches D's weights on the dev split only. ``run --split test`` refuses unless D's code
and its whole dev output match the hashes frozen by amendment (``FROZEN_OBJECTIVE_SHA256``,
``FROZEN_D_SHA256``), so the test run uses the D that was frozen. Results carry case ids, spans
and numbers, never case text.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from lcc.intake import objective
from lcc.intake.objective import SIGNALS, WEIGHTS, Analysis, ObjectivePick, analyse, choose
from lcc.token_budget.counters import approximate_token_count

HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "cases.json"
#: Set by the amendment that froze D: the sha256 of ``objective.py`` and of D's dev output
#: (``_fingerprint``). Empty means D is not frozen.
FROZEN_OBJECTIVE_SHA256 = "80448a328bf426f9e58294de1621dbcdcf1a5b40826a58fdd7d26be81d802431"
FROZEN_D_SHA256 = "d1c870a56de54d9534f38a1ef3e0fbd89426a2018bb515d45a4acd1f80f6a347"
GRID = (0.0, 0.5, 1.0, 2.0)

Span = tuple[int, int]


def load(split: str) -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    return [c for c in cases if c["split"] == split]


def _covers(span: Span | list[int], gold: list[int]) -> bool:
    """``span`` overlaps the gold span by at least half of the gold span."""
    return min(span[1], gold[1]) - max(span[0], gold[0]) >= (gold[1] - gold[0]) / 2


def hit(span: Span | None, golds: list[list[int]]) -> bool:
    return span is not None and any(_covers(span, g) for g in golds)


def _baselines(a: Analysis) -> tuple[Span | None, Span | None]:
    """A0 (first ask in input order) and A1 (last ask)."""
    asks = [a.spans[i] for i, role in enumerate(a.roles) if role == "ask"]
    return (asks[0], asks[-1]) if asks else (None, None)


def score_d(case: dict[str, Any], a: Analysis, pick: ObjectivePick) -> dict[str, Any]:
    """D's hit, hit@3, recall, rebuild, brief ratio and links for one case."""
    text, blocks = case["text"], pick.blocks
    top3 = [blocks[i].span for i in pick.ranking[:3]]
    home = pick.ranking[0] if pick.ranking else None
    brief_ids = sorted(([home] if home is not None else []) + pick.linked)
    kept = brief_ids + pick.stash
    rebuilt = "".join(text[slice(*blocks[i].span)] for i in sorted(kept))
    gold_asks = [s for group in case["asks"] for s in group]
    in_kept = [any(_covers(blocks[i].span, g) for i in kept) for g in gold_asks]
    ask_sentences = [a.spans[i] for i, role in enumerate(a.roles) if role == "ask"]
    labelled = [any(_covers(s, g) for s in ask_sentences) for g in gold_asks]
    brief_text = "".join(text[slice(*blocks[i].span)] for i in brief_ids)
    linked = [
        a.spans[j]
        for i in brief_ids
        for j in blocks[i].sentences
        if a.spans[j] != pick.objective_span and not hit(a.spans[j], case["main"])
    ]
    support = case["support"]
    return {
        "hit": hit(pick.objective_span, case["main"]),
        "hit3": any(hit(s, case["main"]) for s in top3),
        "fallback": pick.fallback,
        "ask_recall": sum(in_kept) / len(gold_asks),
        "asks_labelled": sum(labelled) / len(gold_asks),
        "rebuilds": rebuilt == text and len(kept) == len(blocks),
        "brief_ratio": approximate_token_count(brief_text) / approximate_token_count(text),
        "linked": len(linked),
        "linked_support": sum(any(_covers(s, g) for g in support) for s in linked),
        "support": len(support),
        "support_linked": sum(any(_covers(s, g) for s in linked) for g in support),
        "blocks": len(blocks),
        "eligible": len(pick.ranking),
    }


def run(split: str, weights: dict[str, float]) -> dict[str, Any]:
    rows, trace = [], []
    for case in load(split):
        t0 = time.perf_counter()
        a = analyse(case["text"])
        pick = choose(a, weights)
        ms = (time.perf_counter() - t0) * 1000
        a0, a1 = _baselines(a)
        row = {
            "id": case["id"],
            "family": case["family"],
            "k": case["k"],
            "lang": case["lang"],
            "phrasing": case["phrasing"],
            "A0": hit(a0, case["main"]),
            "A1": hit(a1, case["main"]),
            "D_span": list(pick.objective_span),
            "D_ms": round(ms, 3),
            **{f"D_{k}": v for k, v in score_d(case, a, pick).items()},
        }
        ablated = [choose(a, weights, drop=name).objective_span for name in SIGNALS]
        for name, span in zip(SIGNALS, ablated, strict=True):
            row[f"D-{name}"] = hit(span, case["main"])
        rows.append(row)
        blocks = [b.span for b in pick.blocks]
        trace.append([case["id"], pick.objective_span, blocks, pick.ranking, pick.linked, ablated])
    summary = summarise(rows)
    summary["d_sha256"] = _fingerprint(weights, trace)
    return {"split": split, "weights": weights, "rows": rows, "summary": summary}


def _fingerprint(weights: dict[str, float], trace: list[list[Any]]) -> str:
    """sha256 of the weights and, per case, every D output a metric reads: the objective span,
    the block spans, the ranking, the linked blocks (the rest is the stash) and the ablations'
    objective spans."""
    return hashlib.sha256(json.dumps([weights, trace]).encode()).hexdigest()


def _code_sha256() -> str:
    return hashlib.sha256(Path(objective.__file__).read_bytes()).hexdigest()


ARMS = ["A0", "A1", "D_hit", *(f"D-{name}" for name in SIGNALS)]


def _table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    out: dict[str, Any] = {"n": n}
    for arm in [*ARMS, "D_hit3"]:
        out[arm] = round(sum(r[arm] for r in rows) / n, 4)
    return out


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[f"family={r['family']}"].append(r)
        by[f"k={r['k']}"].append(r)
        by[f"lang={r['lang']}"].append(r)
    hits = [r for r in rows if r["D_hit"]]
    linked = sum(r["D_linked"] for r in hits)
    support = sum(r["D_support"] for r in hits)
    return {
        "total": _table(rows),
        **{key: _table(group) for key, group in sorted(by.items())},
        "D_ask_recall_min": min(r["D_ask_recall"] for r in rows),
        "D_rebuilds_all": all(r["D_rebuilds"] for r in rows),
        "asks_labelled_mean": round(sum(r["D_asks_labelled"] for r in rows) / len(rows), 4),
        "D_brief_ratio_mean": round(sum(r["D_brief_ratio"] for r in rows) / len(rows), 4),
        "D_link_precision_on_hits": round(
            sum(r["D_linked_support"] for r in hits) / linked if linked else 0.0, 4
        ),
        "D_link_recall_on_hits": round(
            sum(r["D_support_linked"] for r in hits) / support if support else 0.0, 4
        ),
        "D_fallbacks": sum(r["D_fallback"] for r in rows),
        "D_ms_mean": round(sum(r["D_ms"] for r in rows) / len(rows), 3),
        "D_ms_max": round(max(r["D_ms"] for r in rows), 3),
    }


def cmd_run(args: argparse.Namespace) -> int:
    if args.split == "test":
        # ponytail: the hashes pin objective.py and D's dev behaviour; the parser and scorer it
        # imports are pinned by their shas in Amendment 2 and by any change to D's dev output.
        frozen = _code_sha256() == FROZEN_OBJECTIVE_SHA256
        if not frozen or run("dev", WEIGHTS)["summary"]["d_sha256"] != FROZEN_D_SHA256:
            print("refused: D is not the frozen D (code or dev output differ from Amendment 2)")
            return 2
    result = run(args.split, WEIGHTS)
    out = HERE / f"results_{args.split}.json"
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=1))
    return 0


def cmd_tune(_: argparse.Namespace) -> int:
    """Grid search on dev: best hit@1, then hit@3, then the smallest total weight."""
    analysed = [(c, analyse(c["text"])) for c in load("dev")]
    scored = []
    for combo in itertools.product(GRID, repeat=len(SIGNALS)):
        if not any(combo):
            continue
        weights = dict(zip(SIGNALS, combo, strict=True))
        h1 = h3 = 0
        for case, a in analysed:
            pick = choose(a, weights)
            h1 += hit(pick.objective_span, case["main"])
            h3 += any(hit(pick.blocks[i].span, case["main"]) for i in pick.ranking[:3])
        scored.append((h1, h3, -sum(combo), combo))
    scored.sort(key=lambda s: (-s[0], -s[1], -s[2], s[3]))
    for h1, h3, _, combo in scored[:10]:
        print(f"hit@1 {h1}/{len(analysed)}  hit@3 {h3}  {dict(zip(SIGNALS, combo, strict=True))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--split", choices=["dev", "test"], required=True)
    p_run.set_defaults(func=cmd_run)
    sub.add_parser("tune").set_defaults(func=cmd_tune)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
