# ADR 0011 - Phase 2 opt-in semantic retrieval boundary

**Status:** accepted

**Context.** Phase 1.7 closes the deterministic prepare workflow: inspection,
recommendations, chunk inventory, lexical selection, and prepare benchmark coverage are all
mechanical and model-free. The roadmap's first Phase 2 capability is optional local semantic
retrieval, but retrieval execution is still not implemented. Before any retrieval code lands,
the repository needs an accepted implementation boundary that keeps Phase 2 from weakening the
deterministic promises in ADR 0005 through ADR 0010.

**Decision.** Accept a disabled-by-default opt-in scaffold for future local semantic
retrieval. The scaffold may validate the boundary and report that retrieval is disabled or
blocked, but it must not perform retrieval. It does not retrieve, rank, select, embed,
summarize, rewrite, paraphrase, call a model, touch the network, or build a prompt.
Optional local semantic retrieval stays outside the deterministic core, outside the inspection
boundary, and outside the deterministic benchmark harness. It must not enter `cleaning`,
`token_budget`, `prompt_builder`, `reporting`, `pipeline`, `inspection`, or `benchmarking`.

The first runtime slice is intentionally small:

- A separate `lcc.semantic_retrieval` package owns the semantic retrieval boundary scaffold.
- A separate `lcc semantic-retrieval` CLI command reports the boundary state.
- Configuration keys live under a separate `semantic_retrieval` mapping.
- Retrieval execution remains blocked until a later accepted ADR defines and implements a
  concrete retrieval adapter.

## Command and Configuration Surface

The scaffold is disabled by default. Existing deterministic commands (`inspect`, `prepare`,
`optimize`, and `bench`) keep their default behavior and do not invoke semantic retrieval.

The only Phase 2 CLI surface accepted by this ADR is:

```bash
lcc semantic-retrieval \
  [--enable-semantic-retrieval] \
  [--index-manifest PATH] \
  [--embedding-assets PATH] \
  [--top-k N] \
  [--config lcc.yaml] \
  [--report semantic-status.json]
```

The equivalent config surface is:

```yaml
semantic_retrieval:
  enabled: false
  index_manifest: path/to/semantic.index.json
  embedding_assets: path/to/local-assets
  top_k: 8
```

CLI flags override config values. `semantic_retrieval.enabled` defaults to `false`. When it is
false, the command emits a deterministic disabled report and exits successfully. The accepted
configuration keys are `semantic_retrieval.enabled`, `semantic_retrieval.index_manifest`,
`semantic_retrieval.embedding_assets`, and `semantic_retrieval.top_k`. When enabled is true,
the command must fail closed unless all required local artifacts are present and a later
accepted implementation actually supports retrieval execution. In the current scaffold, even
valid local artifacts produce a blocked report and a non-zero exit because retrieval execution
is not implemented.

## Module Boundary

The semantic layer is owned by `lcc.semantic_retrieval`. It sits above and outside the
deterministic core, like `lcc.cli`, `lcc.inspection`, and `lcc.benchmarking`.

Import direction is part of the contract:

- `lcc.cli` may import `lcc.semantic_retrieval` for the separate boundary command.
- Future semantic code may consume deterministic reports or source spans through explicit
  arguments, but deterministic modules must not import semantic code.
- `cleaning`, `token_budget`, `prompt_builder`, `reporting`, `pipeline`, `inspection`, and
  `benchmarking` must not import `lcc.semantic_retrieval`.
- The scaffold uses only the standard library. A future retrieval adapter that needs optional
  dependencies must live behind this package boundary and a separate optional extra.

## Dependency and Asset Contract

No embedding model, vector store, tokenizer, local model, remote model, API client, runtime
download, or non-stdlib dependency is required by the scaffold.

Future retrieval execution must satisfy all of these conditions before it can be implemented:

- Dependencies are optional and explicit, for example behind a future `lcc[semantic]` extra.
- Runtime downloads are forbidden. Model, tokenizer, embedding, and index assets must already
  exist locally or be prepared by an explicit user action outside default command paths.
- Missing optional dependencies or assets must fail closed with a user-facing reason; they must
  not silently fall back to network access or a different model.
