# The judge as a stash policy (research spike, 2026-10-22)

Status: **research, report only.** No product default changes. Every number here is
**INFERIDO**: one maintainer's local sessions, one offline run, one machine (macOS arm64,
Python 3.14.3, 10 CPUs), `main` at `b07567a`. Session text never left the machine; only the
counts below were kept.

Question: specialist-v3 removes 1.3–1.9% on real sessions and takes 110–206 s on large ones
([plan §1](../plan/2026-q4.md)). With `recall`, a drop is no longer high-stakes, so is the
judge useful for something else: (1) keeping inline the stash-eligible outputs that will be
needed again soon, because every recall re-sends the context; (2) writing a better pointer so
recalls hit the right blob?

## Short answer

1. **Outputs that `stashed` removes are almost never fetched again.** 6 of 6,004 (0.1%) were
   re-fetched with identical bytes, 68 (1.1%) re-fetched in any form. Outputs the rules keep
   inline are re-fetched at a similar or lower rate (0.5% in any form, about half the stashed
   1.1%; 0.12% with identical bytes, against 0.1%, a strict count that rests on 6 positives), so
   the rules are not stashing what the agent comes back for.
2. **No ranker earns a keep-inline decision.** Keeping an output inline only pays when its
   chance of being needed is above about 0.6 with a warm cache (0.08 even in the worst
   cache case). The best ranker (a 17-feature logistic
   regression) reaches 4.1% precision in its top 5%. specialist-v3 does no better than
   recency (AUC 0.60 vs 0.57, difference +0.03 [−0.09, +0.15]). Keeping even the top 5%
   inline costs 2–4× more token-requests than stashing everything.
3. **A richer pointer is cheap and useful in one way.** A lean pointer (size, lines, exit
   code, error/test identifiers, first line) costs +15 tokens per pointer, or 1.0% of the
   stashed tokens. It cuts the share of stashed outputs that cannot be told apart from
   another stashed output of the same call from 12.5% to 0.9%.
4. **specialist-v3 is slow because of the dependency graph, not the model.** 90% of an
   `auto` pass is `ContextGraph.edges_touching`, a linear scan over every edge on each call.
   Featurizing and scoring every block takes 3–6 s. Scoring only the stash-eligible blocks
   would save about 0.2 s. An edge index takes the synthetic 2,500-message pass from
   319 s to 15.6 s, and the real 2,552-message session CC-A from 156 s to 19.2 s. Decisions
   were identical on both (1,113 of 1,113 and 1,031 of 1,031).

Recommendation (detailed in §6): do not turn the judge into a keep-inline policy. Ship the
edge index (a bug fix with a parity test). Put the lean pointer behind a flag. Start
collecting real recall labels with an opt-in counter. Leave specialist-v3 as `auto` only
if the index fix lands. Otherwise make `rules` the default for `measure-session`.

---

## 1. Offline replay (task 1)

**Sessions.** Every local Claude Code session file (`~/.claude/projects/*/*.jsonl`, top level,
no subagent files) and Codex rollout (`~/.codex/sessions/**`) of at least 200 KB: 657
files. 334 have at least 30 tool calls, and 256 (253 Claude Code, 3 Codex) produced at least
one stashed output at a cut. Hermes sessions were not included.

**Cuts.** For each session, cut at 33%, 50% and 67% of its messages, moved forward to the
next user turn, which is where a compaction pass would run. Run
`provider="rules", rules_mode="stashed"` on the prefix (default `preserve_recent=6`, default
question, a temporary stash). Each output it replaces with a stash pointer is one row:
6,004 rows from 472 cuts (median 9 stashed outputs per cut, max 83).

**Labels.** These come from what the agent actually did after the cut, in a session that ran
with nothing removed:

- *key* of a call: a Read-type call is keyed by its path. A shell call is keyed by its
  whitespace-normalised command. Anything else is keyed by tool plus canonical JSON input.
- a stashed output can be labelled only if it is the **latest** output for its key in the
  prefix. An older one was already superseded before the cut. A suffix call that repeats a
  prefix call's id is a copy (resumed session), not a re-fetch.
- **strict**: an explicit `recall` of its sha256 prefix, or a later same-key call whose
  output is **byte-identical**. In those cases recall would have served exactly what the
  agent fetched.
- **broad**: any later same-key call, even when the output changed (for example a re-read
  after an edit).

**Results.**

