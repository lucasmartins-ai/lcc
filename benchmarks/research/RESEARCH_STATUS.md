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
| answer-eval (live Laya multilingual, offline) | 30 cases, 0 regressions; every case kept its tokens unchanged (keep-all selector) | adversarial_cases | 30 | laya-multilingual | exact o200k | 2026-09-21 | `python3 run_answer_eval.py --provider laya` (offline; artifact `results/answer_eval_laya_live.json`) | required-fact recall, not generative grading; zero regressions is trivial for a keep-all pass |
| answer preservation (live jev selector, mock downstream) | −58 tokens/task, correctness delta 0.0; verifier PASS 29–31, REVIEW 19–21, FAIL 0 | 50 synthetic tasks × 10 domains | 50 | jev-1.13.0 (resolved) | heuristic | 2026-09-21 | `python3 run_answer_preservation.py --provider jev` | mock extractive downstream; generative-LLM grading NOT VALIDATED |
| answer preservation (live Laya selector, mock downstream) | 0 tokens/task delta at aggregate (keep-all); correctness delta −0.02 driven by ONE task where the selector dropped the evidence block and kept noise (`policies-2`, see findings); verifier PASS 1, REVIEW 0/50, FAIL 0; blocks_restored 0 | 50 synthetic tasks × 10 domains | 50 | laya-multilingual | heuristic | 2026-09-21 | `python3 run_answer_preservation.py --provider laya` (artifact `results/answer_preservation_laya_live.json`) | mock extractive downstream; generative-LLM grading NOT VALIDATED |
| judge ablation (live jev A/B/C) | raw: 2 false drops (recall 0.667); safety: unchanged (unlinked evidence); verifier: REVIEW, +1 call | ablation corpus (6 evid + 6 noise) | 12 blocks | jev-1.13.0 (resolved) | heuristic | 2026-09-21 | `python3 run_judge_ablation.py --judge jev` | 1 corpus; isolated-evidence gap visible (see calibration §) |
| judge ablation (live Laya multilingual, A/B/C) | arms identical: recall 1.0, precision 0.5, **false_drops 0, false_keeps 6/6** (kept every noise block), reduction 0.0, 2 calls/arm | ablation corpus (6 evid + 6 noise) | 12 blocks | laya-multilingual (resolved `laya-rl-agent`) | heuristic | 2026-09-21 | `python3 run_judge_ablation.py --judge laya` (offline; `LCC_LAYA_MODEL` selects checkpoint) | keep-all at default settings: no signal on this corpus; Laya never drops here, so safety arms have nothing to close |
| judge ablation (live Laya typed-decisions, A/B/C) | identical keep-all outcome: false_drops 0, false_keeps 6/6, reduction 0.0, 2 calls/arm | ablation corpus | 12 blocks | laya-typed-decisions | heuristic | 2026-09-21 | `python3 run_judge_ablation.py --judge laya --laya-model convaiinnovations/laya-typed-decisions` | checkpoint must be passed via `--laya-model`; env alone is stamped over (see open observation) |
| multi-scale comparison (live Laya multilingual vs mechanical vs jev) | small 1226→1226 (**0.0%**, 0 dropped) / mechanical −26.2% / jev −21.2%; medium 4533→4533 (**0.0%**) / −57.6% / −40.0%; large 11617→11617 (**0.0%**) / −65.5% / −49.6%; category recall 100% all arms | corpora small/medium/large | 3 scales | laya-multilingual + jev-1.13.0 + mechanical | o200k exact | 2026-09-21 | `python3 run_laya_comparison.py` (real by default; `--mock` for harness only) | Laya keeps everything: reduction 0.0 at every scale; CPU latency 33–43 s/pass |
| Laya context-budget A/B/C (live, offline) | A: 6 blocks, 1 call, budget 182/1024, 0 insufficient; B: medium corpus, 19 calls, budget 355/1024, 0 dropped, 0 insufficient; C: 20,063-token input, 22/25 oversized blocks **kept whole** (`laya_context_limit_exceeded`), tail byte-identical (no slicing), 1 call | synthetic A/C + corpora medium | 3 cases | laya-multilingual | o200k + `count_tokens` | 2026-09-21 | `python3 run_laya_context_cases.py` (offline: `LCC_DISABLE_NETWORK=1`, key unset) | budget never exceeded; no naive truncation observed |
| Laya context-budget A/B/C (typed-decisions checkpoint) | same shape: budgets 182/355/520, 0 drops, 0 insufficient on A/B, 22/25 oversized kept whole on C, 19 calls on B | synthetic A/C + corpora medium | 3 cases | laya-typed-decisions | o200k | 2026-09-21 | `python3 run_laya_context_cases.py --model convaiinnovations/laya-typed-decisions` | confirms budget plumbing is checkpoint-independent |
| comparative stress, 4 scales (real backends) | mechanical −26.2/−57.6/−65.5/−70.0%; Laya multilingual **−0.0/−0.0/−0.0/−0.5%** (0–1 blocks dropped); Jev −21.2/−40.0/−49.8/−52.1%; recall 100% every arm; Laya CPU 32–107 s/pass; Jev $0.005–$0.187 per scale | corpora small→xl | 4 scales | laya-multilingual + jev-1.13.0 + mechanical | exact o200k | 2026-09-21 | `python3 run_comparative_stress_test.py` (real default; `--mock` = labelled harness) | edge + cache stages in the same artifact |
| comparative stress, small→large (typed-decisions checkpoint) | Laya typed-decisions **−0.0/−0.0/−0.0%** (keep-all; CPU 35/42/58 s per pass); Jev −21.2/−39.1/−49.7%; mechanical unchanged | corpora small/medium/large | 3 scales | laya-typed-decisions + jev-1.13.0 + mechanical | exact o200k | 2026-09-21 | `python3 run_comparative_stress_test.py --scales small medium large --laya-model convaiinnovations/laya-typed-decisions` | XL not run for this checkpoint (time budget); same keep-all outcome at defaults |
| edge / adversarial (real, stage 2) | giant 20,035-token block: mechanical collapses the file to 14 tokens (its constraint not retained, recall 0); Jev −99.8% recall 1.0 retained; Laya −0.0% recall 1.0, block kept whole. Prompt injection: mechanical/Jev drop the override block; Laya keeps it (keep-all). Noise grid (151 short blocks): all arms keep (below min block size) | synthetic edge cases | 3 cases × 4 arms | laya-multilingual + jev-1.13.0 + mechanical | o200k | 2026-09-21 | same script, stage 2 | block-granularity caveats pre-date this validation (noted, not fixed) |
| cache cold/warm (real Laya) | cold 43.2 s → warm 0.5 s (83.6×), 391 decisions reused, byte-identical (`sha256` match) | large corpus | 2 runs | laya-multilingual | o200k | 2026-09-21 | same script, stage 3 | real-model decisions-cache path |

