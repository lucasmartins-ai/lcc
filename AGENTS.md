# AGENTS.md — guidance for Codex and other coding agents

Concise operating guide for automated coding agents working in this repository. (Claude
Code users: see `CLAUDE.md` for the longer version; the rules are the same.)

## What this project is

`lcc` — a deterministic, local-first toolkit that cleans, deduplicates, structures, and
measures text context before an LLM call. No network calls. No API keys. Not a model
replacement.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Test / lint / type-check commands

```bash
python -m pytest          # tests (must pass)
ruff check .              # lint (must pass)
ruff format --check .     # formatting (must pass)
mypy                      # static types (keep clean)
```

Run all four before reporting a task complete. Do not fabricate results.

## Style rules

- Python 3.11+, typed where reasonable, docstrings on public functions.
- `ruff` is the formatter and linter (line length 100). Match existing style.
- Small modules, single responsibility, explicit names.

## Repository expectations

- Keep the deterministic core (`cleaning`, `token_budget`, `prompt_builder`, `reporting`,
  `pipeline`) free of network/LLM code. Only `pipeline` composes modules; only `cli`
  does IO and config loading. (See `docs/adr/`.)
- Token counts must honestly report `exact` vs `approximate`. `lcc` blocks runtime network
  access by default — including `tiktoken`'s indirect first-use encoding download — via a
  tightly scoped no-network guard in `lcc.token_budget.counters`. Exact counting requires
  tokenizer assets to be cached locally; otherwise counting falls back to a labelled
  approximation. Keep the precise claim ("blocks runtime network by default, falls back
  honestly when exact tokenizer assets are unavailable"), never a vague "local-ish". See
  `docs/adr/0008`.
- The JSON report has a `schema_version`; do not break it without bumping it.
- **Do not add heavy dependencies** without justification.
- **Do not implement roadmap features** (RAG, embeddings, local LLMs, routing, verification)
  unless explicitly asked — record them in `docs/roadmap.md`.
- **Never document a feature that is not implemented.**
- The benchmark harness (`lcc.benchmarking`, ADR 0007, run via `lcc bench benchmarks/cases`)
  stays deterministic and network/LLM-free and measures mechanical optimization behavior
  only; never claim it evaluates LLM answer quality.
- Make the smallest safe change; do not rewrite large parts unprompted.
