# Security Policy

## Local-first privacy

`lcc` is designed to run entirely on your machine.

- **No network calls.** `lcc` blocks runtime network access by default — including indirect
  access — and never sends your text anywhere.
- **No API keys.** Nothing in `lcc` requires credentials; `.env.example` documents that.
- **No telemetry.** `lcc` does not collect or transmit usage data.
- The optional `tiktoken` dependency is used **locally** for token counting, and its first-use
  encoding download is actively blocked: the exact path runs inside a no-network guard, so if
  `tiktoken` would fetch encoding assets, `lcc` blocks the attempt and falls back to a clearly
  labelled approximate counter rather than downloading, failing, or hanging. Exact counting
  therefore requires the encoding assets to be cached locally. See
  [ADR 0008](docs/adr/0008-tokenizer-network-boundary.md).

- **Remote scoring only when you name it.** The optional `jev` provider sends context blocks to
  the TypeSafe API. It runs only with `--provider jev` / `provider: "jev"`, or under `auto`
  when you also set `LCC_AUTO_REMOTE=1`; a TypeSafe key in the environment, a key file or the
  Keychain is not consent on its own. `LCC_DISABLE_NETWORK=1` overrides everything: Jev,
  Hugging Face downloads for Laya, the router's cloud solver, and non-loopback local-model
  endpoints all refuse.

Because everything is local, the privacy of your input is in your hands: treat the text you
feed to `lcc` and the prompts/reports it writes with the same care as the source documents.

## Do not commit secrets or private documents

- Do **not** commit API keys, credentials, customer data, or private documents to this
  repository or to any fork.
- The CLI writes the optimized prompt and JSON report to paths you choose. The default
  output names (`optimized_prompt.md`, `report.json`) are git-ignored, but **review what you
  commit** — a report embeds counts and warnings, and a prompt embeds your context.
- Use synthetic or redacted samples in issues, tests, and pull requests.

## Threat model

**What lcc protects.**

- *Your context stays on your machine* unless you name a remote provider (above).
- *Kept text is byte-identical* and every removal is named in the report; `stashed` keeps the
  removed bytes in a private, content-addressed stash (`~/.cache/lcc/stash` or
  `$LCC_STASH_DIR`, directory `0700`, files `0600`) and `recall` re-hashes before returning.
  Stash ids must be 12-64 lowercase hex characters, so a recall cannot name another path.
- *Local logs are private and redacted.* The opt-in request log (`LCC_REQUEST_LOG=1`) and the
  Jev ledger are written `0600`; the request log keeps redacted goals only (never context),
  and the ledger never stores the API key or a bearer token.
- *Untrusted text cannot steer the tooling.* Tool outputs inside a transcript are data:
  `rules` modes decide from structure (duplicates, re-readable files, the stash), a tool
  output can only make lcc keep more, and the Claude Code pin hook quotes tool errors as data
  for the summarizer. `lcc explain` escapes control characters, so ANSI/OSC sequences in a
  report or `--source` file cannot rewrite the terminal.
- *Bounded work on hostile input.* Cleaning regexes run in linear time, near-duplicate
  detection has a deterministic work budget (it stops early, keeps the rest, and warns), and
  both MCP transports answer malformed or deeply nested JSON with a parse error instead of
  crashing.
- *The HTTP server (`lcc mcp --http`) never exposes the host's disk.* The stash, `recall`,
  `workspace_root` disk checks and `laya_model` are stdio-only; anonymous callers (no
  `LCC_HTTP_TOKEN`) get only the offline providers; errors return no exception text. It
  binds `127.0.0.1` unless you pass `--host`; put TLS in front of any public deployment.

**What lcc does not protect against.**

- *A malicious local user or process* running as you: it can read the stash, the logs and
  your files directly.
- *The disk check on stdio is not a sandbox.* With `workspace_root` set, `recoverable` reads
  the files the transcript's own read calls name (regular files up to 4 MiB, no `..`, no
  final symlink out of the file's directory) to confirm a pointer; files outside the
  workspace root are allowed by design. The caller of `lcc mcp` is your own agent, so treat
  a transcript you did not produce like any other untrusted input.
- *Secrets inside the context you compact.* lcc does not scan or redact your context; kept
  text is returned verbatim and stashed text is stored verbatim (privately).
- *Stashed secrets outliving their transcript.* The stash keeps its copy until you delete it:
  removing a session file does not remove the blobs it pointed to, and nothing expires by
  default. `lcc stash gc --apply` deletes blobs no transcript under `--root` references (and
  not used within `--older-than`); it fails closed and never runs on its own. Sidecars hold
  timestamps and truncated session-id hashes only. See `docs/TOOL_CALLS.md`, *Retention*.
- *The remote provider's handling of data* once you opt in to `jev`.
- *Semantic prompt injection against your model.* lcc never follows instructions in the
  text it compacts, but it does not remove them either: kept text reaches your model as is.

## A note on cleaning safety

Boilerplate removal is intentionally conservative: it only removes lines that match a
boilerplate pattern *in full* (e.g. "Sent from my iPhone", "Page 3 of 10", long decorative
rules). It never truncates partial content, and it can be disabled with `--no-boilerplate`.
Deduplication removes whole duplicate paragraphs only; it never rewrites or shortens text.
If you believe a default pattern is too aggressive, please open an issue.

## Reporting a vulnerability

If you discover a security or privacy issue (for example, an unexpected file write, a path
that escapes the working directory, or any code path that performs network access), please
report it privately to the maintainers rather than opening a public issue. Include steps to
reproduce and the affected version. We will acknowledge the report and work on a fix.
