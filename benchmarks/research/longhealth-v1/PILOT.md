# LongHealth v1 pilot report (2026-11-03)

The pilot ran on the 2 pilot-pool targets only (6 sessions), as the protocol's run order says. These patients never
enter D. The numbers below come from 2 clusters, so they show what the harness and the arms do; they are not
estimates. `gateClaim` (2026-11-03) labels every finding below INFERIDO as general behaviour: each is one pilot
measurement, not a repeated one. No record text, question or option appears here (data use, PROTOCOL.md).

Setup: LCC at `cab0da0` (1.3.0; `src/` identical to `main` `4ec9069`), run from a detached worktree with a clean
tree. Answerer Claude Sonnet 5.5, summarizer Claude Opus 5.5, subscription `claude -p`. 60 calls of the 650 cap.
Weekly plan usage went from 29% to 33%, this session's own use included.

## Gates

| Gate | Pilot |
|---|---|
| V1 `full_t` A ≥ 0.60 | pass (62/80 = 0.775) |
| V2 drops ≤ 5% | pass (0 dropped; see finding 1: both `ans_early` S-clin summaries needed 3 attempts) |
| V3 `ans_early` stash-dependent ≥ 80% | pass (40/40) |
| V3b `ans_late` in view ≥ 80% | pass (40/40; `unans` 40/40 absent) |
| V4 recall through the CLI | pass (1 call) |
| V5 parse ≥ 95% | pass (0 response failures in any arm) |
| V6 not contaminated | pass, close: `none` 25/40 = 0.625 against the line `full_t` A − 0.10 = 0.675 |

The builder gave 12–25 stashed reads per session with no stash violation. Context: full 52–56k tokens per session,
stashed 23–38k (0.43–0.73 of full).

## Accuracy (counts; descriptive)

| Arm | A (answerable) | E | U (`unans` → F) | UA |
|---|---|---|---|---|
| `none` | 25/40 | 12/20 | n/a | n/a |
| `full_t` | 62/80 | 32/40 | 40/40 | 0/40 |
| `stashed_t` | 46/80 | 23/40 | 40/40 | 0/40 |
| `stashed_0` | 30/80 | 15/40 | 40/40 | 0/40 |
| `summary_s` | 54/80 | 29/40 | 40/40 | 0/40 |
| `summary_clin` | 62/80 | 31/40 | 40/40 | 0/40 |
| `stashed_v` | 42/80 | 21/40 | 40/40 | 0/40 |

By condition, `stashed_t − full_t` is 0.00 in `ans_late` (target in view) and −0.40 in `ans_early` (target stashed;
per patient −0.05 and −0.75). Recall: half of the sessions made no recall call (R3 share zero 0.5); 1 in 6 hit
the cap of 8 calls; precision 0.43. The tool's effect on stash-dependent questions (S1) was +0.375 (per patient
+0.75 and 0.00).

Cumulative usage (input + output tokens, all calls): `full_t` 665k, `stashed_t` 663k, `stashed_0` 386k,
`summary_s` 972k, `summary_clin` 2,532k, `stashed_v` 901k. For `summary_clin` that is 1,322k in the final cache plus
1,210k for the four split summary attempts (finding 1) and the two answers given from the broken summaries; those
attempts ran before the harness kept `retry_tokens`, so they were summed by hand from the set-aside files and the
envelope log. Recall turns resend the context, so `stashed_t` costs what `full_t` costs here.

## Findings

1. **A summary reply split over two turns (harness change).** With no tools a `claude -p` reply has one turn.
   In 4 of 6 `summary_clin` attempts in `ans_early` the CLI returned two turns, and `result` held only the second:
   a ~600-character note that the summary had been cut, and in one case that it would not be written again. The
   envelopes say `end_turn`, a 128,000-token output limit and one model (Opus 5.5). One cut came after ~25k
   thinking tokens and under 1k of text, so the output cap does not explain it. The cause is not identified.
   `summary_s` (0/6) and `summary_clin` in `ans_late` and `unans` (0/4) never split. The harness now treats such a
   reply as an infrastructure failure: it retries it, keeps the attempt's tokens in the arm's cost, and logs the
   envelope without its text. It also sets `CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000`. Both `ans_early` sessions
   succeeded on their third attempt, the last one V2 allows.
2. **H3 is at the floor.** Every arm answered F on all 40 `unans` questions, so UA(`stashed_t`) is 0 and H3's
   first criterion (CI upper bound of UA_v − UA_t below 0) cannot be met. The verifier also never caught a quote
   from another patient's records: the answerer did not mix patients.
3. **The verifier does not separate right from wrong answers here.** Over the first-pass lines of `full_t`,
   `stashed_t` and `stashed_v`:
   - the number check flagged 40 lines (15 `full_t`, 11 `stashed_t`, 14 `stashed_v`), of which 35 were right;
   - the quote check flagged 18, of which 15 were right;
   - of the 119 lines that passed, 14 were wrong (12%), against 8 of the 58 lines caught (14%).

   The number check fails right answers in three ways:
   - options that state several facts, when the model quotes one;
   - dates written differently in the option and the record (a two-digit year, or a timestamp against a
     month/year);
   - values the option computes from the record, such as a change between two scores.

   In `stashed_v`, the re-asks turned 5 right answers wrong and fixed none.
