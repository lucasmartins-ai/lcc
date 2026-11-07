# LongHealth v1 results: set D (2026-11-07)

This is the run that [PROTOCOL.md](PROTOCOL.md) pre-registered: frozen by Amendment 2, with the billing route
changed by Amendment 3. Amendment 4 leaves out the credit valuation. The verdicts below are the frozen harness's own
(`longhealth_v1.py score --set D`). Every number comes from [`results.json`](results.json), which holds the
aggregates and per-item 0/1 scores keyed by `(patient, question, condition, arm)`. No record text, question, option,
summary or answer appears here (Data use).

**Verdicts: H1 PASS, H2 FAIL, H3 descriptive.** Every validity gate passed. One dropped session departs from
V2's rule, and scoring it as V2 reads leaves the verdicts unchanged (Dropped session).

`gateClaim` is an evidence check the owner runs on a measured claim before publishing it. PASS lets the claim stand
as measured. BLOCK means it must carry the label INFERIDO (Portuguese for "inferred"). On 2026-11-07 it returned PASS
on the H1 result in its short form below, and BLOCK on a longer wording of the same numbers. It returned BLOCK on the
H2, verifier and token findings, so read those as INFERIDO: one run, one answerer model, no independent replication.

## Setup

- LCC pin `17d9595` (1.3.0). Answerer Claude Sonnet 5.5, summarizer Claude Opus 5.5, through `claude -p`.
- 54 sessions: 18 target patients × `ans_early`, `ans_late`, `unans`. One session was dropped (see Dropped session).
- 582 calls of the 650 cap. Calls 1–214 ran on the subscription, and calls from 216 on through the API route
  (Amendment 3; line 215 was never sent). Only `summary_clin` has calls on both routes.
- Claude Code CLI 2.1.309 for every chunk that logged its version (from 2026-11-06 on).

## Gates

| Gate | Result |
|---|---|
| V1 `full_t` A ≥ 0.60 | pass (621/700 = 0.887) |
| V2 drops ≤ 5% | pass (1 of 54 = 1.9%), but the drop itself departs from V2 (see Dropped session) |
| V3 `ans_early` stash-dependent ≥ 80% | pass (360/360 in the location receipt, which was written before any answer and covers all 54 sessions, the dropped one included; 340/340 on the 17 kept) |
| V3b `ans_late` in view ≥ 80% | pass (360/360; `unans` 360/360 absent; 0 mixed) |
| V4 recall through the CLI | pass |
| V5 parse ≥ 95% | pass (0 response failures in any arm or condition) |
| V6 not contaminated | pass: `none` 215/360 = 0.597 against the line `full_t` A − 0.10 = 0.787 (chance 0.20) |

`none` answers well above chance with no records. This run cannot tell why: memorisation of LongHealth, general
medical knowledge and cues in the questions and options are all possible. Nor does it measure how much that helps
each arm, since the arms' instructions differ (Q-N forces A–E; the others may answer F).

## Accuracy

Counts over the 53 kept sessions. A covers `ans_early` + `ans_late`; E is the exact-value stratum within A; U is
`unans` answered F; UA is `unans` lines that chose A–E.

| Arm | A | E | U | UA |
|---|---|---|---|---|
| `none` (Q-N) | 215/360 = 0.597 | 66/141 = 0.468 | n/a | n/a |
| `full_t` | 621/700 = 0.887 | 248/278 = 0.892 | 360/360 | 0/360 |
| `stashed_t` | 622/700 = 0.889 | 246/278 = 0.885 | 360/360 | 0/360 |
| `stashed_0` | 327/700 = 0.467 | 127/278 = 0.457 | 360/360 | 0/360 |
| `summary_s` | 532/700 = 0.760 | 216/278 = 0.777 | 360/360 | 0/360 |
| `summary_clin` | 612/700 = 0.874 | 242/278 = 0.871 | 360/360 | 0/360 |
| `stashed_v` | 563/700 = 0.804 | 197/278 = 0.709 | 360/360 | 0/360 |

By condition (A):

| Arm | `ans_early` (target stashed) | `ans_late` (target in view) |
|---|---|---|
| `full_t` | 302/340 = 0.888 | 319/360 = 0.886 |
| `stashed_t` | 299/340 = 0.879 | 323/360 = 0.897 |
| `stashed_0` | 2/340 = 0.006 | 325/360 = 0.903 |
| `summary_s` | 246/340 = 0.724 | 286/360 = 0.794 |
| `summary_clin` | 294/340 = 0.865 | 318/360 = 0.883 |
| `stashed_v` | 268/340 = 0.788 | 295/360 = 0.819 |

