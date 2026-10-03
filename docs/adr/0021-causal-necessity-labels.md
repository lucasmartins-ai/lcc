# ADR 0021: Causal necessity labels stay research-only

**Status:** accepted

**Date:** 2026-10-03

## Context

Sprint 6 built a remove-and-replay harness (`src/lcc/router/ablate.py`,
harness `ablate-1.0`) that labels context units NECESSARY /
CONDITIONALLY_NECESSARY / REDUNDANT / UNNECESSARY / PROTECTED / UNKNOWN by
observed outcome delta, and ran a PILOT (N=8, `research/causal-necessity.md`,
`benchmarks/ablation/pilot_results.json`). The pilot shows single-removal
separates NECESSARY from the rest, while pair ablation + token-coverage are
needed for the conditional/redundant/noise split.

## Decision

1. Necessity labels are research artifacts. Nothing in production reads
   them: IR `necessity` stays `UNKNOWN` (ADR-0017 default unchanged), the
   planner (`planner-1.0`) takes no label input, and no CLI surfaces them.
2. Labels become eligible for production use only after sprint-7 validation
   (MSI-Bench, paired quality + cost). A future ADR supersedes this one; no
   silent wiring.
3. Label instability across repeats is UNKNOWN, never a forced category
   (enforced in `run_pilot`, tested).
4. Pilot cap holds: no ablation run above N=30 units without a recorded
   pilot first (cost rule: each replay costs one executor inference once a
   model-backed executor exists).

## Consequences

- Sprint 7 (MSI-Bench) must define the validation bar for promoting any
  label to production (paired outcome + cost evidence, not pilot reuse).
- The harness may grow new baselines/executors, but the research-only
  boundary stays until superseded here.

## Forecloses

- Using pilot labels to trim production context.
- Training or tuning anything on N=8 pilot labels.
- Large-N ablation without a costed pilot.
