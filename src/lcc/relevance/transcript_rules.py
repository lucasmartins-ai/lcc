"""provider="rules": an offline, deterministic policy for tool-call compaction.

No network, no model: every decision comes from the transcript's own structure and is
recorded with the rule that made it. The rules follow taxonomy-v2 ``context_needed`` (what a
follow-up request needs from the history) and are applied in this order, first match wins:

Protect (keep whole)
    latest_error_result / call_before_latest_error
        failure_report needs the failing output and the action that produced it. A result
        is an error when ``is_error`` says so; transcripts without that flag fall back to
        a text regex on command output only (never on Read/Grep of source).
    latest_git_state      git_ship needs the latest ``git status|diff|log`` per subcommand.
    latest_task_state     task_status / handoff need the active plan or todo list.
    latest_artifact_edit  revise_recent_output needs the artifact last written or edited.
    latest_user_question  approve_or_pick needs the options the agent last offered.
    latest_tool_result    task_status needs the most recent tool output.
    named_in_goal         specified_task needs the files/URLs the goal names: the latest
                          read/edit of each named file, plus the latest call that mentions
                          it (whole-name match: ``app.py`` is not ``webapp.py``). A
                          goal-named file is never dropped as stale.
    named_in_recent_turns a call on a file the recent (pinned) turns name is current work.

Remove
    superseded_by_later_call:<id>   a later successful whole-file Read/Write of the same file
                                    (no offset/limit/pages), or the same call run again with
                                    the same output (Codex chunk/timing lines ignored), makes
                                    this output stale. Dropped with its call. A rerun whose
                                    output changed (a poll, a test before/after a fix) does not.
    stale_read_far_from_recent_work a successful read/search more than
                                    ``STALE_AFTER_MESSAGES`` messages before the end.
    large_old_output_trimmed        any other output over ``LARGE_RESULT_CHARS`` keeps its head
                                    and tail plus a note, unless a trim guard keeps it whole.

Trim guards (keep whole; they never change a drop). Real Codex audits showed trims removing the
middle of files the agent was about to edit, so a trim needs all of these to be false:
    trim_guard_recent         within ``TRIM_MIN_AGE_MESSAGES`` of the end (still current work).
    trim_guard_interactive    a ``write_stdin`` poll or a ``wait``-style result (short-lived
                              process/agent state the next step reads in full).
    trim_guard_error          an error by the same test as latest_error_result (``is_error``,
                              or error text in command output when no result carries the flag).
    trim_guard_edited_later   the call names a file that a later edit (Edit/Write/MultiEdit,
                              or an ``apply_patch`` body sent through any tool) changes: its
                              body is what the edit targets.
    trim_guard_named          the call names a path/URL from the goal or the recent turns.

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
LARGE_RESULT_CHARS = 4000
TRIM_HEAD_CHARS = 1000
TRIM_TAIL_CHARS = 1000
#: A large output this close to the end (in messages) is current work: never trimmed.
TRIM_MIN_AGE_MESSAGES = STALE_AFTER_MESSAGES

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
#: Interactive polls and waits: their output is process/agent state, read in full.
INTERACTIVE_TOOLS = {"write_stdin"}
_WAIT_NAME_RE = re.compile(r"(?:^|_)wait(?:_|$)", re.I)
_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+?)\s*$", re.M)
#: Codex result header lines that differ on every run of the same command.
_RUN_META_RE = re.compile(
    r"^(?:Chunk ID|Wall time|Original token count|Process running with session ID"
    r"|Process exited with code)\b.*\n?",
    re.M,
)
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
    value = call.input.get("command") or call.input.get("cmd")  # Claude Bash / Codex exec_command
    return value if isinstance(value, str) else ""


def _input_text(call: Any) -> str:
    return json.dumps(call.input, ensure_ascii=False, sort_keys=True, default=str)


def _flagged(call: Any) -> bool:
    return call.result is not None and bool(getattr(call.result, "is_error", False))


def _is_error(call: Any, flags_present: bool) -> bool:
    """``is_error`` decides when the transcript carries it; otherwise the text regex, on
    command output only (a Read or Grep of source that says ``Error`` is not a failure)."""
    if flags_present or call.result is None:
        return _flagged(call)
    return bool(_command(call)) and bool(ERROR_RE.search(call.result.text))


def _names(path: str | None, ref: str) -> bool:
    """``path`` is the file ``ref`` names (``app.py`` names ``/r/app.py``, not ``webapp.py``)."""
    if not path:
        return False
    return path == ref or path.endswith("/" + ref)


def _mentions(text: str, ref: str) -> bool:
    return re.search(rf"(?<![\w.-]){re.escape(ref)}(?![\w-])", text) is not None


def _whole_view(call: Any) -> bool:
    """A successful view of the whole file: only that replaces an earlier view of it."""
    partial = any(call.input.get(k) is not None for k in ("offset", "limit", "pages"))
    return (
        call.tool in FILE_VIEW_TOOLS
        and not partial
        and call.result is not None
        and not _flagged(call)
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


def _protections(
    all_calls: list[Any], goal: str, recent_text: str, flags_present: bool
) -> dict[str, str]:
    """call id -> protecting rule, first rule wins."""
    protected: dict[str, str] = {}

    def protect(call: Any | None, reason: str) -> None:
        if call is not None and call.id not in protected:
            protected[call.id] = reason

    def latest(pred) -> Any | None:
        return next((call for call in reversed(all_calls) if pred(call)), None)

    for index in range(len(all_calls) - 1, -1, -1):
        if _is_error(all_calls[index], flags_present):
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
        # The file itself first (its latest read/edit), then its latest mention anywhere.
        protect(
            latest(lambda c, r=ref: c.tool in FILE_VIEW_TOOLS | EDIT_TOOLS and _names(_path(c), r)),
            "named_in_goal",
        )
        protect(
            latest(
                lambda c, r=ref: (
                    _mentions(_input_text(c), r)
                    or (c.result is not None and _mentions(c.result.text, r))
                )
            ),
            "named_in_goal",
        )
    for ref in _refs(recent_text):
        protect(latest(lambda c, r=ref: r == _path(c)), "named_in_recent_turns")
    return protected


#: Where a command runs, not what it names: every call in a session shares it.
_CONTEXT_KEYS = ("workdir", "cwd")


def _target_text(call: Any) -> str:
    """The call's input minus its working directory."""
    target = {k: v for k, v in call.input.items() if k not in _CONTEXT_KEYS}
    return json.dumps(target, ensure_ascii=False, sort_keys=True, default=str)


