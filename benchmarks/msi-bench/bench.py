"""MSI Sprint 7: MSI-Bench core (offline, deterministic, no network).

Six arms over the frozen tasks in tasks.py. Every arm-run goes through the
real sprint-4/5 machinery (DeterministicPlanner + run_execution over
verify-1.0); arms differ ONLY in context selection and budgets:

- full:                 all units; fixed frontier plan; single attempt.
- lcc:                  lexical filter, no protection; fixed local plan; single.
- routing:              all units; planned model; single attempt.
- lcc_routing:          lexical filter; planned model; single attempt.
- lcc_routing_verify:   lexical filter; planned model; bounded restore+retry.
- msi:                  lexical filter + exact-carrier/citation protection
                        + protected units; planned model; bounded restore+retry.

Paired scoring: every arm verifies under the task's frozen default profile
(``standard``); plan profiles are normalized to it (recorded in the routed
event). Quality is therefore strictly comparable across arms; plans still
move cost (model choice) and escalation targets.

Cost is MODELED (illustrative prices, ordering-robust; see PRICE table).
Latency reported is measured deterministic wall time only -- no model
inference latency is measured here (no live models; declared limitation).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import replace

from tasks import ARMS, BenchTask, carriers

from lcc.router.escalate import ReceiptVersions, run_execution
from lcc.router.plan import (
    DeterministicPlanner,
    EscalationPolicy,
    Fallback,
    InferencePlan,
    PlannerInput,
)
from lcc.router.verify import UnitResult, VerificationSubject
from lcc.token_budget.counters import approximate_token_count

BENCH_VERSION = "msi-bench-1.0"
EVALUATOR = "verify-1.0"
PLANNER = "planner-1.0"
TOKENIZER = "heuristic-v1"
PROFILE = "standard"
SEED = 7
BOOTSTRAP_RESAMPLES = 2000

# Illustrative modeled prices, USD per 1k tokens. Absolute values are NOT a
# claim (no vendor quote); only the ordering local(0) < hosted < frontier is
# load-bearing, and every cost conclusion is stated as a ratio/rank.
PRICE_IN_PER_1K = {"local_tiny": 0.0, "local_small": 0.0, "fast_hosted": 0.5, "frontier": 8.0}
PRICE_OUT_PER_1K = {"local_tiny": 0.0, "local_small": 0.0, "fast_hosted": 1.5, "frontier": 24.0}
CHEAP_MODELS = ("local_tiny", "local_small")
HIGH_RISKS = ("high", "unknown")

# Closed stopword set, copied from src/lcc/router/ablate.py (fixed there so
# the pilot hash is stable); copied here so the bench does not import a
# private name. Exact match, no stemming.
_STOPWORDS = frozenset(
    [
        "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for",
        "with", "is", "are", "was", "were", "be", "been", "it", "its",
        "this", "that", "these", "those", "as", "by", "from", "every",
        "reminder",
    ]
)

_DET = DeterministicPlanner()


def _tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS)


def lexical_keep(task: BenchTask) -> list[str]:
    """Keep units sharing >=1 non-stopword token with the objective."""
    obj = _tokens(task.objective)
    return [u.id for u in task.units if _tokens(u.content) & obj]


def protected_keep(task: BenchTask) -> list[str]:
    """Lexical keep + exact required-fact carriers + citation carrier + protected."""
    keep = set(lexical_keep(task))
    keep.update(carriers(task))
    keep.update(u.id for u in task.units if u.protected)
    ordered = [u.id for u in task.units if u.id in keep]
    return ordered


def _fixed_plan(model: str, context: str, arm: str) -> InferencePlan:
    return InferencePlan(
        model_class=model,
        reasoning_budget="high" if model == "frontier" else "low",
        context_profile=context,
        verification_profile=PROFILE,
        fallbacks=[
            Fallback("VERIFY_FAIL", "RESTORE_CONTEXT"),
            Fallback("LOW_CONF", "ESCALATE"),
        ],
        escalation_policy=EscalationPolicy(
            max_retries=0, max_restorations=0, escalate_to="frontier"
        ),
        tools=["retrieval.search"],
        route="bench-fixed",
        reasons=[f"bench:arm={arm}", f"bench_pairing:profile={PROFILE}"],
        engine=f"bench-{arm}",
    )


def _planned(task: BenchTask, arm: str) -> InferencePlan:
    plan = _DET.plan(PlannerInput(task_id=task.task_id, risk_level=task.risk))
    return replace(
        plan,
        verification_profile=PROFILE,  # paired scoring; plan profile in reasons
        reasons=[*plan.reasons, f"bench:arm={arm}", f"bench_pairing:profile={PROFILE}",
                 f"plan_profile={plan.verification_profile}"],
        engine=plan.engine,
    )


def _selection(task: BenchTask, arm: str) -> list[str]:
    if arm in ("full", "routing"):
        return [u.id for u in task.units]
    if arm in ("lcc", "lcc_routing", "lcc_routing_verify"):
        return [uid for uid in lexical_keep(task) if uid in [u.id for u in task.units]]
    if arm == "msi":
        return protected_keep(task)
    raise ValueError(f"unknown arm {arm!r}")


def _base_plan(task: BenchTask, arm: str) -> InferencePlan:
    if arm == "full":
        return _fixed_plan("frontier", "full", arm)
    if arm == "lcc":
        return _fixed_plan("local_small", "compiled", arm)
    return _planned(task, arm)


def _subject(task: BenchTask, selected: list[str]) -> VerificationSubject:
    by_id = {u.id: u.content for u in task.units}
    summary = "\n".join(by_id[i] for i in selected)
    cite = task.citation_carrier is not None
    return VerificationSubject(
        output={"summary": summary, "labels": ["bench"]},
        required_fields=["summary"],
        required_facts=list(task.required_facts),
        forbidden_claims=list(task.forbidden_claims),
        citation_ids=["c1"] if cite and task.citation_carrier in selected else [],
        valid_citation_ids=frozenset({"c1"}),
        require_citations=cite,
        tests=[UnitResult("bench", True)],
        objective=task.objective,
        candidate_context="",
        tools_used=["retrieval.search"],
        allowed_tools=["retrieval.search"],
        required_tools=["retrieval.search"],
    )


def _stable(value):
    """Exclude measured wall time and receipt clocks, preserving audit fields."""
    if isinstance(value, dict):
        clocks = {"timestamps", "at", "latency_ms", "wall_ms_measured", "wall_ms_p50"}
        return {k: _stable(v) for k, v in value.items() if k not in clocks}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def receipt_hash(receipt: dict) -> str:
    return hashlib.sha256(json.dumps(_stable(receipt), sort_keys=True).encode()).hexdigest()


def _restore_fn(task: BenchTask, dropped: list[str], budget: int):
    """Re-add dropped exact-carriers/citation carriers, up to budget."""
    cands = [uid for uid in carriers(task) if uid in dropped]
    return cands[: max(0, budget)]


def _modeled_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    return round(
        tokens_in / 1000 * PRICE_IN_PER_1K[model] + tokens_out / 1000 * PRICE_OUT_PER_1K[model], 6
    )


def run_arm(task: BenchTask, arm: str, seed: int = SEED) -> dict:
    """Run one arm on one task. Returns a JSON-able run record with receipt.

    Models each actually executed attempt using its routed model and context.
    Terminal escalation records a request, not an additional model execution.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}")
    selected = _selection(task, arm)
    dropped = [u.id for u in task.units if u.id not in selected]
    plan = _base_plan(task, arm)
    budgets = arm in ("lcc_routing_verify", "msi")

    def execute(_attempt: int) -> VerificationSubject:
        cur = list(selected) + [r for r in restored if r not in selected]
        return _subject(task, cur)

    restored: list[str] = []

    def restore(failures: list[str]) -> list[str]:
        nonlocal restored
        restored = _restore_fn(task, dropped, plan.escalation_policy.max_restorations)
        return list(restored)

    t0 = time.perf_counter()
    run = run_execution(
        task_id=task.task_id,
        plan=plan if budgets else replace(
            plan,
            escalation_policy=replace(
                plan.escalation_policy, max_retries=0, max_restorations=0
            ),
        ),
        execute=execute,
        restore=restore if budgets else None,
        receipt_id=f"{task.task_id}:{arm}:s{seed}",
        selected_units=list(selected),
        omitted_units=[{"id": d, "rationale": "bench:lexical-drop"} for d in dropped],
        versions=ReceiptVersions(
            compiler="bench-lexical-1.0", policy="planner-1.0",
            model=plan.model_class, dataset="msi-bench-7-frozen-2026-10-03",
            evaluator=EVALUATOR,
        ),
    )
    wall_ms = round((time.perf_counter() - t0) * 1000, 4)
    receipt = run.receipt
    final_ids = list(selected) + [r for r in restored if r not in selected]
    by_id = {u.id: u.content for u in task.units}
    summary = "\n".join(by_id[i] for i in final_ids)
    full_summary = "\n".join(u.content for u in task.units)
    tokens_in = approximate_token_count(task.objective + "\n" + summary)
    tokens_out = approximate_token_count(summary)
    full_tokens = approximate_token_count(task.objective + "\n" + full_summary)
    retained_tokens = approximate_token_count(summary)
    status = receipt.verification_result
    success = status == "PASS"
    model = receipt.model_class
    prot_dropped = sum(1 for u in task.units if u.protected and u.id not in final_ids)

    # Full-chain attempt accounting (R1 fix): count context and model for every
    # executed attempt. Terminal escalation is a request, not a model execution.
    cur_selected = list(selected)
    cur_model = plan.model_class
    costs = []

    def account():
        s = "\n".join(by_id[uid] for uid in cur_selected)
        tin = approximate_token_count(task.objective + "\n" + s)
        tout = approximate_token_count(s)
        return {
            "model": cur_model,
            "tokens_in": tin,
            "tokens_out": tout,
            "cost_usd_modeled": _modeled_cost(cur_model, tin, tout),
        }

    for event in receipt.decision_events:
        if event.event == "routed":
            match = re.search(r"model=([a-z_]+)", event.reason)
            if match is not None:
                cur_model = match.group(1)
        elif event.event == "restored":
            cur_selected += [uid for uid in receipt.restored if uid not in cur_selected]
        elif event.event == "failed":
            costs.append(account())
    if success:
        costs.append(account())
    assert len(costs) == run.attempts, f"attempt accounting drift: {len(costs)} != {run.attempts}"

    cost_usd_modeled = round(sum(c["cost_usd_modeled"] for c in costs), 6)
    frontier_call_modeled = sum(c["model"] == "frontier" for c in costs)
    receipt_dict = receipt.to_spec_dict()
    receipt_dict["cost"].update(
        tokens_in=sum(c["tokens_in"] for c in costs),
        tokens_out=sum(c["tokens_out"] for c in costs),
        cost_usd=cost_usd_modeled,
    )

    record = {
        "task_id": task.task_id,
        "category": task.category,
        "risk": task.risk,
        "arm": arm,
        "seed": seed,
        "outcome": status,
        "success": success,
        "model": model,
        "plan_engine": plan.engine,
        "plan_route": plan.route,
        "retained_ids": final_ids,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "retained_tokens": retained_tokens,
        "full_tokens": full_tokens,
        "execution_costs": costs,
        "cost_usd_modeled": cost_usd_modeled,
        "frontier_call_modeled": frontier_call_modeled,
        "verification_calls": run.attempts,
        "restores": len(receipt.restored),
        "retries": receipt.retries,
        "escalations": list(receipt.escalations),
        "false_deescalation": int(
            not success and model in CHEAP_MODELS and task.risk in HIGH_RISKS
        ),
        "unsafe_optimization": int(
            success and model in CHEAP_MODELS
            and task.risk in HIGH_RISKS and retained_tokens < full_tokens
        ),
        "protected_dropped": prot_dropped,
        "wall_ms_measured": wall_ms,
        "receipt": receipt_dict,
        "receipt_hash": receipt_hash(receipt_dict),
    }
    return record


