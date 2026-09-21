"""Measure tool-call compaction on a **real** session transcript.

Two sources, both real transcripts rather than synthetic corpora:

- ``--claude-code <file.jsonl|dir>``: a Claude Code session transcript — the exact input the
  plugin's hook hands over (``role``/``text``/``toolUses``/``toolResults``), so this measures
  the shipping path's data, not a model of it.
- ``--hermes <session_id|latest>``: this machine's Hermes conversation store
  (``~/.hermes/state.db``), converted to the same shape.

What it reports: exact tokens before/after, per-pair outcomes derived from the emitted
messages, whether every original user/assistant text survived byte-identical, the state-fit
stage (or the fit failure that makes the hook stand down), what the plugin's replacement rule
would decide, latency and the TypeSafe tokens the ledger recorded.

Usage:

    python3 benchmarks/research/measure_session.py --hermes latest
    python3 benchmarks/research/measure_session.py --claude-code ~/.claude/projects/-x/y.jsonl
    python3 benchmarks/research/measure_session.py --hermes latest --window-messages 60
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
RESULTS_DIR = HERE / "results"

DEFAULT_OPTIONS = {
    "threshold": 0.5,
    "preserve_recent": 6,
    "trim_head_chars": 300,
    "max_state_tokens": 25000,
    "max_request_tokens": 30000,
    "min_reduction_ratio": 0.25,
}


def _text_of_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(part for part in parts if part)


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)[:20000] if content else ""
    parts = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif block.get("type") == "image":
                parts.append("[image]")
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


def from_claude_code(path: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Claude Code JSONL → the SessionMessage shape the hook receives."""
    messages: list[dict[str, Any]] = []
    stats = {"records": 0, "text_blocks": 0, "thinking_blocks": 0, "tool_uses": 0, "tool_results": 0}
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    for file in files:
        for line in file.open(encoding="utf-8", errors="replace"):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") not in ("user", "assistant"):
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            stats["records"] += 1
            text_parts: list[str] = []
            calls: list[dict[str, Any]] = []
            results: list[dict[str, Any]] = []
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                kind = block.get("type")
                if kind == "text":
                    stats["text_blocks"] += 1
                    text_parts.append(str(block.get("text") or ""))
                elif kind == "thinking":
                    # Not part of SessionMessage: the engine hands hooks text and tool blocks.
                    stats["thinking_blocks"] += 1
                elif kind == "tool_use":
                    stats["tool_uses"] += 1
                    calls.append(
                        {
                            "tool_use_id": str(block.get("id")),
                            "tool": str(block.get("name")),
                            "input": block.get("input") if isinstance(block.get("input"), dict) else {},
                        }
                    )
                elif kind == "tool_result":
                    stats["tool_results"] += 1
                    results.append(
                        {
                            "tool_use_id": str(block.get("tool_use_id")),
                            "text": _tool_result_text(block.get("content")),
                        }
                    )
            entry: dict[str, Any] = {"role": message.get("role") or record.get("type"), "text": "\n".join(text_parts)}
            if calls:
                entry["toolUses"] = calls
            if results:
                entry["toolResults"] = results
            if entry["text"].strip() or calls or results:
                messages.append(entry)
    return messages, stats


