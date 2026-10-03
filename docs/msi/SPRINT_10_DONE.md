# Sprint 10 — DONE (PASS)

- **Date:** 2026-10-03
- **Gate:** `SPRINT_9_DONE.md` = PASS (verified); audit report `research/msi-audit-2026-10-03.md` reviewed and all three release-blocking findings (R1, R2, R3) resolved with regression test coverage.
- **Scope:** Research release consolidation and freeze. Zero new features, zero unbacked claims, zero new benchmark numbers. Reference repositories remained read-only. No external package publication or rebranding performed.

---

## 1. Resolution of Audit Release Blockers (R1–R3)

| Blocker ID | Audit Finding | Resolution Applied in Sprint 10 | Regression Evidence & Verification |
| --- | --- | --- | --- |
| **R1** | Sprint-7 costs only accounted for terminal attempt, omitting retries and earlier attempts. | `benchmarks/msi-bench/bench.py::run_arm` now iterates through receipt decision events and accounts for context tokens and routed model across every executed attempt and retry. Decision-01 under verify arm records 3 attempts and 3 frontier calls at $3.2160, updating verify arm total cost from $2.2160 to $4.3600. | `test_modeled_chain_cost_counts_all_executed_attempts` PASS in `tests/test_msi_bench.py`. |
| **R2** | `bootstrap_ci` advanced one RNG across arms in an arm loop, drawing different task resamples per arm despite the paired claim. | `bench.py::bootstrap_ci` pre-generates task resample sets (`samples = [[rng.choice(tids) for _ in tids] for _ in range(resamples)]`), evaluating every arm against the identical task draw on each resample iteration. | `test_paired_bootstrap_uses_same_task_sample_for_every_arm` PASS in `tests/test_msi_bench.py` (proves identical intervals on identical task success profiles). |
| **R3** | `run.py --check` only checked outcome digest and task hashes, accepting changes to aggregate costs or receipt payloads. | Implemented `check_payload(actual, frozen)` in `benchmarks/msi-bench/run.py` using `_stable` filtering. Any mutation to aggregates, Pareto arms, bootstrap intervals, or receipts raises `AssertionError: payload drift`. | `test_check_rejects_aggregate_drift_even_when_outcome_digest_matches` PASS in `tests/test_msi_bench.py` (corrupting aggregate cost raises `AssertionError`). |

*Re-frozen benchmark matrix digest:* `13a29b20a099681eb6188d54c0fa12ba44c8332c33f44bfcb88c28b55687bb80` (72 runs: 12 tasks $\times$ 6 arms, all 72 pre-registered predictions match).

---

## 2. Acceptance Criteria Verification

### Criterion 1: Zero claims of novelty or superiority without citation or paired measurement
- **Status:** PASS
- **Evidence:** Comprehensive repository audit searching for `novel|SOTA|first|best|guarantee` across all markdown and code documentation. Zero unbacked claims exist.
- **Published Document:** `research/prior-art.md` categorizes contributions into prior art (lexical matching, token accounting, cascading, unit tests), incremental adaptations (cache-aligned compaction, tool-result pruning), and MSI-specific architectures (`context-ir/0.1`, `verify-1.0`, bounded restore-before-retry, `inference-receipt/0.1`). Formal comparison provided against LLMLingua, FrugalGPT, RouteLLM, and Reflexion.

### Criterion 2: `limitations.md` and research agenda published; versions frozen and stamped
- **Status:** PASS
- **Published Documents:**
  - `research/limitations.md`: Complete disclosure of structural limitations, including the oracle carrier protection vs. mechanical compiler distinction, deterministic rubric constraints, illustrative pricing schedules, and five falsifiable research questions (Q1: Non-oracle carrier identification; Q2: Real-world latency breakeven; Q3: Automatic cross-turn dependency inference; Q4: Benchmark transfer to SWE-bench Lite; Q5: Disentanglement of co-located injections).
  - `research/versions.json`: Machine-readable version manifest stamping schemas (`context-ir/0.1`, `planner-contract/0.1`, `inference-plan/0.1`, `inference-receipt/0.1`, `transcript-compaction-1.0`), engines (`planner-1.0`, `verify-1.0`), and frozen datasets (`msi-pilot-6-frozen-2026-10-03`, `msi-bench-7-frozen-2026-10-03`, `msi-replay-9-curated-2026-10-03`, `msi-replay-9-session-2026-10-03`).
  - `research/results-master.md`: Master table listing every empirical measurement across Sprints 6, 7, 9, 10, and baselines with per-row provenance (dataset, N, data class, evidence class, commit, reproduction command).
  - `research/paper.md`: Complete architecture paper ("Minimum Sufficient Inference: Closed-Loop Context Compaction with Bounded Verification").
  - `docs/adr/0022-research-release-freeze.md`: ADR 0022 accepted and indexed in `docs/adr/README.md`.

