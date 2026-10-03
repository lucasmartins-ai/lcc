# ADR 0022: Research release freeze — contracts, versions, and verification boundaries

**Status:** accepted  
**Date:** 2026-10-03  

## Context

Sprints 1–9 delivered the Minimum Sufficient Inference (MSI) protocol across five core specifications (Context IR, Planner Contract, Inference Plan, Layered Verification, Inference Receipt), paired quality-cost benchmarks, and session replay harnesses. The independent release audit identified three methodological blockers in Sprint 7 (final-attempt cost accounting, unshared bootstrap draws, and aggregate drift in `--check`), which were resolved in Sprint 10.

A formal release freeze is required to pin all protocol versions, schema snapshots, and empirical baselines before public dissemination.

## Decision

1. **Frozen Specification Contracts:**
   - Context IR is frozen at `context-ir/0.1`.
   - Planner Contract is frozen at `planner-contract/0.1`.
   - Inference Plan is frozen at `inference-plan/0.1`.
   - Inference Receipt is frozen at `inference-receipt/0.1`.
   - Evaluation engine is frozen at `verify-1.0` under profile `standard`.
   - Planning engine is frozen at `planner-1.0`.

2. **Honest Operational Boundaries:**
   - Standalone mechanical mode (`--provider mechanical`) is strictly deterministic, lexical, and AST-driven. It guarantees byte-faithfulness and cache prefix alignment, but makes no semantic sufficiency claim (`semantic_guarantee: none`).
   - The high-performing `msi` arm in benchmarks is explicitly designated as an **oracle probe** utilizing pre-declared carrier labels to establish theoretical upper bounds, distinct from the mechanical compiler.

3. **Frozen Benchmark Datasets and Hashing:**
   - `msi-bench-7-frozen-2026-10-03` ($N=72$, matrix digest `13a29b20a099681eb6188d54c0fa12ba44c8332c33f44bfcb88c28b55687bb80`).
   - `msi-replay-9-curated-2026-10-03` ($N=60$, matrix digest `a636d2f1ff4ac1f46f20e343c6b48e80b0f99cd3475c54405ab47cc5f085f5fb`).
   - `msi-replay-9-session-2026-10-03` ($N=20$, 10 observation windows from 7 local sessions).
   - All benchmark runners require full stable payload verification (`--check`), asserting that both individual receipts and aggregated metrics match the committed freeze.

4. **Prohibition of Unbacked Claims:**
   - No claim of superiority, SOTA, or novelty may be stated without a cited prior-art comparison or paired empirical measurement with declared sample size and limitations.

## Consequences

- Any future schema evolution must introduce a new minor version (e.g., `0.2` or `1.0`) with backwards-compatible migration tests.
- CI and regression suites enforce immutability of the frozen payloads and rejection of aggregate drift.

## Forecloses

- Silent mutations of benchmark digests or cost figures.
- Marketing claims of "semantic guarantees" on purely lexical passes.
- Promoting oracle probe results as production compiler measurements.
