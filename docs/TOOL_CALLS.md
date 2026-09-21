# Tool-call compaction (`lcc compact --mode tool-calls`)

The message-level sibling of block compaction. Block mode (`--mode blocks`, the default)
scores text blocks inside one document; this mode scores the **tool calls** of an agent
session: it pairs every `tool_use` with its `tool_result` by id and drops the pairs a
semantic judge says the session no longer needs.

Nothing is summarized. User and assistant text is never scored, never trimmed and never
rewritten; a kept result comes back byte for byte; a dropped pair disappears whole. This is
the mode a Claude Code hook drives, and the one to compare against summarization-based
compaction.

```bash
lcc compact transcript.json -q "finish the parser fix" --mode tool-calls \
  -o compacted.json -r report.json
lcc explain report.json          # why every call was kept, trimmed or dropped
```

## 1. Input and output

Input is a JSON transcript: either a bare messages array or `{"messages": [...]}`.

```json
{
  "messages": [
    {"role": "user", "text": "Fix the failing parser test. Never edit src/generated."},
    {"role": "assistant", "text": "Running the suite.",
     "toolUses": [{"tool_use_id": "toolu_1", "tool": "Bash", "input": {"command": "pytest -q"}}]},
    {"role": "user", "toolResults": [{"tool_use_id": "toolu_1", "text": "1 failed, 24 passed"}]}
  ]
}
```

Snake_case equivalents (`tool_calls`, `tool_results`) are accepted too, and a call id may be
`tool_use_id` or `id`. Output is the same shape, in the same order, with the decided pairs
removed or trimmed — so a caller can map it back onto its own session. Messages that lose
all of their content are dropped; results stay in the message they arrived in.

Malformed input fails loudly (exit 2): a decision taken over a half-parsed transcript is not
auditable. A call without a result yet is left alone — there is nothing to judge.

## 2. Decisions

For every non-pinned pair the judge answers two typed `noul` questions: does the **call**
still matter (knowing it happened, with its input), and does its **result** still need to be
there verbatim (its contents are needed and re-running would not do).

| Probabilities | Decision | Effect |
| :--- | :--- | :--- |
| `keep_result >= threshold` | `keep` | call and result stay, byte for byte |
| `keep_call >= threshold` (result below) | `trim` | call stays; result is cut to `--trim-head-chars` plus one note line |
| both below `threshold` | `drop` | call and result are removed together |

Defaults: `--threshold 0.5`, `--trim-head-chars 300`. A result is never left without its
call, and a call is never dropped without its result.

## 3. Pinning (what is never touched)

The first message and the newest `--preserve-recent` messages (default 6) are pinned: their
calls are not scored and not mutated, and they appear in the report as `source: pin` with
reason `pinned_first_message` / `pinned_recent`. Pinning is the honest way to protect a live
turn: the objective and the tool you just ran are usually the ones that matter most.

## 4. Budgets and fitting

The judge is shown the whole conversation, oldest first, with every tool result replaced by a
short note (`ok, 4213 chars`) — inputs and texts stay, payloads do not. That state is resent
with each request, so it is fitted into `--max-state-tokens` (default 25000) in stages,
cheapest first:

| Stage | What changes |
| :--- | :--- |
| `full` | as written |
| `inputs-200` | tool inputs cut to 200 chars; long non-pinned texts abridged (head + tail) |
| `calls-one-line` | non-pinned calls become one line each; old call-only messages collapse |

