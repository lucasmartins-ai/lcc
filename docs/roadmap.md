# Roadmap

This roadmap is aspirational. **Only Phase 1, the deterministic benchmark harness
(Phase 1.5), the deterministic inspection command (Phase 1.6), deterministic Phase 1.7
`prepare` / recommendation / chunk-inventory / lexical-selection / benchmark-coverage /
boundary-ADR slices, and the Phase 2 disabled semantic retrieval boundary scaffold are
implemented today.** No semantic retrieval execution, embedding generation, vector search, or
model-assisted retrieval phase is present in the code, and the documentation never describes a
later phase as if it were.

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

## Phase 1.6 — Deterministic inspection command (implemented)

- `lcc inspect INPUT` analyzes a text input (file or stdin) and emits a deterministic JSON
  diagnostic report (`schema_version` 1.0) covering its token, structure, duplication,
  cleanup, and cost profile, plus a clearly-labelled **projection** of what the safe cleaning
  in `lcc optimize` would remove (ADR 0009).
- Inspection reports include deterministic recommendation fields (`action`, `reason_codes`,
  `summary`, and `suggested_command` when applicable), compact human output via
  `--summary compact`, projected cost savings when pricing is available, and per-stage safe
  cleanup contributions for normalization, boilerplate removal, exact deduplication, and
  near-deduplication.
- It is **diagnostic, not transformative**: it generates **no** prompt, makes no network or
  model call, uses no embeddings/RAG, and never modifies the input. Token counts preserve the
  exact-vs-approximate honesty of ADR 0005 and ADR 0008, and projected savings are labelled as
  a projection, never as a completed optimization.

## Phase 1.7 — Low-friction prepare workflow (deterministic slices implemented)

The implemented deterministic slices keep `lcc` useful without requiring a local LLM, while
leaving room for an optional model-assisted layer later. The user-facing goal is one
low-friction command that answers: "Should I optimize this context, and, if useful, what
deterministic prompt package should I send next?"

Implemented so far:

- `lcc prepare INPUT --question "..."` runs inspection first for file or stdin input.
- When inspection recommends `skip` or `manual_review`, `prepare` emits or writes the
  inspection report and generates no prompt.
- When inspection recommends `optimize_safe` or `optimize_with_flags`, `prepare` can apply
  deterministic question-aware lexical selection, then runs the existing safe optimization
  pipeline on literal source chunks and can write the optimized prompt plus optimization
  report.
- `--output` and `--report` are rejected when they point to the input file, so preparation
  never overwrites its source.
- Inspection recommendations include stable scoring signals with thresholds, evidence values,
  and reason codes for duplication pressure, projected token savings, token budget pressure,
  missing pricing, approximate token counting, and manual-review risk.
- Inspection reports include a deterministic `chunk_inventory` with stable IDs, character
  offsets, line spans, paragraph counts, per-chunk token counts and methods, simple
  structural labels, literal heading text when present, and exact duplicate markers.
- On optimize recommendations, `prepare` applies deterministic question-aware lexical
  selection using keyword overlap, heading matches, rare-term matches, proximity to matched
  headings, and exact-duplicate markers from `chunk_inventory`; the prepare report explains
  why each selected chunk was kept.
- The deterministic benchmark harness supports `workflow: prepare` fixture cases, reports the
  inspection action and lexical-selection state, and includes bundled coverage for
  selection-applied and selection-not-applied prepare paths.
- The command remains deterministic: no source summarization, rewriting, paraphrasing,
  semantic ranking, embeddings, network access, local model call, or remote LLM call.
- ADR 0010 records the deterministic-first preparation boundary: optional future model
  assistance is not implemented, must be opt-in and outside the deterministic core and
  inspection boundary, and cannot enter `cleaning`, `token_budget`, `prompt_builder`,
  `reporting`, `pipeline`, `inspection`, or `benchmarking`.

### Execution roadmap

1. **Record the boundary.** Implemented in ADR 0010. Optional model assistance is not
   implemented and must live outside the deterministic core and outside the inspection
   boundary. No LLM, embedding model, network client, runtime download, local-model call, or
   remote model call may enter `cleaning`, `token_budget`, `prompt_builder`, `reporting`,
   `pipeline`, `inspection`, or `benchmarking`.
2. **Add `lcc prepare` as orchestration only.** Implemented. The command reads the same core
   inputs as `inspect` and `optimize`, runs inspection first, and then either skips prompt
   generation or runs safe optimization based on deterministic recommendation fields. It
   introduces no new dependency and makes no model or network call.
