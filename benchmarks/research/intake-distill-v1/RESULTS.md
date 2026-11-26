# Intake distill v1: results (2026-11-26)

Protocol: [PROTOCOL.md](PROTOCOL.md) (pre-registered before any arm saw T; three amendments, each recorded before the
step it governed). Final test set: `t.json` (private, 68 fresh real prompts/dictations: 24 Part R3, 14 census long
one-paragraph messages, 30 owner-screened voice memos including 9 in the declared `longo` stratum >1,500 words).

**Question.** Can a deterministic linear model trained on Jev's sentence labels (arm P) split a long dictation into a
verbatim XML brief (`<pedido>`, `<outros_pedidos>`, `<entrega>`, `<regras>`, `<contexto>`, `<a_confirmar>`) that
makes a downstream coding agent invent fewer requirements (H1) while misfiling requests, delivery details, or rules
into `<contexto>` in at most 10% of messages (H2)?

**In short**

- **Final test T (`n = 68`, `stats.json`, `gateClaim`: T_PRIMARY — PASS).** Both pre-registered criteria **FAIL**:
  - **H2 (guard, ≤10% misfiled only in `<contexto>`): FAIL.** 55 / 68 (**80.9%**, Wilson 95% CI 70.0%–88.5%) had at
    least one request, delivery detail, or rule filed only under `<contexto>`.
  - **H1 (primary, fewer invented requirements): FAIL.** Raw invented in 52 / 68 (76.5%) vs brief in 58 / 68 (85.3%);
    discordant pairs 4 brief-better vs 10 raw-better (exact two-sided McNemar `p = 0.1796`, leaning against brief).
  - **Blind judge overall preference:** raw beat brief **44 to 24** (0 ties, exact sign `p = 0.0205`).
- **Secondary & descriptive checks on T (descriptive / INFERIDO under `gateClaim`).**
  - **H3 (main ask fully captured 2/2):** raw 64 / 68 (94.1%) vs brief 62 / 68 (91.2%), discordant 3 vs 5 (`p = 0.727`).
  - **All four judge rubric means (0–2)** favored raw over brief: `main_ask` 1.941 vs 1.912, `side_asks` 1.794 vs
    1.500, `delivery` 1.809 vs 1.676, `rules` 1.456 vs 1.265.
  - **Tokens:** brief cost **+5.7%** median tokens (`brief / raw = 1.057`, p90 `1.105`, max `1.172`).
  - **Strata:** H2 failed in both `base` (47 / 59, 79.7%) and `longo` (8 / 9, 88.9%); raw was preferred in both
    (`base` 38 vs 21, `p = 0.0363`; `longo` 6 vs 3, `p = 0.508`).