If even the last stage does not fit, the pass **fails closed** (`TranscriptFitError`, exit 2)
instead of judging a conversation the judge could not see. Questions are split into as many
requests as needed so state plus one batch stays under `--max-request-tokens` (default
30000, Jev's request limit is 32K); `--batch-size` caps calls per request, `--max-workers`
runs requests concurrently.

## 5. Fail-safe behaviour (never silent)

| Situation | `provider_used` | `degraded` | `semantic_guarantee` | What happens |
| :--- | :--- | :--- | :--- | :--- |
| no key / `LCC_DISABLE_NETWORK=1` | `jev` | true | `none` | every call kept, reason `jev_unavailable_fail_safe` |
| a batch fails | `degraded` when nothing was judged, `jev+partial_fail_safe` otherwise | true | `none` / `partial` | unjudged calls kept, judged calls keep their verdict |
| answer missing / malformed / outside 0–1 | — | — | — | that call is kept and the reason is a warning (`jev_missing_answer:…`, `jev_answer_out_of_range:…`) |
| nothing to score (all pinned) | `jev` | false | `none` | reason `no_candidates`; no call is claimed as judged |

`mechanical` and `laya` are refused (exit 2) in this mode: "is this tool output still needed"
is a semantic question, and a lexical scorer cannot answer it honestly. Use `--provider jev`
(or `auto`, which prefers Jev).

## 6. CLI options

Honored: `--question`, `--provider jev|auto`, `--threshold`, `--trim-head-chars`,
`--preserve-recent`, `--max-state-tokens`, `--max-request-tokens`, `--batch-size`,
`--max-workers`, `--min-reduction` (sets `worth_it`), `--model` (token counting),
`--jev-model`, `-o/--output`, `-r/--report`, `--dry-run`.

Refused with exit 2 (they would otherwise be silently ignored): `--trim-threshold`,
`--preserve-tail`, `--min-block-chars`, `--keep-regex`, `--protect-prefix`,
`--prefix-marker`, `--decisions-cache`, `--no-marker`, `--marker-scores`, `--append-to`,
`--require-exact-tokens`, `--semantic-verify`, `--no-sufficiency`, `--max-restorations`,
`--confidence-threshold`, and the `--laya-*` family.

## 7. Report and audit

The report is `transcript-compaction-1.0` with `"mode": "tool-calls"`. It carries the same
keys the block report uses where they map (`decisions`, `blocks_*` counts a call pair as one
block, `chars_before`/`chars_after`, `reduction_ratio`, `tokens_*`, `worth_it`,
`semantic_guarantee`, `warnings`), plus mode-specific ones: `messages_before`/`messages_after`,
`tool_calls_total`/`kept`/`trimmed`/`dropped`, `tool_chars_before`/`after`,
`tool_reduction_ratio` (the judged payload only), `state_tokens`, `state_fit_stage`,
`requests`. Because `decisions` keeps the block schema, `lcc explain report.json` works on it
unchanged, offline.

## 8. Python and MCP

```python
from lcc.relevance import TranscriptCompactionRequest, compact_transcript, messages_to_payload

result = compact_transcript(
    TranscriptCompactionRequest(
        payload=transcript,          # dict or list
        question="finish the parser fix",
        provider="jev",              # needs TYPESAFE_API_KEY
        preserve_recent=6,
    )
)
print(result.report["tool_calls_dropped"], result.report["tool_reduction_ratio"])
compacted_messages = messages_to_payload(result.messages)
```

MCP clients get the same pass as the tool `compact_transcript` (see `docs/MCP.md`).

## 9. Limits, stated plainly

- **Needs a judge.** No key means no pass: this mode keeps everything and says so. It has no
  offline path by design.
- **No sticky decisions yet.** Block mode can pin `(objective, block)` outcomes to keep
  output byte-stable; this mode re-scores each pass. Add a cache when a consumer needs
  byte-stability across runs (`--decisions-cache` would be the flag).
- **Block granularity.** A pair is kept or dropped whole; a 40K-char result that is half
  spent is either all there or trimmed to its head, never half-summarized.
- **Judge quality is the ceiling.** Measured on 12 evidence/noise blocks, the raw Jev judge
  made 2 false drops on the block task (`benchmarks/research/RESEARCH_STATUS.md`); the same
  warn applies here, which is why a call is only dropped when both questions are low.
