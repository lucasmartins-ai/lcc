# Sprint 7 — DONE (PASS)

- Commit: branch `msi/sprint-7-msi-bench` (from `msi/sprint-6-causal-necessity`
  HEAD `b21696a`); exact sha in the PR. Working tree was clean at start
  except one pre-existing untracked foreign file
  (`plugins/chatgpt/assets/make_icon.py`), left untouched and uncommitted.
- Gate: `SPRINT_6_DONE.md` = PASS (verified before any edit);
  `research/methodology.md` (spec repo) + `benchmarks/research/RESEARCH_STATUS.md`
  (CURRENT/EXPERIMENTAL/HISTORICAL/BENCHMARK separation) re-read.

## Acceptance

- [x] Matriz braços×categorias completa com qualidade pareada → PASS.
  72 runs (12 CURATED tasks × 6 arms, 6 categories × 2 tasks), every arm
  scored under the identical rubric (`verify-1.0`, profile `standard`,
  deterministic layers, budgets unconfigured) with one
  `inference-receipt/0.1` receipt per run. Evidence: `benchmarks/msi-bench/
  results.json` (digest `d62de09e65353d3a6c3ebc3c9dffc627f6a08a6135eb888452395e09eef4e93e`);
  `PYTHONPATH=src:benchmarks/msi-bench python3 benchmarks/msi-bench/run.py --check`
  → `reproducible: digest d62de09e… (72 runs, 12 tasks x 6 arms)`.
- [x] Pareto quality×cost/latency/context publicado → PASS. Frontier:
  `lcc`, `lcc_routing_verify`, `msi` (success max, modeled-cost min,
  retained-tokens min); dominated arms named with reasons (`full` and
  `routing` beaten by `msi` on all three axes; `lcc_routing` beaten by `lcc`).
  Latency published flat (~0.03ms deterministic overhead all arms, declared,
  not hidden). Evidence: `benchmarks/msi-bench/REPORT.md` (aggregate table +
  Pareto section).
- [x] Metodologia + proveniência + limitações + incerteza documentadas →
  PASS. `research/benchmark-methodology.md`: CURATED origin/collection,
  freeze date 2026-10-03 + per-task content hashes, contamination rule
  (disjoint ids, no tuning on the test set, 72 pre-registered predicted
  cells), rubric + derived-flag definitions, bootstrap uncertainty (2000
  resamples, seed 7, percentile 95% CI), 7 load-bearing limitations,
  correction log C1-C3. Evidence: file exists; full suite green includes
  `test_docs.py`.
- [x] Falhas publicadas ao lado dos sucessos; reprodução em 1 comando
  funciona → PASS. REPORT.md §Failures lists 5 failure classes (lexical
  5/12 losses incl. 2 ABORTs on empty context; full-context injection FAIL;
  retry-then-escalate bounds; 1 false_deescalation + 1 unsafe_optimization;
  4 protected drops invisible to the success metric). Repro: the
  one-command `--check` above, green. Evidence: REPORT.md + command output.
- [x] `SPRINT_7_DONE.md` em PASS (this file, `docs/msi/`).

## Testes

- `python3 -m pytest tests/test_msi_bench.py -p no:cacheprovider` → **9 passed**
  (matrix shape 72, digest-twice identical, frozen digest+hashes match,
  sanity full-wins-all-required, 72/72 receipts schema-valid, rescue-chain
  fields, key predicted cells, pareto membership, provider hygiene).
- `python3 -m pytest tests/ -p no:cacheprovider` → **795 passed, 5 skipped,
  0 failed** (baseline before sprint: 786 passed + same 5 env/opt-in skips;
  +9 new here, no regressions).
- `.venv/bin/ruff check` on `bench.py`, `tasks.py`, `run.py`,
  `test_msi_bench.py` → clean (3 correction loops were lint/content only;
  see methodology C1-C3). mypy (`--python-version 3.14
  --ignore-missing-imports --follow-imports=silent`, sprint-2 workaround) on
  `bench.py` → `Success: no issues found`. (`ruff format` not enforced:
  pre-existing sprint files are not format-clean either; `ruff check` is the
  gate.)
- 3 correction loops, all pre-freeze and documented: C1 research-02 carrier
  split (restore stage isolation; 71/72 → 72/72 predicted cells); C2 three
  unit strings shortened for the 100-char limit (facts/overlaps re-verified,
  digest re-frozen); C3 `omitted_units` key `reason` → `rationale` at root
  cause in the bench emitter (schema envelope; outcome digest unchanged).

