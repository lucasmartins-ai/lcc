"""Minimal MCP (Model Context Protocol) stdio server for `lcc` (Etapa 5 MVP).

Exposes the local-first capabilities to MCP-capable agents over JSON-RPC 2.0
on stdio (newline-delimited JSON per the MCP spec; LSP-style ``Content-Length``
framing is also accepted):

- ``compact`` — relevance compaction (default ``mechanical``: offline, no key)
- ``compact_transcript`` — tool-call compaction of a session transcript (pairs tool calls with
  their results and drops the pairs Jev no longer needs; needs a semantic judge)
- ``inspect`` — read-only diagnostic inspection (offline)
- ``prepare`` — inspect-first deterministic prompt preparation (offline)
- ``explain`` — audit a compaction report (offline, never re-runs)
- ``intake`` — prompt intake triage + compilation (offline by default)
- ``recall`` — return an output ``rules_mode="stashed"`` removed, hash-verified (offline)

Stdlib only: no new dependencies, nothing added to the installed base package
requirements. The deterministic core boundary is unchanged — this module only
*calls* the same public library entry points as the CLI.

Run: ``lcc mcp`` (stdio) or ``python -m lcc.mcp_server``.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from lcc import __version__

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "lcc"

__all__ = ["PROTOCOL_VERSION", "TOOLS", "ToolInputError", "handle_message", "serve_forever"]

LOGGER = logging.getLogger("lcc.mcp")


class ToolInputError(ValueError):
    """A tool argument the handler rejected on purpose; its text is safe to show any caller."""


def _number(args: dict[str, Any], key: str, default: float, kind: type = float) -> Any:
    """``args[key]`` as ``kind``; a fixed message, never the conversion's own text."""
    try:
        return kind(args.get(key, default))
    except (TypeError, ValueError, OverflowError):  # OverflowError: int(Infinity)
        raise ToolInputError(f"{key!r} must be a number") from None


def _tool_compact(args: dict[str, Any]) -> dict[str, Any]:
    from lcc.relevance import (
        RelevanceCompactionRequest,
        compact_context,
        report_to_dict,
    )

    text = args.get("text", "")
    question = args.get("question", "")
    if not isinstance(text, str) or not text.strip():
        raise ToolInputError("compact requires non-empty 'text'")
    if not isinstance(question, str) or not question.strip():
        raise ToolInputError("compact requires non-empty 'question'")
    provider = args.get("provider", "mechanical")
    if provider not in ("auto", "jev", "laya", "mechanical"):
        raise ToolInputError("provider must be auto, jev, laya, or mechanical")
    threshold = _number(args, "threshold", 0.4)
    if not 0.0 <= threshold <= 1.0:
        raise ToolInputError("threshold must be between 0 and 1")
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
        parse_transcript,
    )

    payload = args.get("messages") if "messages" in args else args.get("payload")
    if not isinstance(payload, (list, dict)) or not payload:
        raise ToolInputError(
            "compact_transcript requires 'messages' (a list or {'messages': [...]})"
        )
    question = args.get("question", "")
    if not isinstance(question, str) or not question.strip():
        raise ToolInputError("compact_transcript requires non-empty 'question'")
    provider = args.get("provider", "auto")
    if provider not in ("auto", "jev", "laya", "rules", "specialist-v3"):
        raise ToolInputError(
            "compact_transcript needs a semantic judge or the rules policy: use 'laya' "
            "(local, offline), 'jev', 'auto', 'rules' (offline deterministic policy) or "
            "'specialist-v3' (offline local ranker) — "
            "'mechanical' scores lexical overlap, which cannot say whether a tool's work "
            "is finished"
        )
    threshold = _number(args, "threshold", 0.5)
    if not 0.0 <= threshold <= 1.0:
        raise ToolInputError("threshold must be between 0 and 1")
    preserve_recent = _number(args, "preserve_recent", 6, int)
    trim_head_chars = _number(args, "trim_head_chars", 300, int)
    if preserve_recent < 0 or trim_head_chars < 0:
        raise ToolInputError("preserve_recent and trim_head_chars must be >= 0")
    request_payload = payload if isinstance(payload, dict) else {"messages": payload}
    result = compact_transcript(
        TranscriptCompactionRequest(
            payload=request_payload,
            question=question,
            provider=provider,
            threshold=threshold,
            preserve_recent=preserve_recent,
            trim_head_chars=trim_head_chars,
            max_state_tokens=_number(args, "max_state_tokens", 25000, int),
            max_request_tokens=_number(args, "max_request_tokens", 30000, int),
            max_workers=_number(args, "max_workers", 4, int),
            min_reduction=_number(args, "min_reduction", 0.25),
            laya_model=args.get("laya_model"),
            jev_model=str(args.get("jev_model", "jev-latest")),
            rules_mode=str(args.get("rules_mode", "lossless")),
            workspace_root=args.get("workspace_root") or None,
            disk_check=bool(args.get("disk_check", True)),
            allow_command_pointers=args.get("allow_command_pointers") is True,
            cache_state=_cache_state_arg(args.get("cache_state")),
        )
    )
    if args.get("ref_unchanged") is True or args.get("ref_blocks") is True:
        # Compact answer for callers whose transport caps the result (Claude Code's
        # $.mcp.call goes through MAX_MCP_OUTPUT_TOKENS): a message that left the pass
        # unchanged comes back as {"ref": <input index>}, and per-call decisions stay out.
        source = messages_to_payload(parse_transcript(request_payload))
        report = {key: value for key, value in result.report.items() if key != "decisions"}
        if args.get("ref_blocks") is True:
            indices = [message.message_index for message in result.messages]
            compacted = _ref_blocks(source, messages_to_payload(result.messages), indices)
        else:
            compacted = _ref_unchanged(source, messages_to_payload(result.messages))
        return {"messages": compacted, "report": report}
    return {
        "messages": messages_to_payload(result.messages),
        "decisions": result.decisions,
        "report": result.report,
    }


