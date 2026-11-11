"""`lcc setup`: the Claude Code settings that make lcc run on its own.

One command for what the guide otherwise asks the user to write by hand in
``~/.claude/settings.json``, none of which a plugin can set for itself:

- ``env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE``: Claude Code compacts on its own at that share of the
  auto-compact window (40 unless the file already holds a value or ``compact_at`` is given);
- ``env.CLAUDE_CODE_ENABLE_FUNCTION_HOOKS``: lets the plugin answer that compaction verbatim;
- the plugin's ``provider: rules`` and ``rulesMode: stashed``: every output a pass removes goes
  to the local stash, one ``recall`` away;
- permission for the plugin's ``compact_transcript`` and ``recall`` tools;
- a ``UserPromptSubmit`` hook (``lcc hint --hook``) and a ``SessionStart`` hook
  (``lcc handoff --hook``).

Stdlib only. :func:`plan` is pure; :func:`write` is the only function that touches the disk.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

PLUGIN = "lcc@lcc"
THRESHOLD = "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"
DEFAULT_COMPACT_AT = 40
TOOLS = ("mcp__plugin_lcc_lcc__compact_transcript", "mcp__plugin_lcc_lcc__recall")
HINT = "lcc hint --hook"  # exactly the command line lcc.entry answers without loading the CLI
OFFER = "lcc handoff --hook"


class SetupError(ValueError):
    """The settings file cannot be read as settings, or changed under us."""


def load(path: Path) -> tuple[dict[str, Any], bytes]:
    """The settings object and the bytes it was read from (``{}``, ``b""`` for no file)."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, b""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SetupError(f"{path} is not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise SetupError(f"{path} does not hold a JSON object")
    return data, raw


def _child(parent: dict[str, Any], key: str, kind: type, where: str) -> Any:
    value = parent.setdefault(key, kind())
    if not isinstance(value, kind):
        raise SetupError(f"{where}.{key} is not {'an object' if kind is dict else 'a list'}")
    return value


def _covers(group: dict[str, Any], source: str) -> bool:
    """Claude Code reads a matcher as a regular expression over the event's source."""
    try:
        return re.fullmatch(str(group["matcher"]), source) is not None
    except re.error:
        return False


def plan(
    settings: dict[str, Any], compact_at: int | None = None
) -> tuple[dict[str, Any], list[str]]:
    """``settings`` with lcc set up, and one line per value that differs. ``settings`` is not
    mutated. Raises :class:`SetupError` when a section has the wrong type, rather than replace it.
    """
    new = copy.deepcopy(settings)
    changes: list[str] = []

    def put(target: dict[str, Any], key: str, value: str, label: str) -> None:
        if target.get(key) != value:
            old = json.dumps(target[key]) if key in target else "unset"
            changes.append(f"{label}: {old} -> {json.dumps(value)}")
            target[key] = value

    env = _child(new, "env", dict, "settings")
    # A threshold the user already chose stands unless this run names another.
    threshold = str(compact_at) if compact_at else env.get(THRESHOLD, str(DEFAULT_COMPACT_AT))
    put(env, THRESHOLD, threshold, f"env.{THRESHOLD}")
    put(env, "CLAUDE_CODE_ENABLE_FUNCTION_HOOKS", "1", "env.CLAUDE_CODE_ENABLE_FUNCTION_HOOKS")

    configs = _child(new, "pluginConfigs", dict, "settings")
    plugin = _child(configs, PLUGIN, dict, "settings.pluginConfigs")
    options = _child(plugin, "options", dict, PLUGIN)
    put(options, "provider", "rules", f"{PLUGIN} provider")
    put(options, "rulesMode", "stashed", f"{PLUGIN} rulesMode")

    allow = _child(_child(new, "permissions", dict, "settings"), "allow", list, "permissions")
    for tool in TOOLS:
        if tool not in allow:
            allow.append(tool)
            changes.append(f"permissions.allow: + {tool}")

    hooks = _child(new, "hooks", dict, "settings")
    for event, command, entry in (
        ("UserPromptSubmit", HINT, {"hooks": [{"type": "command", "command": HINT, "timeout": 5}]}),
        (
            "SessionStart",
            OFFER,
            {"matcher": "startup", "hooks": [{"type": "command", "command": OFFER, "timeout": 10}]},
        ),
    ):
        groups = _child(hooks, event, list, "settings.hooks")
        matcher = str(entry.get("matcher", ""))
        wired = any(
            isinstance(hook, dict) and hook.get("command") == command
            for group in groups
            # The same command under a matcher that leaves this one out is not wired.
            if isinstance(group, dict)
            and (not matcher or group.get("matcher") in (None, "", "*") or _covers(group, matcher))
            for hook in group.get("hooks") or []
        )
        if not wired:
            groups.append(entry)
            changes.append(f"hooks.{event}: + {command}")
    return new, changes


def plugin_enabled(settings: dict[str, Any]) -> bool:
    enabled = settings.get("enabledPlugins")
    return isinstance(enabled, dict) and enabled.get(PLUGIN) is True


def _staged(path: Path, data: bytes, mode: int) -> str:
    """``data`` in a finished temporary file beside ``path``, ready to be renamed onto it. It
    is never readable by more than ``mode`` allows: mkstemp starts at 0600."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, mode)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return tmp


def write(path: Path, settings: dict[str, Any], expect: bytes) -> Path | None:
    """Replace ``path`` atomically with ``settings``, keeping its mode. The first run leaves
    ``expect`` (the bytes :func:`load` returned) at ``<name>.before-lcc-setup`` and returns that
    path. Refuses when the file no longer holds ``expect``: another program wrote it meanwhile.
    """
    target = path.resolve()  # a symlinked settings file (dotfiles) stays a symlink
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    backup = target.with_name(target.name + ".before-lcc-setup")
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = 0o600
    keep = bool(expect) and not backup.exists()
    staged = [(_staged(target, data, mode), target)]
    try:
        if keep:
            staged.insert(0, (_staged(backup, expect, mode), backup))
        try:
            current = target.read_bytes()
        except FileNotFoundError:
            current = b""
        # Checked with both files staged, so only the renames follow. ponytail: Claude Code
        # takes no lock on this file; a write landing between this read and them is lost.
        if current != expect:
            raise SetupError(f"{path} changed while lcc setup ran; run it again")
        for tmp, final in staged:
            os.replace(tmp, final)
    finally:
        for tmp, _ in staged:
            with contextlib.suppress(OSError):  # renamed already: nothing left to remove
                os.unlink(tmp)
    return backup if keep else None
