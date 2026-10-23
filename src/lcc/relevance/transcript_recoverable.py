"""provider="rules", rules_mode="recoverable": replace an old output only when it can be recovered.

Owner contract (2026-10-10): removing an old tool output is acceptable when the agent can get
it back by re-reading a file or re-running a read-only command; removing needed content that
cannot be recovered is not. On top of everything ``lossless`` removes, this mode may replace a
tool result with a recovery pointer:

- ``[removed: re-read <path> to recover]`` (or ``... <path> (lines a-b) ...``) for a successful
  read of one file — ``Read``/``view``/``read_file``, or a shell ``cat``/``head``/``tail``/
  ``sed -n 'a,bp'`` of a single file — when no later call writes, patches, deletes or even
  names that file (any call that is not a pure read whose input names it counts as a possible
  write; so do worktree-changing git commands from any tool, and ``rm``/``mv``-like commands
  naming a parent directory). Without a workspace root the transcript proxy alone decides
  (``recoverability_check`` ``transcript_proxy``).
- Disk-authoritative (owner decision 2026-10-11): with a workspace root and ``disk_check`` on,
  the disk decides a file pointer instead of the transcript proxy. The file is replaced iff it
  exists, its path has no ``..`` component, a final symlink does not escape its own directory
  (files outside the workspace root are allowed: the root only switches the check on), is a
  regular file of at most :data:`DISK_MAX_BYTES`, decodes as UTF-8 and its bytes hold exactly
  the removed output (whole file, or the read's line range; ``Read`` line-number prefixes
  ``N\t``/``N→`` stripped, a Codex exec header dropped, no other normalisation). Later writes,
  opaque or not, do not matter then: what the agent re-reads is what was removed. The pointer
  says ``content verified on disk at compaction time``; reasons are ``replace_disk_verified``
  or ``keep_disk_mismatch`` / ``_missing`` / ``_not_regular`` / ``_outside_root`` /
  ``_too_large`` / ``_unreadable``, and ``keep_disk_changed_before_emit`` when the file's hash
  changed between the check and the emit (see :func:`disk_unchanged`).
- ``[removed: re-run `<cmd>` to recover]`` for a command on :func:`is_read_only_command`'s
  allowlist (``ls``, ``find``, ``rg``/``grep``, read-only ``git status|diff|log|show``,
  ``cat``-likes, ``wc``, ``tree``, ``pwd``, ``--version`` of a known tool) when nothing later
  can have changed its output: no opaque call (a script, test run, build, MCP tool), no
  worktree-wide git command, and — for git reads or commands without explicit paths — no
  write at all; otherwise no write naming one of its paths.
- Pointers name the call's working directory when it had one: ``(cwd <dir>)`` / ``in <dir>``.

Every rule below can only turn a replace into a keep (v0.7 review):

- Opaque later writes: a later shell call off the allowlist (script, build, install, test run,
  git write) or an unknown tool may write any file under its working directory, so it
  invalidates every earlier file pointer under that directory, or all of them when its cwd is
  unknown, relative, or it changes directory (``cd``, ``-C``).
- Command pointers are off unless ``allow_command_pointers``; a read that could only get a
  command pointer (``tail -n N``, a range the output does not fill) is then kept.
- A file pointer needs an absolute path or an absolute working directory on the call.
- Shell reads with globs, braces, ``~`` or several files, reads of ``-``/stdin and of
  ``/dev``, ``/proc``, ``/sys``, and ``tail`` follow modes are never pointers.
- A line range the returned output does not fill exactly is kept, never clamped.
- Calls whose id is carried by more than one call or result are always kept.
- Calls in a system temp dir (``/tmp``, ``/var/tmp``, ``/var/folders``, ``/dev/shm``: cwd, file
  or command argument) are kept: the file may be gone when the agent re-reads it.

Never replaced: anything off the allowlist (tests, builds, installs, network, MCP tools, web
fetch/search, edit/patch results), failed results, the latest error-bearing result and the call
before it, pinned turns (first message and the last ``preserve_recent``), and calls whose path
or command the goal or a recent user turn names. Text and tool inputs never change.
:func:`verify_recoverable` re-checks a compaction from the two payloads plus the pointers.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
import shlex
import stat
from typing import Any

from lcc.relevance.transcript_lossless import (
    _ANY_POINTER_RE,
    duplicate_ids,
    lossless_decisions,
    verify_lossless,
)
from lcc.relevance.transcript_rules import (
    EDIT_TOOLS,
    QUESTION_TOOLS,
    READ_TOOLS,
    TASK_TOOLS,
    _flagged,
    _input_text,
    _is_error,
    _mentions,
    _names_file,
)

FILE_READ_TOOLS = {"Read", "view", "read_file", "NotebookRead"}
# Shell tool names seen in the Claude/Codex/Hermes dossiers (``terminal`` is Hermes').
SHELL_TOOLS = {"Bash", "exec_command", "shell", "local_shell", "container.exec", "terminal"}
#: Tools that write no file: they never invalidate a pointer.
PURE_TOOLS = READ_TOOLS | TASK_TOOLS | QUESTION_TOOLS | FILE_READ_TOOLS | {
    "search_files", "web_search", "ToolSearch", "tool_search", "view_image", "vision_analyze",
    "skill_view", "Skill", "TaskList", "TaskGet",
}
#: Writes whose targets are in their input; any other non-pure call is opaque (may write anything).
TARGETED_WRITE_TOOLS = EDIT_TOOLS | {"apply_patch", "patch", "write_file"}
_SHELL_META = re.compile(r"[|;&<>`$\n\\]|\(|\)")
#: The only version queries on the allowlist: ``<tool> --version`` for these tools.
_VERSION_TOOLS = {"python", "python3", "node", "npm", "git", "pip", "pip3", "uv", "bun", "deno",
                  "rustc", "cargo", "ruby", "go", "tsc", "docker", "pnpm"}
_GIT_READ = {"status", "diff", "log", "show"}
_GIT_WORKTREE = re.compile(
    r"\bgit\s+(?:checkout|switch|reset|stash|restore|pull|merge|rebase|apply|am|cherry-pick"
    r"|revert|clean|mv|rm)\b"
)
#: Commands that can delete or move a whole directory: an ancestor path counts as the file.
_DESTRUCTIVE = re.compile(r"\b(?:rm|rmdir|mv|cp|rsync|unlink|tar|unzip|git\s+(?:rm|mv|clean))\b")
_FIND_UNSAFE = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0",
                "-fprintf", "-fls"}
_SED_RANGE = re.compile(r"^([1-9][0-9]*)(?:,([1-9][0-9]*))?p$")
_NUMBERED = re.compile(r"^\s*([1-9][0-9]*)(?:\t|→)(.*)$")
_CODEX_HEAD = re.compile(
    r"^(?:Chunk ID|Wall time|Process exited with code|Process running with session ID"
    r"|Original token count)\b"
)
_EXIT = re.compile(r"^Process exited with code (\d+)")
#: System temp dirs: their files can be cleared before the agent re-reads them.
_TEMP = re.compile(r"^(?:/private)?/(?:tmp|var/tmp|var/folders)(?:/|$)|^/dev/shm(?:/|$)")
#: Device, process and kernel files: their content is not the file's, re-reading differs.
_SPECIAL = re.compile(r"^(?:/private)?/(?:dev|proc|sys)(?:/|$)")
#: Shell expansions that can name more than one file (or another file) than the literal text.
_GLOB = re.compile(r"[*?\[\]{}]")
#: An opaque call that changes directory may write outside its own cwd.
_CHDIR = re.compile(r"\b(?:cd|pushd)\b|(?:^|\s)-C\b|--(?:prefix|cwd|directory)\b")
#: Disk check: a larger file is never read for a pointer; its read is kept. The removed
#: output sits in a context window, so a real candidate is far smaller than this.
DISK_MAX_BYTES = 4 * 1024 * 1024
_VERIFIED = "; content verified on disk at compaction time"
#: Programs that read stdin when given no file operand.
_STDIN_PROGS = {"cat", "head", "tail", "nl", "wc"}


def shell_command(call: Any) -> str | None:
    """The shell command a call runs, or None when it is not a shell call."""
    if call.tool not in SHELL_TOOLS or call.input.get("background"):
        return None  # a background job's result is a process handle, not the command's output
    value = call.input.get("command", call.input.get("cmd"))
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        # Codex ``shell``: ["bash", "-lc", "<cmd>"]
        shells, flags = {"bash", "sh", "zsh"}, {"-c", "-lc"}
        if len(value) == 3 and value[0].rsplit("/", 1)[-1] in shells and value[1] in flags:
            return value[2]
        return shlex.join(value)
    return value if isinstance(value, str) and value.strip() else None


#: Commands longer than this are never parsed (and so never allowlisted): ``shlex`` is quadratic
#: in the length of one token, and no real command a pointer can name comes close.
MAX_PARSED_COMMAND_CHARS = 4096


def _argv(cmd: str) -> list[str] | None:
    """Tokens of a simple command (no pipes, redirects, substitutions, chains), else None."""
    if len(cmd) > MAX_PARSED_COMMAND_CHARS or _SHELL_META.search(cmd):
        return None
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    # No ``VAR=x cmd`` and no ``env``: outputs must not depend on an injected environment.
    if not argv or "=" in argv[0] or argv[0] == "env":
        return None
    # No ``./x`` or ``bin/x``: a path to a program can be any script.
    if "/" in argv[0] and not argv[0].startswith(("/bin/", "/usr/bin/")):
        return None
    return argv


def _operands(args: list[str]) -> list[str]:
    """Non-flag arguments; the value of ``-n``/``-c`` is a flag value, not a file."""
    out, skip = [], False
    for arg in args:
        if skip:
            skip = False
        elif arg in {"-n", "-c", "--lines", "--bytes", "-e", "-f"}:
            skip = True
        elif arg == "-" or not arg.startswith("-"):
            out.append(arg)
    return out


def _long_opt(arg: str, *names: str) -> bool:
    """``arg`` is a long option getopt may expand to one of ``names`` (``--fo`` -> ``--follow``)."""
    name = arg[2:].split("=", 1)[0] if arg.startswith("--") else ""
    return bool(name) and any(n.startswith(name) for n in names)


def is_read_only_command(cmd: str) -> bool:
    """``cmd`` is on the read-only allowlist: re-running it changes nothing."""
    argv = _argv(cmd)
    if argv is None:
        return False
    prog, args = argv[0].rsplit("/", 1)[-1], argv[1:]
    # stdin and device/proc files: re-running does not reproduce the output.
    if any(a == "-" or _SPECIAL.match(a) for a in args):
        return False
    if prog in _STDIN_PROGS and not _operands(args):
        return False
    if prog in {"grep", "egrep", "fgrep"} and len(_operands(args)) < 2 and not any(
        a.startswith("-") and not a.startswith("--") and ("r" in a or "R" in a) for a in args
    ):
        return False  # ponytail: ``-e PAT FILE`` counts as stdin too; that only keeps more
    if prog in {"python", "python3"} and args == ["-V"]:
        return True
    if prog in _VERSION_TOOLS and args == ["--version"]:
        return True
    if prog in {"ls", "pwd", "wc", "cat", "head", "nl", "grep", "egrep", "fgrep"}:
        return True
    if prog == "tree":
        # -o (anywhere in a short-flag group) and --output write a file; -R with -H writes too.
        return not any(
            a.startswith("--o") or (a.startswith("-") and not a.startswith("--")
                                    and ("o" in a or "R" in a))
            for a in args
        )
    if prog == "tail":
        # -f/-F anywhere in a short-flag group (-fn, -qf, -nf) or --follow/--retry follows.
        return not any(
            a.startswith(("--follow", "--retry")) or _long_opt(a, "follow", "retry")
            or (a.startswith("-") and not a.startswith("--") and ("f" in a or "F" in a))
            for a in args
        )
    if prog == "rg":
        return not any(a.startswith("--pre") for a in args)
    if prog == "find":
        return not any(a in _FIND_UNSAFE for a in args)
    if prog == "sed":
        return _sed_range(args) is not None
    if prog == "git":
        return bool(args) and args[0] in _GIT_READ and not any(
            a.startswith(("--output", "--ext-diff")) or _long_opt(a, "output", "ext-diff")
            for a in args
        )
    return False


def _sed_range(args: list[str]) -> tuple[tuple[int, int], str] | None:
    """``sed -n 'a,bp' FILE`` -> ((a, b), FILE); any other sed is not read-only here."""
    if len(args) != 3 or args[0] != "-n" or args[2].startswith("-"):
        return None
    match = _SED_RANGE.match(args[1])
    if match is None:
        return None
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if last < first:
        return None  # ``12,5p`` prints line 12 only; not a range a pointer can name
    return (first, last), args[2]


def _file_read(call: Any) -> tuple[str, str] | None:
    """(path, range spec) for a read of one file. Spec: ``all``, ``a-b`` or ``tail:N``."""
    read = _one_file_read(call)
    if read is None or read[0] == "-" or _SPECIAL.match(read[0]):
        return None
    if call.tool not in FILE_READ_TOOLS and (_GLOB.search(read[0]) or read[0].startswith("~")):
        return None  # the shell expands it: maybe several files, maybe another one
    return read


def _one_file_read(call: Any) -> tuple[str, str] | None:
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
        if count == 0 and prog == "head":
            return rest[0], "empty"
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
        if spec == "numbered":
            offset, limit = call.input.get("offset"), call.input.get("limit")
            if offset is not None and (not isinstance(offset, int) or first != max(offset, 1)):
                return "skip"
            if limit is not None and (not isinstance(limit, int) or len(rows) > limit):
                return "skip"
        return None if spec == "all" and first == 1 else (first, last)
    if spec == "all":
        return None
    if spec == "empty" or spec.startswith("tail:"):
        return "skip"  # ponytail: tail ranges need the file length; kept rather than guessed.
    a, b = (int(x) for x in spec.split("-"))
    if len(_file_lines(body)) != b - a + 1:
        return "skip"  # the file is shorter than the range: never clamp by guess
    return a, b


def _lines_match(call: Any, spec: str, body: str, disk: list[str]) -> bool:
    """``body`` is exactly the file's ``disk`` lines (whole file or the read range)."""
    if call.tool in FILE_READ_TOOLS and (rows := _numbered(body)) is not None:
        # Claude Code's Read numbers the empty line after a final newline ("480\t" for a
        # 479-line file); that row carries no content, so it does not count against the file.
        if len(rows) > 1 and rows[-1] == (len(disk) + 1, ""):
            rows = rows[:-1]
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


