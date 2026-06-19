# Benchmarks

Deterministic, fixture-based benchmarks for `lcc` (see
[ADR 0007](../docs/adr/0007-deterministic-benchmark-harness.md)).

These benchmarks measure **mechanical context-optimization behavior** — how many tokens and
characters the deterministic pipeline removes, whether required evidence markers survive, and
whether token counting was exact or approximate. They make **no model or network calls**, and
they **do not measure final LLM answer quality**. Literal marker preservation is only a basic
safety proxy. Semantic retrieval and human/LLM-assisted quality evaluation are roadmap items,
not implemented here.

## Run

```bash
lcc bench benchmarks/cases --output bench_report.json --markdown bench_report.md
```

- The JSON report is written to `--output` (or printed to stdout if omitted).
- A human-readable Markdown report is written to `--markdown` (optional).
- A concise summary (total / passed / failed / average savings) is printed to stderr.
- The exit code is `0` when every case passes its thresholds, non-zero otherwise (or if the
  path is invalid).

> Exact-mode cases (`allow_approximate_token_count: false`) require `tiktoken`
> (`pip install ".[tiktoken]"`). Without it, counting falls back to approximate and those
> cases fail honestly rather than report an approximation as exact (ADR 0005).

## Layout

```
benchmarks/
  README.md
  cases/
    <case_id>/
      case.yaml     # metadata, markers, and pass/fail thresholds
      input.txt     # the raw context fed to the pipeline
```

## Case format (`case.yaml`)

| Field | Meaning |
| --- | --- |
| `id` | Stable identifier; also the report sort key. |
| `description` | One line describing what the case exercises. |
| `question` | The question handed to the prompt builder. |
| `model` | Model name for token counting (default `gpt-4.1`). |
| `max_input_tokens` | Optional budget; over it the pipeline emits a warning. |
| `compression_level` | Cleaning preset. Only `safe` exists today (the pipeline defaults). |
| `required_markers` | Literal substrings that MUST remain in the optimized prompt. |
| `forbidden_markers` | Literal substrings that should be gone (e.g. boilerplate lines). |
| `expectations` | Per-case pass/fail thresholds (below). |

### Expectations

| Key | Default | Meaning |
| --- | --- | --- |
| `min_token_savings_percent` | `0.0` | Fail if savings drop below this. |
| `max_token_savings_percent` | `100.0` | Fail if savings exceed this (guards over-cleaning). |
| `min_required_marker_recall` | `1.0` | Fail if fewer required markers survive. |
| `allow_approximate_token_count` | `false` | If `false`, approximate counting fails the case. |
| `max_forbidden_markers_found` | `0` | Fail if more forbidden markers survive than this. |

## Adding a case

1. Create `benchmarks/cases/<your_id>/` with a `case.yaml` and an `input.txt`.
2. Keep `input.txt` small so the suite stays fast.
3. Choose `required_markers` that are specific evidence phrases in your input, and
   `forbidden_markers` that are removable boilerplate lines (mobile signatures, page markers,
   `On <date>, <name> wrote:` headers, long decorative rules). Duplicate paragraph content is
   **not** a good forbidden marker, because deduplication keeps the first copy.
4. Set realistic ranges: run `lcc bench benchmarks/cases` and tune the thresholds to the
   observed numbers, leaving headroom so the case stays robust across exact/approximate
   counting.
5. Add or extend a test in `tests/test_benchmarking.py` if the case exercises new behavior.

## What the metrics do and do not prove

- **Do:** show deterministic token/character reduction, that required literal markers
  survived, that forbidden literal markers were removed, and whether counting was exact.
- **Do not:** prove that a downstream model's answer is correct, complete, or unchanged. That
  is semantic evaluation, which this harness deliberately does not perform.
