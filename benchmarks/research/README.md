# LCC effectiveness and cache-safety research

Measured study of `lcc` as a context transform: what each function saves, what it costs in
answer quality, and what it does to a warm prompt/KV cache. Every number below comes from a
run in this directory; nothing is estimated unless it is labelled as a projection.

Reproduce with:

```bash
export TIKTOKEN_CACHE_DIR="$HOME/.cache/tiktoken"   # see Finding 1
python3 make_corpora.py     # deterministic corpora -> corpora/
python3 run_matrix.py       # 3 corpora x 13 arms   -> results/matrix.jsonl
python3 run_cache.py        # cache-safety suite    -> results/cache_safety.json
python3 make_payloads.py    # agent A/B payloads    -> payloads/
python3 score_agents.py     # agent A/B scoring     -> results/agent_ab.json
```

## Setup

Three deterministic corpora shaped like a real agent dossier: a stable reference prefix, a
cache-break marker, then a volatile tail of tool output, logs and chatter, with five
ground-truth facts and two distractors seeded inside the tail.

| corpus | blocks | chars | tokens (o200k) |
|---|---|---|---|
| small  |  35 |  4 550 |  1 092 |
| medium | 147 | 18 901 |  4 399 |
| large  | 387 | 49 608 | 11 483 |

Thirteen arms: a raw no-LCC baseline, four `optimize` variants, `prepare`, six `compact`
variants, `intake` and a `compact | optimize` chain. Token counts are exact tiktoken
(`o200k_base`) counts of the bytes the downstream model would actually receive. Recall is the
share of the five ground-truth figures that survive the transform, verified in the emitted
bytes.

---

## Finding 1 — token accounting silently degrades to a heuristic (configuration gap)

On a machine whose tiktoken encoding assets are not already cached, `lcc` blocks the
tokenizer download (ADR 0006/0008, correctly — it stays offline) and falls back to a
heuristic estimator. The count is then labelled `approximate`, but the number still looks
authoritative in the CLI summary.

Same input, same objective, cold vs warm tokenizer cache:

| condition | tokens reported | method | report field |
|---|---|---|---|
| cold cache | 2 270 | approximate | `token_count_method: approximate` |
| warm cache | 2 409 | exact | `token_count_method: exact` |

A **139-token shortfall (5.8 % low) on a routine pass**, and it is the number a cost or cache
decision gets built from. It disappears only after something else populates the encoding cache; the first
warm-up happens outside the offline guard, so the transition is silent.

**Action:** pin the cache — `export TIKTOKEN_CACHE_DIR="$HOME/.cache/tiktoken"` — and treat
`token_count_method: approximate` in any report as a stop sign, not a footnote.

---

## Finding 2 — the mechanical arms drop evidence; the Jev arm does not

Fact recall measured in the emitted bytes, all three scales:

| arm | small | medium | large | recall |
|---|---|---|---|---|
| `baseline_raw` | 0.0 % | 0.0 % | 0.0 % | 1.00 |
| `optimize_default` | −13.2 % | −3.5 % | −1.5 % | 1.00 |
| `optimize_claude_xml` | −20.2 % | −5.2 % | −2.1 % | 1.00 |
| `prepare_default` | 66.9 % | 79.4 % | 81.5 % | **0.60** |
| `compact_mechanical` | 67.0 % | 74.4 % | 75.1 % | **0.60** |
| `compact_jev` | 34.2 % | 62.6 % | 68.3 % | **1.00** |
| `compact_jev --prefix-marker` | 36.6 % | 61.1 % | 68.0 % | **1.00** |
| `compact_jev --trim-head-chars 0` | 46.0 % | 66.5 % | 69.8 % | **0.60–0.80** |
| `compact_jev --preserve-tail 6` | 25.2 % | 57.3 % | 67.5 % | 1.00 |
| `intake_default` | −25.6 % | −6.5 % | −2.6 % | 1.00 |
| `chain_compact_optimize` | 13.6 % | 57.4 % | 66.4 % | 1.00 |

Three things worth stating plainly.

