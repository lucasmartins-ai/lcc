#!/usr/bin/env python3
"""Long-session pattern: decisions-cache + prefix-marker + append-only (offline).

Simulates two agent turns. Each payload is compacted standalone (mechanical,
no key, no network) and appended to a session file whose bytes are never
rewritten — so a warm prompt cache survives. The second turn reuses sticky
decisions (`calls` drops) and proves the protected prefix is byte-identical
via `prefix_sha256`.

Usage:  python3 examples/long_session_cache.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

from lcc.relevance import RelevanceCompactionRequest, compact_context

OBJECTIVE = "reduce mobile booking friction"
MARKER = "<!-- lcc:cache-break -->"


SHARED_NOISE = (
    "Nightly chatter from the office channel: the plants need water on Tuesdays, "
    "the coffee machine grinds too loudly, and somebody keeps moving the mugs around."
)


def payload(n: int) -> str:
    return (
        f"TURN {n} evidence: the clinic booking widget keeps losing mobile visitors "
        f"at step two of the funnel, and the redesign shipped in June made it worse.\n\n"
        f"{SHARED_NOISE}\n\n"
    )


def compact(text: str, cache: Path, prefix_marker: str | None = None):
    return compact_context(
        RelevanceCompactionRequest(
            text=text,
            question=OBJECTIVE,
            provider="mechanical",
            decisions_cache_path=cache,
            prefix_marker=prefix_marker,
        )
    )


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="lcc-session-"))
    cache = tmp / "decisions.jsonl"
    session = tmp / "session.md"

    r1 = compact(payload(1), cache)
    session.write_text(r1.compacted_text, encoding="utf-8")
    before = session.read_bytes()

    # Turn 2: same chatter block returns from the sticky cache (no rescoring),
    # and everything before MARKER is untouchable.
    r2 = compact(MARKER + "\n" + payload(2), cache, prefix_marker=MARKER)
    session.write_text(
        before.decode() + "\n\n" + r2.compacted_text, encoding="utf-8"
    )

    print(f"session: {session}  cache: {cache}")
    print(f"turn1: dropped={r1.report.blocks_dropped} calls={r1.report.calls}")
    print(
        f"turn2: dropped={r2.report.blocks_dropped} calls={r2.report.calls} "
        f"reused={r2.report.reused_decisions} "
        f"prefix_untouched={r2.report.prefix_untouched}"
    )
    print(f"turn1 prefix_sha256: {r1.report.prefix_sha256[:16]}...")
    print(f"turn2 prefix_sha256: {r2.report.prefix_sha256[:16]}...")
    print("prior session bytes rewritten: False (append-only)")
    print(json.dumps({"ok": True, "session_chars": len(session.read_text())}))


if __name__ == "__main__":
    main()
