# LongHealth v1: do verbatim compaction and a deterministic check hold up on clinical records? (draft 2026-11-03)

**Status: binding draft, not frozen.** The owner approved the route and cap on 2026-11-03 (Run order, step 2), so the
hypotheses, gates and criteria above the Amendments can now change only by a dated amendment. The harness freeze
(step 4) is still to come. Record texts, questions, options and answers never enter this repository (see Data use); only counts,
aggregates and per-item 0/1 scores keyed by ids do. Results are tagged INFERIDO until `gateClaim` returns PASS on
them.

## Why

The three studies in [`docs/EVIDENCE.md`](../../../docs/EVIDENCE.md) share one limit: every item came from the
maintainer's own coding sessions. They also leave open the first question in
[`research/limitations.md`](../../../research/limitations.md): the MSI `msi` arm protected facts with oracle carrier
labels, and without them nothing showed that verification helps.

This study changes three things at once and says so:

1. **Public data that is not ours.** LongHealth (Adams et al., *J Healthc Inform Res* 9(3), 2025; arXiv
   2401.14490): 20 fictional patients, 5,090 to 6,754 words of records each, 20 multiple-choice questions each.
   Anyone can rerun it.
2. **A domain where exact values matter.** Doses, lab values and dates are the detail `probe-eval-v1` saw a summary
   lose (exact values 0.73 against 0.98 for full context, owner-attested).
3. **A verifier with no oracle.** The check below reads only the session's own bytes and the record system's
   folder-to-patient map. It never sees the correct option or LongHealth's answer locations.

What it cannot show: anything about real patients, real clinical work, or a model's clinical judgement. The patients
are fictional and the benchmark's authors say it must not be used for clinical decisions.

## Data

- Source: `github.com/kbressem/LongHealth` at commit `479922279ce8fa528fe2cd87d854c6a2f8365d21` (Apache-2.0),
  file `data/benchmark_v5.json`, git blob `76bf80d37f321408a0e3f421a2e2d7ef59e97c1e`, 4,429,723 bytes. The
  harness downloads it into the private root and refuses to run if the blob hash differs.
- Each patient has `texts` (`text_0` … `text_n`), `name`, `birthday`, `diagnosis` and 20 `questions`. Each question
  has options `answer_a` … `answer_e`, `correct` (the text of the correct option) and `answer_location` (the texts
  that hold the answer).
- As in LongHealth's tasks 2 and 3, every question gets a sixth option, **F: "Question cannot be answered with
  provided documents"**, in every condition and arm.
- **Pilot pool:** 2 patients drawn with `random.Random(20261103)` from the sorted patient ids. They are never
  targets in D. They may appear as distractor patients.
- **D:** the other 18 patients as targets, 18 × 20 = 360 questions per condition.

## Sessions

LongHealth puts all documents into one prompt per question. An agent instead reads records over a session and is
asked about them later, and that is the case compaction is for. The builder therefore turns each item into a
Claude Code JSONL transcript `C` plus one request `P`. Its rules are fixed here, before the pilot.

- **Patients per session: K = 6.** Distractor patients are drawn with `random.Random(f"{target}:{condition}")`
  from all other patients, pilot pool included.
- **Conditions per target:**
  - `ans_early`: the target is reviewed first, then 5 distractors;
  - `ans_late`: 5 distractors, then the target last;
  - `unans`: 6 distractors and no record of the target. The correct answer to every question is F.
- **Folder ids.** Each patient in a session gets a two-digit id drawn without replacement by the session's seed.
  Files are `records/p<id>/text_<n>.txt`. Neither folder names nor file names contain a patient's name.
- **Messages.**
  - The first user message is fixed: `Chart review for today's multidisciplinary meeting: six patients, folders
    records/p<id> in the order listed. Read every record of each patient, in order.` It lists the six folders.
  - For each patient, for each text in id order: one assistant message with a single `Read` call on that file, and
    its tool result with the text's exact bytes.
  - The call input is exactly `{"file_path": "records/p<id>/text_<n>.txt"}`: a relative path, with no `offset`,
    `limit`, `cwd` or `workdir`. No transcript entry carries a `cwd` field either. Absolute paths change which
    reads lcc's `recoverable` rules replace, whatever their age (Codex review, 2026-11-03).
  - No assistant prose anywhere. The only way to learn a fact is from a record.
