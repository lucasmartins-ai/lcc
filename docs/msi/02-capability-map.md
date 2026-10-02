# MSI — Capability Ownership Matrix (post-inventory, corrected)

| Capability | Owner | Status | Evidence |
|---|---|---|---|
| Intent intake → readiness | LCC `src/lcc/intake/` | implemented | `parser.py: ReadinessState` ×4, pipeline composes |
| Portable intake spec/installer | agentic-prompt-intake | existing, duplicated | v0.4.0, 3 states, no BLOCKED; LCC is superset |
| Deterministic clean/dedupe/budget | LCC core | implemented | `cleaning/`, `token_budget/`, 283+ tests |
| Relevance compaction (verbatim) | LCC `relevance/` | implemented | mechanical/laya/jev, trim, decisions cache |
| Context IR | LCC | **design** (missing) | graph.py edges + 1.2 report exist; no versioned schema |
| Sufficiency (structural) | LCC `sufficiency.py` | implemented | dependency guard, fail-closed |
| Sufficiency (semantic) | LCC `verifier.py` | experimental | PASS/REVIEW/FAIL, FAIL band unobserved |
| Restoration loop | LCC compactor | partial | bounded restore, `blocks_restored`; no retry/escalate chain |
| Provenance/audit trail | LCC (per-block) + recallgraph (reference) | partial | decisions carry reason/policy; full lineage = gap |
| Cognitive triage | pluggable interface, Jev adapter | experimental | triage-benchmark gate `(decision,conf,risk)→route`; Jev NOT hard dep |
| Inference planning/routing | LCC `router/` (+ MSI spec) | partial → planned | deterministic `choose_route` exists; budget/risk-aware planner = gap |
| Verification (assertions/citations/gates) | AgentTrace-derived protocol | partial | `checks.py` 9 checks, `ci_gate.py`, citation_auditor |
| Causal ablation harness | MSI research | planned | only comparative/AB exists; no remove-and-replay |
| Benchmark (MSI-Bench) | MSI-Bench | planned | stress matrix + AB are precursors, not the bench |
| Inference Receipt | MSI | planned | report.json is precursor, not receipt |
| Local execution + escalation | LCC `agents/` + `router/` | implemented (narrow) | Gemma/Qwen + Fireworks; generic model routing = gap |
| Real-world integration | lookaorchestrator (testbed) | planned | private, unmeasured |

## Duplication map

- `agentic-prompt-intake` ⟷ `LCC intake/`: intake repo fully covered. Action: MERGE-as-spec-only or ARCHIVE.
- `lcc-act2-router` ⟷ `LCC cleaning/pipeline/`: act2 is strict subset, predates router+relevance. Action: ARCHIVE.
- `cognitive-triage-benchmark` gate ⟷ future MSI triage interface: keep interface, not implementation. Action: EXTRACT.
- `agenttrace-studio` checks/gates ⟷ future MSI verification: keep protocol, not product dep. Action: EXTRACT.
- `recallgraph-ai` provenance/risk ⟷ future receipt/audit: patterns only. Action: reference, no import.
