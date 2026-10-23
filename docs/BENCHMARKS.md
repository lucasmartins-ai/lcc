# Judge benchmark (synthetic, local)

`benchmarks/run_judge_bench.py` compares LCC's local judges on synthetic agent transcripts.
It runs on the CPU with no network and no API key, makes no model call, and finishes in about
20 seconds on an Apple-silicon laptop.

```sh
pip install -e '.[dev,tiktoken]'
python benchmarks/run_judge_bench.py            # writes benchmarks/results/judge_bench.{md,json}
python benchmarks/run_judge_bench.py --check --out /tmp/judge-bench   # CI: no crash + floors
```

The committed result is [`benchmarks/results/judge_bench.md`](../benchmarks/results/judge_bench.md)
(full numbers, per case, in `judge_bench.json`).

## Inputs

Nine edge cases written for this benchmark, each a short tool-call exchange holding one
must-keep string, padded before and after with the seeded transcripts from
`tests/specialist_synthetic.py`, and closed by a user question:

| case | must keep |
| --- | --- |
| supersession | the edited value (`retry_limit: 7`), not the one read before the edit |
| contradiction | the failing test that contradicts the docs |
| config_value_change | one line in a 44-line env file |
| exception_rule | the exception clause of a policy |
| pt_en_mixed | a Portuguese sentence answering an English question |
| injection_in_tool_output | a fact next to an injected instruction in a fetched page |
| large_git_diff | one changed line in a 61-hunk diff |
| old_root_cause | a traceback older than the noise that follows it |
| identical_reread | a value in a file read twice (the later copy) |

Two seeded transcripts with no labels (302 and 1,138 blocks, the held-out median and largest
sizes) are used for reduction and latency only.

## What it measures

