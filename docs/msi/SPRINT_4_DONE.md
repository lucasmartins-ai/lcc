# Sprint 4 — DONE (PASS)

- Commit: branch `msi/sprint-4-inference-planner`, parent HEAD `3e8e006`
  (single commit with code + this file; exact sha in the PR).
- Gate: `SPRINT_3_DONE.md` = PASS; `src/lcc/router/{policy,features,schemas}.py`
  re-read; triage gate `scripts/integrate_agy_results.py:150-152`
  (`escalate OR risk>=0.60 OR conf<0.65`) re-read in
  `/Users/Master/msi-repos/cognitive-triage-benchmark` (read-only, untouched).

## Acceptance

- [x] Engine plugável com baseline determinístico + 1 adapter real → PASS.
  One interface `PlannerEngine.plan(PlannerInput)` (`src/lcc/router/plan.py`);
  engines `deterministic` (ports `choose_route` + risk overlay),
  `jev-adapter` (triage gate, defaults `0.65/0.60`, delegates when quiet),
  `rules` (static risk table). Evidence: `plan_with_engine` dispatches all
  three; `test_all_three_engines_schema_valid_on_same_inputs` green.
- [x] 10–15 golden decisions verdes e estáveis → PASS. 12 goldens frozen in
  `tests/test_inference_plan.py` (`GOLDENS`, 5 routes × 7 fallback actions
  covered); `pytest tests/test_inference_plan.py` → 27 passed.
- [x] Invariante fail-closed testada → PASS.
  `test_fail_closed_cheap_never_silent` (high|unknown × 4 feature shapes × 3
  engines) + `test_invalid_risk_defaults_unknown_fail_closed` green: cheap
  (`local_tiny|local_small`) is upgraded to `frontier/full/strict + ESCALATE`,
  never emitted silently.
- [x] Decisão 100% auditável → PASS. Every plan carries `reasons[]`
  (route + branch + risk + engine/triage notes), `policy_version`
  (`planner-1.0`), `engine`, `route`; asserted in `test_goldens_exact`
  (`len(reasons) >= 2`, version, engine). Audit lives in the LCC wrapper,
  not in `to_spec_dict()` (spec v0.1 forbids additional properties).
- [x] `SPRINT_4_DONE.md` em PASS (this file, `docs/msi/`).

## Testes

- `PYTHONPATH=src python3 -m pytest tests/test_inference_plan.py -p no:cacheprovider`
  → **27 passed** (12 exact goldens, spec validity ×3 engines, route/action
  coverage, mock-engine swap, Jev gate ×4, fail-closed ×3, invalid-risk,
  unknown-engine, spec-dict provider hygiene).
- `PYTHONPATH=src python3 -m pytest tests/ -p no:cacheprovider`
  → **752 passed, 6 skipped, 2 failed** — both failures pre-existing and
  outside this diff (same proof as sprints 2–3: `test_metadata` asserts
  installed-dist vs staged `pyproject.toml` bump from another WIP;
  `test_docs` missing-link list contains zero entries from/to any file
  created or edited here — full list: only `SPRINT_1_DONE.md`,
  `SPRINT_3_DONE.md` and `prompts/sprint-0*/01/04/05/08` forward refs).
- `.venv/bin/ruff check` on `plan.py`, `test_inference_plan.py`,
  `router/__init__.py` → clean. mypy
  (`--python-version 3.14 --ignore-missing-imports --follow-imports=silent`)
  on `plan.py` → `Success: no issues found`; project-config mypy remains
  unrunnable env-wide (numpy 2.x stubs × pin 3.11, pre-existing, untouched
  files fail identically).
- Provider-coupling grep on schemas (sprint-1 invariant, re-verified):
  `grep -rEi "jev|openai|anthropic|gpt|claude" spec/` in
  `/Users/Master/msi-repos/minimum-sufficient-inference` → no output,
  exit 1. Code label `jev-adapter` appears ONLY in the audit envelope
  (`engine`, reasons); all `to_spec_dict()` outputs are clean, asserted by
  `test_no_provider_fields_in_spec_dict`.

## Benchmark