def _ref_unchanged(
    source: list[dict[str, Any]], compacted: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Replace each compacted message equal to the next unmatched source message by a ref.

    Kept messages are verbatim and in order, so one forward scan finds them; anything else
    (a trimmed, replaced or new message) is sent whole. Duplicate messages map in order.
    """
    positions: dict[str, list[int]] = {}
    for position, entry in enumerate(source):
        positions.setdefault(json.dumps(entry, sort_keys=True), []).append(position)
    out: list[dict[str, Any]] = []
    cursor = 0
    for message in compacted:
        candidates = positions.get(json.dumps(message, sort_keys=True), [])
        index = next((i for i in candidates if i >= cursor), None)
        if index is None:
            out.append(message)
        else:
            out.append({"ref": index})
            cursor = index + 1
    return out


def _utf16_len(text: str) -> int:
    """Length in UTF-16 code units: what a JavaScript caller's ``slice`` counts."""
    return len(text.encode("utf-16-le")) // 2


def _splice(old: str, new: str) -> dict[str, Any]:
    """``new`` as ``old[:head] + text + old[-tail:]``, head and tail in UTF-16 units.

    A trimmed result keeps the original's first characters, so only the note travels.
    """
    head = 0
    limit = min(len(old), len(new))
    while head < limit and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < limit - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    patch: dict[str, Any] = {"text": new[head : len(new) - tail]}
    if head:
        patch["head"] = _utf16_len(old[:head])
    if tail:
        patch["tail"] = _utf16_len(old[len(old) - tail :])
    return patch


def _block_patch(original: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    """A changed message as indices into ``original``'s blocks; None when it cannot be one.

    The pass never edits text or a tool call, it only removes calls and replaces results:
    ``toolUses`` lists the kept calls' indices, ``toolResults`` a kept result's index or
    ``{"ref": index, "text", "head"?, "tail"?}`` for a replaced one.
    """
    if message.get("role") != original.get("role") or message.get("text") != original.get(
        "text"
    ):
        return None
    uses_before = original.get("toolUses", [])
    uses: list[int] = []
    for use in message.get("toolUses", []):
        index = next(
            (i for i in range(uses[-1] + 1 if uses else 0, len(uses_before))
             if uses_before[i] == use),
            None,
        )
        if index is None:
            return None
        uses.append(index)
    results_before = original.get("toolResults", [])
    results: list[Any] = []
    cursor = 0
    for result in message.get("toolResults", []):
        index = next(
            (i for i in range(cursor, len(results_before))
             if results_before[i]["tool_use_id"] == result["tool_use_id"]),
            None,
        )
        if index is None or results_before[index].get("is_error") != result.get("is_error"):
            return None
        cursor = index + 1
        before = results_before[index]
        results.append(
            index if before == result
            else {"ref": index, "tool_use_id": result["tool_use_id"]}
            | _splice(before["text"], result["text"])
        )
    return {"toolUses": uses, "toolResults": results}


def _ref_blocks(
    source: list[dict[str, Any]], compacted: list[dict[str, Any]], indices: list[int]
) -> list[dict[str, Any]]:
    """``ref_blocks``: refs down to the block, so the answer carries only what is new.

    ``indices[i]`` is the input position ``compacted[i]`` came from. An unchanged message is
    ``{"ref": i}``; a changed one is ``{"ref": i, "toolUses": [...], "toolResults": [...]}``
    (see :func:`_block_patch`); one that cannot be patched is sent whole.
    """
    out: list[dict[str, Any]] = []
    for index, message in zip(indices, compacted, strict=True):
        original = source[index]
        if message == original:
            out.append({"ref": index})
            continue
        patch = _block_patch(original, message)
        out.append(message if patch is None else {"ref": index} | patch)
    return out


def _tool_inspect(args: dict[str, Any]) -> dict[str, Any]:
    import json as _json

    from lcc.inspection import InspectionRequest
    from lcc.inspection import inspect as run_inspection
    from lcc.inspection.report import inspection_to_json

    text = args.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise ToolInputError("inspect requires non-empty 'text'")
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
        raise ToolInputError("prepare requires non-empty 'text'")
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
        try:
            report = json.loads(report)
        except ValueError:
            raise ToolInputError("'report' must be a JSON object") from None
    if not isinstance(report, dict) or "decisions" not in report:
        raise ToolInputError("explain requires a 'report' compaction-report object")
    only = args.get("only")
    limit = args.get("limit")
    if limit is not None:
        limit = _number(args, "limit", 0, int)
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
        raise ToolInputError("intake requires non-empty 'text'")
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


def _tool_recall(args: dict[str, Any]) -> dict[str, Any]:
    from lcc.relevance.transcript_stash import parse_lines, recall, recall_sha256

    stash_id = args.get("id", "")
    if not isinstance(stash_id, str):
        raise ToolInputError("recall requires 'id' (the hex id after 'lcc recall' in the pointer)")
    lines = args.get("lines")
    span = parse_lines(lines) if isinstance(lines, str) and lines else None
    return {"sha256": recall_sha256(stash_id), "text": recall(stash_id, span)}


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
            "Default 'auto' is the local specialist-v3 ranker (offline, no key); 'jev' is "
            "remote and needs TYPESAFE_API_KEY. Every failure keeps the call."
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
                "provider": {
                    "type": "string",
                    "enum": ["jev", "laya", "auto", "rules", "specialist-v3"],
                    "default": "auto",
                    "description": (
                        "'auto' (default) and 'specialist-v3' use the local CPU ranker "
                        "(no key, no network; ranks, does not judge). 'jev' is the remote "
                        "TypeSafe System 1, needs TYPESAFE_API_KEY, and runs only when "
                        "named. 'laya' is DEPRECATED (local, needs the [laya] extra) and "
                        "runs only when named. 'rules' is an offline deterministic policy "
                        "(no key, no model); see rules_mode."
                    ),
                },
                "rules_mode": {
                    "type": "string",
                    "enum": ["lossless", "lossy", "recoverable", "stashed"],
                    "default": "lossless",
                    "description": (
                        "Only for provider 'rules'. 'lossless' replaces a tool result with a "
                        "pointer only when its text is kept verbatim in a later result, and "
                        "verifies it. 'recoverable' also replaces old file reads (of files "
                        "not written later) and read-only allowlisted command outputs with "
                        "a re-read/re-run pointer, and verifies it. 'stashed' removes what "
                        "'lossy' drops or trims and 'recoverable' replaces, after saving the "
                        "exact bytes to a local stash; the pointer names a 'recall' id. "
                        "'lossy' is EXPERIMENTAL (trims and drops outputs; failed blind "
                        "audits v0.4 and v0.5)."
                    ),
                },
                "workspace_root": {
                    "type": "string",
                    "description": (
                        "rules_mode 'recoverable' only: the session's working directory. "
                        "When set (and disk_check on), the disk decides file pointers: a "
                        "read is replaced iff the file inside it (or its own directory) "
                        "currently holds exactly the removed content, even after later writes."
                    ),
                },
                "disk_check": {"type": "boolean", "default": True},
                "allow_command_pointers": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "rules_mode 'recoverable' only: also replace allowlisted read-only "
                        "command outputs with a re-run pointer. Off by default."
                    ),
                },
                "threshold": {"type": "number", "default": 0.5},
                "preserve_recent": {"type": "integer", "default": 6},
                "trim_head_chars": {"type": "integer", "default": 300},
                "max_state_tokens": {"type": "integer", "default": 25000},
                "max_request_tokens": {"type": "integer", "default": 30000},
                "max_workers": {"type": "integer", "default": 4},
                "min_reduction": {"type": "number", "default": 0.25},
                "ref_unchanged": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Return each message the pass left unchanged as {'ref': <input "
                        "index>} and leave per-call decisions out, for size-capped callers."
                    ),
                },
                "ref_blocks": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "ref_unchanged down to the block: a changed message comes back as "
                        "{'ref': <input index>, 'toolUses': [<kept call index>...], "
                        "'toolResults': [<kept result index> | {'ref', 'tool_use_id', "
                        "'text', 'head'?, 'tail'?}...]}, a replaced result being "
                        "original[:head] + text + original[-tail:] (UTF-16 units)."
                    ),
                },
                "trigger": {
                    "type": "string",
                    "enum": ["idle"],
                    "description": "Request-log label only: 'idle' for the plugin's idle stash.",
                },
                "cache_state": {
                    "type": "string",
                    "enum": ["warm", "cold", "unknown"],
                    "default": "unknown",
                    "description": (
                        "Provider prompt-cache state for the report's cache_effect "
                        "(unknown is priced as warm). The idle stash sends 'cold'."
                    ),
                },
                "idle_gap_bucket": {
                    "type": "string",
                    "description": "Request-log label only: the idle gap bucket, e.g. '1h-2h'.",
                },
                "jev_model": {"type": "string", "default": "jev-latest"},
                "laya_model": {"type": "string"},
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
    "recall": {
        "handler": _tool_recall,
        "description": (
            "Return a tool output that compact_transcript (rules_mode 'stashed') replaced "
            "with '[removed: N tokens · lcc recall <id>]'. The bytes are re-hashed on read, "
            "so the text is exactly what was removed. Offline, local stash only."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "The hex id from the pointer."},
                "lines": {"type": "string", "description": "Optional 1-based range 'a-b'."},
            },
            "required": ["id"],
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


