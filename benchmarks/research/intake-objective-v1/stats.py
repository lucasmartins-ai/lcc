#!/usr/bin/env python3
"""H1 to H4 of intake-objective-v1 from the arm results (PROTOCOL.md, Hypotheses and pass criteria).

    python benchmarks/research/intake-objective-v1/stats.py --split test

Reads ``results_<split>.json`` (``run_arms.py``) and, when present, ``results_dj_<split>.json``
(``run_dj.py``). Intervals are a paired cluster bootstrap: 10,000 resamples of whole bases with
replacement, seed 20261116; each resample's statistic is the mean per-case difference over every
case of the drawn bases, and the interval is its 2.5th and 97.5th percentiles. Writes
``stats_<split>.json``: ids and numbers, never case text.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from lcc.intake.parser import sentence_role

HERE = Path(__file__).resolve().parent
SEED = 20261116
RESAMPLES = 10_000
H1_MARGIN = 0.15
H3_SLACK = 0.05


def cluster_interval(diffs: dict[str, list[float]]) -> dict[str, float]:
    """Point estimate and 95% percentile interval of the mean of ``diffs`` (per base, per case)."""
    bases = sorted(diffs)
    every = [d for base in bases for d in diffs[base]]
    rng = random.Random(SEED)
    means = []
    for _ in range(RESAMPLES):
        drawn = [d for _ in bases for d in diffs[rng.choice(bases)]]
        means.append(sum(drawn) / len(drawn))
    cuts = statistics.quantiles(means, n=40, method="inclusive")  # cuts[0] = 2.5%, cuts[-1] = 97.5%
    return {
        "diff": round(sum(every) / len(every), 4),
        "lo": round(cuts[0], 4),
        "hi": round(cuts[-1], 4),
    }


def _paired(rows: list[dict[str, Any]], base: dict[str, str], a: str, b: str) -> dict[str, float]:
    diffs: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        diffs[base[r["id"]]].append(float(r[a]) - float(r[b]))
    return cluster_interval(diffs)


def _rate(rows: list[dict[str, Any]], arm: str) -> float:
    return round(sum(r[arm] for r in rows) / len(rows), 4) if rows else 0.0


def analyse(split: str) -> dict[str, Any]:
    cases = {c["id"]: c for c in json.loads((HERE / "cases.json").read_text())["cases"]}
    result = json.loads((HERE / f"results_{split}.json").read_text(encoding="utf-8"))
    rows = result["rows"]
    dj_path = HERE / f"results_dj_{split}.json"
    dj = json.loads(dj_path.read_text(encoding="utf-8")) if dj_path.exists() else None
    if dj:
        by_id = {r["id"]: r for r in dj["rows"]}
        rows = [{**r, "DJ": by_id[r["id"]]["DJ"]} for r in rows]
    base = {i: c["base"] for i, c in cases.items()}
    arms = ["A0", "A1", "D_hit", *(["DJ"] if dj else [])]

    def group(pred: Any) -> dict[str, Any]:
        sel = [r for r in rows if pred(r)]
        return {"n": len(sel), **{arm: _rate(sel, arm) for arm in arms}}

    # Codex's recap phrasings that the parser reads as a rule (Amendment 1, deviation 2), found
    # from the parser's role of the recap span, never by reading the text.
    misread = {
        r["id"]
        for r in rows
        if r["family"] == "restate"
        and sentence_role(cases[r["id"]]["text"][slice(*cases[r["id"]]["main"][1])]) != "ask"
    }
    first = [r for r in rows if r["family"] == "first"]
    h1 = _paired(rows, base, "D_hit", "A0")
    out: dict[str, Any] = {
        "split": split,
        "n": len(rows),
        "bases": len({base[r["id"]] for r in rows}),
        "hit@1": group(lambda r: True),
        "D_hit3": _rate(rows, "D_hit3"),
        "by_family": {
            f: group(lambda r, f=f: r["family"] == f) for f in sorted({r["family"] for r in rows})
        },
        "by_k": {str(k): group(lambda r, k=k: r["k"] == k) for k in sorted({r["k"] for r in rows})},
        "by_lang": {
            g: group(lambda r, g=g: r["lang"] == g) for g in sorted({r["lang"] for r in rows})
        },
        # marker and restate cases: Codex wrote the test phrasings, the author the dev ones.
        ("codex_phrasings" if split == "test" else "author_phrasings"): group(
            lambda r: r["phrasing"] is not None
        ),
        "recap_read_as_rule": {"ids": sorted(misread), **group(lambda r: r["id"] in misread)},
        "ablations": {
            name: _rate(rows, name) for name in sorted(k for k in rows[0] if k.startswith("D-"))
        },
        "D_minus_A0": h1,
        "D_minus_A1": _paired(rows, base, "D_hit", "A1"),
        "H1": h1["diff"] >= H1_MARGIN and h1["lo"] > 0,
        "H3": _rate(first, "D_hit") >= _rate(first, "A0") - H3_SLACK,
        # A0, A1 and DJ keep every sentence (Amendment 2, Ask recall); D's stash is checked here.
        "H4": result["summary"]["D_ask_recall_min"] == 1.0 and result["summary"]["D_rebuilds_all"],
        "D_summary": {k: v for k, v in result["summary"].items() if k.startswith(("D_", "asks"))},
    }
    if dj:
        out["DJ_minus_D"] = _paired(rows, base, "DJ", "D_hit")
        out["H2"] = out["DJ_minus_D"]["lo"] > 0
        out["DJ_summary"] = dj["summary"]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    args = parser.parse_args(argv)
    out = analyse(args.split)
    (HERE / f"stats_{args.split}.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
