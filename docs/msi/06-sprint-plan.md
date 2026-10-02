# Sprint Plan — Sprints 0–2 only (no speculative backlog)

## Sprint 0 — Inventory & baseline ✅ (this doc set)
Done: 01–07 + verdicts below. Acceptance: all 7 repos inspected, status verified vs code, ownership set. Do not code features in Sprint 0.

## Sprint 1 — MSI specification (spec repo + contracts)
1. Create `lucasmartins-ai/minimum-sufficient-inference` with README, docs/theory+architecture+terminology, `spec/*.schema.json` (from 05), research agenda, benchmarks/README, examples. No LCC code copy.
2. Validate schemas against ≥5 realistic workflows (coding fix, repo investigation, multi-tool task, research brief, structured decision) — fixtures in spec repo `examples/`.
3. Decide intake fate (adapter vs independent vs frozen) + get sign-off to archive `lcc-act2-router` (salvage its 6 cases).
4. Write ADRs: Context IR existence, triage-engine pluggability, verification-protocol-over-product, spec/implementation split.
- Acceptance: schemas represent all 5 fixtures; provider-independent; provenance + restore/escalate representable; versioning policy documented.

## Sprint 2 — LCC Context IR (implementation, backwards-compatible)
5. Implement Context IR emission in LCC (`units` + provenance + graph edges + protected + selection + sufficiency + restoration), deterministic serialization; every dropped unit explainable; protected never silently dropped.
6. Property tests: subset-ness, provenance survival, restore-from-original, determinism; golden fixtures (freeze 3–5 reports as IR).
7. `lcc inspect` shows IR summary; `lcc explain` reads IR.
- Acceptance: existing CLI behavior unbroken; IR round-trips; all selected units carry provenance.

## Out of scope until Sprint 3+
Planner, closed-loop verification, ablation harness, MSI-Bench, DX polish, orchestrator integration, paper. Each Sprint 1–2 issue must state: problem, context, deliverable, acceptance criteria, dependencies, tests, documentation impact.
