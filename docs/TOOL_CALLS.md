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
auditable. That includes content lcc cannot rebuild: text under `content` instead of `text`,
any other field holding a non-empty list or object (images, attachments, content blocks), a
tool result whose content blocks sit under `content`, a call `input` that is not an object, and
text that is not valid Unicode. Each error names the field. A call without a result yet, and a
result without a call, are left alone; there is nothing to judge. Calls whose id repeats are
always kept (`duplicate_tool_use_id`). Every case and its test: [EDGE_CASES.md](EDGE_CASES.md).

**Aider.** `.aider.chat.history.md` maps to user/assistant `text` messages through
`lcc.aider_history.from_aider_chat_history`, but it has no `toolUses`/`toolResults` ids, so
tool-calls mode has nothing to score. Details and a sample: [AIDER.md](AIDER.md).

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
reason `pinned_first_message` / `pinned_recent`. A call just outside the window whose result
is inside it is kept whole too (`pinned_recent_result`), so a pinned message never changes.
Pinning is the honest way to protect a live turn: the objective and the tool you just ran are
usually the ones that matter most.

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
| `--provider auto` (default) / `specialist-v3` | `specialist-v3` | false | `none` | the local ranker decides; if it fails, every call kept (`specialist_v3_failed_fail_safe`, degraded) |
| a batch fails | `degraded` when nothing was judged, `jev+partial_fail_safe` otherwise | true | `none` / `partial` | unjudged calls kept, judged calls keep their verdict |
| answer missing / malformed / outside 0–1 | — | — | — | that call is kept and the reason is a warning (`jev_missing_answer:…`, `jev_answer_out_of_range:…`) |
| nothing to score (all pinned) | `jev` | false | `none` | reason `no_candidates`; no call is claimed as judged |

`mechanical` is refused (exit 2) in this mode: "is this tool output still needed"
is a semantic question, and a lexical scorer cannot answer it honestly. Use `--provider jev`,
`auto` (default: the local `specialist-v3` ranker, [SPECIALIST.md](SPECIALIST.md)),
`specialist-v3`, `jev` (opt-in), `laya` (deprecated, opt-in), or `rules` (offline policy, below).

### Offline policy: `--provider rules`

No key, no model, no network. Four modes (`rules_mode`, MCP argument / Python API;
`--rules-mode` on the CLI):

**`lossless` (default)** — `src/lcc/relevance/transcript_lossless.py`. A tool result is
replaced by a pointer to a later result that is kept unchanged and has the same `is_error`
flag: `[identical output kept at <id>]` when the two are the same, or
`[output = lines a-b of <id>]` when the original is exactly raw lines `a`..`b` (1-based,
inclusive) of `<id>`. The note alone rebuilds the original, wherever `<id>` came from. Calls, inputs, texts and messages are never touched; nothing is
trimmed; a pointer never targets a replaced result. The only lines ignored are the Codex
`Chunk ID:` / `Wall time:` / `Original token count:` header lines (exit codes are compared).
`verify_lossless(original, compacted)` re-checks each note's exact claim from the two payloads; the pass runs it
on its own output and keeps everything if it reports a violation. `semantic_guarantee` is
`lossless`; decisions are `keep` or `dedupe` (with `kept_at`).

**`recoverable`** — `src/lcc/relevance/transcript_recoverable.py`. Everything `lossless` does,
plus an old result may become `[removed: re-read <path> (lines a-b) to recover]` (a single-file
read whose path no later non-read call names or writes) or ``[removed: re-run `<cmd>` to
recover]`` (a command on the read-only allowlist: `ls`, `find` without `-exec/-delete`, `rg`,
`grep`, `git status|diff|log|show`, `cat`/`head`/`tail`/`sed -n 'a,bp'`, `wc`, `tree` without
`-o`, `pwd`, `<tool> --version`; no pipes, redirects, substitutions or env prefixes). Never
replaced: other commands, MCP/web tools, edit results, failed results, the latest error and the
call before it, the last `preserve_recent` turns, calls named in the goal or recent user turns.
Decisions are `replace` (with `note` and `recover`), `dedupe` or `keep`; `verify_recoverable`
checks texts/inputs are unchanged and each pointer names its own call's path or allowlisted
command. Command pointers are off unless `allow_command_pointers`.

The file-pointer check has two forms (`recoverability_check` in the report):

- `transcript_proxy` (no `workspace_root`): a read is replaced only when no later call can have
  written the file — no write, patch or delete naming it, no worktree-wide git command, no
  opaque call (script, build, test run, unknown tool) that may write under its directory.
  Benched offline as v0.8 (LCC 4c39161): 0/0/0 verification on 847 items, pooled reduction
  0.0123; most removed pointers (1862 of 1978) are blocked by `file_written_later`.
