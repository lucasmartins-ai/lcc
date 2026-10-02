# ADR 0019 — Deterministic-first inference planner, pluggable engines

Date: 2026-10-02. Status: accepted (MSI Sprint 4).

## Decision

1. The inference planner is a pure mapping
   `(Task Contract risk/type, TaskFeatures) -> InferencePlan`
   in one module (`src/lcc/router/plan.py`, `POLICY_VERSION planner-1.0`).
   It plans, never executes: no provider calls, no network.
2. Deterministic baseline first: it ports `choose_route` semantics plus a
   fail-closed risk overlay (cheap never silent on high/unknown risk).
   The Jev triage gate (`escalate OR risk >= 0.60 OR conf < 0.65`,
   inherited as defaults) lives in `jev-adapter` only, and `rules` is a
   static risk table. A mock engine with the same interface passes the
   same contract tests.
3. Audit (`reasons`, `policy_version`, `engine`, `route`) travels in the
   LCC wrapper, not in the spec dict (spec v0.1 forbids additional
   properties). The receipt (sprint 5+) links them.
4. No `small-local-model` engine and no threshold tuning in this sprint
   (YAGNI; needs paired quality evidence first).

## Reason

The deterministic policy already routes low-risk cases correctly and its
failures are legible (named reasons, versioned policy). The triage gate
was calibrated on SYNTHETIC data upstream, so promoting it to default
without a paired quality comparison would launder an unvalidated
threshold into the critical path. Correction rule applied: an adapter
that does not beat the baseline on paired quality stays optional, never
default — the PILOT comparison (N=5, `SPRINT_4_DONE.md`) shows parity by
construction on neutral triage, which is exactly why the baseline stays
default.

## Alternatives considered

- Jev-first routing: rejected (unvalidated thresholds, provider coupling).
- Tuning cutoffs on the 5 PILOT fixtures: rejected (N=5 cannot support
  generalization; any tuning would be overfitting).
- Small-local-model engine now: rejected (no evidence; stub documented).

## Forecloses

- No provider import in `plan.py` (a future engine needing one must add a
  new ADR and keep the three existing engines network-free).
- No golden updates without a written root cause.
- No threshold changes without a paired experiment at N > PILOT.

## Reversibility

Bump `POLICY_VERSION`, keep the old mapping behind the version string,
and re-freeze goldens with root-cause notes. Engines are additive:
adding `small-local-model` later means one new class + goldens, no
changes to the three existing paths.
