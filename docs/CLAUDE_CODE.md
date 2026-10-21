# Claude Code plugin (`lcc` on the Claude Code marketplace)

`lcc` ships a Claude Code plugin that replaces the built-in compaction **summary** with
verbatim compaction: the session transcript goes to the plugin's own `lcc mcp` server, the
local `specialist-v3` ranker says which tool calls and results are spent, and those pairs are
dropped or trimmed. Kept messages carry
their original bytes; user and assistant text is never scored, trimmed or rewritten. The
decision logic, the report schema and the fallback rules are the ones documented in
[`docs/TOOL_CALLS.md`](TOOL_CALLS.md) for `lcc compact --mode tool-calls`.

## Install

```bash
export CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1   # required while function hooks are early access

pip install "local-context-compiler[tiktoken]"   # the `lcc` CLI and its MCP server

claude plugin marketplace add lucasmartins-ai/lcc
claude plugin install lcc@lcc
```

The hook reaches its server through `$.mcp.call`, which goes through tool permissions: allow
`mcp__plugin_lcc_lcc__compact_transcript` (in `permissions.allow`, or answer the prompt), or the
call is refused and the built-in summary runs.

Requirements: Claude Code **2.1.274 or newer** and `lcc` on `PATH`. The default judge
(`provider: auto`, i.e. `specialist-v3`) runs locally with no key and no network
([details](SPECIALIST.md)). `provider: rules` is the offline deterministic policy. Jev is
opt-in (`provider: jev`, needs `TYPESAFE_API_KEY`); Laya is deprecated and runs only when named.
Against a checkout, without installing:

```bash
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir plugins/claude-code
```

## Layout

| Path | What it is |
| :--- | :--- |
| `.claude-plugin/marketplace.json` | the marketplace this repository hosts (name `lcc`) |
| `plugins/claude-code/.claude-plugin/plugin.json` | the plugin manifest and its configurable options |
| `plugins/claude-code/.mcp.json` | starts the plugin's own `lcc mcp` server |
| `plugins/claude-code/hooks/hooks.json` | registers the hook module and the two classic hooks |
| `plugins/claude-code/hooks/lcc-compact.mjs` | the adapter: `session.compact` → `compact_transcript` → messages |
| `plugins/claude-code/hooks/map.mjs` | the pure mapping helpers, unit-tested on their own |
| `plugins/claude-code/scripts/lcc-pin.mjs` | the classic-hook fallback: `PreCompact` instructions and `SessionStart` (`compact`) re-pin |
| `plugins/claude-code/hooks/README.md` | operator guide: what runs, what falls back, what is limited |

The hook is plain ESM with no build step and no dependencies: the Python package does the
work, the plugin translates.

## Options

Set through `/plugin` → lcc, or `claude plugin install lcc@lcc --config key=value`
(defaults in parentheses):

