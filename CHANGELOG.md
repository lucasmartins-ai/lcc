# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-09-21

**Release focus: Jev first, and enough of it shipped to prove it.** The Jev provider is now the
headline path in the documentation (`docs/JEV.md`), the compiler learned a message-level mode
(`lcc compact --mode tool-calls`) that drops spent tool calls and results from an agent
transcript without ever summarizing, and a Claude Code plugin replaces that editor's built-in
compaction summary with the same pass. A head-to-head study against `fast-jev-compaction` 0.4.0
on the same transcripts with live Jev is published in `benchmarks/research/TRANSCRIPT_AB.md`:
this mode removed 13.3 / 39.2 / 55.7% of the transcript at fact recall 1.00 / 1.00 / 1.00, where
that library removed 70.5 / 78.9 / 83.4% at recall 0.00. Two defects the study found in the new
mode are fixed below.

### Added

- Tool-call compaction study: `benchmarks/research/TRANSCRIPT_AB.md` measures `lcc compact --mode tool-calls` against `fast-jev-compaction` 0.4.0 on the same three deterministic transcripts with matching options and live Jev. Our mode removed 13.3 / 39.2 / 55.7% of the transcript at fact recall 1.00 / 1.00 / 1.00; the npm arm removed 70.5 / 78.9 / 83.4% at recall 0.00 (every evidence pair dropped, reproducibly). New harness: `make_transcripts.py` (ground-truth corpus with a self-check), `run_transcript_ab.py` (both arms measured by the same ruler, per-pair outcomes derived from the emitted messages, arm selection in the artifact filename), `fast_jev_arm.mjs`; artifacts under `benchmarks/research/results/`. Canonical row in `benchmarks/research/RESEARCH_STATUS.md`.

### Fixed

- Tool-call compaction, state budget honesty: the mode scored the conversation with the stdlib heuristic, which undercounts JSON-heavy transcripts by roughly a third. On a then-497-message snapshot of a real session it judged a 22 936-token state inside its 25 000 budget, sent 38 batches, and had every one refused by the API (`400 max_tokens_exceeded`, 123 741 characters ≈ 31 000 real tokens) before degrading to keep-everything. `_budget_tokens` now counts with the real tokenizer when the environment has one and otherwise inflates the heuristic by the measured factor, so a session that cannot fit fails closed in ~50 ms with a typed error and zero requests spent. Regression tests: `test_the_budget_is_never_optimistic`, `test_fitting_uses_the_budget_function`.
- Tool-call compaction: a `drop` decision reported `chars_after` equal to `chars_before`, so the report's `tool_reduction_ratio` read 0.0 while the transcript had shrunk by more than half. A result shorter than `--trim-head-chars` was also "trimmed" into a *longer* transcript, because the audit note outweighed the characters it removed; such a pair is now kept whole with reason `short_result_kept_whole`. Both were found by the new A/B study and both have regression tests.
- Tool-call compaction, real sessions: `benchmarks/research/REAL_SESSIONS.md` adds the measurement the release was missing. A real Claude Code session in this repository (192 messages, 75 tool calls), in the exact shape the hook receives, goes from 55 411 to 18 761 tokens (**−66.1%**) with all 42 user/assistant texts preserved byte for byte; this release's own 337-message Hermes session (187 tool calls) goes from 199 717 to 36 645 tokens (**−81.7%**) with all 58 texts preserved. New harness: `measure_session.py` (Claude Code JSONL or the Hermes store → the session shape → the shipping code path).

- Claude Code plugin (`plugins/claude-code`, `.claude-plugin/marketplace.json`): replaces the built-in compaction summary with verbatim tool-call compaction. The `session.compact` hook is a thin ESM adapter (no build step, no dependencies) that hands the transcript to the plugin's own `lcc mcp` server and maps the result back; it stands down to Claude Code's own summary on any failure, on a below-`minReductionRatio` pass, or when a message carries content it cannot rebuild. Install and limits: `docs/CLAUDE_CODE.md`; operator guide: `plugins/claude-code/hooks/README.md`. Verified by `claude plugin validate` plus `test/hook-map.test.mjs` (10 cases, run by `npm test`); a live head-to-head against the built-in summary is still pending.
- Tool-call compaction: `lcc compact --mode tool-calls` (and the MCP tool `compact_transcript`) compacts a session transcript instead of a document. Each `tool_use` is paired with its `tool_result` by id; the first and newest `--preserve-recent` messages are pinned; every other pair gets two typed Jev questions (does the call still matter, does its result still need to be there verbatim) and is kept, trimmed to `--trim-head-chars` plus a note, or dropped whole. User and assistant text is never scored, trimmed or rewritten, results stay in the message they arrived in, and a history that cannot be shown inside `--max-state-tokens` fails closed instead of being judged blind. `mechanical`/`laya` are refused with exit 2 rather than pretending to judge semantics. The report is `transcript-compaction-1.0` and reads through `lcc explain` unchanged. New: `src/lcc/relevance/transcript.py`, `docs/TOOL_CALLS.md`.
- Jev path documentation: new `docs/JEV.md` (typed-decision contract, key resolution order, honest fallback table, measured behaviour and its limits), a Jev-first section at the top of `README.md` with a five-line `--provider jev` example and a TypeSafe badge, a Jev path in `docs/QUICKSTART.md`, and `tests/test_docs.py` assertions that keep the document linked from both entry points and pinned to the tested phrases.

