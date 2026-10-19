# Evidence: what has been measured, and how far it goes

The numbers in the README come from three studies run on the maintainer's own Claude Code,
Codex and Hermes sessions. The sessions stay private (they hold client work); the protocols,
receipts and per-item rows live in a private repository (`lcc-judge`). This page publishes the
**aggregates**, the method and the limits, so the claims can be checked against something.
Every number here is owner-attested and labelled **INFERIDO**: one run, one person's sessions.

To get numbers that are not mine, run `lcc measure-session <session.jsonl> --markdown` and post
the output in [Discussions → Results](https://github.com/lucasmartins-ai/lcc/discussions/categories/results).

## 1. How much each mode removes (mechanical, offline)

`stashed-v1`, 2026-10-17. 847 real-session dossiers (Claude Code 446, Codex 261, Hermes 140),
45.6 M tokens in all, LCC pin `4719fde`, one offline pass per mode. Pooled token reduction
(1 − Σout/Σin, lcc tokenizer):

| mode | reduction | what a removal is |
| --- | ---: | --- |
| `lossless` | 0.9% | a pointer to an identical later output |
| `recoverable` | 1.2% | an old file read whose file is unchanged on disk |
| `lossy` (experimental) | 27.9% | old outputs dropped or trimmed; failed two blind audits |
| **`stashed`** | **30.1%** | old outputs moved to a local stash, recallable byte for byte |

`stashed` verification: 10,830 results stashed, 0 violations from lcc's `verify_stashed`, 0
from an independent checker that uses no lcc code (it re-hashes every blob). `lossless` and
`recoverable` reproduce an earlier study exactly, which checks the harness.

## 2. Does an agent still answer right? (agent in the loop)

`stashed-recall-v1`, 2026-10-18, pre-registered before any answer existed (protocol frozen,
four dated amendments, all disclosed). 172 real requests from 75 session groups. For each, the
agent got the context before the request and answered questions taken from what it really did
next. Answerer: Claude Sonnet 5.5 through `claude -p`, with one tool, `recall`. Judge: Claude
Opus 5.5, blind to the arm; a second judge (Gemini) agreed at κ = 0.91.

| | full context + tool | `stashed` + `recall` | `stashed`, no tool |
| --- | ---: | ---: | ---: |
| context tokens (pooled) | 9.40 M | **5.96 M (−36.6%)** | 5.96 M |
| file paths recalled (mean) | 0.613 | 0.619 | 0.573 |
| exact values recalled | 0.988 | 0.981 | 0.883 |
| questions about removed content answered exactly | 0.924 | 0.896 | **0.007** |

- **Pre-registered test 1 (passed):** `stashed` + `recall` is not worse than full context on
  file recall: +0.006, 95% CI −0.023 to +0.034 (margin −0.05).
- **Pre-registered test 2 (passed):** the tool is what makes it work: +0.889 [+0.820, +0.949]
  on questions about removed content.
- The agent called `recall` for 90% of those questions and 76% of its calls fetched the
  right output. Recalled text was 16% of what was stashed, so the effective context
  (kept + recalled) was a median 75% of full.

## 3. Verbatim vs a summary

`probe-eval-v1`, 2026-10-17, same 172 requests, same kind of questions. The summary arm is our
clean-room reimplementation of Claude Code's auto-compact (written by Claude Opus 5.5 from the
full context, recent files re-attached), not Claude Code itself.

| | full | summary | `lossless` | `recoverable` |
| --- | ---: | ---: | ---: | ---: |
| context tokens (pooled) | 9.41 M | 0.98 M | 9.38 M | 9.37 M |
| exact values recalled | 0.98 | **0.73** | 0.99 | 0.98 |
| judge, artifact trail (0–5) | 3.72 | 3.12 | 3.73 | 3.73 |

The summary is about ten times smaller and loses exact detail most of all. Verbatim modes keep
it. This is **not a matched-budget comparison**: no lcc mode reaches 10% of the context today,
because user and assistant text and tool-call inputs (about 27% of a session) are never cut.

## Limits

- One maintainer's sessions, one answerer model, one run per study.
- The questions about removed content were built to need it; questions that needed it naturally
  were rare (19 of 662), which is itself a finding: what `stashed` removes is seldom used next.
- During study 2 two run drivers overlapped once; 21 items were re-run and the recall numbers
  hold on the 55 items that ran once (disclosed as amendment 4).
- Recall turns re-send the context; the cost of that is not in these numbers.
- None of this says a model will answer correctly on your task. It says what was kept, what was
  removed, and that the removed part can be brought back.
