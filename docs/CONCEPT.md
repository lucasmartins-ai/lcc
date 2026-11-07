# What lcc is

> lcc removes old tool output from a coding agent's context. In `stashed` mode, every byte it
> removes is one `recall` away, checked by hash. Every pass lists what it removed, and why, in
> a receipt.

That is the product. Everything in the left column below serves it. The right
column is research: it is kept in the repository and documented, but no product claim rests
on it.

## Rules every product path keeps

- **Local and offline by default.** Only two things go online: `lcc fetch-tokenizer`, run once,
  and a provider you name that needs the network. There is no telemetry. `lcc share-stats`
  prints a summary, and sending it is up to you.
- **User text is never rewritten in tool-call mode** (the plugin, `compact_transcript`,
  `--mode tool-calls`): every user and assistant message stays byte for byte. Block mode
  `compact` can drop any block, messages included, and lists each one in the receipt.
- **What happens to a removed tool output depends on the mode.** `lossless` points to an identical
  output still in context. `recoverable` points to an unchanged file to re-read. `stashed`
  stores it, and `recall` returns it exactly after checking its hash. An output that the
  ranker (`auto`) or block mode drops is not stored: the receipt lists it, but it cannot be
  recalled.
- **A receipt is not a proof of relevance.** It records what was removed and checks
  integrity. Whether the agent still needed the removed output is a question for the answer
  and agent evals; the ranker and the mechanical passes report `semantic_guarantee: none`.
- **Every number has a source.** Each published figure comes from a result file in this
  repository, or is marked as coming from the maintainer's private sessions, where only
  aggregates are published. `scripts/check_claims.py` checks the main benchmark tables
  against their result files, and CI runs it through `tests/test_check_claims.py`.

## Glossary

| term | meaning |
| :--- | :--- |
| **context** | everything sent to the model on one request: system prompt, tool schemas, injected instructions, the transcript |
| **`lossless`** | a removed tool output is replaced by a pointer to an identical output still in context. Nothing leaves the context. |
| **`recoverable`** | `lossless`, plus old file reads replaced by a "re-read" pointer when the file is unchanged |
| **`stashed`** | an old tool output moves to the local stash and is replaced by `[removed: … · lcc recall <id>]` |
| **stash** | the local, content-addressed store of removed outputs (`~/.cache/lcc/stash`, `0700`/`0600`, `LCC_STASH_DIR`) |
| **`recall`** | the CLI command and MCP tool that returns a stashed output by id, byte for byte; `--file` also says whether a recalled file read still matches the file |
| **receipt** | what a pass reports: what was removed, why, by which rule, token counts, hashes and the cache effect. The JSON report, and in Claude Code the ledger and statusline ([guide](CLAUDE_CODE.md#receipt-ledger-and-statusline)) |
| **handoff** | `lcc handoff`: a verbatim packet of what the next agent needs, from any agent tool's session ([HANDOFF.md](HANDOFF.md)) |
| **`lossy`** | experimental. It failed two blind audits ([REAL_SESSION_BENCHMARKS.md](REAL_SESSION_BENCHMARKS.md)), and it is not part of the product. |
| **MSI** | Minimum Sufficient Inference, a research protocol frozen as a research release by [ADR 0022](adr/0022-research-release-freeze.md). Not the product. |

## Product and research

| product (supported, measured on real sessions) | research (frozen or experimental, no product claims) |
| :--- | :--- |
| `rules` provider (`lossless`, `recoverable`, `stashed`), and `auto`, the local specialist-v3 ranker that the plugin and `compact_transcript` use by default | MSI specs and engines ([ADR 0022](adr/0022-research-release-freeze.md)) |
| `recall` (CLI and MCP), the stash, `verify_stashed` | causal necessity labels ([ADR 0021](adr/0021-causal-necessity-labels.md)) |
| `measure-session`, `share-stats`, `handoff` | `lossy`, the Jev and Laya providers |
| Claude Code plugin (compaction hook, statusline), MCP server | semantic retrieval scaffold ([ADR 0011](adr/0011-phase-2-opt-in-semantic-retrieval-boundary.md), [ADR 0012](adr/0012-semantic-retrieval-execution-boundary.md)) |
| block mode `compact` with its cache contract ([ADR 0015](adr/0015-minimum-sufficient-context-cost.md)) | the `prepare`/`optimize` cleaning pipeline: it works, but it is not the story |

Other agent tools (Codex, Gemini CLI, Aider, OpenCode, Cline, Cursor) get the product through
the CLI and the MCP server. [Compacting earlier](COMPACT_EARLIER.md) covers their compaction
settings.
