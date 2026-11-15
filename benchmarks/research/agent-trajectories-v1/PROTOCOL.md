# Agent trajectories v1: do stashing's byte guarantees and recall hold on public coding-agent sessions? (draft 2026-11-15)

**Status: draft, not approved.** No model call runs until the owner approves the data source, the route, the cap
and H1's margin (Run order, step 2). Generated questions, options and answers never enter this repository (Data
use); only counts, hashes, aggregates and per-item 0/1 scores keyed by ids do. Results are tagged INFERIDO until
`gateClaim` returns PASS on them.

## Why

What has been measured so far ([`docs/EVIDENCE.md`](../../../docs/EVIDENCE.md),
[`../longhealth-v1/RESULTS.md`](../longhealth-v1/RESULTS.md)):

- `stashed-v1`: on 847 of the maintainer's own sessions, `stashed` removed 30.1% of tokens and `lossless` 0.9%.
  10,830 stashed results had 0 violations from `verify_stashed` and 0 from an independent re-hash.
- `stashed-recall-v1`: on 172 requests from the same sessions, an agent with `recall` was not worse than full
  context on file recall. A model judge graded the answers.
- LongHealth v1: on public data, `stashed_t` was not worse than `full_t` (H1 passed). The sessions were built from
  clinical records, not coding work. A second answerer (S6) ran the same contrast afterwards. S6 has no
  hypothesis and its findings read INFERIDO, so this study does not lean on it.

The gap: lcc is sold for coding agents, and the coding evidence comes from one person's private sessions that
nobody else can rerun, with accuracy graded by a model judge.

This study changes three things:

1. **Public coding-agent sessions that are not ours.** SWE-smith trajectories (MIT). Anyone can rerun every step.
2. **A mechanical gold with no judge.** Questions come from the sessions' own tool outputs, and each answer is a
   line of bytes.
3. **Two parts that make different kinds of claim.**
   - **Part A, no model:** byte-level properties of the compaction itself. Can the original be rebuilt from the
     output? Do the parts lcc promises never to cut stay byte for byte? Does the same input give the same output?
     A user can run these checks on any single output, and the study counts violations over the whole split.
   - **Part B, agent in the loop:** does an answerer with `recall` answer questions about removed outputs as well
     as one with full context? That is a model's behaviour, so it can only be estimated, with a CI.

