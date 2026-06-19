# Local Context Compiler (lcc)

[![CI](https://github.com/vetlucasmartins/lcc/actions/workflows/ci.yml/badge.svg)](https://github.com/vetlucasmartins/lcc/actions/workflows/ci.yml)

> Deterministic, local-first context optimization for LLM prompts: clean, dedupe,
> structure, and **measure** token and cost savings *before* you call a large model.

`lcc` is a middle layer between your application and a large language model. It does **not**
replace the model. It prepares a smaller, cleaner, more structured, evidence-aware prompt
package and tells you, in measurable numbers, how many tokens and how much money you saved.

**Status: v0.1.0 release candidate.** Shipping today: a deterministic MVP, a deterministic
benchmark harness (`lcc bench`), and a tokenizer network guard (runtime network blocked by
default; exact token counting only from local `tiktoken` assets, otherwise an honestly
labelled approximate count). See the [release checklist](docs/release.md) for the full
release process.

## Problem

LLM input is billed per token, and noisy context hurts both cost and answer quality.
Real-world context is full of duplicated paragraphs, boilerplate (signatures, page markers,
decorative rules), inconsistent whitespace, and CRLF noise. Sending it raw wastes tokens and
buries the signal. But blindly compressing context is dangerous: lossy summarization can drop
the very evidence the model needs.

`lcc`'s philosophy:

- Do not send **more** context than necessary.
- Do not send **less** context than sufficient.
- Optimize for **measurable** token savings **without destructive compression**.
- Prefer **deterministic** cleaning and traceable extraction before using any model.
- Preserve the original user intent and evidence provenance.

## What it does

Given raw text, a question, and a model name, `lcc` runs a deterministic pipeline:

```
raw text
  -> normalize        (line endings, whitespace, blank-line runs)
  -> remove boilerplate (conservative, whole-line matches only)
  -> deduplicate      (exact + conservative near-duplicate paragraphs)
  -> count tokens     (exact via tiktoken, or an honest approximation)
  -> build prompt     (evidence-aware template with explicit constraints)
  -> estimate cost    (configurable, editable pricing)
  -> emit report      (JSON) + optimized prompt (text)
```

Nothing is summarized or rewritten. Cleaning only removes safe, redundant, or
non-meaningful text, and every action is recorded in the report.

## MVP scope

**Currently supported (v0.1):**

- Read text from a file or stdin.
- Normalize whitespace, line endings, and blank-line runs (paragraph structure preserved).
- Remove obvious boilerplate lines with a conservative, whole-line match.
- Deduplicate exact and (optionally) conservative near-duplicate paragraphs.
- Count tokens **exactly** with `tiktoken` when available, with an **honest approximate
  fallback** that is clearly flagged in the report.
- Estimate input cost from **editable** model pricing.
- Build an evidence-aware prompt (role, question, context, constraints, response format,
  length guidance, anti-fabrication instructions).
- Emit a JSON report with before/after characters, tokens, compression ratio, savings %,
  cost before/after, cleaning steps, dedup metrics, and warnings.
- A `lcc` CLI with readable terminal output and graceful, non-zero-exit error handling.
- A deterministic **benchmark harness** (`lcc bench`) that runs the pipeline over committed
  fixtures and reports mechanical savings/preservation metrics (it does **not** measure LLM
  answer quality). See [Benchmarking](#benchmarking).

**Not yet supported (on the [roadmap](docs/roadmap.md), and intentionally *not* implemented
here):**

- Semantic retrieval / RAG, embeddings, vector stores (FAISS, Chroma, ...).
- Local LLM integration (Ollama, llama.cpp) or any model calls.
- Intent classification, evidence extraction, model routing, response verification.

If a feature is listed above as "not yet supported," it is **not** in the code. The docs
never describe a roadmap feature as if it were implemented.

## Install

Requires Python 3.11+.

```bash
# from the repository root
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # editable install with dev + tiktoken extras

# minimal runtime install (exact token counting via the optional tiktoken extra)
pip install ".[tiktoken]"
```

`tiktoken` is optional. Without it, `lcc` still runs and clearly marks token counts as
approximate. `lcc` **blocks runtime network access by default** and requires **no API key**:
it never calls the network during normal operation, including indirectly through `tiktoken`.
Exact token counting uses `tiktoken` only when the encoding assets are **locally available**;
if they would have to be downloaded, `lcc` blocks the fetch and falls back to a clearly
labelled approximate count (see [ADR 0008](docs/adr/0008-tokenizer-network-boundary.md)).

## Usage

```bash
# Optimize a file
lcc optimize examples/sample_input.txt \
  --question "What are the key points?" \
  --model gpt-4.1 \
  --max-input-tokens 6000 \
  --output optimized_prompt.md \
  --report report.json

# Read from stdin
cat examples/sample_input.txt | lcc optimize - \
  --question "Summarize the relevant information." \
  --output optimized_prompt.md \
  --report report.json

# Use editable defaults and pricing
lcc optimize examples/sample_input.txt -q "Summarize." \
  --config config/default.yaml --pricing config/pricing.yaml

lcc --version
lcc optimize --help
```

The optimized prompt is written to `--output` (or printed to stdout if omitted). The
human-readable summary and any warnings are printed to **stderr**, so stdout stays clean
for piping.

## Example output

Running the bundled `examples/sample_input.txt`:

```
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

Report excerpt (`report.json`):

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
  "cost": { "before": 0.000472, "after": 0.000256, "savings": 0.000216, "currency": "USD" },
  "dedup_metrics": { "paragraphs_before": 8, "paragraphs_after": 5,
                     "duplicates_removed": 2, "near_duplicates_removed": 1 },
  "warnings": []
}
```

## Architecture overview

Four deterministic libraries, composed by a single pipeline, behind a thin CLI:

| Module | Responsibility |
| --- | --- |
| `lcc.cleaning` | normalize, remove boilerplate, deduplicate (text in → text + metrics out) |
| `lcc.token_budget` | exact/approximate token counting + pricing and cost math |
| `lcc.prompt_builder` | render an evidence-aware prompt from a structured spec |
| `lcc.reporting` | assemble the `OptimizationReport` and serialize it to JSON |
| `lcc.pipeline` | orchestrate the above (the only module that composes them) |
| `lcc.cli` | Typer/Rich presentation and file/stdin IO |

The cleaning, token, prompt, and reporting modules contain **no network or LLM code** and
are fully deterministic. See [docs/architecture.md](docs/architecture.md) and the decision
records in [docs/adr/](docs/adr/).

## Benchmarking

`lcc` ships a deterministic, fixture-based benchmark harness (see
[ADR 0007](docs/adr/0007-deterministic-benchmark-harness.md) and
[benchmarks/README.md](benchmarks/README.md)):

```bash
lcc bench benchmarks/cases --output bench_report.json --markdown bench_report.md
```

It runs the optimization pipeline over the committed cases in `benchmarks/cases/` and reports
mechanical metrics — token savings, compression ratio, character reduction,
exact-vs-approximate token mode, literal marker preservation, and warnings — with explicit
per-case pass/fail thresholds and a versioned, deterministic JSON/Markdown report. The summary
prints to stderr; the exit code is non-zero if any case fails or the path is invalid.

- It measures **deterministic optimization behavior**, not final LLM answer quality.
- Literal marker preservation is only a **basic safety proxy**.
- Future phases may add semantic retrieval and human/LLM-assisted quality evaluation — **not
  now**.

## Roadmap

Phase 1 (this release) is the deterministic MVP, plus an early deterministic **benchmark
harness** (Phase 1.5; see [Benchmarking](#benchmarking)). Later phases add local semantic
retrieval, a local intent classifier, evidence extraction, model routing, response
verification, and a richer semantic-quality benchmark suite — each behind a clearly
separated boundary so the deterministic core stays intact. Full detail in
[docs/roadmap.md](docs/roadmap.md).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and
style, and [docs/adr/](docs/adr/) for the frozen design decisions.

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

Token counts are **exact only** when `tiktoken` recognizes the model **and** its encoding
assets are available from a local cache; otherwise they are **approximate** and the report
says so (with a warning explaining why). `lcc` never downloads tokenizer assets during normal
operation — if exact tokenization is unavailable offline, it falls back to approximate
counting and labels it (see [ADR 0008](docs/adr/0008-tokenizer-network-boundary.md)). Bundled
pricing in `config/pricing.yaml` and the built-in table are **editable EXAMPLES, not
guaranteed current prices** — always verify against your provider before relying on cost
figures.
