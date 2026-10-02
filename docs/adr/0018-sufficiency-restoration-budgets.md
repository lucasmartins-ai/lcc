# ADR 0018 — Sufficiency/restoration budgets per layer, single-shot verifier

Date: 2026-10-02. Status: accepted (MSI Sprint 3).

## Decision

1. Each restoration layer carries its own explicit budget, settable from the
   CLI: structural `--max-restorations` (default 8), verifier
   `--verifier-max-restorations` (default 4, independent — total restored is at
   most the sum). The deterministic protection layer has no budget: it keeps,
   never drops.
2. The semantic verifier stays single-shot: one judgment over objective +
   candidate, at most one bounded FAIL restoration, no re-verify loop. A FAIL
   outcome stays REVIEW — it can never clear to PASS without a re-run that
   does not exist.
3. Any layer crashing fails closed: warn with a typed reason, count the
   failure, flag REVIEW (or keep everything, for provider outage). No silent
   drops, ever.

## Reason

The sprint-3 ablation measured each layer removing a distinct false-drop class
(deterministic: 3 classes on the lexical path; structural: false-drop rate
0.660 → 0.151 under judge error; verifier: restores past the structural
budget). Separate budgets keep that separation honest: a shared budget would
let one layer starve the other, and the ablation toggles (`--no-sufficiency`,
`--no-deterministic-protection`, `--semantic-verify`) only mean something when
each layer's spend is bounded and counted independently.

Single-shot (not a loop) because a re-verify loop can oscillate — restore,
re-judge, drop again — and each extra judge call costs latency and money for
no measured gain. The bounded one-lookahead closure (restored high-risk blocks
pull immediate high-confidence neighbours, one level only) covers the
measured dependency chains without going transitive: full multi-hop closure
was measured and removed earlier for costing ~20 points of reduction while
dragging trap blocks back in.

## Forecloses

- No re-verification loop around the verifier (a future sprint needs new
  ablation evidence to reopen this).
- No shared restoration budget across layers.
- No silent degradation: any new check added to this loop must warn + REVIEW
  on failure, following the fail-closed map in `docs/lcc/sufficiency.md`.