def from_hermes(session: str, db: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Hermes conversation store → the same shape (assistant calls, user-carried results)."""
    db = db or Path.home() / ".hermes" / "state.db"
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if session == "latest":
            row = connection.execute(
                "select session_id from messages where role in ('user','assistant') "
                "order by timestamp desc limit 1"
            ).fetchone()
            if not row:
                raise SystemExit("no messages in the Hermes store")
            session = str(row[0])
        rows = connection.execute(
            "select role, content, tool_call_id, tool_calls from messages "
            "where session_id = ? order by id",
            (session,),
        ).fetchall()
    finally:
        connection.close()

    messages: list[dict[str, Any]] = []
    stats = {"records": len(rows), "text_blocks": 0, "thinking_blocks": 0, "tool_uses": 0, "tool_results": 0}
    pending_results: list[dict[str, Any]] = []

    def flush_results() -> None:
        if pending_results:
            messages.append({"role": "user", "text": "", "toolResults": list(pending_results)})
            pending_results.clear()

    for role, content, tool_call_id, tool_calls in rows:
        if role == "user":
            flush_results()
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            if text.strip():
                stats["text_blocks"] += 1
                messages.append({"role": "user", "text": text})
        elif role == "assistant":
            flush_results()
            calls: list[dict[str, Any]] = []
            for call in json.loads(tool_calls) if tool_calls else []:
                function = call.get("function") or {}
                raw_args = function.get("arguments")
                try:
                    parsed = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    parsed = {"raw": str(raw_args)[:500]}
                stats["tool_uses"] += 1
                calls.append(
                    {
                        "tool_use_id": str(call.get("id") or call.get("call_id")),
                        "tool": str(function.get("name") or "tool"),
                        "input": parsed if isinstance(parsed, dict) else {"value": parsed},
                    }
                )
            text = content if isinstance(content, str) else ""
            entry: dict[str, Any] = {"role": "assistant", "text": text or "", "toolUses": calls}
            if text.strip() or calls:
                if text.strip():
                    stats["text_blocks"] += 1
                messages.append(entry)
        elif role == "tool":
            stats["tool_results"] += 1
            payload = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            pending_results.append({"tool_use_id": str(tool_call_id or ""), "text": payload})
    flush_results()
    return messages, stats


def drop_orphan_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A result whose call is absent from the same transcript is not part of a pair."""
    known = {call["tool_use_id"] for message in messages for call in message.get("toolUses") or []}
    cleaned = []
    for message in messages:
        entry = dict(message)
        results = [r for r in (entry.get("toolResults") or []) if r["tool_use_id"] in known]
        if results:
            entry["toolResults"] = results
        else:
            entry.pop("toolResults", None)
        cleaned.append(entry)
    return cleaned


def _normalise(text: str) -> str:
    return " ".join(text.split())


def flatten(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        parts.append(str(message.get("text") or ""))
        for call in message.get("toolUses") or []:
            parts.append(f"{call.get('tool_use_id')} {call.get('tool')} {json.dumps(call.get('input'), sort_keys=True, default=str)}")
        for result in message.get("toolResults") or []:
            parts.append(str(result.get("text") or ""))
    return "\n".join(parts)


def count(text: str) -> tuple[int, str]:
    from lcc.token_budget import count_tokens

    counted = count_tokens(text, "gpt-4.1")
    return int(counted.value), counted.method.value


def ledger_tail(offset: int) -> dict[str, int] | None:
    from lcc.relevance.jev import default_ledger_path

    path = default_ledger_path()
    if path is None or not path.is_file():
        return None
    totals = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    for line in path.read_bytes()[offset:].decode("utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("status") != "ok":
            continue
        totals["calls"] += 1
        totals["input_tokens"] += int(entry.get("input_tokens") or 0)
        totals["output_tokens"] += int(entry.get("output_tokens") or 0)
    return totals


def _did_not_run(
    label: str,
    messages: list[dict[str, Any]],
    tokens_before: int,
    method: str,
    started: float,
    error: str,
    kind: str,
) -> dict[str, Any]:
    """The compaction did not produce a transcript: that is the finding, not a crash."""
    return {
        "label": label,
        "messages": len(messages),
        "tool_calls": sum(len(message.get("toolUses") or []) for message in messages),
        "tokens_before": tokens_before,
        "token_count_method": method,
        "compacted": False,
        "error": error,
        "error_kind": kind,
        "hook_would_replace": False,
        "hook_reason": f"compaction did not run ({'the state did not fit' if kind == 'fit' else kind})",
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def measure(messages: list[dict[str, Any]], label: str, options: dict[str, Any]) -> dict[str, Any]:
    from lcc.relevance.jev import default_ledger_path
    from lcc.relevance.transcript import (
        TranscriptCompactionRequest,
        TranscriptFitError,
        compact_transcript,
        messages_to_payload,
    )

    originals = {
        result["tool_use_id"]: result["text"]
        for message in messages
        for result in message.get("toolResults") or []
    }
    original_texts = [message["text"] for message in messages if message.get("text")]
    before_text = flatten(messages)
    tokens_before, method = count(before_text)
    ledger_path = default_ledger_path()
    offset = len(ledger_path.read_bytes()) if ledger_path and ledger_path.is_file() else 0

    started = time.perf_counter()
    try:
        result = compact_transcript(
            TranscriptCompactionRequest(
                payload={"messages": messages},
                question=options["question"],
                provider="jev",
                threshold=options["threshold"],
                preserve_recent=options["preserve_recent"],
                trim_head_chars=options["trim_head_chars"],
                max_state_tokens=options["max_state_tokens"],
                max_request_tokens=options["max_request_tokens"],
            )
        )
    except TranscriptFitError as error:  # the fit failure IS a finding: the hook stands down
        return _did_not_run(label, messages, tokens_before, method, started, str(error), "fit")
    except Exception as error:  # noqa: BLE001 - report the real failure rather than hiding it
        return _did_not_run(label, messages, tokens_before, method, started, str(error), type(error).__name__)

    emitted = messages_to_payload(result.messages)
    after_text = flatten(emitted)
    tokens_after, _ = count(after_text)
    report = result.report

    present_calls = {c["tool_use_id"] for m in emitted for c in m.get("toolUses") or []}
    present_results = {r["tool_use_id"]: r["text"] for m in emitted for r in m.get("toolResults") or []}
    outcomes = {"kept": 0, "trimmed": 0, "dropped": 0}
    for call_id in originals:
        if call_id not in present_calls:
            outcomes["dropped"] += 1
        elif _normalise(present_results.get(call_id, "")) == _normalise(originals[call_id]):
            outcomes["kept"] += 1
        else:
            outcomes["trimmed"] += 1

    normalised_after = _normalise(after_text)
    lost_texts = [t for t in original_texts if _normalise(t) not in normalised_after]
    ratio = 0.0 if tokens_before == 0 else max(0.0, 1 - tokens_after / tokens_before)
    replace = bool(report["degraded"] is False and ratio >= options["min_reduction_ratio"] and emitted)

    return {
        "label": label,
        "messages": len(messages),
        "tool_calls": sum(len(m.get("toolUses") or []) for m in messages),
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "reduction": round(ratio, 4),
        "token_count_method": method,
        "messages_after": len(emitted),
        "outcomes": outcomes,
        "outcome_source": report["decisions"] and {
            k: sum(1 for d in report["decisions"] if d["decision"] == k) for k in ("keep", "trim", "drop")
        },
        "texts_checked": len(original_texts),
        "texts_lost": lost_texts[:3],
        "compacted": True,
        "state_tokens": report["state_tokens"],
        "state_fit_stage": report["state_fit_stage"],
        "requests": report["requests"],
        "calls": report["calls"],
        "semantic_guarantee": report["semantic_guarantee"],
        "degraded": report["degraded"],
        "jev_model_resolved": report["jev_model_resolved"],
        "hook_would_replace": replace,
        "hook_reason": f"judged pass, {ratio:.1%} removed"
        if replace
        else f"below the {options['min_reduction_ratio']:.0%} minimum, degraded, or empty",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "ledger": ledger_tail(offset),
    }


def window(messages: list[dict[str, Any]], keep: int) -> list[dict[str, Any]]:
    if keep <= 0 or keep >= len(messages):
        return messages
    return messages[-keep:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--claude-code", type=Path)
    source.add_argument("--hermes")
    parser.add_argument("--question", default="finish the task in this session")
    parser.add_argument("--window-messages", type=int, default=0, help="measure only the newest N messages")
    parser.add_argument("--max-state-tokens", type=int, default=DEFAULT_OPTIONS["max_state_tokens"])
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    if args.claude_code:
        messages, stats = from_claude_code(args.claude_code)
        label = args.label or f"claude-code:{args.claude_code.parent.name}/{args.claude_code.name}"
    else:
        messages, stats = from_hermes(args.hermes)
        label = args.label or f"hermes:{args.hermes}"
    messages = drop_orphan_results(messages)
    total_messages = len(messages)

    options = dict(DEFAULT_OPTIONS)
    options["question"] = args.question
    options["max_state_tokens"] = args.max_state_tokens

    rows = []
    full = measure(messages, f"{label} (full)", options)
    rows.append(full)
    if args.window_messages and total_messages > args.window_messages:
        rows.append(measure(window(messages, args.window_messages), f"{label} (newest {args.window_messages} messages)", options))

    print(f"source: {label}")
    print(f"records: {stats}")
    print(f"messages kept: {total_messages}")
    for row in rows:
        print(f"\n{row['label']}")
        print(f"  messages {row['messages']} | tool calls {row['tool_calls']}")
        print(f"  tokens {row['tokens_before']} -> {row.get('tokens_after', '-')} (reduction {row.get('reduction', 0):.1%})")
        print(f"  compacted: {row['compacted']}" + (f" | {row.get('error_kind')}: {row.get('error', '')[:120]}" if not row["compacted"] else ""))
        if row["compacted"]:
            print(f"  pairs kept/trimmed/dropped: {row['outcomes']}")
            print(f"  user+assistant texts preserved: {row['texts_checked'] - len(row['texts_lost'])}/{row['texts_checked']}")
            print(f"  state {row['state_tokens']} tokens, fit '{row['state_fit_stage']}', {row['requests']} request(s), guarantee {row['semantic_guarantee']}, degraded {row['degraded']}")
            print(f"  ledger: {row['ledger']}")
        print(f"  plugin would replace the transcript: {row['hook_would_replace']} ({row['hook_reason']})")
        print(f"  latency {row['latency_ms']} ms")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H%M%SZ")
    slug = "_".join(label.replace("/", "-").replace(":", "-").split())[:50]
    # The run id is in the filename: a session that is still being written (every live one) must
    # not overwrite the artifact a document quotes.
    out = RESULTS_DIR / f"real_session_{stamp}_{slug}.json"
    out.write_text(
        json.dumps({"run_id": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "options": options, "source_stats": stats, "rows": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