- `disk` (`workspace_root` set and `disk_check` on, the default): the disk decides instead.
  A file read is replaced iff the file currently exists, its path has no `..` component, a
  final symlink does not escape the file's own directory (files outside the workspace root
  are allowed: `workspace_root` only switches the disk check on, it does not contain reads),
  it is a regular file of at most 4 MiB
  (`DISK_MAX_BYTES`), decodes as UTF-8, and its bytes hold exactly the removed output — the
  whole file, or the read's line range. The only normalisation is the one the read tool
  applied: `Read`'s `N\t`/`N→` line-number prefixes and a Codex exec header are stripped;
  CRLF never matches LF. Later writes, opaque or not, then do not matter: what the agent
  re-reads is what was removed. The pointer says so:
  `[removed: re-read <path> to recover; content verified on disk at compaction time]`.
  Reasons: `replace_disk_verified`, or `keep_disk_mismatch`, `keep_disk_missing`,
  `keep_disk_not_regular`, `keep_disk_outside_root`, `keep_disk_too_large`,
  `keep_disk_unreadable`. Right before emitting, every disk-verified file is re-hashed; one that
  changed since its check is kept (`keep_disk_changed_before_emit`). Offline benches cannot
  measure this form: the historical files have changed since the transcripts were recorded, so
  real-use numbers come from the opt-in request log.

Recommended config for live sessions: `provider: rules`, `rules_mode: stashed`, with the
`recall` tool available to the agent (in Claude Code: allow `mcp__plugin_lcc_lcc__recall`).
`recoverable` with `workspace_root` = the session's cwd (the Claude Code hook sends it) is the
option when no local stash is wanted. `lossless` stays the default `rules_mode`: it needs no
disk and makes no recovery claim, and it cuts well under 1% of real sessions.
What each mode measured on real agent sessions: [REAL_SESSION_BENCHMARKS.md](REAL_SESSION_BENCHMARKS.md).

**`stashed`** — `src/lcc/relevance/transcript_stash.py`. Removes what `lossy` would drop or
trim plus what `recoverable` would replace, but stores the exact bytes first, so nothing removed
is lost. Each removed result's UTF-8 text is written to a local content-addressed stash and the
result becomes `[removed: N tokens · lcc recall <sha12>]` (`N` counted with the request's
`model`). Default stash location by OS (file is `<stash>/<sha256>`):

| OS | Default stash directory |
| :--- | :--- |
| POSIX (Linux, macOS, …) | `~/.cache/lcc/stash` |
| Windows | `%LOCALAPPDATA%\lcc\stash` (usually `C:\Users\<you>\AppData\Local\lcc\stash`) |

`$LCC_STASH_DIR` overrides both defaults. On POSIX the directory is `0700` and files are `0600`,
written atomically. On Windows those permission bits are not applied (`os.chmod` only toggles
read-only there), so the stash does not depend on `0700`/`0600`. The whole result is replaced,
never cut: a `lossy` trim becomes a full stash. Lossless dedupes still win where they apply.
Kept as in those modes: pinned turns, the latest error and the call before it, calls named in
the goal or recent turns, failed results, duplicate ids, and results no longer than their
pointer. Calls, inputs and texts never change. Each decision is `replace` with reason
`stashed:<rule that made it eligible>` and `stash: {sha256, tokens, bytes}`; the report adds
`tool_calls_stashed` and `stash_dir`, and `semantic_guarantee` is `stashed`. `verify_stashed`
re-checks every pointer against its blob (present, hash matches, bytes equal the original); a
violation keeps everything. A blob that cannot be written keeps its result
(`stash_write_failed:<error>`).

From the CLI. Getting a result back re-hashes the blob and refuses one that fails:

```bash
lcc compact session.json -q "fix the booking KeyError" --mode tool-calls \
  --provider rules --rules-mode stashed -o compacted.json -r report.json
lcc explain report.json --only replace   # each removed output, its rule and its pointer
lcc recall 3f9a1c0b2d4e               # whole output; 12-64 hex chars of the sha256
lcc recall 3f9a1c0b2d4e --lines 40-80 # 1-based, inclusive
```

MCP: tool `recall` with `{"id": "...", "lines": "a-b"}` returns `{sha256, text}`. The stash
is local to the machine running `lcc mcp` over stdio; `lcc mcp --http` refuses both `recall`
and `rules_mode: "stashed"`, since one disk would be shared by every caller. No TTL or GC yet:
the stash grows until you delete it (`rm -r ~/.cache/lcc/stash` on POSIX, or remove
`%LOCALAPPDATA%\lcc\stash` on Windows; pointers to deleted blobs just stop resolving).

