# ADR 0016 — Laya local semantic backend for relevance compaction

**Status:** accepted

**Context.** ADR 0013 made `lcc compact` opt-in relevance compaction behind a
narrow-judge boundary with two backends: remote Jev (needs `TYPESAFE_API_KEY`)
and the fully local mechanical fallback (lexical overlap, heuristic only).
That left a gap: users without a key had no *semantic* pass available, only a
lexical one (`semantic_guarantee: none`). Laya — a non-autoregressive System 1
decision engine by NandhaKishorM / Convai Innovations (Apache 2.0,
<https://github.com/NandhaKishorM/laya>) — fills it: typed `noul`/`choice`/
`score` judgments, on-device, zero network, zero remote tokens.

**Decision.** Laya is a third scoring provider (`--provider laya`), still
behind the same opt-in boundary (ADRs 0013–0015) and **outside the
deterministic core** (ADR 0010): no Laya code, weight, or dependency may enter
`cleaning`, `token_budget`, `inspection`, `pipeline`, `lexical_selection`, or
`benchmarking`. `local-context-compiler[laya]` is an optional extra; the base
package stays dependency-free:

- **Strict context budgeting, never naive truncation.** Known limits
  (`laya` 512, `laya-multilingual` / `laya-typed-decisions` 1024, overridable
  via `--laya-context-limit`) minus `HEAD_RESERVATION_TOKENS = 192` leave
  319/831 state tokens. A block that alone exceeds the room is kept whole with
  `laya_context_limit_exceeded` (`status: insufficient_context`) — LCC refuses
  `context[:N]` slicing of semantically important content.
- **Honest fallback.** Missing extra or failed batch never drops via the failed
  path and never claims `judged`: missing extra → mechanical scoring as
  `laya+mechanical_fallback` (`degraded: true`,
  `laya_unavailable_mechanical_fallback`, `semantic_guarantee: none`);
  failed batch → remaining blocks mechanical (`semantic_guarantee: partial`).
- **Observability.** Reports carry `laya_model_requested` / `laya_model_resolved`,
  `laya_context_limit` vs `context_budget_used`, `laya_temperature`, `calls`,
  `latency_ms` (model only) alongside `compilation_ms` (whole pass).
  Temperature calibration (`calibrate_noul`, default 1.0 = no-op) is pure
  stdlib and part of the decision-cache identity.
- **Conservative by design.** Laya keeps semantically related content with no
  lexical overlap, so it reduces less than mechanical and preserves more
  (measured XL: −22.6% vs −70%, all at 100% category recall). All safety nets
  (type-aware trim, deterministic protection, graph + sufficiency, confidence
  policy) apply unchanged. Full operator guide: `docs/LAYA.md`.

**Why.** Local-first means the semantic path must also work without a key or
network. A ~1K-context local judge over LCC-compiled context reaches the same
recall as the 32K remote judge on the measured corpora, at $0.00.

**Forecloses.** No future work may make Laya a default or a silent fallback
(`auto` still prefers Jev → mechanical), bundle its weights/deps into the base
package, let it bypass budgeting/trim/sufficiency, or present fallback output
as semantically judged.
