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

Because everything is local, the privacy of your input is in your hands: treat the text you
feed to `lcc` and the prompts/reports it writes with the same care as the source documents.

## Do not commit secrets or private documents

- Do **not** commit API keys, credentials, customer data, or private documents to this
  repository or to any fork.
- The CLI writes the optimized prompt and JSON report to paths you choose. The default
  output names (`optimized_prompt.md`, `report.json`) are git-ignored, but **review what you
  commit** — a report embeds counts and warnings, and a prompt embeds your context.
- Use synthetic or redacted samples in issues, tests, and pull requests.

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