def _disk_read(target: str, root: str) -> tuple[str, bytes | None, str]:
    """(state, file bytes, real path): state ``ok`` or the ``keep_disk_*`` reason."""
    real = os.path.realpath(target)
    homes = (os.path.realpath(root), os.path.realpath(posixpath.dirname(target)))
    if not any(_under(real, home) for home in homes if home != "/"):
        return "keep_disk_outside_root", None, real
    try:
        info = os.stat(real)
        if not stat.S_ISREG(info.st_mode):
            return "keep_disk_not_regular", None, real
        if info.st_size > DISK_MAX_BYTES:
            return "keep_disk_too_large", None, real
        with open(real, "rb") as handle:
            data = handle.read(DISK_MAX_BYTES + 1)
    except FileNotFoundError:
        return "keep_disk_missing", None, real
    except OSError:
        return "keep_disk_unreadable", None, real
    return ("keep_disk_too_large", None, real) if len(data) > DISK_MAX_BYTES else ("ok", data, real)


def _disk_check(
    call: Any, target: str, spec: str, body: str, root: str
) -> tuple[str, dict[str, str] | None]:
    """(``ok`` or a ``keep_disk_*`` reason, {path, real, sha256} to re-hash before emitting)."""
    state, data, real = _disk_read(target, root)
    if data is None:
        return state, None
    try:
        text = data.decode("utf-8")  # strict, no newline translation: CRLF never matches LF
    except UnicodeDecodeError:
        return "keep_disk_unreadable", None
    if not _lines_match(call, spec, body, _file_lines(text)):
        return "keep_disk_mismatch", None
    return "ok", {"path": target, "real": real, "sha256": hashlib.sha256(data).hexdigest()}