## Benchmark

This sprint IS the benchmark (PILOT, N=12 CURATED, offline, 2026-10-03,
evidence BENCHMARK; cost MODELED illustrative, latency deterministic
overhead only, tokens heuristic-v1):

| arm | success | CI95 | modeled cost | frontier | vercalls | restores/retries/escal | retained |
|---|---|---|---|---|---|---|---|
| full | 11/12 | [0.750, 1.000] | $22.8640 | 12 | 12 | 0/0/1 | 679 |
| lcc | 7/12 | [0.333, 0.833] | $0.0000 | 0 | 12 | 0/0/5 | 248 |
| routing | 11/12 | [0.750, 1.000] | $3.2480 | 2 | 12 | 0/0/1 | 679 |
| lcc_routing | 7/12 | [0.333, 0.833] | $2.2160 | 2 | 12 | 0/0/5 | 248 |
| lcc_routing_verify | 8/12 | [0.417, 0.917] | $2.2160 | 2 | 17 | 1/4/4 | 261 |
| msi | 12/12 | [1.000, 1.000] | $2.5040 | 2 | 12 | 0/0/0 | 356 |

Paired read (never compression alone): MSI closed loop is the only 12/12
arm at 0.11x modeled cost and 0.52x context of full-context; routing alone
matches full-context quality cell-for-cell at 0.14x modeled cost (model
selection, not context reduction); LCC-only holds quality where vocabulary
overlaps (7/12) and fails loudly elsewhere. CIs overlap nearly everywhere:
distributions only, no generalization claim (PILOT declared, not "result").

## Docs/ADRs

- Created: `benchmarks/msi-bench/tasks.py` (12 frozen tasks + 72
  pre-registered predicted cells), `bench.py` (arms/cost/Pareto/bootstrap,
  ~380 lines, zero new deps, no network), `run.py` (one-command runner +
  `--check`), `results.json` (frozen, digest-pinned, 72 embedded receipts),
  `REPORT.md` (matrix + failures + limits), `research/benchmark-methodology.md`,
  `tests/test_msi_bench.py` (9 tests).
- Altered: `CHANGELOG.md` (Unreleased/Added entry — tree was clean, no
  foreign hunks, unlike sprints 4–5).
- No ADR: no production-path decision was taken (bench is measurement, not
  mechanism; IR/planner/verifier contracts unchanged).
- All new `docs/*.md` + CHANGELOG links resolve (`tests/test_docs.py` green).

## Deliberately skipped

- Live-model / live-judge arms: OUT scope (no keys, no network in this env);
  cost is modeled and latency is overhead-only, both declared. A live bench
  is future work, explicitly not this sprint.
- New categories beyond the 6 / more tasks per category: sprint allows 1–2
  frozen tasks per category in v0; N stays 12 until a follow-up justifies more.
- CLI surfacing of the bench: library + script only, like sprints 4–6 (one
  repro command is the interface the sprint asked for).
- `plugins/chatgpt/assets/make_icon.py` (untracked, foreign): left alone.
- Commit + PR: performed (branch `msi/sprint-7-msi-bench`, narrow override
  of protocol §anti-slop per explicit user instruction, same call as
  sprint 6). No existing branch touched; foreign untracked file excluded.

## Known limitations

- PILOT N=12, hand-built: every non-extreme CI is wide (7/12 →
  [0.333, 0.833]); overlapping intervals read as "cannot separate", never
  equivalence.
- Deterministic layers only; semantic judge excluded, so `strict` vs
  `standard` differ in nothing outcome-relevant here.
- Exact-substring verifier: zero-overlap wording stands in for paraphrase;
  no live-judge paraphrase evidence.
- Subject-builder has no render-time injection defense (toolheavy-02 full
  FAIL is rubric-correct but models a defense-less system).
- Tool policy uniform across arms: `toolheavy` measures retention under
  tool-output-heavy context, not tool selection.
- Restore fires only on citation-only failure (first-failure precedence);
  test/policy-only rescue paths rest on sprint-5 unit tests.
- Project-config mypy unrunnable env-wide (pre-existing numpy-stub issue);
  clean with the sprint-2 workaround flags.

## Next

Sprint 8 builds DX (one-command verify/escalate surfacing and receipt
reading) on top of the frozen bench chain, so the matrix above becomes
runnable and inspectable from the CLI without touching its semantics.
