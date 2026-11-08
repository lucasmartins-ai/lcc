"""The ``lcc`` console script.

``lcc hint --hook`` runs on every Claude Code prompt, so it answers here without loading the
CLI: typer, rich and the modules behind every other command cost about 0.25 s per prompt.
Any other command line goes to :func:`lcc.cli.cli_main` unchanged. Keep this module's imports
to the standard library.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

_HINT_TAIL = 16_000_000


def read_tail(path: str | Path | None, limit: int = _HINT_TAIL) -> str:
    """The last ``limit`` bytes of a transcript, or "" when it cannot be read.

    ponytail: a long session's JSONL can pass 600 MB, and reading it whole costs a second per
    prompt. Recent pointers sit at the end, and the session's sidecars cover older stashes.
    """
    if not path:
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - limit))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def hint_hook() -> None:
    """Answer a Claude Code UserPromptSubmit event on stdin with ``additionalContext``.

    A prompt hook must never block or break the prompt (exit 2 would block it): every step, the
    import and the final flush included, sits inside the guard, and any error prints nothing.
    """
    try:
        from lcc.relevance.recall_hints import hint_line, hints_for

        event = json.loads(sys.stdin.read() or "null")
        if not isinstance(event, dict) or not isinstance(event.get("prompt"), str):
            return
        path = event.get("transcript_path")
        session_id = event.get("session_id")
        found = hints_for(
            event["prompt"],
            transcript=read_tail(path if isinstance(path, str) else None),
            session_id=session_id if isinstance(session_id, str) else None,
        )
        if found:
            context = "\n".join(hint_line(h) for h in found)
            answer = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
            sys.stdout.write(json.dumps(answer) + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001 - see above: a hint is never worth a failed prompt
        # A reader that closed the pipe would fail the flush again at exit: point stdout
        # at /dev/null so the interpreter shuts down with code 0.
        with contextlib.suppress(Exception):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def main() -> None:
    """Console-script entry point (``lcc``)."""
    if sys.argv[1:] == ["hint", "--hook"]:  # exactly what the documented hook runs
        hint_hook()
        return
    from lcc.cli import cli_main

    cli_main()