`stashed` is the focus because it is the recommended live configuration
([`docs/TOOL_CALLS.md`](../../../docs/TOOL_CALLS.md)). `lossless` and `auto` (the plugin's default) appear in
Part A as references.

What it cannot show: whether an agent still solves its task when its context is compacted mid-task; sessions from
other agents, other tools or longer work than these trajectories; real teams' sessions.

## Data

- Source: Hugging Face dataset `SWE-bench/SWE-smith-trajectories`, revision
  `08e109b4a59eaeebf80e4675cd125d42e7ac99a4` (MIT, metadata read 2026-11-15), split `tool` (24,100 rows).
- Fields read: `traj_id`, `instance_id`, `model`, `messages`. No arm, check or generator reads `resolved` or
  `patch`.
- The harness downloads the split's files at that revision into the private root. It records each file's sha256 in
  the freeze amendment and refuses to run if one differs.
- Shape, from the dataset viewer's first 10 rows (read 2026-11-15; the viewer truncated `messages` in 8 of them):
  - the `model` field of all 10 is `claude-3-7-sonnet-20250219`, and the trajectories come from SWE-agent;
  - in the first untruncated row, messages have roles `system`, `user`, `assistant` and `tool`;
  - an assistant tool call has an `id` and a `function` with `name` and JSON `arguments`;
  - a tool message has `tool_call_ids` and a list of text blocks.

  The harness counts models and message shapes over the whole split and reports them.
- **Repository** of a trajectory: `instance_id` has the form `<owner>__<repo>.<commit>.<task>`, for example
  `pallets__jinja.ada0a9a6.lm_rewrite__i9fx70a0` (30 ids read from the viewer, 2026-11-15).
  - The repository is the first group of `^(.+)\.[0-9a-f]{8}\.[^.]+$`, here `pallets__jinja`.
  - The rule and its unit tests are fixed before the pilot draw. It is the cluster unit for every CI.

## Sessions

**Conversion** (fixed and unit-tested before the pilot). There is one lcc transcript message per SWE-agent
message, in order:

- `system`, `user` and `assistant`: `text` is the message's text, with text blocks joined by `\n`. An assistant's
  `tool_calls` become lcc calls with `id`, `tool` = the function name and `input` = the parsed `arguments`.
- `tool`: a `user` message carrying one `toolResults` entry. Its id is the single entry of `tool_call_ids`, and its
  text is the text blocks joined by `\n`.
- `thought`, `action`, `agent` and `message_type` are dropped. They repeat the content or are metadata.

A row is **unconvertible** when any of these holds:

- `instance_id` does not match the repository rule;
- `messages` does not parse;
- an `arguments` value is not a JSON object;
- a tool message carries other than one id;
- a block is not text;
- lcc's `parse_transcript` raises.

Unconvertible rows are counted by reason and left out of both parts.

**`C`** is the converted transcript and **`C'`** its compaction. The answerer sees them through the flat rendering
of LongHealth v1 (`render` in `longhealth_v1.py`): one header line per block, `[m<NNNN> <role> <kind> <tool>]`,
then the block's text. Message numbers are the same in `C` and `C'`, because `stashed` never removes a message
(A2 checks it).

## Compaction

- LCC at the pin recorded at freeze (today `origin/main` `a80eae3`). It runs offline from a detached worktree with
  a clean tree.
- Modes, all with default settings:
  - `provider="rules"`, `rules_mode="lossless"`;
  - `provider="rules"`, `rules_mode="stashed"`;
  - `provider="auto"` (specialist-v3; it reports `semantic_guarantee: none`).
- **Query-blind.** Every session gets the same goal, `Review this session's tool outputs.` It names no call, file
  or value.
- One stash directory per session, so a session can only recall its own blobs.

## Part A: byte-level checks (no model, every convertible row)

Each mode runs on every convertible row. The checks use no lcc code unless they say so.

- **A1, reconstruction** (`lossless` and `stashed`): rebuild `C` from `C'` alone, plus the stash for `stashed`, and
  compare the result with `C` byte for byte.
  - The rebuild resolves the documented pointer forms: `[identical output kept at <id>]`,
    `[output = lines a-b of <id>]` and `[removed: … · lcc recall <sha12>]`.
  - lcc documents one normalization, for Codex `exec_command` header lines. Where it applies, the comparison
    follows it, and those outputs are counted.
  - lcc's own `verify_lossless` and `verify_stashed` also run, and their verdicts are reported next to the
    independent check.
  - For `auto`: the number of results it changed is reported. It makes no recovery claim.
- **A2, never cut** (`lossless` and `stashed`): every message's role and text, every call's id, tool and input,
  and the message order are byte-identical between `C` and `C'`. Only tool-result texts may differ.
  - `auto` may drop a call together with its result, and then a message the drop left empty (`_apply` in
    `transcript.py`). For `auto` the check covers what it keeps: every kept message's role and text and every kept
    call's id, tool and input are byte-identical to `C`, in `C`'s order. Dropped calls and messages are counted,
    not scored as violations.
- **A3, determinism** (all modes): each mode runs twice, in separate processes with a different `PYTHONHASHSEED`
  and a different working directory. `C'` must match byte for byte, and for `stashed` the set of blob hashes must
  match too.
- **A4, idempotence** (all modes): compacting `C'` again with the same settings returns `C'` unchanged.
- **A5, reduction** (all modes): tokens of `C` and `C'` with lcc's tokenizer.
  - Pooled reduction is 1 − Σ`C'`/Σ`C`, with a 95% CI from a cluster bootstrap over repositories.
  - The per-session median, p10 and p90 are reported too.

**Reporting.** lcc's contract predicts 0 violations of A1–A4 for `lossless` and `stashed`.

- Each check is reported as violations / sessions per mode.
- Part A covers every convertible row, so its counts describe this split. They are not a sample estimate.
- A bound for other sessions is inference. With 0 violations the report gives two 95% upper bounds:
  - 1 − 0.05^(1/N) over N sessions, which assumes sessions fail independently;
  - 1 − 0.05^(1/R) on the share of repositories with a violation, over R repositories, which lets the sessions of
    one repository share a failure. This is the one quoted.
- A violation is listed by `traj_id` and message number. It is a finding about lcc, never a reason to drop the row.
- Stash directories are deleted after the checks. The receipt keeps each session's blob hashes.

## Part B: questions about removed outputs

### Eligibility and sampling (fixed before the pilot)

- **Unique line:** a line of a tool result in `C` that meets all of these, with surrounding whitespace stripped:
  - it is 12 to 160 characters long and contains a letter;
  - it occurs exactly once across all tool results of `C`;
  - it does not occur in any message text or call input of `C`.

  Because of this rule, outputs that `lossless` would point to an identical copy hold no unique lines, so they are
  never targets.
- **Targets** are tool results of at least 1 KB and 5 lines, with at least one unique line. The stash pointer
  prints the output's line count and, under 1 KB, its exact byte count. A short target would bound which option
  lengths fit; at 1 KB or more the pointer prints KB to one decimal, and any option of 160 characters or fewer
  fits. Targets come in two kinds:
  - **SD** (stash-dependent): replaced by a stash pointer in `C'` (`stashed`);
  - **IV** (in view): byte-identical in `C'`.
- A session is **eligible** with at least 3 SD and 3 IV targets. This is computed from `C` and `C'` before any
  answer exists, and the counts are reported.
- **Pilot pool:**
  - 5 repositories are drawn with `random.Random(20261115)` from the sorted repositories that have at least 2
    eligible sessions;
  - 2 sessions are drawn in each, with the same generator;
  - none of the pool's repositories is used in D.
- **D:** 100 sessions from the other repositories. Sort the eligible `traj_id`s, shuffle them with
  `random.Random(20261115)`, and walk the list. Take a session unless its repository already has 2. Stop at 100,
  then apply the size rule under Power.

### Questions (generated before any answer)

Each session gets up to 5 SD and 5 IV targets, drawn with `random.Random(f"{traj_id}:targets")`, plus 2 U
questions. A session's questions are put in one order shuffled by `random.Random(f"{traj_id}:order")`, so a
question's position does not mark its type.

**Answerable question.** It names the target by message number, tool and the first 200 characters of its input:
`In the output of the <tool> call at m<NNNN> (input: <…>), which of these lines appears?`

- Options A–E are the gold and 4 distractors, in an order shuffled by the session's seed. The gold is one unique
  line of the target, drawn by the same seed.
- Option F is `This session does not let me tell.`

**Distractors** are lines drawn from tool results of other trajectories of the same repository, anywhere in the
split. They must meet all of these:

- they have the same tool name when enough exist;
- they are 12 to 160 characters long and contain a letter, as the gold does;
- their length is between half and double the gold's;
- after stripping, they do not occur anywhere in `C`;
- they differ from each other.

If fewer than 4 qualify, the rest come from other repositories under the same rules. All four distractors are
absent from `C`, and the gold is present in `C`, in view or stashed. In `C'` a stashed gold is as invisible as the
distractors, so an answerer cannot pick the gold by elimination on what it can see.

**U question.** It uses the answerable template word for word, but names a call that `C` does not contain:

- the message number is drawn from the assistant messages of `C` that carry a call;
- the tool and input are those of a call from another trajectory of the same repository;
- the input must not equal any call input in `C` after stripping;
- the five options are lines from that call's output that do not occur in `C`. One of them, the **anchor**, is
  drawn first with the session's seed from the lines that are 12 to 160 characters long with a letter. The other
  four follow the distractor rules with the anchor's length in place of the gold's;
- the correct answer is F.

**Location receipt.** It is committed before any arm runs. Per question it records:

- SD and IV: the type, the target's message number and the sha256 of the gold line;
- U: the type, the message number named, the source `traj_id`, the sha256 of the named call's tool and input, and
  the sha256 of the anchor.

### Arms

The answerer is Claude Sonnet 5.5, medium effort, through the subscription `claude -p`. It uses the same flags and
recall shim as LongHealth v1, and one call answers all of a session's questions.

- `full_t`: rendered `C`, with `recall` on the session's stash.
- `stashed_t`: rendered `C'`, with `recall` on the session's stash.
- `stashed_0`: rendered `C'` with no tool (Q-T0). It measures what the pointers and the visible context give away
  about a stashed gold (V6).
- `none`: the questions with options A–E only, no session and no tool. This is the guessability and memorisation
  check (Q-N).

**Stash for Part B.** Part A deletes its stash directories. Before any call, including the pilot's, Part B runs
`stashed` again at the pin on each selected session and checks that the blob hashes equal Part A's receipt (A3 makes
them equal). A session whose hashes differ is a finding about lcc: it is reported, and every `stashed_t` question
of that session is scored wrong.

