"""``lcc hint --hook`` runs on every prompt, so the console script answers it without the CLI.

Each prompt pays Python start-up plus every module the hook imports. The first test fails if the
hook path starts importing typer, rich or the modules behind other commands again; the others
check that every other command line still reaches the full CLI and that the packages' lazy
exports all resolve.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import lcc
from lcc import entry
from lcc.relevance.transcript_stash import put

# Everything the hook imports from lcc. Add a module only if it is cheap to import.
HOOK_MODULES = {
    "lcc",
    "lcc.entry",
    "lcc.receipt",
    "lcc.relevance",
    "lcc.relevance.recall_hints",
    "lcc.relevance.transcript_stash",
    "lcc.reporting",
    "lcc.reporting.explain",
}

PROBE = """
import json, sys
before = set(sys.modules)
sys.argv = ["lcc", "hint", "--hook"]
from lcc.entry import main
main()
sys.stdout.flush()
sys.stderr.write(json.dumps(sorted(set(sys.modules) - before)))
"""


def test_the_hook_answers_without_loading_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))
    digest = put("curl output for order_5521: 502 Bad Gateway\n")
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(f"[removed: 1 line, 0.1 KB · lcc recall {digest[:12]}]\n", "utf-8")
    event = {"session_id": "s", "transcript_path": str(transcript), "prompt": "retry order_5521"}
    proc = subprocess.run(
        [sys.executable, "-c", PROBE],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        timeout=60,
        # The worktree's src, not whatever lcc the interpreter has installed.
        env={**os.environ, "PYTHONPATH": str(Path(lcc.__file__).resolve().parents[1])},
    )
    assert proc.returncode == 0, proc.stderr
    context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert f"lcc recall {digest[:12]}" in context
    loaded = json.loads(proc.stderr)
    roots = sys.stdlib_module_names | {"lcc"}
    assert [m for m in loaded if m.partition(".")[0] not in roots] == []  # typer, rich, tiktoken
    assert {m for m in loaded if m.partition(".")[0] == "lcc"} <= HOOK_MODULES


def test_every_other_command_line_goes_to_the_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["lcc", "--version"])
    with pytest.raises(SystemExit) as exited:
        entry.main()
    assert exited.value.code == 0
    assert capsys.readouterr().out.strip() == f"lcc {lcc.__version__}"


@pytest.mark.parametrize("package", ["lcc", "lcc.relevance", "lcc.reporting"])
def test_every_lazy_export_resolves(package: str) -> None:
    module = importlib.import_module(package)
    assert set(module.__all__) - {"__version__"} == set(module._HOME)
    for name in module.__all__:
        getattr(module, name)  # AttributeError if _EXPORTS points at the wrong module