def disk_unchanged(disk: dict[str, str], root: str) -> bool:
    """The file a disk-verified pointer names still resolves and hashes as at the check."""
    state, data, real = _disk_read(disk["path"], root)
    return (state == "ok" and real == disk["real"] and data is not None
            and hashlib.sha256(data).hexdigest() == disk["sha256"])


def _command_named(cmd: str, text: str) -> bool:
    """``text`` names the command, or a path-like argument of it."""
    if _mentions(text, cmd.strip()):
        return True
    args = (_argv(cmd) or [])[1:]
    return any(
        _names_file(text, arg) for arg in args
        if not arg.startswith("-") and ("/" in arg or "." in arg) and re.search(r"\w", arg)
    )


def _cwd(call: Any) -> str | None:
    value = call.input.get("workdir") or call.input.get("cwd")
    return value if isinstance(value, str) and value else None


def _temp(call: Any) -> bool:
    """The call reads or runs in a system temp dir (its cwd, file or a command argument)."""
    cmd = shell_command(call)
    read = _file_read(call)
    paths = [_cwd(call) or "", read[0] if read else ""] + ((_argv(cmd) or [])[1:] if cmd else [])
    return any(_TEMP.match(p) for p in paths)


def _resolved(path: str, cwd: str | None) -> str | None:
    """The absolute path a read names, or None when it is relative to an unknown directory."""
    if path.startswith("/"):
        return posixpath.normpath(path)
    if cwd and cwd.startswith("/"):
        return posixpath.normpath(posixpath.join(cwd, path))
    return None