Measured once (2026-10-18, label INFERIDO: one run, one owner's sessions, one answerer model),
on 172 real Claude Code contexts with task probes, in
[lcc-judge `stashed-recall-v1`](https://github.com/lucasmartins-ai/lcc-judge/tree/main/research/goal-engine-2026-10-04/stashed-recall-v1):
- `stashed` removed 36.6% of context tokens, with 0 pointer violations.
- With `recall`, artifact recall was non-inferior to the full context
  (difference +0.006, 95% CI [−0.023, +0.034]) and recall exact match stayed at 0.98.
- `recall` is what holds it: on probes whose answer sat only in the stash, exact match was 0.90
  with the tool and 0.007 without it. Counting what agents fetched back, the effective context
  was a median 75% of full.
- For comparison, Claude Code's built-in summary on the same probes
  ([`probe-eval-v1`](https://github.com/lucasmartins-ai/lcc-judge/tree/main/research/goal-engine-2026-10-04/probe-eval-v1))
  kept about 10% of tokens but dropped recall exact match to 0.73.

**`lossy` (EXPERIMENTAL)** — failed two session-disjoint blind audits (bench v0.4: 21/150
decisions flagged; v0.5: 36/132), because its trims and drops remove output an agent may still
need. A deterministic policy (`src/lcc/relevance/transcript_rules.py`) decides each unpinned call from the transcript's
structure and records the rule as the reason: it keeps the latest error result and the call
before it, the latest `git status|diff|log`, plan/todo, edit, question to the user, the most
recent result, and calls on files/URLs named in the goal or recent turns; it drops outputs
superseded by a later successful whole-file Read/Write of the same file (a partial Read with
`offset`/`limit` or a failed one never supersedes) or the same call run again with the same
output, ignoring Codex chunk/timing header lines (`superseded_by_later_call:<id>`; a rerun
whose output changed, such as a poll or a test before and after a fix, is not dropped)
and successful reads far from recent work (`stale_read_far_from_recent_work`); it trims other
outputs over 4000 chars to a 1000-char head + 1000-char tail (`large_old_output_trimmed`),
except outputs from the last 40 messages, `write_stdin`/wait polls, error-bearing outputs,
reads of a file a later edit or `apply_patch` body (sent through any tool) changes, and calls naming a path from the goal
or recent turns (`trim_guard_*`, kept whole). `semantic_guarantee` is
`none`. Pass `is_error: true` on a tool result when the host knows it failed: when any result
carries the flag it alone marks errors; otherwise an error regex is applied to command output
only, never to Read/Grep of source.

## 6. CLI options

Honored: `--question`, `--provider jev|laya|auto|rules|specialist-v3`,
`--rules-mode lossless|recoverable|stashed|lossy` (with `--provider rules` only; refused
elsewhere), `--threshold`, `--trim-head-chars`,
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
Clients that cap a tool result's size ask for `ref_unchanged: true, ref_blocks: true`: the
answer refers back to the input by index and carries only replaced text (the Claude Code plugin
does, see [`docs/CLAUDE_CODE.md`](CLAUDE_CODE.md#the-mcp-result-cap)).

## 9. Limits, stated plainly

Measured against the reference implementation (`fast-jev-compaction` 0.4.0) on the same three
synthetic transcripts, with matching options and live Jev: this mode removed **13.3 / 39.2 /
55.7%** of the transcript at fact recall **1.00 / 1.00 / 1.00**, while that library removed
70.5 / 78.9 / 83.4% at recall 0.00 — it dropped every evidence pair. Reduction alone would rank
them backwards. Method, stability runs and limits: `benchmarks/research/TRANSCRIPT_AB.md`; the
canonical row is in `benchmarks/research/RESEARCH_STATUS.md`. The largest session ranged
55.7–61.5% across four runs, and one of those runs dropped one evidence pair, which is why a
pair only falls when *both* questions score low.

- **The Jev judge needs a key.** No key means no Jev pass: it keeps everything and says so.
  The offline paths are `--provider laya` (local judge) and `--provider rules` (no model).
- **Budgets are counted with the real tokenizer.** The state budget decides what the judge can
  see; an optimistic count builds requests the API refuses, so when no tokenizer is installed
  the heuristic is inflated by the measured factor instead of trusted. Real-session numbers and
  the defect that motivated this: `benchmarks/research/REAL_SESSIONS.md` (a real Claude Code
  session: −66.1%, all 42 texts preserved; this release's own 337-message session: −81.7%, all
  58 texts preserved).
- **No sticky decisions yet.** Block mode can pin `(objective, block)` outcomes to keep
  output byte-stable; this mode re-scores each pass. Add a cache when a consumer needs
  byte-stability across runs (`--decisions-cache` would be the flag).
- **Block granularity.** A pair is kept or dropped whole; a 40K-char result that is half
  spent is either all there or trimmed to its head, never half-summarized.
- **Judge quality is the ceiling.** Measured on 12 evidence/noise blocks, the raw Jev judge
  made 2 false drops on the block task (`benchmarks/research/RESEARCH_STATUS.md`); the same
  warn applies here, which is why a call is only dropped when both questions are low.
