# LCC as an MCP server (`lcc mcp`)

`src/lcc/mcp_server.py` is a minimal
[Model Context Protocol](https://modelcontextprotocol.io/) server over stdio
(JSON-RPC 2.0, `Content-Length` framing). It exposes six tools:

| Tool | What it does | Offline? |
| :--- | :--- | :--- |
| `compact` | Relevance compaction (`text`, `question`, `provider=mechanical`, `threshold=0.4`); returns `compacted_text` + full report | Yes with `mechanical`/`laya`; `jev` needs `TYPESAFE_API_KEY` |
| `compact_transcript` | Tool-call compaction of a session transcript (`messages`, `question`, `preserve_recent=6`): pairs each tool call with its result and keeps, trims or drops the pair; kept messages are verbatim. Contract and limits: [`docs/TOOL_CALLS.md`](TOOL_CALLS.md) | `jev`/`auto` only (needs `TYPESAFE_API_KEY`); failures keep every call |
| `inspect` | Read-only diagnostic inspection; returns the inspection report | Yes |
| `prepare` | Inspect-first deterministic preparation; returns `action` + `prompt` (or skip note) | Yes |
| `explain` | Audits a `compact` report object (`report`, optional `source_text`/`only`/`limit`) | Yes |
| `intake` | Intake triage: readiness, intent, questions, assumptions, compiled prompt | Yes (default; no relevance pass) |

Stdlib only — no new dependencies, and the base install is untouched. The
server only calls the same public library entry points as the CLI, so the
deterministic-core boundary (ADR 0010, `tests/test_deterministic_boundary.py`)
is unaffected.

## Run it

```bash
lcc mcp                       # stdio server (Ctrl-C / EOF to stop)
python -m lcc.mcp_server      # same, without the console script
```

## Connect an agent

Claude Code / generic MCP client (`~/.claude.json`, `.mcp.json`, or equivalent):

```json
{
  "mcpServers": {
    "lcc": { "command": "lcc", "args": ["mcp"] }
  }
}
```

With `pipx`: replace `"command"` with the full path from
`pipx --global-home` (or `which lcc`). With an editable checkout, use
`<repo>/.venv/bin/lcc`.

## Smoke test (no client needed)

```bash
.venv/bin/python - <<'EOF'
import json, subprocess

def frame(payload):
    body = json.dumps(payload).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)

def unframe(out):
    _, _, body = out.partition(b"\r\n\r\n")
    return json.loads(body)

msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]
p = subprocess.run([".venv/bin/lcc", "mcp"], input=b"".join(map(frame, msgs)),
                   capture_output=True, timeout=60)
responses = []
rest = p.stdout
while rest:
    head, _, rest2 = rest.partition(b"\r\n\r\n")
    n = int(head.split(b":")[1])
    responses.append(json.loads(rest2[:n]))
    rest = rest2[n:]
print(responses[0]["result"]["serverInfo"])
print([t["name"] for t in responses[1]["result"]["tools"]])
EOF
```

Simpler still: `tests/test_mcp_server.py` speaks the protocol end-to-end
(initialize → tools/list → tools/call `compact`/`inspect`/`explain`, all
offline) and is the executable contract.

## Notes for integrators

- `compact` defaults to `provider: "mechanical"` — safe for agents with no
  key. Pass `"laya"` only if the `[laya]` extra is installed, `"jev"` only
  with `TYPESAFE_API_KEY` in the server's environment.
- Tool errors come back as `{content: [{type: "text", text: "error: …"}],
  isError: true}` — never as dropped content.
- The server never writes files and never touches the network beyond what the
  chosen provider does (`mechanical`/`laya`: zero).
