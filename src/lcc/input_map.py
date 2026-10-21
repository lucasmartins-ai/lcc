"""`lcc measure-session --input-map`: where a session's input tokens go.

Reads a Claude Code session or Codex rollout (JSONL) locally and reports, **counts only**:

- **billed input**, from the provider's own usage records in the file (exact): uncached,
  cache-write and cache-read tokens, and their cost-weighted split;
- **category shares**, from a replay model: each transcript item (counted with lcc's
  tokenizer) is charged once per later request, until a compaction boundary. Claude Code
  files hold no system prompt or tool schemas, so their per-request size is estimated as the
  intercept of a least-squares fit of billed input on transcript size. Codex rollouts carry
  both, so they are counted directly;
- a **drill-down**: tokens by tool (results and inputs), by attachment type, re-reads and
  duplicate outputs.

The shares assume one tokenizer ratio across categories (the provider's tokenizer differs
from lcc's), so they rank categories; they are not exact percentages. The report says so.
No session text, file path or tool output is in the report; built-in tool names and attachment
types are, and MCP tool names (which carry server names) are grouped as `mcp`. Nothing is sent
anywhere.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

SCHEMA = "lcc-input-map/1"
#: Cost factors relative to one uncached input token (the ones docs/CACHE_ALIGNMENT.md uses).
#: Anthropic 1-hour cache writes cost more than 1.25, so the write share is a lower bound there.
COST_FACTORS = {"uncached": 1.0, "cache_write": 1.25, "cache_read": 0.1}
APPROXIMATION = (
    "Billed input and its cache split come from the provider's usage records (exact). "
    "Category shares replay the transcript with lcc's tokenizer and assume one tokenizer "
    "ratio across categories: use them to rank categories, not as exact percentages. For "
    "Claude Code the fixed overhead is one fit over the whole session, so overhead that changes "
    "between compactions (newly loaded tools, re-injected listings) is averaged."
)
#: Fewer requests than this and the overhead fit is not attempted.
MIN_FIT_REQUESTS = 10
#: A repeated tool output shorter than this is not counted as a duplicate.
DUPLICATE_MIN_TOKENS = 50
TOP_N = 8

FIXED = "fixed overhead (system prompt, tool schemas, instructions)"
OPAQUE = "unattributed (opaque summary)"
# Attachment types Claude Code records but does not render into the model's context.
_NOT_SENT = frozenset({
    "auto_mode", "auto_mode_exit", "command_permissions", "compact_file_reference",
    "credential_org", "deferred_tools_record", "hook_cancelled", "prompt_snapshot",
    "remote_session_change", "thinking_drop",
})
_ATTACHMENT_FIELDS = (
    "content", "text", "prompt", "snippet", "addedNames", "addedBlocks", "addedTypes",
    "files", "date", "context", "snapshot",
)


def _tokens(text: str) -> int:
    from lcc.token_budget import count_tokens

    return count_tokens(text, "gpt-4.1").value if text else 0


def _int(value: Any) -> int:
    """A usage count as written by the provider; anything malformed counts as 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):  # json.loads accepts Infinity and NaN
        return max(0, int(value)) if math.isfinite(value) else 0
    if isinstance(value, str):
        try:
            return max(0, int(value.strip()))
        except ValueError:
            return 0
    return 0


def _tool_name(name: str) -> str:
    """MCP tool names carry server (often project) names: group them."""
    return "mcp" if "mcp__" in name else name


def _token_method() -> tuple[str, str | None]:
    from lcc.token_budget import count_tokens

    probe = count_tokens("lcc", "gpt-4.1")
    return probe.method.value, probe.note


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False) if content else ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text"):
            parts.append(str(block.get("text") or ""))
        elif isinstance(block, dict) and block.get("type") == "tool_result":
            parts.append(_text(block.get("content")))
    return "\n".join(parts)


