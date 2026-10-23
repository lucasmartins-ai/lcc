"""Convert an Aider ``.aider.chat.history.md`` file into an lcc transcript.

Aider's chat history is Markdown with a fixed line grammar (see Aider's own
``split_chat_history_markdown`` in ``aider/utils.py``):

- ``# `` session headers (skipped)
- ``#### `` user turns
- ``> `` Aider tool / UI lines (file adds, token counts, confirms)
- everything else: assistant (LLM) output

That grammar is regular enough to map **user and assistant text** into the
``{"messages": [{"role", "text"}, ...]}`` shape that
``lcc compact --mode tool-calls`` accepts. It does **not** carry
``toolUses`` / ``toolResults`` pairs with ids: Aider applies edits itself and
logs them as plain assistant text (SEARCH/REPLACE fences), not as tool_use
blocks. The ``>`` lines are Aider notifications, not LLM tool results.

Default conversion drops ``>`` lines (matching Aider's ``include_tool=False``
when restoring history). Pass ``include_tool=True`` to keep them as user
messages whose text is the stripped blockquote body.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def parse_aider_chat_history(text: str, *, include_tool: bool = False) -> list[dict[str, Any]]:
    """Parse Aider chat-history Markdown into hook-shaped transcript messages.

    Returns a list of ``{"role": "user"|"assistant", "text": ...}`` dicts in
    file order. Empty segments are omitted. No ``toolUses`` / ``toolResults``
    are invented: the source format has no tool-call ids to pair.
    """
    messages: list[dict[str, Any]] = []
    user: list[str] = []
    assistant: list[str] = []
    tool: list[str] = []

    def append_msg(role: str, parts: list[str]) -> None:
        body = "".join(parts)
        if body.strip():
            messages.append({"role": role, "text": body})

    for line in text.splitlines(keepends=True):
        if line.startswith("# "):
            continue
        if line.startswith("> "):
            append_msg("assistant", assistant)
            assistant = []
            append_msg("user", user)
            user = []
            tool.append(line[2:])
            continue
        if line.startswith("#### "):
            append_msg("assistant", assistant)
            assistant = []
            if include_tool:
                append_msg("user", tool)
            tool = []
            user.append(line[5:])
            continue
        append_msg("user", user)
        user = []
        if include_tool:
            append_msg("user", tool)
        tool = []
        assistant.append(line)

    append_msg("assistant", assistant)
    append_msg("user", user)
    if include_tool:
        append_msg("user", tool)

    return messages


def from_aider_chat_history(
    path: Path | str, *, include_tool: bool = False
) -> list[dict[str, Any]]:
    """Read ``.aider.chat.history.md`` (or any path) into transcript messages."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_aider_chat_history(text, include_tool=include_tool)


def messages_payload(
    messages: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Wrap messages for ``lcc compact --mode tool-calls`` / ``parse_transcript``."""
    return {"messages": messages}
