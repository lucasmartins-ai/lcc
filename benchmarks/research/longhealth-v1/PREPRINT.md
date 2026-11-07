---
title: "Verbatim compaction with recall for agents that read long clinical records: a pre-registered study on LongHealth"
author: "Lucas Martins, LookADev (veterinary medicine graduate)"
date: "Draft of 7 November 2026"
keywords: [context compaction, LLM agents, clinical question answering, pre-registration, LongHealth]
abstract: |
  Coding agents compact their context when a session outgrows the window, and the usual method has a model summarize
  the session. A summary can lose the exact values a later step needs. lcc (Local Context Compiler), an open-source
  tool, moves old tool outputs into a local content-addressed stash, leaves a short pointer in their place, and gives
  the agent a `recall` tool that returns the removed bytes unchanged. I tested it on LongHealth, a public benchmark of
  20 fictional patients with long clinical records and multiple-choice questions. Each test item became a Claude Code
  session in which the agent reads the records of six patients and then answers 20 questions about a target patient.
  In two conditions the target is one of the six. In the third the target's records are absent, and the correct answer
  is always F, the option for a question the records cannot answer. That gives 18 target patients in three
  conditions, 54 sessions, 53 of them scored. I committed the protocol, gates, hypotheses and analysis before the
  pilot, and froze the harness, prompts and lcc version by hash before any main-set call. The
  answerer was Claude Sonnet 5.5. Claude Opus 5.5 wrote two summaries per session, one from a generic prompt and one
  from a clinical prompt. The primary non-inferiority hypothesis H1 passed. With recall over its stash, the stashed
  context answered as well as the full context: 0.889 against 0.887, CI well inside the 5-point margin. The second
  primary hypothesis H2 failed. On questions whose correct option contains a number, the stashed arm beat the generic
  summary by 10.8 points (95% CI +5.9 to +15.5) and the clinical summary by 1.4 points (95% CI −1.2 to +4.1), and H2
  needed both lower bounds above zero. A deterministic quote check found no unsupported answers to prevent and cost
  8.4 points of accuracy. One session was dropped for a reason the protocol does not list; scoring it the way the
  protocol reads leaves both verdicts unchanged. The H2, verifier and token findings come from one run with one
  answerer model and carry the label INFERIDO (inferred).
---

<!-- Build: pandoc PREPRINT.md -o preprint.pdf --pdf-engine=xelatex --number-sections -V geometry:margin=2.5cm
     Numbers: pytest tests/test_longhealth_v1_preprint.py checks every figure here against results.json. -->

# Introduction

An agent that works through a long task reads more than its context window holds. Claude Code and Codex compact a
session when the window fills, and by default a model writes a summary that replaces what came before. The summary
is short, but every name, number and date in it has passed through a model that had to guess what the next step
would need. In an earlier study on my own coding sessions, a summary arm recalled exact values at 0.73 against 0.98
for the full context (owner-attested, `docs/EVIDENCE.md` in [6]).

lcc keeps the session's text and moves the bulk out of it. In its `stashed` mode it replaces an old tool output with
a pointer and writes the output's exact bytes to a local directory under their SHA-256 hash. A `recall` tool returns
those bytes and re-hashes them on read, so the agent gets back what was removed and nothing else. User and assistant
messages and tool-call inputs stay as they were.

My earlier evidence for lcc shares one limit: every item came from my own sessions, which hold client work and stay
private. This study changes three things. It uses public data that anyone can rerun. It works in a domain where exact
values matter: doses, laboratory values and dates. And it adds a verifier that never sees the correct answer or where
the benchmark locates it. I asked three questions and fixed a pass criterion for each before any main-set answer
existed:

- **H1.** Does the stashed context with `recall` answer as well as the full context?
- **H2.** On questions about exact values, does it beat a model-written summary, including one prompted for clinical
  detail?
- **H3.** Does a deterministic quote check reduce answers about patients whose records are absent? (Descriptive since
  Amendment 1.)

H1 passed and H2 failed. H3 sat at a floor: no arm chose an answer about an absent patient, so the check had nothing
to prevent. I report all three as the frozen harness scored them, together with four protocol amendments and one
deviation.

The study says nothing about real patients, real clinical work or a model's clinical judgement. The patients are
fictional, and the benchmark's authors state that it must not be used for clinical decisions.

# Related work

LongHealth [1] measures question answering over long clinical documents. It has 20 fictional patients with records of
5,090 to 6,754 words each and 20 multiple-choice questions per patient, and two of its tasks add an option for
questions the documents cannot answer. Its protocol puts all documents into one prompt per question. Here an agent
reads records across a session and answers later, so my numbers are not comparable with the LongHealth paper's tables.