### Changed

- README positioning: the compaction claim now leads with "Jev-powered relevance compaction that never summarizes", and the provider table's note points to `docs/JEV.md`. No behaviour change; the offline default path (`mechanical`/`laya`, no key, no network) is unchanged.

## [0.4.0] - 2026-09-21

### Added

- Laya live validation (2026-09-21): the real backend runs end-to-end (verified offline, in-budget, `judged`, no fallback) and the pre-validation "Laya = Jev, −22.6% on XL" claims are corrected — measured with real weights the default checkpoint keeps essentially every block (0.0% reduction at small/medium/large, −0.5% at XL; Jev −52% / mechanical −70% at XL, all at 100% category recall). `run_comparative_stress_test.py` and `run_laya_comparison.py` run real backends by default (`--mock` opts into the labelled harness) and every result row now carries `harness: real|mock`. New `run_laya_context_cases.py` (budget cases A/B/C, offline) and gated live test `tests/test_laya_integration.py` (`LCC_LAYA_INTEGRATION=1`). Pre-validation mock archives preserved and labelled. Full rows: `benchmarks/research/RESEARCH_STATUS.md`.
- Laya opt-in local semantic backend for `lcc compact` (ADR 0016, `local-context-compiler[laya]` extra): `LayaClient` judges typed `noul`/`choice`/`score` questions on-device with zero network and zero remote tokens. Strict context budgeting (`laya` 512 / `laya-multilingual` / `laya-typed-decisions` 1024, `HEAD_RESERVATION_TOKENS = 192` → 319/831 state tokens, `--laya-context-limit` override); oversized blocks are kept whole with `laya_context_limit_exceeded`, never sliced. Temperature calibration (`calibrate_noul`, `--laya-temperature`, default 1.0) is pure stdlib and part of the decision-cache identity. New CLI flags `--laya-model`, `--laya-device`, `--laya-context-limit`, `--laya-temperature`; Python API `LayaClient` + `provider="laya"`. Missing extra or failed batch falls back honestly to mechanical (`laya+mechanical_fallback`, `degraded: true`, typed reason) — never a fake `judged`. Operator guide: `docs/LAYA.md`.
- Laya maturity: report schema `relevance-compaction-1.2` (additive; new `context_budget_used`, `laya_temperature` alongside `laya_model_requested`/`resolved`, `laya_context_limit`, `latency_ms`), `lcc compact --help` provider decision guidance (mechanical vs laya vs jev vs auto), and fallback/observability tests including the missing-dependency path.
- Discoverability: `docs/QUICKSTART.md` (5-minute offline tour), runnable `examples/compact_providers.py` (mechanical vs laya vs honest jev-skip on one dossier) and `examples/long_session_cache.py` (decisions-cache + prefix-marker + append-only session), both covered by `tests/test_examples.py`.
- Deterministic boundary hardening: `tests/test_deterministic_boundary.py` fails any network/LLM/embedding capability import in `cleaning`, `token_budget`, `inspection`, `pipeline`, `lexical_selection`, `benchmarking` (sole exceptions: the fail-closed download guard and `*_VERSION` identity constants), fails any opt-in layer import into core, and proves core outputs are byte-identical with the network disabled. ADR 0010 clarified (decision unchanged): Laya, sufficiency, verifier, agents, and router are opt-in outside the core.
- MCP server MVP (`lcc mcp`, `src/lcc/mcp_server.py`, `docs/MCP.md`): stdio JSON-RPC tools `compact` (defaults to offline `mechanical`), `inspect`, `prepare`, `explain`, `intake`. Stdlib only — zero new dependencies; covered by `tests/test_mcp_server.py` including a real framed-subprocess session.
- Minimum-sufficient-context compilation (ADR 0014): `lcc compact` now answers two questions — "is this block relevant?" and "after these drops, can the objective still be solved from what remains?". New modules `lcc.relevance.safety` (independent relevance/necessity/dependency-risk/semantic-risk/redundancy axes), `lcc.relevance.graph` (typed SUPPORTS/QUALIFIES/CONTRADICTS/SUPERSEDES/DEPENDS_ON/DUPLICATES/DERIVED_FROM edges), `lcc.relevance.sufficiency` (verify-then-restore with `--sufficiency/--no-sufficiency`, `--max-restorations`), `lcc.relevance.trim` (type-aware TRIM: valid-syntax JSON/YAML/XML, row-aware tables, line-bound code, head+tail logs, TRIM→KEEP for high-stakes content), and `lcc.benchmarking.metadata` (reproducible benchmark identity). Decision cache keys bind the full policy identity (v1.1); reports add tokenizer identity, `jev_model_resolved`, sufficiency/relationship/marker accounting, per-decision confidence/relationships/policy/content-type, and `compilation_ms`. New CLI flags `--sufficiency/--no-sufficiency`, `--max-restorations`, `--confidence-threshold`. Adversarial suite grows 20→26 cases (scope quantifiers, coreference, paraphrase duplicates, set-level VAT chain, HTML/log injection); new `benchmarks/research/run_answer_eval.py` gates answer-level regressions (26/26 pass, 0 regressions mechanical). Node engine gains `tokenizerIdentity()`/`estimateTokensWithMeta()` with a documented parity boundary.
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
- Visitor-facing project presentation (added during this cycle, since removed as hackathon-specific; pitch content folded into README).