## Primary contrasts

Paired cluster bootstrap over the 18 targets, 2000 resamples, seed `20261103`. Differences are in percentage points.

| Contrast | Metric | Difference | 95% CI | Criterion | Result |
|---|---|---|---|---|---|
| H1 `stashed_t − full_t` | A | +0.1 | −1.9 to +2.1 | lower bound > −5 | **PASS** |
| H2 `stashed_t − summary_s` | E | +10.8 | +5.9 to +15.5 | lower bound > 0 | met |
| H2 `stashed_t − summary_clin` | E | +1.4 | −1.2 to +4.1 | lower bound > 0 | not met |
| H2 (both) | | | | | **FAIL** |
| H3 `stashed_v − stashed_t` | UA | 0.0 | 0.0 to 0.0 | upper bound < 0 | not met (descriptive) |
| H3 `stashed_v − stashed_t` | A | −8.4 | −11.0 to −5.8 | lower bound > −5 | not met (descriptive) |

Per-patient differences (patients 01, 02, 04, 06–20 in order, percentage points):

| Contrast | 18 per-patient differences |
|---|---|
| H1 (A) | 5.0, −2.5, −5.0, 2.5, −5.0, 2.5, 10.0, 2.5, 2.5, 0.0, −2.5, 5.0, 0.0, 0.0, −2.5, −7.5, −5.0, 2.5 |
| H2 vs `summary_s` (E) | 18.2, 0.0, −8.3, 22.7, 0.0, 0.0, 22.2, 8.3, 0.0, 0.0, 18.8, 27.8, 0.0, 7.1, 7.1, 13.6, 16.7, 12.5 |
| H2 vs `summary_clin` (E) | 0.0, −4.5, 0.0, 9.1, 0.0, 5.0, 11.1, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, −11.1, 0.0 |
| H3 (A) | −12.5, −17.5, −15.0, −5.0, −12.5, −17.5, −7.5, −5.0, −5.0, 0.0, −12.5, −2.5, −7.5, 0.0, −12.5, 2.5, −10.0, −7.5 |

What this says:

- **H1.** With recall over its stash, the stashed context answered as well as the full context: 0.889 against
  0.887, CI well inside the 5-point margin. Without the tool (`stashed_0`), questions whose answer was stashed
  dropped to 2/340, so the answers came from recall, not from what stayed in view.
- **H2.** Verbatim compaction beat the generic summary on exact values by 10.8 points. Against the clinical summary,
  the difference is 1.4 points and its CI includes 0, so the pre-registered claim fails. Both summaries are smaller
  than the stashed context (Sizes), so this is not a matched-budget comparison.
- **H3.** No arm ever chose A–E on an absent patient, so the check had nothing to prevent on `unans`. On answerable
  questions it cost 8.4 points of accuracy (Verifier).

## Secondary results (CIs, no pass claim)

| | Contrast | Difference | 95% CI |
|---|---|---|---|
| S1 | `stashed_t − stashed_0`, stash-dependent questions, A | +87.4 | +83.0 to +91.6 |
| S2 `ans_early` | H1 / H2 `summary_s` / H2 `summary_clin` / H3 A | −0.9 / +15.3 / 0.0 / −9.1 | −3.8 to +1.9 / +6.9 to +24.0 / −3.8 to +4.1 / −12.9 to −5.3 |
| S2 `ans_late` | H1 / H2 `summary_s` / H2 `summary_clin` / H3 A | +1.1 / +6.4 / +2.8 / −7.8 | −0.8 to +3.6 / +0.9 to +11.9 / −0.8 to +6.5 / −11.1 to −4.7 |
| S3 | `full_t − summary_s`, A / E | +12.7 / +11.5 | +8.8 to +17.2 / +6.6 to +15.9 |
| S3 | `full_t − summary_clin`, A / E | +1.3 / +2.2 | −0.5 to +3.1 / −0.3 to +4.7 |
| S3 | U, both summaries | 0.0 | 0.0 to 0.0 |
| S4 (substring rule) | H1 / H2 `summary_s` / H2 `summary_clin` / H3 A | 0.0 / +10.8 / +1.1 / −8.7 | −1.9 to +2.0 / +5.9 to +15.5 / −1.5 to +3.9 / −11.6 to −5.9 |

