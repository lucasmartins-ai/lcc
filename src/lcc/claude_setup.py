"""`lcc setup`: the Claude Code settings that make lcc run on its own.

One command for what the guide otherwise asks the user to write by hand in
``~/.claude/settings.json``, none of which a plugin can set for itself:

- ``env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE``: only when ``compact_at`` is given, and only when that
  share of the auto-compact window is at least :data:`MIN_COMPACT_TOKENS`; an override already
  in the file that compacts under it is removed (see :func:`too_early`);
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
import math
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

PLUGIN = "lcc@lcc"
THRESHOLD = "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"
WINDOW = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
DEFAULT_WINDOW = 200_000  # Claude Code's auto-compact window when WINDOW is unset (200k models)
# ponytail: a session's fixed load (memory files, tools, MCP and skill listings) measured ~110k
# input tokens per request; 40 % of a 300k window (120k) compacted 8 times in 10 minutes. 150k
# leaves room for work above that load. A leaner setup could go lower; raise it if loads grow.
MIN_COMPACT_TOKENS = 150_000
# ponytail: Claude Code is reported to cap the window variable at 1M (not verified here); capping
# can only make setup stricter, never let a threshold under the floor through.
MAX_WINDOW = 1_000_000
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


def window(settings: dict[str, Any], environ: dict[str, str] | None = None) -> int:
    """The auto-compact window sessions get: a key in the settings file's ``env`` wins over
    ``environ`` (even when empty), capped at :data:`MAX_WINDOW`. A value that is not a positive
    integer counts as unset: :data:`DEFAULT_WINDOW`, the strictest guess."""
    env = settings.get("env")
    source = env if isinstance(env, dict) and WINDOW in env else environ or {}
    raw = str(source.get(WINDOW, "")).strip()
    return min(int(raw), MAX_WINDOW) if raw.isdigit() and int(raw) > 0 else DEFAULT_WINDOW


def _percent(value: Any) -> float | None:
    """A threshold as Claude Code reads it (``"40"``, ``"40.0"``), or None when not a number."""
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def too_early(percent: float, tokens: int) -> str | None:
    """Why compacting at ``percent`` of a ``tokens`` window thrashes, or None when it does not."""
    at = int(percent * tokens // 100)
    if at >= MIN_COMPACT_TOKENS:
        return None
    least = -(-MIN_COMPACT_TOKENS * 100 // tokens)  # ceiling division
    hint = f"use {least} or more" if least <= 100 else "leave it unset"
    return (
        f"{percent:g} % of the {tokens}-token auto-compact window is {at} tokens, under the "
        f"{MIN_COMPACT_TOKENS} a session needs above its fixed load; Claude Code would compact "
        f"again right after each compaction ({hint})"
    )


def plan(
    settings: dict[str, Any],
    compact_at: int | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """``settings`` with lcc set up, and one line per value that differs. ``settings`` is not
    mutated. ``environ`` supplies the auto-compact window when the file does not. Raises
    :class:`SetupError` when a section has the wrong type, rather than replace it, and when
    ``compact_at`` would compact too early (:func:`too_early`).
    """
    new = copy.deepcopy(settings)
    changes: list[str] = []

    def put(target: dict[str, Any], key: str, value: str, label: str) -> None:
        if target.get(key) != value:
            old = json.dumps(target[key]) if key in target else "unset"
            changes.append(f"{label}: {old} -> {json.dumps(value)}")
            target[key] = value

    env = _child(new, "env", dict, "settings")
    tokens = window(new, environ)
    if compact_at:
        if reason := too_early(compact_at, tokens):
            raise SetupError(f"--compact-at {compact_at}: {reason}")
        put(env, THRESHOLD, str(compact_at), f"env.{THRESHOLD}")
    elif THRESHOLD in env:
        # A threshold already in the file stands, unless it thrashes: an earlier setup wrote 40
        # next to a 300k window. One that is not a number is the user's business: left alone.
        current = _percent(env[THRESHOLD])
        if current is not None and (reason := too_early(current, tokens)):
            old = json.dumps(env.pop(THRESHOLD))
            changes.append(f"env.{THRESHOLD}: {old} -> unset ({reason})")
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
