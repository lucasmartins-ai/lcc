# Sprint 6 — DONE (PASS)

- Commit: branch `msi/sprint-6-causal-necessity` (from `msi/sprint-4-inference-planner`
  HEAD `5cc17a2`); exact sha in the PR. Working tree was clean at start except one
  pre-existing untracked foreign file (`plugins/chatgpt/assets/make_icon.py`), left
  untouched and uncommitted.
- Gate: `SPRINT_5_DONE.md` = PASS (verified before any edit); sprint-5 `standard`
  verification profile + `verify-1.0` evaluator re-read and reused unchanged.

## Acceptance

- [x] Baseline congelado + hash registrado → PASS. `benchmarks/ablation/pilot.py`
  (task `msi-pilot-6-001`, 8 units, profile `standard`, seed 0, deterministic
  offline): baseline_hash
  `cd5a00987c4fd03c917bf91830d7a4a1942834cedb4c5ab976553aec8c1d3b96`, baseline
  outcome PASS. Evidence: `PYTHONPATH=src python3 benchmarks/ablation/pilot.py`
  prints the hash; `tests/test_ablation.py::test_pilot_baseline_passes_and_hash_frozen`
  green.
- [x] Self-test trivial verde; piloto N≤30 com 2 runs idênticas → PASS. Trivial
  fixture (gold + noise): gold NECESSARY, noise UNNECESSARY
  (`test_trivial_gold_necessary_noise_unnecessary`). Pilot N=8 ≤ 30; two full
  sweeps in one run (`repeats=2`, 35 experiments) plus cross-process reruns give
  digest `5251d16c76d0af962d85e85f5e4963bc19d7bcc05c1515ab3db874a74c676972`
  every time; `pilot.py --check` asserts frozen digest. 1 correction loop: a
  crashing baseline propagated instead of recording — fixed at root cause in
  `run_pilot` (broken baseline → CRASH outcome → all UNKNOWN), covered by
  `test_crashing_make_subject_is_unknown_not_silent`.
- [x] Labels com invariante-decisora registrada por unidade → PASS. Every
  NECESSARY/CONDITIONALLY_NECESSARY label carries `deciding_invariant`
  (first failing check id); every CONDITIONALLY_NECESSARY carries a `condition`
  naming companion + invariant (asserted in
  `test_pilot_conditional_names_companion_and_invariant`). Full table in
  `research/causal-necessity.md`.
- [x] Custo do piloto publicado; limitações escritas → PASS. 35 experiments,
  0.7–0.8 ms total wall, 0 model calls, 0 tokens (`pilot_results.json#cost`,
  research doc §Cost). Limits in research doc §Limits + below.
- [x] `SPRINT_6_DONE.md` em PASS (this file, `docs/msi/`).

## Testes

- `python3 -m pytest tests/test_ablation.py -p no:cacheprovider` → **10 passed**
  (trivial self-test ×3, UNKNOWN fail-closed ×2, PROTECTED-never-ablated,
  frozen pilot hash/labels/condition/provenance ×4).
- `python3 -m pytest tests/ -p no:cacheprovider` → **786 passed, 5 skipped,
  0 failed** (baseline before sprint: 774 passed + staged foreign; +10 new here,
  +2 from the merged main line; same 5 env/opt-in skips, no regressions).
- `.venv/bin/ruff check` on `ablate.py`, `router/__init__.py`,
  `test_ablation.py`, `pilot.py` → clean (1 auto-flag fixed: list literal over
  `str.split` for the frozen stopword set). mypy
  (`--python-version 3.14 --ignore-missing-imports --follow-imports=silent`,
  same workaround as sprints 2–5) on `ablate.py` → `Success: no issues found`.
- Reproducibility: `pilot.py --check` green across 3 separate processes
  (digests compared, timing excluded from digest by design).

## Benchmark

The pilot IS the benchmark (N=8 CURATED units, offline, 2026-10-03, evidence
CURRENT; executor is a deterministic subject-builder, data HYBRID at best —
no generalization claim):

| unit | single removal | pair result | label (invariant) |
|---|---|---|---|
| blk_gold_fact | FAIL | n/a | NECESSARY (required_facts_present) |
| blk_gold_cite | FAIL | n/a | NECESSARY (citations_resolve) |
| blk_pair_a | PASS | FAIL with blk_pair_b | CONDITIONALLY_NECESSARY (required_facts_present) |
| blk_pair_b | PASS | FAIL with blk_pair_a | CONDITIONALLY_NECESSARY (required_facts_present) |
| blk_red_a | PASS | all PASS, tokens covered | REDUNDANT |
| blk_red_b | PASS | all PASS, tokens covered | REDUNDANT |
| blk_noise | PASS | all PASS, unique tokens | UNNECESSARY |
| blk_safety | not ablated | — | PROTECTED |

Cost: 35 experiments (1 baseline + 2×(7 singles + 10 pairs)), 0.7–0.8 ms
wall total (~0.02 ms/experiment), 0 model calls, 0 tokens. Scales as
O(singles + passing-pairs) replays; with a model-backed executor each replay
costs one inference — N stays ≤30 until sprint 7 says otherwise.

## Docs/ADRs

- Created: `research/causal-necessity.md` (method, invariants, finding, 3
  commented examples, cost, limits), `docs/adr/0021-causal-necessity-labels.md`
  (labels research-only until bench-validated; instability → UNKNOWN; N≤30
  pilot cap), `src/lcc/router/ablate.py` (~380 lines, zero new deps, no
  network), `tests/test_ablation.py` (10 tests),
  `benchmarks/ablation/pilot.py` + frozen `pilot_results.json`.
- Altered: `src/lcc/router/__init__.py` (ablate exports only),
  `docs/adr/README.md` (+0021 row), `CHANGELOG.md` (Unreleased/Added entry —
  tree was clean, no foreign hunks this time, unlike sprints 4–5).
- `research/` (repo root) chosen per sprint prompt; `test_docs.py` scans only
  `docs/**` + README/CHANGELOG, and new `docs/*.md` links resolve (suite green).

## Deliberately skipped

- IR `necessity` wiring: labels stay research-only per ADR-0021; populating
  IR `necessity` from pilot labels would be production use without validation.
- Semantic-judge executor: excluded by design (opt-in, network, cost); with a
  judge in the loop the repeat-twice → UNKNOWN rule becomes load-bearing.
- Paraphrase-aware redundancy: token-coverage catches near-duplicates only;
  paraphrased duplicates read as UNNECESSARY — documented limit, not fixed.
- CLI surfacing of ablate/pilot: library + script only, like sprints 4–5 (no
  workflow needs CLI yet).
- `plugins/chatgpt/assets/make_icon.py` (untracked, foreign): left alone.

## Known limitations

- PILOT N=8, one hand-built baseline: distribution only; deltas measure
  verifier sensitivity via a subject-builder executor, not end-to-end model
  causality.
- Deterministic layers only; semantic layer unexercised (stub-free path).
- Project-config mypy unrunnable env-wide (pre-existing numpy-stub issue);
  clean with the sprint-2 workaround flags.
- Protocol §anti-slop forbids push/PR; user explicitly overrode ("commit and
  open PR if safe"). Override applied narrowly: commit on a NEW branch
  `msi/sprint-6-causal-necessity`, PR opened, no existing branch touched,
  foreign untracked file excluded. Deviation recorded here.

## Next

Sprint 7 builds MSI-Bench (paired quality + cost over the frozen verification
+ receipt + ablation chain) and sets the validation bar for promoting any
necessity label to production use.
