"""provider="rules": an offline, deterministic policy for tool-call compaction.

No network, no model: every decision comes from the transcript's own structure and is
recorded with the rule that made it. The rules follow taxonomy-v2 ``context_needed`` (what a
follow-up request needs from the history) and are applied in this order, first match wins:

Protect (keep whole)
    latest_error_result / call_before_latest_error
        failure_report needs the failing output and the action that produced it.
    latest_git_state      git_ship needs the latest ``git status|diff|log`` per subcommand.
    latest_task_state     task_status / handoff need the active plan or todo list.
    latest_artifact_edit  revise_recent_output needs the artifact last written or edited.
    latest_user_question  approve_or_pick needs the options the agent last offered.
    latest_tool_result    task_status needs the most recent tool output.
    named_in_goal         specified_task needs the files/URLs the goal names: the latest call
                          whose input or output mentions each one.
    named_in_recent_turns a call on a file the recent (pinned) turns name is current work.

Remove
    superseded_by_later_call:<id>   a later read/write of the same file, or the same command
                                    run again, makes this output stale. Dropped with its call.
    stale_read_far_from_recent_work a successful read/search more than
                                    ``STALE_AFTER_MESSAGES`` messages before the end.
    large_old_output_trimmed        any other output over ``LARGE_RESULT_CHARS`` keeps its head
                                    and tail plus a note.

Everything else is kept (``kept_default``). Text is never touched; pinned messages (the first
and the newest ``preserve_recent``) are handled by the caller and never reach these rules.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: Distance (in messages from the end) after which a successful read is considered stale.
STALE_AFTER_MESSAGES = 40
#: Results longer than this, not protected and not dropped, are trimmed to head + tail.
LARGE_RESULT_CHARS = 2000
TRIM_HEAD_CHARS = 300
TRIM_TAIL_CHARS = 300

ERROR_RE = re.compile(
    r"Traceback \(most recent call last\)|\bError\b|\bERROR\b|\bFAILED?\b"
    r"|\bexit code [1-9]|Exception"
)
GIT_RE = re.compile(r"\bgit\s+(status|diff|log)\b")
REF_RES = (
    re.compile(r"https?://\S+"),
    re.compile(r"[\w.~-]*/[\w.-]+(?:/[\w.-]+)*"),
    re.compile(r"\b[\w-]+\.(?:py|ts|tsx|js|jsx|md|json|toml|ya?ml|sql|css|html|sh|go|rs)\b"),
)
TASK_TOOLS = {"TodoWrite", "TaskCreate", "TaskUpdate", "ExitPlanMode", "update_plan"}
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
QUESTION_TOOLS = {"AskUserQuestion", "ExitPlanMode"}
#: Whole-file views: a later one replaces an earlier view (or edit) of the same file.
FILE_VIEW_TOOLS = {"Read", "Write"}
READ_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch", "NotebookRead"}
_READ_NAME_RE = re.compile(r"(?:^|_)(?:read|get|list|search|fetch|find|snapshot|query)", re.I)


def _refs(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for rx in REF_RES for m in rx.finditer(text)))


def _path(call: Any) -> str | None:
    for key in ("file_path", "notebook_path", "path"):
        value = call.input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _command(call: Any) -> str:
    value = call.input.get("command")
    return value if isinstance(value, str) else ""


def _input_text(call: Any) -> str:
    return json.dumps(call.input, ensure_ascii=False, sort_keys=True, default=str)


def _is_error(call: Any) -> bool:
    result = call.result
    return result is not None and (
        bool(getattr(result, "is_error", False)) or bool(ERROR_RE.search(result.text))
    )


def _is_read(call: Any) -> bool:
    return call.tool in READ_TOOLS or bool(_READ_NAME_RE.search(call.tool.split("__")[-1]))


def _supersede_key(call: Any) -> tuple[str, str]:
    """What a later call must share to make this call's output stale."""
    path = _path(call)
    if call.tool in FILE_VIEW_TOOLS | EDIT_TOOLS and path:
        return ("file", path)
    if call.tool == "Bash" and _command(call):
        return ("bash", _command(call))
    return ("call", f"{call.tool} {_input_text(call)}")


