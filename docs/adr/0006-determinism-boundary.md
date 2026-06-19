# ADR 0006 — Cleaning/dedup stay free of LLM and network

**Status:** accepted

**Decision.** `cleaning/`, `token_budget/`, `prompt_builder/`, `reporting/` and
`pipeline.py` must not import any network or LLM client and must produce identical output
for identical input. `tiktoken` is the only optional native dependency and is used purely
locally; if it performs or fails any network access, the counter falls back to a heuristic.

**Why.** The promise "deterministic cleaning before any local LLM" must hold structurally,
and the tool must run with no API key and no network access.

**Forecloses.** Any future RAG / model-router / verifier that needs a model lives behind a
new, clearly separated boundary — never inside these deterministic modules.
