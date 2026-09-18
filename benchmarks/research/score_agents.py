#!/usr/bin/env python3
"""Score the real agent A/B answers: fact retention, fabrication, and token cost.

Reads answers/<arm>_<n>.txt (one file per agent sample) plus answers/tokens.json
(provider-reported per-session usage pulled from Hermes state.db) and emits
results/agent_ab.json.

Scoring is deterministic and grounded in the corpus ground truth:
  recall      share of the five figures the answer actually states
  fabrication numbers that appear in the dossier ONLY as distractors, or that appear nowhere
  abstention  correct NOT PRESENT IN EVIDENCE usage (should be 0 here: every fact is present)
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
ANSWERS = ROOT / "answers"
OUT = ROOT / "results"

# fact -> (regex that counts as "answered correctly", human label)
FACTS = {
    "q1_step1_63pct": (r"63\s*(?:percent|%)", "63% lost before step 2"),
    "q2_p75_4.2s": (r"4\.2\s*(?:s|seconds|sec)", "p75 4.2s on 3G"),
    "q3_after_hours_41pct": (r"41\s*(?:percent|%)", "41% outside opening hours"),
    "q4_chairs_idle": (r"3\s+chairs|two of (?:the )?three chairs|2 of 3 chairs", "3 chairs, 2 idle after 17:00"),
    "q5_retype_4min": (r"4\s*(?:minutes|min)", "4 minutes re-typing per booking"),
}

# Numbers that exist in the dossier only inside DISTRACTOR blocks, or nowhere at all.
FORBIDDEN = {
    "distractor_300pct": r"300\s*(?:percent|%)",
    "distractor_12x": r"12\s*x\b",
    "invented_emoji": r"\b(?:AI|robot)\s+chatbot\b",
}

ARMS = {"raw": "no LCC (raw corpus)", "lcc_jev": "LCC compact --provider jev", "lcc_optimize": "LCC optimize --template claude_xml"}


def score(text: str) -> dict:
    found = {k: bool(re.search(rx, text, re.I)) for k, (rx, _) in FACTS.items()}
    hits = {k: bool(re.search(rx, text, re.I)) for k, rx in FORBIDDEN.items()}
    return {
        "facts": found,
        "recall": round(sum(found.values()) / len(found), 4),
        "missing": [k for k, v in found.items() if not v],
        "hallucinated": [k for k, v in hits.items() if v],
        "abstained": len(re.findall(r"NOT PRESENT IN EVIDENCE", text)),
        "numbered_items": len(re.findall(r"^\s*\d+[.)]", text, re.M)),
        "chars": len(text),
    }


def main() -> None:
    tokens = json.loads((ANSWERS / "tokens.json").read_text()) if (ANSWERS / "tokens.json").exists() else {}
    result: dict = {"arms": {}, "token_source": "Hermes state.db sessions table (provider-reported)"}

    for arm in ARMS:
        samples = []
        for path in sorted(ANSWERS.glob(f"{arm}_*.txt")):
            samples.append({"file": path.name, **score(path.read_text(encoding="utf-8"))})
        if not samples:
            continue
        recalls = [s["recall"] for s in samples]
        result["arms"][arm] = {
            "label": ARMS[arm],
            "samples": len(samples),
            "recall_values": recalls,
            "recall_mean": round(sum(recalls) / len(recalls), 4),
            "recall_min": min(recalls),
            "perfect_samples": sum(1 for r in recalls if r == 1.0),
            "hallucination_events": sum(len(s["hallucinated"]) for s in samples),
            "per_sample": samples,
            "tokens": tokens.get(arm, {}),
        }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "agent_ab.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"{'arm':16} {'samples':>7} {'recall_mean':>11} {'perfect':>8} {'halluc':>7} {'in_tok':>9} {'cache_rd':>10} {'out_tok':>8}")
    for arm, a in result["arms"].items():
        t = a["tokens"] or {}
        print(f"{arm:16} {a['samples']:>7} {a['recall_mean']:>11.3f} "
              f"{a['perfect_samples']:>8} {a['hallucination_events']:>7} "
              f"{t.get('input_tokens', '-'):>9} {t.get('cache_read_tokens', '-'):>10} "
              f"{t.get('output_tokens', '-'):>8}")
    print(f"\nwrote {OUT / 'agent_ab.json'}")


if __name__ == "__main__":
    main()
