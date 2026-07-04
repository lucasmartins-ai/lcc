"""Tests for the disabled-by-default semantic retrieval boundary scaffold."""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lcc.cli import app
from lcc.semantic_retrieval import (
    LOCAL_INDEX_V1_ADAPTER,
    SEMANTIC_RETRIEVAL_EXECUTION_REPORT_SCHEMA_VERSION,
    SemanticRetrievalBoundaryError,
    SemanticRetrievalConfig,
    SemanticRetrievalExecutionRequest,
    semantic_retrieval_boundary_report,
    semantic_retrieval_execution_report,
    validate_semantic_index_manifest,
)

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[1]
_HASH_A = "sha256:" + "a" * 64
_HASH_C = "sha256:" + "c" * 64
_HASH_D = "sha256:" + "d" * 64
_ASSET_REF = "models/fixture-embedding.asset"
_ASSET_BYTES = b"local embedding asset fixture; hash only, never load as a model\n"
_ASSET_FINGERPRINT = "sha256:" + hashlib.sha256(_ASSET_BYTES).hexdigest()
_VALID_VECTOR_BYTES = b"[0.1, 0.2, 0.3]\n"
_VALID_EXECUTION_INDEX_SETTINGS = {
    "chunk_inventory_version": "inspection-1.0",
    "vector_content_format": "json_float_array_v1",
    "similarity_metric": "cosine",
}
_EXECUTION_SOURCE_TEXT = "Alpha source text.\nBeta source text.\n"
_DEFAULT_COMMAND_INPUT = (
    "The quarterly migration status includes the same operational paragraph "
    "for every regional service owner and should only be kept once.\n\n" * 6
)
_SEMANTIC_IMPORT_BLOCKLIST = [
    REPO_ROOT / "src" / "lcc" / "cleaning",
    REPO_ROOT / "src" / "lcc" / "token_budget",
    REPO_ROOT / "src" / "lcc" / "prompt_builder",
    REPO_ROOT / "src" / "lcc" / "reporting",
    REPO_ROOT / "src" / "lcc" / "pipeline.py",
    REPO_ROOT / "src" / "lcc" / "inspection",
    REPO_ROOT / "src" / "lcc" / "benchmarking",
]


def _valid_semantic_manifest() -> dict[str, object]:
    return {
        "schema_version": "semantic-index-1.0",
        "source_fingerprint": _HASH_A,
        "embedding_model": {
            "provider": "local",
            "model_name": "fixture-embedding",
            "dimensions": 3,
            "asset_fingerprints": {_ASSET_REF: _ASSET_FINGERPRINT},
        },
        "vector_dimensions": 3,
        "chunks": [
            {
                "id": "chunk_0001_cccccccccccc",
                "source_offsets": {"start": 0, "end": 42},
                "line_span": {"start": 1, "end": 2},
                "text_hash": _HASH_C,
                "vector": {"ref": "vectors/chunk_0001_cccccccccccc.bin", "dimensions": 3},
            }
        ],
        "index_settings": {"chunk_inventory_version": "inspection-1.0"},
    }


def _text_fingerprint(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _valid_execution_semantic_manifest(
    source_text: str = _EXECUTION_SOURCE_TEXT,
) -> dict[str, object]:
    chunk_text = "Alpha source text.\n"
    return {
        "schema_version": "semantic-index-1.0",
        "source_fingerprint": _text_fingerprint(source_text),
        "embedding_model": {
            "provider": "local",
            "model_name": "fixture-embedding",
            "dimensions": 3,
            "asset_fingerprints": {_ASSET_REF: _ASSET_FINGERPRINT},
        },
        "vector_dimensions": 3,
        "chunks": [
            {
                "id": "chunk_0001_cccccccccccc",
                "source_offsets": {"start": 0, "end": len(chunk_text)},
                "line_span": {"start": 1, "end": 1},
                "text_hash": _text_fingerprint(chunk_text),
                "vector": {"ref": "vectors/chunk_0001_cccccccccccc.bin", "dimensions": 3},
            }
        ],
        "index_settings": dict(_VALID_EXECUTION_INDEX_SETTINGS),
    }


def _valid_two_chunk_semantic_manifest() -> dict[str, object]:
    manifest = _valid_semantic_manifest()
    first_chunk = dict(list(manifest["chunks"])[0])  # type: ignore[arg-type]
    second_chunk = {
        "id": "chunk_0002_dddddddddddd",
        "source_offsets": {"start": 43, "end": 88},
        "line_span": {"start": 4, "end": 6},
        "text_hash": _HASH_D,
        "vector": {"ref": "vectors/chunk_0002_dddddddddddd.bin", "dimensions": 3},
    }
    manifest["chunks"] = [first_chunk, second_chunk]
    return manifest


def _vector_refs(manifest: dict[str, object]) -> list[str]:
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list):
        return []

    refs: list[str] = []
    for raw_chunk in chunks:
        if not isinstance(raw_chunk, dict):
            continue
        vector = raw_chunk.get("vector")
        if not isinstance(vector, dict):
            continue
        ref = vector.get("ref")
        if isinstance(ref, str):
            refs.append(ref)
    return refs


def _asset_fingerprints(manifest: dict[str, object]) -> dict[str, str]:
    embedding_model = manifest.get("embedding_model")
    if not isinstance(embedding_model, dict):
        return {}
    asset_fingerprints = embedding_model.get("asset_fingerprints")
    if not isinstance(asset_fingerprints, dict):
        return {}

    return {
        ref: fingerprint
        for ref, fingerprint in asset_fingerprints.items()
        if isinstance(ref, str) and isinstance(fingerprint, str)
    }