### Texts (drafts; sha256 recorded at freeze)

**Q-T** (`full_t` and `stashed_t`): `You are given a finished coding-agent session and questions about its tool
outputs. An output shown as [removed: … · lcc recall <id>] can be read with the recall tool. Answer every question
on its own line as Q<n>: <letter>, and nothing else. Choose F only when the session does not let you tell.`

**Q-T0** (`stashed_0`): Q-T without its second sentence.

**Q-N** (`none`): `Each question describes a tool output from a coding-agent session you cannot see. Pick the
option most likely to appear in it. Answer every question on its own line as Q<n>: <letter>, A to E only.`

### Scoring (mechanical, no judge)

Scoring follows LongHealth v1:

- The chosen letter is parsed from each line. A question is correct iff the letter is the gold's, or F for a U
  question.
- A line that does not parse is wrong, and counted. So are a refusal and a missing line.
- If a session's `C'` fails A1, every `stashed_t` question of that session is scored wrong, and the failure is
  reported.

### Metrics

- **SD**: accuracy on SD questions.
- **IV**: accuracy on IV questions.
- **A**: accuracy on SD and IV together.
- **U**: the share of U questions answered F.
- **UA**: the share of U questions answered A–E.
- **Recall behaviour**: R1–R6 as in LongHealth v1, with "gold" read as "the target result".
- **Tokens**: `C` and `C'` pooled, and cumulative usage per arm (input, cached and output) from the CLI envelopes.

