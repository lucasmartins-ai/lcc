# Restoration audit trail (MSI Sprint 3)

Every restored block names its motive and its origin layer in both the report
and the Context IR. There are exactly two restoration reasons, one per layer
that restores:

- `semantic_sufficiency_restoration` — layer 2 (structural): the block was
  dropped by the selector but is linked to kept content in the typed graph.
- `semantic_verifier_fail_restoration` — layer 3 (light judge): the verifier
  FAILed and the block is a graph-linked drop restored within the verifier's
  own budget.

## Reading a restore

Report (`lcc compact -r report.json`, schema `relevance-compaction-1.2`):

- `decisions[]`: the restored block has `decision: keep`,
  `reason: <one of the two above>`, and `relationships[]` listing the typed
  edges that made it restorable (e.g. `QUALIFIES:blk_…`).
- `blocks_restored`: total across both layers (≤ `--max-restorations` +
  `--verifier-max-restorations`).
- `warnings[]`: `semantic_sufficiency_restoration: restored N block(s) linked
  to kept content (…)` or `sufficiency_restoration_budget_exceeded: K
  critical blocks, restored N (max B)` when the budget ran out.

Context IR (`--emit-ir`, `context-ir/0.1`):

- `selection.rationale[<id>]`: the same per-block reason, so `lcc explain`
  audits every restore from the IR alone.
- `restoration.restored`: ids flipped drop/trim → keep, within `budget`;
  `restoration.reason` names both budgets spent.

## Budgets (explicit per layer)

| Layer | Flag | Default | Semantics |
|---|---|---|---|
| Structural | `--max-restorations` | 8 | At most 8 dropped blocks restored per pass, highest semantic risk first, deterministic tie-break by block id |
| Verifier | `--verifier-max-restorations` | 4 | At most 4 graph-linked drops restored on verifier FAIL, independent budget, one pass, no re-verify loop |

Restoration never touches `sanitized` (standalone-instruction) blocks. When the
structural budget is exceeded the output is flagged (`needs_review` via the E2
calibration) rather than trusted. Sanitized blocks are removed, not restored —
that is a safety removal, documented in the report warnings.