def _under(path: str, directory: str) -> bool:
    path, directory = (p.removeprefix("/private") for p in (path, directory))
    directory = directory.rstrip("/")
    return not directory or path == directory or path.startswith(directory + "/")


def _opaque_dir(call: Any, text: str) -> str | None:
    """The directory an opaque call may write under; None means anywhere."""
    cwd = _cwd(call)
    if cwd is None or not cwd.startswith("/") or _CHDIR.search(text):
        return None
    return posixpath.normpath(cwd)


def _file_pointer(
    path: str, lines: tuple[int, int] | None, cwd: str | None = None, verified: bool = False
) -> str:
    span = f" (lines {lines[0]}-{lines[1]})" if lines else ""
    where = f" (cwd {cwd})" if cwd else ""
    return f"[removed: re-read {path}{span}{where} to recover{_VERIFIED if verified else ''}]"


def _command_pointer(cmd: str, cwd: str | None = None) -> str:
    where = f" in {cwd}" if cwd else ""
    return f"[removed: re-run `{cmd}`{where} to recover]"


def _possible_writes(call: Any) -> tuple[str, bool, bool]:
    """(input text, changes the worktree wholesale, opaque) for a call that may write files.

    Opaque: a write whose targets are not in its input (a script, a test run, a build).
    """
    cmd = shell_command(call)
    if cmd is not None and is_read_only_command(cmd):
        return "", False, False
    if cmd is None and call.tool in PURE_TOOLS:
        return "", False, False
    text = _input_text(call)
    # Any tool: Hermes ``execute_code`` or Codex ``exec`` can run git too.
    return text, bool(_GIT_WORKTREE.search(text)), call.tool not in TARGETED_WRITE_TOOLS


