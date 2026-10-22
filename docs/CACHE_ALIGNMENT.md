# Cache alignment for instant relevance compaction

Compact aggressively — but never pay more in cache invalidation than you save in dropped
tokens. This document is the operating contract for `lcc compact` against prompt/KV caches.

## The failure mode this prevents

Prompt caches (Anthropic explicit breakpoints, OpenAI automatic prefix caching, Gemini
implicit/explicit context caching, local KV caches) are keyed on **byte-stable prefixes**:
a request reuses the cached computation for every byte up to the first changed byte.

Compaction that drops a block *inside* a warm prefix changes that prefix. Everything after
the mutation point is recomputed at cache-write prices. Typical numbers: a cache read costs
~0.1x the base token price while a cache miss/write costs ~1.25x. So:

- Dropping 400 tokens **while keeping the prefix intact** saves 400 read-tokens. Free win.
- Dropping 400 tokens **at offset 8 000 of a 40 000-token warm prefix** invalidates ~32 000
  tokens of cache. The invalidation costs ~ 32 000 × (1.25 − 0.1) read-equivalents, roughly
  36 800 read-token-equivalents — about **90x** what the drop saved. Net loss.

Rule of thumb: `saved_tokens × reuse_count > invalidated_prefix_tokens × 1.15` — if not,
do not mutate the prefix. Most of the time the right move is: **prune only after the last
cache breakpoint**, or **wait for a cache epoch**.

## The three mechanisms in `lcc compact`

### 1. Protected prefix — make mid-prefix mutation impossible

```
lcc compact dossier.md -q "<objective>" --protect-prefix 12000
lcc compact dossier.md -q "<objective>" --prefix-marker "<!-- lcc:cache-break -->"
```

Blocks whose start offset is before the boundary are never scored and never dropped. The
report proves it: `prefix_untouched: true` and `first_mutation_offset >= boundary`.
Place your stable material (system contract, reference memory, shared instructions) before
the marker; place volatile material (fresh tool output, logs, transcripts) after it. Then
compaction can only ever touch the volatile tail — zero cache risk while the prefix is warm.

### 2. Sticky decisions — make incremental runs byte-stable

```
lcc compact dossier.md -q "<objective>" --decisions-cache ~/.cache/lcc/decisions.jsonl
```

Decisions are pinned per `(objective, block content)`. Unchanged blocks keep their previous
outcome forever; only new blocks are scored. Because kept bytes are re-emitted exactly and
dropped runs are replaced by a deterministic marker that carries no scorer values, all runs
over an unchanged history produce byte-identical output (verify: `output_sha256` in the
report). Appending content extends the output at the tail instead of rewriting it, so the
previously emitted bytes remain a byte-stable prefix — exactly what incremental caching needs.

Two things break that stability, and both are measured in `benchmarks/research/`:

- **Scorer values in the inline marker.** Live scores wobble between calls, so a marker that
  embeds them rewrites the emitted bytes on every run. That is why `--marker-scores` is
  opt-in: by default the marker reports only the block count and char count, and the
  per-block scores stay in the report.
- **Idle judgment drift.** Without a decisions cache, a block sitting on the threshold can
  flip between runs. The decisions cache removes that by pinning the outcome, so warm runs
  show `calls: 0` and full `reused_decisions`.

One subtlety worth knowing: a run decides identical content once and applies that judgment to
every copy of it. The cache is content-addressed, so a run that scored two copies of the same
block independently could disagree with the single cached score a later run reuses — and
change the bytes. Pinning one judgment per content is what keeps cold and warm runs agreeing.

The objective is part of the decision key: changing the objective is a natural cache epoch
and rescoring starts fresh.