**`optimize` and `intake` are not compressors.** They add prompt scaffolding, so they grow
the context at every scale (−13.2 % to −1.5 % for `optimize`, −25.6 % to −2.6 % for
`intake`). They clean and structure; they do not reduce. Budgeting for them as if they save
tokens is a mistake.

**Mechanical scoring loses the answers.** `prepare` and `compact --provider mechanical` cut
the most bytes (67–82 %) and drop two of the five facts every time. The dropped facts have
weak lexical overlap with the objective — a chair count and a re-typing duration against a
question about mobile conversion — so a lexical scorer never sees them as relevant. Verified
in the emitted output, not just in the metric: the `3 chairs` and `4 minutes` strings are
gone from the file.

**Trimming is the safety net, not a compromise.** `--trim-head-chars 0` looks like the strict
and therefore safer setting. It is the opposite: it removes the middle gear that keeps a
bounded head of borderline-scored blocks, and recall falls from 1.00 to 0.60–0.80. The
default trim behaviour is what protects near-miss blocks.

---

## Finding 3 — `--provider auto` fails unsafe when Jev is unreachable

Same corpus, same objective, Jev made unreachable:

| configuration | `provider_used` | `degraded` | blocks dropped | facts survived | reduction |
|---|---|---|---|---|---|
| Jev reachable | `jev` | `false` | 17 | **5 / 5** | 41.8 % |
| Jev unreachable, `--provider auto` (default) | `mechanical` | **`false`** | 27 | **3 / 5** | 73.0 % |
| Jev unreachable, `--provider jev` | `degraded` | `true` | 0 | **5 / 5** | 0 % |

`--provider jev` behaves exactly as the fail-safe contract describes: every block kept,
`degraded: true`, honest warning. The default `auto` does not fail safe — it silently swaps
in the mechanical scorer, which Finding 2 shows destroys evidence, and still reports
`degraded: false`. The only signal is a warning string in the report.

**Action:** call `--provider jev` explicitly and monitor the `degraded` flag. Prefer the
explicit provider wherever a missing key is possible, which is everywhere.

---

## Finding 4 — the Jev arm was not byte-reproducible, and that is a cache invalidation event

> Fixed in Finding 7. The measurements below are the pre-fix state, kept because they are the
> evidence the fix was built on. Both stability metrics now read `True`.

The cache document promised that sticky decisions make runs over unchanged history
byte-identical. Measured, with the default marker:

| arm | distinct outputs over 5 identical runs |
|---|---|
| `optimize` (default / claude_xml) | 1 / 5 — stable |
| `prepare` | 1 / 5 — stable |
| `compact --provider mechanical` | 1 / 5 — stable |
| `intake` | 1 / 5 — stable |
| **`compact --provider jev`** | **5 / 5 — every run differs** |
| `compact --provider jev --no-marker` | 2 / 5 |
| **`compact --provider jev --no-marker --decisions-cache`** | **1 / 5 — stable** |

Root cause, from the diff: the drop marker embeds the score range of the dropped blocks, and
those scores come from live model judgment.

```
- [lcc-compact: dropped 8 blocks (796 chars, scores 0.03-0.04 < 0.40)]
+ [lcc-compact: dropped 8 blocks (796 chars, scores 0.03-0.03 < 0.40)]
```

The keep/drop decisions were identical; only the annotation drifted. On the small corpus the
first divergence sits at byte 2 485 of 2 718 — **61 tokens from the end of a 725-token
context are invalidated on a run that dropped 373**. The `prefix_sha256` field stays
identical throughout, so a monitor watching only the prefix reports "cache valid" while
`output_sha256` moves.

The good news is that the two flags together fix it. With `--no-marker --decisions-cache`,
five sequential runs produced one distinct hash, `calls: 0` from run 2, and full decision
reuse. Without a decisions cache the output never converges. With one, the cold run still
differs from every later run — the first warm run is always a cache epoch.

**Action for live sessions:** `--no-marker --decisions-cache <path>`, and warm the decisions
cache once before the first model call you intend to cache against.

---

## Finding 5 — a mid-prefix pass does not pay for itself below ~12–20 reuses

