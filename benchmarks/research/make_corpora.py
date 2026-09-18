#!/usr/bin/env python3
"""Benchmark corpus factory for LCC research.

Builds realistic LookADev-shaped context dossiers with:
  * a STABLE PREFIX (system contract + reference facts) -- the KV-cache-resident region
  * a cache-break marker
  * VOLATILE TAIL (tool output, logs, chatter) -- the prunable region
  * GROUND TRUTH facts (must survive any transform)
  * DISTRACTORS (noise that must not be surfaced as an answer)

Deterministic: same seed -> byte-identical corpora.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent / "corpora"

PREFIX = """SYSTEM CONTRACT (stable reference, must never be dropped)
You are the LookADev delivery analyst. Answer strictly from the evidence in this dossier.
Billing anchor: Tier 1 Express is 5.5k-8.5k BRL (1.4k-2.2k GBP); Tier 2 is 15k-32k BRL.
Split: 50 percent on signature, 50 percent on delivery.
Bristol service anchor: LookADev, Bristol BS4 4BX, +44 7356 026050.
Never invent figures that are not present in the evidence below.
"""

# Ground truth: exactly one block carries each fact. A transform that drops one of these
# breaks the downstream answer, which is what the marker-recall metric detects.
GROUND_TRUTH = [
    "GROUND TRUTH A: The clinic booking widget loses 63 percent of mobile visitors before the second step of the form.",
    "GROUND TRUTH B: p75 mobile load time on the treatment landing page is 4.2 seconds on a throttled 3G profile.",
    "GROUND TRUTH C: 41 percent of inbound WhatsApp messages to the clinic arrive outside 09:00-18:00 opening hours.",
    "GROUND TRUTH D: The practice has 3 chairs, 2 of which sit idle after 17:00 on weekdays.",
    "GROUND TRUTH E: Front desk currently re-types every booking into a paper diary, averaging 4 minutes per booking.",
]

DISTRACTORS = [
    "DISTRACTOR 1 (not evidence, ignore): a competitor blog claims a 300 percent revenue lift after a redesign.",
    "DISTRACTOR 2 (not evidence, ignore): an unrelated vendor promises 12x ROI on an AI chatbot.",
]

TOOLS = [
    "TOOL OUTPUT {i}: mobile audit run {i} returned HTTP 200, 41 kB HTML, 0 console errors, viewport meta present, 12 third-party scripts blocking first paint.",
    "TOOL OUTPUT {i}: lighthouse run {i} scored performance {p}/100 on mobile emulation with 6 render-blocking resources.",
    "TOOL OUTPUT {i}: crawl pass {i} found 38 internal links, 4 broken, 2 redirect chains longer than 3 hops.",
    "TOOL OUTPUT {i}: form trace {i} recorded {f} field abandonment events across the booking flow.",
]

LOGS = [
    "LOG {i}: npm WARN deprecated legacy-form-widget@1.0.{i} this package is no longer maintained and will be removed in a future release. Please migrate to a supported alternative.",
    "LOG {i}: queue worker heartbeat ok in {m}ms, backlog {b} jobs, retry budget untouched, no dead letters in the last window.",
    "LOG {i}: cron job lead-sync finished with {b} records processed and {m} ms elapsed; nothing to report beyond the routine summary line.",
]

CHATTER = [
    "CHATTER {i}: Lucas mentioned in passing that we should probably look at this again later, not urgent, just noting it here so it does not get lost in the thread somewhere.",
    "CHATTER {i}: someone asked whether the staging credentials still work and nobody answered, so treat this line as unresolved background rather than evidence.",
]

TASK = """Answer these questions from the dossier, using only the evidence present:

1. What share of mobile visitors is lost in the booking flow, and at which step?
2. What is the measured p75 mobile load time, and on what profile?
3. What share of inbound messages arrives outside opening hours?
4. How much chair capacity is idle after 17:00, and on which days?
5. How long does front desk spend re-typing each booking, and into what?

Return a numbered list. One line per answer, with the figure. If a fact is absent from the
dossier, write exactly: NOT PRESENT IN EVIDENCE. Do not guess.
"""


def build(scale: str, seed: int = 42) -> dict:
    rng = random.Random(seed)
    counts = {
        "small": {"tools": 8, "logs": 6, "chatter": 6},
        "medium": {"tools": 40, "logs": 30, "chatter": 30},
        "large": {"tools": 110, "logs": 80, "chatter": 80},
    }[scale]

    blocks: list[str] = [PREFIX.strip()]
    blocks.append("<!-- lcc:cache-break -->")
    # Ground truth sits in the volatile tail: it is exactly what a bad transform destroys.
    blocks.append(GROUND_TRUTH[0])
    for i in range(counts["tools"]):
        blocks.append(TOOLS[i % len(TOOLS)].format(
            i=i, p=rng.randint(40, 88), f=rng.randint(9, 40)))
    for i in range(counts["logs"]):
        blocks.append(LOGS[i % len(LOGS)].format(
            i=i, m=rng.randint(120, 9000), b=rng.randint(0, 400)))
    blocks.append(GROUND_TRUTH[2])
    for i in range(counts["chatter"]):
        blocks.append(CHATTER[i % len(CHATTER)].format(i=i))
    blocks.append(GROUND_TRUTH[3])
    for i in range(counts["tools"]):
        blocks.append(DISTRACTORS[i % len(DISTRACTORS)])
    blocks.append(GROUND_TRUTH[1])
    blocks.append(GROUND_TRUTH[4])

    text = "\n\n".join(blocks)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return {
        "scale": scale,
        "seed": seed,
        "text": text,
        "blocks": len(blocks),
        "chars": len(text),
        "sha256": digest,
        "objective": "What is the measured mobile conversion problem for the clinic?",
        "task": TASK,
        "required": GROUND_TRUTH,
        "forbidden": DISTRACTORS,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = {}
    for scale in ("small", "medium", "large"):
        case = build(scale)
        (OUT / f"{scale}.md").write_text(case["text"], encoding="utf-8")
        (OUT / f"{scale}.task.md").write_text(case["task"], encoding="utf-8")
        index[scale] = {k: v for k, v in case.items() if k not in ("text", "task")}
        print(f"{scale}: blocks={case['blocks']} chars={case['chars']} sha={case['sha256'][:12]}")
    (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
