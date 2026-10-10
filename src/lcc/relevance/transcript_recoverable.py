"""provider="rules", rules_mode="recoverable": replace an old output only when it can be recovered.

Owner contract (2026-10-10): removing an old tool output is acceptable when the agent can get
it back by re-reading a file or re-running a read-only command; removing needed content that
cannot be recovered is not. On top of everything ``lossless`` removes, this mode may replace a
tool result with a recovery pointer:

- ``[removed: re-read <path> to recover]`` (or ``... <path> (lines a-b) ...``) for a successful
  read of one file — ``Read``/``view``/``read_file``, or a shell ``cat``/``head``/``tail``/
  ``sed -n 'a,bp'`` of a single file — when no later call writes, patches, deletes or even
  names that file (any non-read call whose input names it counts as a possible write; so do
  worktree-changing git commands). With a workspace root and ``disk_check`` on, the file on
  disk must currently hold exactly the removed content (or line range); otherwise it is kept.
  Without a root the transcript proxy alone decides (``recoverability_check``
  ``transcript_proxy``).
- ``[removed: re-run `<cmd>` to recover]`` for a command on :func:`is_read_only_command`'s
  allowlist (``ls``, ``find``, ``rg``/``grep``, read-only ``git status|diff|log|show``,
  ``cat``-likes, ``wc``, ``tree``, ``pwd``, ``<tool> --version``).

Never replaced: anything off the allowlist (tests, builds, installs, network, MCP tools, web
fetch/search, edit/patch results), failed results, the latest error-bearing result and the call
before it, pinned turns (first message and the last ``preserve_recent``), and calls whose path
or command the goal or a recent user turn names. Text and tool inputs never change.
:func:`verify_recoverable` re-checks a compaction from the two payloads plus the pointers.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from lcc.relevance.transcript_lossless import lossless_decisions, verify_lossless
from lcc.relevance.transcript_rules import _flagged, _input_text, _is_error, _mentions, _names_file

FILE_READ_TOOLS = {"Read", "view", "read_file", "NotebookRead"}
SHELL_TOOLS = {"Bash", "exec_command", "shell", "local_shell", "container.exec"}
_SHELL_META = re.compile(r"[|;&<>`$\n\\]|\(|\)")
_VERSION_FLAGS = {"--version", "-V", "version"}
_GIT_READ = {"status", "diff", "log", "show"}
_GIT_WORKTREE = re.compile(
    r"\bgit\s+(?:checkout|switch|reset|stash|restore|pull|merge|rebase|apply|am|cherry-pick"
    r"|revert|clean|mv|rm)\b"
)
_FIND_UNSAFE = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0",
                "-fprintf", "-fls"}
_SED_RANGE = re.compile(r"^([1-9][0-9]*)(?:,([1-9][0-9]*))?p$")
_NUMBERED = re.compile(r"^\s*([1-9][0-9]*)(?:\t|→)(.*)$")
_CODEX_HEAD = re.compile(
    r"^(?:Chunk ID|Wall time|Process exited with code|Process running with session ID"
    r"|Original token count)\b"
)
_EXIT = re.compile(r"^Process exited with code (\d+)")
_FILE_PTR = re.compile(
    r"^\[removed: re-read (.+?)(?: \(lines ([1-9][0-9]*)-([1-9][0-9]*)\))? to recover\]$"
)
_CMD_PTR = re.compile(r"^\[removed: re-run `(.+)` to recover\]$", re.S)


def shell_command(call: Any) -> str | None:
    """The shell command a call runs, or None when it is not a shell call."""
    if call.tool not in SHELL_TOOLS:
        return None
    value = call.input.get("command", call.input.get("cmd"))
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        # Codex ``shell``: ["bash", "-lc", "<cmd>"]
        shells, flags = {"bash", "sh", "zsh"}, {"-c", "-lc"}
        if len(value) == 3 and value[0].rsplit("/", 1)[-1] in shells and value[1] in flags:
            return value[2]
        return shlex.join(value)
    return value if isinstance(value, str) and value.strip() else None


def _argv(cmd: str) -> list[str] | None:
    """Tokens of a simple command (no pipes, redirects, substitutions, chains), else None."""
    if _SHELL_META.search(cmd):
        return None
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    # No ``VAR=x cmd`` and no ``env``: outputs must not depend on an injected environment.
    if not argv or "=" in argv[0] or argv[0] == "env":
        return None
    return argv


def is_read_only_command(cmd: str) -> bool:
    """``cmd`` is on the read-only allowlist: re-running it changes nothing."""
    argv = _argv(cmd)
    if argv is None:
        return False
    prog, args = argv[0].rsplit("/", 1)[-1], argv[1:]
    if prog in {"ls", "pwd", "wc", "cat", "head", "nl", "grep", "egrep", "fgrep"}:
        return True
    if prog == "tree":
        return not any(a == "-o" or a.startswith("-o") for a in args)  # -o writes a file
    if prog == "tail":
        return not any(a in {"-f", "-F"} or a.startswith("--follow") for a in args)
    if prog == "rg":
        return not any(a.startswith("--pre") for a in args)
    if prog == "find":
        return not any(a in _FIND_UNSAFE for a in args)
    if prog == "sed":
        return _sed_range(args) is not None
    if prog == "git":
        return bool(args) and args[0] in _GIT_READ and not any(
            a.startswith(("--output", "--ext-diff")) for a in args
        )
    return len(args) == 1 and args[0] in _VERSION_FLAGS


def _sed_range(args: list[str]) -> tuple[tuple[int, int], str] | None:
    """``sed -n 'a,bp' FILE`` -> ((a, b), FILE); any other sed is not read-only here."""
    if len(args) != 3 or args[0] != "-n" or args[2].startswith("-"):
        return None
    match = _SED_RANGE.match(args[1])
    if match is None:
        return None
    first = int(match.group(1))
    return (first, int(match.group(2) or first)), args[2]


def _file_read(call: Any) -> tuple[str, str] | None:
    """(path, range spec) for a read of one file. Spec: ``all``, ``a-b`` or ``tail:N``."""
    if call.tool in FILE_READ_TOOLS:
        path = call.input.get("file_path") or call.input.get("path") or call.input.get(
            "notebook_path"
        )
        if not isinstance(path, str) or not path:
            return None
        if call.input.get("pages") is not None or call.input.get("view_range") is not None:
            return None
        if call.input.get("offset") is not None or call.input.get("limit") is not None:
            return path, "numbered"
        return path, "all"
    cmd = shell_command(call)
    argv = _argv(cmd) if cmd else None
    if argv is None or not is_read_only_command(cmd or ""):
        return None
    prog, args = argv[0].rsplit("/", 1)[-1], argv[1:]
    if prog == "cat" and len(args) == 1 and not args[0].startswith("-"):
        return args[0], "all"
    if prog == "sed" and (spec := _sed_range(args)):
        (a, b), path = spec
        return path, f"{a}-{b}"
    if prog in {"head", "tail"}:
        count, rest = 10, args
        if len(rest) >= 2 and rest[0] == "-n" and rest[1].isdigit():
            count, rest = int(rest[1]), rest[2:]
        elif rest and re.fullmatch(r"-[0-9]+", rest[0]):
            count, rest = int(rest[0][1:]), rest[1:]
        if len(rest) != 1 or rest[0].startswith("-"):
            return None
        return rest[0], f"1-{count}" if prog == "head" else f"tail:{count}"
    return None


def _body(text: str) -> tuple[str, bool]:
    """Command output minus a Codex exec header; False when the header shows a failure."""
    lines = text.split("\n")
    end = 0
    while end < len(lines) and _CODEX_HEAD.match(lines[end]):
        end += 1
    if end < len(lines) and lines[end] == "Output:":
        ok = all(m is None or m.group(1) == "0" for m in map(_EXIT.match, lines[:end]))
        running = any(line.startswith("Process running") for line in lines[:end])
        return "\n".join(lines[end + 1 :]), ok and not running
    return text, True


def _numbered(body: str) -> list[tuple[int, str]] | None:
    """A ``cat -n``-style read (Claude ``Read``): [(line number, content)], else None."""
    rows = []
    for line in body.rstrip("\n").split("\n"):
        match = _NUMBERED.match(line)
        if match is None:
            return None
        rows.append((int(match.group(1)), match.group(2)))
    numbers = [n for n, _ in rows]
    if not rows or numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return None
    return rows


def _file_lines(text: str) -> list[str]:
    return (text[:-1] if text.endswith("\n") else text).split("\n") if text else []


def _pointer_lines(call: Any, body: str, spec: str) -> tuple[int, int] | None | str:
    """Line range a pointer names: None for the whole file, (a, b), or "skip" if unknowable."""
    if call.tool in FILE_READ_TOOLS:
        rows = _numbered(body)
        if rows is None:
            return None if spec == "all" else "skip"
        first, last = rows[0][0], rows[-1][0]
        return None if spec == "all" and first == 1 else (first, last)
    if spec == "all":
        return None
    if spec.startswith("tail:"):
        return "skip"  # ponytail: tail ranges need the file length; kept rather than guessed.
    a, b = spec.split("-")
    return int(a), int(b)


def _disk_matches(call: Any, path: str, spec: str, body: str, root: Path) -> bool:
    """The file on disk currently holds exactly ``body`` (whole file or the read range)."""
    workdir = call.input.get("workdir") or call.input.get("cwd")
    base = Path(workdir) if isinstance(workdir, str) and Path(workdir).is_absolute() else root
    target = Path(path) if Path(path).is_absolute() else base / path
    try:
        disk = _file_lines(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    if call.tool in FILE_READ_TOOLS and (rows := _numbered(body)) is not None:
        if spec == "all" and (rows[0][0] != 1 or rows[-1][0] != len(disk)):
            return False
        return all(n <= len(disk) and disk[n - 1] == content for n, content in rows)
    got = _file_lines(body)
    if spec == "all":
        return got == disk
    if spec.startswith("tail:"):
        count = int(spec[5:])
        return got == disk[-count:] if count else got == []
    a, b = (int(x) for x in spec.split("-"))
    return got == disk[a - 1 : b]


def _command_named(cmd: str, text: str) -> bool:
    """``text`` names the command, or a path-like argument of it."""
    if _mentions(text, cmd.strip()):
        return True
    args = (_argv(cmd) or [])[1:]
    return any(
        _names_file(text, arg) for arg in args
        if not arg.startswith("-") and ("/" in arg or "." in arg) and re.search(r"\w", arg)
    )


def _file_pointer(path: str, lines: tuple[int, int] | None) -> str:
    span = f" (lines {lines[0]}-{lines[1]})" if lines else ""
    return f"[removed: re-read {path}{span} to recover]"


def _command_pointer(cmd: str) -> str:
    return f"[removed: re-run `{cmd}` to recover]"


def _possible_writes(call: Any) -> tuple[str, bool]:
    """(input text, changes the worktree wholesale) for a call that may write files."""
    cmd = shell_command(call)
    if cmd is not None and is_read_only_command(cmd):
        return "", False
    if call.tool in FILE_READ_TOOLS:
        return "", False
    return _input_text(call), bool(cmd and _GIT_WORKTREE.search(cmd))


def recoverable_decisions(
    messages: list[Any],
    candidates: list[Any],
    goal: str,
    *,
    root: str | None = None,
    disk_check: bool = True,
) -> list[dict[str, Any]]:
    """One decision per candidate: ``replace`` (with ``note``), lossless ``dedupe``, or ``keep``."""
    all_calls = [call for message in messages for call in message.tool_calls]
    flags_present = any(_flagged(call) for call in all_calls)
    protected: dict[str, str] = {}
    for index in range(len(all_calls) - 1, -1, -1):
        if all_calls[index].result is not None and _is_error(all_calls[index], flags_present):
            protected[all_calls[index].id] = "latest_error_result"
            if index:
                protected.setdefault(all_calls[index - 1].id, "call_before_latest_error")
            break
    named_text = "\n".join(
        [goal]
        + [m.text for m in messages if m.pinned and m.message_index != 0 and m.role == "user"]
    )
    # Walk backwards: for each call, what later calls might have written.
    later_texts: dict[str, list[str]] = {}
    later_worktree: dict[str, bool] = {}
    texts: list[str] = []
    worktree = False
    for call in reversed(all_calls):
        later_texts[call.id] = list(texts)
        later_worktree[call.id] = worktree
        text, wholesale = _possible_writes(call)
        if text:
            texts.append(text)
        worktree = worktree or wholesale
    use_disk = bool(root) and disk_check
    # A call outside the pinned tail can still have its result inside it.
    pinned = {m.message_index for m in messages if m.pinned}
    root_path = Path(root) if root else None

    replaced: dict[str, dict[str, Any]] = {}
    reasons: dict[str, str] = {}
    for call in candidates:
        result = call.result
        reason = protected.get(call.id)
        if reason is None and result.message_index in pinned:
            reason = "pinned_recent_result"
        if reason is None and (_flagged(call) or "<tool_use_error>" in result.text):
            reason = "failed_result"
        body, ok = _body(result.text)
        if reason is None and not ok:
            reason = "failed_result"
        cmd = shell_command(call)
        read = _file_read(call)
        if reason is None and (
            (read and _names_file(named_text, read[0])) or (cmd and _command_named(cmd, named_text))
        ):
            reason = "named_in_goal_or_recent_turns"
        hit: dict[str, Any] | None = None
        if reason is None and read is not None:
            path, spec = read
            lines = _pointer_lines(call, body, spec)
            if later_worktree[call.id] or any(_names_file(t, path) for t in later_texts[call.id]):
                reason = "file_written_later"
            elif lines == "skip" and cmd is None:
                reason = "read_range_unknown"
            elif use_disk and not _disk_matches(call, path, spec, body, root_path):  # type: ignore[arg-type]
                reason = "disk_content_differs"
            else:
                # A tail range needs the file length: point at the command itself instead.
                note, recover = (
                    (_command_pointer(cmd), {"kind": "command", "command": cmd})
                    if lines == "skip" and cmd is not None
                    else (_file_pointer(path, lines), {  # type: ignore[arg-type]
                        "kind": "file", "path": path,
                        "lines": list(lines) if isinstance(lines, tuple) else None})
                )
                hit = {
                    "reason": "recoverable_file_read",
                    "note": note,
                    "recover": recover,
                    "recoverability_check": "disk" if use_disk else "transcript_proxy",
                }
        elif reason is None and cmd is not None and is_read_only_command(cmd):
            hit = {
                "reason": "recoverable_read_only_command",
                "note": _command_pointer(cmd),
                "recover": {"kind": "command", "command": cmd},
                "recoverability_check": "read_only_allowlist",
            }
        if hit is not None and len(hit["note"]) < len(result.text):
            replaced[call.id] = hit
        elif reason is not None:
            reasons[call.id] = reason

    # Lossless dedupes may not point at a result that is itself being replaced.
    unavailable = {c.result.id for c in candidates if c.id in replaced}
    lossless = lossless_decisions(messages, candidates, unavailable=unavailable)
    decisions: list[dict[str, Any]] = []
    for call, base in zip(candidates, lossless, strict=True):
        if call.id in replaced:
            decisions.append(base | {"decision": "replace"} | replaced[call.id])
        elif base["decision"] == "dedupe":
            decisions.append(base)
        else:
            decisions.append(base | {"reason": reasons.get(call.id, "not_recoverable")})
    return decisions


def _pointer_matches_call(call: Any | None, note: str) -> bool:
    """``note`` is a recovery pointer naming ``call``'s own path or allowlisted command."""
    if call is None:
        return False
    if (match := _CMD_PTR.match(note)) is not None:
        cmd = shell_command(call)
        return cmd is not None and match.group(1) == cmd and is_read_only_command(cmd)
    if (match := _FILE_PTR.match(note)) is not None:
        read = _file_read(call)
        return read is not None and read[0] == match.group(1)
    return False


def verify_recoverable(original_payload: Any, compacted_payload: Any) -> list[str]:
    """Violations of the recoverable contract; ``[]`` is a pass.

    Messages, roles, texts and tool calls (id, tool, input) must be unchanged, and every
    changed result must be a valid lossless pointer or a recovery pointer whose path/command
    is its own call's (and, for a command, on the read-only allowlist).
    """
    from lcc.relevance.transcript import parse_transcript

    calls = {
        call.id: call for message in parse_transcript(original_payload)
        for call in message.tool_calls
    }
    return verify_lossless(
        original_payload,
        compacted_payload,
        allow=lambda old, note: _pointer_matches_call(calls.get(old.id), note),
    )
