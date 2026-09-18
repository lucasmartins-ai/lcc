"""Reproducible benchmark metadata (ADR 0014).

Every benchmark result must record the full identity of what produced it: corpus and
objective hashes, requested vs resolved model, provider, policy/schema/tokenizer
versions, timestamp, configuration, thresholds and seed. A moving alias such as
``jev-latest`` is never the only model identifier — the resolved version is recorded
alongside it.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from lcc.relevance.compactor import RELEVANCE_SCHEMA_VERSION
from lcc.relevance.decisions import (
    BLOCK_PARSER_VERSION,
    POLICY_VERSION,
    PROTECTION_VERSION,
    RELATIONSHIP_VERSION,
)
from lcc.relevance.trim import TRIM_POLICY_VERSION

BENCH_METADATA_VERSION = "bench-metadata-1.0"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BenchmarkMetadata:
    """Identity of one benchmark measurement; JSON-serializable via :func:`metadata_to_dict`."""

    metadata_version: str = BENCH_METADATA_VERSION
    corpus_sha256: str = ""
    objective_sha256: str = ""
    requested_model: str = ""
    resolved_model: str | None = None
    provider: str = ""
    policy_version: str = POLICY_VERSION
    schema_version: str = RELEVANCE_SCHEMA_VERSION
    block_parser_version: str = BLOCK_PARSER_VERSION
    protection_version: str = PROTECTION_VERSION
    relationship_version: str = RELATIONSHIP_VERSION
    trim_policy_version: str = TRIM_POLICY_VERSION
    tokenizer_id: str = ""
    tokenizer_version: str | None = None
    token_count_method: str = ""
    timestamp: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None


def build_metadata(
    *,
    corpus: str,
    objective: str,
    requested_model: str,
    resolved_model: str | None = None,
    provider: str = "",
    configuration: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    seed: int | None = None,
    tokenizer_id: str = "",
    tokenizer_version: str | None = None,
    token_count_method: str = "",
) -> BenchmarkMetadata:
    """Build metadata for one measurement; timestamp is UTC ISO-8601."""
    return BenchmarkMetadata(
        corpus_sha256=_sha256(corpus),
        objective_sha256=_sha256(objective),
        requested_model=requested_model,
        resolved_model=resolved_model or requested_model,
        provider=provider,
        configuration=dict(configuration or {}),
        thresholds=dict(thresholds or {}),
        seed=seed,
        tokenizer_id=tokenizer_id,
        tokenizer_version=tokenizer_version,
        token_count_method=token_count_method,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


def metadata_to_dict(meta: BenchmarkMetadata) -> dict[str, Any]:
    return asdict(meta)