Prompt-compression methods such as LLMLingua [2] and LongLLMLingua [3] drop tokens that a small language model scores
as uninformative. The output is shorter text, and the dropped tokens are gone. MemGPT [4] lets the model move content
between its context and external storage. lcc's stash sits closer to the second design, with two differences: fixed
rules decide what leaves the context, and `recall` returns the removed bytes exactly, checked by hash.

# Method

## Pre-registration and timeline

I wrote the protocol (`PROTOCOL.md`) before the pilot and committed it as a draft on 2026-11-03. It fixes the session
builder, the arms, the scoring rule, six validity gates, three hypotheses with pass criteria, the statistics and a hard
cap of 650 CLI calls. Every later change is a dated amendment that says what it changes and why.

Table: Protocol timeline. "Owner" in the protocol is the author.

| Date | Step |
|------------|---------------------------------------------------------------------------------------------------|
| 2026-11-03 | Protocol committed as a draft. I approve the route and cap: subscription CLI, no new cash, 650 calls. |
| 2026-11-03 | Pilot on the 2 pilot-pool patients (6 sessions), reported in `PILOT.md`. |
| 2026-11-04 | Amendment 1, after the pilot: H3 becomes descriptive, the verifier stays as written, summary calls get 5 attempts, the stashed arms use `head` pointers. Re-pilot of the stashed arms. |
| 2026-11-04 | Amendment 2, the freeze, before any main-set call: lcc pin, sha256 of the harness and of every prompt text, models, efforts and caps. |
| 2026-11-06 | Amendment 3, during the main set: the remaining calls bill API credits I already held instead of the subscription. Prompts, models and harness unchanged. |
| 2026-11-07 | Scoring. Amendment 4, after scoring: the credit valuation that Amendment 3 promised is left out. I decided this with the verdicts known. |

Amendment 1 changed the treatment, so it needs a closer look. In the pilot every record opened with a salutation.
Neither the plain pointer (line count and size) nor lcc's existing `lean` pointer (which adds the first line) said
whom a removed record concerned. In one of the two pilot sessions with the target stashed, the model made no recall
and answered F to all 20 questions. I added an opt-in pointer to lcc, `head`, that shows the opening of the removed
text across lines, capped at 160 characters, and pinned the commit that ships it. The pointer reads only the stashed
bytes and never the questions, so compaction stays blind to the query. With head pointers the pilot's stashed arm
went from 46/80 to 61/80 correct, with the full context at 62/80. That pilot gain is in-sample, because I designed the
pointer after seeing those six sessions. The 18 main-set targets were never pilot targets. Their records did appear as
distractors in pilot sessions, and a check of first lines read all 133 record texts, so the main set is not fully
unseen.

## Data

The harness downloads LongHealth from `github.com/kbressem/LongHealth` at commit `4799222` (Apache-2.0), file
`data/benchmark_v5.json`, into a private directory, and refuses to run if the file's git blob hash differs from the
protocol's. Each patient has record texts, a name, a birth date, a diagnosis and 20 questions with five options. As in
LongHealth's tasks 2 and 3, every question gets a sixth option, F, which says the provided documents cannot answer
it. A seeded draw put 2 patients in a pilot pool. They never serve as targets in the main set (set D), though
they may appear as distractors. The other 18 patients are the D targets.

LongHealth's authors ask that examples stay out of public text, to keep them out of training sets. No record text,
question, option, summary or answer appears in this paper or in the repository. The repository holds counts, hashes,
aggregates and per-item 0/1 scores keyed by patient, question number, condition and arm.

## Sessions

The builder turns each target and condition into a Claude Code JSONL transcript `C` and one request `P`. A session
holds 6 patients. Each patient gets a random two-digit folder id, and no folder or file name contains a patient's name.
The first user message asks for a chart review of the six folders in order. For every record, the transcript then holds
one assistant message with a single `Read` call on that file and a tool result with the file's exact bytes. The
transcript has no assistant prose, so the only way to learn a fact is from a record.

Each target has three conditions:

- `ans_early`: the target's records come first, then 5 distractor patients;
- `ans_late`: 5 distractors, then the target last;
- `unans`: 6 distractors and no record of the target, so F answers every question correctly.

`P` names the target by name and birth date and asks all 20 of its questions at once, with options A–F. That gives
360 questions per condition and 54 sessions.

## Compaction

lcc ran at commit `17d9595` (release 1.3.0, which includes the `head` pointer from `lucasmartins-ai/lcc#138`),
offline, from a detached worktree with a clean tree. The settings were `provider="rules"`, `rules_mode="stashed"`, the
default `preserve_recent` of 6, and `head` pointers. A stashed record becomes one line of this form:

```
[removed: N lines, S KB · "<opening of the removed text>" · lcc recall <id>]
```

Compaction was query-blind. Every session got the same goal text, which names no file, patient or value, so neither
the stash nor the summarizers ever saw `P`. In real use lcc receives the current request as its goal and keeps any file
the goal names, so this setting makes `stashed` weaker than it is in practice.

Under lcc's rules at the pin, a record read becomes eligible for the stash when it sits more than 40 messages from the
end of `C`. Reads inside the last 40 messages stay in view, and so do the newest 6 messages, the latest tool result
and any output that looks like an error. Each session gets its own stash directory, so a session can recall only its
own blobs. Two checks ran on every compacted session: lcc's `verify_stashed`, and an independent check in the harness
that uses no lcc code and re-hashes every blob against the original bytes. A failure in either would have scored the
session wrong in every stashed arm.

Before any answer existed, the harness worked out where each question's answer sits, from `C`, the compacted `C'` and
LongHealth's answer locations. A question is *stash-dependent* when every text that holds its answer became a pointer,
*in view* when none did, and *mixed* otherwise. The counts went into `location-receipt-D.json`, committed before any
arm ran. The same receipt flags the exact-value stratum E: questions whose correct option text contains a digit.

## Arms

Every answering arm used Claude Sonnet 5.5 at medium effort through `claude -p`, with the same session order and
answer format. The CLI ran isolated, with no other tool, no settings file or CLAUDE.md, and the `ANTHROPIC_*`
variables stripped.

Table: The seven arms.

| Arm | Context | Tool | Role |
|----------------|---------------------------------------------------|-----------------------------------|------------------------|
| `none` | the 20 questions with options A–E only | none | memorisation check |
| `full_t` | `C` unchanged | `recall`, empty stash | reference for H1 |
| `stashed_t` | `C'` | `recall` over the session's stash | treatment for H1 and H2 |
| `stashed_0` | `C'` | none | what `recall` adds (S1) |
| `summary_s` | generic summary of `C`, recent files re-attached | none | comparator for H2 |
| `summary_clin` | clinical summary of `C`, recent files re-attached | none | comparator for H2 |
| `stashed_v` | `C'`, plus the verifier loop | `recall` | H3 (descriptive) |

Every record-reading arm, `full_t` included, must back each non-F answer with up to three quotes of at least 20
characters copied from a record. The rule applies to all arms alike, which keeps it out of the treatment. `recall`
allows 8 calls per answer and 20,000 tokens per call.

Claude Opus 5.5 at high effort wrote each summary from the full `C`, and the harness stripped its reasoning section.
The harness then re-attached the 5 most recently read files, at most 5,000 tokens each and 50,000 in all. This copies
the summary arm of my earlier coding-session study step for step, and it favours the summary. The generic prompt S
comes unchanged from that study. S was written for coding sessions, so I added a clinical prompt, S-clin, that asks
for every diagnosis, treatment, dose, route, schedule, laboratory value, unit and date, copied exactly. Without S-clin
a reviewer could object that nobody asked the summary for the values.

## Verifier

The `stashed_v` arm adds a deterministic check of about 60 lines in the harness. It reads only the session's own bytes
and the folder-to-patient map, which any record system holds. It never sees the correct option or the benchmark's
answer locations. Every non-F answer line must pass three checks:

1. *Quote exists*: after whitespace is collapsed, each quote has at least 20 characters and occurs verbatim in a
   record read in the session.
2. *Right patient*: every quote comes from a record in the folder of the patient that `P` names.
3. *Numbers supported*: every number in the chosen option's text occurs among the numbers in the quotes.

If any line fails, the answerer gets one re-ask in the same session, with the tool. The re-ask names the failing
questions and the failed check, never an option. A line that fails again becomes F. Amendment 1 kept the three checks
as written, although the pilot showed check 3 flagging right answers: changing a check after seeing its pilot effect
is the tuning the protocol rules out.

## Scoring and metrics

Scoring is mechanical, with no judge. The harness parses the chosen letter from each line, and a line is correct when
it picks the correct option: the one whose text equals LongHealth's answer in the answerable conditions, and F in
`unans`. An unparseable line, a refusal and a missing line all count as wrong. LongHealth's own rule, that the correct
text occurs in the answer, serves only as a sensitivity analysis (S4), because a quote can contain the correct text
while the line picks another letter.

- **A**: accuracy on `ans_early` and `ans_late` together.
- **E**: accuracy on the exact-value stratum within A.
- **U**: share of `unans` questions answered F.
- **UA**: share of `unans` lines that chose an option from A to E, an answer about a patient with no record in the
  session. Response failures count against U but not as UA.