def _write_manifest(
    path: Path,
    manifest: dict[str, object] | None = None,
    *,
    create_vector_files: bool = True,
    vector_bytes: bytes = b"local vector fixture; contents must not be parsed\n",
) -> None:
    payload = _valid_semantic_manifest() if manifest is None else manifest
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not create_vector_files:
        return

    manifest_dir = path.parent.resolve()
    for ref in _vector_refs(payload):
        ref_path = Path(ref)
        if ref_path.is_absolute():
            continue
        vector_path = path.parent / ref_path
        try:
            vector_path.resolve().relative_to(manifest_dir)
        except ValueError:
            continue
        vector_path.parent.mkdir(parents=True, exist_ok=True)
        vector_path.write_bytes(vector_bytes)


def _write_embedding_assets(
    assets_dir: Path,
    manifest: dict[str, object] | None = None,
    *,
    asset_bytes: bytes = _ASSET_BYTES,
) -> None:
    payload = _valid_semantic_manifest() if manifest is None else manifest
    assets_root = assets_dir.resolve()
    for ref in _asset_fingerprints(payload):
        ref_path = Path(ref)
        if ref_path.is_absolute():
            continue
        asset_path = assets_dir / ref_path
        try:
            asset_path.resolve(strict=False).relative_to(assets_root)
        except ValueError:
            continue
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(asset_bytes)


def _write_benchmark_case(cases_dir: Path) -> None:
    case_dir = cases_dir / "default_surface"
    case_dir.mkdir(parents=True)
    (case_dir / "case.yaml").write_text(
        (
            "id: default_surface\n"
            "description: Default command isolation fixture.\n"
            "question: What changed?\n"
            "model: gpt-4.1\n"
            "required_markers:\n"
            "  - KEEPER-241\n"
            "expectations:\n"
            "  min_token_savings_percent: 10.0\n"
            "  allow_approximate_token_count: true\n"
        ),
        encoding="utf-8",
    )
    (case_dir / "input.txt").write_text(
        "KEEPER-241 migration evidence paragraph.\n\n"
        "KEEPER-241 migration evidence paragraph.\n\n"
        "KEEPER-241 migration evidence paragraph.\n",
        encoding="utf-8",
    )


def _write_enabled_semantic_config_with_missing_artifacts(path: Path, tmp_path: Path) -> None:
    path.write_text(
        (
            "model: gpt-4.1\n"
            "question: Summarize the migration status.\n"
            "semantic_retrieval:\n"
            "  enabled: true\n"
            f"  index_manifest: {tmp_path / 'missing.semantic.index.json'}\n"
            f"  embedding_assets: {tmp_path / 'missing-embedding-assets'}\n"
            "  top_k: 2\n"
        ),
        encoding="utf-8",
    )


def _assert_validation_failure_does_not_write_report(
    result: Any,
    report_path: Path,
    *,
    exit_code: int,
    error: str,
) -> None:
    assert result.exit_code == exit_code
    assert error in result.stderr
    assert result.stdout == ""
    assert not report_path.exists()


def _block_vector_content_opens(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    original_path_open = Path.open
    original_open = builtins.open

    def fail_if_vector_path_opened(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".bin":
            raise AssertionError(message)
        return original_path_open(self, *args, **kwargs)

    def fail_if_vector_opened(file: object, *args: Any, **kwargs: Any) -> Any:
        if Path(file).suffix == ".bin":
            raise AssertionError(message)
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_if_vector_path_opened)
    monkeypatch.setattr(builtins, "open", fail_if_vector_opened)


def _semantic_report_metadata_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        matches = [
            key
            for key in value
            if "semantic" in str(key).lower() or "retrieval" in str(key).lower()
        ]
        for item in value.values():
            matches.extend(_semantic_report_metadata_keys(item))
        return matches

    if isinstance(value, list):
        matches: list[str] = []
        for item in value:
            matches.extend(_semantic_report_metadata_keys(item))
        return matches

    return []


def _default_command_args(command: str, tmp_path: Path) -> list[str]:
    if command == "bench":
        cases_dir = tmp_path / "cases"
        _write_benchmark_case(cases_dir)
        return ["bench", str(cases_dir), "--output", str(tmp_path / "bench.json")]

    source = tmp_path / f"{command}.txt"
    source.write_text(_DEFAULT_COMMAND_INPUT, encoding="utf-8")
    if command == "inspect":
        return ["inspect", str(source), "--report", str(tmp_path / "inspect.json")]
    if command == "optimize":
        return [
            "optimize",
            str(source),
            "--question",
            "Summarize.",
            "--output",
            str(tmp_path / "optimize.md"),
        ]
    if command == "prepare":
        return [
            "prepare",
            str(source),
            "--question",
            "Summarize.",
            "--output",
            str(tmp_path / "prepare.md"),
            "--report",
            str(tmp_path / "prepare.json"),
        ]
    raise AssertionError(f"unknown command fixture: {command}")


def _python_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.py"))


def _is_semantic_import(name: str) -> bool:
    return name == "lcc.semantic_retrieval" or name.startswith("lcc.semantic_retrieval.")


def _semantic_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names if _is_semantic_import(alias.name))
            continue

        if not isinstance(node, ast.ImportFrom):
            continue

        module = node.module or ""
        if _is_semantic_import(module):
            imports.append(module)
        if module == "lcc":
            imports.extend(
                f"{module}.{alias.name}"
                for alias in node.names
                if alias.name == "semantic_retrieval"
            )
        if node.level > 0:
            imports.extend(alias.name for alias in node.names if alias.name == "semantic_retrieval")
            if module == "semantic_retrieval" or module.startswith("semantic_retrieval."):
                imports.append(f".{module}")
    return imports


