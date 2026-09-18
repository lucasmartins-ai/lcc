#!/usr/bin/env python3
"""Answer-level evaluation: original vs compacted context, deterministic checks.

Compression ratio is not a quality metric. This script answers the only question that
matters for §15: does the compacted context still contain everything needed to produce
a correct answer? For each adversarial case it:

1. builds the corpus (`adversarial_cases.build_corpus`),
2. compacts it with the real `compact_context` (mechanical by default, offline),
3. scores both versions by literal required-fact recall (critical-block prefixes plus
   the case's own `checks` regexes — the same assertions the adversarial suite uses),
4. reports `quality_delta = recall(compacted) - recall(original)` per case.

A case where tokens decrease BUT recall decreases is a REGRESSION and fails the run.
Run: `python3 benchmarks/research/run_answer_eval.py [--pressure N] [--provider mechanical]`.
"""

from __future__ import annotations

# ruff: noqa: I001, E402 — sys.path bootstrap must precede sibling imports.
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from adversarial_cases import CASES, build_corpus  # noqa: E402
from lcc.relevance import RelevanceCompactionRequest, compact_context  # noqa: E402


def _recall(text: str, case) -> tuple[float, list[str]]:
    required = case.must_survive or tuple(range(len(case.critical)))
    hits = 0
    missing: list[str] = []
    for i in required:
        needle = case.critical[i].strip()[:60]
        if needle in text:
            hits += 1
        else:
            missing.append(f"critical[{i}]")
    check_failures = []
    for name, pattern, expectation in case.checks:
        found = bool(re.search(pattern, text, re.I | re.S))
        if (expectation == "present") != found:
            check_failures.append(name)
    total = len(required) + len(case.checks)
    good = hits + (len(case.checks) - len(check_failures))
    recall = (good / total) if total else 1.0
    return round(recall, 4), missing + check_failures


def evaluate_case(case, *, pressure: int, provider: str) -> dict:
    corpus = build_corpus(case, pressure=pressure)
    result = compact_context(
        RelevanceCompactionRequest(text=corpus, question=case.question, provider=provider)
    )
    original_recall, original_missing = _recall(corpus, case)
    compacted_recall, compacted_missing = _recall(result.compacted_text, case)
    return {
        "id": case.id,
        "hazard": case.hazard,
        "tokens_before": result.report.tokens_before,
        "tokens_after": result.report.tokens_after,
        "original_recall": original_recall,
        "compacted_recall": compacted_recall,
        "quality_delta": round(compacted_recall - original_recall, 4),
        "regression": compacted_recall < original_recall,
        "compacted_missing": compacted_missing,
        "original_missing": original_missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pressure", type=int, default=1)
    parser.add_argument("--provider", default="mechanical")
    args = parser.parse_args()
    rows = [evaluate_case(case, pressure=args.pressure, provider=args.provider) for case in CASES]
    regressions = [r for r in rows if r["regression"]]
    for row in rows:
        flag = "REGRESSION" if row["regression"] else "ok"
        print(
            f"{row['id']:28} tok {row['tokens_before']:6}->{row['tokens_after']:6} "
            f"recall {row['original_recall']:.2f}->{row['compacted_recall']:.2f} "
            f"delta {row['quality_delta']:+.2f} {flag}"
        )
    print(f"\n{len(rows)} cases, {len(regressions)} regressions")
    out = Path(__file__).resolve().parent / "answers_after" / "answer_eval.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