def _dumps(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _attachment_text(attachment: dict[str, Any]) -> str:
    if attachment.get("type") in _NOT_SENT:
        return ""
    parts = [_dumps(attachment[k]) for k in _ATTACHMENT_FIELDS if attachment.get(k)]
    if attachment.get("type") == "hook_success":  # hook context arrives as JSON on stdout
        try:
            out = json.loads(attachment.get("stdout") or "{}")
            extra = (out.get("hookSpecificOutput") or {}).get("additionalContext")
        except (ValueError, AttributeError):
            extra = None
        if isinstance(extra, str) and extra:
            parts.append(extra)
    return "\n".join(parts)


# Events: ("item" | "generated", category, detail, tokens, digest, path)
# | ("request", usage[, whole_context]) | ("boundary",) | ("context", category, tokens)
# | ("system_prompt", tokens) | ("opaque",). "generated" items came from the response being
# billed next; "context" items are re-sent copies; "opaque" marks an encrypted summary.
# `detail` is the tool or attachment type for the drill-down.
Event = tuple[Any, ...]


def _request_key(record: dict[str, Any], index: int) -> str:
    # One request can be written over several lines sharing a requestId; a record without
    # one is its own request.
    return str(record.get("requestId") or record.get("uuid") or f"#{index}")


def _preserved_uuids(boundary: dict[str, Any], order: list[str]) -> list[str]:
    """UUIDs of the messages a Claude Code compaction kept (``compactMetadata``)."""
    meta = boundary.get("compactMetadata")
    if not isinstance(meta, dict):
        return []
    kept = meta.get("preservedMessages")
    if isinstance(kept, dict):
        uuids = kept.get("allUuids") or kept.get("uuids")
        if isinstance(uuids, list):
            return [u for u in uuids if isinstance(u, str)]
    segment = meta.get("preservedSegment")
    if isinstance(segment, dict) and segment.get("headUuid") in order:
        head = order.index(segment["headUuid"])
        tail = order.index(segment["tailUuid"]) if segment.get("tailUuid") in order else head
        return order[head:tail + 1]
    return []


def _claude_events(records: list[dict[str, Any]]) -> Iterator[Event]:
    calls: dict[str, tuple[str, str]] = {}
    seen_requests: set[str] = set()
    final_usage: dict[str, dict[str, Any]] = {}  # a split request's last usage is complete
    for index, record in enumerate(records):
        usage = (record.get("message") or {}).get("usage") if isinstance(
            record.get("message"), dict) else None
        if record.get("type") == "assistant" and isinstance(usage, dict):
            final_usage[_request_key(record, index)] = usage

    def record_events(record: dict[str, Any], index: int) -> Iterator[Event]:
        kind = record.get("type")
        if kind == "attachment":
            attachment = record.get("attachment")
            if not isinstance(attachment, dict):
                return
            if attachment.get("type") == "prompt_snapshot":
                yield ("system_prompt", _tokens(_dumps(attachment.get("systemPrompt") or "")))
                return
            text = _attachment_text(attachment)
            if text:
                yield ("item", "attachments", str(attachment.get("type")), _tokens(text), None, "")
            return
        message = record.get("message")
        if not isinstance(message, dict):
            return
        content = message.get("content")
        if kind == "assistant":
            key = _request_key(record, index)
            if key in final_usage and key not in seen_requests:
                seen_requests.add(key)
                yield ("request", final_usage[key])
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    yield ("item", "assistant text", "", _tokens(str(block.get("text") or "")),
                           None, "")
                elif block.get("type") == "tool_use":
                    tool_input = block.get("input")
                    tool_input = tool_input if isinstance(tool_input, dict) else {}
                    name = _tool_name(str(block.get("name") or "?"))
                    path = tool_input.get("file_path") if name == "Read" else None
                    calls[str(block.get("id"))] = (name, path if isinstance(path, str) else "")
                    yield ("item", "tool-call inputs", name, _tokens(_dumps(tool_input)), None, "")
                # thinking: re-sent only in part and not attributable; counted from usage instead
        elif kind == "user":
            summary = bool(record.get("isCompactSummary"))
            if isinstance(content, str):
                category = "compaction summary" if summary else "user text"
                yield ("item", category, "", _tokens(content), None, "")
                return
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    name, path = calls.get(str(block.get("tool_use_id")), ("?", ""))
                    body = _text(block.get("content"))
                    digest = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
                    yield ("item", "tool results", name, _tokens(body), digest, path)
                elif block.get("type") == "text":
                    text = str(block.get("text") or "")
                    if text.lstrip().startswith("<system-reminder"):
                        yield ("item", "attachments", "system-reminder", _tokens(text), None, "")
                        continue
                    category = "compaction summary" if summary else "user text"
                    yield ("item", category, "", _tokens(text), None, "")

    kept: dict[str, list[tuple[str, int]]] = {}  # uuid -> (category, tokens) it put in context
    for index, record in enumerate(records):
        if record.get("isSidechain"):
            continue  # a subagent's own context, not this one's
        if record.get("type") == "system" and record.get("subtype") == "compact_boundary":
            yield ("boundary",)
            # Claude Code keeps some messages through a compaction without writing them again
            for uuid in _preserved_uuids(record, list(kept)):
                for category, tokens in kept.get(uuid, []):
                    yield ("context", category, tokens)
            continue
        events = list(record_events(record, index))
        if isinstance(record.get("uuid"), str):
            kept[record["uuid"]] = [(e[1], e[3]) for e in events if e[0] == "item"]
        yield from events


def _codex_events(records: Iterable[dict[str, Any]]) -> Iterator[Event]:
    """Codex rollout events.

    A response's own items (reasoning, messages, tool calls) and the outputs of the calls it
    made are written *before* its ``token_count``, so they are yielded as ``generated``: the
    replay charges them from the next request on, not to the request that produced them.
    """
    from lcc.session_report import codex_message

    calls: dict[str, str] = {}
    fresh_calls: set[str] = set()  # calls made since the last billed request
    last_total: Any = None
    # token_usage_record duplicates token_count, except for the compaction call itself
    last_record: dict[str, Any] | None = None
    counted: set[str] = set()  # response ids already billed through token_count
    base = ""  # base_instructions: sent as `instructions` on every request

    def item(payload: dict[str, Any], index: int, generated: bool) -> Iterator[Event]:
        tag = "generated" if generated else "item"
        item_type = payload.get("type")
        if item_type == "additional_tools":
            tokens = _tokens(_dumps(payload.get("tools") or ""))
            yield ("item", "tool schemas", "", tokens, None, "")
        elif item_type == "message":
            role = payload.get("role")
            text = _text(payload.get("content"))
            if role == "developer" and base and base in text:
                # newer rollouts repeat base_instructions as the first developer message
                yield ("item", "system prompt", "", max(0, _tokens(text) - _tokens(base)), None,
                       "")
                return
            category = {"developer": "system prompt", "assistant": "assistant text"}.get(
                str(role), "user text"
            )
            if role == "user" and "<environment_context>" in text:
                category = "instructions"
            generated = generated and role == "assistant"
            yield ("generated" if generated else "item", category, "", _tokens(text), None, "")
        elif item_type in ("function_call", "custom_tool_call", "local_shell_call",
                           "web_search_call"):
            entry = codex_message(payload, index)
            if entry is None:
                return
            use = entry["toolUses"][0]
            use["tool"] = _tool_name(use["tool"])
            calls[use["tool_use_id"]] = use["tool"]
            if generated:
                fresh_calls.add(use["tool_use_id"])
            raw = payload.get("arguments") or payload.get("input") or payload.get("action") or ""
            yield (tag, "tool-call inputs", use["tool"], _tokens(_dumps(raw)), None, "")
        elif item_type in ("function_call_output", "custom_tool_call_output"):
            call_id = str(payload.get("call_id"))
            body = _text(payload.get("output"))
            digest = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
            tag = "generated" if generated and call_id in fresh_calls else "item"
            yield (tag, "tool results", calls.get(call_id, "?"), _tokens(body), digest, "")
        elif item_type == "agent_message":
            # messages from other agents arrive as input to this one
            yield ("item", "agent messages", "", _tokens(_text(payload.get("content"))), None, "")

    for index, record in enumerate(records):
        kind, payload = record.get("type"), record.get("payload")
        if not isinstance(payload, dict):
            continue
        if kind == "session_meta":
            instructions = payload.get("base_instructions")
            text = instructions.get("text") if isinstance(instructions, dict) else instructions
            if isinstance(text, str) and text.strip():
                base = text
                yield ("item", "system prompt", "", _tokens(base), None, "")
        elif kind == "compacted":
            # The context after compaction is what replaced it, plus the instructions.
            latest = payload.get("latest_token_usage_record")
            billing = latest if isinstance(latest, dict) else last_record
            response = str((billing or {}).get("response_id") or "")
            if billing and isinstance(billing.get("usage"), dict) and response not in counted:
                counted.add(response)
                # the compaction call was sent the whole context before it
                yield ("request", _codex_usage(billing["usage"]), True)
            yield ("boundary",)
            fresh_calls.clear()
            if base:
                yield ("context", "system prompt", _tokens(base))
            history = payload.get("replacement_history")
            if isinstance(history, list):
                for entry in history:
                    if isinstance(entry, dict):
                        if entry.get("type") == "compaction" or "encrypted_content" in entry:
                            yield ("opaque",)  # an encrypted summary: size unknown here
                        for event in item(entry, index, generated=False):
                            yield ("context", event[1], event[3])
            elif isinstance(payload.get("message"), str):
                yield ("context", "compaction summary", _tokens(payload["message"]))
        elif kind == "response_item":
            yield from item(payload, index, generated=True)
        elif kind == "token_usage_record":
            last_record = payload
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            total = info.get("total_token_usage")
            last = info.get("last_token_usage")
            if not isinstance(last, dict) or not total or total == last_total:
                continue  # Codex repeats a count when nothing new was billed
            last_total = total
            fresh_calls.clear()
            if last_record is not None:
                counted.add(str(last_record.get("response_id") or ""))
                last_record = None
            yield ("request", _codex_usage(last))


def _codex_usage(last: dict[str, Any]) -> dict[str, Any]:
    cached = _int(last.get("cached_input_tokens"))
    written = _int(last.get("cache_write_input_tokens"))
    return {
        # input_tokens includes the cached and written parts
        "input_tokens": max(0, _int(last.get("input_tokens")) - cached - written),
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": written,
        "output_tokens": _int(last.get("output_tokens")),
        "output_tokens_details": {"thinking_tokens": _int(last.get("reasoning_output_tokens"))},
    }


def _records(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _fit(pairs: list[tuple[int, int]]) -> dict[str, Any] | None:
    """Least squares billed = a + b * transcript. None when it cannot be trusted."""
    if len(pairs) < MIN_FIT_REQUESTS:
        return None
    mean_x = sum(x for x, _ in pairs) / len(pairs)
    mean_y = sum(y for _, y in pairs) / len(pairs)
    sxx = sum((x - mean_x) ** 2 for x, _ in pairs)
    if not sxx:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / sxx
    intercept = mean_y - slope * mean_x
    if intercept < 0 or slope <= 0:
        return None  # e.g. many compactions; the overhead is not separable
    return {"intercept_tokens": round(intercept), "slope": round(slope, 3)}


def _top(counter: Counter[str]) -> list[dict[str, Any]]:
    top = [(k, v) for k, v in counter.most_common(TOP_N) if v]
    rows: list[dict[str, Any]] = [{"name": k, "tokens": v} for k, v in top]
    rest = sum(counter.values()) - sum(v for _, v in top)
    if rest:
        rows.append({"name": "(other)", "tokens": rest})
    return rows


def input_map(path: Path) -> dict[str, Any]:
    from lcc import __version__

    records = _records(path)
    codex = bool(records) and records[0].get("type") == "session_meta"
    events = _codex_events(records) if codex else _claude_events(records)

    once: Counter[str] = Counter()  # tokens per category, counted once
    active: Counter[str] = Counter()  # tokens per category in the context right now
    pending: Counter[str] = Counter()  # generated by the response not yet billed
    replayed: Counter[str] = Counter()  # tokens per category summed over requests
    billed: Counter[str] = Counter()
    output: Counter[str] = Counter()
    by_detail: dict[str, Counter[str]] = {
        "tool results": Counter(), "tool-call inputs": Counter(), "attachments": Counter()
    }
    pairs: list[tuple[int, int]] = []
    reads: dict[str, set[str]] = {}
    seen_outputs: set[str] = set()
    reread = reread_identical = duplicates = 0
    system_prompt = 0
    opaque_pending = False
    opaque_segments = 0
    for event in events:
        if event[0] == "boundary":  # what came before is no longer in context
            active.clear()
            pending.clear()
            reads.clear()
            seen_outputs.clear()
        elif event[0] == "system_prompt":
            system_prompt = max(system_prompt, event[1])
        elif event[0] == "context":  # re-sent after a compaction; already counted once
            active[event[1]] += event[2]
        elif event[0] == "opaque":
            opaque_pending = True
        elif event[0] in ("item", "generated"):
            _, category, detail, tokens, digest, file_path = event
            once[category] += tokens
            active[category] += tokens
            if event[0] == "generated":
                pending[category] += tokens
            if category in by_detail:
                by_detail[category][detail] += tokens
            if digest is not None:
                if file_path:
                    previous = reads.setdefault(file_path, set())
                    if previous:
                        reread += tokens
                        reread_identical += tokens if digest in previous else 0
                    previous.add(digest)
                if tokens >= DUPLICATE_MIN_TOKENS:
                    duplicates += tokens if digest in seen_outputs else 0
                    seen_outputs.add(digest)
        else:  # request
            usage = event[1]
            row = {
                "uncached": _int(usage.get("input_tokens")),
                "cache_write": _int(usage.get("cache_creation_input_tokens")),
                "cache_read": _int(usage.get("cache_read_input_tokens")),
            }
            billed.update(row)
            details = usage.get("output_tokens_details")
            output["output"] += _int(usage.get("output_tokens"))
            if isinstance(details, dict):
                output["thinking"] += _int(details.get("thinking_tokens"))
            if len(event) > 2 and event[2]:
                sent = +active  # a compaction call: sent the whole context
            else:
                sent = active - pending  # what this request was sent: not its own output
                pending.clear()
            if opaque_pending and not (len(event) > 2 and event[2]):
                # An encrypted compaction summary has no text to count. Size it from the
                # first request after it: billed input minus what the replay can see.
                gap = max(0, sum(row.values()) - sum(sent.values()))
                active[OPAQUE] += gap
                sent[OPAQUE] += gap
                opaque_pending = False
                opaque_segments += 1
            replayed.update(sent)
            pairs.append((sum(sent.values()), sum(row.values())))

    requests = len(pairs)
    total = sum(billed.values())
    fit = None if codex else _fit(pairs)
    shares: list[dict[str, Any]] = []
    if total:
        fixed_share = min(1.0, fit["intercept_tokens"] * requests / total) if fit else 0.0
        replay_total = sum(replayed.values())
        if fit:
            shares.append({"category": FIXED, "share": round(fixed_share, 4)})
        for category, tokens in replayed.most_common():
            if tokens and replay_total:
                share = (1 - fixed_share) * tokens / replay_total
                shares.append({"category": category, "share": round(share, 4)})
    warnings = []
    if not codex and total and fit is None:
        warnings.append(
            "Fixed overhead (system prompt, tool schemas, instructions) could not be separated "
            "in this session (fewer than 10 requests, or the fit gave a negative intercept). "
            "It is spread over the categories below, which are overstated."
        )
    if opaque_segments:
        warnings.append(
            f"{opaque_segments} compaction(s) left an encrypted summary. Its size is estimated "
            f"as the first later request's billed input minus what lcc can count, and shown "
            f"as '{OPAQUE}'."
        )
    weighted = {k: round(billed[k] * f, 1) for k, f in COST_FACTORS.items()}
    weighted_total = sum(weighted.values())
    method, note = _token_method()
    return {
        "schema": SCHEMA,
        "lcc_version": __version__,
        "format": "codex" if codex else "claude-code",
        "requests": requests,
        "billed_input": {
            **{k: billed[k] for k in COST_FACTORS},
            "total": total,
            "cache_read_share": round(billed["cache_read"] / total, 4) if total else None,
        },
        "cost": {
            "factors": dict(COST_FACTORS),
            "weighted": weighted,
            "cache_write_share": (
                round(weighted["cache_write"] / weighted_total, 4) if weighted_total else None
            ),
            "uncached_share": (
                round(weighted["uncached"] / weighted_total, 4) if weighted_total else None
            ),
        },
        "fixed_overhead_fit": fit,
        "system_prompt_tokens": system_prompt or once.get("system prompt") or None,
        "categories": shares,
        "transcript_tokens": dict(once.most_common()),
        "drill_down": {
            "tool_results_by_tool": _top(by_detail["tool results"]),
            "tool_inputs_by_tool": _top(by_detail["tool-call inputs"]),
            "attachments_by_type": _top(by_detail["attachments"]),
            "re_read_tokens": reread,
            "re_read_identical_tokens": reread_identical,
            "duplicate_output_tokens": duplicates,
        },
        "provider_output_tokens": dict(output),
        "token_count_method": method,
        "token_count_note": note,
        "approximation": APPROXIMATION,
        "warnings": warnings,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def to_markdown(report: dict[str, Any]) -> str:
    billed = report["billed_input"]
    cost = report["cost"]
    factors = cost["factors"]
    lines = [
        f"**lcc measure-session --input-map** · lcc {report['lcc_version']} · "
        f"{report['format']} · tokens counted {report['token_count_method']}",
        "",
        f"{report['requests']} requests · billed input {billed['total']:,} tokens · "
        f"cache read {_pct(billed['cache_read_share'])} of tokens · cache writes "
        f"{_pct(cost['cache_write_share'])} of input cost (read {factors['cache_read']}×, "
        f"write {factors['cache_write']}×)",
        "",
    ]
    lines += [f"> Warning: {w}" for w in report.get("warnings", [])]
    if report.get("warnings"):
        lines.append("")
    if report["categories"]:
        lines += ["| where billed input goes | share |", "| --- | ---: |"]
        lines += [f"| {r['category']} | {r['share']:.1%} |" for r in report["categories"]]
    else:
        lines.append("No usage records in this file: billed shares cannot be computed.")
    fit = report["fixed_overhead_fit"]
    if report["format"] == "claude-code":
        lines += ["", (
            f"Fixed overhead per request (fit): {fit['intercept_tokens']:,} tokens, "
            f"slope {fit['slope']}." if fit else
            "Fixed overhead: not separable in this session (fit skipped)."
        )]
    drill = report["drill_down"]
    for title, key in (("tool results", "tool_results_by_tool"),
                       ("tool-call inputs", "tool_inputs_by_tool"),
                       ("attachments", "attachments_by_type")):
        if drill[key]:
            top = ", ".join(f"{r['name']} {r['tokens']:,}" for r in drill[key])
            lines += ["", f"Top {title} (transcript tokens): {top}"]
    lines += [
        "",
        f"Re-reads: {drill['re_read_tokens']:,} tokens ({drill['re_read_identical_tokens']:,} "
        f"identical) · duplicate outputs: {drill['duplicate_output_tokens']:,} tokens",
        "",
        f"> {report['approximation']}",
    ]
    if report.get("token_count_note"):
        lines.append(f"> Approximate counts: {report['token_count_note']}")
    lines += ["", "Counts only: no session text, file path or tool output is included. Built-in "
              "tool names and attachment types are; MCP tools are grouped as `mcp`."]
    return "\n".join(lines)