def run_matrix(seed: int = SEED) -> list[dict]:
    from tasks import TASKS

    return [run_arm(t, a, seed) for t in TASKS for a in ARMS]


def digest_of(runs: list[dict]) -> str:
    """Stable digest over outcome-relevant fields (excludes wall time and
    receipt timestamps, like the sprint-6 pilot excludes timing)."""
    slim = [
        {
            "task_id": r["task_id"], "arm": r["arm"], "outcome": r["outcome"],
            "model": r["model"], "retained_ids": r["retained_ids"],
            "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
            "cost": r["cost_usd_modeled"], "verify_calls": r["verification_calls"],
            "restores": r["restores"], "retries": r["retries"],
            "escalations": r["escalations"],
        }
        for r in runs
    ]
    slim.sort(key=lambda d: (d["task_id"], d["arm"]))
    return hashlib.sha256(json.dumps(slim, sort_keys=True).encode()).hexdigest()


def aggregate(runs: list[dict]) -> dict:
    """Per-arm aggregates + derived metrics."""

    full_by_task = {(r["task_id"]): r for r in runs if r["arm"] == "full"}
    out: dict[str, dict] = {}
    for arm in ARMS:
        arm_runs = [r for r in runs if r["arm"] == arm]
        n = len(arm_runs)
        wins = sum(1 for r in arm_runs if r["success"])
        matched = [
            r for r in arm_runs
            if r["success"] and full_by_task[r["task_id"]]["success"]
        ]
        retained_matched = (
            round(sum(r["retained_tokens"] for r in matched) / len(matched), 1)
            if matched else 0.0
        )
        avoided = (
            round(
                sum(1 for r in matched
                    if full_by_task[r["task_id"]]["frontier_call_modeled"] == 1
                    and r["frontier_call_modeled"] == 0) / len(matched), 3)
            if matched else 0.0
        )
        cost = round(sum(r["cost_usd_modeled"] for r in arm_runs), 6)
        out[arm] = {
            "n": n,
            "successes": wins,
            "success_rate": round(wins / n, 4) if n else 0.0,
            "cost_usd_modeled_total": cost,
            "success_per_dollar_modeled": round(wins / cost, 2) if cost > 0 else None,
            "frontier_calls_modeled": sum(r["frontier_call_modeled"] for r in arm_runs),
            "verification_calls": sum(r["verification_calls"] for r in arm_runs),
            "restores": sum(r["restores"] for r in arm_runs),
            "retries": sum(r["retries"] for r in arm_runs),
            "escalations": sum(len(r["escalations"]) for r in arm_runs),
            "false_deescalations": sum(r["false_deescalation"] for r in arm_runs),
            "unsafe_optimizations": sum(r["unsafe_optimization"] for r in arm_runs),
            "protected_dropped": sum(r["protected_dropped"] for r in arm_runs),
            "retained_tokens_total": sum(r["retained_tokens"] for r in arm_runs),
            "retained_at_matched_success": retained_matched,
            "frontier_avoided_at_matched_success": avoided,
            "matched_n": len(matched),
            "wall_ms_p50": _p50([r["wall_ms_measured"] for r in arm_runs]),
        }
    return out


