"""Opt-in instant relevance compaction (ADR 0013).

Drops context blocks that are irrelevant to an objective before a larger model ever sees
them. Two modes:

- ``provider="jev"``/``"auto"``: narrow model judgment (TypeSafe System One, "Jev") scores
  every candidate block in batches; blocks below ``threshold`` are dropped.
- ``provider="mechanical"``: fully local fallback that only drops blocks with zero lexical
  overlap with the objective. Used automatically when no API key is configured.

Everything is conservative: kept bytes are re-emitted exactly, blocks that are short or
match ``keep_patterns`` are never scored, and any failure keeps content rather than
dropping it. Sticky decisions (``decisions_cache_path``) keep the output byte-stable across
runs so downstream prompt/KV caches survive (see ``docs/CACHE_ALIGNMENT.md``).
"""

from __future__ import annotations

from lcc.relevance.blocks import (
    BLOCK_ID_RE,
    DEFAULT_MAX_BLOCK_CHARS,
    DEFAULT_MIN_BLOCK_CHARS,
    TextBlock,
    block_id,
    gaps_between,
    reconstruct,
    split_blocks,
)
from lcc.relevance.compactor import (
    RELEVANCE_SCHEMA_VERSION,
    BlockDecision,
    RelevanceCompactionReport,
    RelevanceCompactionRequest,
    RelevanceCompactionResult,
    compact_context,
    report_to_dict,
)
from lcc.relevance.decisions import (
    BLOCK_PARSER_VERSION,
    DECISIONS_CACHE_SCHEMA_VERSION,
    POLICY_VERSION,
    PROTECTION_VERSION,
    RELATIONSHIP_VERSION,
    DecisionCache,
    build_decision_identity,
    canonical_dumps,
    decision_key,
    decision_key_v2,
)
from lcc.relevance.graph import ContextGraph, EdgeType, GraphEdge, build_graph
from lcc.relevance.jev import (
    JevClient,
    JevError,
    JevMalformedResponseError,
    JevRequestError,
    JevUnavailableError,
    default_ledger_path,
    parse_noul_answer,
    resolve_typesafe_key,
)
from lcc.relevance.safety import BlockAssessment, decide_assessment
from lcc.relevance.sufficiency import SufficiencyResult, verify_sufficiency
from lcc.relevance.trim import TRIM_POLICY_VERSION, detect_content_type, trim_block_safe
from lcc.relevance.verifier import SemanticVerificationResult, verify_semantic

__all__ = [
    "BLOCK_ID_RE",
    "BLOCK_PARSER_VERSION",
    "DECISIONS_CACHE_SCHEMA_VERSION",
    "DEFAULT_MAX_BLOCK_CHARS",
    "DEFAULT_MIN_BLOCK_CHARS",
    "POLICY_VERSION",
    "PROTECTION_VERSION",
    "RELATIONSHIP_VERSION",
    "RELEVANCE_SCHEMA_VERSION",
    "TRIM_POLICY_VERSION",
    "BlockAssessment",
    "BlockDecision",
    "ContextGraph",
    "DecisionCache",
    "EdgeType",
    "GraphEdge",
    "JevClient",
    "JevError",
    "JevMalformedResponseError",
    "JevRequestError",
    "JevUnavailableError",
    "RelevanceCompactionReport",
    "RelevanceCompactionRequest",
    "RelevanceCompactionResult",
    "SemanticVerificationResult",
    "SufficiencyResult",
    "TextBlock",
    "block_id",
    "build_decision_identity",
    "build_graph",
    "canonical_dumps",
    "compact_context",
    "decide_assessment",
    "decision_key",
    "decision_key_v2",
    "default_ledger_path",
    "detect_content_type",
    "gaps_between",
    "parse_noul_answer",
    "reconstruct",
    "report_to_dict",
    "resolve_typesafe_key",
    "split_blocks",
    "trim_block_safe",
    "verify_semantic",
    "verify_sufficiency",
]
