# LongHealth v2: retrieval and a matched-budget summary (draft 2026-11-07)

**Status: draft, not approved.** No model call runs until the owner approves the route and the caps (Run order,
step 2), and the driver refuses to start while its `APPROVED` is unset. Record texts, questions, options, excerpts,
summaries and answers never enter this repository (Data use). Results are tagged INFERIDO until `gateClaim` returns
PASS on them.

## Why

LongHealth v1 ([`../longhealth-v1/PROTOCOL.md`](../longhealth-v1/PROTOCOL.md),
[`RESULTS.md`](../longhealth-v1/RESULTS.md)) passed H1 and failed H2. On 2026-11-07, after reading the results, the
owner held the preprint back: "Ao meu ver esta cheio de gapes que precisariamos corrigir e atacar antes de lancar e
divulgar" ("as I see it, it is full of gaps we would need to fix and attack before launching and promoting it"),
naming H2, more vendors and a retrieval baseline. v2 answers four gaps:

1. **No retrieval baseline.** A reviewer will ask how `stashed` + `recall` compares with retrieval-augmented
   generation (RAG) over the same records. v1 has no such arm.
2. **H2 had no budget pressure.** v1's full contexts averaged about 55,000 tokens per session, well inside the
   answerer's window. The clinical summary context kept 0.427 of `C` (1,237,121 of 2,898,882 tokens), less than the
   stashed context (0.551), and the two tied on E. Compaction exists to free most of the window, and v1's H2 says
   nothing about a summary that has to fit a budget. v1 flagged this: H2 "is not a matched-budget comparison".
3. **One answerer family.** Answerer, summarizer and the assistant that built the study all come from Anthropic.
   S6 (v1 Amendment 5) adds GPT as a second answerer for `full_t` and `stashed_t`. v2 adds GPT's `none` and, in
   tier 2, GPT on `rag_t`, all descriptive. A Gemini answerer was drafted and then left out by the owner on
   2026-11-08, after the Gemini CLI refused a free-tier Google login. So v2's primaries name Claude alone, and this
   gap stays partly open.
4. **One run.** v2 reruns `full_t` and `stashed_t` with the v1 answerer, which gives a test-retest measure and
   contemporaneous controls for the new arms.

**What v2 does not change.** v1's verdicts stand as scored: H1 PASS, H2 FAIL, H3 descriptive. v2 is a separate
study with its own hypotheses, and its numbering continues v1's (H4–H6, S7–S13) so the two never share a label.

**What v2 cannot fix.**
- It was designed after v1's results were known, on the same 18 targets and the same questions. LongHealth has 20
  patients and v1 used all of them. v2 is new comparisons on known data, not fresh data. The
  public clinical sets with real records (MIMIC-derived sets, emrQA, EHRNoteQA) need credentialed access or a data
  use agreement, so a second benchmark is out of scope.
- Contamination: `none` answered 0.597 in v1. v2 measures it per answerer and cannot remove it.
- Review by people outside the project, which only outside readers can give.

## Data, sessions and compaction

Unchanged from v1, and reused rather than rebuilt:
- LongHealth at the v1 commit and blob hash, the pilot pool (2 patients) and set D (18 targets × `ans_early`,
  `ans_late`, `unans` = 54 sessions).
- The v1 sessions `C`, compactions `C'`, stashes, location receipt and E stratum, read from v1's private root and
  never written. The stash arms therefore run at v1's LCC pin, `17d9595`, with `head` pointers.
- All 54 sessions run in v2. v1 dropped `patient_12__ans_early` for a `summary_clin` classifier stop (v1
  RESULTS, Dropped session), which concerns no v2 input.

## Arms

Every arm gets the same session order, `P` and answer format as v1. New texts are below; their sha256 is recorded at
the freeze.

| arm | context | tool | answerers | role |
|---|---|---|---|---|
| `none` | the 20 questions, A–E (Q-N) | none | GPT; Claude's is v1's | contamination check (V6) |
| `full_t` | `C` | `recall`, empty stash | Claude (rerun) | reference for H5 |
| `stashed_t` | `C'` | `recall` over the stash | Claude (rerun) | treatment for H4 and H5 |
| `stashed_tN` | `C'` | `recall`, at most the session's budget N in all | Claude | treatment for H6 |
| `rag_t` | retrieved excerpts (Q-R) | none | Claude; GPT in tier 2 | comparator for H4 |
| `summary_m32` | `C'` with the stash replaced by a summary of budget N (b = 0.32) | none | Claude | comparator for H6 |
| `summary_m11` | the same, b = 0.11 | none | Claude | secondary S9 |

