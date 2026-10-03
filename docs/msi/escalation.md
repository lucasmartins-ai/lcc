# Escalation machine + inference receipt (MSI Sprint 5)

Code: `src/lcc/router/escalate.py` (`ESCALATION_POLICY_VERSION
escalation-1.0`). Plans come from `docs/lcc/inference-planning.md`
(`planner-1.0`); verification from `docs/msi/verification.md`
(`verify-1.0`). The machine **drives, never judges**: all verdicts come
from the verification runner.

## Chain (linear, bounded, counted)

1. `routed`: plan engine/route/reasons recorded.
2. `execute(0)` -> verify. PASS ends the run.
3. Non-PASS with RESTORE_CONTEXT and restorations left: `restored` event,
   execute again, single re-verify (no further restore; sprint-3 rule).
4. Still non-PASS with a retryable action (RETRY, INCREASE_REASONING,
   SWITCH_MODEL, ADD_TOOL) and retries left: plan switch recorded as a
   second `routed` event (INCREASE_REASONING steps the budget ladder,
   SWITCH_MODEL steps the tier ladder, RETRY/ADD_TOOL keep the plan),
   execute again, re-verify.
5. Still non-PASS: `escalated` to the plan's `escalate_to` (or `abort`).
   Retry beyond the maximum lands here.

Budgets are the plan's `escalation_policy` (`max_retries`,
`max_restorations`, `escalate_to`); every attempt, restore, retry, and
escalation is counted on the receipt. A transition without a recorded
reason is a bug the machine cannot produce: events are constructed with
their reason (`tests/test_verification.py` asserts non-empty reasons on
all golden chains).

## Receipt v0

`ExecutionReceipt.to_spec_dict()` validates against
`inference-receipt/0.1`: task, selected units, omitted units with
rationale (nothing silently discarded), model + reasoning actually used,
tools used, verification profile + result, restored / retries /
escalations, measured cost, pinned versions, timestamps, decision events
(`dropped | restored | routed | failed | escalated`), outcome + evaluation.
Three chains are frozen as exact goldens: direct PASS, PASS-via-restore,
ESCALATE after one counted retry.

## Overhead (measured, not claimed)

Verification-only wall time over the 30 curated adversarial corpora
(`benchmarks/research/adversarial_cases.py`, offline, N=30, one
`run_verification` per corpus on the compiled text): see
`docs/msi/SPRINT_5_DONE.md` for the table and reproducer. Layers are pure
stdlib string/set scans except the opt-in semantic judge, which stays out
of the default path; overhead is reported next to the distribution, never
hidden inside it.
