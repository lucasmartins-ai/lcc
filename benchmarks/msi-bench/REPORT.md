# MSI-Bench report (sprint 7) — PILOT, N=12

**Release revision (2026-10-03, Sprint 10):** methodological findings
R1–R3 from the audit are resolved. Full-chain attempt costs are instrumented
(all attempts and retries accounted for; decision-01 verify arm records 3 attempts
and 3 frontier calls at $3.2160, bringing verify arm total to $4.3600), bootstrap
draws are shared across all arms in paired resamples, and `--check` validates
the complete stable payload against aggregate/receipt drift. The label-protected
`msi` arm remains an oracle probe, not the public mechanical compiler.
See [audit report](../../research/msi-audit-2026-10-03.md).

Question: "with how many fewer resources is the outcome preserved?"
Hypothesis: LCC+routing+verification dominates Pareto
(quality x cost x latency x context) against full-context on >=1 category,
with paired quality -- and where it does not, that is published too.

Evidence: BENCHMARK. Data: CURATED (12 hand-built tasks, 6 categories x 2).
Method: `research/benchmark-methodology.md`. Reproduce (repo root):

```
PYTHONPATH=src:benchmarks/msi-bench python3 benchmarks/msi-bench/run.py --check
```

Matrix digest `13a29b20a099681eb6188d54c0fa12ba44c8332c33f44bfcb88c28b55687bb80`
(72 runs: 12 tasks x 6 arms). Pre-registered predictions (`tasks.py#PREDICTED`,
written before the first run): 72/72 cells match after one documented
fixture repair (research-02 carrier split; methodology correction log C1).

## Arms

`full` (all context, frontier, single attempt) | `lcc` (lexical filter,
local model, single) | `routing` (all context, planned model, single) |
`lcc_routing` (filter + planned model, single) | `lcc_routing_verify`
(filter + planned model + bounded restore/retry) | `msi` (filter +
exact-carrier/citation protection + protected units + planned model +
bounded restore/retry). All arms score under the same rubric
(`verify-1.0`, `standard`); every run carries an `inference-receipt/0.1`
receipt in `results.json`.

## Matrix (1 = PASS, 0 = FAIL; columns: full lcc routing lcc_routing verify msi)

| category | task | full | lcc | routing | lcc_routing | verify | msi |
|---|---|---|---|---|---|---|---|
| coding | coding-01 | 1 | 1 | 1 | 1 | 1 | 1 |
| coding | coding-02 (pair, zero overlap) | 1 | 0 | 1 | 0 | 0 | 1 |
| research | research-01 | 1 | 1 | 1 | 1 | 1 | 1 |
| research | research-02 (citation-only drop) | 1 | 0 | 1 | 0 | 1 | 1 |
| decision | decision-01 (high risk, 3 facts) | 1 | 0 | 1 | 0 | 0 | 1 |
| decision | decision-02 (high risk, shared) | 1 | 1 | 1 | 1 | 1 | 1 |
| longctx | longctx-01 (8 units) | 1 | 1 | 1 | 1 | 1 | 1 |
| longctx | longctx-02 (zero-overlap fact) | 1 | 0 | 1 | 0 | 0 | 1 |
| toolheavy | toolheavy-01 | 1 | 1 | 1 | 1 | 1 | 1 |
| toolheavy | toolheavy-02 (injection) | 0 | 1 | 0 | 1 | 1 | 1 |
| docreason | docreason-01 (contradiction pair) | 1 | 1 | 1 | 1 | 1 | 1 |
| docreason | docreason-02 (4-block chain) | 1 | 0 | 1 | 0 | 0 | 1 |

## Aggregate (paired quality + cost together, never compression alone)

| arm | success | rate | CI95 | modeled cost | succ/$* | frontier | vercalls | restores | retries | escal | falsedeesc | unsafe | protdrop | retained | wall p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| full | 11/12 | 0.917 | [0.750, 1.000] | $22.8640 | 0.48 | 12 | 12 | 0 | 0 | 1 | 0 | 0 | 0 | 679 | 0.032ms |
| lcc | 7/12 | 0.583 | [0.333, 0.833] | $0.0000 | n/a (zero cost) | 0 | 12 | 0 | 0 | 5 | 1 | 1 | 2 | 248 | 0.037ms |
| routing | 11/12 | 0.917 | [0.750, 1.000] | $3.2480 | 3.39 | 2 | 12 | 0 | 0 | 1 | 0 | 0 | 0 | 679 | 0.031ms |
| lcc_routing | 7/12 | 0.583 | [0.333, 0.833] | $2.2160 | 3.16 | 2 | 12 | 0 | 0 | 5 | 0 | 0 | 2 | 248 | 0.035ms |
| verify (lcc+routing+verification) | 8/12 | 0.667 | [0.417, 0.917] | $4.3600 | 1.83 | 4 | 17 | 1 | 4 | 4 | 0 | 0 | 2 | 261 | 0.032ms |
| msi (closed loop) | 12/12 | 1.000 | [1.000, 1.000] | $2.5040 | 4.79 | 2 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 356 | 0.027ms |

