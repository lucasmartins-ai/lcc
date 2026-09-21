# RESEARCH_STATUS — canonical measurements (single source of truth)

One table answers "what is the true current number?". Historical and
experimental figures live below it and never in the README headline.

Evidence tiers used in this file:

- CURRENT: implemented, tested, reproducible today.
- EXPERIMENTAL: implemented but not yet sufficiently validated (usually needs
  live-model measurement); do not present as capability.
- HISTORICAL: superseded results from earlier versions/configurations.
- BENCHMARK: dataset- and configuration-specific results, pilots included.
  Small samples (N=18, N=20, N=30, N=50-synthetic) are pilots, not
  generalisation evidence.

## Current canonical

| Metric | Value | Dataset | N | Provider | Tokenizer | Date | Repro | Limitations |
|---|---|---|---|---|---|---|---|---|
| adversarial E0 (mechanical) | 30/30, 0 regressions | adversarial_cases | 30 | mechanical | heuristic | 2026-09-18 | `python3 run_answer_eval.py --provider mechanical` | synthetic corpora, regex recall |
| multi-agent pilot E1 | 0 E1 regressions, mean red 54.3% | PILOT_IDS (5 domains) | 20 | mechanical | heuristic | 2026-09-18 | `python3 run_multiagent_ab.py --tasks 20` | mock answerer, not live LLM |
| injection Property B | 3/3 pass | injection_html/log + prompt_injection | 3 | mechanical | heuristic | 2026-09-18 | `python3 run_injection_e2e.py` | deterministic mock downstream |
| agent A/B (live, prior) | ctx −61.2%, prompt −9.1%, recall 5/5 | dossier A/B | 18 agents | jev | exact o200k | prior study | `make_payloads.py + score_agents.py` | 3 samples/arm, 1 scale |
| per-payload vs whole-session | −42.4% vs −7.9% context cost | cache_patterns sim | 5 turns | n/a | exact | prior study | `run_cache_patterns.py` | price model read 0.10x/write 1.25x |
| qualifier-truncation guards | 16/16 qualifiers refuse unsafe trim + control trims | qualifier fixtures | 17 | n/a (deterministic trim) | n/a | 2026-09-20 | `pytest tests/test_trim_qualifiers_adversarial.py` | unit-level; live recall impact not measured |
| structured-field preservation | JSON/YAML/XML/table/code/config refuse field-dropping trims | structured fixtures | 12 | n/a (deterministic trim) | n/a | 2026-09-20 | `pytest tests/test_structured_preservation.py` | unit-level; parser-pair edge cases open |
| adversarial hardening (17 cats) | critical evidence kept in all 17 categories | hardening fixtures | 17 | mechanical (+1 mock-jev) | heuristic | 2026-09-20 | `pytest tests/test_adversarial_hardening.py` | synthetic; live-judge behaviour NOT VALIDATED |
| verifier contract | PASS/REVIEW/FAIL mapping + fail-closed on 3 failure modes | contract fixtures | 11 | n/a (offline fakes) | n/a | 2026-09-20 | `pytest tests/test_verifier_contract.py` | contract only; live calibration NOT VALIDATED |
| verifier FAIL restoration | bounded restore + REVIEW, accounting on final bytes | restoration fixtures | 3 | mock-jev | heuristic | 2026-09-20 | `pytest tests/test_verifier_fail_restoration.py` | synthetic; live-judge behaviour NOT VALIDATED |
| cache identity + economics | verifier epoch fork, byte-stability, break-even accounting | cache fixtures | 9 | mechanical | heuristic | 2026-09-20 | `pytest tests/test_cache_identity_semantic.py tests/test_cache_economics.py` | price model read 0.10x/write 1.25x, provider-specific |
| adversarial E0 (live jev) | 30/30, min survival 1.0, mean red 50.2% | adversarial_cases | 30 | jev-1.13.0 (resolved) | exact o200k | 2026-09-21 | `python3 run_adversarial.py jev` | synthetic corpora, regex recall; keychain key, ~60 calls |
| answer-eval (live jev) | 30 cases, 0 regressions (recall delta ≥ 0 everywhere) | adversarial_cases | 30 | jev-1.13.0 (resolved) | exact o200k | 2026-09-21 | `python3 run_answer_eval.py --provider jev` | required-fact recall, not generative grading |
| answer preservation (live jev selector, mock downstream) | −58 tokens/task, correctness delta 0.0; verifier PASS 29–31, REVIEW 19–21, FAIL 0 | 50 synthetic tasks × 10 domains | 50 | jev-1.13.0 (resolved) | heuristic | 2026-09-21 | `python3 run_answer_preservation.py --provider jev` | mock extractive downstream; generative-LLM grading NOT VALIDATED |
| judge ablation (live jev A/B/C) | raw: 2 false drops (recall 0.667); safety: unchanged (unlinked evidence); verifier: REVIEW, +1 call | ablation corpus (6 evid + 6 noise) | 12 blocks | jev-1.13.0 (resolved) | heuristic | 2026-09-21 | `python3 run_judge_ablation.py --judge jev` | 1 corpus; isolated-evidence gap visible (see calibration §) |

