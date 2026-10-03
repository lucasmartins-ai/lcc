# Layered verification (MSI Sprint 5)

Code: `src/lcc/router/verify.py` (`EVALUATOR_VERSION verify-1.0`).
Spec: `verification-result/0.1` (spec repo, read-only here). The runner
**verifies, never executes**: no provider calls except through a
caller-supplied semantic client; every other layer is pure stdlib.

Protocol ported from `agenttrace-studio` (read-only reference, no
dependency): check shape `{id, passed, detail}`, reason-code taxonomy, gate
semantics (any hard-layer FAIL blocks PASS), tri-state + single-shot from
`src/lcc/relevance/verifier.py`.

## Layers (each failure carries a closed reason code + recommended action)

| layer | checks | FAIL reason | action |
|---|---|---|---|
| schema | required fields present, non-empty | `output_schema_invalid` | ABORT |
| task | required facts present | `required_fact_missing` | RETRY |
| task | forbidden claims absent | `forbidden_claim_present` | RETRY |
| citation | ids resolve against supplied set | `citation_unresolved` / `citation_missing` | RESTORE_CONTEXT |
| test | supplied outcomes all green | `test_failed` | RETRY |
| semantic | opt-in judge, confident insufficiency | `semantic_insufficient` | RESTORE_CONTEXT |
| policy | latency / cost within budget | `latency_budget_exceeded` / `cost_budget_exceeded` | ESCALATE |
| policy | tools within allowlist | `tool_not_allowed` | ABORT |
| policy | required tools used | `required_tool_missing` | ADD_TOOL |

Doubt-only reasons (`semantic_uncertain`, `semantic_unavailable`,
`layer_crashed`) can only force REVIEW, never FAIL. REVIEW always maps to
ESCALATE: doubt escalates, never passes silently. Unknown profile and
unmapped failures also degrade to REVIEW/ESCALATE (fail-closed).

## Profiles

`light` = schema + task. `standard` = light + citation + test + policy.
`strict` = standard + semantic (advisory skip when no client is supplied;
the skip passes and is recorded, it is not evidence).

## Defaults are honest, not silent

Unconfigured layers pass with a `not_configured` detail (mirrors the
AgentTrace budget checks): no citations required, no tests supplied, no
budget, no tool policy. What is not checked is named, never hidden.

## Correction rule

A layer yielding REVIEW in >50% of runs without a matching FAIL is
recalibrated to advisory with written evidence (sprint gate). The semantic
layer satisfies this by construction: absent client = recorded skip;
uncertain or crashed judge = REVIEW. Ported-but-skipped: citation snapshot
match (needs a snapshot store; the id-set check covers resolution).