| tool group | stashed | strict | broad | stashed tokens | strict tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| read | 2,478 | 3 (0.1%) | 1.7% | 3,201,833 | 3,422 |
| shell | 2,000 | 0 | 0.0% | 4,483,234 | 0 |
| web | 599 | 0 | 0.7% | 476,747 | 0 |
| edit | 474 | 0 | 0.0% | 57,143 | 0 |
| mcp | 293 | 3 (1.0%) | 4.8% | 451,239 | 7,230 |
| other | 101 | 0 | 0.0% | 542,771 | 0 |
| agent | 59 | 0 | 11.9% | 164,541 | 0 |
| **all** | **6,004** | **6 (0.1%)** | **68 (1.1%)** | **9,377,508** | **10,652 (0.11%)** |

- 31 of the 68 broad re-fetches are re-reads of a file edited in between. Recall would have
  returned stale bytes for those, so they are not misses.
- There were 0 explicit-recall hits. The local transcripts contain 32 `recall` calls with an
  id (7 sessions, almost all lcc development). Only 1 of them matches an output in the same
  transcript. **Real recall labels do not exist locally yet** (see §6.3).
- Base rate for outputs the rules **kept** (latest of key, same definitions): 53,414
  outputs, broad 278 (0.5%), strict 63 (0.12%).

**Distance** (requests = assistant turns after the cut; calls = tool calls since the output):

| label | n | requests after cut: p25 / median / p75 / p90 | within 5 requests | within 20 | calls since output (median) |
| --- | ---: | --- | ---: | ---: | ---: |
| strict | 6 | 3 / 12 / 28 / 40 | 50% | 67% | 38 |
| broad | 68 | 19 / 38 / 119 / 491 | 15% | 28% | 98 |

Broad re-fetches of reads (n = 43): median 35 requests after the cut, 9% within 5.

**Caveat that bounds all of this.** The transcripts ran with nothing removed. A re-fetch
there happened even though the content was still in context, so these labels measure "the
content mattered again", not "the agent would have called recall". Keeping an output inline
would not have prevented those re-fetches. The quantity a keep-inline policy would save,
extra fetches caused by the stash, cannot be observed in no-stash transcripts. It needs real
recall events (§6.3).

## 2. Does any score rank the needed-again outputs first? (task 2)

Population: the 6,004 stashed outputs. AUC uses Mann–Whitney with ties averaged. The 95% CIs
come from 1,000 bootstrap resamples of **sessions** (rows within a session are correlated),
and Δ is a paired difference on the same resamples.

- *specialist-v3*: the frozen model's block score (`score_rows`, including the size penalty
  and the floor bonus) on the prefix rendered as `_specialist_decisions` renders it, max over
  the blocks of the result.
- *simple LR*: 17 features known at cut time (log tokens, log lines, age in calls and
  messages, how many identifiers from the call input are named later in the prefix, error
  regex, path edited later in the prefix, tool group, key kind). L2 logistic regression with
  out-of-fold scores from 5 folds split by session.

**Broad label** (68 positives):

| ranker | AUC | 95% CI | Δ vs recency [95% CI] |
| --- | ---: | ---: | ---: |
| recency (newer first) | 0.566 | 0.492–0.643 | — |
| size (bigger first) | 0.383 | 0.309–0.470 | −0.183 [−0.300, −0.065] |
| size (smaller first) | 0.617 | 0.530–0.691 | +0.051 [−0.059, +0.140] |
| key named later in prefix | 0.316 | 0.240–0.399 | −0.250 [−0.350, −0.155] |
| specialist-v3 | 0.597 | 0.496–0.696 | +0.032 [−0.085, +0.150] |
| simple LR | **0.776** | 0.703–0.832 | **+0.210 [+0.109, +0.299]** |

**Strict label** (6 positives): every CI spans most of [0, 1] (recency 0.72 [0.50, 0.85],
specialist-v3 0.65 [0.32, 0.87], LR 0.74 [0.49, 0.95]). There is too little signal to rank
anything.

Precision in the top of each ranking (per session-cut), broad label: recency 1.6% (top 5%)
and 2.1% (top 10%); LR 4.1% and 3.5%; specialist-v3 1.2% and 1.4%.

How to read the LR result: its weights are mostly tool type (read and mcp up, shell down)
and a **negative** weight on "named later". An output whose path the agent kept mentioning
was usually re-read before the cut, so it is no longer the latest output for its key. The LR
learns which tools get re-run, not which bytes matter. Its AUC is real, but its precision is
two orders of magnitude below what a keep-inline decision needs (§5).

## 3. A richer deterministic pointer (task 3)

Today the note is `[removed: N tokens · lcc recall <sha12>]`. The call (tool and input) stays
inline, so the agent already sees which file or command it was. What it cannot see is which
of several same-call outputs it needs, or what the output said.