Under S4 every contrast lands on the same side of its criterion as under the letter rule. S6 (a second answerer) was not run.

## Recall behaviour (`stashed_t`, 53 sessions)

| | |
|---|---|
| R1 stash-dependent questions whose answer text was recalled | 0.965 (of 340) |
| R2 recalls that returned an answer text | 0.941 |
| R3 recall calls per session (all / successful) | 2.08 / 1.92 |
| R3 sessions with no recall / that hit the recall cap | 0.68 / 0.04 |
| R4 recalled tokens over stashed tokens | 0.106 |
| R5 restored context, median ratio to `C` | 0.608 |
| R6 recall errors | 8, all `cap` |

Every `ans_early` session recalled. The 36 sessions with no recall are all `ans_late` and `unans`, where the
answers were in view or absent.

## Verifier (`stashed_v`)

| | `ans_early` | `ans_late` | `unans` |
|---|---|---|---|
| Sessions re-asked | 16 of 17 | 18 of 18 | 0 of 18 |
| First-pass catches | 66 | 80 | 0 |
| Lines forced to F | 27 | 22 | 0 |
| Forced lines that were correct on the first pass | 25 | 22 | 0 |
| Lines correct, first pass → final | 293 → 268 | 321 → 295 | 360 → 360 |
| Lines gained / lost by the loop | 1 / 26 | 0 / 26 | 0 / 0 |

Catches split evenly between "quote not found" and "number not in quote" (33 + 33 early, 40 + 40 late). S5:
removing the patient-identity check changes no first-pass catch, because no catch came from it. On answerable
questions the loop mostly turned right answers into F: 47 of its 49 forced lines had been correct.

## Sizes and token use

- `C` (full contexts, pooled): 2,898,882 tokens. `C'` (stashed): 1,596,613 (0.551 of `C`). Summary contexts:
  `summary_s` 635,015, `summary_clin` 1,237,121.
- Restored context (`C'` plus recalled tokens), median ratio to `C`: 0.608.
- Cumulative usage on the kept sessions (input + output over every call the arm needs, summarizer included):

| Arm | Tokens | vs `full_t` |
|---|---|---|
| `full_t` | 5,818,055 | 1.00 |
| `stashed_t` | 4,680,613 | 0.80 |
| `stashed_0` | 3,312,618 | 0.57 |
| `summary_s` | 8,375,754 | 1.44 |
| `summary_clin` | 14,222,255 | 2.44 |
| `stashed_v` | 7,344,489 | 1.26 |
| `none` | 72,834 | |

  Usage over every call, dropped session and split retries included, is in `results.json`
  (`sizes.cumulative_usage_tokens`). Split replies: `summary_clin` 11, `summary_s` 1.
- The context sizes, the restored context and the recall token figures use lcc's offline heuristic counter
  (Amendment 2). Cumulative usage comes from the CLI envelopes, which count tokens exactly.

## Dropped session

`patient_12__ans_early` was dropped from every arm. Its `summary_clin` summary failed 5 attempts: the
summarizer's request was stopped by the provider's `reasoning_extraction` classifier. **This is a deviation from
V2.** V2 drops a session only for infrastructure failures (a transport error, a CLI crash or a usage limit), and a
classifier stop is none of these. The frozen harness counts any failed final attempt as terminal, so it dropped
the session. The verdicts above are the harness's.

Scored as V2 reads, the session stays and `summary_clin` is wrong on all 20 of its questions. That re-score was
done offline, with the harness's own scoring and bootstrap on the cached answers and no model call. The verdicts
do not change:

- H1 +0.1 (−1.8 to +2.1);
- H2 vs `summary_s` +11.0 (+6.1 to +15.5);
- H2 vs `summary_clin` +2.8 (−0.8 to +7.2).

## Limits

- One run, one answerer model and one summarizer model. S6 was not run.
- `none` at 0.597 means some questions can be answered without the records. Whether accuracies would be lower on
  unseen records is not tested here.
- UA was 0 in every arm, so this run cannot show whether the verifier prevents unsupported answers.
- 18 clusters: a percentile bootstrap can cover less than 95%. The per-patient differences above let a reader check.
- No credit valuation. Amendment 3 asked for one; Amendment 4, made after scoring, leaves it out. Calls and tokens
  are reported above (Setup, Sizes and token use).
