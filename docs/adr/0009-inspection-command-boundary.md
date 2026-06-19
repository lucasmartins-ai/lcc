# ADR 0009 — `lcc inspect` is a diagnostic boundary (no prompt, no transform)

**Status:** accepted

**Context.** Before deciding whether to run `lcc optimize`, a user often wants to understand
an input's profile: how big it is in tokens and cost, how it is structured, how much of it is
duplicated, and how much the safe deterministic cleaning would plausibly remove. The MVP only
offers `optimize` (which always builds a prompt) and `bench` (which scores committed
fixtures). The roadmap listed "a standalone inspect / token-count command" as a not-yet-built
surface. This ADR fixes the boundary for that command so it cannot drift into transformation.

**Decision.** Add a read-only diagnostic command, `lcc inspect`, backed by a new
`lcc.inspection` package that sits **above** the deterministic core (like `lcc.cli` and
`lcc.benchmarking`). It composes the existing cleaning and token-budget utilities to *measure*
an input; it never optimizes it.

- **Diagnostic, not transformative.** `inspect` analyzes an input and emits a structured
  report. It does not transform the input into a deliverable artifact.
- **No downstream prompt.** Inspection never builds or writes an optimized prompt. The
  `lcc.inspection` package must not import `lcc.prompt_builder` and must not produce prompt
  text. (It deliberately does *not* route through `lcc.pipeline.optimize`, which always builds
  a prompt; it composes the cleaning utilities directly instead.)
- **No network / model / external services.** Like the rest of the deterministic core and the
  benchmark harness (ADR 0006, ADR 0007), inspection makes no network call and uses no LLM,
  API, embedding model, vector store, or other external service. Token counting reuses the
  existing guarded tokenizer path.
- **Safe-cleanup projection only.** Inspection may reuse the deterministic cleaning utilities
  (`normalize_text`, `remove_common_boilerplate`, `deduplicate_paragraphs`) to compute a
  *projection* of what the safe cleaning in `lcc optimize` would remove. It runs the same safe
  cleaning sequence as `optimize`, but only for measurement.
- **Projections are labelled as projections.** Any projected savings are clearly marked as an
  estimate of what `optimize` would remove — never as a completed optimization. The report
  carries a `projection_note` saying so.
- **Versioned report.** The inspection report carries its own `schema_version` (starting at
  `"1.0"`), independent of the optimization report's version (ADR 0004). Additive fields keep
  it at `"1.0"`; a breaking change bumps it.
- **Deterministic report.** Identical input produces a byte-identical report. No timestamps,
  no random values, no absolute local paths, no machine-specific values (e.g. hostname). The
  input source is recorded only as `"file"` or `"stdin"`, never as a path.
- **Honest token counts.** Token counts preserve the exact-vs-approximate contract of ADR 0005
  and ADR 0008: a count is `exact` only when `tiktoken` maps the model and its encoding assets
  load from a local cache; otherwise it is `approximate`, labelled, and the report warns. An
  approximation is never presented as exact.
- **The input is never modified.** `inspect` is read-only with respect to the input file. It
  reads, measures, and (optionally) writes a separate report file; it never writes back to the
  input.

**Why.** Users need a cheap, honest, offline way to decide whether optimization is worth it,
without paying for a model call or generating an artifact they did not ask for. Freezing the
"diagnostic, not transformative" boundary now keeps `inspect` from accreting prompt-building,
network, or model behavior later, which would blur it into `optimize` and break the local-first
promise.

**Forecloses.** `lcc.inspection` may not build prompts, call networks/models, or mutate inputs.
It composes deterministic utilities and reports measurements and clearly-labelled projections.
Any future semantic or model-based inspection lands behind a new, separate, opt-in boundary
(consistent with ADR 0002 and ADR 0006); it must not weaken this contract or the
exact-vs-approximate honesty of ADR 0005 / ADR 0008.
