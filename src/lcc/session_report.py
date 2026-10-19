"""`lcc measure-session`: what each compaction mode would do to one of your sessions.

Reads a Claude Code session file (JSONL) locally, runs the tool-call compaction modes offline
and reports **counts only**: messages, tool calls, tokens before and after, user/assistant texts
kept byte for byte, time. No session text, path or tool output is in the report, so it can be
pasted into a public issue. Nothing is sent anywhere; `stashed` writes to a temporary stash that
is deleted afterwards.
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
import time
from pathlib import Path
from typing import Any

SCHEMA = "lcc-session-report/1"
#: (label, provider, rules_mode). `recoverable` is left out: it needs the session's disk.
MODES: tuple[tuple[str, str, str], ...] = (
    ("rules:lossless", "rules", "lossless"),
    ("rules:stashed", "rules", "stashed"),
    ("auto", "auto", "lossless"),  # rules_mode is ignored outside provider "rules"
)


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False) if content else ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif isinstance(block, dict) and block.get("type") == "image":
            parts.append("[image]")
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


def from_claude_code(path: Path) -> list[dict[str, Any]]:
    """Claude Code JSONL -> the message shape the plugin hook receives (thinking blocks and
    results whose call is not in the file are left out, as the hook never sees them)."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        return messages_from_jsonl(handle)


def messages_from_jsonl(lines: Any) -> list[dict[str, Any]]:
    """Same as :func:`from_claude_code`, over the file's lines."""
    messages: list[dict[str, Any]] = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        message = record.get("message")
        if record.get("type") not in ("user", "assistant") or not isinstance(message, dict):
            continue
        content = message.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        texts, calls, results = [], [], []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                texts.append(str(block.get("text") or ""))
            elif kind == "tool_use":
                raw_input = block.get("input")
                calls.append(
                    {
                        "tool_use_id": str(block.get("id")),
                        "tool": str(block.get("name")),
                        "input": raw_input if isinstance(raw_input, dict) else {},
                    }
                )
            elif kind == "tool_result":
                results.append(
                    {
                        "tool_use_id": str(block.get("tool_use_id")),
                        "text": _result_text(block.get("content")),
                    }
                )
        entry: dict[str, Any] = {
            "role": message.get("role") or record["type"],
            "text": "\n".join(texts),
        }
        if calls:
            entry["toolUses"] = calls
        if results:
            entry["toolResults"] = results
        if entry["text"].strip() or calls or results:
            messages.append(entry)
    known = {c["tool_use_id"] for m in messages for c in m.get("toolUses") or []}
    for m in messages:
        kept = [r for r in m.get("toolResults") or [] if r["tool_use_id"] in known]
        if kept:
            m["toolResults"] = kept
        else:
            m.pop("toolResults", None)
    return [m for m in messages if m["text"].strip() or m.get("toolUses") or m.get("toolResults")]


def _flatten(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages:
        parts.append(str(m.get("text") or ""))
        for c in m.get("toolUses") or []:
            parts.append(
                f"{c.get('tool_use_id')} {c.get('tool')} "
                f"{json.dumps(c.get('input'), sort_keys=True, default=str)}"
            )
        for r in m.get("toolResults") or []:
            parts.append(str(r.get("text") or ""))
    return "\n".join(parts)


def _norm(text: str) -> str:
    return " ".join(text.split())


def measure_session(
    path: Path, question: str = "finish the task in this session"
) -> dict[str, Any]:
    from lcc import __version__
    from lcc.relevance.transcript import (
        TranscriptCompactionRequest,
        compact_transcript,
        messages_to_payload,
    )
    from lcc.token_budget import count_tokens

    messages = from_claude_code(path)
    before = count_tokens(_flatten(messages), "gpt-4.1")
    texts = [m["text"] for m in messages if m["text"].strip()]
    rows: list[dict[str, Any]] = []
    previous = os.environ.get("LCC_STASH_DIR")
    with tempfile.TemporaryDirectory(prefix="lcc-measure-") as scratch:
        os.environ["LCC_STASH_DIR"] = scratch  # never the user's real stash
        try:
            for label, provider, rules_mode in MODES:
                started = time.perf_counter()
                try:
                    result = compact_transcript(
                        TranscriptCompactionRequest(
                            payload={"messages": messages},
                            question=question,
                            provider=provider,
                            rules_mode=rules_mode,
                        )
                    )
                except Exception as error:  # noqa: BLE001 - a mode that cannot run is a finding
                    rows.append({"mode": label, "error": type(error).__name__})
                    continue
                after_text = _flatten(messages_to_payload(result.messages))
                after = count_tokens(after_text, "gpt-4.1").value
                kept = _norm(after_text)
                rows.append(
                    {
                        "mode": label,
                        "provider_used": result.report["provider_used"],
                        "degraded": bool(result.report["degraded"]),
                        "tokens_after": after,
                        "reduction": round(1 - after / before.value, 4) if before.value else 0.0,
                        "texts_lost": sum(_norm(t) not in kept for t in texts),
                        "stashed": result.report.get("tool_calls_stashed") or 0,
                        "ms": int((time.perf_counter() - started) * 1000),
                    }
                )
        finally:
            if previous is None:
                os.environ.pop("LCC_STASH_DIR", None)
            else:
                os.environ["LCC_STASH_DIR"] = previous
    return {
        "schema": SCHEMA,
        "lcc_version": __version__,
        "platform": f"{platform.system()} {platform.machine()}",
        "messages": len(messages),
        "tool_calls": sum(len(m.get("toolUses") or []) for m in messages),
        "texts": len(texts),
        "tokens_before": before.value,
        "token_count_method": before.method.value,
        "modes": rows,
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"**lcc measure-session** · lcc {report['lcc_version']} · {report['platform']} · "
        f"tokens counted {report['token_count_method']}",
        "",
        f"Session: {report['messages']} messages, {report['tool_calls']} tool calls, "
        f"{report['tokens_before']:,} tokens, {report['texts']} user/assistant texts.",
        "",
        "| mode | tokens after | reduction | texts kept | stashed results | time |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["modes"]:
        if "error" in row:
            lines.append(f"| {row['mode']} | did not run ({row['error']}) | | | | |")
            continue
        kept = report["texts"] - row["texts_lost"]
        lines.append(
            f"| {row['mode']} | {row['tokens_after']:,} | {row['reduction']:.1%} | "
            f"{kept}/{report['texts']} | {row['stashed']} | {row['ms']} ms |"
        )
    lines += ["", "Counts only: no session text, file path or tool output is included."]
    return "\n".join(lines)