Applying the cost model from `docs/CACHE_ALIGNMENT.md` (read 0.10x, write 1.25x) to the
measured mutation offsets:

| corpus | dropped | invalidated | penalty / saving | break-even reuse |
|---|---|---|---|---|
| small  |  373 |  659 | 20.3x | ~20 |
| medium | 2 752 | 3 014 | 12.6x | ~13 |
| large  | 7 849 | 8 045 | 11.8x | ~12 |

Net read-token-equivalents at 1x, 5x and 20x reuse:

| corpus | 1x | 5x | 20x |
|---|---|---|---|
| small  | −721 | −571 | −12 |
| medium | −3 191 | −2 090 | +2 038 |
| large  | −8 467 | −5 327 | +6 446 |

Negative is a net loss. **At one to five reuses, breaking the prefix costs 12–20 read
equivalents for every one it saves.** The pass only turns profitable around a dozen reuses,
which is the concrete form of the "wait for a cache epoch" rule.

Prefix protection behaved correctly and is not cosmetic: with `--prefix-marker`,
`prefix_untouched: true` on all three scales, and on the large corpus protection moved the
first mutation from offset 13 418 to 13 592 — it actually stopped a mutation that would
otherwise have landed early.

The `worth_it` gate also works: `--min-reduction 0.8` flipped `worth_it` to `false` and
emitted `low_reduction: removed 41.8% of chars (< 80% target)`. Append-only growth is
correct too — appending one block kept the previous output as a byte-stable prefix, re-scored
only the new block (`calls: 1`) and added 15 tokens.

---

## Finding 6 — real agent A/B: quality unchanged, context down 61 %, total prompt tokens down 9 %

Nine subagents per run, three arms of three samples, identical harness and task; the only
variable is the context block. Run twice, independently. Token usage read from provider-reported
records (Hermes `state.db`), not estimated.

| arm | context loaded (exact) | mean total prompt tokens | mean fresh input | fact recall | fabricated |
|---|---|---|---|---|---|
| raw (no LCC) | 5 524 | 38 690 | 11 724 | 5 / 5, 3 of 3 | 0 |
| `compact --provider jev` | **2 144** (−61.2 %) | **35 169** (−9.1 %) | 11 105 | 5 / 5, 3 of 3 | 0 |
| `optimize --template claude_xml` | 4 770 | 45 502 | 14 099 | 5 / 5, 3 of 3 | 0 |

Reproducibility across the two independent runs:

| run | raw total prompt | Jev total prompt | delta |
|---|---|---|---|
| 1 | 38 689 | 35 235 | −8.9 % |
| 2 | 38 690 | 35 169 | −9.1 % |

**A metric warning, and a correction to an earlier version of this study.** The obvious metric,
fresh `input_tokens` (the uncached part, billed at full price), is *not* stable here: run 1 read
−43.2 % on it and run 2 read −5.3 % on the same setup, because prompt caching moves tokens
between the fresh and cached buckets from run to run. Total prompt tokens (`input_tokens +
cache_read_tokens`) is caching-agnostic and agrees to 0.2 points across both runs. **Quote −9 %,
not −43 %.** The earlier number in this study was a metric artifact.

**Why 61 % of the context becomes 9 % of the prompt.** The subagent harness carries a fixed floor
of roughly 14 000 tokens per call against a 5 524-token context, so the context is a minority of
what the model actually processes. LCC's saving is bounded by the context's share of the prompt,
not by the compression ratio. The same 61 % reduction inside a 40 000-token context would
dominate the bill, but that is arithmetic extrapolation, **not a measurement**.

**Quality did not move.** All eighteen agents across both runs returned all five figures with no
fabrication in any arm, including the raw arm. On this task LCC's value is cost and context
headroom, not accuracy. The `optimize` arm is the negative control: it grew the context and came
out ~18 % *worse* than raw on total prompt tokens.

---

## Finding 7 — hardening round: the six fixes, and what they changed

The findings above drove six changes to `lcc`. Each was re-measured after landing.

