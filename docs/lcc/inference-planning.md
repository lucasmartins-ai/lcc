# Inference planning (MSI Sprint 4)

Code: `src/lcc/router/plan.py` (`POLICY_VERSION planner-1.0`).
Spec: `inference-plan/0.1` (spec repo, read-only here). The planner
**plans, never executes**: no provider calls, no network, no threshold
tuning inside this module.

## Engines (one interface)

`PlannerEngine.plan(PlannerInput) -> InferencePlan`. Input bundles the
Task Contract slice (`risk_level`, `task_type`, `allowed_tools`) with the
router's `TaskFeatures` (token/noise/ambiguity signals) and an optional
`JevTriage(decision, confidence, escalate_risk)` signal.

- `deterministic` (default): `choose_route(features, policy)` semantics,
  then a fail-closed risk overlay. The only engine that reads `TaskFeatures`
  routing logic.
- `jev-adapter`: same baseline, plus the triage gate inherited from
  `cognitive-triage-benchmark/scripts/integrate_agy_results.py:151` —
  escalate iff `decision == "escalate" OR escalate_risk >= 0.60 OR
  confidence < 0.65`. Thresholds are **defaults, not truth** (SYNTHETIC-
  calibrated upstream); configurable per-instance. On fire: force
  `frontier + strict + ESCALATE`, `escalate_to: human`. Otherwise identical
  to baseline plus a `jev_no_escalation` reason.
- `rules`: static risk table, no feature inspection (`low -> local_tiny`,
  `medium -> fast_hosted`, `high|unknown -> frontier+strict+ESCALATE`).
  Exists so the interface has a second independent implementation and so
  `LOCAL_ONLY` has a reachable emitter (the deterministic policy never
  returns it today).

`small-local-model` is a documented stub, not code (YAGNI: no paired
evidence it beats the baseline; see ADR-0019).

## Route -> plan mapping (deterministic)

| route | model | reasoning | context | verification |
|---|---|---|---|---|
| LOCAL_ONLY | local_tiny | none | minimal | light |
| LOCAL_THEN_VERIFY | local_small | low | minimal | standard |
| COMPRESS_THEN_LOCAL | local_small | low | compiled | standard |
| COMPRESS_THEN_REMOTE | fast_hosted | medium | compiled | standard |
| REMOTE_DIRECT | fast_hosted (frontier if high/unknown) | medium (high if high/unknown) | full | standard (strict if high/unknown) |

Fallbacks are deterministic per branch (all carry `VERIFY_FAIL ->
RESTORE_CONTEXT` first): local branches add `INCREASE_REASONING`/`RETRY`;
`COMPRESS_THEN_REMOTE` adds `SWITCH_MODEL`; `REMOTE_DIRECT` adds
`SWITCH_MODEL` (or `ESCALATE` when high/unknown); external-knowledge tasks
add `ADD_TOOL`; `manual_review` ends in `ESCALATE` + `ABORT`.
Escalation: `max_retries 2, max_restorations 4` (verifier budget, ADR-0018);
`escalate_to: human` for high/unknown/manual_review, else `frontier`.

## When NOT to route cheap (fail-closed)

Cheap = `local_tiny | local_small`. Rules, enforced in code
(`_fail_closed_overlay`, tested):

1. `risk high|unknown` + cheap route -> upgrade to `frontier/full/strict`
   (reason `fail_closed_risk_upgrade:cheap->frontier`). Cheap is never
   emitted silently for high/unknown risk.
2. Every high/unknown plan carries an `ESCALATE` fallback and `strict`
   verification, even if the route was already remote.
3. Unknown/unparseable `risk_level` defaults to `unknown` (fail-closed).
4. The Jev gate firing forces `frontier/strict/human` regardless of features.

Note: sprint-1 fixture `05-structured-decision` pairs `high` risk with
`local_tiny` (spec-valid at v0.1). The planner is stricter than the spec
by design; the spec permits it, the planner refuses to emit it silently.

## Auditability

Every plan carries `reasons[]` (route + per-branch reasons + risk +
engine/triage notes), `policy_version` (`planner-1.0`), `engine`, and
`route`. These live in the LCC wrapper, NOT in `to_spec_dict()`:
spec v0.1 has `additionalProperties: false`, so audit fields would break
validation. The Inference Receipt (sprint 5+) links plan + audit + outcome.

## Examples per risk profile

- low, trivial (`trivial-low-local`): `local_small/low/minimal/standard`,
  `LOCAL_THEN_VERIFY`, fallbacks restore/increase-retry.
- medium, noisy (`noisy-small-medium`): `local_small/low/compiled/standard`,
  `COMPRESS_THEN_LOCAL`.
- medium, external (`external-medium`): `fast_hosted/medium/full/standard`,
  `REMOTE_DIRECT`, includes `ADD_TOOL`.
- high, manual review (`manual-review-high`): `frontier/high/full/strict`,
  `REMOTE_DIRECT`, `ESCALATE` + `ABORT`, `escalate_to: human`.
- high/unknown with cheap features (`high-risk-cheap-upgrade`,
  `unknown-risk-cheap`): route stays `LOCAL_THEN_VERIFY` for traceability
  but the plan is upgraded to `frontier/full/strict + ESCALATE`.

## Limits

- Thresholds (`0.65/0.60`, `choose_route` cutoffs) are inherited, not
  optimized here; tuning needs a paired experiment (out of scope).
- No cost/latency claims: the PILOT table in `SPRINT_4_DONE.md` (N=5) is
  route distribution only.
