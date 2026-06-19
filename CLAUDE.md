# CLAUDE.md — guidance for Claude Code in this repository

## Project purpose

Local Context Compiler (`lcc`) is a deterministic, local-first toolkit that cleans,
deduplicates, structures, and **measures** text context before it is sent to a large LLM.
It is a middle layer, not a model replacement. The MVP makes **no network calls** and
requires **no API key**.

Core philosophy: do not send more context than necessary, nor less than sufficient;
optimize for measurable token savings **without destructive compression**; prefer
deterministic cleaning; preserve user intent and evidence provenance.

## Architecture constraints (do not violate)

- The deterministic core — `lcc.cleaning`, `lcc.token_budget`, `lcc.prompt_builder`,
  `lcc.reporting`, and `lcc.pipeline` — must contain **no network or LLM code** and must be
  deterministic (identical input → identical output). See `docs/adr/0006`.
- Modules do not import each other; only `lcc.pipeline` composes them. `lcc.cli` is the only
  presentation/IO layer (Typer/Rich) and the only place config files are read. See
  `docs/adr/0002`.
- The JSON report carries `schema_version`. Additive fields keep it at `1.0`; a breaking
  change bumps it. See `docs/adr/0004`.
- Token counts are `exact` only when `tiktoken` maps the model **and** its encoding assets
  load from a local cache; otherwise `approximate`, and the report must say so honestly (with
  a warning explaining why). Never present an approximation as exact. See `docs/adr/0005`.
- `lcc` blocks runtime network access by default — including the indirect first-use encoding
  download `tiktoken` would otherwise perform. The exact path runs inside a tightly scoped
  no-network guard (`lcc.token_budget.counters._no_network_guard`); if tiktoken would fetch
  assets, the guard blocks it and counting falls back to a labelled approximation. Do not
  weaken this guard or soften the message to "local-ish": the claim is "blocks runtime network
  by default, falls back honestly when exact tokenizer assets are unavailable". See
  `docs/adr/0008`.
- Schemas are stdlib `dataclasses`, not Pydantic (keeps the core dependency-free). See
  `docs/adr/0001`.
- The benchmark harness (`lcc.benchmarking`, ADR 0007; run via `lcc bench benchmarks/cases`)
  is a composition layer **above** the pipeline, like the CLI. It may import `lcc.pipeline`
  but must stay deterministic and free of network/LLM/embedding calls, must not be imported
  by the deterministic core, and measures mechanical behavior only — never claim it
  evaluates LLM answer quality.

## Coding standards

- Python 3.11+, typed where reasonable; public functions have docstrings.
- `ruff` governs lint and formatting (line length 100). Keep `mypy` clean.
- Small modules, explicit responsibilities, clear names. Match the surrounding style.

## Testing expectations

- New behavior requires tests. Cover edge cases (empty input, single/all-duplicate
  paragraphs, unicode, CRLF/LF, tokenizer fallback, CLI stdin and error exits).
- All of these must pass before claiming done:
  `python -m pytest`, `ruff check .`, `ruff format --check .`, `mypy`.
- Never fabricate test results. If you cannot run a check, say so and give the command.

## Documentation expectations

- Keep `README.md`, `docs/`, and `CHANGELOG.md` in sync with behavior.
- **Never describe a roadmap feature as implemented.** If it is not in the code, it is not
  done. This is the single most important documentation rule here.

## Hard rules

1. **Do not add heavy dependencies** without explicit justification. The MVP runtime deps
   are `typer`, `rich`, `pyyaml`, plus optional `tiktoken`.
2. **Do not implement roadmap features** (RAG, embeddings, local LLMs, intent classifier,
   evidence extraction, model routing, response verification) unless explicitly requested.
   Add them to `docs/roadmap.md` instead.
3. Make the smallest safe change. Do not redesign or rewrite large parts unprompted.
4. No network calls, no required API keys, no hosted services in the core.
