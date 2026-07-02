# Local Context Compiler (`lcc`)

[![CI](https://github.com/vetlucasmartins/lcc/actions/workflows/ci.yml/badge.svg)](https://github.com/vetlucasmartins/lcc/actions/workflows/ci.yml)

Deterministic, local-first context optimization for LLM prompts.

`lcc` cleans, deduplicates, structures, and measures text context before you send it to a
large language model. It does not call a model, require an API key, or send your text over the
network.

## At a Glance

| Question | Answer |
| --- | --- |
| What is it? | A local CLI and Python package for preparing cleaner LLM prompt context. |
| What does it improve? | Token count, cost visibility, repeated text, boilerplate, and prompt structure. |
| What does it preserve? | Original evidence, user intent, and an auditable JSON report of every step. |
| What does it avoid? | Runtime network calls, API keys, LLM calls, embeddings, vector stores, and lossy summarization. |
| Current version | `0.2.0`: `optimize`, `inspect`, `bench`, and the tokenizer network guard. |

## Why It Exists

LLM context is often noisy: repeated paragraphs, email signatures, page markers, decorative
rules, inconsistent whitespace, and copied boilerplate all waste tokens. Sending that raw
context increases cost and can bury the evidence the model needs.

Blind compression is risky too. Summaries can remove the detail that makes an answer
grounded. `lcc` takes a narrower approach:

- remove only safe, redundant, or non-meaningful text;
- never summarize, paraphrase, or rewrite the source content;
- count tokens honestly as `exact` or `approximate`;
- estimate cost from editable pricing data;
- produce a deterministic report that explains what changed.

## What It Does Today

`lcc optimize` runs this deterministic pipeline:

```text
raw text
  -> normalize whitespace and line endings
  -> remove conservative whole-line boilerplate
  -> deduplicate exact and near-duplicate paragraphs
  -> count tokens exactly or with a labelled approximation
  -> build an evidence-aware prompt
  -> estimate input cost
  -> write a JSON report and optimized prompt
```

The current release supports:

- file or stdin input;
- whitespace and line-ending normalization;
- conservative boilerplate removal;
- exact and conservative near-duplicate paragraph deduplication;
- exact token counting with locally available `tiktoken` assets;
- approximate token counting when exact local counting is unavailable;
- editable model pricing and input-cost estimates;
- evidence-aware prompt rendering;
- deterministic JSON reports with `schema_version: "1.0"`;
- `lcc inspect` for read-only diagnostics;
- `lcc bench` for deterministic fixture-based benchmark cases.

## What It Does Not Do

These items are roadmap work and are not implemented in this repository:

- semantic retrieval or RAG;
- embeddings or vector stores;
- local or remote LLM calls;
- hosted API server;
- model routing;
- response verification;
- transcript ingestion;
- voice or audio adapters;
- semantic answer-quality scoring.

The deterministic core stays intentionally small. Future capabilities must live behind clear
boundaries so the local-first behavior remains easy to audit.

## Install

Requires Python 3.11+.

For the published CLI, prefer `pipx`:

```bash
pipx install local-context-compiler
lcc --version
```

Or install into an environment you manage:

```bash
python -m pip install local-context-compiler
lcc --version
```

Optional exact token counting:

```bash
pipx install "local-context-compiler[tiktoken]"
python -m pip install "local-context-compiler[tiktoken]"
```

Without `tiktoken`, `lcc` still runs and marks token counts as approximate. With `tiktoken`,
exact counting is used only when the required encoding assets are already available locally.
`lcc` blocks runtime tokenizer downloads and falls back to an approximate count instead of
making a network request. See [ADR 0008](docs/adr/0008-tokenizer-network-boundary.md).

For local development:

```bash
git clone https://github.com/vetlucasmartins/lcc
cd lcc
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Quick Start

Create a small noisy input:

```bash
printf 'Alpha point.\n\nAlpha point.\n\nRegards,\nTeam\n' > /tmp/lcc_sample.txt
```

Optimize it:

```bash
lcc optimize /tmp/lcc_sample.txt \
  --question "What are the key points?" \
  --model gpt-4.1 \
  --output /tmp/lcc_prompt.md \
  --report /tmp/lcc_report.json
```

Inspect the same input without generating a prompt:

```bash
lcc inspect /tmp/lcc_sample.txt --model gpt-4.1 --report /tmp/lcc_inspect.json
lcc inspect /tmp/lcc_sample.txt --model gpt-4.1 --summary compact
```

Run the bundled deterministic benchmarks from a source checkout:

```bash
lcc bench benchmarks/cases --output /tmp/lcc_bench.json
```

## Command Guide

### `lcc optimize`

Use `optimize` when you are ready to create a prompt package.

```bash
lcc optimize examples/sample_input.txt \
  --question "What are the key points and risks?" \
  --model gpt-4.1 \
  --max-input-tokens 6000 \
  --output optimized_prompt.md \
  --report report.json
```

Output behavior:

- the optimized prompt goes to `--output`, or stdout if omitted;
- the JSON report goes to `--report`, when provided;
- the human-readable summary and warnings go to stderr, so stdout stays pipe-safe.

Useful options:

```bash
# Read from stdin
cat examples/sample_input.txt | lcc optimize - \
  --question "Summarize the relevant information." \
  --output optimized_prompt.md \
  --report report.json

# Use editable defaults and pricing
lcc optimize examples/sample_input.txt -q "Summarize." \
  --config config/default.yaml \
  --pricing config/pricing.yaml

# Disable conservative cleanup steps
lcc optimize examples/sample_input.txt -q "Summarize." \
  --no-near-dedup \
  --no-boilerplate
```

### `lcc inspect`

Use `inspect` before optimization when you want to understand the input first.

```bash
lcc inspect examples/sample_input.txt --model gpt-4.1 --report inspect_report.json
```

The report includes:

- source type, characters, lines, and paragraphs;
- token count, counting method, tokenizer, and estimated input cost;
- structure metrics such as blank-line runs and longest paragraph;
- exact and near-duplicate paragraph counts;
- a safe-cleanup projection of what `optimize` would remove, including per-stage projected
  contributions for normalization, boilerplate removal, exact deduplication, and near-dedup;
- a deterministic recommendation (`skip`, `optimize_safe`, `optimize_with_flags`, or
  `manual_review`) with reason codes and a suggested next command when optimization is useful.

For a short human summary, use:

```bash
lcc inspect examples/sample_input.txt --summary compact
```

`inspect` is diagnostic only. It builds no prompt, calls no model, makes no network request,
and never modifies the input. Projected savings are labelled as projections, not completed
optimizations. See [ADR 0009](docs/adr/0009-inspection-command-boundary.md).

### `lcc bench`

Use `bench` to run deterministic fixture cases.

```bash
lcc bench benchmarks/cases --output bench_report.json --markdown bench_report.md
```

The benchmark harness reports mechanical behavior: token savings, compression ratio,
character reduction, exact-vs-approximate token mode, literal marker preservation, warnings,
and pass/fail thresholds. It does not measure final LLM answer quality.

See [benchmarks/README.md](benchmarks/README.md) and
[ADR 0007](docs/adr/0007-deterministic-benchmark-harness.md).

## Example Summary

Running the bundled `examples/sample_input.txt` can produce output like this:

```text
    lcc -- optimization summary
Model               gpt-4.1
Token counting      exact (tiktoken)
Original tokens     236
Optimized tokens    128
Token savings       45.8%
Compression ratio   0.542
Full prompt tokens  265
Est. cost before    0.000472 USD
Est. cost after     0.000256 USD
Est. cost savings   0.000216 USD
```

Report excerpt:

```json
{
  "schema_version": "1.0",
  "model": "gpt-4.1",
  "original_token_count": 236,
  "optimized_token_count": 128,
  "compression_ratio": 0.5424,
  "token_savings_percent": 45.76,
  "token_count_method": "exact",
  "token_encoding": "o200k_base",
  "cost": {
    "before": 0.000472,
    "after": 0.000256,
    "savings": 0.000216,
    "currency": "USD"
  },
  "warnings": []
}
```

## Architecture

`lcc` keeps deterministic logic separate from IO and presentation.

| Module | Responsibility |
| --- | --- |
| `lcc.cleaning` | Normalize text, remove conservative boilerplate, deduplicate paragraphs. |
| `lcc.token_budget` | Count tokens exactly or approximately, and estimate input cost. |
| `lcc.prompt_builder` | Render an evidence-aware prompt from a structured spec. |
| `lcc.reporting` | Build deterministic JSON reports. |
| `lcc.pipeline` | Compose the deterministic modules. |
| `lcc.cli` | Handle Typer/Rich CLI output, files, stdin, and config loading. |
| `lcc.benchmarking` | Run deterministic benchmark fixtures. |
| `lcc.inspection` | Profile one input without building a prompt. |

Read more:

- [Architecture](docs/architecture.md)
- [Evaluation](docs/evaluation.md)
- [Roadmap](docs/roadmap.md)
- [Architecture decision records](docs/adr/)
- [Project presentation](docs/project-presentation.md)
- [Release process](docs/release.md)

## Development

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Required checks:

```bash
python -m pytest
ruff check .
ruff format --check .
mypy
```

Contributions should keep the deterministic core free of network, LLM, embedding, and hosted
service dependencies. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security and Privacy

`lcc` is local-first by design:

- no API keys are required;
- no telemetry is collected;
- no model or hosted service is called;
- runtime network access is blocked by default, including indirect `tiktoken` downloads;
- generated prompts and reports are written only to paths you choose.

Review generated prompts and reports before committing them. They can contain source context
or metadata derived from your input. See [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).

## Accuracy Notes

Token counts are exact only when `tiktoken` recognizes the model and the encoding assets are
available locally. Otherwise, the report marks counts as approximate and includes a warning.

Bundled pricing in `config/pricing.yaml` and the built-in pricing table is editable example
data, not guaranteed current provider pricing. Verify prices before relying on cost figures.
