"""Sprint 8 DX: minimal API + diff + actionable errors, all offline."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "lcc"

FORBIDDEN_ROOTS = {
    "socket", "requests", "urllib", "http", "httpx", "aiohttp",
    "torch", "transformers", "laya", "openai", "anthropic",
    "sentence_transformers", "huggingface_hub",
}

TASK = "reduce mobile booking friction"
DOSSIER = (
    "The clinic booking widget loses 63 percent of mobile visitors before the second step.\n\n"
    "A quoted complaint carries the evidence: the patient wrote: the form erased everything\n"
    "when I tapped back on my phone, so I gave up and called instead.\n\n"
    "LOG 1: queue worker heartbeat ok in 554ms, backlog 287 jobs, retry budget untouched.\n\n"
    "Chatter about office plants.\n\n"
    "The decline occurred after the mobile redesign shipped to all users in June.\n\n"
)


def test_msi_module_has_no_capability_imports():
    tree = ast.parse((SRC / "msi.py").read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    bad = roots & FORBIDDEN_ROOTS
    assert not bad, f"msi.py pulls capabilities: {bad}"


def test_compile_is_offline_deterministic_and_schema_valid(monkeypatch):
    import socket

    from lcc.msi import compile as msi_compile

    def _boom(*a, **k):
        raise OSError("network disabled by DX test")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setenv("LCC_DISABLE_NETWORK", "1")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    r1 = msi_compile(TASK, DOSSIER)
    r2 = msi_compile(TASK, DOSSIER)
    assert r1.context == r2.context  # byte-identical (receipt timestamps excepted)
    assert r1.provider_used == "mechanical"
    assert r1.degraded is False
    assert r1.sufficiency["result"] in ("PASS", "REVIEW")
    receipt = r1.receipt.to_spec_dict()
    assert receipt["schema_version"] == "inference-receipt/0.1"
    assert receipt["task_id"].startswith("msi-")
    # jsonschema validity against the frozen spec when available
    spec = ROOT.parent / "msi-repos" / "minimum-sufficient-inference" / "spec" / "inference-receipt.schema.json"
    if spec.is_file():
        import jsonschema

        jsonschema.validate(receipt, json.loads(spec.read_text(encoding="utf-8")))


def test_compile_rejects_empty_inputs():
    import pytest

    from lcc.msi import compile as msi_compile

    with pytest.raises(ValueError, match="non-empty task"):
        msi_compile("", DOSSIER)
    with pytest.raises(ValueError, match="non-empty context"):
        msi_compile(TASK, "   ")


def test_diff_runs_offline(monkeypatch, tmp_path):
    import socket

    from typer.testing import CliRunner

    from lcc.cli import app

    def _boom(*a, **k):
        raise OSError("network disabled by DX test")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)

    left = tmp_path / "a.txt"
    right = tmp_path / "b.txt"
    left.write_text("hello\nworld\n", encoding="utf-8")
    right.write_text("hello\nWORLD\n", encoding="utf-8")
    res = CliRunner().invoke(app, ["diff", str(left), str(right)])
    assert res.exit_code == 0, res.output
    res2 = CliRunner().invoke(app, ["diff", str(left), str(left)])
    assert res2.exit_code == 0, res2.output


def test_common_errors_are_actionable():
    from typer.testing import CliRunner

    from lcc.cli import app

    r = CliRunner()
    with r.isolated_filesystem():
        out = r.invoke(app, ["optimize", "nope-missing.md"]).output
        assert "check the path" in out and "'-'" in out
        Path("bad.json").write_text('{"foo": 1}', encoding="utf-8")
        out2 = r.invoke(app, ["explain", "bad.json"]).output
        assert "lcc compact -r report.json" in out2
        out3 = r.invoke(app, ["diff", "-", "bad.json"]).output
        assert "two file paths" in out3