| # | Fix | Before | After |
|---|---|---|---|
| 1 | `--require-exact-tokens` (exit 3) plus an `approximate_token_count` warning naming the fix | estimates reported silently | estimates are labelled and can be refused |
| 2 | `auto` reports its fallback honestly | `degraded: false` on a mechanical fallback | `degraded: true`, `degradation_reason`, `semantic_guarantee: none` |
| 3 | `--trim-head-chars 0` warns about the missing middle gear | footgun documented only in prose | warning emitted on every such run |
| 4 | Drop marker carries no scorer values; `--marker-scores` opts back in | 5 distinct outputs over 5 identical runs | **1 distinct output**, no flags needed |
| 5 | Report states `invalidated_tokens` and `break_even_reuses`, with a `cache_epoch_risk` warning | the cost model lived only in a doc | the pass states its own cost and payback |
| 6 | README and `CACHE_ALIGNMENT.md` corrected | three claims contradicted by measurement | claims match the measurements and cite the study |

### The marker drift had two causes, not one

Live scorer values wobble between calls, and the marker embedded them, so every run rewrote the
emitted bytes. That was the visible half.

The second half only appeared in the cold-to-warm transition, and reproduction pinned it to a
single block. `blk_0026` scored **0.04** on the cold run and **0.03** on the warm run, from the
same cache. The cause: that content appears four times in the corpus (indices 26, 28, 30, 32),
the decisions cache is keyed on `(objective, block content)`, and a cold run scored each copy
independently while a warm run applied whichever score was written last. Identical content was
getting different judgments within a single run, which the content-addressed cache cannot
represent. A run now decides each distinct content once and applies that judgment to every
copy.

### Re-measured after the fixes

| metric | before | after |
|---|---|---|
| `warm_identical` (cold vs warm, decisions cache) | False | **True** (all 3 corpora) |
| `determinism_no_cache` (two identical runs, no cache) | False | **True** (all 3 corpora) |
| `compact_jev` reduction, medium | 62.6 % | **63.9 %** |
| `compact_mechanical` reduction, medium | 74.4 % | **78.6 %** |
| `compact_jev` reduction, large | 68.3 % | **68.8 %** |
| ground-truth recall, `compact_jev` | 1.00 | **1.00** (unchanged) |
| break-even reuses (medium) | 12.59 | 12.33 |

The stability metrics are the point: both flipped from False to True, and the Jev arm kept its
perfect recall. Reductions improved slightly everywhere because the marker text shrank, which
is a side effect rather than the goal.

Test suite: 323 passed / 1 failed before, **336 passed / 1 failed** after, 13 new tests. The one
failure is pre-existing on `main` (`test_bundled_suite_passes_with_tiktoken`, a boilerplate
marker surviving in the bundled benchmark case) and is unrelated to these changes — it fails
identically on a clean checkout.

## Limitations

- The corpora are synthetic and shaped by hand. Fact placement inside the volatile tail is a
  deliberate choice, so the recall numbers describe this shape of dossier, not every dossier.
  The failure mechanism (lexical scoring missing topically-unrelated evidence) is what
  generalises, and it is reproducible from `run_matrix.py`.
- The agent A/B is three samples per arm on one corpus scale. Token deltas are consistent and
  the direction is unambiguous, but treat the exact percentages as one measurement, not a
  general constant.
- The corpus ground-truth facts carry literal `GROUND TRUTH A:`-style labels. Citing them back
  is model behaviour rather than a systematic arm advantage: run 1 saw it in the
  `compact --provider jev` answers, run 2 in the `optimize` answers, and the raw arm was clean
  in both. All arms scored 5/5 in both runs either way. Labelled corpora are still a confound
  worth removing before publishing these numbers as general evidence.
- Scores are floating-point model judgments. Finding 4 does not claim decisions are stable in
  general; it claims the emitted bytes are not, and that the two flags together make them so
  across five consecutive runs.
- Cost maths uses the factors published in `docs/CACHE_ALIGNMENT.md`. Substitute your
  provider's real read/write multipliers before acting on the break-even figures.
- The large-corpus agent run and the 11.5k-token scale of the agent A/B were not executed;
  the extrapolation to larger dossiers is a projection, not a measurement.
