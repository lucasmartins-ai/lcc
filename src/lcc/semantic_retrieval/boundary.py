"""Closed semantic retrieval boundary scaffold (ADR 0011).

The first Phase 2 runtime slice is only a gate: semantic retrieval is disabled by default,
requires explicit local artifacts when enabled, and still reports ``blocked`` until a later
accepted ADR implements a real retrieval adapter. This module deliberately uses only the
standard library.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, NoReturn

SEMANTIC_RETRIEVAL_REPORT_SCHEMA_VERSION = "semantic-retrieval-0.1"
SEMANTIC_INDEX_MANIFEST_SCHEMA_VERSION = "semantic-index-1.0"
DEFAULT_TOP_K = 8
_SHA256_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HASH_READ_SIZE = 1024 * 1024
_SUPPORTED_CHUNK_INVENTORY_VERSION = "inspection-1.0"
_INSPECTION_CHUNK_ID_RE = re.compile(r"^chunk_[0-9]{4}_[0-9a-f]{12}$")
_NONDETERMINISTIC_INDEX_SETTING_KEYS = frozenset(
    {
        "created",
        "created_at",
        "createdat",
        "generated",
        "generated_at",
        "generatedat",
        "host",
        "hostname",
        "machine",
        "machine_id",
        "machineid",
        "timestamp",
        "updated",
        "updated_at",
        "updatedat",
        "user",
        "username",
    }
)


class SemanticRetrievalBoundaryError(ValueError):
    """Raised when an opt-in semantic retrieval request fails the boundary contract."""


@dataclass(frozen=True)
class SemanticIndexManifestSummary:
    """Validated facts from a local semantic index manifest.

    This summary is provenance metadata only. It is not a retrieval result and carries no
    vector contents, rankings, selected source text, prompt text, or model output.
    """

    schema_version: str
    source_fingerprint: str
    embedding_provider: str
    embedding_model_name: str
    vector_dimensions: int
    chunk_count: int


@dataclass(frozen=True)
class SemanticRetrievalConfig:
    """Explicit opt-in configuration for the future semantic retrieval layer.

    ``enabled`` defaults to ``False``. Enabling the boundary requires user-provided local
    artifacts, but this scaffold still performs no retrieval.
    """

    enabled: bool = False
    index_manifest_path: Path | None = None
    embedding_assets_dir: Path | None = None
    top_k: int = DEFAULT_TOP_K


@dataclass(frozen=True)
class SemanticRetrievalBoundaryReport:
    """Deterministic status report for the semantic retrieval boundary gate."""

    schema_version: str
    enabled: bool
    status: str  # "disabled" | "blocked"
    reason_code: str
    message: str
    top_k: int
    index_manifest_present: bool
    embedding_assets_present: bool
    retrieval_performed: bool = False


def _validate_top_k(top_k: int) -> None:
    if top_k <= 0:
        raise SemanticRetrievalBoundaryError("semantic retrieval top_k must be greater than 0")


def _require_file(path: Path | None, label: str) -> bool:
    if path is None:
        raise SemanticRetrievalBoundaryError(f"semantic retrieval requires a local {label}")
    if not path.is_file():
        raise SemanticRetrievalBoundaryError(f"semantic retrieval {label} not found: {path}")
    return True


def _fail_manifest(message: str) -> NoReturn:
    raise SemanticRetrievalBoundaryError(f"semantic retrieval index manifest invalid: {message}")


def _as_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail_manifest(f"{label} must be an object")
    return value


def _required_mapping(manifest: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    if key not in manifest:
        _fail_manifest(f"{label} is required")
    return _as_mapping(manifest[key], label)


def _required_text(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        _fail_manifest(f"{label} is required")
    return value


def _required_positive_int(mapping: dict[str, Any], key: str, label: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail_manifest(f"{label} must be a positive integer")
    return value


def _required_nonnegative_int(mapping: dict[str, Any], key: str, label: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail_manifest(f"{label} must be a non-negative integer")
    return value


def _validate_sha256(value: str, label: str) -> str:
    if not _SHA256_FINGERPRINT_RE.fullmatch(value):
        _fail_manifest(f"stale-looking {label}; expected sha256:<64 lowercase hex>")
    return value


def _normalized_setting_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def _setting_string_is_absolute_path(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _validate_index_setting_value(value: Any, location: str) -> None:
    if isinstance(value, dict):
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                _fail_manifest("deterministic index settings keys must be non-empty strings")
            key = _normalized_setting_key(raw_key)
            if key in _NONDETERMINISTIC_INDEX_SETTING_KEYS:
                _fail_manifest(
                    "deterministic index settings must not include timestamps, hostnames, "
                    "usernames, or machine-specific metadata"
                )
            _validate_index_setting_value(raw_value, f"{location}.{raw_key}")
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_index_setting_value(item, f"{location}[{index}]")
        return

    if isinstance(value, str):
        if _setting_string_is_absolute_path(value):
            _fail_manifest(
                "deterministic index settings must not contain machine-specific absolute paths"
            )
        return

    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return

    _fail_manifest(f"deterministic index settings value at {location} is not JSON-compatible")


def _validate_index_settings(manifest: dict[str, Any]) -> str:
    index_settings = _required_mapping(manifest, "index_settings", "index settings")
    chunk_inventory_version = _required_text(
        index_settings,
        "chunk_inventory_version",
        "index settings chunk_inventory_version",
    )
    if chunk_inventory_version != _SUPPORTED_CHUNK_INVENTORY_VERSION:
        _fail_manifest(
            f"index settings chunk_inventory_version must be {_SUPPORTED_CHUNK_INVENTORY_VERSION!r}"
        )
    _validate_index_setting_value(index_settings, "index_settings")
    return chunk_inventory_version


def _validate_embedding_model(
    manifest: dict[str, Any],
    vector_dimensions: int,
) -> tuple[str, str, dict[str, str]]:
    embedding_model = manifest.get("embedding_model")
    if not isinstance(embedding_model, dict):
        _fail_manifest(
            "embedding model metadata must include provider, model_name, dimensions, "
            "and asset_fingerprints"
        )
    provider = _required_text(embedding_model, "provider", "embedding model metadata provider")
    model_name = _required_text(
        embedding_model, "model_name", "embedding model metadata model_name"
    )
    dimensions = _required_positive_int(
        embedding_model, "dimensions", "embedding model metadata dimensions"
    )
    asset_fingerprints = embedding_model.get("asset_fingerprints")
    if not isinstance(asset_fingerprints, dict) or not asset_fingerprints:
        _fail_manifest(
            "embedding model metadata must include provider, model_name, dimensions, "
            "and asset_fingerprints"
        )
    validated_asset_fingerprints: dict[str, str] = {}
    for asset_name, fingerprint in asset_fingerprints.items():
        if not isinstance(asset_name, str) or not asset_name.strip():
            _fail_manifest("embedding model metadata asset_fingerprints keys must be non-empty")
        if not isinstance(fingerprint, str):
            _fail_manifest(
                "embedding model metadata asset_fingerprints values must be sha256 hashes"
            )
        validated_asset_fingerprints[asset_name] = _validate_sha256(
            fingerprint,
            "embedding model metadata asset fingerprint",
        )
    if dimensions != vector_dimensions:
        _fail_manifest("embedding model metadata dimensions must match vector dimensions")
    return provider, model_name, validated_asset_fingerprints


def _hash_local_file(path: Path, ref: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as asset_file:
            for chunk in iter(lambda: asset_file.read(_HASH_READ_SIZE), b""):
                digest.update(chunk)
    except OSError as exc:
        _fail_manifest(f"embedding asset file could not be read: {ref}: {exc}")
    return "sha256:" + digest.hexdigest()


def _validate_embedding_asset_files(
    asset_fingerprints: dict[str, str],
    embedding_assets_dir: Path,
) -> None:
    assets_root = embedding_assets_dir.resolve()
    for ref, expected_fingerprint in asset_fingerprints.items():
        ref_path = Path(ref)
        if ref_path.is_absolute() or PureWindowsPath(ref).is_absolute():
            _fail_manifest(
                f"embedding asset reference must be a relative embedding asset reference: {ref}"
            )

        asset_path = embedding_assets_dir / ref_path
        try:
            asset_path.resolve(strict=False).relative_to(assets_root)
        except ValueError:
            _fail_manifest(
                f"embedding asset reference must not escape embedding assets directory: {ref}"
            )
        if not asset_path.is_file():
            _fail_manifest(f"embedding asset file not found: {ref}")

        actual_fingerprint = _hash_local_file(asset_path, ref)
        if actual_fingerprint != expected_fingerprint:
            _fail_manifest(f"embedding asset fingerprint mismatch: {ref}")


def _validate_chunk_id(chunk_id: str, chunk_inventory_version: str) -> None:
    if (
        chunk_inventory_version == _SUPPORTED_CHUNK_INVENTORY_VERSION
        and not _INSPECTION_CHUNK_ID_RE.fullmatch(chunk_id)
    ):
        _fail_manifest(
            f"chunk {chunk_id} has stale-looking chunk id for "
            f"{_SUPPORTED_CHUNK_INVENTORY_VERSION}; expected chunk_0001_<12 lowercase hex>"
        )


def _validate_chunk_offsets(chunk: dict[str, Any], chunk_id: str) -> tuple[int, int]:
    offsets = _required_mapping(chunk, "source_offsets", f"chunk {chunk_id} source offsets")
    start = _required_nonnegative_int(offsets, "start", f"chunk {chunk_id} source offsets start")
    end = _required_nonnegative_int(offsets, "end", f"chunk {chunk_id} source offsets end")
    if end <= start:
        _fail_manifest(f"chunk {chunk_id} source offsets end must be greater than start")
    return start, end


def _validate_chunk_line_span(chunk: dict[str, Any], chunk_id: str) -> tuple[int, int]:
    line_span = _required_mapping(chunk, "line_span", f"chunk {chunk_id} line span")
    start = _required_positive_int(line_span, "start", f"chunk {chunk_id} line span start")
    end = _required_positive_int(line_span, "end", f"chunk {chunk_id} line span end")
    if end < start:
        _fail_manifest(f"chunk {chunk_id} line span end must be greater than or equal to start")
    return start, end


def _validate_chunk_vector(
    chunk: dict[str, Any],
    chunk_id: str,
    vector_dimensions: int,
    manifest_dir: Path,
) -> None:
    vector = _required_mapping(chunk, "vector", f"chunk {chunk_id} vector reference")
    ref = _required_text(vector, "ref", f"chunk {chunk_id} vector reference")
    ref_path = Path(ref)
    if ref_path.is_absolute() or PureWindowsPath(ref).is_absolute():
        _fail_manifest(f"chunk {chunk_id} vector reference must be a relative vector reference")

    manifest_root = manifest_dir.resolve()
    vector_path = manifest_dir / ref_path
    try:
        vector_path.resolve(strict=False).relative_to(manifest_root)
    except ValueError:
        _fail_manifest(f"chunk {chunk_id} vector reference must not escape the manifest directory")
    if not vector_path.is_file():
        _fail_manifest(f"chunk {chunk_id} vector file not found: {ref}")

    chunk_dimensions = _required_positive_int(
        vector, "dimensions", f"chunk {chunk_id} vector dimensions"
    )
    if chunk_dimensions != vector_dimensions:
        _fail_manifest(f"chunk {chunk_id} vector dimensions must match manifest vector dimensions")


def _validate_chunks(
    manifest: dict[str, Any],
    vector_dimensions: int,
    manifest_dir: Path,
    chunk_inventory_version: str,
) -> int:
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        _fail_manifest("chunks must be a non-empty list")

    seen_ids: set[str] = set()
    previous_offsets: tuple[int, int] | None = None
    previous_line_span: tuple[int, int] | None = None
    for index, raw_chunk in enumerate(chunks):
        chunk = _as_mapping(raw_chunk, f"chunk {index}")
        chunk_id = _required_text(chunk, "id", "chunk id")
        if chunk_id in seen_ids:
            _fail_manifest(f"duplicate chunk id: {chunk_id}")
        seen_ids.add(chunk_id)
        _validate_chunk_id(chunk_id, chunk_inventory_version)

        offsets = _validate_chunk_offsets(chunk, chunk_id)
        line_span = _validate_chunk_line_span(chunk, chunk_id)
        if previous_offsets is not None and offsets[0] < previous_offsets[1]:
            _fail_manifest(
                f"chunk {chunk_id} source offsets must be in non-overlapping manifest order"
            )
        if previous_line_span is not None and line_span[0] <= previous_line_span[1]:
            _fail_manifest(f"chunk {chunk_id} line span must be in non-overlapping manifest order")
        previous_offsets = offsets
        previous_line_span = line_span

        text_hash = _required_text(chunk, "text_hash", f"chunk {chunk_id} text hash")
        if not _SHA256_FINGERPRINT_RE.fullmatch(text_hash):
            _fail_manifest(
                f"chunk {chunk_id} has stale-looking text hash; expected sha256:<64 lowercase hex>"
            )
        _validate_chunk_vector(chunk, chunk_id, vector_dimensions, manifest_dir)

    return len(chunks)


def validate_semantic_index_manifest(
    path: Path,
    *,
    embedding_assets_dir: Path | None = None,
) -> SemanticIndexManifestSummary:
    """Validate a local ``semantic-index-1.0`` manifest without performing retrieval.

    The manifest is metadata only. Validation fails closed for incompatible schema versions,
    missing provenance, incomplete chunks, invalid fingerprints, inconsistent source spans,
    missing or non-deterministic index settings, unsafe or missing local vector file
    references, unsafe or mismatched embedding asset fingerprints, and vector dimension
    mismatches before any future retrieval adapter could run. It checks vector file paths and
    existence but never opens or parses vector contents.
    """

    try:
        raw_manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail_manifest(f"JSON could not be parsed: {exc.msg}")
    except OSError as exc:
        _fail_manifest(f"could not be read: {exc}")

    manifest = _as_mapping(raw_manifest, "manifest")
    schema_version = manifest.get("schema_version")
    if schema_version != SEMANTIC_INDEX_MANIFEST_SCHEMA_VERSION:
        _fail_manifest(
            "schema_version must be "
            f"{SEMANTIC_INDEX_MANIFEST_SCHEMA_VERSION!r}, got {schema_version!r}"
        )

    source_fingerprint = _required_text(manifest, "source_fingerprint", "source fingerprint")
    _validate_sha256(source_fingerprint, "source fingerprint")

    vector_dimensions = _required_positive_int(manifest, "vector_dimensions", "vector dimensions")
    chunk_inventory_version = _validate_index_settings(manifest)
    provider, model_name, asset_fingerprints = _validate_embedding_model(
        manifest,
        vector_dimensions,
    )
    if embedding_assets_dir is not None:
        if not embedding_assets_dir.is_dir():
            raise SemanticRetrievalBoundaryError(
                f"semantic retrieval embedding assets not found: {embedding_assets_dir}"
            )
        _validate_embedding_asset_files(asset_fingerprints, embedding_assets_dir)
    chunk_count = _validate_chunks(
        manifest,
        vector_dimensions,
        path.parent,
        chunk_inventory_version,
    )

    return SemanticIndexManifestSummary(
        schema_version=SEMANTIC_INDEX_MANIFEST_SCHEMA_VERSION,
        source_fingerprint=source_fingerprint,
        embedding_provider=provider,
        embedding_model_name=model_name,
        vector_dimensions=vector_dimensions,
        chunk_count=chunk_count,
    )


def _require_dir(path: Path | None, label: str) -> bool:
    if path is None:
        raise SemanticRetrievalBoundaryError(f"semantic retrieval requires local {label}")
    if not path.is_dir():
        raise SemanticRetrievalBoundaryError(f"semantic retrieval {label} not found: {path}")
    return True


def semantic_retrieval_boundary_report(
    config: SemanticRetrievalConfig,
) -> SemanticRetrievalBoundaryReport:
    """Return the closed semantic retrieval boundary status for ``config``.

    This is not a retrieval API. It exists so future CLI/config integration can be tested
    against an explicit fail-closed contract before any semantic behavior is implemented.
    """

    _validate_top_k(config.top_k)
    if not config.enabled:
        return SemanticRetrievalBoundaryReport(
            schema_version=SEMANTIC_RETRIEVAL_REPORT_SCHEMA_VERSION,
            enabled=False,
            status="disabled",
            reason_code="semantic_retrieval_disabled",
            message=(
                "Semantic retrieval is disabled by default. Deterministic lcc commands do not "
                "retrieve, rank, embed, call models, or touch the network."
            ),
            top_k=config.top_k,
            index_manifest_present=False,
            embedding_assets_present=False,
        )

    index_manifest_present = _require_file(config.index_manifest_path, "index manifest")
    embedding_assets_present = _require_dir(config.embedding_assets_dir, "embedding assets")
    assert config.index_manifest_path is not None
    assert config.embedding_assets_dir is not None
    validate_semantic_index_manifest(
        config.index_manifest_path,
        embedding_assets_dir=config.embedding_assets_dir,
    )
    return SemanticRetrievalBoundaryReport(
        schema_version=SEMANTIC_RETRIEVAL_REPORT_SCHEMA_VERSION,
        enabled=True,
        status="blocked",
        reason_code="semantic_retrieval_not_implemented",
        message=(
            "Semantic retrieval was explicitly enabled and local artifacts were present, but "
            "retrieval execution is not implemented by this scaffold."
        ),
        top_k=config.top_k,
        index_manifest_present=index_manifest_present,
        embedding_assets_present=embedding_assets_present,
    )