3. **Improve deterministic recommendations.** Implemented. Recommendation reports now include
   explicit scores for duplication, projected savings, budget pressure, missing pricing,
   approximate token counting, and manual-review risk. The output stays auditable through
   reason codes, thresholds, evidence values, and suggested commands when optimization is
   useful.
4. **Add stable section/chunk inventory.** Implemented. Inspection reports now include a
   deterministic chunk inventory that assigns stable IDs, character spans, line spans,
   paragraph counts, token counts, simple structural labels, literal heading text when
   present, and exact duplicate markers. This is diagnostic data, not semantic summarization.
5. **Add question-aware lexical selection.** Implemented. Without adding embeddings or a
   local LLM, `prepare` now selects chunks with transparent lexical signals such as keyword
   overlap, heading matches, rare-term matches, and proximity to matched headings. The selector
   preserves first-copy evidence, avoids exact duplicate copies when applied, and reports why
   each selected chunk was kept.
6. **Extend benchmarks before increasing intelligence.** Implemented. Fixture cases now cover
   `prepare` and lexical selection, including required evidence markers, forbidden irrelevant
   and duplicate markers, selected-chunk thresholds, skipped-duplicate expectations, and
   selection-applied / selection-not-applied paths. These still measure mechanical behavior
   only.
7. **Add semantic evaluation as an opt-in harness.** Only after deterministic selection exists,
   add an evaluation workflow that can compare raw context, optimized context, and selected
   context with a downstream model controlled by the user. This remains outside the default
   deterministic workflow.
8. **Consider optional local model advice last.** A small local model may be useful as an
   optional advisor for ambiguous intent, template choice, or claim extraction. It should read
   deterministic reports and return structured JSON advice; it should not rewrite or delete
   source evidence by default.

### First implementation slice

The first landed prepare slice was `lcc prepare` without chunk selection or model assistance.
It is historical context for the execution roadmap; the current implemented prepare workflow
also includes the deterministic lexical-selection slice described below.

Acceptance criteria:

- `lcc prepare INPUT --question "..."` runs inspection first.
- When inspection recommends `skip` or `manual_review`, the command writes or emits an
  inspection report and explains that no prompt was generated.
- When inspection recommends `optimize_safe` or `optimize_with_flags`, the command runs the
  existing safe optimization path and can write both prompt and report.
- The command remains deterministic: identical input and options produce identical machine
  output.
- The command makes no network, LLM, embedding, or local-model call.
- Tests cover file input, stdin input, skip behavior, optimize behavior, report path handling,
  and protection against writing output or report artifacts over the input file.

### Recommendation scoring slice

The next implemented slice keeps recommendations deterministic and explainable without adding
semantic selection. It adds machine-readable scoring signals under the inspection report's
`recommendation` field. These signals are diagnostic: `lcc prepare` still uses only
`recommendation.action` to decide whether to skip or run the existing safe optimization path.

Acceptance criteria:

- Scores, thresholds, evidence values, and per-signal reason codes are present in inspection
  reports.
- Signals cover duplication pressure, projected token savings, token budget pressure, missing
  pricing, approximate token counting, and manual-review risk.
- Existing recommendation actions remain backward-compatible.
- No semantic selection, embeddings, network access, local model call, or remote LLM call is
  added.

### Stable chunk inventory slice

The current implemented slice adds deterministic, machine-readable `chunk_inventory` data to
inspection reports. It inventories non-empty paragraph-like blocks separated by blank lines,
labels Markdown heading blocks as `heading`, labels other non-empty blocks as
`paragraph_block`, records 0-based character offsets and 1-based line spans, and marks exact
duplicate chunks by pointing later copies at the first matching chunk ID.

Acceptance criteria:

- Inspection reports include stable chunk IDs, indexes, character offsets, line spans,
  paragraph counts, character counts, token counts, and token count methods.
- Literal Markdown heading text is reported for heading chunks; paragraph body text is not
  copied into the inventory.
- Duplicate markers are exact and mechanical; no near-duplicate or semantic ranking is added.
- Existing report consumers remain compatible because the field is additive and
  `schema_version` remains `1.0`.
- No semantic selection, embeddings, network access, local model call, or remote LLM call is
  added.

### Question-aware lexical selection slice

The current implemented slice adds a separate, deterministic selection path to `lcc prepare`
after inspection has already recommended `optimize_safe` or `optimize_with_flags`. Selection
uses the chunk inventory's stable offsets, labels, literal heading text, token counts, and
exact duplicate markers to evaluate literal source chunks against the question. It does not
change how `prepare` decides whether to skip or optimize: that decision still comes only from
`recommendation.action`.

