# Workers that recall instead of re-reading

An orchestrating agent that starts a worker (`claude -p`, `codex exec`, a script) has two bad
options for passing context. Pasting the big outputs fills the worker's context, and a summary
loses the exact error, path or line. With lcc, the parent passes ids instead. The worker gets
the lcc MCP server and uses its `recall` tool to fetch the outputs it needs, byte for byte.
The server also offers lcc's other tools; the worker is only told to use `recall`.

1. **Write the handoff.** `lcc handoff <session>` writes a packet with the requests, files,
   last error and the 30 most recent stashed ids ([HANDOFF.md](HANDOFF.md)). It checks their
   hashes newest first, up to 8 MB of blobs, and marks the rest "not checked". It is not a
   full inventory of the stash. A parent that only wants to pass a few outputs can put their
   ids straight in the prompt.
2. **Start the worker with the lcc MCP server**, on the same machine and with the same
   `LCC_STASH_DIR`. Give it the packet or the ids.

Claude Code:

```bash
claude -p "$(cat .lcc/handoff/3f9a1c0d8e7b.md)

Continue the task above. Use the lcc recall tool for any stashed output you need." \
  --mcp-config '{"mcpServers": {"lcc": {"command": "lcc", "args": ["mcp"]}}}' \
  --allowedTools mcp__lcc__recall < /dev/null
```

Codex CLI:

```bash
codex exec -c 'mcp_servers.lcc.command="lcc"' -c 'mcp_servers.lcc.args=["mcp"]' \
  "$(cat .lcc/handoff/3f9a1c0d8e7b.md)

Continue the task above. Use the lcc recall tool for any stashed output you need." < /dev/null
```

Any other MCP client takes the same stdio server, `lcc mcp`. To point the worker at another
stash, set `LCC_STASH_DIR` in the server's `env`: `"env": {"LCC_STASH_DIR": "/path"}` in the
JSON, or `-c 'mcp_servers.lcc.env.LCC_STASH_DIR="/path"'` for Codex. `< /dev/null` stops the
CLI from waiting for stdin.

**Measured 2026-11-07.** A test run with one failing test was stashed in an empty stash, and a
worker was given only its 12-character id. Each worker called `recall` and replied with the
`FAILED` line, character for character:

- `claude -p` on Claude Code 2.1.309, with `claude-haiku-5-5`, in 3 turns;
- `codex exec` on the Codex CLI.

Gemini CLI, Cursor and other clients were not tested.

## What the worker can and cannot do

- `recall` never changes a stored output. It re-checks each output's sha256 and refuses one
  that does not match. It does write metadata: a `.lock` file, the blob's sidecar
  (`last_recalled_at`) and, with the ledger on, a ledger line.
- `--allowedTools mcp__lcc__recall` lets a `claude -p` worker call `recall` without a
  permission prompt. It adds that approval; it does not hide lcc's other tools or remove
  permissions the worker already has.
- The stash is local. On macOS and Linux it is owner-only (`0700`/`0600`). On Windows lcc
  sets no ACLs, so the folder's own ACLs decide who can read it. A worker on another
  machine, or under another user on POSIX, cannot recall. Copy the blobs, or run the worker
  where the stash is.
- A recalled output and the text quoted in a handoff packet are untrusted data for the
  worker, not instructions from the parent. The packet's fences stop quoted text from
  closing them early. They do not stop a model from following instructions written inside
  that text.