- **Tokens**: the sizes of `C`, `C'` and the summary contexts; the restored context (`C'` plus recalled tokens) as a
  median ratio to `C`; and each arm's cumulative usage, the input and output tokens over every call the arm needs,
  tool turns, re-asks and the summarizer call included. Sizes use lcc's offline heuristic counter; cumulative usage
  comes from the CLI's own counts.

## Gates and hypotheses

If any validity gate fails, the run is invalid and gets no verdict, though its numbers are still published.

- V1: `full_t` reaches an A of at least 0.60.
- V2: the harness retries infrastructure failures (transport errors, CLI crashes, usage limits). A session that still
  fails drops from every arm, and at most 5% of sessions may drop.
- V3: at least 80% of `ans_early` questions are stash-dependent. V3b: at least 80% of `ans_late` questions are in view.
- V4: a scripted `recall` through the CLI returns the stored bytes.
- V5: at least 95% of answer lines parse in every arm.
- V6: the run counts as contaminated if `none` reaches the A of `full_t` minus 0.10.

The hypotheses, declared before any answer:

- **H1** (primary, non-inferiority): `stashed_t` is not worse than `full_t` on A. It passes if the lower bound of the
  95% CI of `stashed_t − full_t` lies above −5 points.
- **H2** (primary): on E, `stashed_t` beats both summaries. It passes if the lower bounds for `stashed_t − summary_s`
  and `stashed_t − summary_clin` both lie above 0. The summaries are smaller than the stashed context, so this is not a
  matched-budget comparison.
- **H3** (descriptive since Amendment 1): on `unans`, `stashed_v` gives fewer unsupported answers than `stashed_t`
  without losing more than 5 points of A. The pilot had UA at 0/40 in every arm, so the first criterion could not be
  met, and Amendment 1 made H3 descriptive.

Secondary contrasts carry CIs and no pass claim. S1 is what the tool adds on stash-dependent questions
(`stashed_t − stashed_0`). S2 splits every primary contrast by condition. S3 compares `full_t` with each summary. S4
rescores with LongHealth's substring rule. S5 replays the verifier's first pass without the patient check. S6, a second
answerer from another model family, was not run.

## Statistics

Every contrast uses a paired cluster bootstrap [5] over the 18 target patients, with 2000 resamples and seed
`20261103`. All of a target's questions in all conditions resample together. The statistic is the pooled difference in
accuracy, and the CI is the percentile interval. With 18 clusters a percentile interval can cover less than 95%, so the
appendix lists the 18 per-patient differences for each primary contrast. Before the run I estimated the CI half-width
on A at about 0.036 (protocol, Power).

## Evidence labels

Before I publish a measured claim, I run it through `gateClaim`, an automated evidence check in my own tooling (not
part of lcc). PASS lets a claim stand as measured. BLOCK means the claim carries the label INFERIDO (Portuguese for
"inferred"). On 2026-11-07 the check passed the H1 result in the short form quoted in the abstract and blocked a longer
wording of the same numbers. It blocked the H2, verifier and token findings, so this paper labels them INFERIDO: one
run, one answerer model, no independent replication.

# Results

## Run and gates

The harness built and compacted all 54 D sessions. lcc stashed 1,069 record reads, all for the reason
`stale_read_far_from_recent_work`, and all 54 sessions passed both stash checks. The run counted 582 CLI calls against the
650-call cap. Calls 1–214 ran on the subscription and calls from 216 on through the API route (Amendment 3). Line 215
logged the start of a call that the CLI never sent. Only `summary_clin` has calls on both routes. One session was
dropped (Dropped session, below). Every gate passed.

Table: Validity gates.

| Gate | Criterion | Result |
|------|-------------------------------------------|-----------------------------------------------------------------|
| V1 | `full_t` A at least 0.60 | pass, 621/700 = 0.887 |
| V2 | at most 5% of sessions dropped | pass, 1 of 54 = 1.9%, but the drop departs from V2's rule |
| V3 | `ans_early` stash-dependent, at least 80% | pass, 360/360 (340/340 on the 17 kept sessions) |
| V3b | `ans_late` in view, at least 80% | pass, 360/360; `unans` 360/360 absent; 0 mixed |
| V4 | `recall` through the CLI | pass |
| V5 | at least 95% of lines parse | pass, 0 response failures in any arm or condition |
| V6 | `none` below the A of `full_t` minus 0.10 | pass, 215/360 = 0.597 against 0.787 (chance 0.20) |

With no records at all, `none` answers well above chance. This run cannot tell why. Memorisation of LongHealth,
general medical knowledge and cues in the questions and options all fit.

## Accuracy

