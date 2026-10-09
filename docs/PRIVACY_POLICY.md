# Privacy Policy — Context Compiler (`lcc` plugin for ChatGPT)

**Effective date:** 1 October 2026
**Applies to:** the "Context Compiler" plugin (`lcc`) hosted at
`https://lcc-production.up.railway.app/mcp`, and the `lcc` open-source project it is
built from (<https://github.com/lucasmartins-ai/lcc>).

## Summary

The plugin processes the text you paste into a chat **on the server that runs it**, in
memory, for the length of a single request. It is not stored, not logged as content, and
not sent to any third party by default. The developer receives no copy of your data.

## What data the plugin collects

**The text you send, and the goal you state with it.** These arrive in the request body
of a tool call. They exist in server memory only while the request is being processed.

Nothing else. The plugin does **not** collect or request:

- account identifiers, names, emails, or profile data
- payment card information, government identifiers, or health information
- credentials, API keys, passwords, or authentication secrets
- precise or coarse location
- your conversation history, beyond the specific text you choose to pass to a tool

## Why the data is used

Sole purpose: score each block of the supplied text against the supplied goal, drop the
blocks the scoring finds irrelevant, and return the remainder verbatim plus a report
naming what was dropped. There is no other use.

## Who receives the data

No third party, by default. The hosted service runs the `mechanical` provider, which is
entirely local to the server process. **No model API is called and no text leaves the
server.**

One exception exists and is **not enabled on the hosted deployment**: the optional `jev`
provider sends your text to TypeSafe (`https://api.typesafe.ai/v1/systemone`) for
semantic scoring, and the optional `nimble` provider uses a locally hosted model. Neither
is configured on the hosted instance — it requires an explicit `TYPESAFE_API_KEY` that the
deployment does not set. If that ever changes, this policy must be updated first.

## Retention

No retention. Text is held in process memory for the duration of the request and is
discarded when the response is returned. The service writes no database, no user files,
and no content-addressed store.

The server's operational log records the request method, path, and status code only
(for example `POST /mcp 200`). It does **not** record request bodies, tool arguments, or
response contents.

The open-source CLI and MCP server have an opt-in request log (`LCC_REQUEST_LOG=1`) that
stores redacted goal strings locally, never the context. It is off by default and **not
enabled on the hosted deployment**. If that ever changes, this policy must be updated first.

## Third-party services and subprocessors

None in the request path. The plugin does not embed trackers, analytics, or advertising
SDKs, and it makes no outbound requests while serving a tool call.

## Your controls

- **You decide what to send.** Nothing is collected unless you paste it into a chat.
- **Avoid pasting secrets.** The plugin never asks for credentials, but you remain in
  control of what you include in the text you provide.
- **Deletion.** Because nothing is retained, there is no stored data to request or
  delete. To have hosted text removed, do not send it.

## Children's privacy

The plugin is not directed at children under 13 and collects no personal information
from anyone, of any age.

## Security

Requests are served over HTTPS only. The plugin's tools are read-only: they compute and
return text and never modify files, accounts, or external systems. See
[`SECURITY.md`](https://github.com/lucasmartins-ai/lcc/blob/main/SECURITY.md) in the
project for the underlying local-first security model.

## Your rights

Depending on where you live, you may have rights to access, correct, delete, or port
your personal data, and to object to or restrict processing. Because the plugin retains
nothing, these rights are satisfied by default: there is no data about you to access,
correct, delete, or export. For any privacy question, open an issue at
<https://github.com/lucasmartins-ai/lcc/issues>.

## Changes

Material changes to this policy will be published at this URL before taking effect, with
the effective date updated above.

## Contact

<https://github.com/lucasmartins-ai/lcc/issues>