- **Dev only (`Part R`, `n = 22`, `stats_p_dev.json`, `gateClaim`: DEV_P — PASS).** Trained on the 1,278 single-line
  pool messages (4,108 sentences), arm P reached **14 / 22** main-ask hit@1 (vs A0 12 / 22, D 11 / 22, Jev `v1_pilot`
  12 / 22) and macro-F1 (6) **0.202** (1.02× teacher's 0.198) at **26.6 ms** median latency. That dev signal did not
  translate into a better downstream XML brief on T.
- **What runs in `lcc` today.** Nothing from this study ships into `src/lcc/`. `parse_intake` is unchanged.

## Final test T (`n = 68`)

Frozen inputs (Amendment 3): `arm_p.py` (`a53c4869…`), `p_weights.json` (`c145a962…`, `tau = 0.40`), `run_test.py`
(`02caf707…`), `SEED_XY = 20261125`. Answerer: `agy --mode plan -p`. Blind judges: `codex exec --ephemeral -s read-only -c model_reasoning_effort=medium` (separate H1/H3 and H2 calls so H1/H3 never sees the brief).

| Hypothesis / Metric | Raw | Brief (arm P) | Test / Interval | Verdict |
| :--- | ---: | ---: | :--- | :--- |
| **H2 (guard): misfiled only in `<contexto>`** | — | **55 / 68 (80.9%)** | Wilson 95% CI `[70.0%, 88.5%]` (bar ≤10%) | **FAIL** |
| **H1 (primary): invents a requirement** | 52 / 68 (76.5%) | 58 / 68 (85.3%) | discordant 4 brief vs 10 raw, McNemar `p = 0.1796` | **FAIL** |
| H3 (secondary): main ask full (2/2) | 64 / 68 (94.1%) | 62 / 68 (91.2%) | discordant 3 brief vs 5 raw, McNemar `p = 0.7266` | FAIL / n.s. |
| Blind judge prefers (`better`) | **44 / 68** | 24 / 68 (0 ties) | exact sign `p = 0.0205` | Raw wins |
| Mean `main_ask` / `side_asks` / `delivery` / `rules` | 1.94 / 1.79 / 1.81 / 1.46 | 1.91 / 1.50 / 1.68 / 1.27 | descriptive | Raw higher on all 4 |
| Tokens (`brief / raw`, median / p90 / max) | 349.5 median | 373.0 median | `1.057` / `1.105` / `1.172` | +5.7% cost |
| Arm P latency on M1 (median / max) | — | 22.4 ms / 193.2 ms | descriptive | Fast, no gain |

H2 misfiled kinds across the 68 messages: `multiple` 21, `rule` 17, `request` 13, `delivery` 4, `none` 13.

### Declared strata and origins on T (descriptive / INFERIDO)

| Slice | n | H2 misfiled | H1 invented (raw / brief, p) | H3 main full (raw / brief) | Judge prefers (raw / brief) | Brief / raw tokens |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **All T** | 68 | 55 (80.9%) | 52 / 58 (`0.180`) | 64 / 62 | 44 / 24 (`p = 0.021`) | 1.057 |
| Stratum: `base` | 59 | 47 (79.7%) | 46 / 50 (`0.388`) | 56 / 55 | 38 / 21 (`p = 0.036`) | 1.061 |
| Stratum: `longo` (>1,500 w) | 9 | 8 (88.9%) | 6 / 8 (`0.500`) | 8 / 7 | 6 / 3 (`p = 0.508`) | 1.014 |
| Origin: `r3` | 24 | 20 (83.3%) | 17 / 17 (`1.000`) | 22 / 23 | 15 / 9 (`p = 0.307`) | 1.072 |
| Origin: `census` | 14 | 13 (92.9%) | 12 / 14 (`0.500`) | 14 / 14 | 9 / 5 (`p = 0.424`) | 1.101 |
| Origin: `voice` | 30 | 22 (73.3%) | 23 / 27 (`0.125`) | 28 / 25 | 20 / 10 (`p = 0.099`) | 1.023 |

## Dev stage: teacher gate, Jev variants, training pool, and arm P

1. **Teacher gate (`stats_teacher_dev.json`, Part R `n = 22`, 1,129 sentences).** Owner labels were 86.5% `contexto`
   and 0% `ruido`. Jev (`v1_pilot`) achieved 12 / 22 main-ask hit@1 and 2 / 22 (9.1%) dev loss; Opus achieved 13 / 22
   and 6 / 22 (27.3%) dev loss. Jev passed the ≤10% eligibility bar (Amendment 2).
2. **Jev prompt tuning (`stats_jev_variants.json`, 185 requests, `jev-1.14.0`).** Four variants adding the owner's
   context prior (EN/PT, 6-class and 5-class) raised κ (0.110 → 0.148–0.271) and macro-F1 (5) (0.237 → 0.282–0.322)
   with 0% `ruido` loss, but dropped main-ask hit@1 (9–11 vs 12) and filed all gold main-ask sentences into
   `<contexto>` on 4–5 / 22 messages (vs 1 / 22 for `v1_pilot`). Under Amendment 2's pre-registered order, `v1_pilot`
   remained frozen.
3. **Training pool (`stats_pool_labels.json`, 1,581 messages, 15,020 sentences, 0 errors, 2,006 / 2,500 Jev budget).**
   The 303 multi-line messages supplied 10,912 sentences (72.6%), heavily skewed toward `entrega` (2,008) and `regra`
   (2,947). As anticipated in `PROTOCOL.md` (Data), arm P was fitted on the 1,278 single-line messages (4,108
   sentences; `entrega` had 117 sentences <200 and was not further tuned), `L2 = 0.01` on the 10% held-out slice
   (seed `20261127`), `τ = 0.40`.
4. **Dev comparison (`stats_p_dev.json`, `gateClaim`: DEV_P — PASS).**

| Model (dev, `n = 22`) | Main-ask hit@1 | κ vs owner | Macro-F1 (6) | Macro-F1 (5, no `ruido`) | Median latency |
| :--- | ---: | ---: | ---: | ---: | ---: |
| A0 (first ask) | 12 / 22 | — | — | — | — |
| D (v1 frozen) | 11 / 22 | — | — | — | — |
| Jev `v1_pilot` (teacher) | 12 / 22 | 0.110 | 0.198 | 0.237 | network |
| **Arm P (single-line, frozen)** | **14 / 22** | 0.074 | **0.202** | **0.243** | **26.6 ms** |
| Arm P ablation (full pool w/ multi-line) | 12 / 22 | 0.020 | 0.183 | 0.220 | 27.9 ms |

## Interpretation and phase 2 recommendation (INFERIDO)

- **Why the brief lost on T (INFERIDO).** Reordering sentences into six XML sections broke narrative continuity while
  putting requests, side asks, and constraints under `<contexto>` (80.9% of messages) or `<a_confirmar>`. Because the
  downstream agent (`agy`) already captured 94.1% of main asks and higher side-ask/delivery/rule scores directly from
  the intact raw dictation, noisy XML re-bucketing subtracted clarity instead of adding it — even on 1,500–2,500 word
  voice memos (`longo`).
- **Phase 2 (Q4: ModernBERT / JEPA student S) is not recommended under this XML-brief design (INFERIDO).** Even in the
  exploratory dev pilot where the Jev teacher itself built the brief (`pilot_downstream_stats.json`), raw still led on
  judge preference (12 vs 10) and the brief added +4.4% tokens. Improving the sentence classifier from P to a small
  encoder student addresses only part of the error; the verbatim XML re-bucketing format itself showed no advantage
  over leaving the prompt intact for a frontier coding agent.

## `gateClaim` receipts (2026-11-26)

Run via `LOOKAORCHESTRATOR` CLI (`npx tsx src/cli/index.ts intelligence gate ... --presented-as MEASURED --json`,
source `jev`):

| Label | Decision | `claimSupported` | `evidenceStrength` | Scope |
| :--- | :--- | ---: | ---: | :--- |
| `T_PRIMARY` | **PASS** | 0.85 | 2.78 | T (`n = 68`) H2 fail (55/68, 80.9%, Wilson 70.0%–88.5%), H1 fail (58 vs 52, McNemar `p = 0.1796`), raw preferred 44 vs 24 (`p = 0.0205`) |
| `DEV_P` | **PASS** | 0.84 | 2.66 | Dev (`n = 22`) single-line arm P hit@1 14/22 (vs A0 12, D 11, Jev 12), macro-F1 (6) 0.202 (1.02× teacher), 26.6 ms median |
| `T_SECONDARY_COMBINED` | BLOCK (downgraded to INFERIDO) | 0.69 | 2.79 | Compound claim combining H3, token ratio, and `base`/`longo` strata — reported above as descriptive / INFERIDO |
