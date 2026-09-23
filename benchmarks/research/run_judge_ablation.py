#!/usr/bin/env python3
"""Judge ablation: separate judge quality from safety-layer masking (P1).

Compares judges across three arms on the same labelled corpus:

  A. RAW judge decision  (threshold only: no protection, no sufficiency, no verifier)
  B. judge + safety      (deterministic protection + sufficiency + restoration)
  C. judge + safety + semantic verifier (arm B + independent verification)

Run one judge at a time (``--judge``) and diff the rows: when arm-A gaps close
in arm B, the safety layer — not judge parity — explains the convergence.
``mock-laya``/``mock-jev`` are deterministic stand-ins with different error
profiles that exercise the harness offline; ``jev``/``laya`` need live backends
and are reported NOT VALIDATED when unavailable.

Metrics per arm: selector precision/recall vs block labels, false drops,
false keeps, critical-evidence recall, reduction, calls, latency, est. cost.

Run: python3 benchmarks/research/run_judge_ablation.py [--judge mock-jev]
"""

from __future__ import annotations

# ruff: noqa: I001, E402 — sys.path bootstrap must precede sibling imports.
import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lcc.relevance import RelevanceCompactionRequest, compact_context  # noqa: E402
from lcc.relevance.blocks import split_blocks  # noqa: E402

EVIDENCE = [
    "The booking widget loses 63 percent of mobile visitors at the date picker step.",
    "The date picker broke in the June release, except on the legacy shard.",
    "Support ticket 4471: checkout fails unless the coupon field is empty.",
    "Revised: May conversion is restated down from 8.7 percent to 4.2 percent.",
    "The refund policy allows claims, but never for sealed auction items.",
    "Order ord-7781 depends on ord-7770 and cannot ship before it clears.",
]
NOISE = [
    "Office chatter about plants needing water near the coffee machine daily.",
    "Parking permits renew in spring; the lot repaving starts someday soon.",
    "The cafeteria menu rotates soups on weekdays with bread on the side.",
    "Someone left a jacket in the meeting room next to the projector remote.",
    "The lobby plant was replaced after the old one dropped its leaves.",
    "Weekend football results surprised nobody at the office this morning.",
]
QUESTION = "Why is the clinic losing mobile bookings and what limits the fix?"


class _MockJudge:
    """Deterministic stand-in judge with a tunable error profile.

    ``drop_rate``: share of evidence blocks deliberately underscored (simulates
    a weaker judge); ``noise`` flips one noise block to low. Different profiles
    stand in for Laya vs Jev offline; they prove the harness, not the models.
    """

    model = "mock-judge"
    last_resolved_model = "mock-judge-1"

    def __init__(self, drop_rate: float = 0.0) -> None:
        self.drop_rate = drop_rate
        self.calls = 0

    def evaluate(self, state, questions):
        self.calls += 1
        if "context" in state:  # verifier call: judge the candidate honestly
            present = sum(1 for e in EVIDENCE if e[:40] in state["context"])
            score = min(1.0, 0.2 + 0.15 * present)
            return {
                "answers": {
                    "sufficient_to_answer": {
                        "type": "noul",
                        "noul": round(score, 2),
                        "confidence": 0.8,
                    },
                    "contradiction_risk": {
                        "type": "noul",
                        "noul": 0.1,
                        "confidence": 0.9,
                    },
                }
            }
        answers = {}
        texts = {b["id"]: b["text"] for b in state.get("blocks", [])}
        ev_idx = 0
        for qid in questions:
            bid = qid[len("keep_"):]
            text = texts.get(bid, "")
            is_evidence = any(e[:40] in text for e in EVIDENCE)
            if is_evidence:
                ev_idx += 1
                # Underscore the first N evidence blocks to simulate judge misses.
                score = 0.1 if ev_idx <= round(self.drop_rate * len(EVIDENCE)) else 0.9
            else:
                score = 0.05
            answers[qid] = {"type": "noul", "noul": score, "confidence": 0.9}
        return {"answers": questions and answers}


@dataclass
class ArmResult:
    arm: str
    precision: float
    recall: float
    false_drops: int
    false_keeps: int
    critical_recall: float
    reduction: float
    calls: int
    latency_ms: int
    needs_review: bool


def _labels(block_ids: list[str], corpus: str) -> dict[str, bool]:
    blocks = {b.id: b.text for b in split_blocks(corpus)}
    return {
        bid: any(e[:40] in blocks.get(bid, "") for e in EVIDENCE) for bid in block_ids
    }