**Answerers.**
- Claude: `claude-sonnet-5-5` at medium effort through `claude -p`, with v1's frozen harness, isolation and
  settings.
- GPT: S6's runner, `gpt-6.1-sol` at medium effort through `codex-cli 0.166.0`, with S6's isolation, unchanged.
- Refusals follow v1 Amendment 5 for both: a provider refusal or safety stop is scored wrong on all 20 questions,
  listed and counted in V5, never retried and never dropped. Any other failed turn is infrastructure (V2).

### `rag_t`

RAG over the session's own records: the agent's earlier reads are gone from the context, and the excerpts most
similar to the questions come back.

- **Index:** every record text read in the session (6 patients), split into windows of 200 words with a stride of
  150 (50 words of overlap). The last window of a text ends at the text's end.
- **Excerpt header:** `[records/p<id>/text_<n>.txt · "<opening>" · excerpt <i>]`, where `<opening>` is the
  opening that lcc's `head` pointer shows for that record at the pin (at most 160 characters). So RAG gets the same
  identity cue as a stash pointer. A window from the middle of a letter often names no patient.
- **Query:** one per question: `P`'s header line (name and birth date), the question text and options A–E. RAG sees
  the questions by design; `stashed_t` sees them only at answer time, through `recall`.
- **Retrieval:** top 5 windows per question, union over the 20 questions with duplicates removed, ordered by file
  then position. At most 100 windows (about 20,000 words); the receipt reports the actual sizes next to `stashed_t`'s
  restored context.
- **Retriever, chosen on the pilot pool only.** Candidates: BM25 (k1 = 1.2, b = 0.75, written in the harness),
  `BAAI/bge-base-en-v1.5` (general-domain dense) and `ncbi/MedCPT` (biomedical dense, separate query and article
  encoders). Each runs on the pilot pool's answerable questions, and the one with the highest coverage (below) is
  used for D. Among candidates tied at the highest coverage, the first in the order `bge-base-en-v1.5`, MedCPT,
  BM25 wins. This uses gold on the 2 pilot-pool targets only and makes RAG as
  strong as these candidates allow. The weights are downloaded once into the private root and pinned by revision
  at the freeze; every later run is offline.
- **Coverage:** LongHealth's `answer_location` gives, for each text that holds the answer, one or more spans as
  relative positions between 0 and 1 (many are points, start = end). A question is **covered** when, for at least
  one of those spans, a retrieved window from that text overlaps the span scaled to the text's length in characters
  and widened by 200 characters on each side. Retrieving some other window of the right file does not count. File
  level coverage (any window from an answer text) is reported beside it. Selection on the pilot and V7 use
  span-level coverage. Coverage per condition goes into `rag-receipt-D.json`, committed before any `rag_t` answer.
  Like v1's location receipt it reads gold, and no arm does.
- **Answerer text Q-R** (draft):

```
You are answering questions from a chart-review session. The text above holds excerpts retrieved from the session's records for these questions. Each excerpt starts with a header of the form [records/p<id>/text_<n>.txt · "<the opening of that record>" · excerpt <i>]. For each numbered question, choose one option from A to F. Answer on one line per question, in this form:
<number>: <letter>: <exact option text> | quote: "<words copied exactly from a record that support the option>"
You may give up to three quotes, separated by " | quote: ". Each quote must be at least 20 characters copied exactly from one record. For option F, write no quote. Choose F when the records you have do not answer the question about this patient.
```

From "For each numbered question" on, Q-R is v1's Q-0 word for word.

### `summary_m32`, `summary_m11` and `stashed_tN`

H6 gives both compactions the same budget N for what stands in for the removed reads. The summary spends N up front,
blind to the questions. `stashed_tN` keeps its pointers and spends the rest of N on `recall` once the questions are
in view. Everything else in the two contexts is identical.

Both arms are measured against one base: `C'` with every stashed read removed (call and pointer). An arm's spend is
what it adds to that base, counted by v1's frozen renderer and token counter on the serialized context, so call
lines, block headers and the summary's lead-in all count. For `stashed_tN` the spend is P, the stashed `Read` calls
and pointers it keeps, plus the tokens its recalls return. For the summary arms it is S, the whole summary message.
H6 holds P + recalled ≤ N and S ≤ N.

- **Input:** the session's first user message and the reads lcc stashed (each `Read` call with its result), in
  session order, rendered as v1 renders `C`. The summarizer never sees `P`, as in v1.