Table: Accuracy by arm over the 53 kept sessions. A covers `ans_early` and `ans_late`, E is the exact-value stratum
within A, U is `unans` answered F, and UA is `unans` lines that chose A–E. `none` uses the A–E prompt with no records.

| Arm | A | E | U | UA |
|----------------|-----------------|-----------------|---------|-------|
| `none` | 215/360 = 0.597 | 66/141 = 0.468 | n/a | n/a |
| `full_t` | 621/700 = 0.887 | 248/278 = 0.892 | 360/360 | 0/360 |
| `stashed_t` | 622/700 = 0.889 | 246/278 = 0.885 | 360/360 | 0/360 |
| `stashed_0` | 327/700 = 0.467 | 127/278 = 0.457 | 360/360 | 0/360 |
| `summary_s` | 532/700 = 0.760 | 216/278 = 0.777 | 360/360 | 0/360 |
| `summary_clin` | 612/700 = 0.874 | 242/278 = 0.871 | 360/360 | 0/360 |
| `stashed_v` | 563/700 = 0.804 | 197/278 = 0.709 | 360/360 | 0/360 |

Table: Accuracy (A) by condition.

| Arm | `ans_early` (target stashed) | `ans_late` (target in view) |
|----------------|------------------------------|-----------------------------|
| `full_t` | 302/340 = 0.888 | 319/360 = 0.886 |
| `stashed_t` | 299/340 = 0.879 | 323/360 = 0.897 |
| `stashed_0` | 2/340 = 0.006 | 325/360 = 0.903 |
| `summary_s` | 246/340 = 0.724 | 286/360 = 0.794 |
| `summary_clin` | 294/340 = 0.865 | 318/360 = 0.883 |
| `stashed_v` | 268/340 = 0.788 | 295/360 = 0.819 |

## Primary contrasts

Table: Primary contrasts in percentage points, paired cluster bootstrap over the 18 targets.

| Hypothesis | Contrast | Metric | Difference | 95% CI | Criterion | Result |
|--------------|----------------------------|--------|------------|----------------|------------------|-----------------------|
| H1 | `stashed_t − full_t` | A | +0.1 | −1.9 to +2.1 | lower bound > −5 | **PASS** |
| H2, generic | `stashed_t − summary_s` | E | +10.8 | +5.9 to +15.5 | lower bound > 0 | met |
| H2, clinical | `stashed_t − summary_clin` | E | +1.4 | −1.2 to +4.1 | lower bound > 0 | not met |
| H2 | both must be met | | | | | **FAIL** |
| H3, UA | `stashed_v − stashed_t` | UA | 0.0 | 0.0 to 0.0 | upper bound < 0 | not met (descriptive) |
| H3, A | `stashed_v − stashed_t` | A | −8.4 | −11.0 to −5.8 | lower bound > −5 | not met (descriptive) |

**H1 passed.** With recall over its stash, the stashed context answered as well as the full context: 0.889 against
0.887, CI well inside the 5-point margin.

Without the tool (`stashed_0`), accuracy on questions whose answer was stashed fell to 2/340, so the correct answers in
`stashed_t` came through recall and not from what stayed in view. When the target sat in view, `stashed_0` reached
325/360. S1 puts what `recall` adds on stash-dependent questions at +87.4 points (+83.0 to +91.6).

**H2 failed** (INFERIDO). Against the generic summary, the stashed arm scored 10.8 points higher on exact values, with
a CI clear of zero. Against the clinical summary the difference was 1.4 points with a CI from −1.2 to +4.1, so the
pre-registered claim fails. The clinical summary also came close to the full context: S3 puts `full_t − summary_clin`
at +1.3 points on A (−0.5 to +3.1) and +2.2 on E (−0.3 to +4.7).

**H3** stayed at its floor (INFERIDO). No arm chose A–E on an absent patient, so the verifier had nothing to prevent
on `unans`. On answerable questions it cost 8.4 points of A.

## Secondary contrasts

Table: Secondary contrasts in percentage points, 95% CI in parentheses. No pass claims.