### Gates

If any gate fails, the run is invalid and no H verdict is given. The numbers are still published.

- **V1:** `full_t` accuracy on SD ≥ 0.60.
- **V2:** a call that fails for infrastructure reasons is retried as in LongHealth v1. At most 5% of D sessions may
  be dropped.
- **V3:** `none` accuracy on SD and IV ≤ 0.35, against chance 0.20. Above that, the questions can be answered
  without the session, and H1 becomes descriptive.
- **V4:** through the CLI path, a scripted `recall` of a known id returns its bytes.
- **V5:** ≥ 95% of answer lines parse in every arm.
- **V6:** `stashed_0` accuracy on SD ≤ 0.35. Above that, a stashed gold can be found without recall, and H1
  becomes descriptive.

### Hypothesis (declared before any answer)

**H1 (primary, non-inferiority).** On SD, `stashed_t` is not worse than `full_t`.

- PASS iff the lower bound of the 95% CI of `stashed_t − full_t` on SD is > −0.05.
- The margin is the one LongHealth v1 and `stashed-recall-v1` used, and the owner confirms it at approval.

**Statistics.** Paired cluster bootstrap over repositories, 2000 resamples, seed `20261115`. Every contrast also
reports its per-repository differences.

**Secondaries (CIs, no pass claim).**

- S1: `stashed_t − full_t` on IV. It is expected near 0 and checks the harness.
- S2: the same contrast on A.
- S3: the U and UA contrasts.
- S4: R1–R6.
- S5: tokens and cumulative usage.
- S6: a second answerer from another model family, only by amendment.

**Power (INFERIDO).**

LongHealth v1's assumptions: a per-question SD of paired differences of 0.35 and a design effect of about 2.