- **Context for the answer:** `C'` with every stashed read removed (call and pointer), and one user message at the
  position of the first removed read: `Summary of the records read earlier in this session, which were removed from
  the context:` followed by the summary. The reads lcc kept in view stay exactly as in `C'`. Then `P`, then Q-0.
- **Budget:** N = ceil(b × T) tokens, where T is the stashed reads' size in lcc's heuristic tokens, the counter v1
  used. The summary prompt asks for M = N − h tokens and about W = round(0.75 × M) words, where h is the spend of
  the summary message with an empty summary, so a summary that meets the prompt fits N.
  - **b = 0.32 (primary).** In v1's `ans_early` sessions, recall brought back 0.312 of the stashed tokens: the
    harness's own `recall_behaviour` (R4), restricted to the 17 kept `ans_early` sessions. In `ans_late` and `unans`
    it brought back none, and pooled over all sessions it was 0.106. The summarizer cannot know the condition, so it
    gets the share recall used where recall was needed, rounded up in the summary's favour.
  - **b = 0.11 (secondary, S9):** the pooled share, rounded up.
- **`stashed_tN`:** `stashed_t` with one more cap. Its spend P counts against N, and the recalls of one answer may
  return at most N − P tokens in all (zero if P ≥ N). A recall that would pass that total returns the
  first tokens that fit and a note that the budget is spent, as v1's shim does at its per-call cap. A small v2
  wrapper around v1's `recall_shim.py` keeps the total; v1's shim and its other caps (8 calls, 20,000 tokens per
  call) are unchanged. The prompt is Q-T, as for `stashed_t`.
- **Summarizer:** `claude-opus-5-5` at high effort, as in v1, with its `<analysis>` part stripped.
- **Summary text S-clin-m** (draft): v1's S-clin, adapted to a partial summary, with the budget added:

```
Write a summary of the records below. It will replace them in the session, and work will continue from your summary and the records read after these. First reason inside <analysis> tags (this part is removed), then write <summary>. For each patient folder: the patient's name and date of birth as written; every diagnosis with its date; every treatment with drug, dose, route, schedule and dates; every lab, imaging and pathology value with its unit and date; procedures, complications and outcomes with dates; and anything recorded as absent, negative or not done. Copy names, numbers, units and dates exactly as they appear. Your <summary> must stay under {M} tokens, about {W} words. If it cannot hold everything, keep what a later question about any of these patients is most likely to need.
```

- **Overflow:** a summary whose S is at most N is used as written. A longer one gets one re-ask, a new call carrying
  the input, the long summary and `Your summary has about {X} tokens. Rewrite it under {M} tokens, about {W} words,
  with the same instructions.` If S is still above N, the summary is cut to the longest prefix with S ≤ N that ends
  at a line break; with no line break in range, at a sentence end; with neither, at a space. No summary enters an
  answer context above N. Re-asks and cuts are counted per arm (V8).
- **No separate native `/compact` arm.** v1's `summary_s` is `probe-eval-v1`'s native-compaction arm step for step
  (generic text S, then up to 5 recent files re-attached), and it trailed `stashed_t` by 10.8 points on E.

## Scoring and metrics

v1's scoring and metrics, unchanged: the letter rule, A, E, U, UA, response failures, the substring rule as a
sensitivity analysis, cumulative usage per arm, and R1–R6 for the `recall` arms. New:
- **RAG size:** retrieved tokens per session, as a median ratio to `C`, next to `stashed_t`'s restored context.
- **Summary size:** N, the summary's actual tokens, re-asks and cuts.

## Gates (per hypothesis)

Every primary is answered by Claude. Each hypothesis is gated only on the arms it uses: H4 on `full_t`, `stashed_t`, `rag_t`
and `none`; H5 on `full_t`, `stashed_t` and `none`; H6 on `full_t`, `stashed_tN`, `summary_m32` and `none`. A gate
that fails makes that hypothesis descriptive. A secondary or tier-2 arm can never void a primary. The numbers are
published either way.
- V1: `full_t` A ≥ 0.60 (Claude rerun).
- V2: infrastructure failures retried as in v1 (3 attempts, 5 for summaries). A session is dropped from a
  hypothesis when any arm that hypothesis uses has a terminal infrastructure failure there; at most 5% of the 54
  sessions may drop per hypothesis. Refusals are scored wrong, never dropped (v1 Amendment 5). This
  covers a summarizer stop: if the provider stops a summary, that summary arm scores wrong on all 20 questions of
  that session.
