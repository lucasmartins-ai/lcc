# Contributing to Local Context Compiler

Thanks for your interest in improving `lcc`. This project values small, well-tested,
well-documented changes over large rewrites.

## Development setup

Requires Python 3.11+.

```bash
git clone https://github.com/your-org/local-context-compiler
cd local-context-compiler
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the checks

```bash
python -m pytest          # tests
ruff check .              # lint
ruff format --check .     # formatting
mypy                      # optional static type check
```

All four should pass before you open a pull request. New behavior needs tests.

## Code style

- Python 3.11+, typed where reasonable. Public functions have docstrings.
- `ruff` is the single source of truth for lint and formatting (config in `pyproject.toml`,
  line length 100).
- Prefer small modules with explicit responsibilities. Keep the deterministic core
  (`cleaning`, `token_budget`, `prompt_builder`, `reporting`, `pipeline`) free of any
  network or LLM dependency — see [docs/adr/0006](docs/adr/0006-determinism-boundary.md).
- **Do not add heavy dependencies** without a clear justification in the PR description.
- **Do not implement roadmap features** (RAG, embeddings, local LLMs, model routing,
  response verification) unless an issue explicitly asks for it. The MVP stays small.

## Commits and pull requests

- Keep commits focused; write imperative, descriptive messages ("Add near-duplicate cap").
- In the PR description, explain *what* changed, *why*, and *how to test it*. Note any new
  dependency and any residual risk.
- If your change affects the JSON report shape, follow
  [docs/adr/0004](docs/adr/0004-report-schema-versioning.md): additive fields keep
  `schema_version` at `1.0`; a breaking change bumps it.

## Proposing features

Open an issue describing the problem, the smallest useful change, and where it fits on the
[roadmap](docs/roadmap.md). For one-way-door decisions (public API, cross-module contracts),
propose a short ADR in [docs/adr/](docs/adr/) first.

By contributing, you agree your contributions are licensed under the project's
[MIT License](LICENSE), and you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
