from __future__ import annotations

import tomllib
from pathlib import Path

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