### Criterion 3: Simulated third-party end-to-end reproduction
- **Status:** PASS
- **Evidence:** Executed outside the source repository in `/tmp/lcc-thirdparty-repro-run` using an isolated virtual environment (`/tmp/lcc-thirdparty-repro-venv`) installed strictly from the built wheel (`local_context_compiler-1.0.0-py3-none-any.whl`).
- **Logged Steps:**
  1. Wheel installation: clean install of `local-context-compiler==1.0.0` with base dependencies (typer, rich, pyyaml).
  2. CLI Quickstart:
     - `lcc optimize dossier.md -o prompt.md -r clean.json` (38.9% token savings, prompt written, report valid).
     - `lcc inspect dossier.md -r inspect.json` (report valid, small_input skip).
     - `lcc compact dossier.md -q "..." --provider mechanical -o compacted.md -r report.json` (`semantic_guarantee: none`, 0 scored, 3 protected).
     - `lcc explain report.json --source dossier.md` (clean rationale display).
     - `lcc diff dossier.md compacted.md` (clean comparison, exit code 0).
  3. Python `compile()` API:
     - `result = compile(...)` executed outside repo; emitted valid context, sufficiency dictionary, and `inference-receipt/0.1` receipt with verification `PASS`.
  4. Benchmark Category Reproduction:
     - Category `coding` (tasks `coding-01` and `coding-02` $\times$ 6 arms = 12 runs): 9/12 passes, all 12 cells reproduced verbatim matching frozen predictions and costs.

### Criterion 4: Full suite + docs tests + links + clean install green
- **Status:** PASS
- **Evidence:**
  - Pytest full suite: **826 passed, 5 skipped, 0 failed** in 12.8s.
  - Node test suite: **Unit suite + 11 hook-mapping tests passed**.
  - Static typing: **mypy clean** over 95 configured source files (`--python-version 3.12`).
  - Linter: **ruff check clean** over source, tests, benchmark runners, and usability scripts.
  - Documentation links: **8 passed in `tests/test_docs.py`**; all relative targets and anchors resolve.
  - Packaging checks: **twine check on wheel and sdist PASSED**; `LICENSE` and `NOTICE` present in both archives.
  - Benchmark runners:
    - `benchmarks/msi-bench/run.py --check` -> PASS (`digest 13a29b20...`, 72 runs).
    - `benchmarks/msi-replay/replay.py --check` -> PASS (`digest a636d2f1...`, 60 runs).
    - `benchmarks/msi-replay/session_replay.py --check` -> PASS (20 runs).
  - Usability runner: **36/36 checks passed** (12 scenarios $\times$ 3 repetitions, 0 failures).

---

## 3. Deliberately Skipped (Out-of-Scope)
- **New live model evaluations:** Live OpenAI/Anthropic/Bedrock API benchmarking was explicitly out of scope for Sprint 10; all figures remain offline, deterministic, and modeled.
- **Public PyPI upload / git push:** Changes remain in the local working tree on branch `msi/sprint-10-release` as instructed by protocol ("Não faça push, não crie PR, não arquive repositório, não publique nada externo").
- **Package rebranding:** Package name remains `local-context-compiler`.

---

## 4. Known Limitations
- The `msi` 12/12 arm is an oracle probe using pre-declared fact/citation carriers, not the standalone public mechanical compiler.
- Prices and inference latencies are modeled approximations.
- See `research/limitations.md` for full discussion.

---

## 5. Next
Research release complete: Sprints 1–10 are delivered in full with all acceptance criteria, frozen version manifests, and green validation gates.
