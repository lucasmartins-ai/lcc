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
python3 adversarial_cases.py && python3 run_adversarial.py jev
python3 stress_edges.py     # xl scale + edge cases -> results/stress.json
python3 run_cache_patterns.py   # where-to-compact economics -> results/cache_patterns.json
python3 show_losses.py      # which categorized item each arm drops
```

## How to audit this

Every number below is produced by a script in this directory, and every script is re-runnable
against the committed corpora. If you want to check a claim rather than trust it:

| what to check | how |
|---|---|
| the study's numbers | run `run_matrix.py`, diff `results/matrix.jsonl` against your run |
| the corpora are what the generator says | `pytest tests/test_benchmark_categories.py` asserts it, item by item |
| the ground truth actually measures something | that test also asserts every marker matches its own block, and every item is above the 80-char scoring floor |
| a claim about quality, not tokens | `run_adversarial.py` prints one row per hazard with the assertions it checked |
| the cache claims | `run_cache.py` (cold vs warm, determinism, prefix protection, append-only, break-even) and `run_cache_patterns.py` (whole-context vs per-payload) |
| what a pass actually decided | `lcc explain results/....json --source corpora/....md` reads the report and shows the reason behind every block |
| which categorized item an arm loses | `show_losses.py` |

Two habits keep this honest, and both were learned the hard way here. **A metric that only
reports a pass/fail hides which kind of failure occurred**, so recall is reported per
information category, and `show_losses.py` names the item. **A benchmark can be wrong instead of
the thing it measures**, so before concluding that a component failed, check that the corpus's
objective actually requires the item you declared as ground truth (Finding 11).

### What each script proves

| script | question it answers |
|---|---|
| `make_corpora.py` | builds four deterministic corpora with categorized ground truth, byte-identical every run |
| `run_matrix.py` | what each of thirteen transforms does to tokens, and which categories it keeps, across four scales |
| `run_cache.py` | whether the output is byte-stable, whether a warm run is free, where a pass mutates the prefix, and whether it pays off |
| `run_cache_patterns.py` | whether compacting the session or compacting each payload costs less, under a cache price model |
| `run_adversarial.py` | whether twenty specific semantic hazards survive compaction, with a trap block in every case |
| `stress_edges.py` | whether behaviour holds at four times the largest curated corpus, and on eight pathological inputs |
| `show_losses.py` | which categorized item each arm actually drops, by marker |
| `make_payloads.py` + `score_agents.py` | what real agents answer, and what their billed tokens were |

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

## Finding 8 — adversarial semantic-safety suite (Etapa 1)

The first suite measured fact recall on a corpus whose evidence blocks carried literal
`GROUND TRUTH A:` labels: easy to find and easy to keep. The adversarial suite in
`adversarial_cases.py` probes the ways a scorer that reads relevance can still destroy the
answer, with twenty cases covering negation, double negation, contradiction, temporal
supersession, source authority, cross-block dependency (qualifier and causal), numerical
precision, units, prompt injection, quoted instructions, five structured payloads, multilingual
and Unicode content, and the two size extremes.

Every case carries a **trap block**: text that mirrors the question's vocabulary while carrying
no evidence at all. Without it the suite is vacuous, because a lexical scorer keeps anything
that shares words with the question. `test_trap_blocks_share_vocabulary_with_the_question` in the
repo suite enforces that every case keeps its trap meaningful.

Baseline, measured with `python3 run_adversarial.py <provider>`:

| provider | cases passing | known failures |
|---|---|---|
| `jev` | **20 / 20** | none |
| `mechanical` | 17 / 20 | `dependency_causal`, `quoted_instruction`, `multilingual` |

The three deterministic failures are the suite proving it discriminates rather than passing
everything. All three are the same underlying limitation: a lexical scorer cannot connect a
cause to its effect, cannot tell a quotation from noise, and shares no tokens with evidence
written in another language. They are recorded as strict `xfail` markers in
`tests/test_adversarial_compaction.py`, so fixing one is a visible act and breaking one of the
seventeen working cases fails the suite.

What the suite found about the current Jev path: **no semantic-safety failure on these twenty
hazards.** In particular the prompt-injection case passes on both counts, with the injected
instruction dropped and the evidence kept. That is the baseline Etapa 2 has to hold, and the
gate any scoring change now has to clear.

### Escalation: the suite was pushed until it broke, and it did not

A suite that passes at one copy of its noise has not been tested. Real dossiers are an order of
magnitude larger, and size is what forces a scorer to choose, so `build_corpus(case, pressure)`
multiplies the filler and the trap while keeping the case assertions fixed.

| pressure | corpus | cases passing | mean reduction | mean blocks dropped |
|---|---|---|---|---|
| 1 | ~2 k chars | 20 / 20 | 56.0 % | 9.0 |
| 3 | ~6 k chars | 20 / 20 | 61.8 % | 25.4 |
| 6 | ~14 k chars | 20 / 20 | **64.0 %** (max 86.2 %) | **50.2** (max 60) |

At the hardest factor the compactor drops fifty blocks out of sixty and still keeps every
critical block across negation, contradiction, temporal supersession, source authority,
cross-block dependency, prompt injection and all five structured payloads.

**The honest reading: the semantic-preservation work has no measured justification on the Jev
path.** Contradiction detection, negation preservation, qualifier preservation, dependency
tracking, temporal awareness, source authority and literal protection were all proposed as
fixes. On this suite, at up to six times the noise, none of the hazards they address actually
fails. Building them would be speculative work defended by argument rather than by a
reproduced failure, which is the exact thing this study exists to avoid.

The one measured gap is the deterministic path: three cases fail under mechanical scoring, and
that path is reachable whenever a key is missing or `--provider auto` degrades. If Etapa 2 is to
be evidence-driven, that is where the evidence points.

## Finding 9 — deterministic safety net: the three measured gaps, closed (Etapa 2)

Etapa 1 ended with a clear verdict: the Jev path shows no semantic-safety failure, and the only
measured gap is the deterministic path, which fails three of twenty cases. Etapa 2 targets
exactly that, and only that.

### What was built

Three rules, each tied to one reproduced failure, applied only to locally scored blocks:

| rule | fixes | mechanism |
|---|---|---|
| quoted speech | `quoted_instruction` | attribution verbs and quoted spans are evidence, not chatter |
| foreign-language evidence | `multilingual` | block language detected from unambiguous function words; a block in another language is not dropped for sharing no tokens with an English objective |
| distinctive-term linkage | `dependency_causal` | a block sharing two or more distinctive terms with a kept block is pulled in, so a conclusion does not outlive its evidence |

### What was built and then removed

Two broader rules looked reasonable and were measured out of existence: protecting every block
containing a negation cue, and every block containing a literal.

| configuration | cases passing | mean reduction |
|---|---|---|
| no protection | 17 / 20 | 62.2 % |
| negation + literal + quotes + language + linkage | 20 / 20 | **0.0 %** |
| quotes + language + linkage (shipped) | **20 / 20** | 51.4 % |

The broad rules took compaction to zero: chatter, log lines and filler are full of the word
"not" and of numbers with units, so protecting them protects everything. A protection that
keeps every block is not a protection, it is a disabled compressor. The hazards they targeted
(`negation_consent`, `numeric_precision`, `unit_conversion`) already passed without them.

### The trade, measured

Cost on the adversarial suite: **−10.9 points of mean reduction** for three failures fixed,
with the rest of the cost falling on cases that were already safe. Cost on the main corpora is
larger and buys more:

| corpus | reduction before | reduction after | ground-truth recall before | after |
|---|---|---|---|---|
| small | 73.2 % | 50.3 % | 3 / 5 | **5 / 5** |
| medium | 78.6 % | 66.0 % | 3 / 5 | **5 / 5** |
| large | 79.1 % | 68.8 % | 3 / 5 | **5 / 5** |

The independent main suite confirms it: the deterministic path now keeps every ground-truth
fact it used to lose, at ten to twenty-three points of reduction. That is the right direction
for a fallback. Its job is to be safe when the model judge is unavailable, and a fallback that
preserves evidence at 50 % compression is worth more than one that reaches 73 % by losing the
answer.

The Jev path is untouched: the protection is only consulted for locally scored blocks, so the
small differences in Jev rows between the two matrix runs are the run-to-run score variance
Finding 4 already documents.

`--no-deterministic-protection` restores the previous behaviour, and
`test_cases_the_safety_net_was_built_for` asserts each fixed case still fails without it, so the
attribution is checked rather than assumed.

## Finding 10 — recall by information category (Etapa 3)

> **Corrected by Finding 11.** The table first published here was measured under a narrower
> objective that its own ground truth did not serve, which made the Jev path look like it was
> losing a critical fact. Fixing the objective removed that failure with no code change. The
> corrected table is below; the narrative of what the metric found, and why the correction was
> needed, is kept because the sequence is the point.

The benchmark up to here reported one recall number over five ground-truth facts. That number
cannot distinguish losing an easy fact from losing a compliance rule, and it was hiding a real
failure. The corpora now carry categorized ground truth: the original facts plus a constraint,
a negative constraint, an exception, a dated revision and a contradictory measurement, and
`run_matrix.py` reports recall per category.

Recall by information category, averaged over the four scales (small, medium, large, xl):

| arm | critical fact | constraint | negative constraint | exception | temporal | contradiction |
|---|---|---|---|---|---|---|
| `baseline_raw` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| **`compact_jev`** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** |
| `compact_jev_prefix` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `compact_jev_tail6` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `chain_compact_optimize` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `optimize_*`, `intake` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `compact_jev_strict` | 0.95 | 1.00 | 1.00 | 1.00 | **0.50** | 1.00 |
| `compact_mechanical` | 1.00 | 1.00 | 1.00 | 1.00 | **1.00** | 1.00 |
| `prepare_default` | **0.40** | **0.00** | 1.00 | **0.00** | **0.00** | **0.00** |

With a question its ground truth can actually serve, the Jev path keeps every item of every
category on every scale, at 49 % reduction on the 1 492-block stress corpus. The deterministic
path matches it category for category after the supersession rule in Finding 12, at 70.7 %
reduction on the same corpus. `compact_jev_strict` is the only model-scored arm with a gap left,
and it is the one that disables the trim gear, which is now a third reason not to touch that
flag. `prepare_default` remains the worst arm in the suite, losing four of six categories.

### What the metric found before the correction

`show_losses.py` prints which item each arm loses, because a category score alone does not say
which item went. Under the original narrow objective it reported:

| arm | lost | marker |
|---|---|---|
| `compact_jev` (large) | critical fact | `3 chairs` |
| `compact_mechanical` | constraint, contradiction | `within 48 hours`, `8.7 percent` |
| `compact_jev_strict` | critical fact, negative constraint, contradiction | `3 chairs`, `must not be contacted`, `8.7 percent` |
| `prepare_default` | five of six categories | — |

That first row is what prompted Finding 11, and the investigation found the benchmark at fault
rather than the scorer.

## Finding 11 — the two-question experiment, a corpus premise bug, and the stress suite

### The premise was wrong before the fix was built

Finding 10 concluded that the Jev path drops the `3 chairs` fact on the large corpus and read
that as a scorer failure. Before building anything, the ground truth was checked against the
objective, and the objective was the problem: a corpus whose subject is *"What is the measured
mobile conversion problem for the clinic?"* cannot honestly require a chair-capacity fact or a
rebooking rule. A benchmark whose ground truth is not needed to answer its own question measures
nothing, and this one had been measuring that way since it was written.

The objective is now `"What is wrong with the clinic's booking operation, and what limits what we
can change?"`, which every category in the corpus actually serves. With that one change and no
code change at all, `3 chairs` survives. The scorer had been right; the question had been too
narrow to make the fact evidence.

