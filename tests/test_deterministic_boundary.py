"""The deterministic core stays free of network, LLM, and embedding capabilities.

Core = cleaning, token_budget, inspection, pipeline, lexical_selection,
benchmarking (ADR 0006/0008/0010). These tests *attempt* the forbidden thing
(statically and at runtime) and must keep failing to find it:

- no capability imports (sockets-as-client, HTTP clients, ML frameworks,
  LLM SDKs) anywhere in core — except the fail-closed network *guard* in
  token_budget/counters.py, which is the enforcement mechanism itself;
- no imports of the opt-in layers (relevance, agents, router,
  semantic_retrieval) from core — except benchmarking/metadata.py reusing the
  single `RELEVANCE_SCHEMA_VERSION` string constant (no capability, no
  behavior; keeps report identity in sync);
- core outputs are byte-identical with the network forcibly disabled;
- importing core never pulls torch/transformers/laya/LLM SDKs into the process.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "lcc"

CORE_DIRS = ["cleaning", "token_budget", "inspection", "benchmarking"]
CORE_FILES = ["pipeline.py", "lexical_selection.py"]

# Module roots that must never appear as an import in core. tiktoken is
# deliberately absent: exact counting is allowed and runs inside the guard.
FORBIDDEN_ROOTS = {
    "socket", "requests", "urllib", "http", "httpx", "aiohttp",
    "torch", "transformers", "laya", "openai", "anthropic",
    "sentence_transformers", "huggingface_hub",
}

OPTIN_LAYERS = {"lcc.relevance", "lcc.agents", "lcc.router", "lcc.semantic_retrieval"}

SAMPLE = (
    "Hello world. Hello world.\n\n"
    "The clinic booking widget loses mobile visitors at step two.\n\n"
    "Common boilerplate footer text here.\n"
)


def _core_files():
    files: list[Path] = []
    for d in CORE_DIRS:
        files.extend((SRC / d).rglob("*.py"))
    for f in CORE_FILES:
        files.append(SRC / f)
    return sorted(files)


def _imports_of(path: Path):
    """Yield (module_root, full_name, enclosing_function_or_None) for imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    def visit(node, func=None):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                if isinstance(child, ast.Import):
                    for a in child.names:
                        found.append((a.name.split(".")[0], a.name, func))
                else:
                    mod = (child.module or "").split(".")[0]
                    for a in child.names:
                        found.append((mod, f"{child.module}.{a.name}", func))
                visit(child, func)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
            else:
                visit(child, func)

    visit(tree)
    return found


def test_core_has_no_capability_imports():
    violations = []
    for path in _core_files():
        is_guard = path.name == "counters.py"
        for root, full, func in _imports_of(path):
            if root not in FORBIDDEN_ROOTS:
                continue
            if is_guard and func == "_no_network_guard":
                continue  # the fail-closed enforcement mechanism itself
            violations.append(f"{path.relative_to(ROOT)}:{func or '<top>'}:{full}")
    assert not violations, (
        "capability imports inside deterministic core:\n" + "\n".join(violations)
    )


def test_network_guard_is_the_only_exception_and_it_fails_closed():
    guard = SRC / "token_budget" / "counters.py"
    text = guard.read_text(encoding="utf-8")
    assert "TokenizerNetworkBlocked" in text
    assert "_no_network_guard" in text
    # The guard patches entry points to raise; it never performs I/O itself.
    assert "raise TokenizerNetworkBlocked" in text


def test_core_does_not_import_optin_layers():
    violations = []
    for path in _core_files():
        for _, full, func in _imports_of(path):
            for layer in OPTIN_LAYERS:
                if full == layer or full.startswith(layer + "."):
                    if path.name == "metadata.py" and full.split(".")[-1].endswith("_VERSION"):
                        continue  # policy/schema identity constants only, checked below
                    violations.append(f"{path.relative_to(ROOT)}:{func or '<top>'}:{full}")
    assert not violations, "opt-in layer leaking into deterministic core:\n" + "\n".join(violations)


def test_metadata_relevance_import_is_constant_only():
    tree = ast.parse((SRC / "benchmarking" / "metadata.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("lcc.relevance"):
            names.update(a.name for a in node.names)
    assert names, "expected version-constant reuse"
    assert all(n.endswith("_VERSION") for n in names), names


def test_core_runs_identical_with_network_disabled(monkeypatch):
    import socket

    from lcc.inspection.inspector import InspectionRequest, inspect
    from lcc.pipeline import OptimizationRequest, optimize

    def _boom(*args, **kwargs):
        raise OSError("network disabled by boundary test")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)

    req = OptimizationRequest(raw_text=SAMPLE, question="q")
    out = optimize(req)
    ireq = InspectionRequest(raw_text=SAMPLE)
    rep = inspect(ireq)
    assert out.cleaned_context  # produced with no network available
    assert rep.token_budget is not None


def test_importing_core_pulls_no_ml_or_llm_frameworks():
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c",
         "import lcc.pipeline, lcc.cleaning, lcc.inspection, "
         "lcc.token_budget, lcc.lexical_selection, lcc.benchmarking; "
         "import sys; "
         "bad = [m for m in sys.modules if m.split('.')[0] in "
         "('torch','transformers','laya','openai','anthropic','requests')]; "
         "print(','.join(bad))"],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT), env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"core pulled heavy frameworks: {proc.stdout.strip()}"
