"""Opt-in compilation for an explicit observation scope and a local engine.

Separate from general KEEP relevance. The caller supplies entity/field/UTC slots;
unknown grammar, missing runtime or invalid receipts keep the source whole. No
provider default, CLI, cache or semantic verification setting is changed here.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from lcc.relevance.blocks import gaps_between, split_blocks


@dataclass(frozen=True)
class ObservationCompilationResult:
    compacted_text: str
    report: dict[str, Any]


def _scope(scope: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in ("entity", "field", "start", "end"):
        value = getattr(scope, name, None)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Explicit entity, field, start and end slots are required")
        values[name] = value
    for name in ("start", "end"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", values[name]):
            raise ValueError("UTC timestamp slots are required")
        try:
            datetime.strptime(values[name], "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise ValueError("Invalid UTC timestamp") from exc
    if values["start"] > values["end"]:
        raise ValueError("Window start must be at or before its end")
    return values


def compact_observations(
    text: str,
    scope: Any,
    *,
    engine: Any = None,
    min_block_chars: int = 80,
    max_block_chars: int = 6000,
    protect_prefix_chars: int = 0,
) -> ObservationCompilationResult:
    """Remove only verified NO_MATCH slices; preserve all other bytes and gaps."""
    slots = _scope(scope)
    if (
        not isinstance(text, str)
        or type(min_block_chars) is not int
        or min_block_chars < 0
        or type(max_block_chars) is not int
        or max_block_chars < 1
        or type(protect_prefix_chars) is not int
        or protect_prefix_chars < 0
    ):
        raise ValueError("Text and valid nonnegative/positive segmentation limits are required")
    started = time.perf_counter()
    blocks = split_blocks(text, min_block_chars=min_block_chars, max_block_chars=max_block_chars)
    protected = {b.id for b in blocks if b.protected or b.character_start < protect_prefix_chars}
    candidates = [{"id": b.id, "text": b.text} for b in blocks if b.id not in protected]
    expected = {b["id"]: hashlib.sha256(b["text"].encode()).hexdigest() for b in candidates}
    decisions: dict[str, str] = {}
    raw = None
    degraded = None
    if candidates:
        if (
            getattr(engine, "is_local", False) is not True
            or not callable(getattr(engine, "rank_observations", None))
            or not callable(getattr(engine, "supports_operation", None))
        ):
            degraded = "observation_engine_unavailable"
        else:
            try:
                if engine.supports_operation("rank_observations") is not True:
                    raise ValueError("Unsupported operation")
                raw = engine.rank_observations(scope, candidates)
                if (
                    not isinstance(raw, dict)
                    or raw.get("schema") != "lcc-observation-ranking/0.1"
                    or raw.get("operation") != "rank_observations"
                    or raw.get("is_local") is not True
                    or not isinstance(raw.get("items"), list)
                    or len(raw["items"]) != len(candidates)
                ):
                    raise ValueError("Invalid response envelope")
                for item in raw["items"]:
                    if not isinstance(item, dict):
                        raise ValueError("Invalid item")
                    identity = item.get("id")
                    if (
                        not isinstance(identity, str)
                        or identity not in expected
                        or identity in decisions
                        or item.get("text_sha256") != expected[identity]
                        or item.get("status") not in ("MATCH", "NO_MATCH", "UNKNOWN")
                        or item.get("decision")
                        != ("DROP" if item.get("status") == "NO_MATCH" else "KEEP")
                    ):
                        raise ValueError("Invalid observation response")
                    decisions[identity] = item["status"]
                if set(decisions) != set(expected):
                    raise ValueError("Missing block response")
            except Exception:
                decisions = {}
                degraded = "invalid_observation_response"
    gaps = gaps_between(text, blocks)
    output = []
    details = []
    for index, block in enumerate(blocks):
        status = "PROTECTED" if block.id in protected else decisions.get(block.id, "UNKNOWN")
        drop = status == "NO_MATCH"
        output.append(gaps[index])
        if not drop:
            output.append(block.text)
        details.append(
            {
                "id": block.id,
                "status": status,
                "decision": "DROP" if drop else "KEEP",
                "character_start": block.character_start,
                "character_end": block.character_end,
                "text_sha256": hashlib.sha256(block.text.encode()).hexdigest(),
            }
        )
    output.append(gaps[-1])
    compiled = "".join(output)
    return ObservationCompilationResult(
        compiled,
        {
            "schema": "lcc-observation-compilation/0.1",
            "operation": "rank_observations",
            "mode": "experimental_selection",
            "scope": slots,
            "is_local": True,
            "blocks_total": len(blocks),
            "blocks_dropped": sum(r["decision"] == "DROP" for r in details),
            "blocks_unknown": sum(r["status"] == "UNKNOWN" for r in details),
            "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "output_sha256": hashlib.sha256(compiled.encode()).hexdigest(),
            "input_bytes": len(text.encode()),
            "output_bytes": len(compiled.encode()),
            "decisions": details,
            "degraded": degraded is not None,
            "degradation_reason": degraded,
            "semantic_guarantee": "none",
            "necessity_estimated": False,
            "set_sufficiency_estimated": False,
            "ranking_receipt": raw,
            "compilation_ms": (time.perf_counter() - started) * 1000,
        },
    )
