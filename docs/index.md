---
title: lcc — Local Context Compiler
description: Shrink LLM prompt context and Claude Code sessions without rewriting a byte. Offline, MIT, with an audit report for every block kept or dropped.
---

# lcc — Local Context Compiler

**Shrink what you send to the model. Keep every byte you didn't cut. Get a receipt.**

`lcc` cleans duplicates and boilerplate, selects context for an explicit objective and writes a
JSON report of what was kept, trimmed or dropped, and why. Selected spans stay verbatim, the
default path runs offline with no API key, and the code is MIT-licensed.

![lcc compact dropping noise from a 23-block dossier, then lcc explain showing why each block went](https://raw.githubusercontent.com/lucasmartins-ai/lcc/main/demos/compact.gif)

| Measured on | Before → after | What was kept |
| --- | --- | --- |
| A real Claude Code session (192 messages) | 55,411 → 18,761 tokens (**−66.1%**) | all 42 user/assistant texts, byte for byte |
| A real 337-message agent session | 199,717 → 36,645 tokens (**−81.7%**) | all 58 user/assistant texts, byte for byte |
| The demo dossier, offline `mechanical` provider | 642 → 393 tokens (**−39.6%**) | 13 of 23 blocks, with a reason for every drop |

Session rows: tool-call mode with the Jev judge. Sources and limits:
[real-session measurements](https://github.com/lucasmartins-ai/lcc/blob/main/benchmarks/research/REAL_SESSIONS.md).

## Install

```sh
pip install "local-context-compiler[tiktoken]"
lcc compact notes.md -q "what is wrong with the booking flow?" --provider mechanical -o compacted.md -r report.json
lcc explain report.json --source notes.md
```

MCP (Claude Code, Cursor, Claude Desktop):

```json
{"mcpServers": {"lcc": {"command": "lcc", "args": ["mcp"]}}}
```

## Guides

- [Quickstart](QUICKSTART.md): every command, offline
- [Claude Code plugin](CLAUDE_CODE.md): verbatim `/compact` instead of a lossy summary
- [Tool-call mode](TOOL_CALLS.md): compacting agent transcripts
- [MCP server](MCP.md): the six tools
- [ChatGPT plugin](CHATGPT_PLUGIN.md) and [privacy policy](PRIVACY_POLICY.md)
- [Architecture](architecture.md) and [roadmap](roadmap.md)

Source, issues and releases: [github.com/lucasmartins-ai/lcc](https://github.com/lucasmartins-ai/lcc).
Maintained by [LookADev](https://lookadev.com).
