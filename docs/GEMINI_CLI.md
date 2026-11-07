# Gemini CLI saved chats as lcc input (#108)

The reader in `src/lcc/gemini_history.py` converts a saved Gemini CLI chat to
the same `text`, `toolUses` and `toolResults` messages used by lcc's other
session readers. It reads only the file you select. It does not start Gemini,
search your home directory, run tools or contact a model.

## Find and measure a saved chat

Gemini CLI stores project chats under
`~/.gemini/tmp/<project-id>/chats/session-*.jsonl` (on Windows, `~` is your
user home directory). In 0.66.0 the project id is a registered slug; older
releases used a project hash and `.json` conversation snapshots.
The format verified here is **Gemini CLI core 0.66.0**; future versions may change it.

Current JSONL sessions are auto-detected by `measure-session`:

```sh
lcc measure-session /path/to/session.jsonl --json
```

The default modes run offline and report counts only. They do not include
session text, file paths or tool output. `--input-map` is a separate Claude
Code billing analysis; it does not support Gemini billing records.

For a legacy snapshot, or to use `compact`, convert the selected file first:

```python
import json
from pathlib import Path
from lcc.gemini_history import from_gemini_cli

messages = from_gemini_cli(Path("/path/to/session.jsonl"))  # .json also accepted
Path("transcript.json").write_text(
    json.dumps({"messages": messages}, ensure_ascii=False), encoding="utf-8"
)
```

```sh
lcc compact transcript.json -q "finish this task" --mode tool-calls \
  --provider rules --rules-mode lossless -o compacted.json -r report.json
```

The converted and compacted files contain the selected session's private
content. Keep them local. Compaction produces lcc messages, not a Gemini
session file; do not overwrite Gemini's own saved chat with this output.
The `specialist-v3` model was trained on Claude Code transcripts, so Gemini
histories are out of distribution. This reader does not establish model quality.

## What maps to what

| Saved Gemini content | lcc transcript |
| --- | --- |
| `user` / `gemini` content strings and text parts | user / assistant `text`, concatenated without inserted separators |
| `gemini.toolCalls` with an id and name | assistant `toolUses`, retaining ids, names and arguments |
| A recorded call's non-null `result` | a following user `toolResults` message with the same id |
| Pending call without a result | call retained; no result invented |
| Error-status call | result has `is_error: true` |
| `thoughts`, tokens, `displayContent`, info/error/warning UI records | omitted |
| Images, audio and other non-text message parts | omitted; this is a text/tool reader, not a multimodal export |

Text and whitespace are preserved exactly, including adjacent text fragments.
Tool responses containing a single string `output` or `error` retain that
string. Other structured function responses are serialized as JSON; their
original JSON whitespace is not retained. A parallel response turn can be
attached to several calls in Gemini's log; responses are matched by id so one
tool's output is not copied into its neighbours. The redundant user
`functionResponse` turn is not emitted a second time.
A response without an id is accepted only when it is unambiguous and its
optional name matches the call. Ambiguous responses and malformed calls are omitted.

The JSONL reader replays full-message replacements, `$patch` changes and
ordering, `$rewindTo` rollbacks and legacy `$set.messages` checkpoints before
conversion. It does not include branches Gemini has discarded. Unknown records
and malformed individual lines, including an unfinished final write, are
ignored as in Gemini's loader. A missing `sessionId`/`projectHash` header raises
`ValueError` in the explicit reader rather than guessing the format.

## Fixture and validation

`tests/fixtures/gemini_cli/session.jsonl` was produced by the actual
`ChatRecordingService` from `@google/gemini-cli-core@0.66.0`, using only synthetic
messages and tool results. No model, API key or existing user chat was used.
The adjacent README and generator document how to reproduce it. Google's own
`loadConversationRecord` was used to verify the replayed message order.

Upstream format references:

- [chatRecordingService.ts](https://github.com/google-gemini/gemini-cli/blob/v0.66.0/packages/core/src/services/chatRecordingService.ts)
- [chatRecordingTypes.ts](https://github.com/google-gemini/gemini-cli/blob/v0.66.0/packages/core/src/services/chatRecordingTypes.ts)

Run `pytest -q tests/test_gemini_history.py` to check recorded message counts,
tool pairing, patches and rewinds, exact user text, session measurement and
offline lossless compaction.