| Option | Meaning |
| :--- | :--- |
| `question` (`""`) | the objective; empty uses the text after `/compact`, or the newest user prompts |
| `threshold` (`0.5`) | below this keep-probability a call or result becomes a candidate for removal |
| `preserveRecentMessages` (`6`) | newest messages never scored, never mutated |
| `trimHeadChars` (`300`) | characters kept from a spent result whose call still matters |
| `maxStateTokens` (`25000`) | token ceiling for the conversation shown to the judge |
| `maxRequestTokens` (`30000`) | ceiling for state plus one batch of questions per request |
| `minReductionRatio` (`0.25`) | below this share removed, the plugin keeps the built-in summary |
| `server` (`plugin:lcc:lcc`) | MCP server name to call, as Claude Code names the plugin's own |
| `idleStash` (`false`) | opt-in idle stash, see [below](#idle-stash-opt-in) |
| `idleTtlSeconds` (`7200`) | idle seconds after the last turn before a resumed session's cache counts as cold |
| `idleMinRemovableTokens` (`10000`) | below this many removable tool-output tokens the idle stash does nothing |
| `idleMaxPassesPerSession` (`8`) | cap on idle stashes per session |
| `ledger` (`false`) | opt-in local ledger for the statusline, see [below](#receipt-ledger-and-statusline) |

## Receipt, ledger and statusline

**Receipt.** Every compaction this plugin applies toasts one line built by the server
(`lcc.receipt.receipt_line`): tokens before and after, what was removed, and how to get it back.

```text
lcc: verbatim compaction via rules, no summary (48,210 -> 31,004 tokens (-17,206, -35.7%) · 2 stashed, 1 deduped · recall: lcc recall aaaaaaaaaaaa (+1 more))
```

The CLI prints the same line last after `lcc compact --mode tool-calls`; `--receipt` prints the
full one (the five largest stashed outputs with their `recall` ids, and the cache effect).
Dropped or trimmed outputs (a judge, or `rulesMode: lossy`) are not recallable, and the line
says so.

**Ledger (opt-in, off by default).** With `ledger: true` (or `LCC_LEDGER=1` in the MCP
server's environment) the server appends one JSON line per compaction the hook applies to
`~/.cache/lcc/ledger.jsonl` (`LCC_LEDGER_PATH`; directory `0700`, file `0600`):

```json
{"v":1,"ts":"2026-10-21T09:12:03Z","session":"e279159a3ffc189d","provider":"rules","tokens_before":148210,"tokens_after":121004,"stashed":14,"deduped":3,"replaced":16,"dropped":0,"trimmed":0}
```

Counts and fixed labels only: no transcript text, no paths, no tool names or inputs, and the
session id only as a truncated SHA-256. Nothing reads it but the statusline, and nothing is
sent anywhere. The server writes it (hook modules have no file system) only for a pass that
meets the hook's own replacement rule (not degraded, over `minReductionRatio`, removed
something). Idle-stash passes are not recorded: the server cannot see whether Claude Code
accepts that compaction. The HTTP server (`lcc mcp --http`) refuses `ledger`, as it refuses
the stash, and never writes the ledger even when it inherits `LCC_LEDGER=1`. Delete the file to reset it.

**Statusline.** `scripts/statusline.mjs` reads the ledger and Claude Code's statusline JSON
on stdin. Add it to `~/.claude/settings.json` with the plugin's path on your machine:

```json
{ "statusLine": { "type": "command", "command": "node /path/to/plugins/claude-code/scripts/statusline.mjs" } }
```

It prints the tokens this session's passes removed, the outputs stashed, and the cache-read
share of the last request (from Claude Code's `context_window.current_usage`, when present):

```text
lcc: -40.6k tokens (2 passes) · 23 stashed · cache read 92%
```

`lcc: no pass this session` before the first applied pass; `lcc: ledger off` when there is no
ledger file. Generated from the fixture ledger in `test/fixtures/ledger.jsonl`
(`node test/statusline.test.mjs`).

## Idle stash (opt-in)

Off by default. With `idleStash: true`, when a session is **resumed** after `idleTtlSeconds`
of idle, the plugin stashes spent tool outputs (`provider: rules`, `rulesMode: stashed`)
before the first request, so that request re-writes a smaller prefix on a prompt cache that
has already expired. Removed outputs become `[removed: N tokens · lcc recall <id>]`; allow
`mcp__plugin_lcc_lcc__recall` so the agent can get them back.

### Why (INFERIDO)

An owner-only study of 767 of the maintainer's Claude Code sessions (usage metadata only,
private receipts) found:

- 95% of main-session cache writes use the 1-hour TTL. After a gap longer than an hour, 97% of
  returns found the cache cold and re-wrote a median 278k-token prefix; those re-writes were
  15.9% of total main-session cost (MEDIDO on that data).
- Simulated, stashing at that moment saved about 9% of total cost (9.3%; with a 10k-token
  minimum, 8.7% and 99% of affected sessions cheaper). The pass pays no extra invalidation
  because the prefix is re-written anyway (INFERIDO: a model, not a measured bill).
- Assuming a 5-minute TTL instead **lost** 10.7%: most of those triggers hit a warm cache.
- Harm: each pass is expected to stash about 4 outputs the agent uses later. They are
  recoverable with `recall`, which is why this is opt-in and not a default.

One user, one machine, subscription traffic; the prices are relative multipliers. The study
simulated a trigger on *every* idle return; this plugin can only act on a resumed session (see
below), so it covers a subset of those returns. Measure your own `recall` calls per pass and
the next request's cache read vs write before relying on it.

### How it runs

| Moment | What happens |
| :--- | :--- |
| each main-loop `turn.complete` | stores the time in the plugin's own store (`$.store`, keyed by session id, newest 64 sessions kept) |
| `session.start` of a resumed session | if the gap is past `idleTtlSeconds`, under `idleMaxPassesPerSession`, with at least `idleMinRemovableTokens` of tool output outside the pinned messages (chars/4), it runs the stash through `compact_transcript`, then calls `$.session.compact({ instructions: "lcc:idle" })`; the plugin's `session.compact` hook hands in the prepared pass |

Guards:

- **Never the built-in summary.** Every failure answers `{ skip }`. If Claude Code compacts
  without asking the plugin's hook (it does when the call comes from the plugin's own code
  outside a hook, see below), the plugin's classic `PreCompact` hook sees
  `custom_instructions: "lcc:idle"` and blocks it. On a cold 300k-token cache the built-in
  summary is the most expensive outcome there is.
- Never on subagents, and never twice over the same history: a second pass needs a new turn.
- The pass asks `compact_transcript` for `ref_unchanged` and `ref_blocks`, like `/compact`
  (see [the MCP result cap](#the-mcp-result-cap)): a 12-message session with four 10 KB reads
  already crossed the cap.
- It sends the session directory as `workspace_root`, so `stashed` can take file reads the
  disk still holds. Reads under a system temp directory are never stashed (a `rules` rule).
- **Cache edges** ([invariants](CACHE_ALIGNMENT.md#invariants-and-tests)): a gap exactly at
  `idleTtlSeconds` counts as cold; a negative gap (clock skew) or a missing timestamp never
  does. The pass sends `cache_state: "cold"` (`unknown` for a manual `/compact lcc:idle`), and
  the report's `cache_effect` prices it. Existing `[removed: … · lcc recall <id>]` placeholders
  are never stashed again, so a second idle stash over stashed history removes nothing new
  from them and keeps their bytes. UI calls are best effort: a headless engine without toasts
  never makes a hook throw.

Toasts: `lcc: idle stash (removed N tokens, S output(s) stashed, idle 2h-8h; recall brings any
back)` or `lcc: idle stash skipped (reason)`. With `LCC_REQUEST_LOG=1` the MCP server's request
log gets `trigger: "idle"`, `gap_bucket` and `removed_tokens` on each idle pass.

### Where it cannot run (Claude Code 2.1.296, observed)

| Trigger tried | What Claude Code did |
| :--- | :--- |
| `prompt.submit` hook (the returning prompt) | refused: "it would compact under the turn this hook is holding; call it from a later event" |
| headless session (`claude -p`, SDK) | refused: "not available in a headless (-p / SDK) session yet" |
| `$.clock.after` timer armed at `turn.complete` (session left open) | the call is the plugin's own code, so Claude Code skipped **all** of the plugin's hooks ("re-entry ... origin lcc"), including the `.catch` handler, and ran its own summary. The `PreCompact` backstop now blocks that. |
| `session.start` hook of a resumed session | works: the plugin's `session.compact` hook ran nested, "a hook's 26 messages stand ... core never ran" |

So a session left **open** while you are away gets no idle stash; one you close and resume
(`claude --continue` / `--resume`) does. If a later Claude Code runs a plugin's own hook for a
compaction the plugin raised from a timer, the timer path can come back.

### The TTL caveat

Everything depends on the cache really being cold when the pass runs. A pass on a warm cache
throws away a cached prefix and costs money.

- **Claude Code's cache keepalive.** Claude Code 2.1.296 touches the prompt cache about every
  30 s after a turn (`[cache-keepalive] touch ok` in `--debug`, MEDIDO in the runs below). Its
  defaults, read from the binary (INFERIDO): `touchIntervalSeconds` 30,
  `activityWindowMinutes` 60. With a 1-hour TTL the cache of a session that stayed open is
  cold only about **two hours** after its last turn, which is why `idleTtlSeconds` defaults
  to 7200 rather than 3600. The plugin measures the gap from the last turn, not from when you
  closed the session, so 7200 stays on the safe side whenever the session was closed within
  the 60-minute keepalive window.
- Use 3600 only if your debug log shows no keepalive touches; never 300 unless your sessions
  really write 5-minute caches.

### Disk check fix that came with it

`recoverable` and `stashed` verify a file read against the disk before replacing it. Claude
Code 2.1.296's Read numbers the empty line after a file's final newline (`480\t` for a 479-line
file), so every whole-file read of a newline-terminated file failed that check and was never
stashed. That empty trailing row is now ignored (a non-empty one still fails).

### Idle stash: disposable session (Claude Code 2.1.296, 2026-10-19)

Throwaway project (four 8.5 KB Python files read with the Read tool), plugin from this branch
via `--plugin-dir`, the installed `lcc@lcc` disabled for the run through `--settings`,
`idleTtlSeconds: 60` and `idleMinRemovableTokens: 1000` for the run only, model Haiku,
subscription login, interactive sessions driven through a pty. Counts from `--debug` logs and
the session JSONL; n=1 per path, a smoke test.

| Run | Path | Result | Fix it led to |
| :--- | :--- | :--- | :--- |
| 1 | `prompt.submit` | refused by Claude Code (above); the prompt went through | moved off `prompt.submit` |
| 2 | `-p --resume` | `session.start` decided to fire; `$.session.compact` refused in headless | documented: interactive only |
| 3 | timer, interactive | plugin hooks skipped (re-entry); **Claude Code's own summary ran** (manual boundary, 83,137 tokens, 9.9 s) | pass computed before the call; `.catch` to hand it in on re-entry |
| 4 | timer | the 49 KB `compact_transcript` answer was replaced by an error text (MCP size cap) | `ref_unchanged` |
| 5 | timer, proof folder moved out of the temp dir (temp reads are never stashed) | 0 outputs stashed: the prompt named the files, so the rules kept them (`named_in_goal_or_recent_turns`) | proof prompt reworded |
| 6 | timer | 0 outputs stashed: every whole-file read failed the disk check | disk-check fix (below) |
| 7 | timer | 2 outputs prepared (5,446 tokens), but the hooks were skipped again and Claude Code's summary ran; the plugin's toast wrongly said the stash stood | outcome check: a pass counts only if the plugin's hook handed it in |
| 8 | timer, with backstop | plugin hooks skipped again; `Compaction blocked by PreCompact hook ...`, "core never ran", toast `idle stash skipped`; no summarizer request | timer path dropped |
| 9 | resume (`claude --resume`, interactive, 61 s idle) | `idle stash starting (resume)`, own MCP server connected in 426 ms, pass 218 ms, "a hook's 26 messages stand ... core never ran"; toast `lcc: idle stash (removed 10892 tokens, 4 output(s) stashed ...)`; the JSONL holds four `[removed: ~2734 tokens · lcc recall <id>]` results | `$.mcp.connect` at `session.start` (the first resume found the server not yet connected) |

After run 9 the agent called `recall` and got the exact bytes back (sha256 included), though it
first picked the wrong id. The first request after the stash read 31,306 and wrote 32,714
cache tokens: in this proof the cache was still warm (60 s idle, keepalive on), so the stash
re-wrote a warm prefix, which is exactly the cost a real `idleTtlSeconds` avoids.

Not verified: the saving on a real bill, the `recall` rate in real use, a real >2 h gap, and
Claude Code builds other than 2.1.296.

## Without the early-access flag or a key: pinned facts in the built-in summary

Two classic hooks ship in the same `hooks/hooks.json` and run on any Claude Code with plugin
hooks, with no `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS`, no judge key and no network:

| Hook | What it adds |
| :--- | :--- |
| `PreCompact` | stdout becomes extra instructions for the built-in summary: the session objective (the two newest user prompts), the files edited and read, and the last tool error, with the order to copy file paths, identifiers and error text verbatim |
| `SessionStart`, matcher `compact` | the same facts, injected into the fresh context after the summary |

Both read the facts from the hook's `transcript_path` (the session JSONL, which compaction
appends to and does not rewrite), so they agree and nothing is stored between them. Lists are
capped at 20 files and the error at 400 characters. Anything unreadable prints nothing and exits
0, so compaction runs exactly as before. Covered by `node test/hook-pin.test.mjs`.

## Fallback: the built-in summary runs whenever anything is off

No key, a degraded pass, a conversation that cannot fit the state budget, a pass below
`minReductionRatio`, content the hook cannot rebuild (image or attachment blocks), or any MCP
failure — each of those calls `next(event)`, so Claude Code compacts exactly as it did before.
The plugin never requests a compaction of its own unless the opt-in idle stash is on; otherwise
it only decides what a compaction produces. Every outcome is one log line plus one toast, e.g.:

```
lcc: verbatim compaction, no summary (kept 18 messages, dropped 7 tool call(s), trimmed 2)
lcc: built-in summary (below the 25% minimum (4.2%))
lcc: built-in summary (judge unavailable (jev_unavailable_fail_safe))
```

## The MCP result cap

Claude Code caps an MCP tool result at `MAX_MCP_OUTPUT_TOKENS`: 25,000 tokens by default on
2.1.296 (the binary's default; a server-side flag can change it, the environment variable wins).
A larger result is not truncated JSON: the plugin's `$.mcp.call` gets a pointer text to a saved
file. Through 1.1.0 the hook asked for the whole compacted conversation, so on any session long
enough to be worth compacting the answer was over the cap, the hook could not parse it and
Claude Code's own summary ran.

The hook now asks for `ref_unchanged: true, ref_blocks: true`. The server answers with refs into
the transcript the hook sent: `{ "ref": i }` for an unchanged message, and for a changed one the
indices of the kept tool calls and results plus, for each replaced result, only its new text
between the original's first `head` and last `tail` characters (UTF-16 units). Placeholders and
trim notes travel; file contents do not. The hook rebuilds the messages from the session's own
copy and throws on any ref that does not fit, which falls back to the built-in summary. An
answer that is still over the cap toasts `lcc: built-in summary (tool result is not JSON (N
chars; over Claude Code's MCP output cap?))`.

Evidence. In the owner's session logs from 2026-10-07 to 2026-10-19 (plugin installed, function
hooks on, `provider: rules`, `rulesMode: stashed`), every `/compact` of a real session (209k to
860k tokens, 27 boundaries) wrote Claude Code's summary (50 to 115 s each); the plugin's
verbatim pass stood only on disposable test sessions of about 58k to 84k tokens. Those logs hold
no toasts, so the cap is the likely cause, not a measured one (INFERIDO). A disposable session
then reproduced it (Claude Code 2.1.296, Haiku, subscription login, plugin from `--plugin-dir`,
the installed `lcc@lcc` off for the run, same options; twelve 30 KB files read, then `/compact`;
n=1 per row):

| Hook | `compact_transcript` answer | Outcome |
| :--- | :--- | :--- |
| before (whole messages) | 157.8 KB, saved to a file by Claude Code; the hook got a 1,365-char text | `lcc: built-in summary (JSON Parse error: Unexpected identifier "Error")`, summary ran |
| after (`ref_blocks`), twice | 3,002 / 3,003 chars | `lcc: verbatim compaction via rules, no summary (kept 26 messages, ... replaced 8)`; "a hook's 26 messages stand ... core never ran" |

After the fix the agent quoted a placeholder (`[removed: 8354 tokens · lcc recall <id>]`),
called `recall` and named the first function of the recalled file correctly.

## What is verified, and what is not

Verified: `claude plugin validate plugins/claude-code` passes and reports the registered
surface (`session.compact`; calls `$.mcp.call`, `$.ui.log`, `$.ui.toast`); the plugin installs
from this repository's marketplace with the documented commands (`claude plugin marketplace add
<repo>` → "Successfully added marketplace: lcc", `claude plugin install lcc@lcc` → installed at
user scope with its eight `userConfig` options reported), and `claude plugin details lcc` lists
the plugin's MCP server. The hook's mapping logic — option coercion, transcript mapping,
tool-result parsing, the replacement decision and the fallback on unsupported content — is
covered by `node test/hook-map.test.mjs` (19 cases, run by `npm test` and by CI); the Python side
is covered by `tests/test_transcript_compaction.py`, `tests/test_cli_tool_calls.py` and
`tests/test_mcp_server.py`.

> **`claude plugin details` counts only classic event hooks**, not the `session.compact`
> module (it reported "Hooks (0)" before the two fallback hooks existed). `claude plugin
> validate` parses the module and names the event it registers; the debug log shows
> `hooks module lcc@... loaded ... events: session.compact` at startup.

The compaction backend itself is now measured against the reference implementation on the same
transcripts: our mode removed **13.3 / 39.2 / 55.7%** of the transcript at fact recall
**1.00 / 1.00 / 1.00**, where `fast-jev-compaction` removed 70.5 / 78.9 / 83.4% at recall 0.00
— it dropped every evidence pair (`benchmarks/research/TRANSCRIPT_AB.md`, canonical row in
`RESEARCH_STATUS.md`). Read that study with its own limits: three synthetic sessions, one seed,
backends only, and one of four runs dropped an evidence pair on the largest session.

And it is measured on **real transcripts** (`benchmarks/research/REAL_SESSIONS.md`): a real
Claude Code session in this repository, in the exact shape the hook receives, went from 55 411
to 18 761 tokens (**−66.1%**) with all 42 user/assistant texts preserved byte for byte, and this
release's own 337-message Hermes session by 81.7% with all 58 texts preserved. That is **n=2**;
on 60 real Claude Code contexts Jev block mode cut 3.5%
([real-session benchmarks, section 3](REAL_SESSION_BENCHMARKS.md#3-against-jev-laya-and-mechanical)). That measurement
found and fixed a real defect: the state budget used a heuristic that undercounts JSON by about
a third, so large sessions built requests the API refused (`400 max_tokens_exceeded`) and
degraded to keep-everything after 38 wasted calls. It also exercised the 25% minimum-reduction
gate for real: one measured window landed below it and the hook would keep the built-in summary.

### Observed end to end (Claude Code 2.1.296, 2026-10-16)

The first real `/compact` runs through this plugin, from `claude -p` on a throwaway session
(one synthetic workspace: 4 file reads of about 6.5K characters each, 2 Bash calls, 1 Edit,
1 Grep). Counts only; one session shape, so read them as a smoke test, not a benchmark.

What the shipped hook did on the first run, and what was fixed:

| Run | Observed | Fix in this branch |
| :--- | :--- | :--- |
| 1 | `session.compact` fired (trigger `manual`, 16 messages, keys `role`, `text`, `toolUses`, `toolResults`, `handle`) and the hook threw `ReferenceError: process is not defined`: hook modules run in a worker with no `process`, and the event carries no `cwd`. The engine skipped the hook and its own summary ran. | `sessionCwd()` uses `globalThis.process?.cwd?.()`; no `workspace_root` is sent when there is none |
| 2 | `$.mcp.call` found no server named `lcc`: Claude Code names the plugin's server `plugin:lcc:lcc` | default `server` is `plugin:lcc:lcc` (manifest and `map.mjs`) |
| 3 | the call was refused until `mcp__plugin_lcc_lcc__compact_transcript` was allowed (`$.mcp.call` goes through tool permissions; headless `-p` cannot prompt) | documented below; allow it once |
| 4 | replacement accepted (receipt below), but a failed tool result came back as a success: the engine rebuilds `is_error` from `isError`, the payload said `is_error` | `toSessionMessages` emits `isError`; after the fix the run kept 1 of 1 error flags |

The receipt of the first accepted replacement (default provider `jev`; `lcc` found its key in
its own key store): judged by `jev-1.13.0`, 1 call, 329 ms, not degraded; 7 tool calls → 1 kept,
2 trimmed, 3 dropped; 29,039 → 2,845 characters (−90.2%); 20 messages in, 11 out. Claude Code
logged `a hook's 11 messages stand ... core never ran`, and the `compact_boundary` recorded
58,429 → 2,324 tokens in 482 ms, against 15–17 s for the built-in summary on the same session
shape. Two runs of the plugin directory from this branch kept 12 and 10 messages.

**Claude Code's post-compact re-attachments do not happen when the hook replaces messages.**
After the boundary, the hook path had 0 re-read files and 0 tool/agent/MCP/environment/model
deltas; only the 3 `SessionStart` hook outputs. The built-in path on the same session had 4
re-read files, 5 deltas (deferred tools, agent listing, MCP instructions, environment, model)
and the hook outputs. `PreCompact` does not run on the hook path (0 invocations) and does run on
the built-in path. Kept messages are verbatim, so a kept file read is still in context; a
dropped or trimmed one is not re-attached, and `lcc`'s `SessionStart` re-pin lists its path.

Two more observations: the hook module loaded with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS` unset
and with it set to `0` on this 2.1.296 install, so the variable was not the gate here (it may
be on other accounts or builds). And the classic fallback changed the built-in summary: with
the `PreCompact` pin it carried 4 of the 4 absolute file paths, without the plugin 0 of 4
(n=1 each; both kept the edited function name and the error text).

To repeat it:

```bash
cd <a throwaway repo> && CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir <lcc>/plugins/claude-code \
  --allowedTools mcp__plugin_lcc_lcc__compact_transcript --debug-file /tmp/lcc-compact.log
# after a few tool calls:  /compact
grep -E "\[lcc\]|session\.compact \(" /tmp/lcc-compact.log
```

Note that Claude Code is a *consumer*, not a requirement: the same pass runs from the CLI
(`lcc compact transcript.json --mode tool-calls`) and from any MCP client through `lcc mcp`
(`compact_transcript`), with no editor involved.

## Early-access caveat

Function hooks (`hooks/hooks.json` modules, the `session.compact` event, the `$` engine
surface) are early access: they require `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` and a Claude
Code release that carries the surface (2.1.274+). The API can change between releases; this
plugin is written against the declarations Claude Code 2.1.274 generated, and
`claude plugin validate` is the check to re-run after an upgrade.