Two prototypes. Both are a pure function of the blob and its own call, with no dependency on
later transcript, so they stay a fixed point under the cache contract:

- **rich**: `[stashed <tool> <path|command, ≤60 chars> · L lines · N tok · exit X · lcc recall
  <sha12>] ids: <≤3 identifiers> | <first non-empty line, ≤80 chars>`, capped at 240 chars.
- **lean**: drops tool and argument (the inline call already says them):
  `[removed: N tokens · L lines · exit X · <≤2 identifiers> · lcc recall <sha12>] <first
  line, ≤60 chars>`, capped at 200 chars.

Identifiers come from rules: `…Error|…Exception|…Warning` type names, `FAILED|ERROR
path::test`, `test_*` names, and exit codes from `exit code N` / `Process exited with code N`
in the last 2,000 chars.

Measured on the 3,152 stashed outputs at the 50% cut (o200k tokens):

| pointer | mean tokens | median | p90 | max | extra vs note | share of stashed tokens given back | same-call outputs not distinguishable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| current note | 19.3 | 19 | 21 | 24 | — | — | 12.5% |
| lean | 34.3 | 34 | 42 | 70 | +15.0 | 1.03% | 0.9% |
| rich | 54.5 | 53 | 68 | 101 | +35.2 | 2.41% | 0.4% |

This is a proxy, not a recall-accuracy result. It shows the pointer can tell same-call
outputs apart. It does not show that the 24% of wrong-output recalls in `stashed-recall-v1`
came from that ambiguity. Two cautions for shipping:

- the first line is copied verbatim from tool output. It was already in context, but it is
  now pinned into every later request, so it should go through the same
  `terminal_safe`/printable filtering the receipt uses;
- changing the note format touches `_NOTE` (fixed-point detection) and `verify_stashed`.
  Both formats must be recognised forever, or a pass over a transcript stashed by an older
  version would re-stash its pointers and break the prefix.

## 4. Why specialist-v3 is slow (task 4)

Profile of `compact_transcript(provider="auto")` on a deterministic synthetic transcript
(2,500 messages, 1,113 tool calls, 3,066 blocks; generator in the hand-over notes):

| stage | time |
| --- | ---: |
| whole `auto` pass | 304.8 s (319.2 s on a second run) |
| `ContextGraph.edges_touching` (7,012 calls, ~2 M edges, linear scan each) | **275.4 s** |
| `_restoration_rank` sorting with graph lookups | 16.9 s |
| `build_graph` (×2) | 16.1 s |
| featurize, every block (includes `_mechanical` 1.8–3.4 s) | 3.0–5.4 s |
| model `raw()`, every block | 0.44 s |
| model `raw()`, stash-eligible blocks only (1,271) | 0.20 s |
| `rules` `stashed` on the same transcript | 5.1 s |

**Scoring only stash-eligible blocks would not remove the cost.** The model is about 2% of
the pass. Most features are global (BM25 over all blocks, later references, duplicates), so
featurize has to see every block anyway. The saving would be about 0.2 s.

**What does remove it:** index the edges per block. The experiment replaced `edges_touching`
with a per-block index that returns the same edges in insertion order (a monkeypatch in the
scratch harness; product code unchanged):

| transcript | original | with edge index | decisions |
| --- | ---: | ---: | --- |
| synthetic, 2,500 messages | 319.2 s | 15.6 s | identical, 1,113 / 1,113 |
| CC-A, real, 2,552 messages | 156.4 s (153 s alone in plan §1) | 19.2 s | identical, 1,031 / 1,031 |

The 156.4 s run overlapped another 8-process job, so it is inflated a little. The plan's
153 s was measured alone.

What is left after the fix is `build_graph` (~11 s on CC-A) and graph-based sorting, both in
the block compactor, not the model. In the replay, featurize plus score on real prefixes took
a median 0.21 s and a max of 3.4 s (472 cuts, up to 3,643 blocks).

## 5. Objective function

For one stash-eligible output *o* at pass time:

- *T* = its tokens, *P* = pointer tokens
- *R* = requests that will re-send the history before the next compaction or the end of the
  session
- *p* = chance that *o* is needed again, and *d* = requests until then
- *C* = context tokens re-sent by the extra recall round trip, and *κ* = its price relative
  to an ordinary re-sent token. κ = 1 when the recall turn reads the same warm cache as every
  other request; κ ≈ 12 (1.25 / 0.1) in the worst case, when the turn has to re-write the
  cache.

