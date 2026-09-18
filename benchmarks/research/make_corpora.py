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

# Ground truth, tagged by the CATEGORY of information it represents. A flat fact count cannot
# tell you *which kind* of information a transform is bad at keeping, and that is the number a
# reviewer needs: losing a critical fact, a negative constraint and a dated value are three
# different severities, and a compressor can be good at one and bad at another.
#
# `marker` is the regex that must still match the emitted context for the item to count as kept.
# `text` is the block placed into the corpus; it has to be over the 80-char scoring floor, or
# nothing could ever drop it and the item would test nothing.
BLOCKS: list[dict[str, str]] = [
    {
        "category": "critical_fact",
        "marker": r"63 percent",
        "text": "GROUND TRUTH A: The clinic booking widget loses 63 percent of mobile visitors "
        "before the second step of the form.",
    },
    {
        "category": "critical_fact",
        "marker": r"4\.2 seconds",
        "text": "GROUND TRUTH B: p75 mobile load time on the treatment landing page is 4.2 "
        "seconds on a throttled 3G profile.",
    },
    {
        "category": "critical_fact",
        "marker": r"41 percent",
        "text": "GROUND TRUTH C: 41 percent of inbound WhatsApp messages to the clinic arrive "
        "outside 09:00-18:00 opening hours.",
    },
    {
        "category": "critical_fact",
        "marker": r"3 chairs",
        "text": "GROUND TRUTH D: The practice has 3 chairs, 2 of which sit idle after 17:00 on "
        "weekdays.",
    },
    {
        "category": "critical_fact",
        "marker": r"4 minutes",
        "text": "GROUND TRUTH E: Front desk currently re-types every booking into a paper diary, "
        "averaging 4 minutes per booking.",
    },
    {
        "category": "constraint",
        "marker": r"within 48 hours",
        "text": "OPERATING CONSTRAINT: an appointment may only be rebooked through the front "
        "desk, and only within 48 hours of the original slot.",
    },
    {
        "category": "negative_constraint",
        "marker": r"must not be contacted",
        "text": "COMPLIANCE RULE: patients who have not signed the updated consent form must not "
        "be contacted about the booking system migration.",
    },
    {
        "category": "exception",
        "marker": r"excludes returning (?:customers|visitors|patients)",
        "text": "EXCEPTION: the 63 percent abandonment figure excludes returning customers "
        "entirely, so it describes first-time visitors only.",
    },
    {
        "category": "temporal",
        "marker": r"revised on 3 September|5\.8 seconds",
        "text": "REVISION: the p75 figure was revised on 3 September, down from 5.8 seconds "
        "measured in June.",
    },
    {
        "category": "contradiction",
        "marker": r"8\.7 percent",
        "text": "CONFLICTING MEASUREMENT: a later export puts monthly churn at 8.7 percent, "
        "against the 4.2 percent recorded earlier in the same quarter.",
    },
]

#: Categories present in a corpus, for the per-category recall table.
CATEGORIES: tuple[str, ...] = (
    "critical_fact",
    "constraint",
    "negative_constraint",
    "exception",
    "temporal",
    "contradiction",
)

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
        # Stress scale: roughly four times `large`, to check that category recall and cache
        # behaviour hold when the corpus stops fitting comfortably in a small context.
        "xl": {"tools": 420, "logs": 320, "chatter": 320},
    }[scale]

    blocks: list[str] = [PREFIX.strip()]
    blocks.append("<!-- lcc:cache-break -->")
    # Categorized ground truth sits in the volatile tail: it is exactly what a bad transform
    # destroys, and spreading it through the corpus means no single drop decision can take out
    # one category by accident.
    blocks.append(BLOCKS[0]["text"])           # critical_fact A
    for i in range(counts["tools"]):
        blocks.append(TOOLS[i % len(TOOLS)].format(
            i=i, p=rng.randint(40, 88), f=rng.randint(9, 40)))
    blocks.append(BLOCKS[5]["text"])           # constraint
    for i in range(counts["logs"]):
        blocks.append(LOGS[i % len(LOGS)].format(
            i=i, m=rng.randint(120, 9000), b=rng.randint(0, 400)))
    blocks.append(BLOCKS[2]["text"])           # critical_fact C
    blocks.append(BLOCKS[6]["text"])           # negative_constraint
    for i in range(counts["chatter"]):
        blocks.append(CHATTER[i % len(CHATTER)].format(i=i))
    blocks.append(BLOCKS[7]["text"])           # exception
    blocks.append(BLOCKS[3]["text"])           # critical_fact D
    for i in range(counts["tools"]):
        blocks.append(DISTRACTORS[i % len(DISTRACTORS)])
    blocks.append(BLOCKS[8]["text"])           # temporal
    blocks.append(BLOCKS[1]["text"])           # critical_fact B
    blocks.append(BLOCKS[9]["text"])           # contradiction
    blocks.append(BLOCKS[4]["text"])           # critical_fact E

    text = "\n\n".join(blocks)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return {
        "scale": scale,
        "seed": seed,
        "text": text,
        "blocks": len(blocks),
        "chars": len(text),
        "sha256": digest,
        # The objective has to match what the ground truth actually claims is needed. A narrow
        # "mobile conversion" question cannot honestly require a chair-capacity fact or a
        # rebooking rule, and a benchmark whose ground truth is not needed to answer its own
        # question measures nothing. This objective covers every category the corpus carries.
        "objective": "What is wrong with the clinic's booking operation, and what limits what we can change?",
        "task": TASK,
        "categories": list(CATEGORIES),
        "items": [
            {"category": item["category"], "marker": item["marker"]} for item in BLOCKS
        ],
        "forbidden": DISTRACTORS,
    }


#: Canonical scale order. `xl` is the stress scale: roughly four times `large`.
SCALES: tuple[str, ...] = ("small", "medium", "large", "xl")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = {}
    for scale in SCALES:
        case = build(scale)
        (OUT / f"{scale}.md").write_text(case["text"], encoding="utf-8")
        (OUT / f"{scale}.task.md").write_text(case["task"], encoding="utf-8")
        index[scale] = {k: v for k, v in case.items() if k not in ("text", "task")}
        print(f"{scale}: blocks={case['blocks']} chars={case['chars']} sha={case['sha256'][:12]}")
    (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