### The two-question design, measured and removed

The failure above was the argument for a second, separately typed question per block: relevance
answers "does this block talk about the objective", which is not the same as "does this block
carry something the objective needs". So the second question was built — *does this block state a
concrete fact, figure or rule the objective needs, even without the objective's vocabulary?* —
with an asymmetric policy: a high confidence there keeps a block that relevance scored low.

Measured on 391 model-scored blocks of the large corpus, under both objectives:

| objective | correlation of the two scores | cases where relevance says drop and the fact score says keep |
|---|---|---|
| narrow (pre-fix) | 0.975 | **0 / 391** |
| aligned (post-fix) | 0.989 | **0 / 391** |

The two questions produce the same answer. The rescue path cannot fire, because the two scores
move together. And the cost is not free:

| | input tokens per call | output tokens per call | latency per call |
|---|---|---|---|
| one question | 1,765 | 271 | 627 ms |
| two questions | **3,142 (+77.9 %)** | **538 (+98.5 %)** | 663 ms (+5.7 %) |

A 78 % cost increase for a path that provably never fires is worse than not having the feature,
so it was removed rather than shipped behind a flag. The code is in the history if the idea is
revisited.

**What this says about the multi-question proposal.** The design asks several typed questions
about the same block in the same state, and the measurement says that yields collinear answers.
If dependency, contradiction or authority signals are wanted, they need a different *state* —
pairs or clusters of blocks rather than one block — not another question about the same block.
That is a different experiment, and this one does not support the cheaper version of it.

