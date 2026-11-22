# Intake objective v1: results (2026-11-22)

Protocol: [PROTOCOL.md](PROTOCOL.md). It was pre-registered before any arm ran and has nine amendments, each merged
before the run it governs. Cases: `cases.json`, 600 synthetic cases, sha256
`a22ae7028a406db30d89680d9eefe378076f62a40a2f6ca35cbb0afd0c01776b`. The test split has 300 cases from the 20
even-numbered bases.

**Question.** `brief.objective` is the first ask in input order (A0). Does a deterministic ranking of topic blocks
(D) pick the main ask of a long dictation more often? Does one Jev choice over D's top blocks (DJ) add to it?

**In short**

- **Synthetic test split.** All four pre-registered hypotheses pass:
  - D beats A0 by 0.237 (interval 0.18 to 0.297);
  - DJ beats D by 0.18 (0.123 to 0.24);
  - D keeps the easy case;
  - every ask stays recoverable.
- **The owner's real dictations,** INFERIDO. Neither real set shows D ahead of A0.
  - **Part R:** on 22 dictations, A0 hits 12, D 11 and DJ 14.
  - **Part R2:** on 20 dictations under the owner's verdicts, D is rated the main ask on 4 and A0 on 3.

  Both sets are small, so this is "not shown at this size", not "no effect".
- **A line written by Claude,** INFERIDO. It was rated the main ask on 20 of the 20 Part R2 dictations. That
  comparison is not blind (see Part R2).
- **What runs in lcc today.** `parse_intake` still uses A0, and the module under test, `lcc/intake/objective.py`, is
  called only by this study's scripts. What ships is the owner's decision.

