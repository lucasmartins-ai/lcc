# Evaluation

How to measure whether `lcc` is actually helping on cost, deterministic behavior, and any
downstream quality checks you run outside `lcc`.

## Measuring token savings

`lcc` reports token counts for the original input and the cleaned context, using the same
counter and model for both so the comparison is fair. The report records whether counting
was `exact` (tiktoken recognized the model **and** its encoding assets were available from a
local cache) or `approximate`. `lcc` never downloads tokenizer assets during normal operation:
if exact tokenization is unavailable offline, it falls back to approximate counting and labels
it, with a warning explaining why (see [ADR 0008](adr/0008-tokenizer-network-boundary.md)).

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

### Previewing savings with `lcc inspect`

To estimate savings **before** committing to optimization, run `lcc inspect INPUT`. It reports
the input's token, structure, duplication, and cost profile and a `safe_cleanup_projection`
(`projected_token_savings_percent`, `projected_character_savings_percent`) of what the same safe
cleaning would remove — **without** building a prompt or calling anything. The projection is
explicitly labelled as an estimate of what `optimize` would do, not a completed optimization,
and it makes **no** claim about answer quality (ADR 0009). Token counts carry the same
exact-vs-approximate honesty as the optimization report.

The inspection report also includes a deterministic `recommendation`:

- `skip` when the input is small or projected savings are low;
- `optimize_safe` when deterministic cleanup has a clear payoff;
- `optimize_with_flags` when cleanup looks useful but extra configuration, such as pricing,
  is needed before relying on cost output;
- `manual_review` when the projected cleaned context is still very large.

Use `lcc inspect INPUT --summary compact` for a short terminal summary with the decision,
main reason, projected token/cost savings when pricing is available, and the next suggested
command. The full JSON report remains available on stdout or via `--report`.

### Preparing deterministically with `lcc prepare`

`lcc prepare` is deterministic prepare orchestration, not model assistance. It runs the same
diagnostic inspection first, branches only on `recommendation.action`, and when optimization
is recommended it may apply question-aware lexical chunk selection before the existing safe
optimization path. The selector assembles literal source chunks using lexical/mechanical
signals such as keyword overlap, heading matches, rare-term matches, proximity to matched
headings, and exact duplicate markers. It does not summarize, rewrite, paraphrase, embed, call
a model, semantically rank source content, or access the network. See
[ADR 0010](adr/0010-deterministic-first-preparation-model-assistance.md).

## Measuring quality preservation

Token savings are only useful if the answer quality holds. Because `lcc` does **not** call an
LLM, quality must be measured outside `lcc` with a downstream model you control:

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

## Suggested downstream evaluation examples

- **Duplicated reports:** status notes or logs with repeated paragraphs → expect high
  savings, then check answer quality outside `lcc` if needed.
- **Email threads:** quoted replies, signatures, and disclaimers → tests boilerplate removal.
- **Long documentation:** a question answerable from a few sections → in `lcc bench`, test only
  that required literal markers survive; measure answer quality separately.
- **Already-clean text:** a tight, unique document → expect near-zero savings and **zero**
  quality change when you run an external downstream-model comparison.

A reproducible **deterministic** harness for mechanical token/marker checks now ships with
`lcc` (Phase 1.5); see below. Automated quality-preservation measurement inside `lcc` remains
future work because it needs a downstream model or evaluator outside the deterministic harness.

## Deterministic benchmark harness

`lcc bench` runs deterministic `optimize` or `prepare` workflows over committed fixtures and
reports **mechanical metrics**. It calls no model or network and is **not LLM answer quality**
evaluation. See [ADR 0007](adr/0007-deterministic-benchmark-harness.md),
[ADR 0010](adr/0010-deterministic-first-preparation-model-assistance.md), and
[../benchmarks/README.md](../benchmarks/README.md).

```bash
lcc bench benchmarks/cases --output bench_report.json --markdown bench_report.md
```

### How cases work

Each case is a directory under `benchmarks/cases/<id>/` with a `case.yaml` (metadata,
`required_markers`, `forbidden_markers`, and `expectations`) and an `input.txt` (raw context).
The harness feeds `input.txt` and the case `question` through either `lcc optimize` behavior
or the implemented deterministic `prepare` flow, then scores the result against the case's
explicit mechanical thresholds.

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
- **token_count_mode** — `exact` when `tiktoken` recognized the model and its encoding assets
  were available locally, else `approximate` (ADR 0005, ADR 0008). Exact-mode cases fail
  honestly if counting falls back to approximate, so they **may require cached tokenizer
  assets to pass as exact** — `lcc` will not download them.
- **required_marker_recall** — the fraction of required literal evidence markers still present
  in the optimized prompt (a basic preservation proxy).
- **forbidden_markers_found** — forbidden literal markers (e.g. boilerplate lines) that
  survived; these should be empty.
- **warnings** — pass-through of the pipeline's honesty warnings (approximate counts, missing
  pricing, exceeding `max_input_tokens`).
- **prepare action / lexical-selection state** — for `workflow: prepare`, the inspection
  action, whether lexical selection applied, selected chunk counts and IDs, reason codes, and
  skipped exact duplicate chunk IDs.
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