| Contrast | Difference (95% CI) |
|--------------------------------------------------------------|-----------------------------------------------|
| S1: `stashed_t − stashed_0`, stash-dependent questions, A | +87.4 (+83.0 to +91.6) |
| S2, `ans_early`: H1 | −0.9 (−3.8 to +1.9) |
| S2, `ans_early`: H2 against `summary_s` | +15.3 (+6.9 to +24.0) |
| S2, `ans_early`: H2 against `summary_clin` | 0.0 (−3.8 to +4.1) |
| S2, `ans_early`: H3, A | −9.1 (−12.9 to −5.3) |
| S2, `ans_late`: H1 | +1.1 (−0.8 to +3.6) |
| S2, `ans_late`: H2 against `summary_s` | +6.4 (+0.9 to +11.9) |
| S2, `ans_late`: H2 against `summary_clin` | +2.8 (−0.8 to +6.5) |
| S2, `ans_late`: H3, A | −7.8 (−11.1 to −4.7) |
| S3: `full_t − summary_s`, A / E | +12.7 (+8.8 to +17.2) / +11.5 (+6.6 to +15.9) |
| S3: `full_t − summary_clin`, A / E | +1.3 (−0.5 to +3.1) / +2.2 (−0.3 to +4.7) |
| S3: U, both summaries | 0.0 (0.0 to 0.0) |
| S4, substring rule: H1 | 0.0 (−1.9 to +2.0) |
| S4, substring rule: H2 against `summary_s` | +10.8 (+5.9 to +15.5) |
| S4, substring rule: H2 against `summary_clin` | +1.1 (−1.5 to +3.9) |
| S4, substring rule: H3, A | −8.7 (−11.6 to −5.9) |

The gap to the generic summary was wider with the target stashed (+15.3) than with the target in view (+6.4). In
`ans_late` the summary arms also got the target's files back through re-attach. Under S4 every contrast lands on the
same side of its criterion as under the letter rule.

## Recall behaviour

Table: Recall behaviour of `stashed_t` over the 53 kept sessions.

| Measure | Value |
|------------------------------------------------------------------------------|------------------|
| R1: stash-dependent questions whose answer text was recalled (of 340) | 0.965 |
| R2: recalls that returned an answer text | 0.941 |
| R3: recall calls per session, all / successful | 2.08 / 1.92 |
| R3: share of sessions with no recall / that hit the cap of 8 calls | 0.68 / 0.04 |
| R4: recalled tokens over stashed tokens | 0.106 |
| R5: restored context, median ratio to `C` | 0.608 |
| R6: recall errors | 8, all of type `cap` |

Every `ans_early` session recalled. The 36 sessions without a recall are all `ans_late` and `unans` sessions, where the
answers sat in view or did not exist.

## Verifier (INFERIDO)

Table: The verifier loop in `stashed_v`.

| | `ans_early` | `ans_late` | `unans` |
|----------------------------------------------------|-------------|------------|------------|
| Sessions re-asked | 16 of 17 | 18 of 18 | 0 of 18 |
| First-pass catches | 66 | 80 | 0 |
| Lines forced to F | 27 | 22 | 0 |
| Forced lines that were correct on the first pass | 25 | 22 | 0 |
| Correct lines, first pass to final | 293 to 268 | 321 to 295 | 360 to 360 |
| Lines gained / lost by the loop | 1 / 26 | 0 / 26 | 0 / 0 |

The first-pass catches split between "quote not found" and "number not in quote": 33 and 33 in `ans_early`, 40 and 40
in `ans_late`. None came from the patient check, so removing that check (S5) changes no first-pass catch. On
answerable questions the loop turned right answers into F: 47 of its 49 forced lines had been correct. The pilot found
three ways the number check fails a right answer: an option states several facts and the model quotes one; an option
and a record write a date differently; an option gives a value computed from the record. I did not classify the D
catches this way.

## Sizes and token use (INFERIDO)

Pooled, the full contexts `C` held 2,898,882 tokens and the stashed contexts `C'` held 1,596,613, which is 0.551 of
`C`. The summary contexts held 635,015 tokens (`summary_s`) and 1,237,121 (`summary_clin`). With recalled text added
back, the restored context had a median ratio to `C` of 0.608.

Table: Cumulative token use on the 53 kept sessions: input plus output tokens over every call each arm needs,
summarizer included.

| Arm | Tokens | Ratio to `full_t` |
|----------------|------------|-------------------|
| `full_t` | 5,818,055 | 1.00 |
| `stashed_t` | 4,680,613 | 0.80 |
| `stashed_0` | 3,312,618 | 0.57 |
| `summary_s` | 8,375,754 | 1.44 |
| `summary_clin` | 14,222,255 | 2.44 |
| `stashed_v` | 7,344,489 | 1.26 |
| `none` | 72,834 | n/a |

Recall turns resend the context, and the summary arms pay for a summarizer call over the full `C`. The CLI returned
some summary replies split over two turns, and the harness retried them as infrastructure failures: 11 in
`summary_clin` and 1 in `summary_s`. `results.json` also gives usage over every call, the dropped session and the
retries included. Context sizes, the restored context and the recall figures use lcc's heuristic token counter;
cumulative usage comes from the CLI's counts. Amendment 4 left out the credit valuation, so no money figure appears
here.

## Dropped session

