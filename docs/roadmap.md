# Roadmap

This roadmap is aspirational. **Only Phase 1 and the deterministic benchmark harness
(Phase 1.5) are implemented today.** No other phase is present in the code, and the
documentation never describes a later phase as if it were.

## Phase 1 — Deterministic MVP (implemented)

- Read from file or stdin.
- Normalize whitespace, line endings, and blank-line runs.
- Conservative boilerplate removal (whole-line matches).
- Exact and conservative near-duplicate paragraph deduplication.
- Exact token counting via `tiktoken` with an honest approximate fallback.
- **Tokenizer network guard (completed hardening).** Runtime network access is blocked by
  default, including the first-use encoding download `tiktoken` would otherwise perform; exact
  counting requires locally cached encoding assets, and otherwise falls back to a clearly
  labelled approximate count (ADR 0008).
- Editable, configurable pricing and input-cost estimation.
- Evidence-aware prompt builder with an extensible template registry.
- JSON `OptimizationReport` (`schema_version` 1.0) and a `lcc` CLI (`optimize`, `bench`).

## Phase 1.5 — Deterministic benchmark harness (implemented)

- A fixture-based harness (`lcc.benchmarking`, `lcc bench`) that runs the pipeline over
  committed cases in `benchmarks/cases/` and reports **mechanical** metrics: token savings,
  compression ratio, character reduction, exact/approximate token mode, literal marker
  preservation, and warnings — with explicit per-case thresholds and a versioned,
  deterministic JSON/Markdown report (ADR 0007).
- It measures deterministic optimization behavior only; it does **not** evaluate LLM answer
  quality. Semantic/quality benchmarking remains Phase 7.

## Phase 2 — Local semantic retrieval (planned)

- Optional local chunking + embeddings + similarity selection (e.g. a local vector index).
- Selects the most relevant chunks for the question, feeding cleaned context into the
  existing pipeline. Fully optional and isolated; the deterministic core is unchanged.

## Phase 3 — Local intent classifier (planned)

- A small local classifier to infer task type and shape the prompt template, with no
  required network access.

## Phase 4 — Evidence extraction (planned)

- Span-level provenance: tie statements in the context to their source locations and attach
  that provenance to the prompt package.

## Phase 5 — Model routing (planned)

- Choose a downstream model from a configurable cost/quality policy, using the token and
  cost estimates `lcc` already produces.

## Phase 6 — Response verification (planned)

- After the downstream LLM responds, check the answer for unsupported claims against the
  provided evidence and surface an "unsupported claim rate" (see `evaluation.md`).

## Phase 7 — Benchmark suite and integrations (planned)

- The deterministic benchmark harness already landed as Phase 1.5 (above). Phase 7 extends
  it with **quality-preservation** measurement across representative datasets (requiring a
  downstream model you control) plus integrations (library API, framework adapters).

## Other planned surfaces (not implemented)

These are explicitly **not** in v0.1.0 and are listed here so the docs never imply they
exist:

- A standalone inspect / token-count command (counting and reporting without building a
  prompt).
- Transcript ingestion (importing and normalizing conversation/meeting transcripts).
- An API server / hosted service.
- Voice / audio adapters and ASR (speech-to-text).

Each, if pursued, lands behind a new, clearly separated boundary; none touches the
deterministic core.

## Guiding constraints for every phase

- Keep the deterministic core dependency-free and free of network/LLM code.
- Add new capabilities behind new, clearly separated boundaries (ADRs 0002, 0006).
- Keep new dependencies optional and justified.
