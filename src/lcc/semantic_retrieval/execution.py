"""Explicit semantic retrieval execution boundary (ADR 0012).

This module defines the first fail-closed execution report shape. It recognizes the future
``local_index_v1`` adapter boundary but does not implement retrieval, vector scoring, prompt
assembly, embeddings, model calls, network access, or runtime downloads.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from lcc.semantic_retrieval.boundary import (
    DEFAULT_TOP_K,
    SemanticRetrievalBoundaryError,
    validate_semantic_index_manifest,
)

SEMANTIC_RETRIEVAL_EXECUTION_REPORT_SCHEMA_VERSION = "semantic-retrieval-execution-1.0"
LOCAL_INDEX_V1_ADAPTER = "local_index_v1"
_SUPPORTED_VECTOR_CONTENT_FORMAT = "json_float_array_v1"
_SUPPORTED_SIMILARITY_METRIC = "cosine"


@dataclass(frozen=True)
class SemanticRetrievalExecutionRequest:
    """Explicit opt-in request for future semantic retrieval execution."""

    enabled: bool = False
    adapter_name: str = LOCAL_INDEX_V1_ADAPTER
    source_text: str | None = None
    question: str | None = None
    index_manifest_path: Path | None = None
    embedding_assets_dir: Path | None = None
    top_k: int = DEFAULT_TOP_K


@dataclass(frozen=True)
class SemanticRetrievalExecutionReport:
    """Fail-closed report for explicit semantic retrieval execution attempts."""

    schema_version: str
    enabled: bool
    status: str
    reason_code: str
    message: str
    adapter_name: str
    top_k: int
    retrieval_performed: bool = False
    selected_evidence: tuple[dict[str, Any], ...] = ()


def _blocked(
    request: SemanticRetrievalExecutionRequest,
    reason_code: str,
    message: str,
) -> SemanticRetrievalExecutionReport:
    return SemanticRetrievalExecutionReport(
        schema_version=SEMANTIC_RETRIEVAL_EXECUTION_REPORT_SCHEMA_VERSION,
        enabled=request.enabled,
        status="blocked",
        reason_code=reason_code,
        message=message,
        adapter_name=request.adapter_name,
        top_k=request.top_k,
    )


def _text_fingerprint(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_manifest_metadata(path: Path) -> dict[str, Any]:
    try:
        raw_manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SemanticRetrievalBoundaryError(
            f"semantic retrieval index manifest invalid: JSON could not be parsed: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise SemanticRetrievalBoundaryError(
            f"semantic retrieval index manifest invalid: could not be read: {exc}"
        ) from exc

    if not isinstance(raw_manifest, dict):
        raise SemanticRetrievalBoundaryError(
            "semantic retrieval index manifest invalid: manifest must be an object"
        )
    return raw_manifest


def _chunk_text(chunk: dict[str, Any], key: str, chunk_id: str) -> str:
    value = chunk.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SemanticRetrievalBoundaryError(
            f"semantic retrieval index manifest invalid: chunk {chunk_id} {key} is required"
        )
    return value


def _chunk_offsets(chunk: dict[str, Any], chunk_id: str) -> tuple[int, int]:
    offsets = chunk.get("source_offsets")
    if not isinstance(offsets, dict):
        raise SemanticRetrievalBoundaryError(
            "semantic retrieval index manifest invalid: "
            f"chunk {chunk_id} source_offsets must be an object"
        )
    start = offsets.get("start")
    end = offsets.get("end")
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
    ):
        raise SemanticRetrievalBoundaryError(
            "semantic retrieval index manifest invalid: "
            f"chunk {chunk_id} source_offsets must be integer offsets"
        )
    return start, end


def _manifest_chunks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list):
        raise SemanticRetrievalBoundaryError(
            "semantic retrieval index manifest invalid: chunks must be a list"
        )

    validated_chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise SemanticRetrievalBoundaryError(
                f"semantic retrieval index manifest invalid: chunk {index} must be an object"
            )
        validated_chunks.append(chunk)
    return validated_chunks


def _chunk_vector(chunk: dict[str, Any], chunk_id: str) -> tuple[str, int]:
    vector = chunk.get("vector")
    if not isinstance(vector, dict):
        raise SemanticRetrievalBoundaryError(
            f"semantic retrieval index manifest invalid: chunk {chunk_id} vector must be an object"
        )
    ref = _chunk_text(vector, "ref", chunk_id)
    dimensions = vector.get("dimensions")
    if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0:
        raise SemanticRetrievalBoundaryError(
            "semantic retrieval index manifest invalid: "
            f"chunk {chunk_id} vector dimensions must be a positive integer"
        )
    return ref, dimensions


def _vector_path(manifest_path: Path, ref: str, chunk_id: str) -> Path:
    ref_path = Path(ref)
    if ref_path.is_absolute() or PureWindowsPath(ref).is_absolute():
        raise SemanticRetrievalBoundaryError(
            "semantic retrieval index manifest invalid: "
            f"chunk {chunk_id} vector reference must be relative"
        )
    manifest_root = manifest_path.parent.resolve()
    vector_path = manifest_path.parent / ref_path
    try:
        vector_path.resolve(strict=False).relative_to(manifest_root)
    except ValueError as exc:
        raise SemanticRetrievalBoundaryError(
            "semantic retrieval index manifest invalid: "
            f"chunk {chunk_id} vector reference must not escape the manifest directory"
        ) from exc
    return vector_path


def _parse_vector_contents(
    request: SemanticRetrievalExecutionRequest,
    *,
    chunk_id: str,
    ref: str,
    vector_path: Path,
    expected_dimensions: int,
) -> SemanticRetrievalExecutionReport | None:
    try:
        raw_vector = vector_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _blocked(
            request,
            "semantic_retrieval_vector_contents_missing",
            f"Vector contents for chunk {chunk_id} were not found: {ref}.",
        )
    except OSError as exc:
        return _blocked(
            request,
            "semantic_retrieval_vector_contents_missing",
            f"Vector contents for chunk {chunk_id} could not be read: {ref}: {exc}.",
        )
    except UnicodeDecodeError:
        return _blocked(
            request,
            "semantic_retrieval_vector_contents_malformed",
            f"Vector contents for chunk {chunk_id} are not valid UTF-8 JSON: {ref}.",
        )

    if not raw_vector.strip():
        return _blocked(
            request,
            "semantic_retrieval_vector_contents_empty",
            f"Vector contents for chunk {chunk_id} are empty: {ref}.",
        )

    try:
        vector = json.loads(raw_vector)
    except json.JSONDecodeError:
        return _blocked(
            request,
            "semantic_retrieval_vector_contents_malformed",
            f"Vector contents for chunk {chunk_id} are not valid JSON: {ref}.",
        )
    if not isinstance(vector, list):
        return _blocked(
            request,
            "semantic_retrieval_vector_contents_malformed",
            f"Vector contents for chunk {chunk_id} must be a JSON array: {ref}.",
        )
    if not vector:
        return _blocked(
            request,
            "semantic_retrieval_vector_contents_empty",
            f"Vector contents for chunk {chunk_id} are empty: {ref}.",
        )

    for value in vector:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return _blocked(
                request,
                "semantic_retrieval_vector_contents_malformed",
                f"Vector contents for chunk {chunk_id} must contain only numbers: {ref}.",
            )
        if not math.isfinite(float(value)):
            return _blocked(
                request,
                "semantic_retrieval_vector_contents_non_finite",
                f"Vector contents for chunk {chunk_id} contain non-finite values: {ref}.",
            )

    if len(vector) != expected_dimensions:
        return _blocked(
            request,
            "semantic_retrieval_vector_dimension_mismatch",
            f"Vector contents for chunk {chunk_id} do not match declared dimensions.",
        )
    return None


def _vector_content_block(
    request: SemanticRetrievalExecutionRequest,
    manifest: dict[str, Any],
    expected_dimensions: int,
) -> SemanticRetrievalExecutionReport | None:
    assert request.index_manifest_path is not None
    for chunk in _manifest_chunks(manifest):
        chunk_id = _chunk_text(chunk, "id", "unknown")
        ref, dimensions = _chunk_vector(chunk, chunk_id)
        if dimensions != expected_dimensions:
            return _blocked(
                request,
                "semantic_retrieval_vector_dimension_mismatch",
                f"Chunk {chunk_id} vector dimensions do not match manifest dimensions.",
            )
        blocked = _parse_vector_contents(
            request,
            chunk_id=chunk_id,
            ref=ref,
            vector_path=_vector_path(request.index_manifest_path, ref, chunk_id),
            expected_dimensions=expected_dimensions,
        )
        if blocked is not None:
            return blocked
    return None


def _execution_setting_block(
    request: SemanticRetrievalExecutionRequest,
    index_settings: dict[str, Any],
    *,
    key: str,
    supported_value: str,
    required_reason_code: str,
    unsupported_reason_code: str,
) -> SemanticRetrievalExecutionReport | None:
    value = index_settings.get(key)
    if not isinstance(value, str) or not value.strip():
        return _blocked(
            request,
            required_reason_code,
            f"local_index_v1 execution requires index_settings.{key}.",
        )
    if value != supported_value:
        return _blocked(
            request,
            unsupported_reason_code,
            f"local_index_v1 does not support index_settings.{key}: {value}.",
        )
    return None


def _execution_index_settings_block(
    request: SemanticRetrievalExecutionRequest,
    manifest: dict[str, Any],
) -> SemanticRetrievalExecutionReport | None:
    index_settings = manifest.get("index_settings")
    if not isinstance(index_settings, dict):
        return _blocked(
            request,
            "semantic_retrieval_manifest_invalid",
            "semantic retrieval index manifest invalid: index settings must be an object.",
        )

    for blocked in (
        _execution_setting_block(
            request,
            index_settings,
            key="vector_content_format",
            supported_value=_SUPPORTED_VECTOR_CONTENT_FORMAT,
            required_reason_code="semantic_retrieval_vector_content_format_required",
            unsupported_reason_code="semantic_retrieval_unsupported_vector_content_format",
        ),
        _execution_setting_block(
            request,
            index_settings,
            key="similarity_metric",
            supported_value=_SUPPORTED_SIMILARITY_METRIC,
            required_reason_code="semantic_retrieval_similarity_metric_required",
            unsupported_reason_code="semantic_retrieval_unsupported_similarity_metric",
        ),
    ):
        if blocked is not None:
            return blocked
    return None


def _source_provenance_block(
    request: SemanticRetrievalExecutionRequest,
    manifest: dict[str, Any],
    expected_source_fingerprint: str,
) -> SemanticRetrievalExecutionReport | None:
    assert request.source_text is not None
    source_text = request.source_text
    if _text_fingerprint(source_text) != expected_source_fingerprint:
        return _blocked(
            request,
            "semantic_retrieval_source_fingerprint_mismatch",
            "Supplied source text fingerprint does not match the semantic index manifest.",
        )

    for chunk in _manifest_chunks(manifest):
        chunk_id = _chunk_text(chunk, "id", "unknown")
        start, end = _chunk_offsets(chunk, chunk_id)
        if start < 0 or end <= start or end > len(source_text):
            return _blocked(
                request,
                "semantic_retrieval_chunk_source_span_invalid",
                f"Chunk {chunk_id} source_offsets are outside the supplied source text.",
            )
        expected_text_hash = _chunk_text(chunk, "text_hash", chunk_id)
        if _text_fingerprint(source_text[start:end]) != expected_text_hash:
            return _blocked(
                request,
                "semantic_retrieval_chunk_text_hash_mismatch",
                f"Chunk {chunk_id} text_hash does not match the supplied source span.",
            )

    return None


def semantic_retrieval_execution_report(
    request: SemanticRetrievalExecutionRequest,
) -> SemanticRetrievalExecutionReport:
    """Return a deterministic fail-closed execution report for ``request``.

    ``local_index_v1`` is only a recognized future boundary here. Even with valid local
    artifacts and vector contents, this function performs no similarity ranking and still
    returns a blocked adapter-not-implemented report.
    """

    if request.top_k <= 0:
        return _blocked(
            request,
            "semantic_retrieval_top_k_invalid",
            "Semantic retrieval execution requires top_k greater than 0.",
        )
    if not request.enabled:
        return _blocked(
            request,
            "semantic_retrieval_disabled",
            "Semantic retrieval execution requires explicit --enable-semantic-retrieval.",
        )
    if request.adapter_name != LOCAL_INDEX_V1_ADAPTER:
        return _blocked(
            request,
            "semantic_retrieval_unsupported_adapter",
            f"Unsupported semantic retrieval adapter: {request.adapter_name}.",
        )
    if not request.question or not request.question.strip():
        return _blocked(
            request,
            "semantic_retrieval_question_required",
            "Semantic retrieval execution requires an explicit question.",
        )
    if request.source_text is None or not request.source_text:
        return _blocked(
            request,
            "semantic_retrieval_source_required",
            "Semantic retrieval execution requires explicit source text.",
        )
    if request.index_manifest_path is None:
        return _blocked(
            request,
            "semantic_retrieval_index_manifest_required",
            "Semantic retrieval execution requires a local index manifest.",
        )
    if not request.index_manifest_path.is_file():
        return _blocked(
            request,
            "semantic_retrieval_index_manifest_missing",
            f"Semantic retrieval index manifest not found: {request.index_manifest_path}.",
        )
    if request.embedding_assets_dir is None:
        return _blocked(
            request,
            "semantic_retrieval_embedding_assets_required",
            "Semantic retrieval execution requires local embedding assets.",
        )
    if not request.embedding_assets_dir.is_dir():
        return _blocked(
            request,
            "semantic_retrieval_embedding_assets_missing",
            f"Semantic retrieval embedding assets not found: {request.embedding_assets_dir}.",
        )

    try:
        manifest_summary = validate_semantic_index_manifest(
            request.index_manifest_path,
            embedding_assets_dir=request.embedding_assets_dir,
        )
    except SemanticRetrievalBoundaryError as exc:
        return _blocked(request, "semantic_retrieval_manifest_invalid", str(exc))

    try:
        manifest_metadata = _read_manifest_metadata(request.index_manifest_path)
        provenance_block = _source_provenance_block(
            request,
            manifest_metadata,
            manifest_summary.source_fingerprint,
        )
    except SemanticRetrievalBoundaryError as exc:
        return _blocked(request, "semantic_retrieval_manifest_invalid", str(exc))
    if provenance_block is not None:
        return provenance_block

    vector_content_block = _vector_content_block(
        request,
        manifest_metadata,
        manifest_summary.vector_dimensions,
    )
    if vector_content_block is not None:
        return vector_content_block

    execution_settings_block = _execution_index_settings_block(request, manifest_metadata)
    if execution_settings_block is not None:
        return execution_settings_block

    return _blocked(
        request,
        "semantic_retrieval_adapter_not_implemented",
        "local_index_v1 is recognized, but semantic retrieval execution is not implemented.",
    )
