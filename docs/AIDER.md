# Aider chat history as lcc input (#63)

Aider stores each session in `.aider.chat.history.md`. The file is Markdown with a
fixed line grammar (Aider's own `split_chat_history_markdown` in `aider/utils.py`):

| Line prefix | Aider meaning | Maps to lcc transcript? |
| --- | --- | --- |
| `# ` | session header (`# aider chat started at …`) | skipped |
| `#### ` | user turn | yes → `{"role": "user", "text": …}` |
| (no prefix) | assistant / LLM output (often with SEARCH/REPLACE fences) | yes → `{"role": "assistant", "text": …}` |
| `> ` | Aider tool / UI notification (token counts, file add, confirms) | optional → user `text` when `include_tool=True`; default dropped |

## Verdict

**Yes for user and assistant text.** The structure is regular enough to build the
JSON transcript shape that `lcc compact --mode tool-calls` takes
(`{"messages": [{"role", "text"}, …]}`).

**No for `toolUses` / `toolResults` pairs.** Aider does not log LLM tool calls with
ids. It applies edits itself and writes them as ordinary assistant Markdown. The
`>` lines are Aider's own notifications, not paired `tool_use` / `tool_result`
blocks. A converted history therefore has **no tool-call pairs to score**: tool-calls
mode still accepts the file (text-only messages stay pinned or pass through), but
there is nothing for the judge or rules policy to drop. Prefer block mode, or keep
using Aider's own history summarizer, when the goal is shrinking Aider context.

`specialist-v3` was trained on Claude Code transcripts; an Aider-derived session is
out of distribution there.

## Sample

Synthetic `.aider.chat.history.md`:

```markdown
# aider chat started at 2026-03-01 10:15:00

> Aider v0.82.0
> Model: gpt-4o with diff edit format
> Added hello.py to the chat

#### Fix the greeting in hello.py

I'll update the print.

hello.py
<<<<<<< SEARCH
print("hello")
=======
print("goodbye")
>>>>>>> REPLACE

> Applied edit to hello.py
> Tokens: 1.2k sent, 80 received.

#### Run the file and show the output
```

Converted (default, tool lines dropped) via `lcc.aider_history.from_aider_chat_history`:

```json
{
  "messages": [
    {"role": "user", "text": "Fix the greeting in hello.py\n"},
    {"role": "assistant", "text": "\nI'll update the print.\n\nhello.py\n<<<<<<< SEARCH\nprint(\"hello\")\n=======\nprint(\"goodbye\")\n>>>>>>> REPLACE\n\n"},
    {"role": "user", "text": "Run the file and show the output\n"}
  ]
}
```

## How to convert

```python
from pathlib import Path
from lcc.aider_history import from_aider_chat_history, messages_payload

messages = from_aider_chat_history(Path(".aider.chat.history.md"))
payload = messages_payload(messages)
# write payload as JSON, then:
#   lcc compact transcript.json -q "…" --mode tool-calls …
```

Reader: `src/lcc/aider_history.py`. Tests: `tests/test_aider_history.py` with
`tests/fixtures/aider_chat_history.md`.
