# ADR 0015 — Cache-aware minimum-sufficient-context compiler

**Status:** accepted

**Context.** ADR 0014 defined the safety model (relevance, necessity, dependency
risk, semantic risk, redundancy) and structural sufficiency. The external review
found three gaps: (1) the implicit objective `min |C'| s.t. Answer(C')=Answer(C)`
is too strong and ignores cost; (2) structural sufficiency can report
"sufficient" when it merely found no broken link (false confidence); (3) there
was no fourth outcome for "I don't know whether this is safe to remove".

**Decision.**

- **Objective function.** Minimize total cost, not tokens:

  ```
  minimize inference_cost(C') + compilation_cost + cache_invalidation_cost
  subject to P(answer_correct | C') >= τ
         and critical_evidence(C') >= required_threshold
         and semantic_risk(C') <= allowed_risk
  ```

  Token reduction ≠ cost reduction; context reduction ≠ cache cost reduction
  (Finding 5, Finding 13). The report states `invalidated_tokens` and
  `break_even_reuses` for every mutating pass.

- **Independent semantic verifier** (`lcc.relevance.verifier`). One Jev call over
  `{objective, candidate_context}` only — never scores or decisions. Returns
  `{sufficient, missing_evidence, contradiction_risk, confidence}`. Fail-closed:
  unavailable/malformed → `sufficient=False`, `confidence=0.0`.

- **Fourth decision REVIEW (signal-only).** `KEEP | TRIM | DROP | REVIEW`, where
  REVIEW keeps bytes identical to KEEP and adds `needs_review=True`,
  `review_reason`, and a `needs_review:*` warning. Triggered by verifier
  insufficiency, `contradiction_risk >= 0.7`, or unresolved structural failure
  after restoration. Callers quarantine; the compiler never silently trusts.

- **Terminology.** `sufficiency.py` is structural/dependency sufficiency until a
  semantic stage judges. Semantic sufficiency means the verifier's question:
  "is any required information no longer present?".

**Consequences.** `--semantic-verify/--no-semantic-verify` (off by default, one
extra call). E2 safety calibration (refusal rate) becomes a first-class metric
alongside E0 evidence preservation and E1 answer preservation.
