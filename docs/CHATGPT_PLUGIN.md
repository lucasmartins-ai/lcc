# ChatGPT plugin (`lcc`)

Turns `lcc` into a ChatGPT / Codex plugin: the six MCP tools already served over stdio
are also served over streamable HTTP, so ChatGPT can recommend and call them mid-conversation.

The deterministic engine is untouched. `src/lcc/chatgpt_server.py` is a transport that
reuses `lcc.mcp_server.handle_message`, so the two transports cannot drift.

## What ships

| Path | What it is |
| --- | --- |
| `src/lcc/chatgpt_server.py` | Streamable-HTTP transport over the existing MCP handlers |
| `plugins/chatgpt/plugin.json` | Portable plugin manifest + `extensions.com.openai` store metadata |
| `plugins/chatgpt/mcp.json` | Registered MCP server mapping |
| `tests/test_chatgpt_server.py` | Real HTTP round-trips against a live server on an ephemeral port |

## 1. Run the server

```bash
lcc mcp --http --host 0.0.0.0 --port 8080
```

Endpoint: `POST /mcp`, responses as a single SSE `message` event. Stdlib only — no new
dependency in the installed package.

Verb contract (all verified against a running server in the test suite):

| Request | Response | Why |
| --- | --- | --- |
| `POST /mcp` | `200` + SSE, or `202` for a notification | Result delivery |
| `GET /mcp` | `405` | No server-initiated stream exists; must not hang |
| `DELETE /mcp` | `200` | Stateless, no session to terminate |
| `POST /anything-else` | `404` | Unknown endpoint |
| malformed JSON | `400` | Parse error, as a JSON-RPC error body |

## 2. Deploy behind TLS

The submission portal requires a **public HTTPS origin** — a local or testing endpoint is
rejected. Put a TLS-terminating proxy in front of the process. Options that fit a stdlib
Python service with no extra app code:

```bash
# Fly.io
fly launch --now --http-service 8080   # or fly cert add <app>.<domain> for TLS

# Render / Railway
#   build: pip install . && lcc mcp --http --host 0.0.0.0 --port $PORT
```

Do not expose this process directly to the internet as plain HTTP.

### Domain verification

Plugins with MCP must prove control of the serving domain. The portal shows a
verification challenge; place the exact token at the generated well-known URL and
return **only that one token**:

```
https://<challenge-base-host>/.well-known/openai-apps-challenge
```

The endpoint must not return JSON, a list, or multiple tokens.

## 3. Point the manifest at your host

Edit `plugins/chatgpt/mcp.json`:

```json
{
  "mcpServers": {
    "lcc": { "type": "streamable-http", "url": "https://your-host/mcp" }
  }
}
```

Then update `plugins/chatgpt/plugin.json` version and zip the plugin folder
(`plugin.json`, `mcp.json`, plus `skills/` if you add one) for the portal.

## 4. Test in developer mode before submitting

1. ChatGPT → Settings → Security and login → enable **Developer mode**.
2. <https://chatgpt.com/plugins> → add the MCP server URL. Copy the technical ID that
   starts with `plugin_asdk_app`.
3. Run the `defaultPrompt` examples from `plugin.json` and check the tool that fires.

Discovery is driven by the store metadata, so the phrases in `shortDescription` and
`defaultPrompt` are the lever on whether ChatGPT recommends the plugin at all.

## Review requirements this build satisfies

- **Tool annotations** — every tool carries explicit `readOnlyHint`, `destructiveHint`,
  and `openWorldHint` booleans. All six are read-only. `openWorldHint` is `true` only for
  `compact` and `compact_transcript`, whose `jev`/`nimble` providers call a third-party
  judge; the default `mechanical` path is fully local.
- **Descriptions match behavior** — tool descriptions come from `TOOLS` in
  `mcp_server.py`, so they cannot drift from the implementations.
- **No secret-seeking inputs** — no tool asks for conversation history, credentials, or
  location. `compact_transcript` takes only the transcript the caller explicitly sends.
- **No telemetry** — nothing is stored or logged beyond the process' own access log.
- **Capability declared honestly** — `"Read"` only; the plugin never writes.

## Known gaps before submission

These are submission prerequisites that live in the OpenAI dashboard, not in this repo:

1. **Privacy policy URL.** A published privacy policy is required. `SECURITY.md` covers
   the zero-telemetry posture but is not the per-plugin policy page; `plugin.json` has no
   `privacyPolicyURL` field set yet.
2. **Organization + identity verification**, and the `api.apps.write` permission, for
   whoever owns the submitting org.
3. **No UI component.** The plugin is tools-only, which is allowed — screenshots are only
   expected for plugins that ship UI, and the directory now shows example prompts instead.
