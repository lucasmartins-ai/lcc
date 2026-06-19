# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [0.1.0] - 2026-06-19

First public release: the deterministic, local-first context-optimization MVP plus a
deterministic benchmark harness. No RAG, embeddings, vector databases, local or remote LLM
calls, API server, voice/audio, transcript ingestion, semantic scoring, model routing, or
response verification — those remain roadmap items (see `docs/roadmap.md`).

### Added

- Initial deterministic MVP — identical input produces identical output.
- Deterministic cleaning: `normalize_text`, `remove_common_boilerplate`,
  `deduplicate_paragraphs` (exact + conservative near-duplicate).
- Token budget and cost estimation: token counting via `tiktoken` with an honest
  approximate fallback (the method `exact` / `approximate` is surfaced in every report),
  plus configurable, editable model pricing and input-cost estimates.
- Tokenizer network guard: exact token counting runs inside a tightly scoped no-network
  guard. `lcc` blocks runtime network access by default — including the first-use encoding
  download `tiktoken` would otherwise perform — and no CLI command makes an internet request
  by default. If exact tokenizer assets are not available locally, counting falls back to a
  clearly labelled approximate count whose warning explains the specific reason (tiktoken not
  installed, model/encoding unknown, encoding unavailable offline, or another tiktoken
  failure). Exact counting therefore requires the encoding assets to be cached locally. See
  [ADR 0008](docs/adr/0008-tokenizer-network-boundary.md).
- Evidence-aware prompt builder with an extensible template registry.
- `OptimizationReport` (deterministic JSON, `schema_version` 1.0) with before/after
  characters, tokens, compression ratio, savings percentage, cost before/after, cleaning
  steps, dedup metrics, and warnings.
- `lcc optimize` CLI (file or stdin), with `--version` and graceful, non-zero-exit errors.
- `lcc bench` CLI and the deterministic benchmark harness (`lcc.benchmarking`): runs the
  optimization pipeline over committed fixtures in `benchmarks/cases/` and reports mechanical
  metrics (token savings, compression ratio, character reduction, exact/approximate token
  mode, literal marker preservation, warnings) with explicit per-case thresholds and a
  versioned (`schema_version` 1.0), deterministic JSON/Markdown report. See ADR 0007. It does
  **not** measure LLM answer quality.
- Benchmark fixtures in `benchmarks/cases/` (basic redundancy, boilerplate cleanup, evidence
  preservation, approximate-token fallback).
- Architecture Decision Records 0001–0008 capturing the frozen, one-way-door design
  decisions.
- CI workflow (`.github/workflows/ci.yml`) running ruff, mypy, and pytest on Python 3.11,
  3.12, and 3.13.
- Open-source project docs: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, the `docs/` set (architecture, evaluation, roadmap, release, ADRs),
  examples, and agent guidance (`CLAUDE.md`, `AGENTS.md`).

[Unreleased]: https://github.com/vetlucasmartins/lcc/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vetlucasmartins/lcc/releases/tag/v0.1.0
