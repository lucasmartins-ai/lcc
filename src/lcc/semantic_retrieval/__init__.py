"""Disabled-by-default semantic retrieval boundary scaffold (ADR 0011).

This package is intentionally outside the deterministic core. It validates the opt-in
boundary for future local semantic retrieval, but does not retrieve, rank, select, embed,
summarize, rewrite, paraphrase, call a model, touch the network, or build a prompt.
"""

from __future__ import annotations

from lcc.semantic_retrieval.boundary import (
    SEMANTIC_INDEX_MANIFEST_SCHEMA_VERSION,
    SEMANTIC_RETRIEVAL_REPORT_SCHEMA_VERSION,
    SemanticIndexManifestSummary,
    SemanticRetrievalBoundaryError,
    SemanticRetrievalBoundaryReport,
    SemanticRetrievalConfig,
    semantic_retrieval_boundary_report,
    validate_semantic_index_manifest,
)
from lcc.semantic_retrieval.execution import (
    LOCAL_INDEX_V1_ADAPTER,
    SEMANTIC_RETRIEVAL_EXECUTION_REPORT_SCHEMA_VERSION,
    SemanticRetrievalExecutionReport,
    SemanticRetrievalExecutionRequest,
    semantic_retrieval_execution_report,
)

__all__ = [
    "LOCAL_INDEX_V1_ADAPTER",
    "SEMANTIC_INDEX_MANIFEST_SCHEMA_VERSION",
    "SEMANTIC_RETRIEVAL_EXECUTION_REPORT_SCHEMA_VERSION",
    "SEMANTIC_RETRIEVAL_REPORT_SCHEMA_VERSION",
    "SemanticIndexManifestSummary",
    "SemanticRetrievalBoundaryError",
    "SemanticRetrievalBoundaryReport",
    "SemanticRetrievalConfig",
    "SemanticRetrievalExecutionReport",
    "SemanticRetrievalExecutionRequest",
    "semantic_retrieval_boundary_report",
    "semantic_retrieval_execution_report",
    "validate_semantic_index_manifest",
]
