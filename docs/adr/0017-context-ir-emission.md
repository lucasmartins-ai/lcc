# ADR 0017: Context IR emission (compilation output contract)

Status: accepted (MSI Sprint 2).

## Decision

LCC emits a versioned, deterministic Context IR (`context-ir/0.1`) for every
relevance-compaction pass that opts in (`--emit-ir` / `emit_ir=True`). The IR is
a pure mapping over finished state — blocks, final decisions, the typed graph,
the last sufficiency verdict, the restoration log — built in one module
(`lcc.relevance.ir`), reusing `blocks.py`, `graph.py`, `decisions.py` without
duplicating them. `lcc explain` reads IR files; `lcc inspect --ir` summarizes
them; default CLI outputs are byte-identical with the flag off.

## Reason

The MSI program needs contracts before more code (Sprint 1 froze the schemas).
The IR is the first contract LCC implements: it proves every current decision
(score/selection/restoration) is expressible provider-independently, without
changing compaction behavior. Emission-on-request (not always-on) keeps the
deterministic core untouched and the overhead measurable (see Sprint 2 DONE).

## Forecloses

- A second IR dialect: the spec repo schema is normative; LCC maps onto it,
  never around it. Field requests become tracked issues, not ad-hoc fields.
- Silent drops: every dropped unit carries a rationale by construction, and
  `protected` units can never drop silently (tested, unit + property).
- Scorer identity in the envelope: decision `source` (jev/mechanical/…) is not
  recorded; reasons and policy versions are.
- Causal claims from this module: `necessity` stays `UNKNOWN` until ablation
  (Sprint 6) assigns stronger labels.

## Consequences

`report.json` stays the operational artifact; `ir.json` is the interchange
artifact. Golden fixtures (`tests/fixtures/ir/`) freeze the mapping; any
compactor change that alters IR bytes fails loudly, which is the point.
