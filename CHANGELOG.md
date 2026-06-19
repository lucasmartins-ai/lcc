# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Deterministic benchmark harness (`lcc.benchmarking`) and the `lcc bench` CLI command: runs
  the optimization pipeline over committed fixtures in `benchmarks/cases/` and reports
  mechanical metrics (token savings, compression ratio, character reduction,
  exact/approximate token mode, literal marker preservation, warnings) with explicit
  per-case thresholds and a versioned (`schema_version` 1.0), deterministic JSON/Markdown
  report. See ADR 0007. It does **not** measure LLM answer quality.

### Changed

- **No indirect network via `tiktoken`.** Exact token counting now runs inside a tightly
  scoped no-network guard: if `tiktoken` would download encoding assets (its first-use fetch),
  the attempt is blocked and counting falls back to a clearly labelled approximate count whose
  warning explains why. `lcc` blocks runtime network access by default — including indirectly
  through `tiktoken` — and no CLI command makes an internet request by default. Exact counting
  requires tokenizer encoding assets to be available locally. See
  [ADR 0008](docs/adr/0008-tokenizer-network-boundary.md). Approximate-count warnings now
  include the specific reason (tiktoken not installed, model/encoding unknown, encoding
  unavailable offline, or another tiktoken failure).

## [0.1.0] - 2026-06-19

### Added

- Initial deterministic MVP.
- Deterministic cleaning: `normalize_text`, `remove_common_boilerplate`,
  `deduplicate_paragraphs` (exact + conservative near-duplicate).
- Token counting via `tiktoken` with an honest approximate fallback; the method
  (`exact` / `approximate`) is surfaced in every report.
- Configurable, editable model pricing and input-cost estimation.
- Evidence-aware prompt builder with an extensible template registry.
- `OptimizationReport` (JSON, `schema_version` 1.0) with before/after characters,
  tokens, compression ratio, savings percentage, cost, cleaning steps, dedup metrics,
  and warnings.
- `lcc optimize` CLI (file or stdin), with `--version` and graceful, non-zero-exit errors.
- Tests, examples, documentation, ADRs, and agent guidance (`CLAUDE.md`, `AGENTS.md`).

[Unreleased]: https://github.com/your-org/local-context-compiler/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/local-context-compiler/releases/tag/v0.1.0
