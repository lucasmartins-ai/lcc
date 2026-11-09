from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from lcc import __version__


def test_imported_version_matches_pyproject() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert __version__ == pyproject["project"]["version"]


def test_citation_version_matches_pyproject() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")

    assert f'\nversion: "{pyproject["project"]["version"]}"\n' in citation


def test_every_manifest_version_matches_pyproject() -> None:
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

    def manifest(path: str) -> Any:
        return json.loads((root / path).read_text(encoding="utf-8"))

    # plugins/chatgpt/plugin.json carries its own version and is not listed.
    plugin = "plugins/claude-code"
    server = manifest("server.json")
    marketplace = manifest(".claude-plugin/marketplace.json")
    found = {
        "package.json": manifest("package.json")["version"],
        "server.json": server["version"],
        **{f"server.json packages[{i}]": p["version"] for i, p in enumerate(server["packages"])},
        **{f"marketplace.json plugins[{i}]": p["version"] for i, p in enumerate(marketplace["plugins"])},
        f"{plugin}/.claude-plugin/plugin.json": manifest(f"{plugin}/.claude-plugin/plugin.json")["version"],
        f"{plugin}/.codex-plugin/plugin.json": manifest(f"{plugin}/.codex-plugin/plugin.json")["version"],
    }
    wrong = {name: value for name, value in found.items() if value != version}
    assert len(found) >= 6 and not wrong, f"expected {version}: {wrong}"

    # The fallback lcc.__version__ returns from a source tree that is not installed.
    init = (root / "src" / "lcc" / "__init__.py").read_text(encoding="utf-8")
    assert f'return "{version}"' in init
