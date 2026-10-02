# Risk Register (Sprint 0, living doc)

| # | Risk | Likelihood / Impact | Mitigation (owner: Sprint) |
|---|---|---|---|
| R1 | Overengineering / monolith creep | H / H | Layered contracts (03); per-sprint acceptance gates; ponytail rule: smallest diff |
| R2 | Benchmark contamination (SYNTHETIC tuned, claimed as real) | H / H | Dataset classes REAL/ANONYMIZED/REPLAYED/CURATED/SYNTHETIC/HYBRID mandatory; triage-bench stays SYNTHETIC-labelled |
| R3 | Model-judge bias / circular evaluation (Jev scores + verifies) | H / H | Selector/verifier independence (verifier sees only objective+candidate); deterministic checks first; record judge+version |
| R4 | False context drops (relevance ≠ necessity) | H / H | Fail-closed defaults; protection reasons; sufficiency+restore; measure false-drop rate; ablation (Sprint 6) |
| R5 | Unsafe de-escalation (cheap route, wrong answer) | M / H | Escalation policy explicit; measure false_deescalation_rate — more important than compression |
| R6 | Provider variance / window changes (32K guard, tokenizer drift) | M / M | Pre-flight guard + recalibration probe (`calibrate_preflight_tokens.py`); cache epochs on policy change |
| R7 | Non-determinism breaking receipts/goldens | M / M | Deterministic-first; versioned policies; sticky cache keys; seeds recorded |
| R8 | Evaluation cost / latency amplification (verify-everything) | M / M | Budgets in Task Contract; break-even accounting (`invalidated_tokens`, `break_even_reuses`); Pareto reporting |
| R9 | Schema lock-in (IR/Contract freeze too early) | M / M | v0 experimental; validate on 5 fixtures before freeze; independent versioning |
| R10 | Repository fragmentation (7 repos, 3 single-commit) | H / M | Boundaries in 04; archive act2; intake decision Sprint 1 |
| R11 | Poor DX (research-grade CLI) | M / M | Sprint 8 gate: pip install → first compile in 5 min, offline defaults |
| R12 | Concept drift (relevance thresholds stale) | M / L | Golden fixtures + periodic re-measurement; thresholds in policy version |
| R13 | Synthetic-data overfitting | H / M | Never market synthetic as production; real-session + replayed tracks required in MSI-Bench |
| R14 | Single-maintainer bus factor | M / H | ADRs + docs hierarchy (spec repo); tests as executable spec |

Top-3 to actively manage in Sprint 1–2: R4 (false drops), R5 (false de-escalation), R2 (contamination labelling).
