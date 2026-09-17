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
dropped runs are replaced by a deterministic marker, **all runs over an unchanged history
produce byte-identical output** (verify: `output_sha256` in the report). Appending content
extends the output at the tail instead of rewriting it, so the previously emitted bytes
remain a byte-stable prefix — exactly what incremental caching needs.

The objective is part of the decision key: changing the objective is a natural cache epoch
and rescoring starts fresh.

### 3. Epoch discipline — recompute only when you must

Treat these as epoch boundaries (rebuild caches once, deliberately):

- the objective changes;
- a session ends / a new agent session starts;
- the provider cache TTL expired anyway (otherwise you were paying full price regardless);
- the protected prefix itself changed (new reference material).

At an epoch boundary, run a **full** compaction without prefix protection and let the cache
rebuild once — that is the cheapest moment to restructure. Between epochs: append-only +
sticky, tail compaction only.

## What to monitor

The report is designed for automated cache accounting:

| field | use |
|---|---|
| `first_mutation_offset` | where you broke the prefix; compare with your cache breakpoints |
| `prefix_sha256` | hash of the emitted bytes before the first mutation; if unchanged between runs, the cached prefix stays valid |
| `output_sha256` | full-output hash; detect accidental drift between runs |
| `prefix_untouched` | true when protection guarantees zero prefix risk |
| `reused_decisions` / `calls` | a warm-cache run should show `calls: 0` and full reuse |

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