\* `succ/$` uses modeled illustrative prices; absolute dollars are not a
claim. Latency is deterministic overhead only (flat across arms by design;
model inference latency unmeasured -- see limitations). Wall p50 jitters
~+/-0.01ms run to run and is excluded from the reproducibility digest.

Derived, at matched success (tasks where the arm AND full-context PASS):
retained tokens full 57.3 / lcc 24.8 / routing 57.3 / lcc_routing 24.8 /
verify 25.3 / msi 31.3; frontier-avoided lcc 1.000 / routing 0.818 /
lcc_routing 0.833 / verify 0.857 / msi 0.818.

## Pareto (success max, modeled cost min, retained min)

Frontier: `lcc`, `lcc_routing_verify`, `msi`. Dominated and why:
`full` (msi beats it on all three axes), `routing` (same: msi 12/12 at
$2.50/356 tokens vs routing 11/12 at $3.25/679), `lcc_routing` (lcc matches
its 7/12 at $0/248 vs $2.22/248). No arm dominates everywhere: `lcc` is
cheapest but loses 5/12; `msi` wins quality at 9.1x lower modeled cost than
`full` ($2.50 vs $22.86) and 0.52x the context (356 vs 679 tokens) -- with
the PILOT caveat below, not as a generalization.

## Failures, published alongside successes

1. Lexical filtering without protection loses 5/12 (coding-02, research-02
   without restore, decision-01, longctx-02, docreason-02). Two of those
   runs end in ABORT (empty summary fails the schema layer: coding-02 and
   longctx-02 under single-attempt arms) -- aggressive filtering can erase
   the answer entirely, and the machine says ABORT, never silent PASS.
2. `full-context` FAILs toolheavy-02: keeping everything forwards the
   injected instruction (`forbidden_claims_absent`). Full context is not a
   safety strategy under this rubric (no render-time defense in the
   subject-builder; methodology limitation 4).
3. Verification makes failure visible and bounded, not fixed: decision-01
   and docreason-02 under the verify arm burn 2 retries each, then ESCALATE
   (human / frontier). Restore rescues exactly one run (research-02,
   citation-only failure); joint task+citation failure resolves to RETRY by
   first-failure precedence -- restore cannot rescue what the task layer
   already lost (methodology correction log C1).
4. `lcc` on high risk: decision-01 FAIL on a cheap model = 1
   false_deescalation; decision-02 PASS on a cheap model with reduced
   context = 1 unsafe_optimization flag (process proxy).
5. Protected units are dropped by every unprotected filtering arm
   (longctx-01, toolheavy-01: 2 drops each) with zero effect on the success
   metric. The quality metric alone does not see safety erosion; the
   `protected_dropped` column exists so the gap cannot hide.

## Where the hypothesis lands (PILOT-scoped)

- MSI closed loop is the only 12/12 arm, at 0.11x the modeled cost and
  0.54x the context of full-context. Pareto-dominant in this matrix, with
  CIs that overlap full/routing on quality ([1.000,1.000] vs
  [0.750,1.000] -- separation is one task, not a claim).
- Routing alone preserves full-context quality (11/12, identical cells) at
  0.14x modeled cost by avoiding frontier on 9/11 matched tasks. The saving
  is model selection, not context reduction (retained identical).
- LCC-only is free (modeled $0) and keeps quality where vocabulary overlaps
  (7/12), with named failure modes elsewhere. No headline without the
  failure table above.

## Limits (do not cite past these)

PILOT N=12; bootstrap CIs overlap nearly everywhere; cost illustrative;
latency = deterministic overhead; tokens heuristic; no live models, no
live judges, no generative grading. Promoting any of this beyond the frozen
task set requires a larger, disjoint, live-model bench -- explicitly not
this sprint.