- V3, V3b: properties of the sessions, held from v1.
- V4: a scripted `recall` through the `stashed_tN` wrapper returns the stored bytes and stops at N − P.
- V5: ≥ 95% of answer lines parse in each arm the hypothesis uses.
- V6: if Claude's `none` A reaches its v2 `full_t` A − 0.10, Claude is contaminated and every primary becomes
  descriptive. Claude's `none` is v1's (Q-N, 18 targets, 215/360), reused: it reads no session, so a rerun would only
  repeat it. GPT's `none` (v2) is read the same way against S6's `full_t`, and flags only GPT's secondaries.
- V7 (new): `rag_t` span-level coverage ≥ 0.80 on D's answerable questions, from the receipt. Below that the
  retriever is too weak to test against, and H4 becomes descriptive.
- V8 (new): at most 10% of `summary_m32` summaries cut after the re-ask. Above that the summary did not meet the
  budget in its own terms, and H6 becomes descriptive.

## Hypotheses and pass criteria (declared before any v2 answer)

**Statistics.** Paired cluster bootstrap over the 18 targets, 2,000 resamples, seed `20261108`, all of a target's
questions in all conditions together; per-patient differences for every contrast. The three hypotheses are separate questions with their own criteria. S12 repeats them with
Bonferroni-adjusted 98.33% CIs.

**H4 (primary, against retrieval).** `stashed_t` is not worse than `rag_t` on A (Claude).
- PASS iff the 95% CI lower bound of `stashed_t − rag_t` is > −0.05.
- Reported with E, U, UA, both contexts' sizes and cumulative usage.

**H5 (primary, H1 replicated).** `stashed_t` is not worse than `full_t` on A (Claude rerun).
- PASS iff the 95% CI lower bound of `stashed_t − full_t` is > −0.05.
- S6's GPT numbers stay descriptive, as Amendment 5 declared, and are shown beside H5.

**H6 (primary, same budget, exact values).** On E, `stashed_tN` beats `summary_m32` (Claude).
- PASS iff the 95% CI lower bound of `stashed_tN − summary_m32` is > 0.
- Both arms get the same N per session for what replaces the removed reads, which v1's H2 did not have. H6 does
  not revise H2.

**What each outcome would mean**, written down now so the results cannot pick the reading. Each contrast gets two
readings from its 95% CI. The first answers the hypothesis:
- **PASS**, as defined above.
- **Contrary**: for H4 or H5 the upper bound is below −0.05 (the stash is worse by more than the margin); for H6 the
  upper bound is below 0. The paper then says the comparator did better on this task: retrieval with the questions
  in hand (H4), the full context (H5), or the summary at the same budget (H6).
- **Inconclusive**, anything else: the run could not decide the hypothesis. An H6 that misses PASS is not evidence
  that the summary is as good; an H4 or H5 that misses PASS is not evidence that the stash is worse by the margin.

The second is the direction, reported apart from the first: **difference detected**, naming the arm that did better,
when the CI excludes 0, and **no difference detected** when it does not. So an H4 with CI [−0.06, −0.01] reads
inconclusive on the margin and difference detected in retrieval's favour, and an H4 PASS with CI [−0.04, −0.01]
reads within the margin and difference detected in retrieval's favour. No difference detected is never read as
equivalence.

**Secondaries (CIs, no pass claim).**
- S7: the H4 and H5 contrasts on E, U and UA, and by condition; `rag_t` coverage by condition.
- S8: test-retest. Claude's v2 `full_t` and `stashed_t` against v1's answers on the 53 sessions both have: A per
  arm in each run, per-item agreement, and the H1 contrast in each run.
- S9: `stashed_t − summary_m11` on E and A (not budget-matched: `stashed_t` has no total cap); `stashed_t −
  summary_m32` on E and A; and `stashed_tN − stashed_t`, what the budget costs the stash. Per session: N, P, the
  tokens `stashed_tN` recalled, and how often it hit the budget.
- S10: `summary_m32` against v1's `summary_clin` on E and A (53 sessions; different runs and dates).
- S11 (tier 2): GPT's `rag_t` against S6's `stashed_t` on A and E, the H4 contrast in a second family.
- S12: H4–H6 with 98.33% CIs.
- S13: `none` for Claude (v1) and GPT (v2), with chance (0.20) beside it.

**Power (INFERIDO).** v1's H1 CI on A was about ±2 points and its H2 CIs on E about ±2.5 to ±5. The −5 margins of
H4 and H5 have room if the true difference is near 0. H6's CI on E should be about ±2.7 points, so a true gain
below about 3 points will often miss it.

## Leakage and design risks

