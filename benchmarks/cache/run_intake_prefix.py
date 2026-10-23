#!/usr/bin/env python3
"""Intake prompt prefix stability: two different requests must share the whole static template.

A prompt cache reuses a byte-identical prefix. ``lcc intake`` renders a static template
(role, constraints, definition of done) plus per-request content (the payload, the question,
readiness, reasons, assumptions). This check renders pairs of corpus requests with every
template and asserts that the bytes before the first per-request byte are identical.

    python benchmarks/cache/run_intake_prefix.py          # print the table
    python benchmarks/cache/run_intake_prefix.py --check  # exit 1 if a pair diverges early

No network, deterministic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("LCC_DISABLE_NETWORK", "1")

from lcc.intake import LccIntake  # noqa: E402
from lcc.prompt_builder import available_templates  # noqa: E402

CORPUS = ROOT / "tests" / "corpus" / "intake" / "v1.json"
PAIRS = [("en_typed_clear", "pt_whisper_multi_ask"), ("en_typed_vague", "pt_srt_transcript")]


def _shared(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


def measure() -> list[dict[str, object]]:
    cases = {c["id"]: c["text"] for c in json.loads(CORPUS.read_text("utf-8"))["cases"]}
    rows: list[dict[str, object]] = []
    for template in available_templates():
        for left, right in PAIRS:
            a = LccIntake(template_name=template).process(cases[left])
            b = LccIntake(template_name=template).process(cases[right])
            # The first per-request byte: the earliest of the cleaned payload or the question.
            payload_a = a.compression.compressed_text if a.compression else cases[left]
            first_dynamic = min(
                a.formatted_prompt.find(s)
                for s in (payload_a.strip()[:20], a.parsed.brief.objective[:20])
                if s and a.formatted_prompt.find(s) >= 0
            )
            shared = _shared(a.formatted_prompt, b.formatted_prompt)
            rows.append(
                {
                    "template": template,
                    "pair": f"{left} / {right}",
                    "prompt_chars": len(a.formatted_prompt),
                    "static_chars": first_dynamic,
                    "shared_chars": shared,
                    "shared_share": round(shared / len(a.formatted_prompt), 3),
                    "ok": shared >= first_dynamic,
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 on a violation")
    args = parser.parse_args(argv)
    rows = measure()
    print(f"{'template':<20} {'pair':<46} {'shared/static/prompt chars':>28}  ok")
    for r in rows:
        nums = f"{r['shared_chars']}/{r['static_chars']}/{r['prompt_chars']}"
        print(f"{r['template']:<20} {r['pair']:<46} {nums:>28}  {r['ok']}")
    bad = [r for r in rows if not r["ok"]]
    if args.check and bad:
        print(
            f"FAIL: {len(bad)} pair(s) diverge before the first per-request byte", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
