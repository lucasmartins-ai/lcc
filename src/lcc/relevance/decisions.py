"""Sticky decision cache for instant relevance compaction (ADR 0013).

Why sticky decisions exist (cache alignment): prompt/KV caches are keyed on byte-stable
prefixes. A relevance pass that re-scores every block on every run can flip borderline
decisions as the model's judgment wobbles, silently changing bytes in the middle of a
cached prefix and turning cheap cache reads into expensive cache writes. Sticky decisions
pin the outcome for an ``(objective, block content)`` pair: unchanged blocks keep their
previous decision on every later run, so the compacted output stays byte-stable and the
downstream cache survives. Invalidate by deleting the cache file, or by changing the
objective (which is part of the key, so a new objective is a natural cache epoch).

Format: JSONL, one record per decision, append-only::

    {"k": "<sha256>", "objective_sha256": "...", "block_sha256": "...",
     "score": 0.18, "decision": "drop", "provider": "jev"}
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DECISIONS_CACHE_SCHEMA_VERSION = "relevance-decisions-1.0"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def decision_key(objective: str, block_text: str) -> str:
    """Stable key for an ``(objective, block)`` pair; content-addressed on both sides."""
    return _sha256(f"{_sha256(objective)}:{_sha256(block_text)}")


@dataclass(frozen=True)
class CachedDecision:
    score: float | None
    decision: str
    provider: str


class DecisionCache:
    """Load/append sticky decisions; safe to disable by passing ``path=None``."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._entries: dict[str, CachedDecision] = {}
        self._pending: list[dict[str, Any]] = []
        self.reused = 0
        self.written = 0

    def load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = record.get("k")
            decision = record.get("decision")
            if not isinstance(key, str) or decision not in ("keep", "drop"):
                continue
            score = record.get("score")
            self._entries[key] = CachedDecision(
                score=float(score) if isinstance(score, (int, float)) else None,
                decision=str(decision),
                provider=str(record.get("provider", "unknown")),
            )

    def get(self, key: str) -> CachedDecision | None:
        entry = self._entries.get(key)
        if entry is not None:
            self.reused += 1
        return entry

    def put(self, key: str, *, objective: str, block_text: str, entry: CachedDecision) -> None:
        self._entries[key] = entry
        self._pending.append(
            {
                "schema_version": DECISIONS_CACHE_SCHEMA_VERSION,
                "k": key,
                "objective_sha256": _sha256(objective),
                "block_sha256": _sha256(block_text),
                "score": entry.score,
                "decision": entry.decision,
                "provider": entry.provider,
            }
        )

    def flush(self) -> None:
        if self.path is None or not self._pending:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                for record in self._pending:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.written = len(self._pending)
        except OSError:
            pass  # decision caching must never break compaction
        finally:
            self._pending.clear()