def _run_arm(
    arm: str, corpus: str, judge_factory, verify: bool, safety: bool, batch_size: int = 8
) -> ArmResult:
    started = time.perf_counter()
    request = RelevanceCompactionRequest(
        text=corpus,
        question=QUESTION,
        provider="jev",
        client=judge_factory(),
        threshold=0.4,
        deterministic_protection=safety,
        enable_sufficiency=safety,
        enable_semantic_verify=verify,
        batch_size=batch_size,
    )
    result = compact_context(request)
    latency_ms = int((time.perf_counter() - started) * 1000)
    labels = _labels([d.id for d in result.report.decisions], corpus)
    kept = {d.id for d in result.report.decisions if d.decision == "keep"}
    # Protected short blocks are keeps by construction; score only judged ones.
    judged = [d for d in result.report.decisions if d.source != "protected"]
    tp = sum(1 for d in judged if labels[d.id] and d.id in kept)
    fp = sum(1 for d in judged if not labels[d.id] and d.id in kept)
    fn = sum(1 for d in judged if labels[d.id] and d.id not in kept)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    critical = sum(1 for e in EVIDENCE if e[:40] in result.compacted_text)
    return ArmResult(
        arm=arm,
        precision=round(precision, 3),
        recall=round(recall, 3),
        false_drops=fn,
        false_keeps=fp,
        critical_recall=round(critical / len(EVIDENCE), 3),
        reduction=round(result.report.reduction_ratio, 3),
        calls=result.report.calls,
        latency_ms=latency_ms,
        needs_review=result.report.needs_review,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Judge ablation A/B/C.")
    parser.add_argument(
        "--judge",
        default="mock-jev",
        choices=("mock-jev", "mock-laya", "mechanical", "jev", "laya"),
        help="mock-jev: near-perfect stand-in; mock-laya: misses 2/6 evidence; "
        "mechanical: local lexical baseline; jev: live TypeSafe judge (needs "
        "TYPESAFE_API_KEY); laya: local Laya backend (needs the laya extra).",
    )
    parser.add_argument(
        "--laya-model",
        default=None,
        help="Laya checkpoint for --judge laya (e.g. convaiinnovations/laya-typed-decisions). "
        "Must be passed here: the request field otherwise carries the LCC default and the "
        "compactor stamps it over an injected client, so LCC_LAYA_MODEL alone is not enough.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Blocks per judge state. 1 is the measured working configuration for Laya: a "
        "batched state collapses its per-block judgement (docs/LAYA.md §8).",
    )
    parser.add_argument("--out", default=None, help="Write JSON rows here.")
    args = parser.parse_args()

    # Pad every segment past min_block_chars so each one is actually judged:
    # short blocks are protected by construction and would blunt the ablation.
    def _pad(i: int, seg: str) -> str:
        pads = " ".join([f"padword{i}{k}" for k in range(8)])
        filler = (
            " Additional background sentence " + str(i) + " with neutral filler"
            " vocabulary " + pads + " rounding out the block."
        )
        return seg + filler

    corpus = "\n\n".join(
        _pad(i, seg) for i, seg in enumerate(EVIDENCE + NOISE)
    ) + "\n"

    def factory():
        if args.judge == "mock-laya":
            return _MockJudge(drop_rate=0.34)  # misses first 2 evidence blocks
        if args.judge == "mock-jev":
            return _MockJudge(drop_rate=0.0)
        if args.judge == "jev":
            from lcc.relevance import JevClient

            client = JevClient.from_env()
            if client is None:
                print("NOT VALIDATED: no live Jev backend (TYPESAFE_API_KEY missing).")
                raise SystemExit(2)
            return client
        if args.judge == "laya":
            try:
                from lcc.relevance import LayaClient
            except Exception as err:
                print("NOT VALIDATED: laya extra not installed.")
                raise SystemExit(2) from err
            try:
                return LayaClient(model=args.laya_model) if args.laya_model else LayaClient()
            except Exception as exc:
                print(f"NOT VALIDATED: Laya backend unavailable ({exc}).")
                raise SystemExit(2) from exc
        return None  # mechanical: provider path, no client

    def run(arm, safety, verify, provider):
        if provider == "mechanical":
            req = RelevanceCompactionRequest(
                text=corpus,
                question=QUESTION,
                provider="mechanical",
                threshold=0.4,
                deterministic_protection=safety,
                enable_sufficiency=safety,
                enable_semantic_verify=False,
            )
            started = time.perf_counter()
            result = compact_context(req)
            latency_ms = int((time.perf_counter() - started) * 1000)
            labels = _labels([d.id for d in result.report.decisions], corpus)
            kept = {d.id for d in result.report.decisions if d.decision == "keep"}
            judged = [d for d in result.report.decisions if d.source != "protected"]
            tp = sum(1 for d in judged if labels[d.id] and d.id in kept)
            fp = sum(1 for d in judged if not labels[d.id] and d.id in kept)
            fn = sum(1 for d in judged if labels[d.id] and d.id not in kept)
            critical = sum(1 for e in EVIDENCE if e[:40] in result.compacted_text)
            return ArmResult(
                arm=arm,
                precision=round(tp / (tp + fp) if (tp + fp) else 1.0, 3),
                recall=round(tp / (tp + fn) if (tp + fn) else 1.0, 3),
                false_drops=fn,
                false_keeps=fp,
                critical_recall=round(critical / len(EVIDENCE), 3),
                reduction=round(result.report.reduction_ratio, 3),
                calls=result.report.calls,
                latency_ms=latency_ms,
                needs_review=result.report.needs_review,
            )
        return _run_arm(
            arm, corpus, factory, verify=verify, safety=safety, batch_size=args.batch_size
        )

    if args.judge in ("mechanical",):
        provider = "mechanical"
    elif args.judge in ("jev", "laya"):
        provider = "live"
    else:
        provider = "mock"

    def run_live(arm, safety, verify):
        from lcc.relevance import RelevanceCompactionRequest as _Req
        from lcc.relevance import compact_context as _compact

        started = time.perf_counter()
        client = factory()
        req_provider = "laya" if args.judge == "laya" else "jev"
        extra_kw: dict[str, Any] = (
            {"laya_model": args.laya_model}
            if (args.laya_model and req_provider == "laya")
            else {}
        )
        result = _compact(
            _Req(
                text=corpus,
                question=QUESTION,
                provider=req_provider,
                client=client,
                threshold=0.4,
                deterministic_protection=safety,
                enable_sufficiency=safety,
                enable_semantic_verify=verify,
                batch_size=args.batch_size,
                **extra_kw,
            )
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        labels = _labels([d.id for d in result.report.decisions], corpus)
        kept = {d.id for d in result.report.decisions if d.decision == "keep"}
        judged = [d for d in result.report.decisions if d.source != "protected"]
        tp = sum(1 for d in judged if labels[d.id] and d.id in kept)
        fp = sum(1 for d in judged if not labels[d.id] and d.id in kept)
        fn = sum(1 for d in judged if labels[d.id] and d.id not in kept)
        critical = sum(1 for e in EVIDENCE if e[:40] in result.compacted_text)
        rep = result.report
        extra = {
            "provider_used": rep.provider_used,
            "semantic_guarantee": rep.semantic_guarantee,
            "verifier_decision": rep.semantic_verifier_decision,
            "verifier_confidence": rep.semantic_verifier_confidence,
            "blocks_restored": rep.blocks_restored,
            "resolved_model": rep.jev_model_resolved or rep.laya_model_resolved,
        }
        row = ArmResult(
            arm=arm,
            precision=round(tp / (tp + fp) if (tp + fp) else 1.0, 3),
            recall=round(tp / (tp + fn) if (tp + fn) else 1.0, 3),
            false_drops=fn,
            false_keeps=fp,
            critical_recall=round(critical / len(EVIDENCE), 3),
            reduction=round(rep.reduction_ratio, 3),
            calls=rep.calls,
            latency_ms=latency_ms,
            needs_review=rep.needs_review,
        )
        return row, extra

    rows: list = []
    live_extra: dict[str, dict] = {}
    if provider == "live":
        for arm, safety, verify in (
            ("A_raw_judge", False, False),
            ("B_judge_safety", True, False),
            ("C_judge_safety_verifier", True, True),
        ):
            row, extra = run_live(arm, safety, verify)
            rows.append(row)
            live_extra[arm] = extra
    else:
        rows = [
            run("A_raw_judge", safety=False, verify=False, provider=provider),
            run("B_judge_safety", safety=True, verify=False, provider=provider),
            run("C_judge_safety_verifier", safety=True, verify=True, provider=provider),
        ]
    payload = [
        {
            "judge": args.judge,
            "arm": r.arm,
            "selector_precision": r.precision,
            "selector_recall": r.recall,
            "false_drops": r.false_drops,
            "false_keeps": r.false_keeps,
            "critical_evidence_recall": r.critical_recall,
            "reduction": r.reduction,
            "calls": r.calls,
            "latency_ms": r.latency_ms,
            "needs_review": r.needs_review,
        }
        for r in rows
    ]
    live = provider == "live"
    scope_note = (
        "LIVE backend — measured figures"
        if live
        else "mock judges prove the harness, not the models"
    )
    print(f"# judge ablation: {args.judge} ({scope_note})")
    print("| arm | precision | recall | false_drops | false_keeps | critical_recall | reduction | calls | review |")
    print("|---|---|---|---|---|---|---|---|---|")
    for row in payload:
        print(
            f"| {row['arm']} | {row['selector_precision']} | {row['selector_recall']} | "
            f"{row['false_drops']} | {row['false_keeps']} | {row['critical_evidence_recall']} | "
            f"{row['reduction']} | {row['calls']} | {row['needs_review']} |"
        )
    a_gap = rows[0].false_drops
    b_gap = rows[1].false_drops
    if a_gap > b_gap:
        print(f"\nSafety layer closed {a_gap - b_gap} raw-judge false drop(s): arm-A gaps are judge gaps.")
    if live_extra:
        print("\nLive arm detail:")
        for arm, extra in live_extra.items():
            print(f"- {arm}: " + ", ".join(f"{k}={v}" for k, v in extra.items()))
    if args.out:
        Path(args.out).write_text(
            json.dumps({"judge": args.judge, "live": live, "rows": payload, "live_extra": live_extra}, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