- **`P`** opens with `Questions about <name>, born <birthday>:`, then the patient's 20 questions, numbered, with
  options A–F, then the answer format. One call answers all 20.

This turns LongHealth's per-question protocol into a per-session one, so numbers here are **not comparable with the
LongHealth paper's tables**.

## Compaction

- LCC at the pin recorded at freeze (today `origin/main` `cab0da0`, release 1.3.0). It runs offline from a detached
  worktree with a clean tree.
- Settings: `provider="rules"`, `rules_mode="stashed"`, the default `preserve_recent` (6), no `workspace_root`,
  plain pointers. (Amendment 1: `head` pointers.)
- **Compaction is query-blind.** `question` is the same fixed text for every session: `Answer questions about one
  patient from today's list.` It names no file, patient or value. So stashing, like the summary writers, never
  sees `P`, and H2 compares the two compactions with the same access.
  - In real use lcc gets the current request as its goal, and a goal that names a file keeps that file
    (`named_in_goal`). Leaving that out makes `stashed` weaker here, not stronger.
  - The query-aware variant is out of scope for v1.
- What that means for these sessions (`transcript_rules.py` at the pin):
  - A record read becomes eligible as `stale_read_far_from_recent_work` when it is more than 40 messages from the
    end of `C`.
  - Reads inside the last 40 messages stay, and so do the newest 6 messages (pinned) and the latest tool result.
  - A read whose text matches lcc's `ERROR_RE` (`Error`, `ERROR`, `FAIL`, `FAILED`, `Exception`, …) is never
    stale.
  - The first message is pinned, but its folder list does not count as a recent turn (`message_index 0` is
    excluded).
  - `recoverable` decisions are also eligible. The location receipt records the lcc reason for every stashed read.
    V3b checks that reads near the end really stay in view.
- One stash directory per session (`LCC_STASH_DIR=<private>/stash/<session>`), so a session can only recall its own
  blobs.
- Two checks run on every output:
  - lcc's `verify_stashed`;
  - an independent check in the harness that uses no lcc code: it re-hashes every blob and compares it with the
    original result bytes.

  A violation is scored as a treatment failure (Scoring) and reported.
- **Gold location, computed from `C`, `C'` and LongHealth's `answer_location` before any answer exists.** A
  question is **stash-dependent** when every text in its `answer_location` became a stash pointer in `C'`, and
  **in-view** when none did. Counts per condition go into `location-receipt.json`, committed before any arm runs.
- **Exact-value stratum E:** questions whose correct option text contains a digit, fixed from the gold before any
  answer exists.

## Arms

All answering arms use the same answerer (Claude Sonnet 5.5, medium effort, subscription `claude -p`), the same
session order, and the same answer format. CLI isolation is as in `stashed-recall-v1`: no other tool, no settings or
CLAUDE.md, and ANTHROPIC_* variables stripped.

| arm | context | tool | role |
|---|---|---|---|
| `none` | the 20 questions with options A–E only, text Q-N, one call per target patient | none | memorisation check (V6) |
| `full_t` | `C` unchanged | `recall`, stash empty | reference for H1 and H3 |
| `stashed_t` | `C'` (stashed) | `recall` over the session's stash | treatment for H1 and H2 |
| `stashed_0` | the same `C'` | none | isolates what `recall` buys (S1) |
| `summary_s` | summary of `C` by text S, then re-attach | none | general agent compaction, H2 |
| `summary_clin` | summary of `C` by text S-clin, then re-attach | none | domain-fair compaction, H2 |
| `stashed_v` | `C'`, with the verifier loop below | `recall` | treatment for H3 |

**Summary arms.**
- Claude Opus 5.5 (high effort) writes the summary from the full `C`, and the `<analysis>` part is stripped.
- Then the 5 most recently read files are re-attached, ≤ 5,000 tokens each and ≤ 50,000 in all. This is the
  `probe-eval-v1` native arm step for step, which favours the summary.
