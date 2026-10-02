# Context IR (MSI Sprint 2)

Versioned, deterministic Intermediate Representation of a finished
relevance-compaction pass, conforming to `context-ir/0.1` from the
`minimum-sufficient-inference` spec repo. One file emits it:
`src/lcc/relevance/ir.py` (pure mapping, no scoring, no network).

## Emitting

```bash
lcc compact dossier.md -q "<objective>" --provider mechanical --emit-ir ir.json
```

`--emit-ir` is opt-in. Without it, `compact` outputs are byte-identical to
before (same prompt, same report). The IR is also available from Python:

```python
from lcc.relevance import RelevanceCompactionRequest, compact_context

result = compact_context(RelevanceCompactionRequest(
    text=text, question=objective, provider="mechanical",
    emit_ir=True, source_origin="dossier.md",
))
ir = result.context_ir  # dict, context-ir/0.1; None when emit_ir=False
```

## Reading

```bash
lcc explain ir.json --only drop   # IR carries unit bytes inline; --source optional
lcc inspect dossier.md --ir ir.json
```

`explain` detects the `context-ir/0.1` envelope and audits kept/trimmed/dropped
from `selection` + `rationale`. `inspect --ir` prints the IR summary table; the
normal inspection output is unchanged.

## Guarantees

- **Subsetness**: kept/trimmed/dropped partition the unit ids, disjointly.
- **Provenance**: every unit carries `provenance` (origin/collected_at/transform);
  every selected unit therefore carries it.
- **Explainability**: `selection.rationale` holds a non-empty reason for every
  unit, so every drop is explainable (`explain` covers 100% of drops).
- **Protected**: `protected` units are never silently dropped (dedicated unit +
  seeded property tests in `tests/test_context_ir.py`).
- **Restored-in-original**: `restoration.restored` ⊆ unit ids, within `budget`.
- **Determinism**: same input → same bytes (index-ordered lists, edges sorted by
  `(from, to, type)`, sorted-key serialization). The only timestamp,
  `provenance.collected_at`, defaults to `2026-10-02T00:00:00Z`; override it
  (`RelevanceCompactionRequest(ir_collected_at=...)`) when audit truth matters
  more than byte-stability.
- **Provider-independence**: the envelope has no provider/model fields. Decision
  `source` (which scorer judged) is intentionally not recorded; only the reason
  and the policy version are.
- **`necessity` is always `UNKNOWN`**: causal labels arrive with the ablation
  harness (MSI Sprint 6), never from this emitter.

## Mapping report-1.2 → IR v0.1

| IR field | Source in the compaction pass |
|---|---|
| `units[].content/source` | verbatim `TextBlock.text`, `origin:lines` |
| `units[].provenance` | `origin` (= `source_origin`), `collected_at`, `transform: none` |
| `units[].relevance` | decision score, else 1.0 (keep) / 0.0 (drop) |
| `units[].protected` | `TextBlock.protected` |
| `units[].relationships` / top-level `relationships` | `graph.py` edges touching the unit / all edges |
| `selection` | final keep/trim/drop + `POLICY_VERSION` + per-id reasons |
| `sufficiency` | last structural verdict (sufficient/missing/confidence; 0.0 when unchecked) |
| `restoration` | ids flipped to keep by bounded restoration + both budgets in `reason` |

## Limits

- `transform` is always `none`: IR emission runs on raw input text, not on
  cleaned/deduped pipeline output (pipeline wiring is a later sprint).
- `task_id` defaults to `lcc-<12 hex of objective>`; pass `task_id=` to link an
  IR to its Task Contract.
- Restoration is exercised structurally here; the trigger path (semantic judge
  drops a linked block, sufficiency restores it) is covered with a fake-Jev test
  because no network judge runs in CI.
