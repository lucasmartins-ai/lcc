# ADR 0005 — Exact vs approximate token counting

**Status:** accepted

**Decision.** `count_tokens(text, model)` returns a `TokenCount` carrying `value`,
`method` (`"exact"` | `"approximate"`), `counter`, `encoding`, and an optional `note`.
The count is `exact` only when `tiktoken` maps the requested model to an encoding. An
unknown model (with tiktoken present) is `approximate` and records the fallback encoding.
No tiktoken, or any tiktoken failure, yields a heuristic `approximate` count. The report
surfaces the method honestly and warns whenever counts are approximate.

**Why.** Token counts drive cost estimates; a guess must never be presented as exact.

**Forecloses.** The `TokenCount` shape is the contract. New counting backends must populate
the same fields rather than inventing parallel ones.