def _edited_paths(call: Any) -> list[str]:
    """Files a call edits: Edit/Write/MultiEdit/NotebookEdit paths, or the file headers of an
    ``apply_patch`` body in any input field (Codex also patches through ``exec``/shell)."""
    if call.tool in EDIT_TOOLS:
        return [p] if (p := _path(call)) else []
    return _PATCH_FILE_RE.findall("\n".join(str(v) for v in call.input.values()))


def _same_output(call: Any, later: Any) -> bool:
    """A rerun repeats ``call``: same result text once per-run Codex metadata is removed."""
    texts = [_RUN_META_RE.sub("", c.result.text if c.result else "").strip() for c in (call, later)]
    return texts[0] == texts[1]


def _names_file(text: str, path: str) -> bool:
    """``text`` names ``path``: the whole path, or its file name as a whole word."""
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return bool(name) and (_mentions(text, path) or _mentions(text, name))


def _trim_guard(
    call: Any, age: int, later_edits: set[str], refs: list[str], flags_present: bool
) -> str | None:
    """The guard that keeps this large output whole, or None when it may be trimmed."""
    if age <= TRIM_MIN_AGE_MESSAGES:
        return "trim_guard_recent"
    if call.tool in INTERACTIVE_TOOLS or _WAIT_NAME_RE.search(call.tool.split("__")[-1]):
        return "trim_guard_interactive"
    if _is_error(call, flags_present):
        return "trim_guard_error"
    text = _target_text(call)
    if call.tool not in EDIT_TOOLS | {"apply_patch"} and any(
        _names_file(text, p) for p in later_edits
    ):
        return "trim_guard_edited_later"
    if any(_mentions(text, ref) for ref in refs):
        return "trim_guard_named"
    return None


def rules_decisions(messages: list[Any], candidates: list[Any], goal: str) -> list[dict[str, Any]]:
    """One decision per candidate (non-pinned call with a result), each with its rule."""
    all_calls = [call for message in messages for call in message.tool_calls]
    recent_text = "\n".join(
        part
        for message in messages
        if message.pinned and message.message_index != 0
        for part in [message.text, *(_input_text(c) for c in message.tool_calls)]
    )
    flags_present = any(_flagged(call) for call in all_calls)
    protected = _protections(all_calls, goal, recent_text, flags_present)
    goal_refs = _refs(goal)
    # Guards match refs the goal or a recent turn's text names (not tool inputs: workdirs).
    pinned_text = "\n".join(m.text for m in messages if m.pinned and m.message_index != 0)
    guard_refs = list(dict.fromkeys([*goal_refs, *_refs(pinned_text)]))
    # Files edited after each call: walk backwards, accumulating every later edit.
    edited_after: dict[str, set[str]] = {}
    seen_edits: set[str] = set()
    for call in reversed(all_calls):
        edited_after[call.id] = set(seen_edits)
        seen_edits.update(_edited_paths(call))
    # Walk backwards once: for each call, the nearest later call that supersedes it.
    superseded_by: dict[str, str] = {}
    next_view: dict[tuple[str, str], Any] = {}
    for call in reversed(all_calls):
        key = _supersede_key(call)
        later = next_view.get(key)
        if later is not None and (key[0] == "file" or _same_output(call, later)):
            superseded_by[call.id] = later.id
        if key[0] != "file" or _whole_view(call):
            next_view[key] = call
    last_index = messages[-1].message_index if messages else 0

    decisions: list[dict[str, Any]] = []
    for call in candidates:
        decision, reason, tail = "keep", protected.get(call.id), 0
        if reason is None:
            if call.id in superseded_by:
                decision, reason = "drop", f"superseded_by_later_call:{superseded_by[call.id]}"
            elif (
                _is_read(call)
                # Conservative on any tool: a read that may have failed is never stale.
                and not (_flagged(call) or ERROR_RE.search(call.result.text))
                and not any(_names(_path(call), ref) for ref in goal_refs)
                and last_index - call.message_index > STALE_AFTER_MESSAGES
            ):
                decision, reason = "drop", "stale_read_far_from_recent_work"
            elif len(call.result.text) > LARGE_RESULT_CHARS:
                guard = _trim_guard(
                    call,
                    last_index - call.message_index,
                    edited_after.get(call.id, set()),
                    guard_refs,
                    flags_present,
                )
                if guard:
                    reason = guard
                else:
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
                "trim_head_chars": TRIM_HEAD_CHARS if decision == "trim" else None,
            }
        )
    return decisions
