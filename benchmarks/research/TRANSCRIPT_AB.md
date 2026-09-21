# Tool-call compaction, head to head: `lcc` vs `fast-jev-compaction`

**Question.** `lcc compact --mode tool-calls` claims to drop spent tool calls without losing
anything that matters. Does that survive contact with the reference implementation of the same
idea (`tamaratran/fast-jev-compaction`, npm `fast-jev-compaction@0.4.0`) on the same
transcripts?

**Answer, in one line.** On this corpus, our arm removes 13–56% of the transcript and keeps
every required fact; theirs removes 71–83% and loses every evidence pair. Ours is not perfect
either: one of four runs dropped an evidence pair on the largest session (the other three kept
all of them). A smaller reduction alongside full recall is the trade, and it is the honest
direction — the opposite trade is measured, published, and shown below.

Date: 2026-09-21. Harness: `real` on both arms (live TypeSafe System One, resolved
`jev-1.13.0` for the `lcc` arm; the npm library does not report its resolved model).

## Method

- **Corpus** (`make_transcripts.py` → `corpora/transcripts/`): three deterministic sessions —
  small (23 messages, 11 tool calls), medium (41/20), large (65/32). Each call is labelled
  *evidence* (its result carries a required fact, worded away from the objective so no lexical
  scorer can keep it by accident), *spent* (the work is over), *noise* (topically distant), or
  *pinned* (inside the newest messages both implementations protect by design). The generator
  asserts every ground-truth literal really sits in its evidence result.
- **Arms**: `none` (identity baseline), `lcc` (Python, this repo), `fast-jev` (their npm
  library through `fast_jev_arm.mjs`, installed under `work_transcript_ab/`).
- **Matching options**: keep threshold 0.5, six pinned recent messages, 300-char trimmed head,
  25 000-token state ceiling, 30 000-token request ceiling, model alias `jev-latest`.
- **Same ruler for both arms**: token counts come from LCC's counter (`exact`, o200k) over the
  same flattened transcript, and per-pair outcomes are derived from the **emitted messages** —
  a call id is *dropped* when it is gone, *kept* when its result comes back byte-identical,
  *trimmed* otherwise. Neither tool's own bookkeeping is trusted for scoring.
- Repro: `python3 make_transcripts.py && TYPESAFE_API_KEY=... python3 run_transcript_ab.py`.
  Artifacts: `results/transcript_ab_2026-09-21_all.json` / `.jsonl` (canonical: every arm, nine
  rows), plus a partial `..._lcc_rerun_large55.json` kept as stability evidence. The arm
  selection is part of the filename, so a partial run cannot overwrite the canonical artifact.

## Results (canonical artifact, 2026-09-21)

| Session | Calls (E/S/N/P) | Arm | Tokens | Reduction | Fact recall | Evidence dropped | Spent dropped | Noise dropped | Latency | Requests |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| large | 5/14/10/3 | none | 1617 → 1617 | 0.0% | 1.00 | 0 | 0 | 0 | – | 0 |
| large | 5/14/10/3 | **lcc** | 1617 → 716 | 55.7% | **1.00** | 0 | 11 | 10 | 887 ms | 4 |
| large | 5/14/10/3 | fast-jev | 1617 → 268 | 83.4% | **0.00** | 5 | 14 | 10 | 856 ms | 1 |
| medium | 3/8/6/3 | none | 1044 → 1044 | 0.0% | 1.00 | 0 | 0 | 0 | – | 0 |
| medium | 3/8/6/3 | **lcc** | 1044 → 635 | 39.2% | **1.00** | 0 | 4 | 6 | 681 ms | 3 |
| medium | 3/8/6/3 | fast-jev | 1044 → 220 | 78.9% | **0.00** | 3 | 8 | 6 | 603 ms | 1 |
| small | 2/4/2/3 | none | 624 → 624 | 0.0% | 1.00 | 0 | 0 | 0 | – | 0 |
| small | 2/4/2/3 | **lcc** | 624 → 541 | 13.3% | **1.00** | 0 | 1 | 1 | 636 ms | 1 |
| small | 2/4/2/3 | fast-jev | 624 → 184 | 70.5% | **0.00** | 2 | 4 | 2 | 616 ms | 1 |

Both arms dropped every noise pair and (nearly) every spent pair, and neither ever touched a
pinned pair — the difference is entirely in the evidence class.