def _p50(xs: list[float]) -> float:
    s = sorted(xs)
    return round(s[len(s) // 2], 4) if s else 0.0


def pareto(agg: dict) -> list[str]:
    """Nondominated arms on (success max, cost min, retained min)."""
    arms = list(agg)
    dom: set[str] = set()
    for a in arms:
        for b in arms:
            if a == b:
                continue
            if (agg[b]["success_rate"] >= agg[a]["success_rate"]
                    and agg[b]["cost_usd_modeled_total"] <= agg[a]["cost_usd_modeled_total"]
                    and agg[b]["retained_tokens_total"] <= agg[a]["retained_tokens_total"]
                    and (agg[b]["success_rate"] > agg[a]["success_rate"]
                         or agg[b]["cost_usd_modeled_total"] < agg[a]["cost_usd_modeled_total"]
                         or agg[b]["retained_tokens_total"] < agg[a]["retained_tokens_total"])):
                dom.add(a)
                break
    return [a for a in arms if a not in dom]


def bootstrap_ci(runs: list[dict], resamples: int = BOOTSTRAP_RESAMPLES,
                 seed: int = SEED) -> dict:
    """Percentile 95% CI per arm success rate, resampling tasks with
    replacement (paired across arms: same task indices per resample)."""
    import random

    from tasks import TASKS

    tids = [t.task_id for t in TASKS]
    by_arm = {a: {r["task_id"]: r["success"] for r in runs if r["arm"] == a} for a in ARMS}
    rng = random.Random(seed)
    samples = [[rng.choice(tids) for _ in tids] for _ in range(resamples)]
    out: dict[str, dict] = {}
    for arm in ARMS:
        rates = []
        for sample in samples:
            rates.append(sum(by_arm[arm][t] for t in sample) / len(sample))
        rates.sort()
        lo = rates[int(0.025 * resamples)]
        hi = rates[int(0.975 * resamples) - 1]
        out[arm] = {"lo": round(lo, 4), "hi": round(hi, 4), "resamples": resamples}
    return out
