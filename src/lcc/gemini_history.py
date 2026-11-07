"""Read Gemini CLI saved chats, without running Gemini or accessing its tools.

Gemini CLI 0.66.0 writes an append-only JSONL log, not just a list of turns.
Replay replacements, patches and rewinds before mapping the resulting conversation.
The older JSON conversation snapshot is also accepted. See ``docs/GEMINI_CLI.md``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def is_gemini_chat_record(record: Any) -> bool:
    """Recognize Gemini's session header, rather than guessing from a message role."""
    return (
        isinstance(record, dict)
        and isinstance(record.get("sessionId"), str)
        and bool(record["sessionId"])
        and isinstance(record.get("projectHash"), str)
        and bool(record["projectHash"])
    )


def _records(text: str) -> Iterable[Any]:
    try:
        yield json.loads(text)
        return
    except (json.JSONDecodeError, RecursionError):
        pass
    # JSONL uses LF, not every Unicode line-separator character. JSON.stringify
    # leaves U+0085/U+2028/U+2029 literal inside strings, where splitlines loses them.
    yield from _line_records(text.split("\n"))


def _line_records(lines: Iterable[str]) -> Iterable[Any]:
    for line in lines:
        try:
            yield json.loads(line)
        except (json.JSONDecodeError, RecursionError):
            # Match Gemini's loader, including a partially written last line.
            continue


def _saved_messages(records: Iterable[Any]) -> list[dict[str, Any]]:
    messages: dict[str, dict[str, Any]] = {}
    recognized = False

    def store(items: Any) -> None:
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    messages[item["id"]] = item

    def update(patch: Any) -> None:
        if not isinstance(patch, dict):
            return
        message_id = patch.get("id")
        message = messages.get(message_id) if isinstance(message_id, str) else None
        if message is None:
            return
        if "content" in patch:
            message["content"] = patch["content"]
        if isinstance(patch.get("toolCalls"), list) and isinstance(message.get("toolCalls"), list):
            for change in patch["toolCalls"]:
                if not isinstance(change, dict) or "result" not in change:
                    continue
                for call in message["toolCalls"]:
                    if isinstance(call, dict) and call.get("id") == change.get("id"):
                        call["result"] = change["result"]

    for record in records:
        if not isinstance(record, dict):
            continue
        if isinstance(record.get("$rewindTo"), str):
            ids = list(messages)
            start = ids.index(record["$rewindTo"]) if record["$rewindTo"] in messages else 0
            for key in ids[start:]:
                del messages[key]
        elif isinstance(record.get("$patch"), dict):
            patch = record["$patch"]
            update(patch)
            for item in patch.get("updates", []) if isinstance(patch.get("updates"), list) else []:
                update(item)
            for key in (
                patch.get("removeIds", []) if isinstance(patch.get("removeIds"), list) else []
            ):
                if isinstance(key, str):
                    messages.pop(key, None)
            if isinstance(patch.get("orderIds"), list):
                ordered = [
                    key for key in patch["orderIds"] if isinstance(key, str) and key in messages
                ]
                tail = {key: messages[key] for key in ordered}
                messages = {key: value for key, value in messages.items() if key not in tail} | tail
        elif isinstance(record.get("id"), str):
            messages[record["id"]] = record
        elif isinstance(record.get("$set"), dict):
            if isinstance(record["$set"].get("messages"), list):
                messages.clear()
                store(record["$set"]["messages"])
        elif is_gemini_chat_record(record):
            recognized = True
            store(record.get("messages"))
    if not recognized:
        raise ValueError("not a Gemini CLI saved chat (missing sessionId/projectHash header)")
    return list(messages.values())


def _parts(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str:
    # Adjacent text parts are fragments, so inserting separators would change the text.
    return "".join(
        part if isinstance(part, str) else part.get("text", "")
        for part in _parts(value)
        if isinstance(part, str)
        or (
            isinstance(part, dict)
            and isinstance(part.get("text"), str)
            and part.get("thought") is not True
        )
    )


def _result_text(value: Any, call_id: str, call_name: str) -> str | None:
    result_parts = [
        part
        for part in _parts(value)
        if not isinstance(part, dict) or part.get("thought") is not True
    ]
    functions = [
        part["functionResponse"]
        for part in result_parts
        if isinstance(part, dict) and isinstance(part.get("functionResponse"), dict)
    ]
    if not functions:
        has_text = any(
            isinstance(part, str) or (isinstance(part, dict) and isinstance(part.get("text"), str))
            for part in result_parts
        )
        return _text(result_parts) if has_text or value == [] else None
    # History synchronization can attach a whole parallel-response turn to each
    # call. Prefer exact ids; don't assign an ambiguous id-less result by position.
    matching = [function for function in functions if function.get("id") == call_id]
    if not matching:
        matching = [
            function
            for function in functions
            if function.get("id") is None and function.get("name") in (None, call_name)
        ]
        if len(matching) != 1:
            return None
    parts = []
    for function in matching:
        response = function.get("response")
        if isinstance(response, dict) and len(response) == 1:
            output = response.get("output", response.get("error"))
            if isinstance(output, str):
                parts.append(output)
                continue
        parts.append(json.dumps(response, ensure_ascii=False))
    return "".join(parts)


def messages_from_gemini_records(records: Iterable[Any]) -> list[dict[str, Any]]:
    """Replay saved records and return hook-shaped text and paired tool messages.

    User/assistant text parts are concatenated verbatim. Thoughts, UI notifications,
    display-only text and non-text parts are not included. Results come from each
    recorded tool call; duplicated functionResponse history turns are not emitted twice.
    """
    messages: list[dict[str, Any]] = []
    for record in _saved_messages(records):
        kind = record.get("type")
        if kind not in ("user", "gemini"):
            continue
        entry: dict[str, Any] = {
            "role": "assistant" if kind == "gemini" else "user",
            "text": _text(record.get("content")),
        }
        calls, results = [], []
        saved_calls = record.get("toolCalls")
        for call in saved_calls if kind == "gemini" and isinstance(saved_calls, list) else []:
            if not isinstance(call, dict):
                continue
            call_id, name = call.get("id"), call.get("name")
            if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                continue
            args = call.get("args", {})
            if not isinstance(args, dict):
                continue
            calls.append({"tool_use_id": call_id, "tool": name, "input": args})
            if call.get("result") is not None:
                text = _result_text(call["result"], call_id, name)
                if text is None:
                    continue
                result: dict[str, Any] = {
                    "tool_use_id": call_id,
                    "text": text,
                }
                if call.get("status") == "error":
                    result["is_error"] = True
                results.append(result)
        if calls:
            entry["toolUses"] = calls
        if entry["text"] or calls:
            messages.append(entry)
        if results:
            messages.append({"role": "user", "text": "", "toolResults": results})
    return messages


def parse_gemini_chat_history(text: str) -> list[dict[str, Any]]:
    """Read a Gemini CLI JSONL log or legacy JSON snapshot from a string."""
    return messages_from_gemini_records(_records(text))


def messages_from_gemini_jsonl(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Read current Gemini JSONL records from an iterable of lines."""
    return messages_from_gemini_records(_line_records(lines))


def from_gemini_cli(path: Path | str) -> list[dict[str, Any]]:
    """Read one explicitly selected saved chat as UTF-8; never discover private files."""
    return parse_gemini_chat_history(Path(path).read_text(encoding="utf-8"))
