# Benchmarks

Deterministic, fixture-based benchmarks for `lcc` (see
[ADR 0007](../docs/adr/0007-deterministic-benchmark-harness.md) and
[ADR 0010](../docs/adr/0010-deterministic-first-preparation-model-assistance.md)).

These benchmarks measure **mechanical context-optimization behavior** — how many tokens and
characters deterministic `optimize` or `prepare` workflows remove, whether required literal
markers survive, whether forbidden literal markers are absent, whether prepare selection
applied, and whether token counting was exact or approximate. They make **no model or network
calls**, and they **do not measure final LLM answer quality**. Literal marker preservation is
only a basic safety proxy, not semantic evidence validation. `workflow: prepare` mirrors the
implemented deterministic prepare boundary: inspect first, branch only on
`recommendation.action`, optionally select literal source chunks with lexical/mechanical
signals, then run safe optimization. It does not summarize, rewrite, or paraphrase source
content. Semantic retrieval, semantic marker matching, paraphrase detection, and
human/LLM-assisted quality evaluation are roadmap items, not implemented here.

## Run

```bash
lcc bench benchmarks/cases --output bench_report.json --markdown bench_report.md
```

- The JSON report is written to `--output` (or printed to stdout if omitted).
- A human-readable Markdown report is written to `--markdown` (optional), including the
  same mechanical benchmark summary plus prepare action and lexical-selection state when
  `workflow: prepare` is used.
- A concise summary (total / passed / failed / average savings) is printed to stderr.
- The exit code is `0` when every case passes its thresholds, non-zero otherwise (or if the
  path is invalid).

> Exact-mode cases (`allow_approximate_token_count: false`) require `tiktoken`
> (`pip install ".[tiktoken]"`) **and** its encoding assets to be cached locally — `lcc`
> blocks runtime network access by default and never downloads them (ADR 0008). Without
> tiktoken, or when the assets are unavailable offline, counting falls back to approximate and
> those cases fail honestly rather than report an approximation as exact (ADR 0005). To run
> exact-mode cases offline, pre-cache the tokenizer once (for example, by setting
> `TIKTOKEN_CACHE_DIR` to a populated directory).

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
| `workflow` | `optimize` (default) or `prepare`. Prepare cases run inspection, branch only on `recommendation.action`, apply deterministic lexical selection for optimize actions, then run safe optimization. |
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
| `expected_prepare_action` | `null` | For prepare cases, fail if inspection returns a different recommendation action. |
| `expected_selection_applied` | `null` | For prepare cases, fail if lexical selection applied state differs. |
| `min_selected_chunk_count` | `null` | For prepare cases, fail if fewer chunks are selected. |
| `max_selected_chunk_count` | `null` | For prepare cases, fail if more chunks are selected. |
| `min_skipped_duplicate_chunk_count` | `0` | For prepare cases, fail if fewer duplicate matching chunks are skipped. |

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

- **Do:** show deterministic token/character reduction, that required literal markers survived
  by exact substring match, that forbidden literal markers were removed, whether prepare
  selection applied, and whether counting was exact.
- **Do not:** prove that a downstream model's answer is correct, complete, or unchanged. That
  is semantic evaluation, which this harness deliberately does not perform. They also do not
  perform semantic selection, embeddings, local-model calls, remote LLM calls, network access,
  summarization, rewriting, or paraphrasing (ADR 0010).