### Stress suite

`stress_edges.py` covers the two things the matrix cannot: behaviour at a stress scale, and
inputs nobody designs for.

**`xl`, roughly four times `large`**: 192 785 chars, 1 492 blocks, 44 128 tokens.

| metric | result |
|---|---|
| reduction | 51.5 % (44 128 → 22 651 tokens, exact counting) |
| Jev calls | 187 |
| cold wall time | 32 196 ms |
| warm wall time (decisions cache) | **458 ms** (70x faster) |
| warm calls / reused decisions | 0 / 1 491 |
| cold vs warm bytes | **byte-identical** |
| category recall | **6 of 6 categories perfect**, 5 of 5 critical facts |

Category recall and cache byte-stability both hold at four times the previous maximum, and the
decisions cache turns a 32-second pass into half a second.

**Edge cases, 8 of 8 passing:**

| case | input | output | note |
|---|---|---|---|
| empty file | 0 chars | 0 chars | exits 0, no crash |
| whitespace only | 11 | 11 | unchanged |
| single tiny block | 11 | 11 | below the scoring floor, kept |
| **one 264 kB block** | 264 030 | **77** | keeps its verdict line, drops 264 000 chars of repetitive tail |
| CRLF line endings | 83 | 78 | no mangling of the remaining text |
| unicode and emoji | 498 | 498 | `OdontoVero — Clínica Odontológica 🦷` intact |
| 400 tiny blocks | 7 488 | 7 488 | none scored, none lost |
| one 40 kB line | 40 006 | 36 386 | preserved, nothing droppable |