def _cache_state_arg(value: Any) -> str:
    state = str(value or "unknown")
    if state not in ("warm", "cold", "unknown"):
        raise ToolInputError(f"cache_state must be warm, cold or unknown, got {state!r}")
    return state


def handle_message(
    message: dict[str, Any], *, echo_errors: bool = True
) -> dict[str, Any] | None:
    """Handle one JSON-RPC message; return the response, or None for notifications.

    ``echo_errors=False`` (HTTP) shows only ``ToolInputError`` text; any other failure
    answers with its type and is logged, since its text may carry a server path.
    """
    if not isinstance(message, dict):  # batches are not supported by MCP
        return _error(None, -32600, "invalid request: expected a JSON object")
    method = message.get("method", "")
    request_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(request_id, -32602, "invalid params: expected an object")

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
        if not isinstance(arguments, dict):
            return _error(request_id, -32602, "invalid params: 'arguments' must be an object")
        spec = TOOLS.get(name)
        if spec is None:
            return _error(request_id, -32602, f"unknown tool {name!r}")
        try:
            output = spec["handler"](arguments)
        except (ValueError, KeyError, TypeError) as exc:
            if echo_errors or isinstance(exc, ToolInputError):
                text = f"error: {exc}"
            else:
                # Bad input is the caller's; a traceback is only worth it for a likely bug.
                log = LOGGER.warning if isinstance(exc, ValueError) else LOGGER.exception
                log("tool %s failed: %s", name, type(exc).__name__)
                text = f"error: tool call failed ({type(exc).__name__})"
            return _result(request_id, {"content": [{"type": "text", "text": text}],
                                        "isError": True})
        # Opt-in (LCC_REQUEST_LOG=1): logs the redacted goal only, after the output exists.
        from lcc.request_log import log_request

        # compact_transcript also records which provider ran and why it degraded (fixed
        # labels from the report, never content), so the hook's choice is visible in the log.
        report = output.get("report") if name == "compact_transcript" else None
        extra = (
            {
                "provider": report.get("provider_used"),
                "degradation_reason": report.get("degradation_reason"),
            }
            if isinstance(report, dict)
            else {}
        )
        # The plugin's idle stash labels its passes: fixed labels and a count, never content.
        if isinstance(report, dict) and arguments.get("trigger") == "idle":
            removed = (report.get("tokens_before") or 0) - (report.get("tokens_after") or 0)
            extra.update(
                trigger="idle",
                gap_bucket=str(arguments.get("idle_gap_bucket") or "unknown")[:16],
                removed_tokens=max(0, int(removed)),
            )
        log_request(
            arguments.get("question"),
            tool=f"mcp:{name}",
            field=arguments.get("field"),
            language=arguments.get("language"),
            **extra,
        )
        return _result(
            request_id, {"content": [{"type": "text", "text": json.dumps(output)}]}
        )
    if method.startswith("notifications/"):
        return None
    if request_id is None:
        return None
    return _error(request_id, -32601, f"method not found: {method!r}")


