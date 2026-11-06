# Compacting earlier, in every agent tool

A long session costs more per request and answers worse as the window fills. lcc's suggested
rule is the same for every tool: **see the fill, consider compacting at 30 %, have the tool
compact on its own at 40 %**. Claude Code, Codex CLI, Gemini CLI and Aider document a
setting for the automatic part, and Cline sets it from its progress bar. OpenCode and Cursor
document none, so there the 30–40 % compaction is a manual `/compact`, or not available. lcc
does not change these settings for you.

Compacting earlier has a price. On a warm prompt cache, the first request after a compaction
writes the new prefix at the cache-write price, and in every tool below except Claude Code with
the lcc plugin, the compaction is the tool's own summary, which loses text. Whether 30/40 saves
money on your sessions has not been measured yet.

| tool | see the fill | compact on its own earlier | value for about 40 % |
| --- | --- | --- | --- |
| **Claude Code** | lcc statusline: `ctx 41% of 200k · /compact suggested` ([setup](CLAUDE_CODE.md#receipt-ledger-and-statusline)) | `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` in the `env` of `~/.claude/settings.json`: percent (1–100) of the auto-compact window, can only lower the default | `"40"`. With the lcc plugin, that compaction is verbatim when the pass clears `minReductionRatio` |
| **Codex CLI** | `context-remaining` item of the TUI `status_line` | `model_auto_compact_token_limit` in `config.toml`: a token count, "token usage threshold triggering auto-compaction" | 0.4 × your model's context window, in tokens. The default is not documented |
| **Gemini CLI** | footer percentage, hidden by default: set `ui.footer.hideContextPercentage` to `false` | `model.compressionThreshold` in `settings.json`: a fraction of context (default `0.5`; restart needed) | `0.4` |
| **Aider** | `/tokens` | `--max-chat-history-tokens` (or `AIDER_MAX_CHAT_HISTORY_TOKENS`): a soft token limit on chat history, after which summarization begins | 0.4 × the window minus your files and repo map, in tokens. It counts chat history only |
| **OpenCode** | not documented | no percentage setting. `compaction.auto` (default `true`) compacts when the context is full. `compaction.reserved` is a token buffer, and whether a bigger buffer compacts earlier is not documented | none: run `/compact` (alias `/summarize`) at 30–40 % |
| **Cline** | context-window progress bar in the task header | auto-condense (`useAutoCondense`, on by default). The CHANGELOG says the progress bar sets its threshold. The setting's key and range are not documented | set it on the bar |
| **Cursor** | not documented | not documented | none |

What lcc adds in each tool today:

- **Claude Code**: the plugin replaces the built-in summary with verbatim compaction, keeping
  removed outputs one `recall` away ([guide](CLAUDE_CODE.md)).
- **Every MCP client** (Cursor, Codex, Claude Desktop, any stdio client): `lcc mcp` serves
  `compact_transcript` and `recall` ([MCP guide](MCP.md)).
- **Codex CLI rollouts and Claude Code sessions**: `lcc measure-session` reports what each mode
  would remove, offline. **Aider**: its chat history is readable as lcc input ([guide](AIDER.md)).

## Sources

Read on 2026-11-06. These settings move between releases, so check your tool's version.

- Claude Code: `code.claude.com/docs/en/env-vars` (`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`) and
  `code.claude.com/docs/en/statusline` (`context_window.used_percentage`).
- Codex CLI: `openai/codex`, `codex-rs/core/config.schema.json` (`model_auto_compact_token_limit`,
  `status_line`) and `codex-rs/tui/src/bottom_pane/status_line_setup.rs` (`context-remaining`).
- Gemini CLI: `google-gemini/gemini-cli`, the configuration reference
  (`reference/configuration.md` in its docs folder: `model.compressionThreshold`,
  `ui.footer.hideContextPercentage`).
- Aider: `Aider-AI/aider`, the website pages `config/options.md` and `usage/commands.md`.
- OpenCode: `sst/opencode`, `packages/web/src/content/docs/config.mdx` (`compaction`) and
  `tui.mdx` (`/compact`).
- Cline: `cline/cline`, `apps/vscode/src/shared/storage/state-keys.ts` (`useAutoCondense`) and
  `CHANGELOG.md` (progress-bar threshold).
- Cursor: `cursor.com/docs`, where no threshold or usage display was found.
