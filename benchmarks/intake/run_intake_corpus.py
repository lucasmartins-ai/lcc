#!/usr/bin/env python3
"""Intake on the versioned corpus: dictation detection accuracy, readiness, token savings.

    python benchmarks/intake/run_intake_corpus.py          # print the table
    python benchmarks/intake/run_intake_corpus.py --json   # machine-readable

Token counts come from ``lcc.token_budget`` for ``--model`` (approximate when tiktoken has no
exact encoding for it; the method is printed). Savings are speech cleaning only, on the cases
the corpus marks as dictation. No network, deterministic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("LCC_DISABLE_NETWORK", "1")

from lcc.intake import LccIntake  # noqa: E402
from lcc.token_budget import count_tokens  # noqa: E402

CORPUS = ROOT / "tests" / "corpus" / "intake" / "v1.json"


def measure(model: str) -> dict[str, object]:
    cases = json.loads(CORPUS.read_text("utf-8"))["cases"]
    detected_ok = readiness_ok = 0
    distribution: Counter[str] = Counter()
    raw_tokens = cleaned_tokens = spans = prose_raw = prose_cleaned = 0
    method = ""
    for case in cases:
        result = LccIntake(optimize_context=False).process(case["text"])
        detected = bool(result.dictation and result.dictation.detected)
        detected_ok += detected is case["dictation"]
        readiness_ok += result.parsed.readiness.value == case["readiness"]
        distribution[result.parsed.readiness.value] += 1
        if case["dictation"]:
            cleaned = result.speech_cleaning.text if result.speech_cleaning else case["text"]
            before = count_tokens(case["text"], model)
            after = count_tokens(cleaned, model).value
            raw_tokens += before.value
            cleaned_tokens += after
            if "-->" not in case["text"]:  # plain dictation, no SRT/VTT timing to strip
                prose_raw += before.value
                prose_cleaned += after
            spans += len(result.speech_cleaning.removals) if result.speech_cleaning else 0
            method = before.method.value
    return {
        "cases": len(cases),
        "detection_accuracy": round(detected_ok / len(cases), 3),
        "readiness_accuracy": round(readiness_ok / len(cases), 3),
        "readiness_distribution": dict(sorted(distribution.items())),
        "dictation_tokens_before": raw_tokens,
        "dictation_tokens_after": cleaned_tokens,
        "dictation_token_savings": round(1 - cleaned_tokens / raw_tokens, 3) if raw_tokens else 0.0,
        "prose_dictation_token_savings": round(1 - prose_cleaned / prose_raw, 3)
        if prose_raw
        else 0.0,
        "removed_spans": spans,
        "token_count_method": method,
        "model": model,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = measure(args.model)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            print(f"{key:<26} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