@pytest.mark.parametrize("command", ["inspect", "prepare", "optimize", "bench"])
def test_default_commands_do_not_invoke_semantic_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
) -> None:
    def fail_if_semantic_retrieval_is_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            f"{command} default path must not invoke semantic retrieval boundary reporting"
        )

    monkeypatch.setattr(
        "lcc.cli.semantic_retrieval_boundary_report",
        fail_if_semantic_retrieval_is_called,
    )

    result = runner.invoke(app, _default_command_args(command, tmp_path))

    assert result.exit_code == 0, result.output


def test_optimize_ignores_enabled_semantic_retrieval_config_with_missing_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_if_semantic_retrieval_is_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("optimize must ignore semantic_retrieval config keys")

    monkeypatch.setattr(
        "lcc.cli.semantic_retrieval_boundary_report",
        fail_if_semantic_retrieval_is_called,
    )
    source = tmp_path / "optimize.txt"
    source.write_text(_DEFAULT_COMMAND_INPUT, encoding="utf-8")
    config = tmp_path / "lcc.yaml"
    _write_enabled_semantic_config_with_missing_artifacts(config, tmp_path)
    prompt = tmp_path / "prompt.md"
    report = tmp_path / "optimize.json"

    result = runner.invoke(
        app,
        [
            "optimize",
            str(source),
            "--config",
            str(config),
            "--output",
            str(prompt),
            "--report",
            str(report),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Summarize the migration status." in prompt.read_text(encoding="utf-8")
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert _semantic_report_metadata_keys(data) == []


def test_prepare_ignores_enabled_semantic_retrieval_config_with_missing_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_if_semantic_retrieval_is_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("prepare must ignore semantic_retrieval config keys")

    monkeypatch.setattr(
        "lcc.cli.semantic_retrieval_boundary_report",
        fail_if_semantic_retrieval_is_called,
    )
    source = tmp_path / "prepare.txt"
    source.write_text(_DEFAULT_COMMAND_INPUT, encoding="utf-8")
    config = tmp_path / "lcc.yaml"
    _write_enabled_semantic_config_with_missing_artifacts(config, tmp_path)
    prompt = tmp_path / "prompt.md"
    report = tmp_path / "prepare.json"

    result = runner.invoke(
        app,
        [
            "prepare",
            str(source),
            "--config",
            str(config),
            "--output",
            str(prompt),
            "--report",
            str(report),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Inspection decision: optimize_safe" in result.stderr
    assert "Summarize the migration status." in prompt.read_text(encoding="utf-8")
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["schema_version"] == "prepare-1.0"
    assert data["inspection"]["schema_version"] == "1.0"
    assert data["optimization"]["schema_version"] == "1.0"
    assert _semantic_report_metadata_keys(data) == []


def test_deterministic_default_modules_do_not_import_semantic_retrieval() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)} imports {import_name}"
        for blocked_path in _SEMANTIC_IMPORT_BLOCKLIST
        for path in _python_files(blocked_path)
        for import_name in _semantic_imports(path)
    ]

    assert offenders == []


def test_semantic_retrieval_is_disabled_by_default() -> None:
    report = semantic_retrieval_boundary_report(SemanticRetrievalConfig())

    assert report.enabled is False
    assert report.status == "disabled"
    assert report.reason_code == "semantic_retrieval_disabled"
    assert report.retrieval_performed is False
    assert report.index_manifest_present is False
    assert report.embedding_assets_present is False


def test_enabled_semantic_retrieval_requires_index_manifest(tmp_path: Path) -> None:
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    config = SemanticRetrievalConfig(
        enabled=True,
        index_manifest_path=tmp_path / "missing.index.json",
        embedding_assets_dir=assets_dir,
    )

    with pytest.raises(SemanticRetrievalBoundaryError, match="index manifest"):
        semantic_retrieval_boundary_report(config)


def test_enabled_semantic_retrieval_requires_embedding_assets(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    config = SemanticRetrievalConfig(
        enabled=True,
        index_manifest_path=index_manifest,
        embedding_assets_dir=tmp_path / "missing-assets",
    )

    with pytest.raises(SemanticRetrievalBoundaryError, match="embedding assets"):
        semantic_retrieval_boundary_report(config)


def test_enabled_boundary_fails_closed_until_retrieval_is_implemented(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir)
    config = SemanticRetrievalConfig(
        enabled=True,
        index_manifest_path=index_manifest,
        embedding_assets_dir=assets_dir,
        top_k=4,
    )

    report = semantic_retrieval_boundary_report(config)

    assert report.enabled is True
    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_not_implemented"
    assert report.top_k == 4
    assert report.retrieval_performed is False
    assert report.index_manifest_present is True
    assert report.embedding_assets_present is True


def test_valid_semantic_index_manifest_is_validated_without_retrieval(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)

    summary = validate_semantic_index_manifest(index_manifest)

    assert summary.schema_version == "semantic-index-1.0"
    assert summary.source_fingerprint == _HASH_A
    assert summary.embedding_provider == "local"
    assert summary.embedding_model_name == "fixture-embedding"
    assert summary.vector_dimensions == 3
    assert summary.chunk_count == 1


def test_manifest_validation_accepts_local_embedding_asset_provenance(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir)

    summary = validate_semantic_index_manifest(
        index_manifest,
        embedding_assets_dir=assets_dir,
    )

    assert summary.embedding_provider == "local"
    assert summary.embedding_model_name == "fixture-embedding"


def test_manifest_validation_requires_declared_embedding_asset_file(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()

    with pytest.raises(SemanticRetrievalBoundaryError, match="embedding asset file not found"):
        validate_semantic_index_manifest(index_manifest, embedding_assets_dir=assets_dir)


def test_manifest_validation_requires_relative_embedding_asset_references(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    embedding_model = dict(manifest["embedding_model"])  # type: ignore[arg-type]
    embedding_model["asset_fingerprints"] = {
        str(tmp_path / "assets" / "fixture.bin"): _ASSET_FINGERPRINT
    }
    manifest["embedding_model"] = embedding_model
    _write_manifest(index_manifest, manifest)
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()

    with pytest.raises(SemanticRetrievalBoundaryError, match="relative embedding asset reference"):
        validate_semantic_index_manifest(index_manifest, embedding_assets_dir=assets_dir)


def test_manifest_validation_rejects_embedding_asset_reference_that_escapes_assets_dir(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    embedding_model = dict(manifest["embedding_model"])  # type: ignore[arg-type]
    embedding_model["asset_fingerprints"] = {"../outside.asset": _ASSET_FINGERPRINT}
    manifest["embedding_model"] = embedding_model
    _write_manifest(index_manifest, manifest)
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()

    with pytest.raises(SemanticRetrievalBoundaryError, match="must not escape"):
        validate_semantic_index_manifest(index_manifest, embedding_assets_dir=assets_dir)


def test_manifest_validation_fails_closed_for_embedding_asset_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, asset_bytes=b"tampered local asset\n")

    with pytest.raises(SemanticRetrievalBoundaryError, match="fingerprint mismatch"):
        validate_semantic_index_manifest(index_manifest, embedding_assets_dir=assets_dir)


def test_manifest_validation_requires_relative_vector_references(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    chunk = dict(chunks[0])  # type: ignore[index]
    chunk["vector"] = {"ref": str(tmp_path / "vectors" / "chunk-0001.bin"), "dimensions": 3}
    manifest["chunks"] = [chunk]
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="relative vector reference"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_rejects_vector_reference_that_escapes_manifest_dir(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "indexes" / "semantic.index.json"
    index_manifest.parent.mkdir()
    manifest = _valid_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    chunk = dict(chunks[0])  # type: ignore[index]
    chunk["vector"] = {"ref": "../outside.bin", "dimensions": 3}
    manifest["chunks"] = [chunk]
    _write_manifest(index_manifest, manifest, create_vector_files=False)
    (tmp_path / "outside.bin").write_bytes(b"outside manifest directory\n")

    with pytest.raises(SemanticRetrievalBoundaryError, match="must not escape"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_requires_referenced_vector_file_to_exist_locally(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest, create_vector_files=False)

    with pytest.raises(SemanticRetrievalBoundaryError, match="vector file not found"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_does_not_open_vector_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    original_path_open = Path.open
    original_open = builtins.open

    def fail_if_vector_path_opened(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".bin":
            raise AssertionError("vector contents must not be opened")
        return original_path_open(self, *args, **kwargs)

    def fail_if_vector_opened(file: object, *args: Any, **kwargs: Any) -> Any:
        if Path(file).suffix == ".bin":
            raise AssertionError("vector contents must not be opened")
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_if_vector_path_opened)
    monkeypatch.setattr(builtins, "open", fail_if_vector_opened)

    summary = validate_semantic_index_manifest(index_manifest)

    assert summary.chunk_count == 1


def test_status_reporting_does_not_open_vector_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir)
    original_path_open = Path.open
    original_open = builtins.open

    def fail_if_vector_path_opened(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".bin":
            raise AssertionError("status reporting must not open vector contents")
        return original_path_open(self, *args, **kwargs)

    def fail_if_vector_opened(file: object, *args: Any, **kwargs: Any) -> Any:
        if Path(file).suffix == ".bin":
            raise AssertionError("status reporting must not open vector contents")
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_if_vector_path_opened)
    monkeypatch.setattr(builtins, "open", fail_if_vector_opened)

    report = semantic_retrieval_boundary_report(
        SemanticRetrievalConfig(
            enabled=True,
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.retrieval_performed is False


def test_manifest_validation_requires_semantic_index_schema(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    manifest["schema_version"] = "1.0"
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="schema_version.*semantic-index-1.0"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_requires_source_fingerprint(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    del manifest["source_fingerprint"]
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="source fingerprint"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_fails_closed_for_stale_looking_source_fingerprint(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    manifest["source_fingerprint"] = "sha256:short"
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="stale-looking source fingerprint"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_requires_embedding_model_metadata(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    manifest["embedding_model"] = {"provider": "local", "dimensions": 3}
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="embedding model metadata"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_requires_positive_vector_dimensions(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    manifest["vector_dimensions"] = 0
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="vector dimensions"):
        validate_semantic_index_manifest(index_manifest)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("id", "chunk id"),
        ("source_offsets", "source offsets"),
        ("line_span", "line span"),
        ("text_hash", "text hash"),
        ("vector", "vector reference"),
    ],
)
def test_manifest_validation_requires_complete_chunk_records(
    tmp_path: Path, field: str, expected: str
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    chunk = dict(chunks[0])  # type: ignore[index]
    del chunk[field]
    manifest["chunks"] = [chunk]
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match=expected):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_fails_closed_for_duplicate_chunk_ids(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_two_chunk_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    duplicate = dict(chunks[1])  # type: ignore[index]
    duplicate["id"] = chunks[0]["id"]  # type: ignore[index]
    manifest["chunks"] = [chunks[0], duplicate]  # type: ignore[list-item]
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="duplicate chunk id"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_fails_closed_for_stale_looking_chunk_id(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    chunk = dict(chunks[0])  # type: ignore[index]
    chunk["id"] = "chunk-0001"
    chunk["vector"] = {"ref": "vectors/chunk-0001.bin", "dimensions": 3}
    manifest["chunks"] = [chunk]
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="stale-looking chunk id"):
        validate_semantic_index_manifest(index_manifest)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        (
            "source_offsets",
            {"start": 41, "end": 88},
            "source offsets.*non-overlapping manifest order",
        ),
        (
            "line_span",
            {"start": 2, "end": 6},
            "line span.*non-overlapping manifest order",
        ),
    ],
)
def test_manifest_validation_fails_closed_for_inconsistent_chunk_provenance_order(
    tmp_path: Path, field: str, value: dict[str, int], expected: str
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_two_chunk_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    second = dict(chunks[1])  # type: ignore[index]
    second[field] = value
    manifest["chunks"] = [chunks[0], second]  # type: ignore[list-item]
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match=expected):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_fails_closed_for_stale_looking_chunk_hash(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    chunk = dict(chunks[0])  # type: ignore[index]
    chunk["text_hash"] = "sha256:short"
    manifest["chunks"] = [chunk]
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="stale-looking text hash"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_fails_closed_for_vector_dimension_mismatch(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    chunk = dict(chunks[0])  # type: ignore[index]
    chunk["vector"] = {"ref": "vectors/chunk_0001_cccccccccccc.bin", "dimensions": 2}
    manifest["chunks"] = [chunk]
    _write_manifest(index_manifest, manifest)

    with pytest.raises(
        SemanticRetrievalBoundaryError,
        match="chunk_0001_cccccccccccc.*vector dimensions",
    ):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_requires_index_settings(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    del manifest["index_settings"]
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="index settings"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_requires_supported_chunk_inventory_version(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    manifest["index_settings"] = {"chunk_inventory_version": "unknown-1.0"}
    _write_manifest(index_manifest, manifest)

    with pytest.raises(
        SemanticRetrievalBoundaryError,
        match="chunk_inventory_version.*inspection-1.0",
    ):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_rejects_nondeterministic_index_settings_metadata(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    manifest["index_settings"] = {
        "chunk_inventory_version": "inspection-1.0",
        "created_at": "2026-07-03T00:00:00Z",
    }
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="deterministic index settings"):
        validate_semantic_index_manifest(index_manifest)


def test_manifest_validation_rejects_absolute_paths_in_index_settings(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_semantic_manifest()
    manifest["index_settings"] = {
        "chunk_inventory_version": "inspection-1.0",
        "source_path": str(tmp_path / "source.txt"),
    }
    _write_manifest(index_manifest, manifest)

    with pytest.raises(SemanticRetrievalBoundaryError, match="machine-specific absolute paths"):
        validate_semantic_index_manifest(index_manifest)


def test_semantic_retrieval_command_reports_disabled_boundary() -> None:
    result = runner.invoke(app, ["semantic-retrieval"])

    assert result.exit_code == 0
    assert '"status": "disabled"' in result.stdout
    assert '"retrieval_performed": false' in result.stdout


def test_semantic_retrieval_command_default_does_not_invoke_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_execution_is_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("default semantic-retrieval status must not invoke execution")

    monkeypatch.setattr("lcc.cli.semantic_retrieval_execution_report", fail_if_execution_is_called)

    result = runner.invoke(app, ["semantic-retrieval"])

    assert result.exit_code == 0
    assert '"schema_version": "semantic-retrieval-0.1"' in result.stdout


def test_semantic_retrieval_command_writes_deterministic_disabled_report(
    tmp_path: Path,
) -> None:
    first_report = tmp_path / "semantic-disabled-first.json"
    second_report = tmp_path / "semantic-disabled-second.json"

    first = runner.invoke(app, ["semantic-retrieval", "--report", str(first_report)])
    second = runner.invoke(app, ["semantic-retrieval", "--report", str(second_report)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert first.stdout == ""
    assert second.stdout == ""
    first_payload = first_report.read_text(encoding="utf-8")
    assert first_payload == second_report.read_text(encoding="utf-8")
    assert json.loads(first_payload) == {
        "schema_version": "semantic-retrieval-0.1",
        "enabled": False,
        "status": "disabled",
        "reason_code": "semantic_retrieval_disabled",
        "message": (
            "Semantic retrieval is disabled by default. Deterministic lcc commands do not "
            "retrieve, rank, embed, call models, or touch the network."
        ),
        "top_k": 8,
        "index_manifest_present": False,
        "embedding_assets_present": False,
        "retrieval_performed": False,
    }


def test_semantic_retrieval_validation_failure_with_report_requires_index_manifest(
    tmp_path: Path,
) -> None:
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    report_path = tmp_path / "semantic-validation.json"

    result = runner.invoke(
        app,
        [
            "semantic-retrieval",
            "--enable-semantic-retrieval",
            "--index-manifest",
            str(tmp_path / "missing.semantic.index.json"),
            "--embedding-assets",
            str(assets_dir),
            "--report",
            str(report_path),
        ],
    )

    _assert_validation_failure_does_not_write_report(
        result,
        report_path,
        exit_code=1,
        error="semantic retrieval index manifest not found",
    )


def test_semantic_retrieval_validation_failure_with_report_requires_embedding_assets(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    report_path = tmp_path / "semantic-validation.json"

    result = runner.invoke(
        app,
        [
            "semantic-retrieval",
            "--enable-semantic-retrieval",
            "--index-manifest",
            str(index_manifest),
            "--embedding-assets",
            str(tmp_path / "missing-embedding-assets"),
            "--report",
            str(report_path),
        ],
    )

    _assert_validation_failure_does_not_write_report(
        result,
        report_path,
        exit_code=1,
        error="semantic retrieval embedding assets not found",
    )


def test_semantic_retrieval_validation_failure_with_report_rejects_cli_top_k(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "semantic-validation.json"

    result = runner.invoke(
        app,
        ["semantic-retrieval", "--top-k", "0", "--report", str(report_path)],
    )

    _assert_validation_failure_does_not_write_report(
        result,
        report_path,
        exit_code=1,
        error="semantic retrieval top_k must be greater than 0",
    )


def test_semantic_retrieval_validation_failure_with_report_rejects_config_top_k(
    tmp_path: Path,
) -> None:
    config = tmp_path / "lcc.yaml"
    config.write_text("semantic_retrieval:\n  top_k: 0\n", encoding="utf-8")
    report_path = tmp_path / "semantic-validation.json"

    result = runner.invoke(
        app,
        ["semantic-retrieval", "--config", str(config), "--report", str(report_path)],
    )

    _assert_validation_failure_does_not_write_report(
        result,
        report_path,
        exit_code=2,
        error="config key semantic_retrieval.top_k must be a positive integer",
    )


@pytest.mark.parametrize(
    ("config_body", "error"),
    [
        ("semantic_retrieval: disabled\n", "config key semantic_retrieval must be a mapping"),
        (
            "semantic_retrieval:\n  enabled: 1\n",
            "config key semantic_retrieval.enabled must be a boolean",
        ),
        (
            "semantic_retrieval:\n  index_manifest: []\n",
            "config key semantic_retrieval.index_manifest must be a path string",
        ),
        (
            "semantic_retrieval:\n  adapter: local\n",
            "unsupported config key semantic_retrieval.adapter",
        ),
    ],
)
def test_semantic_retrieval_validation_failure_with_report_rejects_invalid_config(
    tmp_path: Path,
    config_body: str,
    error: str,
) -> None:
    config = tmp_path / "lcc.yaml"
    config.write_text(config_body, encoding="utf-8")
    report_path = tmp_path / "semantic-validation.json"

    result = runner.invoke(
        app,
        ["semantic-retrieval", "--config", str(config), "--report", str(report_path)],
    )

    _assert_validation_failure_does_not_write_report(
        result,
        report_path,
        exit_code=2,
        error=error,
    )


@pytest.mark.parametrize(
    "config_body",
    [
        "semantic_retrieval: true\n",
        "semantic_retrieval:\n  - enabled\n",
        "semantic_retrieval: disabled\n",
    ],
)
def test_semantic_retrieval_command_rejects_non_mapping_config_section(
    tmp_path: Path,
    config_body: str,
) -> None:
    config = tmp_path / "lcc.yaml"
    config.write_text(config_body, encoding="utf-8")

    result = runner.invoke(app, ["semantic-retrieval", "--config", str(config)])

    assert result.exit_code == 2
    assert "config key semantic_retrieval must be a mapping" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("top_k", ["0", "-2", "true", "1.5", "many"])
def test_semantic_retrieval_command_rejects_invalid_config_top_k(
    tmp_path: Path,
    top_k: str,
) -> None:
    config = tmp_path / "lcc.yaml"
    config.write_text(
        (f"semantic_retrieval:\n  top_k: {top_k}\n"),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["semantic-retrieval", "--config", str(config)])

    assert result.exit_code == 2
    assert "config key semantic_retrieval.top_k must be a positive integer" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "enabled",
    [
        "1",
        '"true"',
        "[]",
        "{}",
        "null",
    ],
)
def test_semantic_retrieval_command_rejects_invalid_config_enabled_values(
    tmp_path: Path,
    enabled: str,
) -> None:
    config = tmp_path / "lcc.yaml"
    config.write_text(
        (f"semantic_retrieval:\n  enabled: {enabled}\n"),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["semantic-retrieval", "--config", str(config)])

    assert result.exit_code == 2
    assert "config key semantic_retrieval.enabled must be a boolean" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("unknown_key", ["adapter", "query", "vector_store", "model"])
def test_semantic_retrieval_command_rejects_unsupported_config_keys(
    tmp_path: Path,
    unknown_key: str,
) -> None:
    config = tmp_path / "lcc.yaml"
    config.write_text(
        (f"semantic_retrieval:\n  enabled: false\n  {unknown_key}: local\n"),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["semantic-retrieval", "--config", str(config)])

    assert result.exit_code == 2
    assert f"unsupported config key semantic_retrieval.{unknown_key}" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("index_manifest", "123"),
        ("index_manifest", "true"),
        ("index_manifest", "[]"),
        ("index_manifest", "{}"),
        ("index_manifest", "null"),
        ("index_manifest", '""'),
        ("embedding_assets", "123"),
        ("embedding_assets", "true"),
        ("embedding_assets", "[]"),
        ("embedding_assets", "{}"),
        ("embedding_assets", "null"),
        ("embedding_assets", '""'),
    ],
)
def test_semantic_retrieval_command_rejects_invalid_config_path_values(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    config = tmp_path / "lcc.yaml"
    config.write_text(
        (f"semantic_retrieval:\n  enabled: false\n  {key}: {value}\n"),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["semantic-retrieval", "--config", str(config)])

    assert result.exit_code == 2
    assert f"config key semantic_retrieval.{key} must be a path string" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("top_k", ["0", "-2"])
def test_semantic_retrieval_command_rejects_invalid_cli_top_k(top_k: str) -> None:
    result = runner.invoke(app, ["semantic-retrieval", "--top-k", top_k])

    assert result.exit_code == 1
    assert "semantic retrieval top_k must be greater than 0" in result.stderr
    assert result.stdout == ""


def test_semantic_retrieval_command_fails_closed_when_enabled(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir)

    result = runner.invoke(
        app,
        [
            "semantic-retrieval",
            "--enable-semantic-retrieval",
            "--index-manifest",
            str(index_manifest),
            "--embedding-assets",
            str(assets_dir),
        ],
    )

    assert result.exit_code == 1
    assert '"status": "blocked"' in result.stdout
    assert '"reason_code": "semantic_retrieval_not_implemented"' in result.stdout
    assert "not implemented" in result.stderr


def test_semantic_retrieval_command_writes_blocked_report_when_enabled(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir)
    report_path = tmp_path / "semantic-blocked.json"

    result = runner.invoke(
        app,
        [
            "semantic-retrieval",
            "--enable-semantic-retrieval",
            "--index-manifest",
            str(index_manifest),
            "--embedding-assets",
            str(assets_dir),
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not implemented" in result.stderr
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["enabled"] is True
    assert data["status"] == "blocked"
    assert data["reason_code"] == "semantic_retrieval_not_implemented"
    assert data["retrieval_performed"] is False


def test_explicit_execution_writes_separate_fail_closed_report(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Local source text.\n", encoding="utf-8")
    report_path = tmp_path / "semantic-execution.json"

    result = runner.invoke(
        app,
        [
            "semantic-retrieval",
            "--execute",
            "--source",
            str(source),
            "--question",
            "What changed?",
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == SEMANTIC_RETRIEVAL_EXECUTION_REPORT_SCHEMA_VERSION
    assert data["enabled"] is False
    assert data["status"] == "blocked"
    assert data["reason_code"] == "semantic_retrieval_disabled"
    assert data["adapter_name"] == LOCAL_INDEX_V1_ADAPTER
    assert data["retrieval_performed"] is False
    assert data["selected_evidence"] == []


def test_execution_checks_prerequisites_before_manifest_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_if_manifest_validation_is_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("missing question must fail before manifest validation")

    monkeypatch.setattr(
        "lcc.semantic_retrieval.execution.validate_semantic_index_manifest",
        fail_if_manifest_validation_is_called,
    )

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text="Local source text.\n",
            index_manifest_path=tmp_path / "missing.semantic.index.json",
            embedding_assets_dir=tmp_path / "missing-assets",
        )
    )

    assert report.schema_version == SEMANTIC_RETRIEVAL_EXECUTION_REPORT_SCHEMA_VERSION
    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_question_required"
    assert report.retrieval_performed is False


def test_execution_rejects_unsupported_adapter_before_artifact_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_if_manifest_validation_is_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unsupported adapter must fail before manifest validation")

    monkeypatch.setattr(
        "lcc.semantic_retrieval.execution.validate_semantic_index_manifest",
        fail_if_manifest_validation_is_called,
    )

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            adapter_name="remote_vector_db",
            source_text="Local source text.\n",
            question="What changed?",
            index_manifest_path=tmp_path / "missing.semantic.index.json",
            embedding_assets_dir=tmp_path / "missing-assets",
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_unsupported_adapter"
    assert report.adapter_name == "remote_vector_db"
    assert report.retrieval_performed is False


def test_local_index_v1_execution_boundary_is_recognized_but_not_implemented(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(
        index_manifest,
        _valid_execution_semantic_manifest(),
        vector_bytes=_VALID_VECTOR_BYTES,
    )
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, _valid_execution_semantic_manifest())

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            adapter_name=LOCAL_INDEX_V1_ADAPTER,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
            top_k=2,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_adapter_not_implemented"
    assert report.adapter_name == LOCAL_INDEX_V1_ADAPTER
    assert report.top_k == 2
    assert report.retrieval_performed is False
    assert report.selected_evidence == ()


@pytest.mark.parametrize(
    ("setting", "value", "reason_code"),
    [
        (
            "vector_content_format",
            None,
            "semantic_retrieval_vector_content_format_required",
        ),
        (
            "vector_content_format",
            "raw_float32_le",
            "semantic_retrieval_unsupported_vector_content_format",
        ),
        (
            "similarity_metric",
            None,
            "semantic_retrieval_similarity_metric_required",
        ),
        (
            "similarity_metric",
            "dot_product",
            "semantic_retrieval_unsupported_similarity_metric",
        ),
    ],
)
def test_explicit_execution_requires_supported_local_index_v1_settings(
    tmp_path: Path,
    setting: str,
    value: str | None,
    reason_code: str,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_execution_semantic_manifest()
    index_settings = dict(manifest["index_settings"])  # type: ignore[arg-type]
    if value is None:
        del index_settings[setting]
    else:
        index_settings[setting] = value
    manifest["index_settings"] = index_settings
    _write_manifest(index_manifest, manifest, vector_bytes=_VALID_VECTOR_BYTES)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, manifest)

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == reason_code
    assert report.retrieval_performed is False
    assert report.selected_evidence == ()


def test_execution_validates_vector_contents_before_execution_settings(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_execution_semantic_manifest()
    index_settings = dict(manifest["index_settings"])  # type: ignore[arg-type]
    del index_settings["vector_content_format"]
    manifest["index_settings"] = index_settings
    _write_manifest(index_manifest, manifest, vector_bytes=b"not json\n")
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, manifest)

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_vector_contents_malformed"
    assert report.retrieval_performed is False


def test_execution_fails_closed_for_source_fingerprint_mismatch_before_opening_vectors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_execution_semantic_manifest()
    manifest["source_fingerprint"] = _text_fingerprint(_EXECUTION_SOURCE_TEXT + "stale\n")
    _write_manifest(index_manifest, manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, manifest)
    _block_vector_content_opens(
        monkeypatch,
        "source fingerprint mismatch must block before vector contents are opened",
    )

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_source_fingerprint_mismatch"
    assert report.retrieval_performed is False
    assert report.selected_evidence == ()


def test_execution_fails_closed_for_provenance_before_execution_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_execution_semantic_manifest()
    manifest["source_fingerprint"] = _text_fingerprint(_EXECUTION_SOURCE_TEXT + "stale\n")
    index_settings = dict(manifest["index_settings"])  # type: ignore[arg-type]
    index_settings["similarity_metric"] = "dot_product"
    manifest["index_settings"] = index_settings
    _write_manifest(index_manifest, manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, manifest)
    _block_vector_content_opens(
        monkeypatch,
        "source fingerprint mismatch must block before settings or vector contents",
    )

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_source_fingerprint_mismatch"
    assert report.retrieval_performed is False


def test_execution_fails_closed_for_stale_chunk_text_hash_before_opening_vectors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_execution_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    chunk = dict(chunks[0])  # type: ignore[index]
    chunk["text_hash"] = _text_fingerprint("stale chunk text\n")
    manifest["chunks"] = [chunk]
    _write_manifest(index_manifest, manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, manifest)
    _block_vector_content_opens(
        monkeypatch,
        "stale chunk text hash must block before vector contents are opened",
    )

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_chunk_text_hash_mismatch"
    assert report.retrieval_performed is False
    assert report.selected_evidence == ()


def test_execution_fails_closed_for_out_of_bounds_chunk_offsets(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_execution_semantic_manifest()
    chunks = list(manifest["chunks"])  # type: ignore[arg-type]
    chunk = dict(chunks[0])  # type: ignore[index]
    chunk["source_offsets"] = {"start": 0, "end": len(_EXECUTION_SOURCE_TEXT) + 1}
    manifest["chunks"] = [chunk]
    _write_manifest(index_manifest, manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, manifest)

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_chunk_source_span_invalid"
    assert report.retrieval_performed is False
    assert report.selected_evidence == ()


def test_explicit_execution_opens_vector_contents_after_provenance_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_execution_semantic_manifest()
    _write_manifest(index_manifest, manifest, vector_bytes=_VALID_VECTOR_BYTES)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, manifest)
    original_path_open = Path.open
    original_open = builtins.open
    opened_vectors: list[str] = []

    def track_vector_path_opened(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".bin":
            opened_vectors.append(self.name)
        return original_path_open(self, *args, **kwargs)

    def track_vector_opened(file: object, *args: Any, **kwargs: Any) -> Any:
        if Path(file).suffix == ".bin":
            opened_vectors.append(Path(file).name)
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", track_vector_path_opened)
    monkeypatch.setattr(builtins, "open", track_vector_opened)

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_adapter_not_implemented"
    assert report.retrieval_performed is False
    assert opened_vectors == ["chunk_0001_cccccccccccc.bin"]


def test_execution_fails_closed_for_missing_vector_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_execution_semantic_manifest()
    _write_manifest(index_manifest, manifest, vector_bytes=_VALID_VECTOR_BYTES)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, manifest)
    original_path_open = Path.open

    def missing_vector_path(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".bin":
            raise FileNotFoundError(str(self))
        return original_path_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", missing_vector_path)

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == "semantic_retrieval_vector_contents_missing"
    assert report.retrieval_performed is False


@pytest.mark.parametrize(
    ("vector_bytes", "reason_code"),
    [
        (b"not json\n", "semantic_retrieval_vector_contents_malformed"),
        (b"", "semantic_retrieval_vector_contents_empty"),
        (b"[0.1, NaN, 0.3]\n", "semantic_retrieval_vector_contents_non_finite"),
        (b"[0.1, 0.2]\n", "semantic_retrieval_vector_dimension_mismatch"),
    ],
)
def test_execution_fails_closed_for_invalid_vector_contents(
    tmp_path: Path,
    vector_bytes: bytes,
    reason_code: str,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    manifest = _valid_execution_semantic_manifest()
    _write_manifest(index_manifest, manifest, vector_bytes=vector_bytes)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir, manifest)

    report = semantic_retrieval_execution_report(
        SemanticRetrievalExecutionRequest(
            enabled=True,
            source_text=_EXECUTION_SOURCE_TEXT,
            question="What changed?",
            index_manifest_path=index_manifest,
            embedding_assets_dir=assets_dir,
        )
    )

    assert report.status == "blocked"
    assert report.reason_code == reason_code
    assert report.retrieval_performed is False


def test_semantic_retrieval_command_reads_config_surface(tmp_path: Path) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir)
    config = tmp_path / "lcc.yaml"
    config.write_text(
        (
            "semantic_retrieval:\n"
            "  enabled: true\n"
            f"  index_manifest: {index_manifest}\n"
            f"  embedding_assets: {assets_dir}\n"
            "  top_k: 3\n"
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["semantic-retrieval", "--config", str(config)])

    assert result.exit_code == 1
    assert '"top_k": 3' in result.stdout
    assert '"reason_code": "semantic_retrieval_not_implemented"' in result.stdout


def test_semantic_retrieval_cli_flags_override_config_values_and_stay_blocked(
    tmp_path: Path,
) -> None:
    index_manifest = tmp_path / "semantic.index.json"
    _write_manifest(index_manifest)
    assets_dir = tmp_path / "assets"
    _write_embedding_assets(assets_dir)
    config = tmp_path / "lcc.yaml"
    config.write_text(
        (
            "semantic_retrieval:\n"
            "  enabled: true\n"
            "  index_manifest: 123\n"
            "  embedding_assets: []\n"
            "  top_k: 0\n"
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "semantic-overrides.json"

    result = runner.invoke(
        app,
        [
            "semantic-retrieval",
            "--config",
            str(config),
            "--index-manifest",
            str(index_manifest),
            "--embedding-assets",
            str(assets_dir),
            "--top-k",
            "5",
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not implemented" in result.stderr
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["enabled"] is True
    assert data["status"] == "blocked"
    assert data["reason_code"] == "semantic_retrieval_not_implemented"
    assert data["top_k"] == 5
    assert data["index_manifest_present"] is True
    assert data["embedding_assets_present"] is True
    assert data["retrieval_performed"] is False


def test_semantic_retrieval_command_reads_enabled_config_and_fails_closed_for_missing_artifacts(
    tmp_path: Path,
) -> None:
    config = tmp_path / "lcc.yaml"
    _write_enabled_semantic_config_with_missing_artifacts(config, tmp_path)

    result = runner.invoke(app, ["semantic-retrieval", "--config", str(config)])

    assert result.exit_code == 1
    assert "semantic retrieval index manifest not found" in result.stderr
    assert result.stdout == ""
