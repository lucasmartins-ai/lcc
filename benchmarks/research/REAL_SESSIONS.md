# Real sessions, measured

The synthetic A/B in `TRANSCRIPT_AB.md` proves the mechanism on a corpus designed to be
unforgiving. This file measures the shipping path on **real transcripts** — the thing the
"not verified" note in `docs/CLAUDE_CODE.md` was waiting for.

Two sources, both real, both fed through `lcc compact --mode tool-calls` (the code path the
plugin's hook calls over MCP):

| Source | What it is | Shape |
| :--- | :--- | :--- |
| Hermes session `20260921_225926_e0d6bd` | the session that built this release, pulled from `~/.hermes/state.db` | 337 messages, 187 tool calls, 199 717 tokens (the snapshot the run measured — the live store keeps changing while the session runs) |
| Claude Code session `fd825893-…` in `~/.claude/projects/-Users-Master-lcc/` | a real Claude Code session in this repository — the exact `SessionMessage` shape the plugin receives | 192 messages, 75 tool calls, 55,411 tokens |

Repro:

```bash
python3 benchmarks/research/measure_session.py --hermes latest --window-messages 60
python3 benchmarks/research/measure_session.py \
  --claude-code ~/.claude/projects/-Users-Master-lcc/fd825893-fff7-44a3-abc5-831a9e091bb0.jsonl \
  --window-messages 80
```

Artifacts: `results/real_session_2026-09-21_hermes-latest.json`,
`results/real_session_2026-09-21_claude-code--Users-Master-lcc-fd825893-…json`.

## Results (2026-09-21, live Jev, resolved `jev-1.13.0`)

| Session | Window | Tokens | Reduction | Pairs kept / trimmed / dropped | User+assistant text preserved | State | Requests | Cost (in/out tokens) | Latency |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Claude Code `fd825893` | full (192 msgs, 75 calls) | 55 411 → 18 761 | **−66.1%** | 23 / 24 / 28 | **42/42 byte-identical** | 24 076, fit `full` | 10 | 292 937 / 5 696 | 2.6 s |
| Claude Code `fd825893` | newest 80 msgs | 12 513 → 9 956 | −20.4% | 18 / 3 / 8 | **22/22** | 12 215, fit `full` | 4 | 61 982 / 2 048 | 1.2 s |
| Hermes (this session) | full (337 msgs, 187 calls) | 199 717 → 36 645 | **−81.7%** | 14 / 53 / 119 | **58/58** | 23 546, fit `calls-one-line` | 23 | 715 590 / 14 798 | 4.4 s |
| Hermes (this session) | newest 60 msgs | 19 867 → 7 261 | −63.4% | 4 / 9 / 17 | **14/14** | 14 372, fit `full` | 4 | 68 425 / 2 192 | 1.2 s |

Artifacts (run ids in the filenames, because a live session keeps growing):
`results/real_session_2026-09-21T224733Z_claude-code--Users-Master-lcc-fd825893….json` and
`results/real_session_2026-09-21T224739Z_hermes-latest.json`.

Reading it:

- **On a real Claude Code session in this repository — the exact shape the hook receives — the
  full 192-message history compresses by 66.1% with every one of the 42 user/assistant texts
  preserved byte for byte.** That is the number the plugin is for: the same conversation, minus
  the tool calls Jev says are spent.
- **A 337-message session with 187 tool calls fits and compresses by 81.7%** — but only after
  the fit ladder collapses old call-only messages to one line each (`calls-one-line`); at the
  smaller windows the state fits untouched. The consumer contract does not change: the messages
  that come back are the ones the judge decided about, texts intact.
- **Trims carry a lot of the win on real data** (53 of 186 decided pairs on the full Hermes
  session, 24 of 75 on the Claude Code session): real sessions keep calls whose inputs are still
  relevant while their payloads are spent — exactly the case the middle gear exists for, and the
  case synthetic corpora under-represent.
- **The gates fire in practice.** The Claude Code newest-80 window compresses 20.4%, below the
  plugin's 25% minimum, so the hook would keep Claude Code's built-in summary there and replace
  it in the other three cases. A gate that never fired would be a gate nobody tested.
- **Cost note: the state is resent with every request.** 23 batches × ~31k tokens is the
  715 590 input tokens above. Fewer, larger batches (`--batch-size`) cut that directly; the
  default of 8 is what these runs used.

## The defect this measurement found (fixed here)

The first run of the full Hermes session did something worse than fail. It scored the state with
the stdlib heuristic at **22 936 tokens**, judged that inside its 25 000 budget, built 38
batches, sent them, and had **every request refused** (`HTTP 400
{"error_type":"max_tokens_exceeded"}`, state 123 741 characters) — because the same state is
~31 000 real tokens. The pass then degraded to keep-everything and reported `degraded: true`,
which is the fail-safe direction but not a useful one: 38 wasted requests (6.4 s) on a session
that the judge could never have seen.

Fix, at the root: `_budget_tokens` now counts with the real tokenizer when the environment has
one, and when it does not, inflates the stdlib heuristic by the measured factor (×1.45) instead
of trusting it. Budget checks are the one place where an optimistic estimate is worse than no
estimate, because the optimistic number builds a request that gets refused. After the fix a
session that cannot fit fails closed in ~50 ms with a typed error and zero requests
(`tests/test_transcript_compaction.py::test_the_budget_is_never_optimistic`,
`::test_fitting_uses_the_budget_function`).

## What this still does not show

- **The editor never fired it.** These runs drive the same function the hook calls, with real
  transcripts, but Claude Code's own `/compact` has not been intercepted end to end. What is
  unmeasured is the plumbing (`session.compact` → `$.mcp.call` → messages back), not the
  compaction.
- **No ground truth for tool payloads.** User and assistant text is verified byte for byte; the
  119 dropped pairs on the Hermes session are judged spent, not proven spent. That is the same
  limit every compaction carries, and it is why the plugin only replaces the transcript when the
  pass is judged and the reduction clears the minimum.
- **One run per window.** The run-to-run wobble measured in `TRANSCRIPT_AB.md` (~6 points on the
  largest synthetic session) applies here too; the Hermes session is still being written, so its
  numbers move with it.
- **No downstream answer quality.** Whether a model answers as well from the compacted
  transcript is not measured.
