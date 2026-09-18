# RESEARCH_STATUS — canonical measurements (single source of truth)

One table answers "what is the true current number?". Historical and
experimental figures live below it and never in the README headline.

## Current canonical

| Metric | Value | Dataset | N | Provider | Tokenizer | Date | Repro | Limitations |
|---|---|---|---|---|---|---|---|---|
| adversarial E0 (mechanical) | 30/30, 0 regressions | adversarial_cases | 30 | mechanical | heuristic | 2026-09-18 | `python3 run_answer_eval.py --provider mechanical` | synthetic corpora, regex recall |
| multi-agent pilot E1 | 0 E1 regressions, mean red 54.3% | PILOT_IDS (5 domains) | 20 | mechanical | heuristic | 2026-09-18 | `python3 run_multiagent_ab.py --tasks 20` | mock answerer, not live LLM |
| injection Property B | 3/3 pass | injection_html/log + prompt_injection | 3 | mechanical | heuristic | 2026-09-18 | `python3 run_injection_e2e.py` | deterministic mock downstream |
| agent A/B (live, prior) | ctx −61.2%, prompt −9.1%, recall 5/5 | dossier A/B | 18 agents | jev | exact o200k | prior study | `make_payloads.py + score_agents.py` | 3 samples/arm, 1 scale |
| per-payload vs whole-session | −42.4% vs −7.9% context cost | cache_patterns sim | 5 turns | n/a | exact | prior study | `run_cache_patterns.py` | price model read 0.10x/write 1.25x |

## Historical (superseded reduction columns — Finding 14)

Pre-sufficiency matrix reductions (Findings 9/10/12/13) are superseded by
Finding 14 table (mechanical small 44.8→26.2%, Jev small 32.5→21.2%, etc.).
Recall columns and cache findings unaffected in kind.

## Experimental

- Semantic verifier (`--semantic-verify`): 1 extra Jev call, REVIEW signal-only.
  Needs live-key measurement before canonical numbers.
- Neighborhood-aware cache identity: related blocks bind neighbourhood hash;
  isolated blocks content-only. Awaiting warm-cache byte-stability re-measure.
- DecisionCache GC (TTL/LRU/compaction): measure via `DecisionCache.stats()`
  first; no policy shipped.

## Number discipline

README headlines MUST match a row above. Anything else is labelled
historical or experimental with its repro command.
