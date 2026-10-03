"""Replay anonymous excerpts of local tool results through msi-api-1.0."""

import hashlib
import importlib
import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks/msi-replay"))


def module():
    return importlib.import_module("session_replay")


def test_collection_allowlists_output_and_preserves_all_matching_results(tmp_path):
    records = [
        {"timestamp": "2026-06-18T23:51:53Z", "message": {"content": [
            {"type": "tool_result", "content": text}
        ]}}
        for text in (
            "private customer name\n.......... [100%]\n45 passed in 0.31s\nsecret=value",
            "1 failed, 47 passed in 0.29s",
            "47 passed in 0.29s",  # repeated observations remain in the denominator
        )
    ]
    (tmp_path / "private-session-id.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records)
    )
    captured = module().collect(tmp_path)
    assert len(captured["traces"]) == 3
    public = json.dumps(captured)
    assert "private-session-id" not in public
    assert "private customer" not in public and "secret=value" not in public
    assert captured["data_class"] == "REPLAYED"
    assert captured["traces"][0]["required_facts"] == ["45 passed in 0.31s"]
    assert "1 failed" in captured["traces"][1]["context"]


def test_public_compile_is_exercised_offline_and_full_receipts_replay(monkeypatch):
    def offline(*args, **kwargs):
        raise AssertionError("Replay attempted network access")

    monkeypatch.setattr(socket.socket, "connect", offline)
    monkeypatch.setattr(socket, "create_connection", offline)
    first = module().build()
    second = module().build()
    assert first["api_version"] == "msi-api-1.0"
    assert first["data_class"] == "REPLAYED"
    assert len(first["runs"]) == 20  # 10 captured windows x 2 paired arms
    assert [r["receipt_hash"] for r in first["runs"]] == [
        r["receipt_hash"] for r in second["runs"]
    ]
    for run in first["runs"]:
        assert run["receipt"]["versions"]["dataset"] == first["dataset"]
        assert run["receipt"]["schema_version"] == "inference-receipt/0.1"
        assert run["receipt"]["cost"]["tokens_out"] == run["retained_tokens"]
        assert run["model_calls"] == run["frontier_calls"] == 0


def test_all_regressions_have_measured_failures_and_next_experiment():
    result = module().build()
    failures = {(r["trace_id"], r["arm"]) for r in result["runs"] if not r["success"]}
    investigated = {(r["trace_id"], r["arm"]) for r in result["regressions"]}
    assert investigated == failures
    for regression in result["regressions"]:
        assert regression["root_cause"] and regression["next_experiment"]
        assert regression["missing_facts"] or regression["sufficiency_failures"]


def test_published_session_excerpts_follow_safe_output_grammar():
    m = module()
    captured = json.loads(m.SESSIONS_PATH.read_text())
    assert captured["source_files_scanned"] == 10
    assert len(captured["traces"]) == 10
    assert captured["selection_rule"]
    for trace in captured["traces"]:
        assert trace["source_sha256"] and trace["record_number"] > 0
        assert m.safe_excerpt(trace["context"]) == trace["context"]
        assert hashlib.sha256(trace["context"].encode()).hexdigest() == trace["excerpt_sha256"]


def test_public_compile_receipts_validate_against_frozen_spec():
    spec = Path("/Users/Master/msi-repos/minimum-sufficient-inference/spec")
    if not spec.exists():
        pytest.skip("Local spec checkout unavailable")
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((spec / "inference-receipt.schema.json").read_text())
    for run in module().build()["runs"]:
        jsonschema.validate(run["receipt"], schema)
