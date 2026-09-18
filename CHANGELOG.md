# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Relevance compaction v1.1 (2026-09-18 review of `tamaratran/fast-jev-compaction`, adapted to this boundary): three-way decisions — **keep / trim / drop** — where borderline blocks keep a bounded head plus an audit note (`--trim-threshold`, `--trim-head-chars 0` restores strict keep/drop); `--preserve-tail N` pins the newest blocks untouched for live append-only contexts; scoring batches run concurrently (`--max-workers`, up to 8); reduction accounting (`reduction_ratio`, `worth_it`, `--min-reduction`) flags passes that save too little to justify a cache epoch. Report schema is `relevance-compaction-1.1` (additive; `decisions[].chars_after` for trims). A failed scoring batch no longer aborts the remaining ones — missing blocks fall back mechanically, as before.
- `lcc compact` (ADR 0013): opt-in instant relevance compaction. Drops context blocks that are irrelevant to an objective using narrow model judgment (TypeSafe System One / Jev) in batched calls, with a fully local mechanical fallback (zero-lexical-overlap blocks only) when no API key is configured. Fail-safe: provider failures keep content, never drop it.
- Cache-aligned compaction: sticky decisions (`--decisions-cache`) pin `(objective, block)` outcomes so unchanged history keeps byte-identical output; `--protect-prefix` / `--prefix-marker` make early-prefix mutation impossible; reports expose `first_mutation_offset`, `prefix_sha256`, and `output_sha256` for automated cache accounting (`docs/CACHE_ALIGNMENT.md`).
- `lcc intake --enable-relevance` (with `--relevance-threshold`, `--relevance-provider`): runs relevance compaction on raw input before intake compilation; results appear in the intake report JSON and summary.
- Deterministic relevance block segmentation (`lcc.relevance.blocks`) with content-addressed ids (`blk_0001_<12 hex>`), fenced-code-aware spans, and byte-exact reconstruction; shared-ledger audit trail for every scoring call (`lcc_compact` feature tag, matching the LookADev fleet ledger schema).
- `lcc agent` local agent subsystem (`lcc.agents`) with native support for **Gemma 4 e4b** (turn formatting `<start_of_turn>user...`) and **Qwen3.5-4B** (ChatML `<|im_start|>...`), Ollama, llama.cpp / GGUF (e4b 4-bit), vLLM, MLX, and mock backends with health checks and zero remote token usage.
- `lcc route` hybrid local/cloud routing subsystem (`lcc.router`) with conservative verification gates (`RuleBasedVerifier`, `LocalLLMVerifier`) and selective escalation to Fireworks AI.
- `lcc intake` intelligent prompt intake engine (`lcc.intake`) with automated readiness triage (`READY_TO_EXECUTE`, `NEEDS_LIGHT_REFINEMENT`, `NEEDS_INTAKE`, `BLOCKED`), intent/assumptions extraction, and clarifying questions generation.
- `lcc speech` and transcript cleaning (`lcc.cleaning.speech`) with deterministic speech disfluency stripping (English & Portuguese fillers), Whisper audio tag elimination (`[Music]`, `[Applause]`, etc.), hallucinated subtitle/video outro removal, and speaker-turn collapsing.
- Code-block and Markdown-table safe normalization in `lcc.cleaning.normalize` protecting fenced code blocks (``` and ~~~) and Markdown tables against destructive inner-space collapsing and indentation disruption.
- Fixed `REMOTE_DIRECT` router token leak in `lcc.router` so direct cloud model escalation always receives safe deterministic cleaning (normalization, boilerplate removal, and exact paragraph deduplication).
- Universal TypeScript & Node.js client package exports (`LccCompressor`, `LccIntake`, `processIntake`).
- `lcc prepare` deterministic inspect-first workflow. It runs inspection, skips prompt

  generation for `skip`/`manual_review` recommendations, and runs deterministic lexical
  selection plus the existing safe optimization path for `optimize_safe`/`optimize_with_flags`,
  with input-file overwrite protection for output and report paths.
- Machine-readable inspection recommendation scoring signals with deterministic scores,
  thresholds, evidence values, and reason codes for duplication pressure, projected savings,
  token budget pressure, missing pricing, approximate token counting, and manual-review risk.
- Additive `chunk_inventory` data in inspection reports, with deterministic chunk IDs,
  character offsets, line spans, paragraph counts, token counts and methods, structural
  labels, literal heading text, and exact duplicate markers.
- Deterministic question-aware lexical chunk selection for `lcc prepare` optimize decisions,
  using keyword overlap, heading matches, rare-term matches, heading proximity, and exact
  duplicate markers from `chunk_inventory`; prepare reports explain selected chunks and nested
  optimization output.
- Deterministic benchmark coverage for `workflow: prepare` cases, including bundled
  selection-applied and selection-not-applied fixtures with required evidence markers,
  forbidden irrelevant/duplicate markers, and prepare selection report assertions.
- Phase 1.7 roadmap status for the implemented deterministic `prepare` and recommendation
  scoring slices, chunk-inventory slice, lexical-selection slice, and prepare benchmark slice.
- ADR 0010 documenting the deterministic-first preparation and optional model-assistance
  boundary. Optional future model assistance is not implemented; model, embedding, network
  client, runtime-download, and local/remote model-call code cannot enter the deterministic
  core, inspection, or benchmarking boundary.
- ADR 0011 as the accepted Phase 2 opt-in semantic retrieval boundary, plus a
  disabled-by-default `lcc.semantic_retrieval` / `lcc semantic-retrieval` scaffold that reports
  disabled or blocked status only. Retrieval execution, embeddings, RAG, model calls, network
  access, and local-model behavior are still not implemented.
- Visitor-facing project presentation in `docs/project-presentation.md`.

### Changed

- Reworked the README into a clearer first-visit guide with a tighter project summary,
  command guide, architecture map, and explicit scope boundaries.
- Tightened CLI-facing and visitor-facing docs around the deterministic Phase 1.7 prepare
  boundary, diagnostic-only inspection, and mechanical-only benchmark claims.
- The inline drop marker no longer carries scorer values, so repeated `lcc compact` runs emit
  byte-identical output without extra flags; `--marker-scores` restores the previous verbose
  form. Per-block scores remain in the report. Measured over five identical runs, this took the
  output from five distinct hashes to one.
- `--provider auto` reports a mechanical fallback honestly: `degraded` is now true with a
  `degradation_reason` and `semantic_guarantee: none`, instead of claiming success while a
  lexical scorer replaced the semantic judge.
- `lcc compact` exits 3 under `--require-exact-tokens` when token counting degrades to the
  heuristic estimator, and always warns (`approximate_token_count`) that every token figure in
  the report is an estimate.
- Passing `--trim-head-chars 0` now warns (`strict_keep_drop`) that the trim middle gear is
  disabled and borderline blocks are dropped outright instead of keeping a bounded head.
- `lcc compact --help` and the README document `--provider jev` as the recommended explicit
  choice, and describe the trim band as the safety net rather than an optional extra.
- `docs/CACHE_ALIGNMENT.md` corrects the byte-stability claim (scorer values in the marker and
  uncached threshold drift were two distinct causes) and documents the new report fields.

### Added

- Deterministic safety net for locally scored blocks (`--deterministic-protection`, on by
  default). When `lcc compact` falls back to the lexical scorer, three classes of evidence now
  survive it: quoted third-party speech, evidence written in another language than the
  objective, and blocks sharing two or more distinctive terms with a block that is being kept.
  Measured against the adversarial suite in `benchmarks/research/`, this takes the deterministic
  path from 17/20 cases passing to 20/20, and on the main corpora from 3/5 ground-truth facts
  retained to 5/5, at a cost of 10 to 23 points of reduction. The Jev path is unaffected.
- `invalidated_tokens` and `break_even_reuses` in the relevance compaction report, plus a
  `cache_epoch_risk` warning when a pass mutates a warm prefix earlier than the reuse count can
  pay for. Measured break-even sits between 11.8 and 20.3 reuses across three corpus sizes.
- `degradation_reason` and `semantic_guarantee` (`judged` / `partial` / `none`) in the relevance
  compaction report so callers can decide whether a pass is trustworthy without parsing prose.
- `--marker-scores` and `--require-exact-tokens` CLI flags for `lcc compact`.
- `benchmarks/research/`: a measured study of compaction effectiveness, evidence retention and
  prompt-cache safety, with reproducible corpora, a 39-run transform matrix, a cache-safety
  suite, and a real 9-agent A/B against a no-LCC baseline.

### Fixed

- Identical blocks are now decided once per run. The decisions cache is content-addressed, so a
  run that scored two copies of the same block independently could disagree with the single
  cached score a warm run reuses, changing the emitted bytes between runs.

## [0.2.0] - 2026-06-22

### Added

- `lcc inspect` diagnostic command — analyzes a text input (from a file or stdin) and reports
  its token, structure, duplication, cleanup, and cost profile, plus a clearly-labelled
  projection of what `lcc optimize`'s safe cleaning would remove. It is diagnostic, not
  transformative: it builds **no** prompt, makes no network or model call, and never modifies
  the input. The JSON report goes to `--report` (or stdout); a human-readable summary and
  warnings go to stderr.
- Deterministic inspection reports (`lcc.inspection`, `schema_version` 1.0): identical input
  produces a byte-identical report — no timestamps, random values, absolute paths, or
  machine-specific values. Token counts preserve the exact-vs-approximate honesty of ADR 0005
  and ADR 0008.
- ADR 0009 — `lcc inspect` is a diagnostic boundary (no prompt, no transform).
- PyPI Trusted Publishing workflow for tag-triggered releases via GitHub Actions OIDC,
  without long-lived PyPI tokens.
- Explicit source distribution manifest covering docs, examples, benchmark fixtures, config
  examples, and tests.
- PEP 561 typing marker (`py.typed`) in the wheel.

### Changed

- Documented published-package installation with `pipx install local-context-compiler` and
  `python -m pip install local-context-compiler`.
- Updated the release checklist for building distributions, checking them with `twine`,
  installing the wheel in a clean virtual environment, and publishing through PyPI Trusted
  Publishing.

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

[Unreleased]: https://github.com/vetlucasmartins/lcc/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/vetlucasmartins/lcc/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vetlucasmartins/lcc/releases/tag/v0.1.0