| tool-call A/B vs `fast-jev-compaction` (live jev, synthetic transcripts) | lcc −13.3 / −39.2 / −55.7% tokens at fact recall 1.00 / 1.00 / 1.00 (one of four runs dropped an evidence pair on the largest session; large ranged −55.7 to −61.5%); fast-jev −70.5 / −78.9 / −83.4% at fact recall 0.00 (every evidence pair dropped, every run) | `corpora/transcripts` small/medium/large | 3 sessions (11/20/32 tool calls) | jev-1.13.0 (lcc) + fast-jev-compaction 0.4.0 | exact o200k | 2026-09-21 | `python3 make_transcripts.py && python3 run_transcript_ab.py` | synthetic corpus, N=3, single seed and objective; the npm arm reports no usage and no resolved model; backends only, no live editor session. Full method, stability runs, and the two defects it found in our own code: `benchmarks/research/TRANSCRIPT_AB.md` |

| tool-call compaction, real Claude Code session | full 192-message session (75 tool calls) 55 411 → 18 761 tokens (**−66.1%**), 23 kept / 24 trimmed / 28 dropped, all 42 user+assistant texts byte-identical; newest 80 messages −20.4% (below the plugin's 25% minimum, so the hook keeps the built-in summary there) | `~/.claude/projects/-Users-Master-lcc/fd825893….jsonl` | 2 windows | jev-1.13.0 | exact o200k | 2026-09-21 | `python3 measure_session.py --claude-code <path> --window-messages 80` | one run per window, one session; the editor's own `/compact` was not intercepted; no ground truth for tool payloads; no downstream answer-quality measure. Method and the budget defect it found: `benchmarks/research/REAL_SESSIONS.md` |
| tool-call compaction, real Hermes session | full 337-message session (187 tool calls) 199 717 → 36 645 tokens (**−81.7%**, fit stage `calls-one-line`), 14 kept / 53 trimmed / 119 dropped, all 58 user+assistant texts preserved; newest 60 messages −63.4% | `~/.hermes/state.db` session `20260921_225926_e0d6bd` | 2 windows | jev-1.13.0 | exact o200k | 2026-09-21 | `python3 measure_session.py --hermes latest --window-messages 60` | one run per window; a live session that keeps growing, so the numbers move with it; dropped tool payloads are judged spent, not proven spent |

## Benchmark (dataset-specific, reproducible offline)

| Metric | Value | Dataset | N | Provider | Tokenizer | Date | Repro | Limitations |
|---|---|---|---|---|---|---|---|---|
| judge ablation (mock-laya) | raw 2 false drops → safety closes both; verifier +1 call | ablation corpus (6 evid + 6 noise) | 12 blocks | mock stand-ins | heuristic | 2026-09-20 | `python3 run_judge_ablation.py --judge mock-laya` | mock judges prove the harness, NOT Laya/Jev quality |
| judge ablation (mock-jev) | raw already clean; safety changes nothing | ablation corpus | 12 blocks | mock stand-ins | heuristic | 2026-09-20 | `python3 run_judge_ablation.py --judge mock-jev` | same: harness only |
| judge ablation (mechanical) | raw 5 false drops → safety recovers 2 | ablation corpus | 12 blocks | mechanical | heuristic | 2026-09-20 | `python3 run_judge_ablation.py --judge mechanical` | lexical baseline behaviour |
| answer preservation (mock) | −58 tokens/task, correctness delta 0.0 | 50 synthetic tasks × 10 domains | 50 | mechanical | heuristic | 2026-09-20 | `python3 run_answer_preservation.py` | mock extractive downstream; live LLM NOT VALIDATED |

> Mock provenance (kept for honesty): `comparative_stress_results_2026-09-19_mock.json`
> and `laya_comparison_2026-09-20_mock.jsonl` preserve the pre-validation figures the
> earlier README text quoted for "Laya" and "Jev" (both columns came from the same
> `CalibratedMockAgent`, which is why they were byte-identical). Harness evidence only —
> never cite them as model behaviour.

## Laya validation — network verification (2026-09-21)

- Laya runs execute with `LCC_DISABLE_NETWORK=1` + `HF_HUB_OFFLINE=1` +
  `TRANSFORMERS_OFFLINE=1` and no `TYPESAFE_API_KEY` in the environment. By the
  repo's own kill-switches (`jev.py`: `LCC_DISABLE_NETWORK` → `JevClient.from_env()`
  returns None; `laya.py`: HF offline env), no remote semantic API or model hub is
  reachable; the passes still report `provider_used: laya`, `degraded: false`,
  `semantic_guarantee: judged` — so the decisions cannot have come from a remote call
  or from the mechanical fallback.