- Text S is reused from `probe-eval-v1` unchanged (frozen, sha256
  `ea72d62fb0091811dce1ffcc8f2decbb08a028e8790cbbc6f6250399275550e6`).
- S is written for coding sessions, so S-clin (below) is added. Without it a reviewer could fairly say the summary
  never asked for the values.

### Q-T — answerer instructions (draft; sha256 recorded at freeze)

```
You are continuing a chart-review session. The context above is everything you have from the session so far; parts of it may have been compressed. Some old tool results were replaced by a marker of the form [removed: N lines, S KB · lcc recall <id>]. If you have the recall tool, it returns the exact removed text for an id; use it when an answer depends on removed text, and do not recall text you do not need. For each numbered question, choose one option from A to F. Answer on one line per question, in this form:
<number>: <letter>: <exact option text> | quote: "<words copied exactly from a record that support the option>"
You may give up to three quotes, separated by " | quote: ". Each quote must be at least 20 characters copied exactly from one record. For option F, write no quote. Choose F when the records you have do not answer the question about this patient.
```

`stashed_0` and `summary_*` get the same text with the recall sentence removed (Q-0, hashed at freeze). Every
record-reading arm, `full_t` included, must quote, so the quote rule is held constant and is not the treatment.

### Q-N — memorisation check (`none` only; sha256 recorded at freeze)

```
You have no records for this patient. Answer each numbered question from what you know, choosing one option from A to E even if you are unsure. Answer on one line per question, in this form:
<number>: <letter>: <exact option text>
```

`none` offers no F and asks for no quote, so a model that memorised LongHealth can show it. Chance is 0.20.

### S-clin — clinical summary instructions (draft; sha256 recorded at freeze)

```
Write a summary of this chart review that will replace it. Work will continue from your summary alone. First reason inside <analysis> tags (this part is removed), then write <summary>. For each patient folder: the patient's name and date of birth as written; every diagnosis with its date; every treatment with drug, dose, route, schedule and dates; every lab, imaging and pathology value with its unit and date; procedures, complications and outcomes with dates; and anything recorded as absent, negative or not done. Copy names, numbers, units and dates exactly as they appear.
```

## Verifier (`stashed_v` only)

This is MSI's `verify-1.0` fact-containment layer and bounded escalation, specialised to this task and implemented
in the harness in about 60 lines. It does not call the MSI planner. It reads `C` (local bytes, the same bytes the
stash holds) and the folder-to-patient map, which is system metadata any record system holds: the answerer is never
shown it, and it is not the gold.

For each answer line that is not F, all three checks must pass:

1. **Quote exists.** After whitespace is collapsed, each quote is ≥ 20 characters and occurs verbatim in one record
   text read in this session.
2. **Right patient.** Every quote occurs in a record in the folder of the patient `P` names. A quote from another
   patient's record fails the line, even when other quotes are right.
3. **Numbers supported.** Every number token in the chosen option text (`[0-9]+([.,][0-9]+)?`, comma read as a dot)
   occurs among the number tokens of the quotes. By check 2, those quotes all come from the target patient's
   records.