**Ranker at fixed cuts.** Each judge scores every block. Tool calls and tool results are the
droppable candidates; they are dropped lowest score first until 30%, 50% and 70% of their
characters are gone. A case passes a cut when the block holding its must-keep string
survives. This is the raw ranking, with none of LCC's protection rules, so it compares
ordering only. Judges: `specialist-v3`, `mechanical` (LCC's lexical scorer), `bm25` and
`recency` (implemented in the script), and a seeded `random`.

**Full pass at default settings.** What a user gets: whether each must-keep string is still in
the output, token reduction, latency (median and p90 over the edge cases, median on the two
large transcripts) and peak RSS. Each pass runs in its own subprocess so peak RSS is its own.

| pass | what runs |
| --- | --- |
| `specialist-v3` | `compact_transcript`, `provider="auto"` (the default for transcripts) |
| `rules-lossless` / `rules-recoverable` | `compact_transcript`, `provider="rules"` |
| `v3-blocks` / `mechanical-blocks` | `compact_context` on the rendered transcript with block metadata |

Ranking results are deterministic. Latency and RSS depend on the machine and its load; the
result file records platform, Python version, CPU count and the load average at start.

## Results (2026-10-18, macOS arm64, Python 3.14, 10 CPUs, load average ~43)

Ranker, cases passed of 9 / mean must-keep recall:

| judge | 30% cut | 50% cut | 70% cut |
| --- | ---: | ---: | ---: |
| specialist-v3 | 8/9 · 0.89 | 7/9 · 0.78 | 7/9 · 0.78 |
| mechanical | 9/9 · 1.00 | 9/9 · 1.00 | 9/9 · 1.00 |
| bm25 | 9/9 · 1.00 | 9/9 · 1.00 | 7/9 · 0.78 |
| recency | 8/9 · 0.89 | 6/9 · 0.67 | 3/9 · 0.33 |
| random | 7/9 · 0.78 | 3/9 · 0.33 | 2/9 · 0.22 |

Full pass:

| pass | must-keep kept | token reduction, edge cases | token reduction, 302 blocks | ms, edge median / p90 | ms, 1,138 blocks | peak RSS MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| specialist-v3 (tool calls) | 9/9 | 0.4% | 3.0% | 68 / 278 | 3,407 | 71.0 |
| rules-lossless | 9/9 | 0.3% | 0.0% | 1 / 2 | 16 | 54.8 |
| rules-recoverable | 9/9 | 0.3% | 0.0% | 1 / 3 | 22 | 54.6 |
| v3-blocks | 8/9 | 21.0% | 25.4% | 69 / 282 | 3,211 | 70.9 |
| mechanical-blocks | 9/9 | 34.6% | 0.5% | 40 / 194 | 2,709 | 68.4 |

Token counts are LCC's approximate count (tiktoken encodings were not cached offline). A
process that only imports `lcc` peaks at 45.4 MB.

## How to read it

- The edge cases are lexically easy: each question shares words with its must-keep line, so
  `mechanical` and `bm25` do well. v3 misses `pt_en_mixed` at every cut (the answer is in
  Portuguese) and `identical_reread` from 50% on. This matches the private edge suite, where
  v3 was also weakest on hand-built hard cases (see [SPECIALIST.md](SPECIALIST.md)).
- In tool-call mode v3 removes little on these transcripts: short blocks are protected, so the
  usual outcome is a trim. The rules modes remove only provable duplicates; the only one here is
  the re-read. On real sessions, where tool output dominates, see
  [real-session benchmarks](REAL_SESSION_BENCHMARKS.md).
- `mechanical-blocks` removes 34.6% on the edge cases but 0.5% on the unlabeled transcripts,
  whose filler is drawn from the same word list as their goal, so almost every block clears
  the lexical threshold (3 of 282 scored blocks dropped). Lexical reduction depends on how
  much of the text shares words with the question.

## Limits

- Synthetic only. Nine hand-written cases are a smoke test of known failure modes, not an
  estimate of quality on real sessions.
- Evidence on real sessions is in [SPECIALIST.md](SPECIALIST.md) (held-out final test, tagged
  INFERIDO) and [REAL_SESSION_BENCHMARKS.md](REAL_SESSION_BENCHMARKS.md). The held-out
  comparison ran privately on the maintainer's sessions; only aggregates are published. Large
  hosted models were used there as an offline reference point only; they are not part of LCC.
- `--check` gates on: no crash, v3 ranker recall at or above 0.6 / 0.5 / 0.4 at the three
  cuts, and `rules-lossless` keeping every must-keep string. Latency is not gated.

## Efficiency gate (PR CI)

`benchmarks/efficiency_gate.py` is the regression gate for token efficiency, cache stability and
cost. It runs offline on fixed synthetic inputs (about 30 s) and compares each path with
[`benchmarks/results/efficiency_baseline.json`](../benchmarks/results/efficiency_baseline.json).

| path | input |
| --- | --- |
| `rules-lossless`, `rules-recoverable` | 300 turns of files re-read unchanged and `git status` |
| `rules-stashed` | 60 turns of `tests/specialist_synthetic.py` |
| `specialist-v3-auto-2500` | 400 synthetic turns (2,500 messages), `provider="auto"` |
| `blocks-mechanical` | the 60-turn transcript rendered with block metadata, `compact_context` |
| `intake` | a brief plus 1,500 notes through `LccIntake.process` |
| `mcp-compact-transcript` | a 300-turn `tools/call` round trip through `handle_message` |

Per path it records `tokens_in` / `tokens_out` (the approximate counter, so a machine without a
`tiktoken` cache gets the same numbers), `prefix_share` (the share of the output for a session
that survives byte-identical at the head of the output for the same session plus 6 turns: what a
prompt cache can reuse) and `cost`.

`cost` is wall time divided by a calibration loop timed in the same process (best of 3 runs,
calibration measured around each run), so a slower or busier machine moves both sides. It is a
proxy. It catches a path going from O(n) to O(n²), not a 10% change.

`--check` fails, naming the path and the delta, when:

| metric | fails when | flag |
| --- | --- | --- |
| `tokens_out` | grows more than 1% | `--token-tolerance` |
| `prefix_share` | drops more than 0.02 | `--prefix-tolerance` |
| `cost` | grows more than 50% | `--cost-tolerance` |

`tests/test_efficiency_gate.py` plants an O(n²) loop in a path and checks the gate fails it.

### Updating the baseline

When a change moves a number on purpose (a better compaction, a new fixture), run

```sh
python benchmarks/efficiency_gate.py --update-baseline --note "why the numbers moved"
```

It measures every path, rewrites the baseline and adds the note to `CHANGELOG.md` under
Unreleased. Commit both files. `--note` is required, and `--only` is refused, so a baseline is
never half updated. Do not update it to make a slow path pass: fix the path.