- Jev rows (by design) call the remote TypeSafe API; per-scale cost is recorded in the
  artifact (`$0.005` small → `$0.187` XL).
- Open observation (pre-existing, flagged — not fixed here): a pass where every block
  is protected (nothing scored) still reports `semantic_guarantee: judged` (vacuous
  truth, see the `high_density_noise` rows). Follow-up candidate.
- Open observation (checkpoint selection): `LCC_LAYA_MODEL` — and an injected
  `LayaClient(model=...)` — is stamped over by
  `RelevanceCompactionRequest.laya_model` (default `convaiinnovations/laya-multilingual`)
  inside `compact_context`, so programmatic checkpoint changes need the request field
  (`laya_model=`). The benchmark harnesses now expose `--laya-model`; letting the
  explicitly constructed client win over the request default in `compactor.py` is a
  follow-up candidate (touching it without tests would risk the CLI path, which
  relies on the request field).

## Live Laya findings (2026-09-21, real weights — measured, not assumed)

- **Keep-all is the aggregate behaviour, not a guarantee.** Across the corpora the
  default checkpoint drops 0–1 blocks at every scale, so reduction is ~0%; but the
  50-task preservation sweep contains ONE task (`policies-2`; 3 blocks: noise /
  key finding on POL-102 / noise) where the selector dropped the **evidence**
  block and kept both noise blocks — the exact inverse of mechanical, and the
  source of the −0.02 correctness delta. Judge quality, not the 1K window,
  remains the bottleneck; individual drops are not safe by construction.
- **Budget plumbing is checkpoint-independent.** Both 1024-token checkpoints stay
  inside the budget (max used 520), keep oversized blocks whole and never slice;
  no fallback occurred in any offline run (rows above).
- **Wrong-direction scores exist.** An isolated probe on the exact compactor
  question separated evidence (≈0.48) from noise (≈0.39) for
  `laya-typed-decisions`; the multilingual checkpoint returned near-constant
  scores per phrasing (≈0.73 for everything, or ≈0.08 with a reworded question).
  Phrasing/calibration is an open study — see the open observations below.

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
  VALIDATED 2026-09-21 on real weights (HF cache, macOS CPU, offline —
  `LCC_DISABLE_NETWORK=1`, no API key present). Measured behaviour with the
  default checkpoint (`convaiinnovations/laya-multilingual`): keep-all at
  default settings — 0.0% reduction at every scale, 6/6 noise blocks kept on
  the ablation corpus, and no discrimination between evidence and distractors
  in the current question shape. Consequence: the pre-validation headline
  ("same recall and reduction as remote Jev") was mock arithmetic, not model
  behaviour — see the mock-provenance note above. The
  `convaiinnovations/laya-typed-decisions` checkpoint separates evidence from
  noise in an isolated probe (≈0.48 vs ≈0.39) but its in-batch scores stay
  above the 0.4 drop band on the evaluated corpora, so it is keep-all there
  too; its rows are in the canonical table.
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
