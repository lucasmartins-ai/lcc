# Causal necessity pilot (MSI sprint 6) — PILOT, N=8

Status: research-only. Labels are NOT consumed by any production path (no IR
`necessity` wiring, no planner input). Evidence: CURRENT. Data: CURATED
(hand-built pilot baseline, offline, deterministic). No generalization claim.

## Method

Remove-and-replay over a frozen baseline (`benchmarks/ablation/pilot.py`,
task `msi-pilot-6-001`, baseline hash
`cd5a00987c4fd03c917bf91830d7a4a1942834cedb4c5ab976553aec8c1d3b96`):

1. Verify the full baseline with the sprint-5 `standard` profile
   (deterministic layers only: schema, task, citation, test, policy; no
   semantic client, no network). Baseline must PASS or every label is UNKNOWN.
2. Remove each non-protected unit alone, replay verification, record the
   outcome delta + deciding check (first failing check id).
3. Remove each pair of single-PASS units, replay, record. Pairs where either
   single already fails are not tested (the single already explains the loss).
4. Repeat the whole sweep twice; a label that disagrees across repeats is
   UNKNOWN, never forced.
5. Every experiment records seed (0), baseline hash, model
   (`deterministic-mechanical`), evaluator (`verify-1.0`), and wall time.

Harness: `src/lcc/router/ablate.py` (`run_pilot`, harness `ablate-1.0`).
Frozen results: `benchmarks/ablation/pilot_results.json` (35 experiments:
1 baseline + 2 x (7 singles + 10 pairs)). Reproduce:
`PYTHONPATH=src python3 benchmarks/ablation/pilot.py --check` asserts the
digest `5251d16c76d0af962d85e85f5e4963bc19d7bcc05c1515ab3db874a74c676972`.

## Invariants (what "degradation" means)

Outcome deltas are read off the sprint-5 verification layers; the deciding
invariant per unit is the first failing check:

| invariant (check id) | layer | pilot units decided by it |
|---|---|---|
| `required_facts_present` | task | blk_gold_fact (single), blk_pair_a/b (pair) |
| `citations_resolve` | citation | blk_gold_cite (single) |
| `tests_green`, `schema_valid`, policy checks | test/schema/policy | none in this pilot (all PASS throughout) |

## Label distribution (N=8 units)

| unit | label | deciding invariant | condition |
|---|---|---|---|
| blk_gold_fact | NECESSARY | required_facts_present | — |
| blk_gold_cite | NECESSARY | citations_resolve | — |
| blk_pair_a | CONDITIONALLY_NECESSARY | required_facts_present | requires blk_pair_b present (jointly cover required_facts_present) |
| blk_pair_b | CONDITIONALLY_NECESSARY | required_facts_present | requires blk_pair_a present (jointly cover required_facts_present) |
| blk_red_a | REDUNDANT | — | — |
| blk_red_b | REDUNDANT | — | — |
| blk_noise | UNNECESSARY | — | — |
| blk_safety | PROTECTED | — | — |

## Finding (pilot-scale, no generalization)

Single-removal alone separates NECESSARY (2/7 ablated units) from everything
else: 5/7 non-protected units survive single removal (PASS), so
`P(degradation | remove single)` conflates CONDITIONALLY_NECESSARY,
REDUNDANT, and UNNECESSARY. The separation needs two more steps, both
demonstrated here: pair ablation (1 of 10 tested pairs FAILS, splitting the
2 conditional units from the 3 always-passing ones) and token-coverage
(identical duplicates are REDUNDANT; unique noise is UNNECESSARY). A
relevance scorer that keeps "whatever looks similar" would keep all 8; the
causal read says 3 of 8 (redundant x2 + noise) can go with zero outcome
delta, and 2 more (the pair) can go only together-with-companion awareness.
Whether that gap persists outside this pilot is sprint-7 work, not a claim.

## Commented examples

1. NECESSARY — `blk_gold_fact` ("The crash is a null deref at auth.py line
   42."): removing it drops the only carrier of required fact F1, replay
   FAILS `required_facts_present`. No other unit covers F1. Causal, not
   correlational: the outcome delta is observed, not scored.
2. REDUNDANT — `blk_red_a` ("The team uses pytest for unit tests.", byte-
   identical to `blk_red_b`): single removal PASS, pair removal with its twin
   still PASS (the sentence feeds no invariant), and every meaningful token
   is covered by the twin. Safe to drop one copy; dropping both is equally
   safe here because the content is noise to all invariants.
3. CONDITIONALLY_NECESSARY — `blk_pair_a` ("The api key lives in the vault
   path prod/api-key."): single removal PASS (twin `blk_pair_b` still carries
   F2), but joint removal FAILS `required_facts_present`. Condition:
   "requires blk_pair_b present (jointly cover required_facts_present)".
   A compaction pass that drops both as "similar" breaks the outcome; one
   that keeps at least one is safe. This is the class a similarity scorer
   cannot see.

## Cost

35 experiments, 0.7–0.8 ms total wall (~0.02 ms/experiment), 0 model calls,
0 tokens. Ablation at this scale is free because the executor and the
verifier are both deterministic and local. Cost scales as
O(singles + passing-pairs) replays per baseline; with a model-backed
executor each replay costs one inference, so N stays small until sprint 7
says otherwise. No N large without a pilot first (sprint OUT scope).

## Limits

- PILOT N=8, one hand-built baseline: distribution only, no quality/cost
  claim beyond the gate. Executor is a subject-builder, not a model; deltas
  measure verifier sensitivity, which is the point at this stage (do the
  labels track outcome-relevant content?) but not end-to-end causality.
- Deterministic layers only. The semantic layer (opt-in judge) is excluded;
  with a judge in the loop, labels inherit judge noise and the repeat-twice
  -> UNKNOWN rule becomes load-bearing rather than vacuous.
- REDUNDANT vs UNNECESSARY rests on token-coverage over a fixed stopword
  set: adequate for near-duplicate detection, not for paraphrase (paraphrased
  duplicates read as UNNECESSARY). Documented, not fixed here.
- IR `necessity` fields still default to UNKNOWN everywhere; nothing in
  `src/lcc/relevance/` or the planner reads these labels (ADR-0021).
