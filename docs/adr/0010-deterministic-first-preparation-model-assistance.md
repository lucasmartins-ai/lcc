# ADR 0010 - Deterministic-first preparation and optional model assistance

**Status:** accepted

**Context.** Phase 1.7 added deterministic `lcc prepare` orchestration, inspection
recommendations, chunk inventory, lexical selection, and prepare benchmark coverage. The
roadmap also leaves room for optional future model assistance, but no such assistance is
implemented today. Without a written boundary, future work could accidentally blur
deterministic preparation into semantic selection, inspection transformation, model-backed
rewriting, or answer-quality benchmarking.

**Decision.** Preparation remains deterministic-first. Optional future model assistance is not
implemented and must live outside the deterministic core and outside the inspection boundary.

- **Core modules stay model-free.** No LLM, embedding model, network client, runtime download,
  local-model call, or remote model call may enter `cleaning`, `token_budget`,
  `prompt_builder`, `reporting`, `pipeline`, `inspection`, or `benchmarking`.
- **Inspection stays diagnostic, not transformative.** `lcc inspect` may measure source text,
  report deterministic structure, and project safe-cleanup savings. It must not build prompts,
  choose evidence with a model, summarize source text, rewrite source text, paraphrase source
  text, or modify the input.
- **Preparation stays deterministic by default.** `lcc prepare` may orchestrate inspection,
  deterministic recommendations, lexical chunk selection, and the existing safe optimization
  path. It never summarizes, rewrites, or paraphrases source content.
- **Benchmarks stay mechanical.** `lcc.benchmarking` measures deterministic mechanical
  behavior only - token savings, character reduction, exact-vs-approximate token mode, literal
  marker preservation, warning output, prepare action, and lexical-selection state. It is not
  LLM answer quality evaluation.
- **Token-count honesty remains unchanged.** Any future opt-in model-assistance layer must
  preserve the ADR 0005 / ADR 0008 exact-vs-approximate token-count contract. Runtime downloads
  are not a valid way to make deterministic token counts appear exact.
- **Future assistance needs its own boundary.** If a later command, package, or harness uses a
  local model, remote model, embedding model, vector store, network client, or runtime
  download, it must be explicit, opt-in, separately documented, and outside the modules listed
  above.

**Why.** The product promise is that `lcc` prepares context before a model call without making
one itself. Deterministic-first preparation keeps reports auditable, lets users run the tool
offline, avoids hidden dependency or tokenizer downloads, and prevents lexical selection from
being mistaken for semantic understanding.

**Forecloses.** No future work may add semantic selection, embeddings, RAG, local-model calls,
remote model calls, model-assisted rewriting, model-backed inspection, or answer-quality
scoring inside the deterministic core, inspection, or benchmark harness. Those capabilities
remain roadmap work behind separate, opt-in boundaries and must not weaken ADR 0005, ADR 0006,
ADR 0007, ADR 0008, or ADR 0009.

**Clarification (0.4.0, decision unchanged).** The opt-in layers foreseen above now
exist and stay outside the core: `lcc compact` relevance providers (mechanical /
Jev / Laya, ADRs 0013/0016), the minimum-sufficient-context machinery — safety
model, context graph, type-aware trim, sufficiency verification, independent
semantic verifier (ADRs 0014/0015) — and the agent/router/retrieval scaffolds.
Concretely: no network, autoregressive LLM, embedding, download, torch /
transformers / Laya, or LLM-SDK import may enter `cleaning`, `token_budget`
(beyond its fail-closed download guard), `inspection`, `pipeline`,
`lexical_selection`, or `benchmarking` (beyond `*_VERSION` identity constants);
pinned by `tests/test_deterministic_boundary.py`. `mechanical` and `laya`
paths run with no API key and no network.