The harness dropped `patient_12__ans_early` from every arm. Its `summary_clin` call failed 5 attempts: the provider's
`reasoning_extraction` classifier stopped the summarizer's request each time. This departs from V2, which drops a
session only for infrastructure failures (a transport error, a CLI crash or a usage limit). A classifier stop is none
of these, but the frozen harness treats any failed final attempt as terminal. The verdicts above are the harness's.

Scored as V2 reads, the session stays in and `summary_clin` is wrong on all 20 of its questions. I re-scored it offline
with the harness's own scoring and bootstrap on the cached answers, with no model call. The verdicts do not change: H1
+0.1 (−1.8 to +2.1); H2 against `summary_s` +11.0 (+6.1 to +15.5); H2 against `summary_clin` +2.8 (−0.8 to +7.2).

# Discussion

On this benchmark, with this answerer, stashing old record reads and giving the agent `recall` matched the full
context on answerable questions. The stashed contexts held 0.551 of the full tokens before recall and a median 0.608
after it. The answers that needed stashed text came through recall: the model recalled the answer text for 0.965 of
stash-dependent questions, and without the tool it got 2 of those 340 questions right. In the pilot the plain pointer
failed because the model often did not recall, and the `head` pointer changed that. A reader should count the
pointer's text as part of the treatment.

H2 failed on the clinical summary. The generic prompt, written for coding sessions, lost exact values, as the generic
summary did in my earlier coding-session study. The clinical prompt asks for every value, unit and date, and it closed
most of that gap: on E the stashed arm led it by 1.4 points with a CI that includes 0, and the clinical summary
trailed the full context by 2.2 points with a CI that also includes 0. A summary prompt written for the domain is a
strong baseline here. It also cost more. The clinical summary context was about twice the size of the generic one,
and its arm used 2.44 times the cumulative tokens of `full_t`, against 0.80 for `stashed_t` (INFERIDO). This run's
questions come from the benchmark, and I did not pick them to probe what summaries leave out.

The verifier result is negative. Its number check assumes that every number in a correct option appears in a quote.
LongHealth's options break that assumption, and 47 of the 49 lines the loop forced to F had been correct. UA was 0 in
every arm, so the run cannot say whether any version of the check would prevent unsupported answers. Testing that
needs questions on which models do answer about absent patients.

# Limits

- One run, one answerer model (Claude Sonnet 5.5) and one summarizer model (Claude Opus 5.5), both from one vendor.
  S6, a second answerer from another family, was not run.
- `none` scored 0.597 with no records, against chance at 0.20, so some questions can be answered without the records.
  I did not test whether accuracies would be lower on records no model has seen.
- UA was 0 in every arm, so the run cannot show whether the verifier prevents unsupported answers.
- 18 clusters: a percentile bootstrap can cover less than 95%. The appendix lists the per-patient differences.
- I designed the `head` pointer after the pilot. The D targets were never pilot targets, but their records appeared as
  distractors in pilot sessions and in the first-line check.
- The session format differs from LongHealth's protocol, so these numbers are not comparable with the LongHealth
  paper's tables.
- Compaction was query-blind. In real use lcc sees the request and keeps the files it names; the query-aware variant
  was out of scope.
- One session was dropped for a reason V2 does not list. Scoring it as V2 reads leaves the verdicts unchanged.
- Amendment 4 came after scoring, with the verdicts known. It removes one reporting line, the credit valuation, and
  changes no data, gate or verdict.
- I built lcc, the harness and the protocol, with AI assistants (AI-use disclosure, below). No one outside the project
  has replicated the run.
- Context sizes use lcc's heuristic token counter, not the model's tokenizer.

# Data and code availability

Everything needed to check or rerun the study is in the lcc repository [6], `github.com/lucasmartins-ai/lcc` (MIT),
under `benchmarks/research/longhealth-v1/`:

- `PROTOCOL.md`: the pre-registered protocol with Amendments 1–4;
- `PILOT.md`: the pilot and re-pilot report;
- `RESULTS.md` and `results.json`: the D results, with aggregates and 6,720 per-item 0/1 scores keyed by patient,
  question number, condition and arm;
- `location-receipt-D.json`: where each question's answer sits after compaction, as hashes of record texts, written
  before any answer;
- `longhealth_v1.py` and `recall_shim.py`: the harness, whose sha256 Amendment 2 records, and `freeze-tests.log`, the
  test run at the pin;
- `PREPRINT.md`: this paper. `tests/test_longhealth_v1_preprint.py` checks the numbers quoted here against
  `results.json` and the study's own files.