**Evidence labels.** `gateClaim` is the evidence check the owner runs on a measured claim before publishing it. PASS
lets the claim stand as measured; DOWNGRADE or BLOCK means it reads INFERIDO. Each synthetic finding below names its
claim, and the Part R and Part R2 sections read INFERIDO as a whole. All verdicts are from 2026-11-22 (see
[gateClaim](#gateclaim)).

| Arm | What it is | Code | Results |
| :--- | :--- | :--- | :--- |
| A0 | the first ask in input order: today's `brief.objective` | `lcc.intake` parser | `results_test.json` |
| A1 | the last ask, a position control | same | `results_test.json` |
| D | ranks topic blocks by marker, restatement and ask cues | `src/lcc/intake/objective.py`, frozen by Amendment 2 | `results_test.json` |
| DJ | one Jev `choice` over D's top 5 blocks, used at p ≥ 0.6 | `run_dj.py`, frozen by Amendment 3; `jev-1.14.0` | `results_dj_test.json` |
| C (Part R2 only) | one line written by a fresh Claude `opus` agent per batch | Amendment 8 | private |

## Synthetic test split (Part S)

Pre-registered verdicts. The intervals are paired cluster bootstraps over the 20 test bases: 10,000 resamples, seed
20261116.

| Hypothesis | Measured | Criterion | Verdict | `gateClaim` |
| :--- | :--- | :--- | :--- | :--- |
| H1, D over A0 | D 0.79, A0 0.553; diff 0.237 (0.18 to 0.297) | diff ≥ 0.15 and lower bound > 0 | **PASS** | H1 |
| H2, DJ over D | DJ 0.97, D 0.79; diff 0.18 (0.123 to 0.24) | lower bound > 0 | **PASS** | H2 |
| H3, `first` kept | D 1.0, A0 1.0 on the 60 `first` cases | D ≥ A0 − 0.05 | **PASS** | H3 |
| H4, recall | D's ask recall 1.0 in all 300 cases; every stash rebuilds byte for byte | 1.00 and every rebuild | **PASS** | H4 |

Hit@1 by family, length and language, with no pass criterion (`gateClaim`: TABLE):

| Group (test) | n | A0 | A1 | D | DJ |
| :--- | ---: | ---: | ---: | ---: | ---: |
| all | 300 | 0.553 | 0.473 | 0.79 | 0.97 |
| `bare` | 60 | 0.383 | 0.4 | 0.667 | 0.933 |
| `first` | 60 | 1 | 0.15 | 1 | 1 |
| `marker` | 60 | 0.433 | 0.483 | 0.817 | 1 |
| `recurrence` | 60 | 0.433 | 0.417 | 0.717 | 1 |
| `restate` | 60 | 0.517 | 0.917 | 0.75 | 0.917 |
| k = 4 blocks | 100 | 0.74 | 0.65 | 0.87 | 0.99 |
| k = 8 blocks | 100 | 0.56 | 0.45 | 0.8 | 0.97 |
| k = 16 blocks | 100 | 0.36 | 0.32 | 0.7 | 0.95 |
| English | 150 | 0.507 | 0.42 | 0.667 | 0.947 |
| Portuguese | 150 | 0.6 | 0.527 | 0.913 | 0.993 |
| Codex phrasings (leakage control) | 120 | 0.475 | 0.7 | 0.783 | 0.958 |
| recap read as a rule (Amendment 1) | 8 | 0.625 | 0.375 | 0.75 | 1 |

- **Length.** A0 falls from 0.74 at 4 blocks to 0.36 at 16. D falls from 0.87 to 0.7 and DJ from 0.99 to 0.95.
- **Leakage.** On the test phrasings Codex wrote without seeing D's cue lists, D hits 0.783 against A0's 0.475
  (`gateClaim`: CODEX). `bare`, the only family whose gold is the author's judgment, is the family where D is lowest
  (0.667).
- **The position control.** D minus A1 is 0.317 (0.23 to 0.403). A1 wins only on `restate` (0.917), where the
  restatement is last by construction (`gateClaim`: CONTROLS, which also covers the ablations and hit@3).
- **Ablations.** D's hit@1 with one signal removed:
  - without ask cues, 0.617;
  - without the marker, 0.767;
  - without the restatement, 0.78;
  - without recurrence, 0.79, unchanged, because the dev tuning set recurrence's weight to 0 (Amendment 2).
- **D's hit@3** is 0.967.

**Q3, the brief** (D, test; `gateClaim`: Q3):

- **Size.** The objective plus the linked blocks are 0.151 of the input tokens on average.
- **Asks.** Ask recall is 1.0, and every stash rebuilds the input byte for byte. The parser labels 0.655 of the gold
  asks `ask` (`asks_labelled`), so that share reaches `brief.asks` itself.
- **Links,** on the cases D hits: precision 0.398 and recall 0.402.
- **Speed and fallbacks.** D takes 5.5 ms per case on average (11.0 ms at most) and never falls back to A0.

**DJ's calls** (test): 258 Jev calls. The 42 cases with fewer than two eligible blocks made none. There were 0
errors, Jev's pick was used in 244, and every call resolved to `jev-1.14.0` (`gateClaim`: DJCALLS).

**Dev split,** where D was tuned and DJ was seen before the test run: A0 0.597, A1 0.537, D 0.893, DJ 0.993
(`gateClaim`: DEV).

## Part R: the owner's real dictations, gold sentences (Amendments 4 and 5)

Amendment 4 drew the pool mechanically from the owner's transcripts: messages the app tagged as typed by a person,
300 words or more, with no pasted or generated content and no duplicate. That left 31 candidates in a seeded order.
The owner went through them top down and marked the main ask sentence or sentences before any arm ran. They kept 22
and skipped 9 as "não tem um pedido principal". Scoring is Part S's rule: a pick hits when it covers at least half
of any gold sentence. Nothing here has a pass criterion.

| Arm (n = 22) | hit@1 | Wilson 95% |
| :--- | ---: | :--- |
| A0 | 12 (0.545) | 0.347 to 0.731 |
| A1 | 6 (0.273) | 0.132 to 0.481 |
| D | 11 (0.5) | 0.307 to 0.693 |
| D, hit@3 | 19 (0.864) | 0.667 to 0.953 |
| DJ | 14 (0.636) | 0.430 to 0.803 |

`gateClaim`: PARTR, BLOCK, so this section reads INFERIDO.

- **What the intervals say.** They overlap widely, so 22 dictations do not separate D from A0 or DJ from D.
- **DJ against D.** DJ fixed 4 of D's 11 misses and lost 1 of its hits. It made 21 Jev calls with 0 errors; Jev's
  pick was used in 18 and fell below 0.6 in 3.
- **Gold labels.**
  - 19 of the 22 dictations have two or more gold sentences.
  - In 2, the parser labels no gold sentence `ask`, so no arm can hit them.
  - In three long dictations the gold covers most of the text (see Deviations).
- **D's brief** is 0.618 of the input on average.

**Claude as a labeller** (Amendment 7). A fresh `opus` agent labelled the same 22 dictations blind and agreed with
the owner on 7 of 22 (Wilson 0.164 to 0.527), against a pass mark of 19. Under Amendment 7 a failed check means
Claude's labels replace no owner labels. `gateClaim`: CLAUDE, DOWNGRADE, so the 7 of 22 reads INFERIDO too.

## Part R2: the owner's verdict on each arm's objective (Amendments 6, 8 and 9)

Amendment 6 drew 152 more candidates from the owner's transcripts. The first 100 positions of its seeded order were
judged. Each arm offered one objective per message, and the owner, who wrote the message, rated each one:

- **Sim:** it is the main ask;
- **Em parte:** it is an ask of theirs, but not the main one, or it misses something essential;
- **Não:** it is context, another topic or wrong.

Equal objectives shared one rating, and the arms' names were hidden. Amendment 9 kept only one-paragraph messages,
the owner's dictations, which leaves 20. This is a different measure from Part R's and a different length band
(18 of the 20 have 200 to 299 words), so the two sets are not pooled or compared. Every Part R2 finding returned
BLOCK at `gateClaim` and reads INFERIDO.

| Arm (n = 20) | "Sim" | Wilson 95% | "Sim" or "Em parte" | Wilson 95% |
| :--- | ---: | :--- | ---: | :--- |
| C, Claude's line | 20 of 20 | 0.839 to 1 | 20 of 20 | 0.839 to 1 |
| D | 4 of 20 | 0.081 to 0.416 | 15 of 20 | 0.531 to 0.888 |
| A0 | 3 of 20 | 0.052 to 0.360 | 13 of 20 | 0.433 to 0.819 |
| A1 | 5 of 20 | 0.112 to 0.469 | 15 of 20 | 0.531 to 0.888 |

- **The pre-registered test,** D against A0 on "Sim", paired:
  - D alone in 1 message and A0 alone in 0, exact McNemar p = 1.0;
  - D's objective is A0's in 11 of the 20;
  - the run is underpowered (the floor was 60), so it shows no difference at this size (`gateClaim`: R2).
- **Sensitivity.** On the 49 messages as first judged, before Amendment 9's rule, the paired counts are D alone 3
  and A0 alone 6 (p = 0.5078). That is the opposite direction, and neither set is near 0.05 (`gateClaim`: R2SENS).
- **C,** descriptive. C against D on "Sim" is 16 to 0 (p = 3.052e-05), and C is 47 of 49 on the messages as first
  judged (`gateClaim`: R2C). Three things limit this:
  - the judgment is not blind, because C paraphrases and the owner can usually tell its line from the verbatim
    sentences;
  - C reads the whole message, while the other arms can only pick one of its sentences;
  - the 20 messages were selected by Amendment 9's rule, which was written after the ratings.
- **Arm C's runs.** Nine agents wrote all 100 lines on the first try. A count-only check of their transcripts
  found calls only on each agent's own input and answer files.

## Deviations

- **Part R text reached a model once.** After the labelling and before the run, a text search the assistant ran over
  the labelling page printed about five short fragments of pooled messages. The labels were already final, and A0,
  A1 and D read no model output (Part R run record).
- **Part R gold coverage.** In three dictations of 13 or more sentences, the gold covers 60%, 68% and 83% of the
  text. The owner saw these shares and chose to run on the labels as made. The run does not measure what this does
  to the hit rates.
- **Part R2's late skips.** The owner judged positions 1 to 34 before applying the skip rule. Amendment 9 turned 29
  of them into skips by a fixed text rule (one paragraph = dictated). The rule was written from the owner's 66
  decisions made before any reveal and reproduces them in-sample. The sensitivity check above reports the set as
  first judged.
- **Synthetic test phrasings.** Two Codex recap phrasings are read as rules in eight test `restate` cases
  (Amendment 1). They stay as written and are reported apart.

## What this does not show

- **Synthetic answers.** The generator and D come from the same author, so D's synthetic gain may partly reflect the
  author's own sense of what a main ask sounds like. The Codex phrasings narrow this for markers and restatements,
  but not for `bare`.
- **Real data.** Part R (22) and Part R2 (20) come from one speaker and are small. A null there means "not shown at
  this size".
- **Claude's line.** C's 20 of 20 is not blind and covers 20 messages. It shows what a blind test should check, not
  that a generated objective is better.

## gateClaim

Run on 2026-11-22 with `intelligence gate --presented-as MEASURED`, one claim per finding or group of numbers, with
aggregates only. The evidence named its sources:

- **Most claims** had two: the study's stats file, and a recount from the per-case rows by a separate script, which
  matched every rate and count it covered. The intervals (bootstrap and Wilson) and the McNemar p-values come from
  the stats files alone.
- **CLAUDE's** second source is a re-score of the private answer file, whose sha256 the stats file pins, with the
  study's own scoring function.
- **R2SENS** has one source.

CODEX, CLAUDE and R2SENS were first run with evidence that wrongly claimed a recount for each. They were run again the
same day with the same claim text and evidence that states their sources, and the table gives that second run.

| Claim | Finding | Verdict | Support | Evidence strength | Reads as |
| :--- | :--- | :--- | ---: | ---: | :--- |
| H1 | D over A0, synthetic test | PASS | 0.81 | 2.9 | measured |
| H2 | DJ over D, synthetic test | PASS | 0.77 | 2.86 | measured |
| H3 | D keeps `first`, synthetic test | PASS | 0.87 | 2.87 | measured |
| H4 | ask recall and rebuild, synthetic test | PASS | 0.94 | 2.92 | measured |
| CODEX | D over A0 on the Codex phrasings | PASS | 0.9 | 2.77 | measured |
| TABLE | hit@1 by family, length and language | PASS | 0.9 | 2.87 | measured |
| CONTROLS | D minus A1, ablations, D's hit@3 | PASS | 0.85 | 2.81 | measured |
| Q3 | brief size, asks labelled, links, speed, fallbacks | PASS | 0.91 | 2.83 | measured |
| DJCALLS | DJ's calls, errors, uses and model | PASS | 0.79 | 2.74 | measured |
| DEV | dev split hit@1 | PASS | 0.87 | 2.88 | measured |
| CLAUDE | Claude as a labeller, 7 of 22 against 19 | DOWNGRADE | 0.85 | 2.18 | INFERIDO |
| PARTR | Part R hit@1 and its overlapping intervals | BLOCK | 0.62 | 2.77 | INFERIDO |
| R2 | Part R2, D against A0 | BLOCK | 0.69 | 2.74 | INFERIDO |
| R2C | Part R2, C's 20 of 20 | BLOCK | 0.51 | 2.81 | INFERIDO |
| R2SENS | Part R2 sensitivity, 3 to 6 | BLOCK | 0.44 | 1.22 | INFERIDO |

The gate's reasons were:

- **PARTR, R2 and R2C:** support below 0.75, the threshold for their evidence strength.
- **CLAUDE:** evidence strength below 2.5, which the gate reads as a single point measurement.
- **R2SENS:** evidence strength below 2 for a claim presented as measured.

So every finding on the owner's real dictations reads INFERIDO. No claim was reworded to change a verdict.

Some cells of the synthetic hit@1 table are in no claim's text: A1 outside `restate` (the `all` row's 0.473
among them) and DJ on the Codex phrasings (0.958). The recount matched them, but they carry no verdict.
