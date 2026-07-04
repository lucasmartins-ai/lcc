# Hackathon Baseline Declaration

This repository started from the pre-existing Local Context Compiler (`lcc`) codebase. The
AMD ACT II work is the router layer and submission harness built around that baseline.

## Pre-Existing Before Hackathon

- deterministic context cleaning;
- deduplication;
- token counting with exact-vs-approximate reporting;
- cost estimation;
- `lcc inspect`;
- `lcc prepare`;
- lexical selection;
- deterministic benchmark harness;
- deterministic documentation and ADRs.

These capabilities live under `src/lcc/`, `docs/`, `benchmarks/`, and the original LCC tests.
They should not be represented as newly built during the hackathon.

## Built For AMD ACT II

- hybrid local/remote router in `act2_router/`;
- local model adapter and mock local solver;
- local verification gate;
- Fireworks AI escalation client and mock remote fallback;
- routing policy and configs;
- task adapter and local evaluation runner;
- Dockerized demo/evaluation path;
- hackathon-specific documentation.

## Claim Boundaries

- No official performance result is claimed before official evaluation.
- The router is policy-driven, not optimal.
- Local verification is a conservative quality gate, not a correctness guarantee.
- Local tokens are treated as zero-cost for Track 1 scoring, but local inference still uses
  compute.
- Fireworks remote tokens are counted when returned by the API and estimated conservatively
  when usage is missing.