The oversized-block case is the one to remember: a quarter of a megabyte of repeated filler
collapses to its verdict line plus a drop marker, which is exactly the shape a compaction pass
should have on a pathological input.

## Finding 12 — supersession: closing the last deterministic gap

`temporal` was the one category the deterministic scorer lost, on every scale: 0.00. The datum is
a dated revision —

> `REVISION: the p75 figure was revised on 3 September, down from 5.8 seconds measured in June.`

— and the diagnosis, from the block's own term sets, was precise: it shares **one** distinctive
term with each of the two blocks that matter (`seconds` with the figure it revises, `figure` with
the exception that qualifies it). The linkage closure requires two shared terms, so it never
fired, and the revision was dropped while the value it corrects was kept. That is the worst
possible ordering: the stale figure survives with no sign it was replaced.

### Two attempts, and only the second one shipped

**Attempt one: make the closure transitive (two hops).** It worked and it was far too expensive.
Reduction on the medium corpus fell from 64.5 % to 37.0 %, because the closure cascades: the five
`GROUND TRUTH` blocks share `ground` and `truth`, so one kept fact pulls the other four, and a
second hop pulls everything that mentions the same nouns. Twenty-seven points of reduction for one
category.

**Attempt two: a supersession pass, separate from the loop.** A block that restates a value needs
one shared distinctive term, not two — it names the same metric in different words, so a single
term is the signal. And it may attach to a block the closure itself pulled in, because a revision
often qualifies evidence that was linked rather than natively kept. What it must never do is seed
further links, so the pass runs once, after the loop, against a frozen set of kept blocks.

The cue set is deliberately narrow — `revised|revision|superseded|supersedes|corrected|
correction|amended|amendment|restated|restatement|down from|up from` — because the negation and
literal experiments already showed what a broad rule does to a compressor.

### Result

| corpus | reduction before | reduction after | delta | categories lost |
|---|---|---|---|---|
| small | 46.8 % | 44.8 % | −2.0 | 1 → **0** |
| medium | 64.5 % | 64.0 % | −0.5 | 1 → **0** |
| large | 68.2 % | 68.0 % | −0.2 | 1 → **0** |
| xl | 70.7 % | 70.7 % | −0.1 | 1 → **0** |

The deterministic scorer now keeps every item of every category on every scale, and the price is
between one and two points of reduction. The Jev path is untouched, the adversarial suite stays
20/20 on both providers, and the stress suite stays green at four times `large`.

Three tests hold the rule in place: it fires for a revision sharing exactly one term, it does not
fire on a revision cue alone, and it does not seed a second hop. Writing them was instructive
too — the first version of the tests passed without exercising the new path at all, because the
objective in the fixture contained the very term the rule links on, and a term that appears in
the objective is correctly excluded as a link.

## Finding 13 — where you compact matters more than how much you remove

Everything up to here compacted the **accumulated context**. This finding measures the
alternative the cache economics actually favour, and the gap is large enough to change the
recommendation.

**Whole-context** (`lcc compact session.md`): the pass rewrites the session, so the first drop
mutates a byte-stable prefix. Every warm byte to the right of that offset stops being a cache
read and becomes a cache write.

**Per-payload** (`lcc compact result.txt` before appending it): the tool result is compacted
while it is still standalone, and only the compacted version ever enters the session. The prefix
never changes, so no warm byte is invalidated.