Escalation:
- If any line fails, the answerer gets **one** re-ask in the same session, with the tool. The re-ask lists the
  failing question numbers and the failed check for each ("quote not found", "quote is not from this patient's
  records", "number not in quote"), and never the right option.
- A line that fails again becomes F (abstain).
- The re-ask answers replace only the failing lines.

Every catch, re-ask and forced F is logged with the check that caused it.

## Scoring (mechanical, no judge)

- The chosen letter is parsed from each line. **Correct iff the chosen option is the correct one**: in the
  answerable conditions the option whose text equals `correct`, in `unans` option F.
- A line that does not parse is wrong, and counted. A refusal, an empty answer and a missing line are wrong too.
  A model's failure to answer is an outcome, never a reason to drop the item.
- A session whose `stashed` output fails either stash check is scored wrong on every question in the stashed arms,
  and reported. A broken lcc contract is a treatment failure.
- LongHealth's own rule (the correct text occurs in the answer) is a sensitivity analysis only (S4). Here it would
  be wrong, because a quote can contain the correct option's text while a different letter was chosen.

## Metrics

- **A**: accuracy on `ans_early` + `ans_late`.
- **U**: accuracy on `unans`, the share answered F.
- **Unsupported-answer rate (UA)**: on `unans`, the share of lines that chose an option from A to E about a patient
  with no record in the session. This is not 1 − U. Response failures (refusal, empty, missing or unparseable line)
  are wrong for U, but they are not unsupported answers. They are reported separately, per arm and condition.
- **E**: accuracy on stratum E within A.
- **Tokens**:
  - `C` and `C'` (pooled) and summary size.
  - **Restored context**: `C'` plus recalled tokens, as a median ratio to `C`. This is a size, not a cost.
  - **Cumulative usage per arm**: input and output tokens summed over every call the arm needs, from the CLI
    envelopes. That includes each tool turn inside an answer, the verifier's re-ask and, for the summary arms, the
    summarizer call. This is the cost figure.
- **Recall behaviour**: R1–R6 as defined in `stashed-recall-v1`, with "gold" read as "a text in the question's
  `answer_location`".
- **Verifier**: catches per check, re-asks, forced F, and what a forced F did. It was right on `unans` lines and
  wrong on answerable ones, and its accuracy changed relative to the first-pass line.

## Hypotheses and pass criteria (declared before any answer)

**Statistics.**
- Paired cluster bootstrap over the 18 target patients, 2000 resamples, seed `20261103`. All of a target's
  questions in all conditions resample together.
- Every contrast also reports the 18 per-patient differences. With 18 clusters a percentile bootstrap can cover less
  than 95%, and the per-patient differences let a reader check that.

**Validity gates.** If any fails, the run is *invalid* and no H verdict is given; the numbers are still published.
- V1: `full_t` A ≥ 0.60.
- V2: a call that fails for infrastructure reasons is retried, after a reset when the reason is a usage limit, up
  to 3 attempts. Infrastructure means a transport error, a CLI crash or a usage limit, never a model answer. A
  session still failing is dropped from every arm and counted, and at most 5% of D sessions may be dropped.
  Refusals and bad answers are scored, not dropped (Scoring).
- V3: in `ans_early`, ≥ 80% of questions are stash-dependent (from `location-receipt.json`). If the pilot shows this
  will fail, the builder changes by amendment before the freeze, never after.
- V3b: in `ans_late`, ≥ 80% of questions are in-view, so the late condition is a real in-view control. Questions
  whose answer texts are partly stashed and partly in view are counted and reported as **mixed** in both
  conditions.
- V4: through the CLI path, a scripted `recall` of a known id returns its bytes.
- V5: ≥ 95% of answer lines parse in every arm.
- V6 (contamination): LongHealth has been public since 2024 and may be in the answerer's training data.
  - If `none` accuracy (Q-N, A–E) is ≥ `full_t` A − 0.10, the run is reported as contaminated and H1–H3 become
    descriptive.
  - Otherwise `none` accuracy is reported next to every result, with chance (0.20) beside it.

**H1 (primary, non-inferiority).** `stashed_t` is not worse than `full_t` on A.
- PASS iff the lower bound of the 95% CI of `stashed_t − full_t` is > −0.05.
- Reported with restored context and cumulative usage next to it.

**H2 (primary, verbatim against summary on exact values).** On E, `stashed_t` beats both summaries.
- PASS iff the CI lower bounds of `stashed_t − summary_s` **and** `stashed_t − summary_clin` are both > 0.
- This is not a matched-budget comparison. The summaries are smaller, and both sizes are reported.

**H3 (primary, the deterministic check; descriptive since Amendment 1).** On `unans`, `stashed_v` gives fewer unsupported answers than `stashed_t`
without costing more than the margin on answerable questions. PASS iff both:
- the CI upper bound of UA(`stashed_v`) − UA(`stashed_t`) is < 0. Fewer refusals or formatting failures cannot
  meet this; only fewer A–E choices about absent patients can.
- the CI lower bound of A(`stashed_v`) − A(`stashed_t`) is > −0.05.

U and response failures are reported next to H3.

**Secondaries (CIs, no pass claim).**
- S1: `stashed_t − stashed_0` on stash-dependent questions (what the tool buys), and R1–R6.
- S2: every primary contrast split by `ans_early` and `ans_late`. In `ans_late` the target's records are mostly in
  view, so stashed should match full there. In `ans_late` the summary arms also get the target's files back through
  re-attach.
- S3: `full_t` against `summary_s` and `summary_clin` on A, U and E.
- S4: A, U and E under LongHealth's substring rule.
- S5: the verifier replayed offline on `stashed_v`'s first-pass lines with check 2 removed. This needs no model
  call. It says how many **first-pass catches** depend on the patient-identity check, and nothing about H3's final
  accuracy without it: the re-asks and forced F of an ablated loop were never run. On `unans` every non-F line
  fails check 2 by construction, so the S5 counts there are reported split by check 1 and check 3.
- S6: `full_t` and `stashed_t` with a second answerer from another model family. Run only by amendment and only if
  the budget allows.

**Power (INFERIDO).**
- n = 360 questions per condition in 18 clusters.
- With a per-question SD of paired differences of 0.35 and a design effect of about 2, the CI half-width on A (720
  questions) is about 0.036, and on U and UA (360) about 0.051.
- H1's margin can be met if the true loss is near 0. H3's second part has less room. The CIs are reported either
  way.

## Leakage controls

| leak | control |
|---|---|
| Builder tuned to make stashed win | Rules fixed above before the pilot; the pilot can only change them by a dated amendment, before the freeze. |
| Gold seen by an arm or the verifier | No arm and no verifier check reads `correct` or `answer_location`; those are read only by scoring and by the location and E receipts. |
| Folder ids hinting the target | Ids are random per session; names appear only inside records and in `P`. |
| Verifier hinting the answer | Re-ask texts name the question and the failed check, never an option. |
| Cross-session recall | One stash dir per session; the tool refuses ids outside it. |
| Training-data contamination | `none` arm and V6; all contrasts are paired, so contamination raises every arm. |
| Tuning on D | Pilot only on the 2 pilot-pool targets; code fixes only after it. |
| Summary favoured or disfavoured | Opus writes it from full `C`, recent files re-attached, and a clinical text S-clin in addition to S. |
| Compaction sees the questions | Neither compaction sees `P`: stashing gets one fixed goal, the summarizers get `C` only. |
| Refusals hiding losses | A refusal or unparseable line is scored wrong; only infrastructure failures drop a session (V2). |

## Data use

LongHealth's authors ask that examples not be shared publicly, to keep them out of training sets. So:
- record texts, questions, options, summaries, recalled text and answers live only under the private root
  `~/.lcc/bench/longhealth-v1/`;
- the repository gets the harness, receipts with counts and hashes, `results.json` with aggregates, and per-item 0/1
  scores keyed by `(patient_id, question_no, condition, arm)`;
- no data from this study is used to train or tune any lcc ranker or judge.

## Budget (owner approval required before the pilot)

Subscription route, $0 cash, hard cap **650 CLI calls**.
- Pilot: 2 targets × 3 conditions = 6 sessions × (6 answering arms + 2 summaries + ≤ 1 re-ask) + 2 `none` ≈ 56.
- D: 54 sessions × 6 answering arms = 324; summaries 2 × 54 = 108; re-asks ≤ 54; `none` 18. Total ≤ 504.
- Total ≤ 560, under the cap. Tool turns add tokens, not calls; cumulative usage reports them.
- Infrastructure retries (V2) count against the cap.
- S6 is not in this budget.

Usage-limit stop: wait for the reset and resume from cache. Transport errors get 1 retry. Only one driver runs at a
time. It takes a lock file, and a second driver refuses to start (the `stashed-recall-v1` Amendment 4 incident).

## Run order

1. This file committed as draft.
2. Owner approves the route and cap (dated line here).
   **Approved 2026-11-03 by the owner: subscription CLI, $0 cash, hard cap 650 calls, harness and pilot next**
   ("I approve", in reply to "Do you approve the study's route and cap (650 calls on the subscription, $0)?").
3. Harness and tests in `benchmarks/research/longhealth-v1/`: builder, compaction runner, independent stash check,
   recall shim, verifier, scorer. Pilot on the 2 pilot-pool targets.
4. Freeze amendment: LCC pin, sha256 of the harness, Q-T, Q-0, Q-N, S-clin and the green test log.
5. Build and compact D, verify, write and commit `location-receipt.json` and the E receipt.
6. Run the arms, summaries first, then `stashed_v`'s re-asks.
7. Score: `RESULTS.md` and `results.json`, and run `gateClaim` on the headline numbers. Publish whatever the verdicts
   are, including a run voided by a gate.

## Amendments

### Amendment 1 (2026-11-04, after the pilot, before the freeze)

The pilot (`PILOT.md`) left four decisions to the owner. The answer, verbatim: "concordo com d1 - d3 e prefiro que
constuir um ponteiro" (D1–D3 as recommended in `PILOT.md`, and D4 option (b)).

- **D1. H3 becomes descriptive.** In the pilot, UA was 0/40 in every arm, so H3's first criterion could not be met.
  `stashed_v` stays in D, and its UA, U, A against `stashed_t`, the verifier's catches, re-asks and forced F are
  reported with CIs and no pass claim. H1 and H2 are unchanged.
- **D2. The verifier is unchanged.** Its three checks stay as written, though the pilot showed the number check
  flagging right answers. Changing it after seeing its pilot effect is the tuning the risk table rules out.
- **D3. Summary calls get up to 5 infrastructure attempts; other calls keep 3.**
  - A reply with no tools that comes back over more than one turn counts as an infrastructure failure. The CLI
    resumed a cut reply and returned only its tail in 4 of 6 `ans_early` S-clin attempts.
  - Each attempt's tokens stay in the arm's cumulative usage, and split counts are reported per arm
    (`split_replies` in the results).
  - At the pilot's split rate D needs about 36 extra calls. The 650-call cap still binds: a run that reaches it
    stops, and the sessions it leaves count as V2 drops.
- **D4. The stashed arms use `head` pointers.** This is a new opt-in lcc pointer: the lean fields with the first
  line replaced by the opening of the removed text, at most 160 characters across lines.
  - In the pilot every record opened with a salutation. The plain and lean pointers therefore said nothing about
    whom a removed record was about. In one of the two `ans_early` sessions the model made no recall call and
    answered F to all 20 questions.
  - In the 6 pilot sessions, head pointers named the right patient in 115 of 115 stashed records.
  - The pointer reads only the stashed bytes. It never sees `P` or the goal, so compaction stays query-blind.
  - Q-T's marker description becomes `[removed: N lines, S KB · "<the opening of the removed text>" · lcc recall
    <id>]`. Q-0 follows Q-T, as before.
  - The LCC pin becomes the commit that ships `head`, recorded at the freeze.
- **Re-pilot.** `stashed_t`, `stashed_0` and `stashed_v` (with its re-asks) rerun on the same 2 pilot targets with
  head pointers. The other arms do not depend on the pointer and are reused. The plain-pointer pilot answers are
  kept beside them for comparison.
- **Clarifications from the harness**, recorded before the freeze:
  - The re-ask is a new call. It carries the first pass's prompt, the recalled texts exactly as the shim emitted
    them, the first answer and the failed checks.
  - `recall` is capped at 8 calls per answer and 20,000 tokens per call. A longer text returns its first tokens
    and a note to pass `lines`.
  - Transport retries: 2 per driver run, within each call's attempt limit.
  - Prompt order: context, then `P`, then Q-T (or Q-0).
  - V4 is one call.
  - Every call sets `CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000`.
  - `LONGHEALTH_PAUSE_AT` can stop the driver between calls; the next run resumes from cache.
- **Not changed:** D, the builder, the gates, H1, H2, scoring, the metrics and the cap.