## Benchmark (dataset-specific, reproducible offline)

| Metric | Value | Dataset | N | Provider | Tokenizer | Date | Repro | Limitations |
|---|---|---|---|---|---|---|---|---|
| judge ablation (mock-laya) | raw 2 false drops → safety closes both; verifier +1 call | ablation corpus (6 evid + 6 noise) | 12 blocks | mock stand-ins | heuristic | 2026-09-20 | `python3 run_judge_ablation.py --judge mock-laya` | mock judges prove the harness, NOT Laya/Jev quality |
| judge ablation (mock-jev) | raw already clean; safety changes nothing | ablation corpus | 12 blocks | mock stand-ins | heuristic | 2026-09-20 | `python3 run_judge_ablation.py --judge mock-jev` | same: harness only |
| judge ablation (mechanical) | raw 5 false drops → safety recovers 2 | ablation corpus | 12 blocks | mechanical | heuristic | 2026-09-20 | `python3 run_judge_ablation.py --judge mechanical` | lexical baseline behaviour |
| answer preservation (mock) | −58 tokens/task, correctness delta 0.0 | 50 synthetic tasks × 10 domains | 50 | mechanical | heuristic | 2026-09-20 | `python3 run_answer_preservation.py` | mock extractive downstream; live LLM NOT VALIDATED |

## Historical (superseded reduction columns — Finding 14)

Pre-sufficiency matrix reductions (Findings 9/10/12/13) are superseded by
Finding 14 table (mechanical small 44.8→26.2%, Jev small 32.5→21.2%, etc.).
Recall columns and cache findings unaffected in kind.

## Live calibration findings (2026-09-21, jev-1.13.0 resolved — measured, not assumed)

- **Backend omits confidence.** Live noul answers carry `{type, noul}` with no
  `confidence` field (neither scoring nor verifier questions). Consequence:
  the selector confidence gear (DROP→TRIM→KEEP) is inert against this backend
  version, and the verifier treats absence as neutral 0.5 (documented in
  `verifier.py`): systematic omission is not per-judgment doubt, so maximal
  doubt would make PASS unreachable — a 100%-REVIEW verifier is noise, not
  safety. Explicit out-of-range confidence still REVIEWs. Test:
  `test_missing_confidence_is_neutral_not_maximal_doubt`.
- **FAIL band unreachable without explicit confidence.** Neutral 0.5 < 0.7 FAIL
  threshold, so FAIL requires a backend that actually returns high confidence
  with a low score. Live distribution on 50 tasks: PASS 29–31, REVIEW 19–21,
  FAIL 0 (two runs; live scores jitter ±1). Bounded FAIL restoration is
  unit-covered (`test_verifier_fail_restoration.py`) but has zero live
  observations to date.
- **Verifier is conservative on revision/conditional evidence.** All 19–21
  REVIEWs are `verifier_uncertain_review` on finance/business/data-analysis
  tasks (restatements, `unless`, rate pairs) with fact recall still 1.0 —
  REVIEW fires without any recall loss. REVIEW rate ≈ 40% on this synthetic
  mix is a pessimism signal, not a quality gate: treat as triage, not verdict.
- **Isolated-evidence gap (the ablation's point).** Live Jev underscored two
  evidence blocks with unique vocabulary (refund exclusion, order dependency);
  the structural layer restored nothing — correctly, since no link was
  severed (unlinked evidence has no severable link). Lexical-graph safety only
  protects *linked* evidence; the verifier REVIEW was the sole backstop. This
  is the known ceiling of the current safety model, stated here so no one
  reads "safety layer" as "no judge miss can escape".

## Experimental (implemented, NOT sufficiently validated — do not headline)

- Semantic verifier (`--semantic-verify`, opt-in): tri-state PASS/REVIEW/FAIL
  contract (`semantic-verifier-1.0`), selector/verifier independence (objective
  + candidate only), fail-closed REVIEW on error/timeout/invalid, bounded
  FAIL restoration (≤ `--verifier-max-restorations`, one pass, no re-verify
  loop). 1 extra Jev call max. Contract unit-tested + live-calibrated above;
  remaining open: FAIL-band live observation, generative-downstream answer
  lift. Until then: safety flag, not guarantee.
- Live Laya judge on arms A/B/C (`run_judge_ablation.py --judge laya`):
  NOT VALIDATED (laya extra unavailable in this environment). Mock-harness
  rows above prove the harness only.
- Generative downstream answer grading (RAW vs LCC vs LCC+verifier on ≥2
  downstream LLMs via `run_answer_preservation.py --downstream-cmd`):
  NOT VALIDATED — no generative key in this environment. Mock-extractive
  figures above.
- Neighborhood-aware cache identity: related blocks bind neighbourhood hash;
  isolated blocks content-only. Awaiting warm-cache byte-stability re-measure.
- DecisionCache GC (TTL/LRU/compaction): measure via `DecisionCache.stats()`
  first; no policy shipped.

## Number discipline

README headlines MUST match a row above. Anything else is labelled
historical or experimental with its repro command.