### Changed

- **Behavior change:** `--provider laya` without the `[laya]` extra (or with an unloadable model) now falls back honestly to mechanical scoring (`provider_used: laya+mechanical_fallback`, `degraded: true`, `degradation_reason: laya_unavailable_mechanical_fallback`) instead of keeping every block silently. Rationale: a keep-all pass disguised the missing dependency and hid that no semantic judgment ran; the fallback is labeled, warned, and `semantic_guarantee: none`.
- `semantic_guarantee` is now exact about mixed runs: `partial` only when at least one block was actually judged before the failure; a total provider failure (every decision lexical) reports `none`. Same rule for Jev and Laya fallbacks.
- Report schema `relevance-compaction-1.1` → `relevance-compaction-1.2` (additive only: `context_budget_used`, `laya_temperature`; all 1.1 consumers keep working, e.g. `lcc explain` reads both).
- Reworked the README into a clearer first-visit guide with a tighter project summary, the offline-first path, direct links to the five-minute QUICKSTART and MCP Server guide, a command guide, an architecture map, and explicit scope boundaries.
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

- `lcc compact --append-to <session>`: compacts the payload and appends it in one step, never
  rewriting the bytes already in the file. This makes the placement the measurements favour — a
  per-payload pass instead of a whole-session rewrite — a first-class operation rather than shell
  plumbing, and it is what keeps a session's prefix byte-stable so its prompt cache survives.
- The Jev scorer is documented as optional everywhere it is mentioned. `--provider mechanical`
  needs no key and no network and the measurements show it keeps every item of every information
  category on every corpus size tested, so the README now answers "does it work without a model
  API key?" directly, and `lcc compact --help` says which path needs what.
- `benchmarks/research/run_cache_patterns.py`: measures where compaction is placed, which turns
  out to matter more than how much it removes. Per-payload compaction (the tool result, before it
  is appended) saved 42.4% of context cost against 7.9% for a single whole-session pass, and spent
  fewer scorer tokens, because a whole-session drop pays to rewrite everything it invalidates.
  `docs/CACHE_ALIGNMENT.md` now carries the placement guidance and the recommended order.
- An audit guide in `benchmarks/research/README.md`: what each script proves, how to re-run every
  number, and the two habits that keep the benchmark honest (report recall per information
  category, and check that the objective actually requires the ground truth before blaming a
  component).
- Supersession rule in the deterministic safety net: a block that revises or corrects a value
  carried by a kept block is kept too, even when it shares only one distinctive term with it. It
  closes the last category the local scorer was losing (`temporal`, at 0.00 on every scale) for
  between one and two points of reduction. The rule is a separate pass rather than a transitive
  closure, because making the closure transitive cost 27 points of reduction on the medium corpus.
- `lcc explain`: reads a report written by `lcc compact -r` and prints why every block was kept,
  trimmed or dropped, in plain language, with the original text behind each decision when
  `--source` is given. `--only` filters to one decision kind and `--limit` caps the trail. It
  never re-runs compaction and never touches the network, so a pass stays auditable after the
  fact.
- Recall by information category in the research benchmark. The corpora now carry categorized
  ground truth (critical facts, a constraint, a negative constraint, an exception, a dated
  revision and a contradictory measurement) and `run_matrix.py` reports recall per category
  instead of one flat count.
- `benchmarks/research/stress_edges.py`: a stress and edge-case suite. The `xl` corpus is roughly
  four times `large` (1 492 blocks, 44 128 tokens) and confirms that category recall, reduction
  and cache byte-stability hold at that scale; eight edge cases cover empty input, whitespace, a
  single oversized block, CRLF, unicode, 400 sub-floor blocks and a 40 kB line.
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

[Unreleased]: https://github.com/lucasmartins-ai/lcc/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/lucasmartins-ai/lcc/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lucasmartins-ai/lcc/compare/v0.2.0...v0.4.0
[0.2.0]: https://github.com/lucasmartins-ai/lcc/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lucasmartins-ai/lcc/releases/tag/v0.1.0
