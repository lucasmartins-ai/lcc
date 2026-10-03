# MSI-Bench methodology (sprint 7) — PILOT, N=12

**Release revision (2026-10-03, Sprint 10):** the methodological findings
documented in [the audit](msi-audit-2026-10-03.md) (R1–R3) have been corrected:
all-attempt cost accounting is instrumented for every executed attempt and retry,
bootstrap resampling draws a single task sample per resample shared across all arms,
and `--check` asserts the entire stable payload against aggregate/receipt drift.

Status: PILOT. All figures below are evidence class BENCHMARK on CURATED
hand-built tasks (N=12, offline, deterministic, no live models). Nothing
here generalizes beyond the frozen task set; intervals are published wide
on purpose.

## Origin and collection

Tasks were hand-written by the author on 2026-10-03 in
`benchmarks/msi-bench/tasks.py`. No model generated any unit. Scenario
shapes borrow from `benchmarks/research/adversarial_cases.py` (negation,
authority, dependency chains, injection-shaped logs, contradiction pairs),
but every id, unit, fact, and objective string is new content.
Collection = authoring; there is no sampling step, so there is no sampling
frame to describe. The lexical filter threshold (>=1 shared non-stopword
token, exact match, no stemming) was fixed a priori in `bench.py`; the one
fixture repair during the sprint (research-02 carrier split, see Correction
log) changed task construction to isolate the restore stage, not the
threshold, and the pre-registered outcome for that cell did not change.

## Freeze

Freeze date: 2026-10-03. Frozen artifacts: `tasks.py` (12 tasks),
`results.json` (matrix digest
`13a29b20a099681eb6188d54c0fa12ba44c8332c33f44bfcb88c28b55687bb80`).
Per-task content hashes live in `results.json#task_hashes`
(`run.py --check` asserts the full stable payload including digest, task hashes,
receipts, aggregates, and bootstrap CIs, failing loudly on any drift).
Reproduce with one command (repo root):

```
PYTHONPATH=src:benchmarks/msi-bench python3 benchmarks/msi-bench/run.py --check
```

## Dataset classification

All 12 tasks: CURATED. Executor: deterministic subject-builder (joins the
arm's retained units into the verified output; no model, no paraphrase).
Evaluator: sprint-5 `verify-1.0`, profile `standard`, budgets unconfigured.
Tokenizer: `heuristic-v1` (`approximate_token_count`; estimates, +/-20-30%
vs exact -- token columns are approximate by construction). Cost: MODELED
(illustrative prices in `bench.py`: local 0, hosted 0.5/1.5, frontier 8/24
USD per 1k in/out tokens; absolute dollars are not a claim, only the
ordering local < hosted < frontier is load-bearing). Latency: measured
deterministic wall time only (`wall_ms_measured`, CURRENT); model inference
latency is NOT measured (no live models).

## Contamination rule

Bench task ids (`msi-bench-7-*`) are disjoint from the sprint-6 pilot task
(`msi-pilot-6-001`) and from all adversarial calibration corpora; content
hashes are listed, not reused. Planner thresholds (`0.65/0.60`) and the
lexical rule were inherited/fixed, never tuned on this task set (N=12
cannot support tuning; tuning here would be overfitting by construction).
Pre-registered arm outcomes (`tasks.py#PREDICTED`, 72 cells) were written
before the first matrix run; the single first-run miss is documented in
the correction log, not silently absorbed.

## Rubric

Success = `verify-1.0` outcome PASS under profile `standard`, scored
identically for every arm (paired). Failing checks map to actions per
sprint 5 (`schema->ABORT`, `task->RETRY`, `citation->RESTORE_CONTEXT`,
`test->RETRY`, policy/unknown->ESCALATE/ABORT). Derived flags:

- `false_deescalation`: cheap model on high/unknown risk AND outcome != PASS.
- `unsafe_optimization` (process proxy, not a safety verdict): outcome PASS
  with a cheap model on high/unknown risk while retaining < full context
  (savings claimed where risk said frontier -- held this time, flagged).
- `protected_dropped`: protected units absent from the final selection
  (safety gap invisible to the success metric; published, not hidden).
- `retained@matched-success`: mean retained tokens on tasks where the arm
  AND full-context both PASS. `frontier-avoided@matched-success`: fraction
  of those where full-context used frontier and the arm did not (modeled
  would-calls, no live dispatch).

## Statistical uncertainty

Bootstrap over tasks (paired resampling across arms, 2000 resamples, seed
7, percentile 95% CI) per arm success rate. N=12 makes every non-extreme
interval wide (e.g. 7/12 -> [0.333, 0.833]); that width IS the result at
this N. No significance claim is made; overlapping intervals are read as
"cannot separate at this N", never as equivalence.

## Limitations (load-bearing)

1. PILOT N=12, one hand-built task per cell pair: distributions only.
2. Deterministic layers only; the opt-in semantic judge is excluded, so
   `strict` vs `standard` differ in nothing outcome-relevant here.
3. Exact-substring verifier: paraphrase-sensitivity of the lexical filter is
   exercised only through zero-overlap wording, not through live judges.
4. Subject-builder concatenates retained units without an injection filter;
   the toolheavy-02 full-context FAIL is correct under the rubric but models
   a system with no render-time defense (stated, not hidden).
5. Tool policy is uniform across arms (all arms present the same tool set);
   `toolheavy` measures retention under tool-output-heavy context, not tool
   selection skill.
6. Restore fires only on citation-only failure (first-failure precedence:
   joint task+citation failure resolves to RETRY). No bench task isolates a
   test/policy-only failure; those paths rest on sprint-5 unit tests.
7. Cost is modeled, latency is deterministic overhead only; no
   quality-per-dollar claim against live vendor pricing.

## Correction log

- C1 (2026-10-03, pre-freeze): research-02 first ran FAIL on the verify arm
  (predicted PASS). Root cause: fact and citation shared one zero-overlap
  unit, so the first attempt failed task AND citation layers jointly, and
  the machine's first-failure precedence resolved to RETRY, never
  RESTORE_CONTEXT. Fixed the fixture (split fact carrier / citation
  carrier), not the machine; predicted cell unchanged. Post-fix matrix:
  72/72 predicted cells match.
- C2 (2026-10-03, pre-freeze): three unit strings shortened to satisfy the
  100-char lint limit (required facts and token overlaps verified
  unchanged via the overlap checker); matrix re-run and re-frozen, digest
  updated in REPORT.md and here; predictions still 72/72.
- C3 (2026-10-03, pre-freeze): `omitted_units` entries used key `reason`;
  the `inference-receipt/0.1` schema requires `rationale` (caught by the new
  72-receipt validation test). Fixed the bench emitter at root cause, not
  the schema; outcome digest unchanged (envelope-only fix).
- C4 (2026-10-03, Sprint 10 release): audit blockers R1–R3 resolved.
  R1: full-chain attempt cost accounting records context and model for every
  executed attempt, including retries (decision-01 verify arm records 3 attempts
  and 3 frontier calls at $3.2160, updating verify total to $4.3600);
  R2: bootstrap resampling draws task indices once per resample across all arms
  (paired resampling);
  R3: `run.py --check` asserts full stable payload equality including aggregates
  and receipts, preventing aggregate drift; matrix re-run and re-frozen with
  digest `13a29b20a099681eb6188d54c0fa12ba44c8332c33f44bfcb88c28b55687bb80`.
