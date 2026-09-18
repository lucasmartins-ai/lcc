#!/usr/bin/env python3
"""Multi-agent benchmark PILOT (E0/E1/E2): RAW vs LCC across domains, offline.

Pilot scope (approved): 20 tasks x 5 domains, deterministic mock agents.
Each task = one adversarial case mapped to a domain. Arms differ ONLY in the
context block; the harness, question, and mock answerer are identical.

- E0 evidence preservation: required regex checks survive in compacted bytes.
- E1 answer preservation: mock downstream answer from RAW vs from COMPACTED
  has the same recall (quality_delta = recall_compact - recall_raw; <0 = regression).
- E2 safety calibration: when structural sufficiency fails or verifier would
  flag, did the pass set needs_review instead of silently trusting?
- Cost: tokens_before/after, reduction, invalidated_tokens, break_even_reuses.

Arms (offline, no API key): raw | compact-mechanical | compact-mechanical-no-sufficiency.
Jev arms plug in with --provider jev when TYPESAFE_API_KEY exists.

Run: python3 benchmarks/research/run_multiagent_ab.py [--tasks 20] [--provider mechanical]
Writes results/multiagent_ab.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adversarial_cases import CASES, build_corpus  # noqa: E402
from lcc.relevance import RelevanceCompactionRequest, compact_context  # noqa: E402

DOMAIN_OF = {
    "negation_consent": "booking",
    "double_negation": "booking",
    "contradiction_same_metric": "finance",
    "temporal_supersession": "finance",
    "source_authority_conflict": "devops",
    "dependency_qualifier": "booking",
    "dependency_causal": "booking",
    "numeric_precision": "devops",
    "unit_conversion": "devops",
    "quoted_instruction": "support",
    "prompt_injection": "support",
    "structured_json": "devops",
    "structured_yaml": "devops",
    "structured_xml": "devops",
    "structured_code": "devops",
    "structured_table": "finance",
    "multilingual": "support",
    "unicode_content": "support",
    "qualifier_truncation": "safety",
    "qualifier_unless": "finance",
    "structured_semantic_json": "finance",
    "structured_semantic_units": "devops",
    "very_long_block": "devops",
    "many_short_blocks": "devops",
    "scope_quantifiers": "safety",
    "coreference_resolution": "support",
    "paraphrase_duplicates": "support",
    "multiblock_vat_set": "finance",
    "injection_html": "support",
    "injection_log": "devops",
}

PILOT_IDS = [
    "negation_consent", "dependency_qualifier", "dependency_causal", "temporal_supersession",
    "quoted_instruction", "prompt_injection", "injection_html", "multilingual",
    "contradiction_same_metric", "structured_table", "qualifier_unless", "multiblock_vat_set",
    "numeric_precision", "unit_conversion", "structured_semantic_units", "structured_code",
    "source_authority_conflict", "injection_log", "very_long_block", "scope_quantifiers",
]


def _recall(text: str, case) -> float:
    required = case.must_survive or tuple(range(len(case.critical)))
    hits = sum(1 for i in required if case.critical[i].strip()[:60] in text)
    check_ok = sum(
        1
        for _, pat, exp in case.checks
        if bool(re.search(pat, text, re.I | re.S)) == (exp == "present")
    )
    total = len(required) + len(case.checks)
    return round((hits + check_ok) / total, 4) if total else 1.0


def mock_answer(context: str, case) -> str:
    spans = [
        case.critical[i].strip()[:200]
        for i in (case.must_survive or tuple(range(len(case.critical))))
        if case.critical[i].strip()[:60] in context
    ]
    return "ANSWER :: " + " | ".join(spans)


def run_task(case, provider: str, enable_sufficiency: bool) -> dict:
    corpus = build_corpus(case)
    raw_recall = _recall(corpus, case)
    raw_answer_recall = _recall(mock_answer(corpus, case), case)
    result = compact_context(
        RelevanceCompactionRequest(
            text=corpus,
            question=case.question,
            provider=provider,
            enable_sufficiency=enable_sufficiency,
        )
    )
    r = result.report
    comp_recall = _recall(result.compacted_text, case)
    ans_recall = _recall(mock_answer(result.compacted_text, case), case)
    return {
        "id": case.id,
        "domain": DOMAIN_OF.get(case.id, "general"),
        "hazard": case.hazard,
        "tokens_before": r.tokens_before,
        "tokens_after": r.tokens_after,
        "reduction": round(r.reduction_ratio, 4),
        "E0_evidence_delta": round(comp_recall - raw_recall, 4),
        "E1_answer_delta": round(ans_recall - raw_answer_recall, 4),
        "E1_regression": ans_recall < raw_answer_recall,
        "E2_needs_review": bool(getattr(r, "needs_review", False)),
        "E2_review_reason": getattr(r, "review_reason", None),
        "sufficiency_failures": r.sufficiency_failures,
        "blocks_restored": r.blocks_restored,
        "invalidated_tokens": r.invalidated_tokens,
        "break_even_reuses": r.break_even_reuses,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=20)
    ap.add_argument("--provider", default="mechanical")
    args = ap.parse_args()
    id_list = PILOT_IDS[: args.tasks]
    cases = [c for c in CASES if c.id in id_list]
    arms = {
        "raw_vs_compact": {"provider": args.provider, "enable_sufficiency": True},
        "no_sufficiency_ablation": {"provider": args.provider, "enable_sufficiency": False},
    }
    out: dict = {"arms": {}, "tasks": id_list}
    failed = False
    for arm, kw in arms.items():
        rows = [run_task(c, kw["provider"], kw["enable_sufficiency"]) for c in cases]
        regs = [r for r in rows if r["E1_regression"]]
        e0regs = [r for r in rows if r["E0_evidence_delta"] < 0]
        reviews = sum(1 for r in rows if r["E2_needs_review"])
        mean_red = round(sum(r["reduction"] for r in rows) / len(rows), 4)
        out["arms"][arm] = {
            "n": len(rows),
            "E1_regressions": len(regs),
            "E0_regressions": len(e0regs),
            "reviews": reviews,
            "mean_reduction": mean_red,
            "rows": rows,
        }
        print(
            f"{arm:24} n={len(rows)} E1_reg={len(regs)} E0_reg={len(e0regs)} "
            f"reviews={reviews} mean_red={mean_red:.1%}"
        )
        for r in regs:
            print(f"  E1 REGRESSION {r['id']} delta={r['E1_answer_delta']}")
            failed = True
    dest = Path(__file__).resolve().parent / "results" / "multiagent_ab.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {dest}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
