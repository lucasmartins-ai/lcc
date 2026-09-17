# ADR 0013 - Opt-in instant relevance compaction (narrow model judgment)

**Status:** accepted

**Context.** The roadmap leaves room for model assistance, and `lcc agent` / `lcc route`
already call models behind their own opt-in boundaries. Users increasingly paste large
contexts (tool output dossiers, transcripts, logs) that contain blocks with zero value for
the actual objective. Deterministic cleaning cannot judge relevance; and naive semantic
pruning done per-run silently mutates prompt prefixes, which breaks prompt/KV caching (a
dropped mid-prefix block can invalidate tens of thousands of cached tokens to save a few
hundred). A bounded, auditable, cache-aware boundary is needed.

**Decision.** Add `lcc.relevance`, an explicit opt-in instant relevance compaction layer,
and the `lcc compact` command, plus `lcc intake --enable-relevance`.

- **Opt-in only, outside the deterministic core.** Default runs of `optimize`, `prepare`,
  `inspect`, and `intake` (without the flag) remain deterministic and network-free. The
  new package never imports into `cleaning`, `token_budget`, `prompt_builder`, `reporting`,
  `pipeline`, `inspection`, or `benchmarking`.
- **Narrow judgment provider.** Scoring uses the TypeSafe System One ("Jev") API — one
  batched call scores many blocks — with a shared-ledger audit trail (`lcc_compact`
  feature tag) matching the LookADev fleet schema.
- **Fail-safe direction.** Any provider failure keeps content, never drops it; no API key
  falls back to a fully local mechanical pass (zero-lexical-overlap blocks only). Blocks
  shorter than a threshold and blocks matching `--keep-regex` are never scored.
- **Byte fidelity.** Kept blocks are re-emitted exactly; output is byte-identical to the
  input when nothing is dropped; dropped runs are replaced by a deterministic marker line.
- **Cache alignment is part of the contract.** Sticky decisions (`--decisions-cache`) pin
  an `(objective, block)` outcome across runs so incremental outputs stay byte-stable;
  `--protect-prefix` / `--prefix-marker` make early-prefix mutation impossible; the report
  exposes `first_mutation_offset`, `prefix_sha256`, and `output_sha256` so orchestrators can
  detect cache epochs instead of discovering them via costs. See `docs/CACHE_ALIGNMENT.md`.
- **Reports stay versioned.** Every compaction run emits a `relevance-compaction-1.0`
  report with per-block decisions, scores, and provider provenance.

**Why.** Relevance is undecidable by deterministic cleaning alone, but it must not be
undecidable *silently*. This boundary keeps the local-first promise intact for every
existing command while giving users a fast, auditable way to drop context noise — and it
makes cache safety a first-class feature rather than an afterthought.

**Forecloses.** No future work may enable model-backed relevance scoring by default, place
it inside the deterministic core or the inspection boundary, drop blocks without an
auditable decision record, or mutate protected prefixes. Node/TypeScript parity for
`compact` is roadmap work behind the same contract, not implied by this ADR.

## Update 2026-09-18 — trim middle gear, tail pinning, concurrent batches

Reviewed `tamaratran/fast-jev-compaction` (a Claude Code plugin that replaces compaction
summaries with Jev decisions per tool call: keep the call, keep its result verbatim, or
truncate the result) and adopted what fits this boundary:

- Three-way decisions **keep / trim / drop**. Borderline blocks (score in
  `[--trim-threshold, threshold)`, default `threshold / 2`) keep a bounded head plus an
  audit note instead of vanishing; `--trim-head-chars 0` restores strict keep/drop.
- `--preserve-tail N` pins the newest N blocks untouched (live append-only contexts where
  fresh content must never be sacrificed by a pass that runs mid-session).
- Scoring batches run concurrently (`--max-workers`, max 8); a failed batch no longer
  aborts the remaining ones — blocks left unanswered fall back mechanically, as before.
- Reduction accounting: `reduction_ratio`, `worth_it`, `--min-reduction` — callers can skip
  a cache epoch that would save too little (`docs/CACHE_ALIGNMENT.md`).

The report schema moves to `relevance-compaction-1.1` (additive fields;
`decisions[].chars_after` for trims). Not adopted, deliberately: the reviewed plugin throws
on failure and relies on a host-provided fallback summary — this boundary keeps its
built-in fail-safe (keep-all) and its byte-stable sticky decisions.
