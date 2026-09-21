"""Sticky decision cache for instant relevance compaction (ADR 0013, ADR 0014).

Why sticky decisions exist (cache alignment): prompt/KV caches are keyed on byte-stable
prefixes. A relevance pass that re-scores every block on every run can flip borderline
decisions as the model's judgment wobbles, silently changing bytes in the middle of a
cached prefix and turning cheap cache reads into expensive cache writes. Sticky decisions
pin the outcome for an ``(objective, block content, policy)`` triple: unchanged blocks
under an unchanged policy keep their previous decision on every later run, so the
compacted output stays byte-stable and the downstream cache survives. Invalidate by
deleting the cache file, or by changing the objective (which is part of the key, so a new
objective is a natural cache epoch). Changing the policy, model, thresholds or parser
also starts a new epoch: same content + different policy is a different decision.

Cache identity (v1.1): the key covers every semantic input that can change the decision
(objective, block bytes, provider, model, resolved model version, policy version,
thresholds, trim policy, parser/schema version, protection version, relationship
version, tokenizer identity). Canonical JSON (sorted keys, compact separators) is hashed
so field order never causes a spurious miss, and omitting a policy field never causes a
spurious hit. Whitespace behaviour is explicit: block bytes are hashed exactly as
emitted by the block splitter, with no normalisation — a trailing space is a different
block.

Format: JSONL, one record per decision, append-only::

    {"k": "<sha256>", "objective_sha256": "...", "block_sha256": "...",
     "score": 0.18, "decision": "drop", "provider": "jev"}

v1.0 records (objective+block only) still load, but v1.1 lookups never hit them: the
policy change is itself a cache epoch, which is the safe direction (a stale hit would
silently reuse a decision made under different rules).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lcc.relevance.trim import TRIM_POLICY_VERSION

DECISIONS_CACHE_SCHEMA_VERSION = "relevance-decisions-1.1"

#: Policy identity components. Bumped only when the corresponding logic changes; every
#: component participates in the v1.2 cache key so a logic change is a cache epoch.
POLICY_VERSION = "relevance-compaction-1.2"
BLOCK_PARSER_VERSION = "blocks-1.0"
PROTECTION_VERSION = "protection-1.1"
RELATIONSHIP_VERSION = "relationships-1.0"
# NOTE: TRIM_POLICY_VERSION lives in lcc.relevance.trim (single source of truth) and is
# re-exported here so identity builders do not need a second import.

__all__ = [
    "BLOCK_PARSER_VERSION",
    "DECISIONS_CACHE_SCHEMA_VERSION",
    "POLICY_VERSION",
    "PROTECTION_VERSION",
    "RELATIONSHIP_VERSION",
    "TRIM_POLICY_VERSION",
    "CachedDecision",
    "DecisionCache",
    "build_decision_identity",
    "canonical_dumps",
    "decision_key",
    "decision_key_v2",
]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_dumps(payload: dict[str, Any]) -> str:
    """Canonical JSON: sorted keys, compact separators, UTF-8. Field order is stable."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def decision_key(objective: str, block_text: str) -> str:
    """Legacy v1.0 key for an ``(objective, block)`` pair; content-addressed on both sides.

    Kept for backwards compatibility (old tests, old cache readers). New code must use
    :func:`decision_key_v2`, which additionally binds the policy/model/threshold state.
    Block bytes are hashed exactly — no whitespace normalisation.
    """
    return _sha256(f"{_sha256(objective)}:{_sha256(block_text)}")


