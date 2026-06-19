# Evaluation

How to measure whether `lcc` is actually helping — on both **cost** and **quality**.

## Measuring token savings

`lcc` reports token counts for the original input and the cleaned context, using the same
counter and model for both so the comparison is fair. The report records whether counting
was `exact` (tiktoken recognized the model) or `approximate`.

### Compression ratio

```
compression_ratio = optimized_token_count / original_token_count
```

Lower is more compression. A ratio of `0.54` means the cleaned context is 54% of the
original token count. (When the original is empty, the ratio is defined as `1.0`.)

### Token savings percentage

```
token_savings_percent = (1 - compression_ratio) * 100
                       = (1 - optimized_token_count / original_token_count) * 100
```

A value of `45.8` means 45.8% of the input tokens were removed.

### Cost savings

```
estimated_input_cost = tokens * input_price_per_million / 1_000_000
estimated_cost_savings = cost_before - cost_after
```

Cost is omitted (and a warning is emitted) when the model has no pricing entry. Pricing is
**editable example data**, not guaranteed current — treat cost figures as estimates.

> Note: the report's `original`/`optimized` figures measure the **context**. The full
> rendered prompt (context + question + template) is reported separately as
> `prompt_token_count` so you can see the real payload size you will send.

## Measuring quality preservation

Token savings are only useful if the answer quality holds. Because the MVP does **not** call
an LLM, quality must be measured with a downstream model you control:

1. Pick a fixed set of (document, question, reference-answer) cases.
2. For each case, generate an answer twice: once with the **raw** context, once with the
   **`lcc` optimized** prompt — using the same downstream model and decoding settings.
3. Score both answers against the reference (exact match, F1, rubric score, or an
   LLM-as-judge rubric). Compare quality side by side with the token/cost savings.

Quality should be **preserved** (statistically indistinguishable) while tokens drop. If
quality falls, the cleaning was too aggressive for that data — tune or disable steps
(`--no-near-dedup`, `--no-boilerplate`, a higher `similarity_threshold`).

## Unsupported claim rate (future concept)

A planned Phase 6 metric (not implemented today). The idea: after the downstream model
answers, check each factual claim in the answer against the provided evidence and compute

```
unsupported_claim_rate = unsupported_claims / total_claims
```

A good context optimizer keeps this rate flat or lower than the raw-context baseline: it
should never *increase* hallucination by removing needed evidence. This requires a
verification step and is on the [roadmap](roadmap.md), not in the MVP.

## Suggested benchmark examples

- **Duplicated reports:** status notes or logs with repeated paragraphs → expect high
  savings with no quality loss.
- **Email threads:** quoted replies, signatures, and disclaimers → tests boilerplate removal.
- **Long documentation:** a question answerable from a few sections → tests that needed
  evidence survives (quality must hold).
- **Already-clean text:** a tight, unique document → expect near-zero savings and **zero**
  quality change (a guard against over-cleaning).

A reproducible **deterministic** harness for these now ships with `lcc` (Phase 1.5); see
below. Quality-preservation measurement (which needs a downstream model you control) remains
future work.

## Deterministic benchmark harness

`lcc bench` runs the optimization pipeline over committed fixtures and reports **mechanical**
optimization metrics. It calls no model or network and makes **no claim about answer
quality**. See [ADR 0007](adr/0007-deterministic-benchmark-harness.md) and
[../benchmarks/README.md](../benchmarks/README.md).

```bash
lcc bench benchmarks/cases --output bench_report.json --markdown bench_report.md
```

### How cases work

Each case is a directory under `benchmarks/cases/<id>/` with a `case.yaml` (metadata,
`required_markers`, `forbidden_markers`, and `expectations`) and an `input.txt` (raw context).
The harness feeds `input.txt` and the case `question` through the same pipeline as
`lcc optimize`, then scores the result against the case's explicit thresholds.

### Formulas

```
char_reduction_percent = (1 - optimized_char_count / original_char_count) * 100
compression_ratio      = optimized_token_count / original_token_count
token_savings_percent  = (1 - compression_ratio) * 100
required_marker_recall = required_markers_found / required_markers_total   (1.0 if none)
```

(When the original is empty, `char_reduction_percent` is `0.0` and `compression_ratio` is
`1.0`, matching the optimization report.)

### What the metrics mean

- **token_savings_percent / compression_ratio / char_reduction_percent** — how much the
  deterministic cleaning shrank the context.
- **token_count_mode** — `exact` when `tiktoken` recognized the model, else `approximate`
  (ADR 0005). Exact-mode cases fail if counting falls back to approximate.
- **required_marker_recall** — the fraction of required literal evidence markers still present
  in the optimized prompt (a basic preservation proxy).
- **forbidden_markers_found** — forbidden literal markers (e.g. boilerplate lines) that
  survived; these should be empty.
- **warnings** — pass-through of the pipeline's honesty warnings (approximate counts, missing
  pricing, exceeding `max_input_tokens`).
- **passed / failure_reasons** — whether every threshold held, with explicit reasons when not.

### What the metrics do NOT prove

They do **not** measure whether a downstream model's answer is correct, complete, or
unchanged. Literal marker preservation only checks that specific substrings survived; it is a
safety proxy, not a semantic guarantee. Answer-quality evaluation is the manual method in
[Measuring quality preservation](#measuring-quality-preservation) above and is roadmap work,
not something this harness performs.

### Adding a benchmark case

Create `benchmarks/cases/<id>/{case.yaml,input.txt}`, pick `required_markers` that are
specific evidence phrases and `forbidden_markers` that are removable boilerplate lines, set
realistic min/max ranges (run the suite and leave headroom), and keep the input small. The
full field reference is in [benchmarks/README.md](../benchmarks/README.md).
