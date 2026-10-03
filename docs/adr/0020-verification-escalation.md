# ADR 0020 — Layered verification + bounded escalation with receipt

Date: 2026-10-03. Status: accepted (MSI Sprint 5).

## Decision

1. Verification is a layered runner (`src/lcc/router/verify.py`,
   `EVALUATOR_VERSION verify-1.0`) emitting the spec's tri-state
   (`verification-result/0.1`): schema, task, citation, test, semantic
   (opt-in, single-shot, inherits `verifier.py` bands), policy. It
   verifies, never executes: no provider calls except through a
   caller-supplied semantic client.
2. The AgentTrace protocol is ported, not depended on: check shape
   `{id, passed, detail}`, reason-code taxonomy, gate semantics (any
   hard-layer FAIL blocks PASS). Citation snapshot match is skipped
   (needs a snapshot store; id-set resolution covers the failure class).
3. Escalation is a linear bounded machine (`src/lcc/router/escalate.py`,
   `escalation-1.0`): restore (own budget, single re-verify) -> retry
   (plan switch at most one step per retry, counted) -> ESCALATE/ABORT.
   Budgets come from the sprint-4 plan's `escalation_policy`; retry beyond
   the maximum escalates. Every transition carries its reason; a
   reason-less transition is a bug the machine cannot construct.
4. Every execution emits one Inference Receipt v0
   (`inference-receipt/0.1`) with the full decision chain. Doubt-only
   signals (uncertain/unavailable semantic judge, crashed layer) force
   REVIEW -> ESCALATE, never FAIL and never PASS.

## Reason

Complementary layers catch complementary failures (shape, facts,
citations, tests, semantics, budgets); one gate cannot. Bounds plus
counting keep retries finite and auditable; the receipt links plan,
audit, and outcome, closing the sprint-4 gap (audit was local-only).

## Alternatives considered

- Depending on AgentTrace installed: rejected (product coupling; the
  protocol shape is the reusable part).
- Mandatory LLM judge in the default path: rejected (network, cost, and
  REVIEW-heavy noise; semantic stays opt-in advisory).
- Unbounded retry-until-pass: rejected (loops hide failure; single
  re-verify per stage, exhaustion escalates).
