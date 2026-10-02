# Sufficiency + restoration loop (MSI Sprint 3)

The compaction pass is `SELECT → SAFETY → RESTORATION → VALIDATION → VERIFY
(opt-in)`. Scoring answers "what can I remove"; this loop answers "after these
drops, was any explicit dependency link severed" — and restores the evidence
that was. Three layers, each removing a distinct class of false drops:

| Layer | What it is | Budget | Off switch | Counters in the report |
|---|---|---|---|---|
| 1. Deterministic | Quoted-speech + cross-language keep, distinctive-term dependency closure, prefix/tail/keep-pattern protection, high-risk retention | Unbounded keep (never drops) | `--no-deterministic-protection` (also gates layer 2: raw scoring means no safety nets) | `blocks_protected` |
| 2. Structural (dependency) | Typed graph (`relationships-1.0`) + `verify_sufficiency` + bounded restore of dropped blocks linked to kept content, one re-check, no loop | `--max-restorations` (default 8) | `--no-sufficiency` | `sufficiency_checks`, `sufficiency_failures`, `blocks_restored`, `relationship_edges` |
| 3. Light judge (semantic verifier) | One independent Jev question over objective + candidate only; FAIL restores graph-linked drops once, never re-runs | `--verifier-max-restorations` (default 4, independent: total restored ≤ 8 + 4) | `--semantic-verify/--no-semantic-verify` (default off) | `semantic_verifier_decision`, `semantic_verifier_confidence`, `needs_review` |

The verifier is single-shot by design: it judges the candidate, restores within
budget on FAIL, and the outcome stays REVIEW — never PASS without a re-run that
does not exist. No restoration loop is possible by construction.

## Fail-closed map

| Layer crashes | Result (proved by test) |
|---|---|
| Graph build throws | `relationship_analysis_failed` warning; compaction continues, output produced |
| `verify_sufficiency` throws (first check or re-check) | `sufficiency_failed_fail_closed` / `sufficiency_recheck_failed_fail_closed` warning, `sufficiency_failures + 1`, IR `sufficient: false`; unresolved failures flip `needs_review` (E2 calibration) |
| Verifier client explodes | Contract maps to REVIEW (`verifier_unavailable_fail_closed`) |
| Verifier code itself explodes | `semantic_verifier_failed` warning + `needs_review` |

Nothing is silently discarded: every failure warns and flags REVIEW so the
caller keeps more context instead of trusting the output.

## Mechanism ablation (measured 2026-10-02, offline)

Corpora: the 30 curated adversarial cases (`benchmarks/research/`,
`adversarial_cases.py`, pressure 1). Evidence class: CURRENT. Data: CURATED.
`false_drop_rate` = required critical blocks lost / required critical blocks
(53 total). Reproduce: sweep script driving `compact_context` per case with the
layer toggles below (mechanical provider; harsh-judge variant uses a fake Jev
client that keeps only the single highest-overlap block).

Lexical path (provider mechanical):

| Config | Cases pass | lost_req | false_drop_rate | blocks_restored |
|---|---|---|---|---|
| All layers on | 30/30 | 0/53 | 0.000 | 0 |
| `--no-deterministic-protection` | 27/30 | 3 cases fail: `dependency_causal`, `quoted_instruction`, `multilingual` | — | 0 |
| `--no-sufficiency` | 30/30 | 0/53 | 0.000 | 0 (nothing to restore: lexical scoring + protection already keep linked content) |

Judge-error path (fake Jev, keeps 1 block, drops the rest):

| Config | Cases pass | lost_req | false_drop_rate | blocks_restored |
|---|---|---|---|---|
| All layers on | 22/30 | 8/53 | 0.151 | 127 |
| `--no-sufficiency` | 3/30 | 35/53 | 0.660 | 0 |

Verifier path (targeted fixture, `tests/test_verifier_fail_restoration.py`):
structural budget 1 restores 1, verifier FAIL restores 2 more linked blocks
within its own budget (3 ≤ 1 + 4), outcome REVIEW, accounting describes the
final bytes.

KEEP verdict per layer: deterministic removes 3 real false-drop classes
(causal link, quoted instruction, cross-language evidence); structural cuts
false drops 0.660 → 0.151 under judge error (27 fewer lost required blocks);
verifier restores what the structural budget could not afford and adds the
REVIEW signal. No layer was deleted. Note: with a Jev-path judge the
deterministic keep rules do not fire (they guard lexical scoring only), so
`--no-deterministic-protection` ≡ `--no-sufficiency` under the harsh judge —
the protection and the restoration gate share one flag by design.

Red rows (no cherry-pick): under the harsh judge 8 required blocks are still
lost with all layers on — all are restoration-budget exhaustion (more linked
drops than 8 per pass, e.g. the 4-block VAT chain, the 3-price series). Each
such pass carries `sufficiency_failures ≥ 1` → `needs_review`, i.e. the loop
says "don't trust this" instead of silently dropping.

## Adversarial matrix (sprint scope, provider mechanical, N = 1 corpus each)

| Class | Case / probe | Result |
|---|---|---|
| Contraditório | `contradiction_same_metric`: both 4.2% and 8.7% survive | PASS |
| Stale | `temporal_supersession`: latest 95 pounds survives | PASS |
| Duplicado | exact-duplicate probe: byte-identical copy dropped, content survives in first copy | PASS |
| Dependência oculta | `dependency_causal` under judge error: cause restored with `semantic_sufficiency_restoration` | PASS |
| Evidência única | `unit_conversion`: sole value 10000 ms survives | PASS |
| Proveniência malformada | emitter output validates against `context-ir/0.1` (provenance on every unit); IR with provenance deleted is rejected | PASS |

Implementation: `src/lcc/relevance/compactor.py` (loop),
`src/lcc/relevance/sufficiency.py` (structural check),
`src/lcc/relevance/verifier.py` (light judge),
`src/lcc/relevance/graph.py` (typed edges). Tests: `tests/test_sufficiency.py`
(severed link, bypassed protection, 3 injected failures, 6 adversarial),
`tests/test_verifier_fail_restoration.py` (bounded FAIL restoration).
