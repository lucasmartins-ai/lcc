# Sprint 5 — DONE (PASS)

- Commit: working tree (no commit/push/PR per protocol anti-slop rule; user
  asked to commit + PR only "if safe" — unsafe here, see Deliberately
  skipped. HEAD `e285adb` on `msi/sprint-4-inference-planner`)
- Gate: `SPRINT_4_DONE.md` = PASS; `agent_api/evals/checks.py` (9 checks,
  shape + taxonomy) + `ci_gate.py` (thresholds, 100%-or-block) re-read in
  `/Users/Master/msi-repos/agenttrace-studio` (read-only, untouched);
  `src/lcc/relevance/verifier.py` (tri-state + single-shot) re-read.

## Acceptance

- [x] Falha de verificação jamais silenciosa → PASS. 1 injection test per
  layer (schema/task×2/citation/test/semantic×2/policy×3) + crash +
  unknown-profile: every non-PASS lands in `failures` with reason code.
  Evidence: `tests/test_verification.py` 19/19 green (below).
- [x] Todo escalonamento tem motivo; retries limitados e contados → PASS.
  Retry-beyond-max (max_retries=1, always-fail) → ESCALATE with counted
  retry; restore-budget-zero skips the restore stage; all golden events
  carry non-empty reasons. Evidence: `test_retry_beyond_max_escalates_with_reason`,
  `test_restore_budget_zero_skips_restore_stage`, golden event assertions.
- [x] Receipt contém a cadeia de decisão completa → PASS. 3 exact-frozen
  goldens (direct PASS, PASS-via-restore, ESCALATE after 1 counted retry),
  all valid against `inference-receipt/0.1`; verification outcomes valid
  against `verification-result/0.1`. Evidence: `test_golden_*` + jsonschema.
- [x] Overhead de verificação publicado → PASS. Table below (CURRENT,
  CURATED N=30 adversarial corpora × intact/stripped = 60 runs, offline,
  deterministic layers only, standard profile).
- [x] `SPRINT_5_DONE.md` em PASS (this file, `docs/msi/`).

## Testes

- `PYTHONPATH=src python3 -m pytest tests/test_verification.py -p no:cacheprovider` → **19 passed**
  (11 injection/limit/profile, 3 golden receipts, schema validity throughout,
  provider-hygiene, quoted/unicode regression).
- `python3 -m pytest tests/ -p no:cacheprovider` (system interpreter) →
  **774 passed, 5 skipped, 0 failed**. Collected 779 = 757 at HEAD +
  19 new here + 3 from another WIP's staged `test_chatgpt_server.py`
  change (foreign, untouched by this sprint; verified via clean-worktree
  collect-only diff, worktree removed after). All 5 skips are env/opt-in
  (tiktoken assets, live Laya, Jev key), same set as HEAD. No regressions.
- `.venv/bin/ruff check` on `verify.py`, `escalate.py`, `router/__init__.py`,
  `test_verification.py` → clean. mypy
  (`--python-version 3.14 --ignore-missing-imports --follow-imports=silent`,
  same workaround as sprints 2–4) on `verify.py`, `escalate.py` → clean.
- Provider-coupling re-check (sprint-1 invariant): receipt + verification
  spec dicts contain no `jev|openai|anthropic|gpt|claude`
  (`test_no_provider_fields_in_spec_dicts`); `grep -rEi` on `spec/` still
  empty (no schema touched).
- 1 correction loop: benchmark harness exposed a real layer gap —
  `layer_task` searched only the JSON dump, so facts with quotes/newlines
  (escaped `\"`, `\\n`) and non-ASCII (escaped `\uXXXX`) never matched
  (4 structured + 1 unicode adversarial cases failed intact). Fixed at root
  cause in `verify.py::_search_texts` (dump `ensure_ascii=False` + raw
  recursive string concatenation, both haystacks, one place) + empty-fact
  guard; regression test `test_task_layer_matches_quoted_unicode_…` green.

## Benchmark

N=30 CURATED (`benchmarks/research/adversarial_cases.py`, offline,
2026-10-03); per case one intact subject (fact present) + one stripped
subject (fact absent), `standard` profile, deterministic layers only;
machine runs use the sprint-4 deterministic low-risk plan
(max_retries=2). Evidence: CURRENT. Reproducer: inline script (not
committed) — build intact/stripped `VerificationSubject` per case,
`run_verification` timed with `perf_counter`, `run_execution` counted.

| run | result |
|---|---|
| intact subjects verified | 30/30 PASS |
| stripped subjects verified | 30/30 FAIL (`required_fact_missing` → RETRY) |
| machine over 30 failing runs | retries=60 (2/run, bounded), escalations=30, restored=0 (RETRY path, restore stage correctly skipped) |
| verify-only latency (60 runs) | p50 0.011 ms, max 0.045 ms |

No quality claim beyond the gate (paired quality + cost together required
from here on; this sprint publishes detection distribution + explicit
overhead, nothing hidden). Semantic judge excluded from timing (opt-in,
out of default path).

## Docs/ADRs

- Created: `docs/msi/verification.md` (layers → reason codes → actions,
  profiles, correction rule), `docs/msi/escalation.md` (chain, budgets,
  receipt, overhead pointer), `docs/adr/0020-verification-escalation.md`,
  `tests/test_verification.py`, `src/lcc/router/verify.py` (~410 lines),
  `src/lcc/router/escalate.py` (~330 lines, zero new deps, no network).
- Altered: `src/lcc/router/__init__.py` (exports only),
  `docs/adr/README.md` (+0020 row).
- All new `docs/*.md` links resolve (`tests/test_docs.py` green).

## Deliberately skipped

- Commit + PR: skipped — working tree holds another WIP's staged work
  (`pyproject.toml`, `README.md`, `CHANGELOG.md`, `plugins/chatgpt/**`);
  committing would sweep foreign hunks (same call as sprints 2–3).
  Protocol also forbids push/PR. Revisit on explicit user sign-off with a
  clean tree (suggested: new branch `msi/sprint-5-verification` from HEAD).
- CHANGELOG entry: deferred, same foreign-hunk reason (consistent with
  sprint 4). Add on rebase/merge.
- Citation snapshot match (AgentTrace port gap): needs a snapshot store;
  id-set resolution covers the failure class; documented in verification.md.
- `transform: clean/dedupe`, `--task-id` flags, Nimble scorer, CLI
  surfacing of verify/escalate: inherited OUT scope (library-only, like
  the sprint-4 planner — no workflow needs CLI yet).
- Calibration of the >50%-REVIEW rule on live traffic: no live traffic
  exists; the semantic layer satisfies it by construction (advisory unless
  confident).

## Known limitations

- PILOT-scale benchmark (N=30 curated, hand-built subjects): detection
  distribution only; no latency/cost-of-execution claim (executor trivial).
- Semantic layer unexercised against a live judge in CI (stub only);
  bands inherited from `verifier.py`, covered by unit contract tests.
- Receipt `cost.tokens_*`/`cost_usd` default 0 unless the caller supplies
  measurements; `latency_ms` derives from the injected clock (0 with a
  fixed clock — goldens) or wall clock (live).
- Project-config mypy unrunnable env-wide (pre-existing numpy-stub issue);
  clean with the sprint-2 workaround flags.

## Next

Sprint 6 implements causal necessity (remove-and-replay ablation over the
frozen verification + receipt chain) to populate the IR `necessity` labels
that still default to UNKNOWN.