4. **Stashed loses where the target is stashed because the model often does not recall.** In `ans_early` the
   target's records are all pointers, and the patient's name is inside the removed text. In one of the two
   `ans_early` sessions the model made no recall call and answered F to all 20 questions. LCC's opt-in
   `pointer="lean"` would not help: the first line of all 133 LongHealth record texts is a salutation with no name.
   This is the treatment's behaviour, so the pilot does not tune Q-T or the builder for it.

## Harness changes after the pilot (all before the freeze)

- `cli()`: a reply split over turns with no tools raises `InfraError`, with the attempt's tokens and an envelope log
  (`split-envelopes.jsonl`, no text). The cached result records `stop_reason` and the models used.
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000` is set for every call. The CLI clamps it to the model's upper limit.
- `cached()` carries the rejected attempts' tokens (`retry_tokens`), and cumulative usage counts them (Codex review
  finding).
- `LONGHEALTH_PAUSE_AT=<n>` stops the driver before call n, so D can run in chunks between plan-usage checks. The
  rerun resumes from cache.
- 16 tests pass, and `ruff check .` is clean.

## Decisions for the owner before the freeze

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | H3 is at the floor | (a) H3 becomes descriptive and `stashed_v` stays in D as a secondary; (b) drop `stashed_v` from D (saves ≤ 108 calls) | (a): what the verifier costs on answerable questions is itself a result |
| D2 | Number check | (a) keep it as pre-registered; (b) drop check 3 before the freeze | (a): changing it after seeing its pilot effect is the tuning the risk table rules out |
| D3 | Split summaries | (a) up to 5 attempts for summary calls and the split rate reported per arm; (b) keep 3 attempts and accept the risk of V2 drops in `ans_early` | (a). At the pilot's split rate (4 of 6 `ans_early` S-clin attempts, 0 of 10 other summary attempts) D needs about 36 extra calls, about 600 of the 650 cap in all. The worst case is 4 extra on each of the 108 summaries (+432); the cap then stops the run, and the sessions it leaves count as V2 drops |
| D4 | Stashed loses on `ans_early` | (a) run D as pre-registered and publish the result, likely an H1/H2 FAIL with the cause (no recall); (b) first build an LCC pointer that tells the model what a removed text is about, release it, then re-pin and re-pilot | Owner's call: (a) is the honest v1 and costs an estimated 34% of a week's plan (pilot: ~4% for 60 calls); (b) is product work and a v2 study |

The owner chose D1–D3 as recommended and D4 (b) on 2026-11-04; they are recorded as Amendment 1 in `PROTOCOL.md`.

## Re-pilot with head pointers (2026-11-04)

LCC gained an opt-in `head` pointer (lucasmartins-ai/lcc#138, pinned here at `9d1406c`). It is lean's fields with the
first line replaced by the opening of the removed text, at most 160 characters across lines. The pilot sessions were
compacted again with it. The same reads were stashed, the location receipt was unchanged (40/40/40), and head
pointers named the right patient in 115 of 115 stashed records.

`stashed_t`, `stashed_0` and `stashed_v` (with its re-asks) were rerun: 22 calls, 82 of the cap in all. Every other
arm was reused. The plain-pointer answers are kept beside them.

| Arm | A, plain | A, head | E, plain | E, head |
|---|---|---|---|---|
| `full_t` (reused) | 62/80 | 62/80 | 32/40 | 32/40 |
| `stashed_t` | 46/80 | 61/80 | 23/40 | 31/40 |
| `stashed_0` | 30/80 | 31/80 | 15/40 | 16/40 |
| `stashed_v` | 42/80 | 57/80 | 21/40 | 28/40 |
| `summary_s` (reused) | 54/80 | 54/80 | 29/40 | 29/40 |
| `summary_clin` (reused) | 62/80 | 62/80 | 31/40 | 31/40 |

- `stashed_t − full_t` moved from −0.20 to −0.0125. By condition, `ans_early` moved from −0.40 to −0.025 (per
  patient 0.00 and −0.05), and `ans_late` stayed at 0.00.
- Recall: questions whose answer needed a recall got one in 95% of cases (was 40%), and recall precision rose from
  0.43 to 0.87. The tool's effect on stash-dependent questions (S1) rose from +0.375 to +0.75. Without the tool
  (`stashed_0`), head pointers alone added 1 question.
- Cost: `stashed_t` used 584k tokens in all, against 665k for `full_t`. C′ grew from 180k to 185k tokens.
- On E, `stashed_t` was 0.05 above `summary_s` and level with `summary_clin`.
- The verifier still cost answers: `stashed_v` scored 57 against `stashed_t`'s 61, and UA was 0 in every arm.

`gateClaim` passes the headline (46/80 → 61/80, with full context at 62/80) as a measurement of these 6 sessions.
It is in-sample: the pointer was designed after seeing these sessions, on 2 clusters. Only D, on 18 patients the
design never saw, can say whether it holds.

D has not been built, compacted or run. Nothing is frozen.
