# Master Results and Provenance Table

**Document version:** 1.0.0  
**Freeze date:** 2026-10-03  
**Status:** RELEASE-FROZEN  

This document consolidates all empirical measurements produced across Sprints 1–10. In accordance with the Anti-Slop Protocol (`docs/msi/prompts/00-protocol.md`), **every row carries its exact dataset, sample size ($N$), data class, evidence class, commit hash, and reproduction command**. No new experimental numbers are introduced in this consolidation.

---

## 1. Consolidated Master Table

| Sprint | Investigation / Benchmark | Dataset ID | Data Class | Evidence Class | Sample Size ($N$) | Primary Metrics Observed | Git Revision / Commit | One-Command Reproduction |
|---|---|---|---|---|---|---|---|---|
| **6** | Causal Necessity Pilot | `msi-pilot-6-frozen-2026-10-03` | CURATED | BENCHMARK | 1 task, 8 ablation runs | Necessity verified as conditional on rubric; carrier drop produces verifier FAIL | `b21696a` | `PYTHONPATH=src:benchmarks/msi-pilot python3 benchmarks/msi-pilot/pilot.py --check` |
| **7** | MSI-Bench Matrix (Pilot) | `msi-bench-7-frozen-2026-10-03` | CURATED | BENCHMARK | 12 tasks $\times$ 6 arms = 72 runs | Success rates: full 11/12, lcc 7/12, routing 11/12, lcc_routing 7/12, verify 8/12, msi 12/12. Modeled cost: full $22.86, routing $3.25, msi $2.50, verify $4.36. | `3f03d10` (updated in Sprint 10) | `PYTHONPATH=src:benchmarks/msi-bench python3 benchmarks/msi-bench/run.py --check` |
| **9** | Curated Regression Probes | `msi-replay-9-curated-2026-10-03` | CURATED | CURRENT | 10 traces $\times$ 6 arms = 60 runs | 25 terminal failures published; 36 attempt-level failures priced; 4 permanent failure fixtures reproduced | `4373161` | `PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python3 benchmarks/msi-replay/replay.py --check` |
| **9** | Replayed Local Sessions | `msi-replay-9-session-2026-10-03` | REPLAYED | CURRENT | 10 windows $\times$ 2 arms = 20 runs | 20/20 summary retentions PASS; zero public API replay regressions | `4373161` | `PYTHONPATH=src:benchmarks/msi-bench:benchmarks/msi-replay python3 benchmarks/msi-replay/session_replay.py --check` |
| **Audit / 10** | Packaged Base Usability | `usability-packaged-base-12x3` | SCRIPTED | CURRENT | 12 scenarios $\times$ 3 reps = 36 checks | 36/36 checks PASS; first compile 3.14 s (N=1, cold compile with pip cache, outside source tree) | `3c5a3bf` | `PYTHONPATH=src python3 benchmarks/usability/run.py` |
| **Baseline** | Answer Evaluation (E0) | `adversarial_cases` | CURATED | BENCHMARK | 30 adversarial cases | 30/30 pass, 0 regressions, mean token reduction 54.4% under mechanical mode | `main` | `python3 benchmarks/research/run_answer_eval.py --provider mechanical` |
| **Baseline** | Injection E2E (Property B) | `adversarial_cases` | CURATED | BENCHMARK | 3 prompt injection cases | 3/3 pass; malicious instructions unexecuted | `main` | `python3 benchmarks/research/run_injection_e2e.py` |

---

## 2. Granular Results by Track

### 2.1 Sprint 7: MSI-Bench Pilot Matrix ($N=72$)
*Matrix digest:* `13a29b20a099681eb6188d54c0fa12ba44c8332c33f44bfcb88c28b55687bb80`  
*Evaluator:* `verify-1.0` (profile `standard`) | *Planner:* `planner-1.0` | *Tokenizer:* `heuristic-v1`

| Arm | Description | Success / Total | Success Rate | 95% Bootstrap CI (Paired) | Modeled Cost (All Attempts) | Frontier Calls | Retained Tokens (Sum) | Pareto Status |
|---|---|---|---|---|---|---|---|---|
| `full` | All context, frontier model, single attempt | 11/12 | 0.917 | [0.750, 1.000] | $22.8640 | 12 | 679 | Dominated by `msi` |
| `lcc` | Lexical filter, local small, single attempt | 7/12 | 0.583 | [0.333, 0.833] | $0.0000 | 0 | 248 | **Nondominated** (Lowest cost) |
| `routing` | All context, planned model, single attempt | 11/12 | 0.917 | [0.750, 1.000] | $3.2480 | 2 | 679 | Dominated by `msi` |
| `lcc_routing` | Lexical filter, planned model, single attempt | 7/12 | 0.583 | [0.333, 0.833] | $2.2160 | 2 | 248 | Dominated by `lcc` |
| `lcc_routing_verify` | Lexical filter, planned model, bounded restore/retry | 8/12 | 0.667 | [0.417, 0.917] | $4.3600 | 4 | 261 | **Nondominated** (Intermediate context/cost) |
| `msi` | Lexical filter + oracle carrier protection, planned model, bounded restore/retry | 12/12 | 1.000 | [1.000, 1.000] | $2.5040 | 2 | 356 | **Nondominated** (Highest quality) |

### 2.2 Sprint 9: Curated Probes ($N=60$)
*Matrix digest:* `a636d2f1ff4ac1f46f20e343c6b48e80b0f99cd3475c54405ab47cc5f085f5fb`  
*Tracks:* 10 hand-authored failure-mode scenarios across 6 arms.
- **Failures published:** 25/60 runs failed; every failing run has a documented root-cause investigation and proposed experiment in `results.json#regressions`.
- **Permanent failure fixtures:** 4 fixtures (`f1-colocated-injection`, `f2-ambient-injection`, `f3-overlap-dragged-injection`, `f4-chain-break`) prove that context compaction without carrier awareness predictably fails on co-located adversarial instructions or broken dependency chains.

### 2.3 Sprint 9: Replayed Local Sessions ($N=20$)
*Dataset:* 10 observation windows extracted from 7 local developer sessions (`2026-06-18` to `2026-06-19`), anonymized via positive grammar.
- **Task:** Preservation of pytest execution summaries across tool results.
- **Outcome:** 10/10 PASS under full context; 10/10 PASS under MSI compaction. 0% quality degradation on local summary retention.
