# ADR 0014 — Minimum sufficient context: safety model, sufficiency, and typed decisions

**Status:** accepted

**Context.** ADR 0013 made relevance compaction opt-in, fail-safe and cache-aligned,
but it answered only one question: "is this block relevant enough to retain?". Three
gaps remained. First, a single relevance score stood in for necessity, dependency and
risk, so a unique exception could score moderately and still be dropped. Second, the
decision cache keyed on `(objective, block)` alone, so a policy, model or threshold
change silently reused decisions made under different rules. Third, trimming cut
characters without regard for content type, so structured blocks could come out
syntactically broken and misleading.

**Decision.** Evolve `lcc compact` from a relevance filter into a minimum-sufficient-
context compiler, still behind the same opt-in boundary:

- **Safety model.** Relevance, necessity, dependency risk, semantic risk and redundancy
  are represented independently (`lcc.relevance.safety.BlockAssessment`). Dependency or
  high semantic risk keeps a block regardless of relevance; high redundancy with low
  necessity may drop even at high relevance.
- **Decision cache identity v1.1** (`relevance-decisions-1.1`). The key binds objective,
  block bytes (exact, no whitespace normalisation), provider, model, policy/parser/
  protection/relationship/trim versions, thresholds, trim policy and tokenizer identity,
  hashed over canonical JSON. Same content + same policy reuses; anything else is a new
  cache epoch. v1.0 records still load but never hit under v1.1 (the safe direction).
- **Tokenizer contract.** Reports carry `tokenizer`, `tokenizer_id`, `tokenizer_version`
  and `is_estimate`. Token counts from different tokenizers must never be compared
  without re-counting; "context reduced by X%" is never presented as "cost reduced by X%".
- **Type-aware TRIM** (`lcc.relevance.trim`, policy `trim-1.0`). JSON/YAML/XML trim only
  to still-parseable line boundaries, tables keep whole rows, code/config cut at line
  boundaries, logs keep head+tail, high-risk content refuses trimming (TRIM→KEEP).
- **Context graph** (`lcc.relevance.graph`, `relationships-1.0`). Typed edges
  (SUPPORTS, QUALIFIES, CONTRADICTS, SUPERSEDES, DEPENDS_ON, DUPLICATES, DERIVED_FROM)
  replace open-ended regex accumulation. Deterministic today, Jev-assisted later.
- **Sufficiency verification** (`lcc.relevance.sufficiency`). After candidate selection
  the pass asks "can the objective still be solved from what remains?" and restores
  linked evidence up to `--max-restorations` (default 8), then verifies once more.
  Disable with `--no-sufficiency`. The verifier never regenerates information.
- **Confidence as policy input.** `--confidence-threshold` (default 0.5): a DROP below
  it degrades to TRIM, below half of it to KEEP. High-risk content additionally requires
  a high score to drop at all.
- **Jev stays a typed scorer.** `parse_noul_answer` validates range and confidence;
  out-of-range or malformed answers fall back mechanically with typed warnings. The
  report records `jev_model_requested` and `jev_model_resolved` so a moving alias is
  never the only identifier. All failure modes (timeout, 429, 5xx, malformed, partial,
  unavailable, disabled network) keep content and report `degraded` honestly.

**Why.** The old mental model was "which context can I remove?". The target is "what
is the minimum context from which the objective can still be solved safely, and what
evidence proves it?". Every item above serves that proof: identity makes decisions
reproducible, trim safety keeps partials honest, the graph makes dependencies explicit,
and sufficiency closes the loop that relevance alone leaves open.

**Forecloses.** No future work may collapse relevance/necessity/dependency/risk back
into one score, key decisions without policy identity, trim structured content naively,
or let the semantic provider own policy, safety, authorization or execution. Retrieval
remains behind ADR 0011/0012 and is out of scope for this change.