PILOT, N=5 (sprint-1 fixtures; contracts REAL, features hand-mapped per
fixture and documented below — data HYBRID, evidence EXPERIMENTAL, no
generalization claim). Command reproduces exactly (workdir `/Users/Master/LCC`,
`PYTHONPATH=src`); feature map is the table, triage neutral
`JevTriage(approve, 0.9, 0.2)` vs escalated `JevTriage(escalate, 0.9, 0.1)`:

| fixture (risk) | representative features | deterministic | jev-adapter neutral | match |
|---|---|---|---|---|
| 01-coding-fix (medium) | savings 0.3, noise 0.3 | local_small / COMPRESS_THEN_LOCAL | local_small / COMPRESS_THEN_LOCAL | yes |
| 02-repo-investigation (medium) | 800 tokens, plain | local_small / LOCAL_THEN_VERIFY | local_small / LOCAL_THEN_VERIFY | yes |
| 03-multi-tool-task (high) | external-knowledge, 1200 tokens | frontier / REMOTE_DIRECT | frontier / REMOTE_DIRECT | yes |
| 04-research-brief (low) | trivial 200 tokens | local_small / LOCAL_THEN_VERIFY | local_small / LOCAL_THEN_VERIFY | yes |
| 05-structured-decision (high) | trivial 200 tokens | frontier / LOCAL_THEN_VERIFY (fail-closed upgrade, route kept for trace) | same | yes |

Route distribution (both engines, neutral triage): cheap 3/5, frontier 2/5 —
projected, not measured (no execution, no latency/cost observed). Paired
comparison baseline-vs-jev-adapter: 5/5 identical (parity by construction on
quiet triage — hence baseline stays default per correction rule). Paired
escalated-triage variant (same N=5): 5/5 forced
`frontier/strict/ESCALATE/escalate_to:human` (route preserved, model +
verification + fallback upgraded) — the gate is the ONLY divergence.

## Docs/ADRs

- Created: `docs/lcc/inference-planning.md` (engines, route→plan table,
  fail-closed rules, per-risk examples, limits; LCC chosen over spec repo /
  `docs/msi/` to avoid duplication per sprint prompt), `docs/adr/0019-
  deterministic-inference-planner.md`, `tests/test_inference_plan.py`.
- Altered: `src/lcc/router/plan.py` (new, ~380 lines, zero new deps, no
  network), `src/lcc/router/__init__.py` (plan exports only),
  `docs/adr/README.md` (+0019 row).

## Deliberately skipped

- `small-local-model` engine: stub documented in planning doc + ADR-0019;
  no paired evidence it beats the baseline (YAGNI).
- Threshold tuning (`0.65/0.60`, `choose_route` cutoffs): inherited as
  defaults; N=5 cannot support tuning (would be overfitting); needs a
  paired experiment at N > PILOT.
- CHANGELOG entry: deferred — `CHANGELOG.md` carries unrelated staged +
  unstaged hunks from another WIP;   touching it would sweep another WIP's hunks.
  Add on rebase/merge.
- CLI surfacing of the planner: library-only; no workflow needs it yet.
- `LOCAL_ONLY` via deterministic policy: unreachable in `choose_route`
  today (pre-existing); mapping supports it and `rules` emits it, so all 5
  routes stay covered by goldens.

## Known limitations

- PILOT N=5 with hand-mapped features: route-distribution only; no quality,
  latency, or cost claim (quality + cost together required from sprint 5 on).
- Triage thresholds are SYNTHETIC-calibrated upstream; treated as defaults,
  never truth.
- Audit (`reasons`, `policy_version`) is outside the spec dict; the receipt
  (sprint 5) must link plan + audit + outcome or auditability is local-only.
- Sprint-1 fixture `05-structured-decision` pairs `high` + `local_tiny`
  (spec-valid); the planner refuses to EMIT that combination silently —
  stricter than the spec by design, documented in planning doc.
- Project-config mypy unrunnable in this env (pre-existing, see Testes).

## Next

Sprint 5 implements verification/escalation execution (bounded restore →
retry → escalate chain) on top of the frozen `planner-1.0` plans and their
audit envelope.