def _command_paths(cmd: str) -> list[str] | None:
    """Paths whose writes can change ``cmd``'s output; None when unknown (any write can)."""
    argv = _argv(cmd) or []
    prog = argv[0].rsplit("/", 1)[-1] if argv else ""
    if prog == "pwd" or argv[1:] in (["--version"], ["-V"]):
        return []
    if prog == "git":
        return None  # git status/diff/log/show: any git or file write in the repo
    paths = [a for a in argv[1:] if not a.startswith("-")]
    if not paths or any(a in {".", "./", "..", "~", "/"} or re.search(r"[*?\[]", a)
                        for a in paths):
        return None
    return paths  # ponytail: flag values (``-n 5``) count as paths too; that only keeps more


def _ancestors(path: str) -> list[str]:
    parts = path.rstrip("/").split("/")
    return [a for a in ("/".join(parts[:i]) for i in range(1, len(parts))) if a.strip("./~")]


def _refs_asked(candidates: list[Any]) -> set[str]:
    """Every path and file name the later-write checks will ask about (see ``_names_file``)."""
    refs: set[str] = set()
    for call in candidates:
        read = _file_read(call)
        cmd = shell_command(call)
        paths = ([read[0]] if read else []) + ((_command_paths(cmd) or []) if cmd else [])
        for path in paths:
            for ref in (path, *_ancestors(path)):
                refs.update((ref, ref.rstrip("/").rsplit("/", 1)[-1]))
    refs.discard("")
    return refs