Two exceptions to "forever", both reported (see [Invariants and tests](#invariants-and-tests)):
a sufficiency restoration may keep an earlier sticky drop once a new block links to it (the
flip is persisted, so it happens once), and a block whose semantic neighbourhood changes is
re-keyed and decided again.

### 3. Epoch discipline — recompute only when you must

Treat these as epoch boundaries (rebuild caches once, deliberately):

- the objective changes;
- a session ends / a new agent session starts;
- the provider cache TTL expired anyway (otherwise you were paying full price regardless);
- the protected prefix itself changed (new reference material).

At an epoch boundary, run a **full** compaction without prefix protection and let the cache
rebuild once — that is the cheapest moment to restructure. Between epochs: append-only +
sticky, tail compaction only.

## Where to compact, not just how much

The sections above assume you are compacting the accumulated session. That is the expensive
placement, and measurement says so plainly.

| placement | what it does to a warm prefix | measured context cost |
|---|---|---|
| whole session, one pass | invalidates everything right of the first drop | **−7.9 %** |
| whole session, three passes | the same, three times | **−22.6 %** |
| **each payload before it is appended** | nothing, ever | **−42.4 %** |

Measured by `benchmarks/research/run_cache_patterns.py` over a session shape of a 255-token
prefix, five tool-result turns and 4 254 tokens of appended payload, priced with the read/write
factors above. The same run also shows the per-payload pattern spending fewer scorer tokens
(33 154 against 57 567), because a whole-session pass re-scores the entire session every time.

The arithmetic behind the gap: a whole-session drop pays to rewrite everything it invalidates,
so it hands back most of what it removed. A per-payload drop pays fresh-input price on smaller
content and invalidates nothing.

**Recommended order of preference:**

1. **Compact the payload before appending it.** Run the pass on the tool result, the fetched
   page, the log bundle. The appended bytes are final, and the session prefix stays byte-stable
   for the whole session.
2. **If you must compact the session, protect the prefix.** `--prefix-marker` makes mid-prefix
   mutation impossible and the report proves it with `prefix_untouched: true`.
3. **Before keeping a whole-session pass, read `break_even_reuses`.** Measured across three
   corpus sizes, a pass that mutates a warm prefix needs 12 to 20 reuses of the pruned context
   before it pays for itself. Below that, keep the original bytes and the cache.

This matters most where the reasoning trace is not visible. When the model does not expose its
reasoning, the context you send is the context you pay for on every call, so an invalidated
prefix is charged again and again rather than once.

## What to monitor

The report is designed for automated cache accounting:

| field | use |
|---|---|
| `first_mutation_offset` | where you broke the prefix; compare with your cache breakpoints |
| `prefix_sha256` | hash of the emitted bytes before the first mutation; if unchanged between runs, the cached prefix stays valid |
| `output_sha256` | full-output hash; detect accidental drift between runs |
| `prefix_untouched` | true when protection guarantees zero prefix risk |
| `reused_decisions` / `calls` | a warm-cache run should show `calls: 0` and full reuse |
| `invalidated_tokens` | tokens to the right of the mutation, i.e. what a warm cache would recompute |
| `break_even_reuses` | reuses of the pruned context needed before the drop pays for the invalidation |
| `cache_effect` | the cost-model verdict: stable prefix, invalidated/rewritten tokens, relative cost delta, `recommended`, `epoch_opened`, `sticky_flips` (below) |
| `degraded` / `degradation_reason` / `semantic_guarantee` | whether the semantic judge actually ran, and what the pass can promise |
| `token_count_method` | `approximate` means every token figure is an estimate, not a measurement |

`break_even_reuses` is the one to gate on. Measured across three corpus sizes the figure lands
between 11.8 and 20.3 reuses: below that, a mid-prefix pass costs more in invalidation than it
saves in dropped tokens, and the report says so explicitly with a `cache_epoch_risk` warning.
A run that would not pay off yet should keep the original bytes and the cache.

If `prefix_sha256` changes while a cache should still be warm, something recomputed the
head region — investigate before blaming the model provider.

### When a pass is not worth an epoch (v1.1)

The report carries `reduction_ratio` and `worth_it` (target via `--min-reduction`, default
25%). A pass that removes little is usually not worth breaking a warm prefix: keep the
original bytes and the cache. Trimmed blocks are counted separately (`blocks_trimmed`,
`decisions[].chars_after`) so accounting can tell "deleted" from "shortened". For live
append-only contexts, `--preserve-tail N` pins the newest blocks untouched, so freshly
appended content is never sacrificed by a pass that runs while the session is still
growing.

## Agent pattern (the short version)

1. Structure the prompt as `[stable prefix][cache break][volatile tail]`.
2. While the cache is warm: `lcc compact tail.md -q "<objective>" --prefix-marker "<!-- lcc:cache-break -->" --decisions-cache <path>`.
3. On objective/session change: full `lcc compact` once, no protection, fresh decisions file.
4. Never compact the stable prefix mid-epoch; the 90x math above is the reason.

## Invariants and tests

The contract above is code (`src/lcc/relevance/cache_contract.py`) and is tested. A pass
promises four things.

| | invariant | how it holds | tested by |
|---|---|---|---|
| **I1** | **Prefix stability.** Within one cache epoch (same objective and policy, `--decisions-cache` on), a pass over an append-only input emits the previous pass's output as a byte-exact prefix. | Sticky decisions; restorations are persisted (ratchet), so a decision flips at most once per epoch, and such a flip is reported. | `tests/test_cache_contract.py` (seeded property test), `benchmarks/cache/run_prefix_stability.py --check` |
| **I2** | **Deterministic placeholders.** The same removed content gives the same marker / `[removed: N lines, S KB · lcc recall <id>]` text and id; a pass never replaces its own placeholder, so a second pass over its output is a no-op. | Content-addressed stash ids; existing pointers are kept (`already_stashed`). | `test_second_stash_pass_keeps_existing_placeholders`, `test/hook-cache.test.mjs` |
| **I3** | **No non-deterministic fields** in the emitted context: no timestamps, random ids, dict order, locale, timezone or float formatting drift. | Scores only inline with `--marker-scores`, as fixed-decimal buckets; reports round every cost to fixed decimals. | `test_emitted_bytes_ignore_hash_seed_locale_and_timezone` (three `PYTHONHASHSEED` / `LC_ALL` / `TZ` combinations, one sha256) |
| **I4** | **Appending never rewrites earlier output** unless an epoch is opened and the report says so. | With a decisions cache each dropped block gets its own marker, so a dropped run that grows at the tail does not rewrite the marker already emitted. | `test_sticky_tail_run_growing_keeps_earlier_marker` |

### Reading `cache_effect`

```json
"cache_effect": {
  "contract_version": "cache-contract-1.0",
  "cache_state": "unknown", "assumed_state": "warm", "baseline": "previous_output",
  "stable_prefix_tokens": 9120, "invalidated_prefix_tokens": 0, "rewritten_tokens": 310,
  "removed_tokens": 1450, "expected_reuses": 1,
  "factors": {"read": 0.1, "write": 1.25, "input": 1.0},
  "estimated_cost_no_pass": 6470.0, "estimated_cost_pass": 1299.5,
  "estimated_relative_cost_delta": -0.7991,
  "recommended": true, "reason": "saves_cost_warm_cache",
  "epoch_opened": false, "sticky_flips": []
}
```

An incremental sticky pass: the previous output (9 120 tokens) is cached; the new pass keeps it
whole and appends 310 tokens. Sending the raw input instead would diverge from the cache at the
first block an earlier pass dropped (6 200 tokens in) and write the rest again, so here the pass
is about 80 % cheaper even on a warm cache.

- **baseline** is what the provider has cached: the input (default) or the previous pass's
  output (`--previous-output`, `previous_compacted_text`). Pass the previous output on
  incremental sticky runs: the cache holds that, not the raw input.
- **cost model.** Costs are relative to the input-token price. Warm: tokens in the stable prefix
  are cache reads (`read`), the rest is written (`write`). Cold: everything is written. Each
  further reuse reads the whole request. The pass is `recommended` only when it removes at
  least one token (the idle stash: `idleMinRemovableTokens`) and its cost over
  `expected_reuses` requests is lower than not compacting. `unknown` is priced as warm, the
  conservative assumption. `invalidated_tokens` / `break_even_reuses` keep their old meaning
  (tokens right of the first mutation in the *input*); `rewritten_tokens` counts what is
  actually written again after the pass.
- **cache state from an idle gap** (`cache_state_from_idle`, mirrored by the Claude Code hook's
  `idleDecision`): a gap exactly at the TTL is cold; one millisecond less is warm; a negative
  gap is clock skew and counts as warm (a wrong "cold" is the expensive mistake); a missing or
  non-numeric timestamp is unknown and the hook does nothing.
- **epoch_opened** is true when the pass does not keep the whole baseline as a prefix.
  `sticky_flips` names reused decisions a restoration flipped to keep in this pass (with a
  `cache_epoch_opened` warning). A flip is persisted and does not repeat.

The idle stash is a deliberate epoch: it runs only once the cache is cold, sends
`cache_state: "cold"`, and rewrites early history by design. What it promises is I2: a second
stash never touches the placeholders of the first, and stashing already-stashed history removes
nothing, so the hook stands down instead of rewriting a prefix for no saving. Its edges (TTL
boundary, `idleMinRemovableTokens` boundary, `idleMaxPassesPerSession`, every failure path
answering skip and never throwing into Claude Code) are in `test/hook-cache.test.mjs`.

### Measured: `benchmarks/cache/run_prefix_stability.py`

Seeded synthetic sessions (12 seeds, 12 turns, mechanical provider, no network, ~10 s) grow one
to three blocks per turn with a pass after every turn; the stable share is the fraction of the
previous output that survives byte-identical at the head of the next.

| arm | passes | append-only | mean stable share | unexplained breaks |
|---|---|---|---|---|
| block compaction, sticky (this contract) | 132 | 96.2 % | 0.975 | 0 (5 reported epochs, 9 sticky flips) |
| same, merged run markers (before) | 132 | 82.6 % | 0.968 | 18 |

Stashed transcript passes (12 seeds × 5 rounds): 0 idempotence violations, 0 placeholder
rewrites, every pass `recommended` on a cold cache. The mean stable share there is 0.08 by
design: a stash rewrites early history, which is why it waits for a cold cache.

`--check` fails on any unreported or unexplained break, an append-only rate under 0.9, a
non-idempotent stash or a rewritten placeholder; CI runs it next to the judge benchmark smoke.

