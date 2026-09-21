# Claude Code plugin (`lcc` on the Claude Code marketplace)

`lcc` ships a Claude Code plugin that replaces the built-in compaction **summary** with
verbatim compaction: the session transcript goes to the plugin's own `lcc mcp` server, Jev
says which tool calls and results are spent, and those pairs are dropped. Kept messages carry
their original bytes; user and assistant text is never scored, trimmed or rewritten. The
decision logic, the report schema and the fallback rules are the ones documented in
[`docs/TOOL_CALLS.md`](TOOL_CALLS.md) for `lcc compact --mode tool-calls`.

## Install

```bash
export CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1   # required while function hooks are early access
export TYPESAFE_API_KEY=...                  # or ~/.config/lcc/typesafe.key, or the macOS keychain

pip install "local-context-compiler[tiktoken]"   # the `lcc` CLI and its MCP server

claude plugin marketplace add lucasmartins-ai/lcc
claude plugin install lcc@lcc
```

Requirements: Claude Code **2.1.274 or newer**, `lcc` on `PATH`, and a TypeSafe API key.
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
| `plugins/claude-code/hooks/hooks.json` | registers the hook module |
| `plugins/claude-code/hooks/lcc-compact.mjs` | the adapter: `session.compact` → `compact_transcript` → messages |
| `plugins/claude-code/hooks/map.mjs` | the pure mapping helpers, unit-tested on their own |
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
| `server` (`lcc`) | MCP server name to call |

## Fallback: the built-in summary runs whenever anything is off

No key, a degraded pass, a conversation that cannot fit the state budget, a pass below
`minReductionRatio`, content the hook cannot rebuild (image or attachment blocks), or any MCP
failure — each of those calls `next(event)`, so Claude Code compacts exactly as it did before.
The plugin also never requests a compaction of its own; it only decides what a compaction
produces. Every outcome is one log line plus one toast, e.g.:

```
lcc: verbatim compaction, no summary (kept 18 messages, dropped 7 tool call(s), trimmed 2)
lcc: built-in summary (below the 25% minimum (4.2%))
lcc: built-in summary (judge unavailable (jev_unavailable_fail_safe))
```

## What is verified, and what is not

Verified: `claude plugin validate plugins/claude-code` passes and reports the registered
surface (`session.compact`; calls `$.mcp.call`, `$.ui.log`, `$.ui.toast`); the plugin installs
from this repository's marketplace with the documented commands (`claude plugin marketplace add
<repo>` → "Successfully added marketplace: lcc", `claude plugin install lcc@lcc` → installed at
user scope with its eight `userConfig` options reported), and `claude plugin details lcc` lists
the plugin's MCP server. The hook's mapping logic — option coercion, transcript mapping,
tool-result parsing, the replacement decision and the fallback on unsupported content — is
covered by `node test/hook-map.test.mjs` (10 cases, run by `npm test` and by CI); the Python side
is covered by `tests/test_transcript_compaction.py`, `tests/test_cli_tool_calls.py` and
`tests/test_mcp_server.py`.

> **`claude plugin details` reports "Hooks (0)" for this plugin, and that is the inventory
> counter, not the truth.** Function-hook modules (`hooks/hooks.json` with `"modules"`) are the
> early-access surface: `claude plugin validate` parses the module and names the event it
> registers, while the component inventory counts only classic event hooks. Do not read
> "Hooks (0)" as a missing hook.

The compaction backend itself is now measured against the reference implementation on the same
transcripts: our mode removed **13.3 / 39.2 / 55.7%** of the transcript at fact recall
**1.00 / 1.00 / 1.00**, where `fast-jev-compaction` removed 70.5 / 78.9 / 83.4% at recall 0.00
— it dropped every evidence pair (`benchmarks/research/TRANSCRIPT_AB.md`, canonical row in
`RESEARCH_STATUS.md`). Read that study with its own limits: three synthetic sessions, one seed,
backends only, and one of four runs dropped an evidence pair on the largest session.

And it is measured on **real transcripts** (`benchmarks/research/REAL_SESSIONS.md`): a real
Claude Code session in this repository, in the exact shape the hook receives, went from 55 411
to 18 761 tokens (**−66.1%**) with all 42 user/assistant texts preserved byte for byte, and this
release's own 337-message Hermes session by 81.7% with all 58 texts preserved. That measurement
found and fixed a real defect: the state budget used a heuristic that undercounts JSON by about
a third, so large sessions built requests the API refused (`400 max_tokens_exceeded`) and
degraded to keep-everything after 38 wasted calls. It also exercised the 25% minimum-reduction
gate for real: one measured window landed below it and the hook would keep the built-in summary.

Not verified: Claude Code's own `/compact` has never been intercepted end to end. The hook's
plumbing (`session.compact` → `$.mcp.call` → messages back) is validated and unit-tested, but not
yet fired by the editor: **the author does not have a Claude Code subscription**, so this
repository cannot run that last step. The two-minute check for anyone who does — Claude Code
2.1.274 or newer, and a TypeSafe key:

```bash
cd <this repo> && CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir plugins/claude-code
# in a long session:  /compact
# expect the toast: "lcc: verbatim compaction, no summary (kept N messages, dropped D tool call(s), trimmed T)"
# or, when the pass lands below the minimum: "lcc: built-in summary (below the 25% minimum (x%))"
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