- 100 sessions give 300 to 500 SD questions (3 to 5 each). The CI half-width on SD is then about 0.056 to 0.043.
- With a true difference of 0 and the −0.05 margin, power is about 42% at 300 questions and 62% at 500. About 770
  SD questions give 80%.
- **Size rule (before any D answer):** if D holds fewer than 770 SD questions, the walk under Sampling continues
  down the same list until it does, D reaches 180 sessions, or the list runs out. The final count and its computed
  power go into the location receipt. If D stops short of 770, H1 is reported with that power.
- The pilot counts the repositories and the SD targets per session.

## Leakage controls

| leak | control |
|---|---|
| Generator tuned to make `stashed` win | Rules fixed here before the pilot; the pilot changes them only by dated amendment, before the freeze. |
| Gold picked by elimination on what is visible | All distractors are absent from `C`; a stashed gold is as invisible in `C'` as they are. |
| Answer visible somewhere else | Unique lines exclude any line repeated across results or present in a text or call input. |
| Gold guessable from the call input, or memorised (SWE-smith is public since 2025) | `none` arm and V3; every contrast is paired. |
| Gold read off the pointer (line and byte counts) or the visible context | Targets have at least 1 KB and 5 lines; options follow the gold's length and content rules; `stashed_0` arm and V6. |
| U told apart by its wording or position | U uses the answerable template; one shuffled order per session. |
| Compaction sees the questions | One fixed goal for every session. |
| Cross-session recall | One stash directory per session. |
| Refusals hiding losses | Scored wrong; only infrastructure failures drop a session (V2). |
| Tuning on D | Pilot only on the pilot pool's repositories. |

## Data use

MIT allows redistribution, but the generated questions, options and answers stay under the private root
`~/.lcc/bench/agent-trajectories-v1/`. That keeps them out of training sets, so later reruns stay clean. The
generator is deterministic from the pinned revision and the seed, so anyone can rebuild them.

The repository gets:

- the harness;
- receipts with counts and hashes;
- `results.json` with aggregates;
- per-item 0/1 scores keyed by `(traj_id, question_no, arm)`.

No data from this study trains or tunes any lcc ranker or judge.

## Budget (owner approval required before the pilot)

- **Part A:** local CPU only, $0, no model call. One process at a time. The split is 1,077 MB of parquet and 2,777 MB
  in memory (dataset viewer size endpoint, 2026-11-15), so the harness streams it row by row. The stash directories
  are deleted after their checks.
- **Part B:** subscription route, $0 cash, hard cap **800 CLI calls**.
  - Pilot: 10 sessions × 4 calls (`full_t`, `stashed_t`, `stashed_0`, `none`) = 40.
  - D: 100 to 180 sessions × 4 calls = 400 to 720.
  - Infrastructure retries count against the cap.
- Driver rules from LongHealth v1:
  - each call is logged before it starts;
  - one driver runs at a time, behind a lock;
  - a usage limit pauses the run, which resumes from cache after the reset;
  - no plan reset credit is spent.

## Run order

1. This file committed as draft.
2. The owner approves the data source, the route and cap, and H1's margin (dated line here).
3. Build the harness and its tests:
   - the converter;
   - the Part A checker, which imports no lcc code;
   - the question generator;
   - the answer harness.

   Then run Part A and question generation on the pilot pool, and the pilot answers.
4. Freeze amendment. It records:
   - the LCC pin;
   - the harness sha256;
   - Q-T and Q-N;
   - the data file hashes;
   - the repository rule;
   - the green test log.
5. Part A on every convertible row. Commit its receipts.
6. Build D and commit the location receipt before any D answer.
7. Run the arms.
8. Score: `RESULTS.md`, `results.json`, and `gateClaim` on the headline numbers. Publish whatever the verdicts are,
   including a run voided by a gate.

## Out of scope (later studies or amendments)

- End-to-end SWE-bench Verified: resolve rate with and without compaction mid-task.
- A synthetic stress test generated fresh on each run (RULER-style) for the worst case of the `auto` ranker.
- LongMemEval: multi-session chat memory with unanswerable questions.
- A second answerer (S6 above).

## Amendments

None yet.
