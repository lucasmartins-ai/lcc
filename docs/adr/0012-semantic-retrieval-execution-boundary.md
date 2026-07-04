# ADR 0012 - Semantic retrieval execution boundary

**Status:** accepted

**Context.** ADR 0011 closed the Phase 2 scaffold: `lcc semantic-retrieval` can report a
disabled or blocked boundary state and can validate local manifest metadata, but retrieval
execution is still not implemented. The next useful decision is the smallest execution
contract that can later turn the scaffold into real retrieval without weakening the
deterministic core, inspection, preparation, or benchmark boundaries.

**Decision.** The first future retrieval execution adapter is a separate, explicit,
local-index adapter named `local_index_v1`. It may execute only when the user opts in to
semantic retrieval and explicitly requests execution. It selects evidence from a prebuilt
local semantic index and returns provenance-rich literal source spans. It does not build an
index, refresh an index, generate corpus embeddings, summarize, rewrite, paraphrase, call a
local or remote LLM, access the network, download assets, or build a prompt.

This ADR defines the future implementation contract only. The current repository still has no
retrieval execution adapter.

## Exact Scope

The first adapter may do only this:

- accept source text, a question, `top_k`, a `semantic-index-1.0` manifest path, and an
  embedding assets directory from an explicit semantic retrieval execution path;
- validate the manifest using the ADR 0011 boundary rules before execution;
- compute the source fingerprint from the supplied source text and fail closed if it differs
  from the manifest source fingerprint;
- verify selected chunk text hashes against literal source slices before returning evidence;
- load only the declared local embedding assets whose fingerprints match the manifest;
- compute one local query embedding for the supplied question using those local assets;
- read local vector contents only during explicit execution, after manifest, source, and asset
  validation have passed;
- score indexed chunks against the query embedding with the manifest-declared dimensions and
  deterministic similarity settings;
- return at most `top_k` selected evidence records with ranks, scores, chunk IDs, source
  offsets, line spans, text hashes, and literal source text copied from the original source
  spans.

The adapter must not mutate source files, manifests, vector files, embedding assets, config
files, or existing reports.

## Module Boundary

The retrieval execution code must remain inside `lcc.semantic_retrieval` and outside the
deterministic core.

Allowed import direction:

- `lcc.cli` may import `lcc.semantic_retrieval` for the separate semantic retrieval command.
- `lcc.semantic_retrieval.execution` may import `lcc.semantic_retrieval.boundary` and the
  concrete adapter module.
- `lcc.semantic_retrieval.adapters.local_index` may import boundary data structures and
  optional semantic dependencies lazily, after explicit execution is requested.
- `cleaning`, `token_budget`, `prompt_builder`, `reporting`, `pipeline`, `inspection`,
  `lexical_selection`, and `benchmarking` must not import `lcc.semantic_retrieval`.
- The adapter must not import `lcc.pipeline`, `lcc.prompt_builder`, `lcc.benchmarking`, or
  `lcc.inspection` to perform retrieval. It receives source text and manifest paths as
  arguments.

The existing status and manifest-validation path remains standard-library-only. Optional
dependency imports are allowed only in the execution adapter.

## Dependency Strategy

Default installs remain dependency-light. No semantic dependency is required for `optimize`,
`inspect`, `prepare`, `bench`, or disabled semantic status reporting.

If the adapter needs a non-stdlib package, it must be exposed through a separate optional
extra, for example `local-context-compiler[semantic]`. The dependency must be imported lazily
only after explicit execution is requested. Missing or incompatible optional dependencies fail
closed with a dependency-specific reason; they must not silently produce empty results or fall
back to a different backend.

No dependency may download model, tokenizer, vector, or index assets at runtime. A dependency
that tries to fetch assets during import or execution is incompatible with this boundary
unless the adapter blocks the fetch and fails closed.

## Local Assets and Index

The first adapter consumes a prebuilt local index. Index creation remains out of scope.

Execution requires:

- a `semantic-index-1.0` manifest that passes ADR 0011 validation;
- a source text whose `sha256:<hex>` fingerprint exactly matches the manifest;
- chunk IDs and source spans that correspond to the indexed chunks;
- relative vector references that stay inside the manifest directory;
- vector contents whose dimensions match both the chunk vector dimensions and the embedding
  model dimensions;
- relative embedding asset references that stay inside `embedding_assets`;
- local embedding asset files whose hashes match the manifest;
- deterministic index settings that declare the vector content format and similarity metric
  used by the adapter.

Status reporting and manifest validation must continue to avoid reading vector contents.
Only the explicit execution path may open vector files.

## Fail-Closed Behavior

The adapter must fail before returning selected evidence when any required condition is not
met. Required fail-closed cases include:

