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
  lexical overlap, so it reduces less than mechanical and preserves more.
  Validated 2026-09-21 with real weights: the default checkpoint
  (`laya-multilingual`) keeps essentially every block — 0.0% reduction at
  small/medium/large, −0.5% at XL — so it currently reduces *much* less than
  mechanical (−70% XL), both at 100% category recall (Addendum below +
  `benchmarks/research/RESEARCH_STATUS.md`). All safety nets
  (type-aware trim, deterministic protection, graph + sufficiency, confidence
  policy) apply unchanged. Full operator guide: `docs/LAYA.md`.

**Why.** Local-first means the semantic path must also work without a key or
network. Validated 2026-09-21: the local judge runs offline at $0.00, inside the
budget, with `judged` and no fallback. Pre-validation text claimed it reached the
same recall *and reduction* as the 32K remote judge; the measured corpus result is
that the **default checkpoint makes no drops at all** (0.0% reduction), so the 1K
window is not the limiting factor on the evaluated corpora — judge capability is.
See the Addendum and `benchmarks/research/RESEARCH_STATUS.md` for the real rows.

**Forecloses.** No future work may make Laya a default or a silent fallback
(`auto` still prefers Jev → mechanical), bundle its weights/deps into the base
package, let it bypass budgeting/trim/sufficiency, or present fallback output
as semantically judged.

---

**Addendum — live validation (2026-09-21).** Decision unchanged; this replaces
the pre-validation figures above, which came from a mock harness.

- **Real execution.** `convaiinnovations/laya-multilingual` (resolved
  `laya-rl-agent`), macOS CPU, fully offline (`LCC_DISABLE_NETWORK=1`, HF hub
  offline, no API key): `provider_used: laya`, `degraded: false`,
  `semantic_guarantee: judged`. Every state stayed inside the 1024-token budget
  (max `context_budget_used` observed: 520); oversized blocks were kept whole
  with `laya_context_limit_exceeded` and never sliced (tail byte-identical).
- **Measured decisions.** The default checkpoint keeps essentially every block
  (0.0% reduction at small/medium/large; −0.5% at XL; 6/6 noise blocks kept on
  the ablation corpus). Consequence: the ~1K window is **not** the limiting
  factor on the evaluated corpora — judge capability is; a checkpoint that
  drops confidently is required before local reduction becomes real. The
  `laya-typed-decisions` checkpoint discriminates modestly where the default
  does not.
- **Repro.** `benchmarks/research/`: `run_laya_comparison.py`,
  `run_judge_ablation.py --judge laya`, `run_laya_context_cases.py`,
  `run_comparative_stress_test.py`; gated integration test
  `LCC_LAYA_INTEGRATION=1 pytest tests/test_laya_integration.py`. Full rows,
  sample sizes and limitations: `benchmarks/research/RESEARCH_STATUS.md`.
  Pre-validation mock archives are preserved there, clearly labelled.