| risk | control |
|---|---|
| v2 designed after v1's results | Declared above. v1's verdicts stand; v2 tests new contrasts with criteria fixed before any v2 answer. |
| The budget b taken from v1's data | Declared, with how it was computed. It is rounded up in the summary's favour, and b = 0.11 is reported too. |
| Weak RAG | Three retrievers, the best chosen on the pilot pool; the same identity header as the stash pointer; V7. |
| Retriever chosen on D | Selection reads gold on the 2 pilot-pool targets only; D's coverage receipt is written after the choice. |
| Gold seen by an arm | No arm reads `correct` or `answer_location`; only scoring and the receipts do. |
| Summary starved by the format | It replaces only what the stash removed, keeps the same in-view reads, and gets a re-ask before any cut (V8). |
| H6 budgets not equal | Both spends are counted on the serialized context against one base, calls and headers included; the summary is held to S ≤ N, and `stashed_tN`'s recalls to N − P by the wrapper (V4). S9 reports how often each hit N. |
| Drift between v1 and v2 runs | Claude reruns `full_t` and `stashed_t` (S8); the primaries compare runs made in v2. |
| Refusals hiding losses | Scored wrong, never dropped (V2). |

## Data use

As v1. Record texts, questions, options, excerpts, summaries, recalled text and answers live only under the private
root `~/.lcc/bench/longhealth-v2/` (v1's root is read, never written). The repository gets the driver, its tests,
receipts with counts and hashes, `results.json` with aggregates, and per-item 0/1 scores keyed by
`(patient_id, question_no, condition, arm, answerer)`. Nothing from this study trains or tunes any lcc ranker or
judge.

## Budget (owner approval required before any call)

All calls run on plans the owner already has: no new cash. Each route has its own hard cap, call ledger and driver
lock, and only one driver per route runs at a time.

| route | pilot | D, tier 1 | D, tier 2 | reserve | cap |
|---|---|---|---|---|---|
| Claude subscription | 36 | 432 | 0 | 58 | **526** |
| ChatGPT Plus (S6's runner) | 2 + 6 | 18 | 53 | 11 | **90** |

- Claude pilot: on the 6 pilot-pool sessions, `rag_t` 6, `stashed_tN` 6, `summary_m32` 6 summaries + 6 answers,
  `summary_m11` 6 + 6. D tier 1: `full_t`, `stashed_t`, `stashed_tN`, `rag_t` 54 each, `summary_m32` and
  `summary_m11` 54 summaries + 54 answers each. Claude's `none` is v1's, so it costs no call.
- GPT: `none` 2 in the pilot and 18 in D (tier 1); `rag_t` 6 in the pilot and 53 in D on S6's sessions (tier 2).
  GPT gets the least because the same plan carries the owner's Codex code reviews.
- Order on Claude: every arm a primary uses (`full_t`, `stashed_t`, `stashed_tN`, `rag_t`, `summary_m32`, 324
  calls) finishes, retries and re-asks included, before `summary_m11` starts. The reserve serves primary arms first.
- Reserve: V2 retries and summary re-asks. A run that reaches its cap stops; what is left counts as V2 drops for
  that route, and by the order above only secondary arms can be left.
- Tier 2 runs only after every tier-1 arm of every route is done. Tier 2 feeds secondaries only, so leaving it
  unrun changes no primary.
- Pacing: no Claude or GPT call starts while that plan's 5-hour or weekly window is at 80% or more (v1 Amendment 3,
  S6). No driver spends a plan reset credit.
- Downloads: the two dense retrievers' weights from Hugging Face (`BAAI/bge-base-en-v1.5`, `ncbi/MedCPT` query and
  article encoders, about 1.3 GB together), into the private root.

## Run order

1. This file committed as a draft.
2. The owner approves the routes, caps and downloads (dated line here). Until then nothing runs.
3. Driver and tests in `benchmarks/research/longhealth-v2/`. The driver imports v1's frozen harness and changes none
   of it, as S6 does. Tests use fake CLIs and make no model call.
4. The `stashed_tN` wrapper check (V4), retriever selection on the pilot pool, then the pilot on the 6 pilot-pool
   sessions: every new arm. A pilot that shows a problem changes the design by a dated
   amendment, before the freeze, never after.
5. Freeze amendment: the driver's sha256, Q-R, S-clin-m and the re-ask text, the chosen retriever and its revision,
   and the green test log.
6. Receipts before any D answer: `rag-receipt-D.json` (coverage, sizes), and per session, for both values of b,
   the budgets N and M, h, and `stashed_tN`'s spend P.
7. D, tier 1 on every route, then tier 2.
8. Score: `RESULTS.md` and `results.json`, `gateClaim` on the headline numbers. Publish whatever the verdicts are,
   including runs a gate voids.

## Amendments

None yet.