- semantic retrieval disabled;
- execution requested without an explicit question;
- missing manifest, vector files, source text, or embedding assets;
- invalid or unsupported manifest schema;
- unsupported adapter name;
- missing optional dependency;
- dependency import, initialization, or local model-load failure;
- any attempted runtime download;
- source fingerprint mismatch;
- stale chunk text hash or source span mismatch;
- stale or unsupported index settings;
- incompatible vector, chunk, query, or embedding dimensions;
- unreadable, malformed, non-finite, or empty vector contents;
- query embedding failure;
- `top_k` less than 1;
- no eligible chunks after validation.

Failures must report a deterministic `reason_code` and message. They must not return partial
rankings as success.

## Provenance and Literal Output

Selected evidence must remain literal source evidence. Every selected item must carry:

- rank and deterministic tie-break behavior;
- score and score kind;
- manifest schema version and adapter name;
- source fingerprint;
- chunk ID;
- source offsets;
- line span;
- chunk text hash;
- literal source text copied from the corresponding source span.

Prompt integration, if added later, must assemble selected context from these literal source
spans. Generated summaries, paraphrases, model-written evidence, or rewritten chunks are not
valid retrieval output for this adapter.

## Report Schema Impact

Existing report schemas are unchanged:

- optimization reports remain `schema_version: "1.0"`;
- inspection reports remain `schema_version: "1.0"`;
- benchmark suite reports remain `schema_version: "1.0"`;
- prepare reports remain `prepare-1.0`;
- boundary status reports remain `semantic-retrieval-0.1`.

The first execution adapter must write a separate report schema, starting at
`semantic-retrieval-execution-1.0`. That report may include retrieval status, adapter name,
manifest summary, source fingerprint, question fingerprint, `top_k`, selected evidence, and
fail-closed reason codes.

Adding semantic retrieval metadata to `prepare`, optimization, inspection, or benchmark
reports remains out of scope and requires a later accepted ADR or an explicit revision of this
ADR. Any future report integration must keep semantic fields separate from token-count fields
and must preserve ADR 0005 / ADR 0008 exact-vs-approximate token-count honesty.

## CLI and Config Impact

The current no-execution status behavior remains valid:

```bash
lcc semantic-retrieval [--config lcc.yaml] [--report semantic-status.json]
```

A future implementation may extend only the separate semantic retrieval command with an
explicit execution path. The accepted execution shape is:

```bash
lcc semantic-retrieval \
  --enable-semantic-retrieval \
  --execute \
  --source INPUT \
  --question TEXT \
  --adapter local_index_v1 \
  --index-manifest PATH \
  --embedding-assets PATH \
  [--top-k N] \
  [--config lcc.yaml] \
  [--report semantic-execution.json]
```

Config may supply only execution defaults:

```yaml
semantic_retrieval:
  enabled: true
  adapter: local_index_v1
  index_manifest: path/to/semantic.index.json
  embedding_assets: path/to/local-assets
  top_k: 8
```

`--execute` must be a CLI opt-in, not a config-only behavior. Existing deterministic commands
continue to ignore `semantic_retrieval` config keys unless a later ADR explicitly integrates
retrieval with those commands.

## Test Boundary

The eventual implementation must add tests that prove:

- default `optimize`, `inspect`, `prepare`, and `bench` paths do not import or invoke retrieval
  execution;
- status reporting and manifest validation still do not read vector contents;
- execution reads vector contents only after manifest, source, and asset validation pass;
- missing dependencies, missing assets, runtime-download attempts, stale indexes, source
  fingerprint mismatches, and dimension mismatches fail closed;
- selected evidence is copied from literal source spans and carries complete provenance;
- output ordering and tie-breaking are deterministic;
- report schemas remain separate from optimization, inspection, prepare, and benchmark
  schemas;
- optional dependencies are absent from the default install path.

No implementation tests are required by this ADR until the adapter is actually implemented.

## Out of Scope

This ADR does not authorize:

- index building, index refreshing, or corpus embedding generation;
- hosted vector databases or vector-store daemons;
- remote embedding APIs or remote LLM calls;
- local or remote answer generation;
- RAG prompt assembly inside `prepare` or `optimize`;
- model-backed inspection or benchmarking;
- answer-quality scoring;
- runtime downloads;
- automatic fallback to lexical selection when semantic execution fails;
- changing deterministic core behavior.

**Why.** The right next step is one narrow execution contract, not more scaffold code and not
a full RAG system. Keeping execution separate lets future work prove local semantic selection
without touching the deterministic commands that already work offline and without presenting
retrieval as implemented before it exists.

**Forecloses.** Retrieval execution may not enter the deterministic core, inspection,
preparation, lexical selection, or benchmarking by accident. The first implementation must be
explicit, local, fail-closed, provenance-preserving, and report-only until a later ADR accepts
prompt or prepare integration.