- Token counting remains governed by ADR 0005 and ADR 0008. A semantic layer may not upgrade
  approximate token counts to exact.

## Index and Provenance Contract

A future retrieval adapter must use a versioned local index manifest. The reserved first
manifest version is `semantic-index-1.0`. The manifest must be deterministic JSON and must
record at least:

- the manifest schema version;
- a source fingerprint, such as `sha256:<hex>`, for the exact source text used to create the
  index;
- embedding model metadata, including provider, model name, dimensions, and local asset
  fingerprints;
- chunk IDs that correspond to deterministic inspection `chunk_inventory` IDs or a clearly
  versioned replacement inventory;
- source character offsets and line spans for every indexed chunk;
- a source-text hash for each chunk so stale indexes can be detected;
- vector record references and vector dimensionality;
- index creation settings that affect retrieval results, without timestamps, hostnames, or
  machine-specific absolute paths.

Selected evidence must preserve provenance as source spans. The first retrieval slice may
select or reference literal source spans, but it must not rewrite, paraphrase, or summarize
source evidence by default. Any later prompt integration must assemble literal source text
from provenance spans, not from generated summaries.

## Report Schema Impact

Existing report schemas are unchanged by this ADR:

- optimization reports remain `schema_version: "1.0"`;
- inspection reports remain `schema_version: "1.0"`;
- benchmark suite reports remain `schema_version: "1.0"`;
- prepare reports remain `prepare-1.0`.

The scaffold has its own boundary status report schema:

```json
{
  "schema_version": "semantic-retrieval-0.1",
  "enabled": false,
  "status": "disabled",
  "reason_code": "semantic_retrieval_disabled",
  "retrieval_performed": false
}
```

Future integration that adds semantic retrieval metadata to `prepare`, optimization,
inspection, or benchmark reports requires a new accepted ADR or an explicit ADR 0011 revision.
Any breaking report-shape change must bump that report's schema version. Semantic metadata
must be clearly separate from token-count fields, and exact-vs-approximate token-count honesty
must remain visible.

## Failure Modes

The boundary must fail closed:

- Disabled config emits `status: "disabled"` and performs no retrieval.
- Enabled config without an index manifest fails before any retrieval attempt.
- Enabled config without embedding assets fails before any retrieval attempt.
- Invalid `top_k` fails before any retrieval attempt.
- Present artifacts with no implemented adapter emit `status: "blocked"` and exit non-zero.
- Optional dependency failures must be reported as dependency failures, not as empty results.
- Incompatible manifest versions, source fingerprints, vector dimensions, or stale chunk hashes
  must fail closed.
- Approximate token counts remain approximate and must be reported as such if future reports
  include token counts.

## Test Boundary

Tests for this boundary must prove:

- existing deterministic command defaults avoid semantic retrieval, embeddings, model calls,
  network access, runtime downloads, and answer-quality claims;
- `lcc.semantic_retrieval` is disabled by default;
- enabling the boundary requires explicit local index and embedding asset paths;
- enabled scaffolding fails closed until retrieval execution is implemented;
- deterministic core modules do not import `lcc.semantic_retrieval`;
- inspection remains diagnostic, not transformative;
- benchmarking remains mechanical by default.

**Why.** Phase 2 is valuable only if it is clearly optional. The project promise is still that
`lcc` can inspect, prepare, optimize, and benchmark local context without making a model call,
touching a network, or hiding approximation. Accepting this boundary lets the next
implementation step start from explicit contracts without smuggling semantic behavior into
deterministic surfaces.

**Forecloses.** Future Phase 2 work may not add semantic selection, embeddings, vector stores,
RAG, local-model calls, remote model calls, runtime downloads, model-backed inspection, or
semantic benchmark claims inside `cleaning`, `token_budget`, `prompt_builder`, `reporting`,
`pipeline`, `inspection`, or `benchmarking`. Retrieval execution remains blocked until a
future accepted ADR or ADR 0011 revision defines a concrete adapter while keeping the semantic
retrieval layer opt-in, separable, and honest about dependencies and limits.