```
saving if stashed   = (T − P) · R
expected recall cost = p · (κ·C + T · (R − d))      # one extra round trip, then the bytes are back
keep inline  ⇔  p · (κ·C + T·(R − d))  >  (T − P) · R
break-even   p* = (T − P)·R / (κ·C + T·(R − d))
```

Typical stashed output: *T* ≈ 1,500, *P* ≈ 20–35, *R* ≈ 100, *C* ≈ 150k, *d* ≈ 35. This gives
*p\** ≈ 0.6 at κ = 1 and ≈ 0.08 in the cache-rewrite worst case (κ ≈ 12). The best ranker's
top-5% precision is 0.04, below both.
In the replay, keeping the top 5% inline (per cut) cost 0.11–0.17 G token-requests, against
0.04–0.05 G for stashing everything (C = 50k–150k, κ = 1). Keeping everything inline cost
2.52 G. The economics say **stash everything eligible**. They would flip only for outputs
with *p* near 1: the output the agent is about to use, which the rules already pin (recent
window, latest error, calls named in the goal).

## 6. Recommendation

### 6.1 Do not ship a keep-inline judge

The data does not support one, and the reason is structural. In the common warm-cache case
*p\** ≈ 0.6 while the base rate is ~1%, and a better model cannot close a 50× gap. Even in
the cache-rewrite worst case (*p\** ≈ 0.08), the best top-5% precision (0.04) is half of
what is needed. Re-run this only after real
recall events exist (6.3) and show a recall rate above ~10% for some identifiable class of
output.

### 6.2 What to ship behind a flag

1. **Edge index in `ContextGraph`** (not a flag; a fix). Keep a `dict[block_id, list[int]]`
   in `add_edge` and return the edges in insertion order. Add a regression test that compares
   decisions with and without the index on the judge-bench transcripts. Then re-measure
   `measure-session` on CC-A to CC-D. This is what makes `auto` affordable, whatever its
   future role.
2. **Lean pointer**, `--stash-pointer=lean` (default `plain`). Accept both note formats in
   `_NOTE` and `verify_stashed`. Filter the first line for printable, terminal-safe text.
   Cost: +15 tokens per pointer (~1% of stashed tokens).
3. **No judge in the stash path.** `rules` stays the decision maker for `stashed`.
   specialist-v3 stays a research arm (or `auto` for block mode) until it beats recency on a
   label that matters.

### 6.3 Collect the missing label (opt-in)

Every recall is a real miss label, but today nothing records one. Extend the opt-in ledger
(`receipt.py`, `LCC_LEDGER=1`) with a counts-only `recall` record: version, timestamp,
session key, pass age in requests, stashed tokens, tool group label, and whether the hash
check passed. No id, path, input or text. Leave it off by default, as the ledger is now.
After a few weeks of the maintainer's own use, this gives the *p* and *d* that §5 needs,
measured in a world where the stash actually exists.

### 6.4 Eval before any default change

Pre-register it, in the same style as `stashed-recall-v1`:

- **Lean pointer as the default**: re-run the `stashed-recall-v1` protocol (same 172
  requests, same answerer and blind judge) with `plain` vs `lean` pointers. Primary outcome:
  share of recall calls that fetch the right output (baseline 76%). Non-inferiority on
  file-path recall (margin −0.05). Report the pointer token cost from the receipt.
- **Any keep-inline policy**: only with ledger recall data from ≥ 2 people or ≥ 4 weeks.
  Primary outcome: total token-requests (§5 with measured κ) vs stash-everything. A policy
  ships only if the upper CI bound of its cost difference is below zero.
- **Edge index**: decision parity on `benchmarks/run_judge_bench.py` and the five plan
  sessions (identical decisions), plus wall time. Nothing about quality changes.

## Reproduce

The scratch scripts (replay, analysis, pointer variants, profiler, synthetic generator) are
in this spike's hand-over notes, outside the repository. They import only `lcc` (`PYTHONPATH=src`)
and numpy, write counts only, and use a temporary stash. If this direction is kept, they
can move to `benchmarks/research/` as a follow-up.

## Limits

- One maintainer, mostly Claude Code (253 of 256 sessions), one run, no Hermes.
- Labels come from no-stash transcripts (§1 caveat). Strict positives are too few (6) to
  rank anything.
- Keys are exact-match: a re-read with a different path spelling, or a command with
  different flags, is not counted. Both bias the needed-again rate down. Allowing for that,
  the warm-cache gap to *p\** (§5) stays above an order of magnitude.
- The economic model ignores output tokens and latency of the extra round trip. Both make a
  recall more expensive, but not by enough to close the gap.
