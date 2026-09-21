"""Minimal MCP (Model Context Protocol) stdio server for `lcc` (Etapa 5 MVP).

Exposes the local-first capabilities to MCP-capable agents over JSON-RPC 2.0
on stdio (LSP-style ``Content-Length`` framing):

- ``compact`` — relevance compaction (default ``mechanical``: offline, no key)
- ``compact_transcript`` — tool-call compaction of a session transcript (pairs tool calls with
  their results and drops the pairs Jev no longer needs; needs a semantic judge)
- ``inspect`` — read-only diagnostic inspection (offline)
- ``prepare`` — inspect-first deterministic prompt preparation (offline)
- ``explain`` — audit a compaction report (offline, never re-runs)
- ``intake`` — prompt intake triage + compilation (offline by default)

Stdlib only: no new dependencies, nothing added to the installed base package
requirements. The deterministic core boundary is unchanged — this module only
*calls* the same public library entry points as the CLI.

Run: ``lcc mcp`` (stdio) or ``python -m lcc.mcp_server``.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from lcc import __version__

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "lcc"

__all__ = ["PROTOCOL_VERSION", "TOOLS", "handle_message", "serve_forever"]


def _tool_compact(args: dict[str, Any]) -> dict[str, Any]:
    from lcc.relevance import (
        RelevanceCompactionRequest,
        compact_context,
        report_to_dict,
    )

    text = args.get("text", "")
    question = args.get("question", "")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("compact requires non-empty 'text'")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("compact requires non-empty 'question'")
    provider = args.get("provider", "mechanical")
    if provider not in ("auto", "jev", "laya", "mechanical"):
        raise ValueError("provider must be auto, jev, laya, or mechanical")
    threshold = float(args.get("threshold", 0.4))
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    result = compact_context(
        RelevanceCompactionRequest(
            text=text,
            question=question,
            provider=provider,
            threshold=threshold,
        )
    )
    return {"compacted_text": result.compacted_text, "report": report_to_dict(result.report)}


def _tool_compact_transcript(args: dict[str, Any]) -> dict[str, Any]:
    from lcc.relevance.transcript import (
        TranscriptCompactionRequest,
        compact_transcript,
        messages_to_payload,
    )

    payload = args.get("messages") if "messages" in args else args.get("payload")
    if not isinstance(payload, (list, dict)) or not payload:
        raise ValueError("compact_transcript requires 'messages' (a list or {'messages': [...]})")
    question = args.get("question", "")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("compact_transcript requires non-empty 'question'")
    provider = args.get("provider", "jev")
    if provider not in ("auto", "jev"):
        raise ValueError(
            "compact_transcript needs a semantic judge: use 'jev' or 'auto' "
            "(mechanical and laya cannot judge tool-call relevance)"
        )
    threshold = float(args.get("threshold", 0.5))
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    preserve_recent = int(args.get("preserve_recent", 6))
    trim_head_chars = int(args.get("trim_head_chars", 300))
    if preserve_recent < 0 or trim_head_chars < 0:
        raise ValueError("preserve_recent and trim_head_chars must be >= 0")
    result = compact_transcript(
        TranscriptCompactionRequest(
            payload=payload if isinstance(payload, dict) else {"messages": payload},
            question=question,
            provider=provider,
            threshold=threshold,
            preserve_recent=preserve_recent,
            trim_head_chars=trim_head_chars,
            max_state_tokens=int(args.get("max_state_tokens", 25000)),
            max_request_tokens=int(args.get("max_request_tokens", 30000)),
            max_workers=int(args.get("max_workers", 4)),
            min_reduction=float(args.get("min_reduction", 0.25)),
            jev_model=str(args.get("jev_model", "jev-latest")),
        )
    )
    return {
        "messages": messages_to_payload(result.messages),
        "decisions": result.decisions,
        "report": result.report,
    }


def _tool_inspect(args: dict[str, Any]) -> dict[str, Any]:
    import json as _json

    from lcc.inspection import InspectionRequest
    from lcc.inspection import inspect as run_inspection
    from lcc.inspection.report import inspection_to_json

    text = args.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("inspect requires non-empty 'text'")
    report = run_inspection(InspectionRequest(raw_text=text))
    return {"report": _json.loads(inspection_to_json(report))}


def _tool_prepare(args: dict[str, Any]) -> dict[str, Any]:
    import dataclasses

    from lcc.inspection import InspectionRequest
    from lcc.inspection import inspect as run_inspection
    from lcc.lexical_selection import select_chunks_for_question
    from lcc.pipeline import OptimizationRequest
    from lcc.pipeline import optimize as run_pipeline
    from lcc.reporting.report import report_to_dict as optimization_report_to_dict

    text = args.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("prepare requires non-empty 'text'")
    question = args.get("question", "") or ""
    inspection_report = run_inspection(InspectionRequest(raw_text=text))
    action = inspection_report.recommendation.action
    if action not in ("optimize_safe", "optimize_with_flags"):
        return {
            "action": action,
            "prompt": None,
            "note": "inspection did not recommend optimization; no prompt generated",
        }
    selection = select_chunks_for_question(
        raw_text=text,
        question=question,
        chunk_inventory=inspection_report.chunk_inventory,
    )
    result = run_pipeline(
        OptimizationRequest(raw_text=selection.selected_text, question=question)
    )
    return {
        "action": action,
        "prompt": result.prompt,
        "lexical_selection": dataclasses.asdict(selection.report),
        "report": optimization_report_to_dict(result.report),
    }


def _tool_explain(args: dict[str, Any]) -> dict[str, Any]:
    from lcc.reporting.explain import render

    report = args.get("report")
    if isinstance(report, str):
        report = json.loads(report)
    if not isinstance(report, dict) or "decisions" not in report:
        raise ValueError("explain requires a 'report' compaction-report object")
    only = args.get("only")
    limit = args.get("limit")
    if limit is not None:
        limit = int(limit)
    return {
        "explanation": render(
            report,
            only=only,
            limit=limit,
            source_text=args.get("source_text"),
        )
    }


def _tool_intake(args: dict[str, Any]) -> dict[str, Any]:
    from lcc.intake import LccIntake

    text = args.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("intake requires non-empty 'text'")
    question = args.get("question", "") or ""
    result = LccIntake().process(raw_input=text, question=question)
    return {
        "readiness": result.parsed.readiness.value,
        "readiness_score": result.parsed.readiness_score,
        "intent": result.parsed.intent,
        "questions": list(result.parsed.questions),
        "assumptions": list(result.parsed.assumptions),
        "formatted_prompt": result.formatted_prompt,
    }


TOOLS: dict[str, dict[str, Any]] = {
    "compact": {
        "handler": _tool_compact,
        "description": (
            "Drop context blocks irrelevant to an objective. Default provider "
            "mechanical is fully offline (no key, no network); laya is offline "
            "semantic (needs the [laya] extra, else honest mechanical fallback); "
            "jev needs TYPESAFE_API_KEY. Fail-safe: failures keep content."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "question": {"type": "string"},
                "provider": {
                    "type": "string",
                    "enum": ["auto", "jev", "laya", "mechanical"],
                    "default": "mechanical",
                },
                "threshold": {"type": "number", "default": 0.4},
            },
            "required": ["text", "question"],
        },
    },
    "compact_transcript": {
        "handler": _tool_compact_transcript,
        "description": (
            "Tool-call compaction for a session transcript: pairs each tool call with its "
            "result, pins the first and newest messages, and drops the pairs a semantic "
            "judge says are spent — kept messages stay verbatim, so nothing is summarized. "
            "Needs TYPESAFE_API_KEY (provider jev/auto); every failure keeps the call."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "description": (
                        "Messages with role/text and toolUses/toolResults blocks (Claude Code "
                        "hook shape) or tool_calls/tool_results."
                    ),
                    "items": {"type": "object"},
                },
                "question": {"type": "string"},
                "provider": {"type": "string", "enum": ["jev", "auto"], "default": "jev"},
                "threshold": {"type": "number", "default": 0.5},
                "preserve_recent": {"type": "integer", "default": 6},
                "trim_head_chars": {"type": "integer", "default": 300},
                "max_state_tokens": {"type": "integer", "default": 25000},
                "max_request_tokens": {"type": "integer", "default": 30000},
                "max_workers": {"type": "integer", "default": 4},
                "min_reduction": {"type": "number", "default": 0.25},
                "jev_model": {"type": "string", "default": "jev-latest"},
            },
            "required": ["messages", "question"],
        },
    },
    "inspect": {
        "handler": _tool_inspect,
        "description": (
            "Read-only diagnostic inspection of a text: tokens, structure, "
            "duplication, cleanup projection, and recommendation. Offline."
        ),
        "schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    "prepare": {
        "handler": _tool_prepare,
        "description": (
            "Inspect-first deterministic prompt preparation: runs inspection, "
            "then lexical selection + safe optimization only when recommended. "
            "Never summarizes or paraphrases. Offline."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "question": {"type": "string", "default": ""},
            },
            "required": ["text"],
        },
    },
    "explain": {
        "handler": _tool_explain,
        "description": (
            "Explain a relevance-compaction report (as produced by compact): "
            "why every block was kept, trimmed, or dropped. Never re-runs, "
            "never touches the network."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "report": {"type": "object"},
                "source_text": {"type": "string"},
                "only": {"type": "string", "enum": ["keep", "trim", "drop"]},
                "limit": {"type": "integer"},
            },
            "required": ["report"],
        },
    },
    "intake": {
        "handler": _tool_intake,
        "description": (
            "Intake triage for raw prompt input: readiness, intent, clarifying "
            "questions, assumptions, and a compiled prompt. Offline by default."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "question": {"type": "string", "default": ""},
            },
            "required": ["text"],
        },
    },
}


def _tools_list() -> list[dict[str, Any]]:
    return [
        {"name": name, "description": spec["description"], "inputSchema": spec["schema"]}
        for name, spec in TOOLS.items()
    ]


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC message; return the response, or None for notifications."""
    method = message.get("method", "")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": _tools_list()})
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        spec = TOOLS.get(name)
        if spec is None:
            return _error(request_id, -32602, f"unknown tool {name!r}")
        try:
            output = spec["handler"](arguments)
        except (ValueError, KeyError, TypeError) as exc:
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                },
            )
        return _result(
            request_id, {"content": [{"type": "text", "text": json.dumps(output)}]}
        )
    if method.startswith("notifications/"):
        return None
    if request_id is None:
        return None
    return _error(request_id, -32601, f"method not found: {method!r}")


def _read_message(buffer: Any) -> dict[str, Any] | None:
    """Read one LSP-framed message from a binary stream; None on clean EOF."""
    headers: dict[str, str] = {}
    while True:
        line = buffer.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        name, _, value = line.decode("utf-8", "replace").partition(":")
        headers[name.strip().lower()] = value.strip()
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        return None
    if length <= 0:
        return None
    body = buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(buffer: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    buffer.write(b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    buffer.flush()


def serve_forever() -> None:
    """Serve MCP over stdio until EOF."""
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    while True:
        try:
            message = _read_message(stdin)
        except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            break
        if message is None:
            break
        try:
            response = handle_message(message)
        except Exception as exc:  # never kill the server on a bad message
            response = _error(message.get("id"), -32603, f"internal error: {exc}")
        if response is not None:
            try:
                _write_message(stdout, response)
            except OSError:
                break


if __name__ == "__main__":
    serve_forever()