def _ref_trie(refs: set[str]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for ref in refs:
        node = root
        for ch in ref:
            node = node.setdefault(ch, {})
        node[""] = ref
    return root


_WORD_START = re.compile(r"(?<![\w.-])")
_WORD_END = re.compile(r"[\w-]")


def _refs_named(text: str, trie: dict[str, Any]) -> set[str]:
    """The refs ``text`` mentions as whole words: ``_mentions`` for every ref at once."""
    found: set[str] = set()
    for start in _WORD_START.finditer(text):
        node = trie
        for end in range(start.start(), len(text)):
            child = node.get(text[end])
            if child is None:
                break
            node = child
            ref = node.get("")
            if ref is not None and not _WORD_END.match(text, end + 1):
                found.add(ref)
    return found


def recoverable_decisions(
    messages: list[Any],
    candidates: list[Any],
    goal: str,
    *,
    root: str | None = None,
    disk_check: bool = True,
    allow_command_pointers: bool = False,
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
    # What later calls might have written, as indexes by call position (linear in calls):
    # ``named[ref]`` is the last position whose write text names ``ref`` as a whole word,
    # ``named_destructive`` the same over destructive texts, ``opaque_dirs`` where an opaque
    # write may land (None: anywhere). A call at position ``i`` sees what sits after ``i``.
    position = {id(call): i for i, call in enumerate(all_calls)}
    trie = _ref_trie(_refs_asked(candidates))
    named: dict[str, int] = {}
    named_destructive: dict[str, int] = {}
    opaque_dirs: dict[str | None, int] = {}
    last_text = -1
    later: dict[int, tuple[bool, bool]] = {}  # id(call) -> (worktree, opaque) of later calls
    worktree = opaque = False
    for i in range(len(all_calls) - 1, -1, -1):
        call = all_calls[i]
        later[id(call)] = (worktree, opaque)
        text, wholesale, unknown = _possible_writes(call)
        if text:
            last_text = max(last_text, i)
            destructive = bool(_DESTRUCTIVE.search(text))
            for ref in _refs_named(text, trie):
                named.setdefault(ref, i)
                if destructive:
                    named_destructive.setdefault(ref, i)
            if unknown:
                opaque_dirs.setdefault(_opaque_dir(call, text), i)
        worktree = worktree or wholesale
        opaque = opaque or (bool(text) and unknown)
    duplicated = duplicate_ids(messages)
    use_disk = bool(root) and disk_check
    # A call outside the pinned tail can still have its result inside it.
    pinned = {m.message_index for m in messages if m.pinned}

    replaced: dict[str, dict[str, Any]] = {}
    reasons: dict[str, str] = {}
    def names_later(path: str, i: int, index: dict[str, int]) -> bool:
        name = path.rstrip("/").rsplit("/", 1)[-1]  # as ``_names_file``
        return bool(name) and (index.get(path, -1) > i or index.get(name, -1) > i)

    def command_changed(cmd: str, call: Any) -> bool:
        """A later call may have changed ``cmd``'s output. When in doubt, it did."""
        i = position[id(call)]
        wholesale, unknown = later[id(call)]
        if wholesale or unknown:
            return True
        paths = _command_paths(cmd)
        if paths is None:
            return last_text > i
        return any(names_later(p, i, named) for p in paths)

    def file_written(path: str, call: Any) -> bool:
        i = position[id(call)]
        wholesale, _unknown = later[id(call)]
        target = _resolved(path, _cwd(call))
        if any(
            at > i and (d is None or target is None or _under(target, d))
            for d, at in opaque_dirs.items()
        ):
            return True  # H1: a later opaque call may have written it
        return wholesale or names_later(path, i, named) or any(
            names_later(a, i, named_destructive) for a in _ancestors(path)
        )

    for call in candidates:
        result = call.result
        reason = "duplicate_tool_use_id" if call.id in duplicated else protected.get(call.id)
        if reason is None and _ANY_POINTER_RE.match(result.text):
            reason = "already_pointer"  # an earlier pass's pointer is a fixed point
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
        if reason is None and _temp(call):
            reason = "temp_path"
        hit: dict[str, Any] | None = None
        cwd = _cwd(call)
        if reason is None and read is not None:
            path, spec = read
            lines = _pointer_lines(call, body, spec)
            # Disk-authoritative: for a file pointer the disk check below replaces the proxy.
            disk_decides = use_disk and lines != "skip"
            target = _resolved(path, cwd)
            disk: dict[str, str] | None = None
            if not disk_decides and file_written(path, call):
                reason = "file_written_later"
            elif spec == "empty":
                reason = "read_range_empty"
            elif lines == "skip" and cmd is None:
                reason = "read_range_unknown"
            elif lines == "skip" and command_changed(cmd, call):  # type: ignore[arg-type]
                reason = "command_output_changed_later"
            elif lines == "skip" and not allow_command_pointers:
                reason = "command_pointers_disabled"
            elif target is None and (lines != "skip" or use_disk):
                reason = "relative_path_without_cwd"  # with the disk on: no file to check
            elif use_disk and ".." in posixpath.join(cwd or "", path).split("/"):
                # normpath collapses '..' lexically, the kernel follows symlinks first: the
                # checked file and the re-read file could differ, so never vouch for it.
                reason = "keep_disk_dotdot"
            elif use_disk and (
                state := _disk_check(call, target, spec, body, root)  # type: ignore[arg-type]
            )[0] != "ok":
                reason = state[0]
            else:
                disk = state[1] if use_disk else None
                # A tail range needs the file length: point at the command itself instead.
                note, recover = (
                    (_command_pointer(cmd, cwd), {"kind": "command", "command": cmd, "cwd": cwd})
                    if lines == "skip" and cmd is not None
                    else (_file_pointer(path, lines, cwd, disk_decides), {  # type: ignore[arg-type]
                        "kind": "file", "path": path, "cwd": cwd,
                        "lines": list(lines) if isinstance(lines, tuple) else None})
                )
                hit = {
                    "reason": "replace_disk_verified" if disk_decides else "recoverable_file_read",
                    "note": note,
                    "recover": recover,
                    "recoverability_check": "disk" if use_disk else "transcript_proxy",
                }
                if disk_decides:
                    hit["disk"] = disk
        elif reason is None and cmd is not None and is_read_only_command(cmd):
            if command_changed(cmd, call):
                reason = "command_output_changed_later"
        if hit is None and reason is None and cmd is not None and is_read_only_command(cmd):
            if not allow_command_pointers:
                reasons[call.id] = "command_pointers_disabled"
                continue
            hit = {
                "reason": "recoverable_read_only_command",
                "note": _command_pointer(cmd, cwd),
                "recover": {"kind": "command", "command": cmd, "cwd": cwd},
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


def _valid_pointers(call: Any, original: str, allow_command_pointers: bool) -> set[str]:
    """Every recovery pointer the planner could write for ``call`` and its original output:
    its own allowlisted command, or its own file with the exact line range and cwd."""
    pointers: set[str] = set()
    if _temp(call):
        return pointers
    cmd = shell_command(call)
    if allow_command_pointers and cmd is not None and is_read_only_command(cmd):
        pointers.add(_command_pointer(cmd, _cwd(call)))
    read = _file_read(call)
    if read is not None:
        lines = _pointer_lines(call, _body(original)[0], read[1])
        if lines != "skip" and _resolved(read[0], _cwd(call)) is not None:
            for verified in (False, True):
                pointers.add(_file_pointer(read[0], lines, _cwd(call), verified))  # type: ignore[arg-type]
    return pointers


def verify_recoverable(
    original_payload: Any, compacted_payload: Any, *, allow_command_pointers: bool = False
) -> list[str]:
    """Violations of the recoverable contract; ``[]`` is a pass.

    Messages, roles, texts and tool calls (id, tool, input) must be unchanged, and every
    changed result must be a valid lossless pointer or a recovery pointer whose path/command
    is its own call's (and, for a command, on the read-only allowlist).
    """
    from lcc.relevance.transcript import parse_transcript

    messages = parse_transcript(original_payload)
    calls = {call.id: call for message in messages for call in message.tool_calls}
    duplicated = duplicate_ids(messages)  # an ambiguous id never carries a pointer
    return verify_lossless(
        original_payload,
        compacted_payload,
        allow=lambda old, note: old.id in calls and old.id not in duplicated
        and note in _valid_pointers(calls[old.id], old.text, allow_command_pointers),
    )
