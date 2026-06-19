# Architecture

## Design philosophy

`lcc` is a deterministic middle layer that prepares context for a large LLM. It is not a
model and does not call one. Its job is to send **as little as necessary and as much as
sufficient**, with measurable savings and without destructive compression.

Principles:

- **Deterministic before model-based.** All cleaning is rule-based and reproducible.
  Anything that needs a model is deferred to a clearly separated, future boundary.
- **Safe over aggressive.** Cleaning removes redundant or non-meaningful text only. It never
  summarizes, rewrites, or shortens a paragraph.
- **Honest measurement.** Token counts declare whether they are exact or approximate; prices
  are editable examples; nothing is presented as more certain than it is.
- **Traceable.** Every cleaning action and every warning is recorded in the report.

## Pipeline (text diagram)

```
                +-------------------+
  raw text ---> |  normalize_text   |  line endings, trailing ws, inner spaces, blank runs
                +---------+---------+
                          |
                          v
                +-------------------+
                | remove_boilerplate|  conservative, whole-line matches only
                +---------+---------+
                          |
                          v
                +-------------------+
                | deduplicate_      |  exact + conservative near-duplicate paragraphs
                | paragraphs        |
                +---------+---------+
                          |  cleaned context
          +---------------+----------------+
          v                                v
  +---------------+                 +----------------+
  | count_tokens  |                 | build_prompt   |  evidence-aware template
  | (orig + opt)  |                 +-------+--------+
  +-------+-------+                         |
          |                                 v
          |                         +----------------+
          |                         | count_tokens   |  full prompt (informational)
          |                         +-------+--------+
          v                                 |
  +-----------------+                       |
  | pricing / cost  |                       |
  +-------+---------+                        |
          |                                  |
          +---------------+------------------+
                          v
                +-------------------+
                |   build_report    |  OptimizationReport (JSON, schema_version)
                +-------------------+
```

All of the above is orchestrated by `lcc.pipeline.optimize`. The `lcc.cli` layer handles
file/stdin IO, config, and terminal rendering.

## Module responsibilities

| Module | Input → Output | Notes |
| --- | --- | --- |
| `lcc.cleaning.normalize` | text → text + steps | whitespace/line-ending normalization |
| `lcc.cleaning.boilerplate` | text → text + actions | conservative whole-line removal |
| `lcc.cleaning.deduplicate` | text → text + metrics | exact + near-duplicate paragraphs |
| `lcc.token_budget.counters` | text, model → `TokenCount` | tiktoken exact (guarded, no network), else heuristic |
| `lcc.token_budget.pricing` | pricing doc, model → cost | editable, example pricing |
| `lcc.prompt_builder` | `PromptSpec` → str | extensible template registry |
| `lcc.reporting.report` | parts → `OptimizationReport` + JSON | depends only on `schemas` |
| `lcc.pipeline` | `OptimizationRequest` → `OptimizationResult` | the only composer |
| `lcc.cli` | argv/stdin → files + summary | Typer/Rich; the only IO layer |
| `lcc.schemas` | — | shared dataclasses; the cross-module contract |
| `lcc.benchmarking` | cases → suite report | runs the pipeline over fixtures; deterministic, no network (ADR 0007) |
| `lcc.inspection` | text → diagnostic report | profiles an input + projects safe-cleaning savings; builds **no** prompt, deterministic, no network (ADR 0009) |

## Current MVP architecture

- Pure-stdlib deterministic core; `tiktoken` is an **optional** native dependency used only
  for local token counting (with a graceful fallback). The exact path runs inside a tightly
  scoped no-network guard, so `lcc` performs **no network access during normal operation** —
  including indirectly through `tiktoken`. Exact counting requires the tokenizer's encoding
  assets to be available locally; if they would need to be downloaded, the guard blocks the
  fetch and counting falls back to a clearly labelled approximation (see
  [adr/0008](adr/0008-tokenizer-network-boundary.md)).
- The report is a stdlib dataclass serialized to JSON via a small recursive normalizer.
- The CLI is a thin Typer app; all logic is unit-testable without Typer or Rich.
- A deterministic **benchmark harness** (`lcc.benchmarking`, ADR 0007) runs the pipeline
  over committed fixtures and reports mechanical metrics (token savings, marker
  preservation, exact/approximate mode). Like the CLI it composes the pipeline and adds no
  core dependency; it makes no claim about LLM answer quality.
- A deterministic **inspection command** (`lcc.inspection`, ADR 0009) profiles a single input
  — tokens, structure, duplication, cleanup, and cost — and projects what `optimize`'s safe
  cleaning would remove, **without** building a prompt. It sits above the pipeline like the CLI
  and benchmark harness, composes the cleaning and token-budget utilities directly (it does not
  import `prompt_builder`), is deterministic and network/model-free, and never modifies the
  input. It is **diagnostic, not transformative**, and makes no claim about answer quality.

The one-way-door decisions are recorded in [adr/](adr/).

## Future architecture (roadmap, not implemented)

Later phases attach **behind new, clearly separated boundaries** so the deterministic core
stays intact and dependency-free:

- **Local semantic retrieval / RAG** — a retrieval module that selects relevant chunks; it
  would feed cleaned context into the existing pipeline, not replace it.
- **Local intent classifier** — a small local model to infer task type, isolated from
  cleaning.
- **Evidence extraction** — span-level provenance attached to the prompt package.
- **Model routing** — choose a downstream model from a cost/quality policy.
- **Response verification** — check answers for unsupported claims after the LLM call.

Each is a separate module with its own optional dependency; none may import into or change
the deterministic core's contracts (see ADRs 0002 and 0006).

## Non-goals

- `lcc` is **not** an LLM or an inference server, and does not call one in the MVP.
- It does **not** perform lossy summarization or paraphrase context.
- It does **not** require an API key, network access, or any hosted service.
- It does **not** guarantee pricing accuracy — pricing is user-editable example data.