Acceptance criteria:

- Selection uses lexical/mechanical signals only: keyword overlap, heading matches,
  rare-term matches, proximity to matched headings, and exact duplicate markers.
- Selected text is assembled from literal source chunks; no source content is summarized,
  rewritten, or paraphrased.
- First-copy evidence is preserved and later exact duplicate chunks are skipped when selection
  is applied.
- Prepare reports include selected chunk IDs, reason codes, signal evidence, skipped duplicate
  chunk IDs, and the nested optimization report.
- If the question has no usable terms or no lexical matches, selection is not applied and the
  existing safe optimization path receives the original input.
- No semantic ranking, embeddings, network access, local model call, or remote LLM call is
  added.

### Prepare benchmark coverage slice

The current implemented slice extends the deterministic benchmark harness so fixtures can
exercise either the original `optimize` workflow or the `prepare` workflow. Prepare fixtures
mirror the command's deterministic orchestration: run inspection, branch only on
`recommendation.action`, apply lexical selection only for optimize recommendations, and then
run the safe optimization path.

Acceptance criteria:

- Benchmark case metadata supports `workflow: optimize` (default) and `workflow: prepare`.
- Prepare benchmark reports include the inspection action, whether lexical selection applied,
  selected chunk IDs, selected reason codes, selected token count, and skipped duplicate chunk
  IDs.
- Prepare expectations can assert the action, selection-applied state, selected chunk count
  bounds, and minimum skipped duplicate chunk count.
- Bundled fixtures cover both selection-applied and selection-not-applied paths with required
  evidence markers and forbidden irrelevant / duplicate markers.
- The harness remains deterministic and measures mechanical behavior only; it adds no
  semantic scoring, embeddings, network access, local model call, or remote LLM call.

## Phase 2 — Local semantic retrieval (planned)

Phase 2 remains planned for retrieval itself. The first accepted boundary artifact is
[ADR 0011](adr/0011-phase-2-opt-in-semantic-retrieval-boundary.md), which defines the
disabled-by-default opt-in scaffold for optional local semantic retrieval. The scaffold lives
outside the deterministic core, inspection boundary, and deterministic benchmark harness.
The retrieval execution contract is recorded in
[ADR 0012](adr/0012-semantic-retrieval-execution-boundary.md): the first future adapter must
be a separate opt-in local-index adapter that returns provenance-rich literal source spans.
No retrieval execution adapter is implemented today.

Implemented boundary scaffold:

- `lcc.semantic_retrieval` exposes a standard-library-only boundary status contract.
- `lcc semantic-retrieval` reports the scaffold state.
- `semantic_retrieval.enabled` defaults to `false`; enabled requests require explicit local
  index and embedding asset paths.
- Enabled requests validate local `semantic-index-1.0` manifest metadata for source
  fingerprint, embedding model metadata, positive vector dimensions, deterministic
  `index_settings`, chunk provenance consistency, and local vector file references. Vector
  references must be relative, stay inside the manifest directory, and exist locally;
  validation does not read vector contents.
- Enabled requests validate declared local embedding asset provenance under
  `embedding_assets`: asset references must be relative, stay inside the embedding assets
  directory, exist locally, and match their declared `sha256:<hex>` fingerprints.
- Even with valid local artifacts present, retrieval execution returns a blocked status and
  exits non-zero because no retrieval adapter is implemented.

Still planned:

- Optional local chunking + embeddings + similarity selection (for example, a local vector
  index).
- Selecting the most relevant chunks for the question and feeding literal source spans into
  the existing pipeline. This remains fully optional and isolated; the deterministic core is
  unchanged.

Next real implementation step: implement ADR 0012's separate `local_index_v1` execution
adapter behind explicit opt-in, starting with fail-closed tests. Do not add embedding
generation, index building, vector search in deterministic commands, or prompt integration in
that first implementation.

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

These are explicitly **not** implemented and are listed here so the docs never imply they
exist:

- Transcript ingestion (importing and normalizing conversation/meeting transcripts).
- An API server / hosted service.
- Voice / audio adapters and ASR (speech-to-text).

Each, if pursued, lands behind a new, clearly separated boundary; none touches the
deterministic core.

## Guiding constraints for every phase

- Keep the deterministic core dependency-free and free of network/LLM code.
- Add new capabilities behind new, clearly separated boundaries (ADRs 0002, 0006).
- Keep new dependencies optional and justified.
