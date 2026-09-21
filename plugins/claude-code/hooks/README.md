# lcc — Claude Code plugin

Replaces Claude Code's compaction summary with **verbatim** compaction: every tool call is
paired with its result, TypeSafe Jev is asked whether the call and its output are still
needed, and the pairs it says are spent are dropped. Nothing is summarized, nothing is
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
(the plugin's `.mcp.json` starts `lcc mcp`), and a TypeSafe API key.

For local development against a checkout:

```bash
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir plugins/claude-code
```

## What runs, and when

The plugin registers one hook:

| Event | What it does |
| :--- | :--- |
| `session.compact` | Sends the transcript to `compact_transcript`, replaces the conversation with the compacted one when the pass was judged and removed something, otherwise calls `next(event)` so Claude Code's own summary runs |

Every outcome is reported in one toast and one log line, and each per-call decision is in
the report the tool returns:

- `lcc: verbatim compaction, no summary (kept N messages, dropped D tool call(s), trimmed T)`
- `lcc: built-in summary (below the 25% minimum (4.2%))`
- `lcc: built-in summary (judge unavailable (jev_unavailable_fail_safe))`

There is **no forced compaction**: the plugin never requests a compaction of its own, it only
decides what a compaction produces. Configure `minReductionRatio`, `preserveRecentMessages`,
`threshold`, `trimHeadChars`, `maxStateTokens`, `maxRequestTokens` and `question` through the
plugin's config (`/plugin` → lcc, or `claude plugin install --config key=value`).

## Fallback is the default when anything is off

The hook stands down — and Claude Code compacts the way it always did — when:

- there is no key, the network is disabled, or every batch fails (`degraded: true`);
- the conversation cannot be shown to the judge inside `--max-state-tokens`;
- the pass removed less than `minReductionRatio` of the transcript;
- a message carries content this hook cannot rebuild from `role`, `text` and tool blocks
  (an image or attachment block), because the engine rebuilds a handle-less message from
  exactly those fields;
- the MCP call fails for any reason.

It also skips `precompute` invocations, which install nothing.

## Limitations, stated plainly

- **Early access surface.** Function hooks (`hooks/hooks.json` modules, `session.compact`)
  require `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` and Claude Code 2.1.274+; the API may change
  between releases. The hook is written in plain ESM (`.mjs`), no build step, no dependencies.
- **Out-of-process by design.** The decision logic is Python (`lcc`), reached over MCP, so the
  hook returns rebuilt messages rather than the engine's own objects. Claude Code rebuilds
  each returned message from `role`, `text` and tool blocks — which is why the hook refuses
  sessions carrying content it cannot rebuild.
- **Needs a judge.** No key means no compaction: the plugin does not have, and does not fake,
  an offline semantic path for tool-call relevance.
- **Tool granularity.** A pair is kept, trimmed to its head, or dropped whole; a half-spent
  40K-char result is not half-summarized.

## Test it

```bash
node test/hook-map.test.mjs        # the mapping helpers, no engine needed
claude plugin validate plugins/claude-code
```