def _protections(all_calls: list[Any], goal: str, recent_text: str) -> dict[str, str]:
    """call id -> protecting rule, first rule wins."""
    protected: dict[str, str] = {}

    def protect(call: Any | None, reason: str) -> None:
        if call is not None and call.id not in protected:
            protected[call.id] = reason

    def latest(pred) -> Any | None:
        return next((call for call in reversed(all_calls) if pred(call)), None)

    for index in range(len(all_calls) - 1, -1, -1):
        if _is_error(all_calls[index]):
            protect(all_calls[index], "latest_error_result")
            if index:
                protect(all_calls[index - 1], "call_before_latest_error")
            break
    for sub in ("status", "diff", "log"):
        protect(
            latest(
                lambda c, s=sub: (
                    c.tool == "Bash" and any(m.group(1) == s for m in GIT_RE.finditer(_command(c)))
                )
            ),
            "latest_git_state",
        )
    for tool in sorted(TASK_TOOLS):
        protect(latest(lambda c, t=tool: c.tool == t), "latest_task_state")
    protect(latest(lambda c: c.tool in EDIT_TOOLS), "latest_artifact_edit")
    protect(latest(lambda c: c.tool in QUESTION_TOOLS), "latest_user_question")
    protect(latest(lambda c: c.result is not None), "latest_tool_result")
    for ref in _refs(goal):
        protect(
            latest(
                lambda c, r=ref: (
                    r in _input_text(c) or (c.result is not None and r in c.result.text)
                )
            ),
            "named_in_goal",
        )
    for ref in _refs(recent_text):
        protect(latest(lambda c, r=ref: r == _path(c)), "named_in_recent_turns")
    return protected


def rules_decisions(messages: list[Any], candidates: list[Any], goal: str) -> list[dict[str, Any]]:
    """One decision per candidate (non-pinned call with a result), each with its rule."""
    all_calls = [call for message in messages for call in message.tool_calls]
    recent_text = "\n".join(
        part
        for message in messages
        if message.pinned and message.message_index != 0
        for part in [message.text, *(_input_text(c) for c in message.tool_calls)]
    )
    protected = _protections(all_calls, goal, recent_text)
    # Walk backwards once: for each call, the nearest later call that supersedes it.
    superseded_by: dict[str, str] = {}
    next_view: dict[tuple[str, str], str] = {}
    for call in reversed(all_calls):
        key = _supersede_key(call)
        if key in next_view:
            superseded_by[call.id] = next_view[key]
        if key[0] != "file" or call.tool in FILE_VIEW_TOOLS:
            next_view[key] = call.id
    last_index = messages[-1].message_index if messages else 0

    decisions: list[dict[str, Any]] = []
    for call in candidates:
        decision, reason, tail = "keep", protected.get(call.id), 0
        if reason is None:
            if call.id in superseded_by:
                decision, reason = "drop", f"superseded_by_later_call:{superseded_by[call.id]}"
            elif (
                _is_read(call)
                and not _is_error(call)
                and last_index - call.message_index > STALE_AFTER_MESSAGES
            ):
                decision, reason = "drop", "stale_read_far_from_recent_work"
            elif len(call.result.text) > LARGE_RESULT_CHARS:
                decision, reason, tail = "trim", "large_old_output_trimmed", TRIM_TAIL_CHARS
            else:
                reason = "kept_default"
        decisions.append(
            {
                "id": call.id,
                "decision": decision,
                "score": None,
                "keep_call": None,
                "keep_result": None,
                "source": "rules",
                "reason": reason,
                "message_index": call.message_index,
                "tool": call.tool,
                "trim_tail_chars": tail,
            }
        )
    return decisions
