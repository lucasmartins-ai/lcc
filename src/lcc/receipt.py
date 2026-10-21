"""The receipt a tool-call compaction pass prints, and the opt-in local ledger.

``receipt_line`` is the one line shown after every pass (CLI and the Claude Code hook):
what was removed, tokens before and after, and how to get it back. ``receipt_full`` is the
``--receipt`` form: the largest stashed outputs with their ``recall`` ids and the cache effect.
Both read only the pass's report; neither touches the transcript.

The ledger is OFF unless the caller asks (``ledger: true`` from the plugin option) or
``LCC_LEDGER=1``. It appends one JSON line per pass to ``~/.cache/lcc/ledger.jsonl``
(``LCC_LEDGER_PATH``): counts and fixed labels only, never text, paths or tool inputs, and
the session id only as a truncated SHA-256. Nothing is ever sent anywhere. The Claude Code
statusline (``plugins/claude-code/scripts/statusline.mjs``) reads it.
"""

from __future__ import annotations

import hashlib
import json
import os
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lcc.reporting.explain import terminal_safe

ENV_FLAG = "LCC_LEDGER"
ENV_PATH = "LCC_LEDGER_PATH"
LEDGER_VERSION = 1


def _n(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _stashed(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Stashed outputs, largest first (only when the report still carries its decisions)."""
    found = [
        {
            "id": d["stash"]["sha256"][:12],
            "tokens": _n(d["stash"].get("tokens")),
            "tool": d.get("tool"),
        }
        for d in report.get("decisions") or ()
        if isinstance(d, dict) and isinstance(d.get("stash"), dict) and d["stash"].get("sha256")
    ]
    return sorted(found, key=lambda item: (-item["tokens"], item["id"]))


def _removed(report: dict[str, Any]) -> list[str]:
    stashed = _n(report.get("tool_calls_stashed"))
    # "replace" counts stashed outputs too; the rest are lossless/recoverable pointers.
    pointers = _n(report.get("tool_calls_replaced")) - stashed
    parts = [
        (stashed, "stashed"),
        (_n(report.get("tool_calls_deduped")), "deduped"),
        (pointers, "replaced by a pointer"),
        (_n(report.get("tool_calls_dropped")), "dropped"),
        (_n(report.get("tool_calls_trimmed")), "trimmed"),
    ]
    return [f"{count} {label}" for count, label in parts if count > 0]


def _recall_hint(report: dict[str, Any]) -> str:
    stashed = _n(report.get("tool_calls_stashed"))
    largest = _stashed(report)
    if stashed and largest:
        more = f" (+{stashed - 1} more)" if stashed > 1 else ""
        return f"recall: lcc recall {largest[0]['id']}{more}"
    if stashed:
        return "recall: lcc recall <id> from each [removed: ...] placeholder"
    if _n(report.get("tool_calls_dropped")) or _n(report.get("tool_calls_trimmed")):
        return "dropped/trimmed outputs are not recallable (use rules_mode stashed for that)"
    return "nothing to recall: each removed output is still in context or on disk"


def receipt_line(report: dict[str, Any]) -> str:
    """One line: tokens before -> after, what was removed, how to get it back."""
    before = _n(report.get("tokens_before"))
    after = _n(report.get("tokens_after"))
    removed = _removed(report)
    if not removed or before <= after:
        return f"lcc: nothing removed ({before:,} tokens)"
    saved = before - after
    share = saved / before if before else 0.0
    return (
        f"lcc: {before:,} -> {after:,} tokens (-{saved:,}, -{share:.1%}) · "
        f"{', '.join(removed)} · {_recall_hint(report)}"
    )


def receipt_full(report: dict[str, Any], top: int = 5) -> str:
    """The ``--receipt`` form: the one line, then the largest stashed outputs and cache effect."""
    lines = [receipt_line(report)]
    method = report.get("token_count_method")
    if method:
        lines.append(f"  token count: {method}")
    largest = _stashed(report)
    if largest:
        lines.append(f"  largest stashed outputs ({min(top, len(largest))} of {len(largest)}):")
        for item in largest[:top]:
            # Tool names come from the transcript: escape them before they reach a terminal.
            tool = f"  {terminal_safe(str(item['tool']))}" if item.get("tool") else ""
            lines.append(f"    lcc recall {item['id']}  {item['tokens']:,} tokens{tool}")
    cache = report.get("cache_effect")
    if isinstance(cache, dict):
        delta = cache.get("estimated_relative_cost_delta")
        delta_text = f", est. cost {delta:+.1%}" if isinstance(delta, (int, float)) else ""
        lines.append(
            f"  cache ({cache.get('cache_state', 'unknown')}): "
            f"{_n(cache.get('stable_prefix_tokens')):,} tokens stay cached, "
            f"{_n(cache.get('rewritten_tokens')):,} re-written{delta_text}; "
            f"{'recommended' if cache.get('recommended') else 'not recommended'} "
            f"({cache.get('reason', 'unknown')})"
        )
    return "\n".join(lines)


def ledger_path() -> Path:
    return Path(os.environ.get(ENV_PATH) or Path.home() / ".cache" / "lcc" / "ledger.jsonl")


def ledger_enabled(requested: bool = False) -> bool:
    return requested or os.environ.get(ENV_FLAG) == "1"


def pass_stands(report: dict[str, Any]) -> bool:
    """The hook's own rule (``decideReplacement``): judged, over the minimum, removed something."""
    removed = sum(
        _n(report.get(key))
        for key in (
            "tool_calls_dropped",
            "tool_calls_trimmed",
            "tool_calls_deduped",
            "tool_calls_replaced",
        )
    )
    return report.get("degraded") is not True and report.get("worth_it") is True and removed > 0


def session_key(session_id: Any) -> str | None:
    """Truncated SHA-256 of the session id; the statusline hashes the same way to match."""
    if not isinstance(session_id, str) or not session_id:
        return None
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def ledger_record(report: dict[str, Any], *, session_id: Any = None) -> dict[str, Any]:
    """Counts and fixed labels only. Never text, never paths, never tool names or inputs."""
    return {
        "v": LEDGER_VERSION,
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": session_key(session_id),
        "provider": str(report.get("provider_used") or "unknown")[:32],
        "tokens_before": _n(report.get("tokens_before")),
        "tokens_after": _n(report.get("tokens_after")),
        "stashed": _n(report.get("tool_calls_stashed")),
        "deduped": _n(report.get("tool_calls_deduped")),
        "replaced": _n(report.get("tool_calls_replaced")),
        "dropped": _n(report.get("tool_calls_dropped")),
        "trimmed": _n(report.get("tool_calls_trimmed")),
    }


def append_ledger(record: dict[str, Any]) -> None:
    """Append one line (dir ``0700``, file ``0600``). A failure warns and never fails the pass."""
    path = ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            # O_CREAT's mode only applies to a new file; tighten one that already exists.
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError as exc:
        warnings.warn(f"lcc ledger not written ({path}): {exc}", RuntimeWarning, stacklevel=2)