def _read_message(buffer: Any) -> tuple[dict[str, Any] | None, bool]:
    """Read one message; return (message, ndjson). Message is None on clean EOF.

    MCP stdio is newline-delimited JSON (what Claude Code, Codex, Cursor send).
    LSP ``Content-Length`` framing is still accepted for older clients.
    """
    headers: dict[str, str] = {}
    while True:
        line = buffer.readline()
        if not line:
            return None, False
        line = line.strip()
        if not line:
            if headers:
                break
            continue
        if not headers and line.startswith((b"{", b"[")):
            return json.loads(line.decode("utf-8")), True
        name, _, value = line.decode("utf-8", "replace").partition(":")
        headers[name.strip().lower()] = value.strip()
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        return None, False
    if length <= 0:
        return None, False
    body = buffer.read(length)
    if not body:
        return None, False
    return json.loads(body.decode("utf-8")), False


def _write_message(buffer: Any, payload: dict[str, Any], ndjson: bool = True) -> None:
    body = json.dumps(payload).encode("utf-8")
    if ndjson:
        buffer.write(body + b"\n")
    else:
        buffer.write(b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    buffer.flush()


def serve_forever() -> None:
    """Serve MCP over stdio until EOF."""
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    ndjson = True
    while True:
        try:
            message, ndjson = _read_message(stdin)
        except OSError:
            break
        except (ValueError, RecursionError):  # bad or too-deeply-nested JSON: answer, keep serving
            response: dict[str, Any] | None = _error(None, -32700, "parse error")
        else:
            if message is None:
                break
            try:
                response = handle_message(message)
            except Exception as exc:  # never kill the server on a bad message
                response = _error(message.get("id"), -32603, f"internal error: {exc}")
        if response is not None:
            try:
                _write_message(stdout, response, ndjson)
            except OSError:
                break


if __name__ == "__main__":
    serve_forever()