def build_decision_identity(
    *,
    objective: str,
    block_text: str,
    provider: str = "mechanical",
    model: str = "",
    resolved_model: str | None = None,
    policy_version: str = POLICY_VERSION,
    threshold: float = 0.4,
    trim_threshold: float | None = None,
    trim_head_chars: int = 300,
    trim_policy_version: str = TRIM_POLICY_VERSION,
    parser_version: str = BLOCK_PARSER_VERSION,
    protection_version: str = PROTECTION_VERSION,
    relationship_version: str = RELATIONSHIP_VERSION,
    tokenizer_id: str | None = None,
    deterministic_protection: bool = True,
    relationship_context: str | None = None,
    laya_temperature: float | None = None,
    semantic_verify: bool = False,
    verifier_model: str | None = None,
    verifier_policy_version: str | None = None,
) -> dict[str, Any]:
    """Build the canonical identity dict hashed by :func:`decision_key_v2`.

    All floats are rounded to 6dp so ``0.4`` and ``0.4000000001`` do not fork the cache.
    ``None`` is preserved as null (distinct from ``""``) so an absent trim band and an
    explicit ``0.0`` band never collide.

    Verifier keys are appended only when ``semantic_verify`` is true, so every
    existing ``semantic_verify=False`` identity — and every sticky record written
    before the verifier existed — hashes exactly as before. Enabling the verifier
    is a cache epoch (a different decision context), which is the safe direction.
    """
    identity: dict[str, Any] = {
        "objective_sha256": _sha256(objective),
        "block_sha256": _sha256(block_text),
        "provider": provider,
        "model": model,
        "resolved_model": resolved_model,
        "policy_version": policy_version,
        "threshold": round(float(threshold), 6),
        "trim_threshold": None if trim_threshold is None else round(float(trim_threshold), 6),
        "trim_head_chars": int(trim_head_chars),
        "trim_policy_version": trim_policy_version,
        "parser_version": parser_version,
        "protection_version": protection_version,
        "relationship_version": relationship_version,
        "tokenizer_id": tokenizer_id,
        "deterministic_protection": bool(deterministic_protection),
        "relationship_context": relationship_context,
        "laya_temperature": None
        if laya_temperature is None
        else round(float(laya_temperature), 6),
    }
    if semantic_verify:
        identity["semantic_verify"] = True
        identity["verifier_model"] = verifier_model
        identity["verifier_policy_version"] = verifier_policy_version
    return identity


def decision_key_v2(identity: dict[str, Any]) -> str:
    """Stable key for a full decision identity; canonical serialisation before hashing."""
    return _sha256(canonical_dumps(identity))


@dataclass(frozen=True)
class CachedDecision:
    score: float | None
    decision: str
    provider: str
    reason: str | None = None


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
            if not isinstance(key, str) or decision not in ("keep", "trim", "drop"):
                continue
            score = record.get("score")
            reason = record.get("reason")
            self._entries[key] = CachedDecision(
                score=float(score) if isinstance(score, (int, float)) else None,
                decision=str(decision),
                provider=str(record.get("provider", "unknown")),
                reason=reason if isinstance(reason, str) else None,
            )

    def get(self, key: str) -> CachedDecision | None:
        entry = self._entries.get(key)
        if entry is not None:
            self.reused += 1
        return entry

    def put(
        self,
        key: str,
        *,
        objective: str,
        block_text: str,
        entry: CachedDecision,
        identity: dict[str, Any] | None = None,
    ) -> None:
        self._entries[key] = entry
        record: dict[str, Any] = {
            "schema_version": DECISIONS_CACHE_SCHEMA_VERSION,
            "k": key,
            "objective_sha256": _sha256(objective),
            "block_sha256": _sha256(block_text),
            "score": entry.score,
            "decision": entry.decision,
            "provider": entry.provider,
            "reason": entry.reason,
        }
        if identity is not None:
            # Audit trail: record the policy state that produced the decision without
            # affecting the key (the key already binds it).
            record["identity"] = identity
        self._pending.append(record)

    def stats(self) -> dict[str, int]:
        """Size accounting for GC planning (append-only growth observability)."""
        lines = 0
        byte_size = 0
        if self.path is not None and self.path.is_file():
            try:
                raw = self.path.read_bytes()
                byte_size = len(raw)
                lines = raw.count(b"\n")
            except OSError:
                pass
        return {
            "entries": len(self._entries),
            "pending": len(self._pending),
            "reused": self.reused,
            "written": self.written,
            "file_lines": lines,
            "file_bytes": byte_size,
        }

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