Simulated over a real session shape (`run_cache_patterns.py`: a 255-token prefix, five
tool-result turns, 4 254 tokens of appended payload, two model calls per turn), priced with the
repository's own model (read 0.10x, write 1.25x):

| pattern | passes | context cost | tokens seen | Jev tokens | vs no compaction |
|---|---|---|---|---|---|
| none | — | 8 062 | 28 800 | 0 | — |
| whole-context | 1 | 7 426 | 24 012 | 20 311 | **−7.9 %** |
| whole-context | 3 | 6 239 | 19 896 | 57 567 | **−22.6 %** |
| **per-payload** | 5 | **4 646** | 19 398 | **33 154** | **−42.4 %** |

Two things stand out.

**Per-payload compaction saves 5.4 times more context cost than a single whole-context pass**
(−42.4 % against −7.9 %), and it beats three whole-context passes (−22.6 %) as well. The reason
is arithmetic, not judgement: a whole-context drop pays to rewrite everything it invalidates, so
most of what it removed is handed straight back. A per-payload drop pays fresh-input price on
smaller content and never invalidates anything.

**Per-payload is also cheaper to run.** Five small passes spend 33 154 Jev tokens, while three
whole-context passes spend 57 567, because a whole-context pass re-scores the entire session
every time. Compacting often and locally costs less than compacting rarely and globally.

The numbers above are context cost in read-token-equivalents for the main model, with Jev tokens
reported separately. They are not added together: Jev is billed on its own schedule and
converting one into the other would be inventing a rate.

### What this means for a model that hides its reasoning

This is the case the pattern distinction exists for. When the reasoning trace is not visible, the
context you send is the context you pay for on every call, so a broken cache is felt immediately
and repeatedly. Three rules follow, in order of how much they matter:

1. **Compact the payload, not the session.** Run `lcc compact` on the tool result, the fetched
   page, the log bundle, before it is appended. The appended bytes are then final, and the
   session's prefix stays byte-stable for its whole life.
2. **If you must compact the session, protect the prefix.** `--prefix-marker` with the marker
   placed after the stable material makes mid-prefix mutation impossible, and the report proves
   it with `prefix_untouched: true`.
3. **Check `break_even_reuses` before keeping a whole-context pass.** Measured, a pass that
   mutates a warm prefix needs 12 to 20 reuses of the pruned context before it pays for itself.
   Below that, keep the original bytes and the cache.

## Finding 14 — sufficiency restoration costs reduction, most of it on small corpora

Everything above measured a relevance filter. `lcc compact` now also verifies sufficiency
(ADR 0014): after selection it asks whether the objective can still be solved from what remains,
and restores dropped blocks that are linked to kept content. The reduction figures in Findings 9,
10, 12 and 13 predate this, so the tables below supersede their reduction columns. Recall columns
and the cache findings are unaffected in kind.

48 of the 52 matrix rows moved. Only `baseline_raw` did not, because it compacts nothing.

**`compact_mechanical`** (exact tokens, `run_matrix.py`):

| scale | reduction before | reduction after | delta | recall |
|---|---|---|---|---|
| small | 44.8 % | **26.2 %** | −18.6 | 1.00 → 1.00 |
| medium | 64.0 % | **55.3 %** | −8.7 | 1.00 → 1.00 |
| large | 68.0 % | 64.6 % | −3.4 | 1.00 → 1.00 |
| xl | 70.7 % | 69.8 % | −0.9 | 1.00 → 1.00 |

**`compact_jev`** gives up less: 32.5 → 21.2 % on small, 43.3 → 39.4 % on medium, and under half a
point at large and xl.

The cost shrinks as the dossier grows, and the reason is structural rather than a tuning artefact.
Restoration is bounded by how many dropped blocks carry a link to kept content, and on a small
corpus a larger share of blocks is linked. So the penalty is worst exactly where the corpus is
smallest, which is also where the least context is at stake.

Two results worth stating plainly rather than burying in the table:

- **`compact_jev_strict` recall moved in both directions.** 0.9 → 1.00 on small and large, but
  1.00 → 0.9 on medium. The strict arm is the one that gains most from restoration on two scales
  and loses a category on the third. Treat it as one measurement on one corpus, not as a
  general improvement or a regression.
- **The `optimize_*` and `intake_default` arms gained about a point** of reduction
  (small −11.6 → −10.6 %, and larger gains at xl). They route through the same pipeline, so a
  change in block selection moves them too.

**What this buys.** Every `compact_*` arm holds recall at 1.00 across all four scales, and the
adversarial suite that exercises the hazards restoration exists for goes 26/26. The trade is
compression for not severing evidence, and it is now the default rather than an option:
`--no-sufficiency` restores the reduction figures above.

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
