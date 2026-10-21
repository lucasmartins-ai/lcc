# lcc — Claude Code plugin

Replaces Claude Code's compaction summary with **verbatim** compaction: every tool call is
paired with its result, a judge (the local `specialist-v3` ranker by default, TypeSafe Jev on opt-in, deprecated
Laya on opt-in, or the offline `rules` policy) decides whether the call and its output are still needed, and the pairs it marks
spent are dropped or trimmed. Nothing is summarized, nothing is
rewritten — kept messages carry their original bytes, and user/assistant text is never
touched at all.

The decision logic and the judge live in the `lcc` Python package (
`lcc compact --mode tool-calls`); this plugin is a thin adapter that hands the session
transcript to the plugin's own `lcc mcp` server. Contract: [`docs/TOOL_CALLS.md`](../../../docs/TOOL_CALLS.md).

## Install

```bash
export CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1   # required while function hooks are early access
export TYPESAFE_API_KEY=...                  # or ~/.config/lcc/typesafe.key, or the macOS keychain

pip install "local-context-compiler[tiktoken]"   # provides the `lcc` CLI + MCP server

claude plugin marketplace add lucasmartins-ai/lcc
claude plugin install lcc@lcc
```

Requirements: Claude Code **2.1.274 or newer** (function hooks), the `lcc` CLI on `PATH`
(the plugin's `.mcp.json` starts `lcc mcp`), and a TypeSafe API key only for `provider: jev`
(`auto`/`specialist-v3`, `laya` and `rules` need none).

For local development against a checkout:

```bash
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir plugins/claude-code
```

## What runs, and when

The plugin registers one function hook and two classic hooks:

| Event | What it does |
| :--- | :--- |
| `session.compact` | Sends the transcript to `compact_transcript`, replaces the conversation with the compacted one when the pass was judged and removed something, otherwise calls `next(event)` so Claude Code's own summary runs |
| `PreCompact` (classic) | Prints the session objective, edited/read files and the last tool error, asking the built-in summary to keep them verbatim (`scripts/lcc-pin.mjs precompact`); blocks the summary for an idle-stash compaction |
| `SessionStart`, matcher `compact` (classic) | Re-pins the same facts after the summary (`scripts/lcc-pin.mjs sessionstart`) |
| `turn.complete`, `session.start` | Only with `idleStash: true` (off by default): record the last turn's time / run the idle stash on a session resumed after the cache expired (see "Idle stash" below) |

The two classic hooks need neither the function-hook flag nor a key: without the flag they are
the whole plugin, and the built-in summary keeps paths, identifiers and the last error verbatim.

Every outcome is reported in one toast and one log line, and each per-call decision is in
the report the tool returns:

- `lcc: verbatim compaction via PROVIDER, no summary (kept N messages, dropped D tool call(s), trimmed T, deduped P, replaced R)`
- `lcc: built-in summary (the pass removed no tool output)`
- `lcc: built-in summary (below the 25% minimum (4.2%))`
- `lcc: built-in summary (judge unavailable (jev_unavailable_fail_safe))`

There is **no forced compaction** by default: the plugin requests a compaction of its own only
with the opt-in idle stash below; otherwise it only decides what a compaction produces. Configure `minReductionRatio`, `preserveRecentMessages`,
`threshold`, `trimHeadChars`, `maxStateTokens`, `maxRequestTokens` and `question` through the
plugin's config (`/plugin` → lcc, or `claude plugin install --config key=value`).

`rulesMode` (with `provider: rules`) picks `lossless`, `recoverable`, `stashed` or `lossy`; empty
keeps the server default. With `stashed`, each removed tool output is written to the local stash
(`~/.cache/lcc/stash`, or `LCC_STASH_DIR`) and replaced by `[removed: N tokens · lcc recall <id>]`;
the agent gets the exact bytes back with the plugin's `recall` tool, so allow
`mcp__plugin_lcc_lcc__recall` as well. With `recoverable` the hook sends the session's working directory as
`workspace_root`, so every removed file read is checked against the file on disk. The
directory is the event's `cwd` field when it is an absolute path, else the hook process's
`process.cwd()` (function hooks run inside the session's process).

`provider` defaults to `auto`, which is the local `specialist-v3` ranker (offline, no key);
`specialist-v3` names it explicitly. Jev runs only with `provider: jev`, and Laya (deprecated)
only with `provider: laya`. Any ranker error keeps every call (`degraded: true`) and the hook
stands down. See [`docs/SPECIALIST.md`](../../../docs/SPECIALIST.md).

## Idle stash (opt-in)

`idleStash: true` adds one more trigger. When a session is **resumed** (`claude --continue` /
`--resume`) after `idleTtlSeconds` of idle (default 7200: the 1-hour cache TTL plus Claude
Code's 60-minute cache keepalive), the plugin stashes spent tool outputs (`provider: rules`,
`rulesMode: stashed`) at `session.start`, before the first request re-writes the cold prefix.
Removed outputs come back with `recall` (allow `mcp__plugin_lcc_lcc__recall`).

- Any failure answers `{ skip }`; the classic `PreCompact` hook blocks Claude Code's own summary
  for an idle compaction (`custom_instructions: "lcc:idle"`). Never the built-in summary.
- It stands down below `idleMinRemovableTokens` (10000), after `idleMaxPassesPerSession` (8)
  passes, on subagents, and when no turn has happened since the last pass.
- Toasts: `lcc: idle stash (removed N tokens, ...)` or `lcc: idle stash skipped (reason)`.
- Interactive and resumed sessions only. On Claude Code 2.1.296 `$.session.compact` is refused
  in `-p`/SDK sessions and from `prompt.submit`, and a timer's call skips the plugin's own
  hooks, so a session left open while you are away gets no pass.

Details, evidence and the disposable-session run: [`docs/CLAUDE_CODE.md`](../../../docs/CLAUDE_CODE.md#idle-stash-opt-in).

## Receipt, ledger and statusline

Every compaction the hook applies toasts the server's one-line receipt: tokens before and
after, what was removed, and how to recall it. `ledger: true` (off by default) has the server
append one line of counts per applied pass to `~/.cache/lcc/ledger.jsonl` (never text or
paths, never sent anywhere), and `scripts/statusline.mjs` shows it in the Claude Code
statusline:

```text
lcc: -40.6k tokens (2 passes) · 23 stashed · cache read 92%
```

Setup and the ledger format: [`docs/CLAUDE_CODE.md`](../../../docs/CLAUDE_CODE.md#receipt-ledger-and-statusline).

## Fallback is the default when anything is off

The hook stands down — and Claude Code compacts the way it always did — when:

- the judge or ranker is unavailable, or every batch fails (`degraded: true`);
- the conversation cannot be shown to the judge inside `--max-state-tokens`;
- the pass removed less than `minReductionRatio` of the transcript;
- a message carries content this hook cannot rebuild from `role`, `text` and tool blocks
  (an image or attachment block), because the engine rebuilds a handle-less message from
  exactly those fields;
- the MCP call fails for any reason.

It also skips `precompute` invocations, which install nothing.

## Limitations, stated plainly

- **Fired end to end on one session shape.** Claude Code 2.1.296 ran a real `/compact` through
  this hook; it needed three fixes first (no `process` in the hook worker, the server name
  `plugin:lcc:lcc`, `isError` on rebuilt results). Counts are in
  [`docs/CLAUDE_CODE.md`](../../../docs/CLAUDE_CODE.md#observed-end-to-end-claude-code-21296-2026-10-16).
- **No native re-attachments after a replacement.** When the hook's messages stand, Claude Code
  does not re-read recent files or re-announce tools, MCP instructions or the environment, and
  `PreCompact` does not run. Only `SessionStart` hooks (including `lcc`'s re-pin) run.
- **Permission.** `$.mcp.call` is permission-checked: allow
  `mcp__plugin_lcc_lcc__compact_transcript`, or every compaction falls back to the summary.
- **Early access surface.** Function hooks (`hooks/hooks.json` modules, `session.compact`)
  require `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` and Claude Code 2.1.274+; the API may change
  between releases. The hook is written in plain ESM (`.mjs`), no build step, no dependencies.
- **Out-of-process by design.** The decision logic is Python (`lcc`), reached over MCP, so the
  hook returns rebuilt messages rather than the engine's own objects. Claude Code rebuilds
  each returned message from `role`, `text` and tool blocks — which is why the hook refuses
  sessions carrying content it cannot rebuild.
- **The default provider needs a key.** With `provider: jev` and no key there is no
  compaction. `provider: rules` runs offline with no model; it removes far less on real
  sessions (see `docs/REAL_SESSION_BENCHMARKS.md`), so lower `minReductionRatio` to use it.
- **Tool granularity.** A pair is kept, trimmed to its head, or dropped whole; a half-spent
  40K-char result is not half-summarized.

## Test it

```bash
node test/hook-map.test.mjs        # the mapping helpers, no engine needed
node test/hook-idle.test.mjs       # the idle stash, against a fake engine
node test/hook-pin.test.mjs        # the PreCompact / SessionStart fallback
node test/statusline.test.mjs      # the statusline on a fixture ledger
claude plugin validate plugins/claude-code
```
