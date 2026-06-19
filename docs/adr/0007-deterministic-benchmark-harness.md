# ADR 0007 — Deterministic benchmark harness

**Status:** accepted

**Decision.** A `lcc.benchmarking` package provides a fixture-based harness that runs the
existing deterministic pipeline over fixed local cases and measures **mechanical**
optimization behavior. It sits *above* the pipeline (like the CLI) and composes it; it is
not a peer of the deterministic core and does not change any core contract.

The harness obeys these rules:

- **Deterministic.** Identical fixtures and identical environment produce an identical
  report. No timestamps, no random values, no wall-clock or hostname metadata. The suite
  report is byte-stable across repeated runs and diffable in version control.
- **No network, no models.** The harness never calls a network, API, remote model, local
  LLM, or embedding model. It only invokes `lcc.pipeline.optimize`, which is itself
  network/LLM-free (ADR 0006). `tiktoken`, when installed, is used purely locally for token
  counting, exactly as in the rest of the tool.
- **Fixture-based and versioned.** Cases live under `benchmarks/cases/<id>/` as a
  `case.yaml` (metadata, markers, expectations) plus an `input.txt` (the raw context).
  Fixtures are committed to the repository so runs are reproducible.
- **Mechanical metrics only.** The harness measures token savings, compression ratio,
  character reduction, exact-vs-approximate tokenization status, literal marker
  preservation, and warning output. It makes **no claim about final LLM answer quality** or
  semantic correctness. Semantic and answer-quality evaluation is roadmap (Phases 2–7), not
  part of this harness.
- **Literal markers only.** Preservation is checked by literal substring match of
  `required_markers` / `forbidden_markers` against the rendered optimized prompt. There is
  no embedding similarity, paraphrase detection, or semantic matching in this phase.
- **Versioned report.** The suite report carries its own `schema_version` (starting at
  `"1.0"`), independent of the optimization report's version (ADR 0004). Additive fields
  keep it at `"1.0"`; a breaking change bumps it.
- **Explicit per-case thresholds.** Each case declares its own pass/fail expectations
  (min/max token savings, minimum required-marker recall, whether approximate token counting
  is allowed, maximum surviving forbidden markers). A case passes only when every threshold
  is met; failures list explicit, deterministic reasons.

**Why.** Contributors need a reproducible way to see that cleaning saves tokens without
dropping required evidence, and to catch regressions in a diff. Tying the harness to the
deterministic core (rather than to a model) keeps it honest, fast, dependency-light, and
runnable offline with no API key.

**Forecloses.** Because counts are honest about exactness (ADR 0005), exact-mode
expectations (`allow_approximate_token_count: false`) require `tiktoken` to be installed;
without it, counting falls back to approximate and those cases fail rather than pretend a
heuristic count is exact. Any future semantic/answer-quality benchmark is a separate,
clearly labeled harness behind its own boundary — it must not be presented as part of, or
implemented inside, this deterministic harness.
