# Sprint 1 — DONE (PASS)

- Commit: `284f11fd44f6046ef950ea8f74cfb25287bb804f` (LCC HEAD; spec work lives in working tree + local spec dir, no commit/push per protocol §anti-slop and user instruction)
- Spec location (local-only adaptation): `/Users/Master/msi-repos/minimum-sufficient-inference` (repo-map allowed `gh repo create` OR local folder when offline; user forbade GitHub/push/PR, protocol forbids push/PR — so local folder, no remote)

## Acceptance

- [x] Repo/árvore completa → PASS. Local dir holds README, `docs/theory.md`, `docs/architecture.md`, `docs/terminology.md`, `docs/versioning.md`, `docs/adr/0001-0004.md`, `spec/*.schema.json` (5), `research/research-agenda.md`, `research/methodology.md`, `benchmarks/README.md`, `examples/` (5 + 1 negative), `scripts/validate_examples.py`. Evidence: `ls -R /Users/Master/msi-repos/minimum-sufficient-inference` lists all files (verified 2026-10-02). Deviation: public `gh` repo NOT created — forbidden by user + protocol; local folder used instead.
- [x] 5/5 fixtures validam; 1/1 negativa falha pelo motivo esperado → PASS. Evidence: `python3 scripts/validate_examples.py` (workdir = spec dir) → 25/25 `PASS <fixture> :: <schema>` (5 fixtures × 5 schemas) + `EXPECTED-FAIL negative-provider-field.json :: context_ir: ValidationError` + final `ALL GREEN`. Negative fails on `openai_temperature` extra property in `context_ir.units[0]` (additionalProperties false) — the expected provider-coupling rejection.
- [x] Grep de provider nos schemas retorna vazio → PASS. Evidence: `grep -rEi "jev|openai|anthropic|gpt|claude" spec/` → no output, exit 1 (verified 2026-10-02).
- [x] Proveniência + restauração + escalonamento representáveis em ≥1 fixture cada → PASS. Proveniência: all 5 bundles carry `context_ir.units[].provenance` (origin/collected_at/transform), e.g. `examples/01-coding-fix.json: units[0].provenance`. Restauração: `examples/02-repo-investigation.json` (`restoration.restored: ["blk_0012_cccc33"]`, reason recorded) and `examples/03-multi-tool-task.json` (restored `blk_0023_hh7788`). Escalonamento: `examples/03-multi-tool-task.json` (`inference_plan.fallbacks` contains ESCALATE, `escalation_policy.escalate_to: human`, `verification_result.status: FAIL / recommended_action: ESCALATE`, receipt `escalations: ["human"]`).
- [x] `SPRINT_1_DONE.md` no repo LCC (`docs/msi/`) → PASS (this file).

## Testes

- `python3 scripts/validate_examples.py` (jsonschema 4.26.0, Python 3.14.3) → ALL GREEN: 25 passed, 0 failed; negative correctly rejected (1/1). One correction loop needed: initial fixtures placed `trimmed` at IR top level instead of inside `selection`; fixed via moving `trimmed` into `selection` (fixtures 02–05), re-ran → green. No LCC test suite touched (sprint 1 = spec-only, OUT scope: no LCC code).

## Benchmark

N/A (sprint sem medição, por design). Validação = matriz 5 fixtures × 5 schemas, tudo verde — sem claims de performance, sem números.

## Docs/ADRs

Created in spec dir: `README.md`, `docs/theory.md`, `docs/architecture.md`, `docs/terminology.md`, `docs/versioning.md`, `research/methodology.md`, `research/research-agenda.md`, `benchmarks/README.md`, `docs/adr/0001-context-ir.md` (IR existence), `docs/adr/0002-triage-pluggability.md`, `docs/adr/0003-verification-protocol.md`, `docs/adr/0004-spec-implementation-split.md`. Schemas: `spec/task-contract.schema.json`, `spec/context-ir.schema.json`, `spec/inference-plan.schema.json`, `spec/verification-result.schema.json`, `spec/inference-receipt.schema.json` — all with per-field `description`, `required`, `additionalProperties: false`, closed enums (relationship 7 types, necessity 6 labels, task_type 7, model_class 4, reasoning_budget 4, profiles, triggers 3, actions 7, statuses 3, escalate_to 3, decision_events 5).

## Deliberately skipped

- Public `gh repo create` + push/PR: skipped per protocol anti-slop rule (no push/PR) and explicit user instruction (local-only, no GitHub). Revisit only on explicit user sign-off.
- Intake-fate decision + `lcc-act2-router` archive sign-off (sprint-plan item 3): noted as deferred — needs owner sign-off, no unilateral archive; tracked under Known limitations.
- No LCC code, routing/verification code, new deps, CLI: OUT scope per sprint prompt.

## Known limitations

- `python -m json` fallback not needed (jsonschema present); validation depends on jsonschema 4.26.0.
- Fixture `unit.id` pattern `^blk_[0-9a-z_]+$` enforced; real-world id collisions/determinism rules arrive in sprint 2 (serialization).
- Intake-fate (adapter vs independent vs frozen) and act2 archive sign-off still open — requires owner decision, not taken unilaterally.
- Field requests discovered during sprint-2 implementation must become tracked issues, not ad-hoc fields (per ADR-0004).

## Next

Sprint 2 implements Context IR emission in LCC (backwards-compatible) against these frozen v0 schemas.
