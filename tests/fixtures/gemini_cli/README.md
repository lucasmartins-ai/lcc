# Gemini CLI recorder fixture

`session.jsonl` is the unedited output of the actual
`@google/gemini-cli-core@0.66.0` `ChatRecordingService`, recorded offline on
2026-11-02. All input text, file names, tool ids, tool results and the project
root are synthetic. No user chat, credentials or model response was used.
The recorder received a minimal local context, not a live Gemini `Config`.
It did not authenticate, invoke an LLM or execute any of the recorded tools.

The fixture contains full-message replacements, two parallel read-file calls,
completed results, a discarded branch, a rewind and a real history-sync patch.
Google's `loadConversationRecord` loads five saved messages in this order:
`user-1`, `assistant-1`, `tool-results`, `user-2`, `assistant-2`.
Lcc emits five transcript messages too, replacing the redundant function-response
turn with the two correctly paired results.

Fixture SHA-256:
`3226448e470b2390c245bbab8f9b519d8aa94d77496c4c25e18d914563b69f7b`

Official package used:

- Version: `@google/gemini-cli-core@0.66.0`
- Archive: `https://registry.npmjs.org/@google/gemini-cli-core/-/gemini-cli-core-0.66.0.tgz`
- npm integrity: `sha512-fhrC9UfDY91VK+bCz7fZQE0NBas2TgwYeF099cG2TVYeoxwL2g4FaHC6pPHYfk14i4Sd1xAeboLEtOAPelrcLA==`
- Upstream is Apache-2.0. No upstream implementation or dependencies are vendored here.

## Regenerate without an API key

In an empty scratch directory, install that exact development-only package:

```sh
npm install --ignore-scripts @google/gemini-cli-core@0.66.0
node /path/to/lcc/tests/fixtures/gemini_cli/record_fixture.mjs \
  ./node_modules/@google/gemini-cli-core ./fixture-output
```

This writes the captured JSONL and Google's loaded conversation to
`fixture-output/`. The saved message order and content reproduce; timestamps
are the generation time, so a new run has a different byte hash. The lcc test
suite uses the committed fixture and needs neither Node nor Gemini installed.

The loader additionally supports the old whole-conversation JSON shape, which
is covered by a small constructed unit test. This is not a claim that we
captured or tested every historical Gemini CLI release.