The `head` pointer lives in `src/lcc/relevance/transcript_stash.py` at the pin
`17d9595ca0f9b54cdec2e483cf389e8c8a1bb2ae`. The harness fetches LongHealth from `github.com/kbressem/LongHealth` at
commit `479922279ce8fa528fe2cd87d854c6a2f8365d21` (Apache-2.0) and checks its git blob hash. Record texts, questions,
options, summaries, recalled text and answers stay in a private directory and are not redistributed, as the
benchmark's authors ask. A rerun needs the Claude Code CLI with access to the two models. The phases run in order,
with `PYTHONPATH` set to the pin's `src`, `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`:

```
python longhealth_v1.py fetch --set D
python longhealth_v1.py build --set D       # then compact, locate and toolcheck the same way
python longhealth_v1.py run --arm <arm> --set D
python longhealth_v1.py score --set D
```

This draft has no archival DOI yet.

# AI-use disclosure

I designed, built and ran this study with Claude Code (Anthropic) as the main assistant. It drafted the protocol and
amendments, wrote the harness and tests, drove the pilot and the main set, and scored them. Codex (OpenAI) reviewed
the protocol, the harness changes and the reports as an independent second reviewer; the protocol cites one of its
findings and the pilot report another. Claude Code drafted this paper from the repository's protocol and results
files, Codex reviewed the draft, and a test ties its numbers to `results.json`. The decisions the protocol records as
the owner's are mine: the route and call cap, the pilot decisions in Amendment 1, the billing switch in Amendment 3
and the omission in Amendment 4. The models under test, Claude Sonnet 5.5 as answerer and Claude Opus 5.5 as
summarizer, come from the same vendor as the main assistant. I am responsible for the content.

# Ethics

The study used no real patient data and had no human participants: LongHealth's patients are fictional. I did not
seek ethics review.

# Competing interests and funding

I maintain lcc, the tool under test, and run LookADev, a software business. The study had no external funding. Model
calls ran on my own Claude subscription and on API credits I already held.

# References

[1] Adams L, Busch F, Han T, et al. LongHealth: A Question Answering Benchmark with Long Clinical Documents. *Journal
of Healthcare Informatics Research* 9(3), 2025. arXiv:2401.14490.

[2] Jiang H, Wu Q, Lin C-Y, Yang Y, Qiu L. LLMLingua: Compressing Prompts for Accelerated Inference of Large Language
Models. *EMNLP 2023*.

[3] Jiang H, Wu Q, Luo X, et al. LongLLMLingua: Accelerating and Enhancing LLMs in Long Context Scenarios via Prompt
Compression. *ACL 2024*.

[4] Packer C, Wooders S, Lin K, et al. MemGPT: Towards LLMs as Operating Systems. arXiv:2310.08560, 2023.

[5] Efron B, Tibshirani RJ. *An Introduction to the Bootstrap*. Chapman & Hall, 1993.

[6] Martins L. lcc (Local Context Compiler). `github.com/lucasmartins-ai/lcc`, MIT License.

# Appendix: per-patient differences

Table: Per-patient differences in percentage points for the 18 D targets (the two pilot-pool patients are not
targets). `patient_12` lost its `ans_early` session to the drop.

| Patient | H1 (A) | H2 against `summary_s` (E) | H2 against `summary_clin` (E) | H3 (A) |
|--------------|--------|----------------------------|-------------------------------|--------|
| `patient_01` | 5.0 | 18.2 | 0.0 | −12.5 |
| `patient_02` | −2.5 | 0.0 | −4.5 | −17.5 |
| `patient_04` | −5.0 | −8.3 | 0.0 | −15.0 |
| `patient_06` | 2.5 | 22.7 | 9.1 | −5.0 |
| `patient_07` | −5.0 | 0.0 | 0.0 | −12.5 |
| `patient_08` | 2.5 | 0.0 | 5.0 | −17.5 |
| `patient_09` | 10.0 | 22.2 | 11.1 | −7.5 |
| `patient_10` | 2.5 | 8.3 | 0.0 | −5.0 |
| `patient_11` | 2.5 | 0.0 | 10.0 | −5.0 |
| `patient_12` | 0.0 | 0.0 | 0.0 | 0.0 |
| `patient_13` | −2.5 | 18.8 | 0.0 | −12.5 |
| `patient_14` | 5.0 | 27.8 | 0.0 | −2.5 |
| `patient_15` | 0.0 | 0.0 | 10.0 | −7.5 |
| `patient_16` | 0.0 | 7.1 | 0.0 | 0.0 |
| `patient_17` | −2.5 | 7.1 | 0.0 | −12.5 |
| `patient_18` | −7.5 | 13.6 | 0.0 | 2.5 |
| `patient_19` | −5.0 | 16.7 | −11.1 | −10.0 |
| `patient_20` | 2.5 | 12.5 | 0.0 | −7.5 |