Their own bookkeeping says the same thing (`fast-jev` stats, large): `calls: 32, kept: 0,
resultsDropped: 0, callsDropped: 29, pinned: 3, requests: 1`. Our arm's report for the same
session: `provider_used: jev, degraded: false, semantic_guarantee: judged, jev_model_resolved:
jev-1.13.0, calls: 4, state_tokens: 1487, tool_reduction_ratio: 0.673` — the tool payload alone
shrank 67.3% while the whole transcript (including the untouched user/assistant text) shrank
55.7%.

**Cost basis (lcc arm, from the shared ledger, `ok` rows only):** 39 004 input tokens and
2 732 output tokens across the three sessions (4 + 3 + 1 calls: 23 419/1 466 large,
12 125/862 medium, 3 460/404 small). The npm arm reports no usage.

## Run-to-run stability (same day, same options)

| Arm | small | medium | large | Evidence pairs dropped (s/m/l) |
| :--- | :--- | :--- | :--- | :--- |
| lcc (canonical run, `..._all.json`) | 13.3% | 39.2% | 55.7% | 0 / 0 / 0 |
| lcc (partial rerun, `..._lcc_rerun_large55.json`) | 13.3% | 39.2% | 55.7% | 0 / 0 / 0 |
| lcc (run 2) | 13.3% | 39.2% | 59.1% | 0 / 0 / 0 |
| lcc (run 3) | 13.3% | 39.2% | 61.5% | 0 / 0 / 1 |
| fast-jev (runs 1–3) | 70.5% | 78.9% | 83.4% | 2 / 3 / 5 (every run) |

Small and medium reproduce exactly on both sides. The large session wobbles by ~6 points for
our arm (a borderline pair flips), and one of four runs dropped an evidence pair there — so
**individual drops are not safe by construction**, which is exactly why the block mode carries
the safety/verifier layers and why the tool-call mode only drops when *both* questions score
low. Their arm gave the same reduction to one decimal across runs on this corpus, and lost
every evidence pair each time.

## Reading the comparison honestly

- **Their arm is not "worse" in the abstract; it is answering a stricter question.** Their
  criterion for keeping a result is that its contents are still needed *and re-running the tool
  would not do*. Every synthetic call here is re-runnable (`cat reports/…`, `pytest -k …`), so
  the criterion pushes toward "spent" for the whole class. Our question — is the output still
  needed verbatim — keeps what a re-run would produce only if re-running is cheaper than the
  context it costs. The mechanism is plausible and testable; it is a follow-up, not a settled
  conclusion from one corpus.
- **Neither arm sees tool payloads in the state** (both replace results with size notes), so
  neither can judge a result by reading it. The difference is in the questions, not in the
  visibility.
- **Reduction alone would have ranked them backwards.** 83.4% with recall 0.00 versus 61.5%
  with recall 0.80 on the same session: the higher number is the one that lost the evidence.
- **The corpus is synthetic and small** (N=3 sessions, one seed, one objective). It is a
  regression harness, not evidence about your sessions. The honest claim is narrow: on a corpus
  built to punish confident dropping, our arm's questions preserved the evidence and theirs did
  not, reproducibly.

## Defects this study found in our own code (fixed before the table above)

1. **Drop decisions reported `chars_after == chars`**, so `tool_reduction_ratio` read `0.0`
   while the transcript had actually shrunk by 54%. Fixed in `_decide`; regression test
   `test_a_dropped_pair_reports_no_chars_after`.
2. **A result shorter than the trim head was "trimmed" into a longer transcript**: the audit
   note added more characters than the trim removed, so a pass could grow the context. Now such
   a result is kept whole with reason `short_result_kept_whole`; regression test
   `test_a_result_too_short_to_trim_is_kept_whole`.

Both were invisible in unit tests that only asserted the decision label, and obvious the moment
a real corpus was measured. That is the value of the harness, not a footnote.

## What this does NOT show

- No live Claude Code session was compacted end to end; this measures the compaction backends,
  not the plugin's behaviour inside an editor.
- No downstream answer quality: recall here is the presence of ground-truth literals in the
  emitted transcript, not a model's ability to answer from it.
- No cost comparison beyond the lcc arm's ledger tokens (the npm arm reports no usage).
- No threshold sweep: 0.5 on both sides, once each.
