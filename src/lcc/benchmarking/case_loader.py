"""Load benchmark cases from disk into validated dataclasses (ADR 0007).

This is the benchmark harness's IO boundary, analogous to ``token_budget.pricing.load_pricing``:
it reads committed fixture files (a ``case.yaml`` plus an ``input.txt``), validates them, and
returns pure dataclasses. It performs no network or model calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from lcc.benchmarking.schemas import (
    COMPRESSION_LEVELS,
    BenchmarkCase,
    BenchmarkExpectations,
)

CASE_FILE = "case.yaml"
INPUT_FILE = "input.txt"

_EXPECTATION_KEYS = {
    "min_token_savings_percent",
    "max_token_savings_percent",
    "min_required_marker_recall",
    "allow_approximate_token_count",
    "max_forbidden_markers_found",
}


class BenchmarkCaseError(ValueError):
    """Raised when a benchmark case directory is missing files or has invalid metadata."""


def discover_case_dirs(root: str | Path) -> list[Path]:
    """Return benchmark case directories under ``root`` (those containing a ``case.yaml``).

    Sorted by directory name for deterministic ordering. Raises ``BenchmarkCaseError`` when
    ``root`` is missing, is not a directory, or contains no cases.
    """
    root_path = Path(root)
    if not root_path.exists():
        raise BenchmarkCaseError(f"benchmark path does not exist: {root}")
    if not root_path.is_dir():
        raise BenchmarkCaseError(f"benchmark path is not a directory: {root}")
    dirs = sorted(
        (
            child
            for child in root_path.iterdir()
            if child.is_dir() and (child / CASE_FILE).is_file()
        ),
        key=lambda path: path.name,
    )
    if not dirs:
        raise BenchmarkCaseError(
            f"no benchmark cases (subdirectories with a {CASE_FILE}) under: {root}"
        )
    return dirs


def load_suite(root: str | Path) -> list[BenchmarkCase]:
    """Discover and load every benchmark case under ``root``."""
    return [load_case(case_dir) for case_dir in discover_case_dirs(root)]


def load_case(case_dir: str | Path) -> BenchmarkCase:
    """Load and validate a single benchmark case directory into a ``BenchmarkCase``."""
    cdir = Path(case_dir)
    case_file = cdir / CASE_FILE
    input_file = cdir / INPUT_FILE
    where = cdir.name or str(cdir)

    if not case_file.is_file():
        raise BenchmarkCaseError(f"case {where!r}: missing {CASE_FILE}")
    if not input_file.is_file():
        raise BenchmarkCaseError(f"case {where!r}: missing {INPUT_FILE}")

    try:
        loaded = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BenchmarkCaseError(f"case {where!r}: could not parse {CASE_FILE}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise BenchmarkCaseError(f"case {where!r}: {CASE_FILE} must contain a YAML mapping")
    data: dict[str, Any] = loaded

    compression_level = _optional_str(data, "compression_level", where, default="safe")
    if compression_level not in COMPRESSION_LEVELS:
        supported = ", ".join(sorted(COMPRESSION_LEVELS))
        raise BenchmarkCaseError(
            f"case {where!r}: unknown compression_level {compression_level!r}; "
            f"supported: {supported}"
        )

    return BenchmarkCase(
        id=_required_str(data, "id", where),
        description=_required_str(data, "description", where),
        question=_required_str(data, "question", where, allow_empty=True),
        input_text=input_file.read_text(encoding="utf-8"),
        model=_optional_str(data, "model", where, default="gpt-4.1"),
        max_input_tokens=_optional_int(data, "max_input_tokens", where),
        compression_level=compression_level,
        required_markers=_str_list(data, "required_markers", where),
        forbidden_markers=_str_list(data, "forbidden_markers", where),
        expectations=_parse_expectations(data.get("expectations"), where),
    )


def _required_str(data: dict[str, Any], key: str, where: str, *, allow_empty: bool = False) -> str:
    value = data.get(key)
    if value is None:
        raise BenchmarkCaseError(f"case {where!r}: missing required field {key!r}")
    if not isinstance(value, str):
        raise BenchmarkCaseError(f"case {where!r}: field {key!r} must be a string")
    if not allow_empty and not value.strip():
        raise BenchmarkCaseError(f"case {where!r}: field {key!r} must not be empty")
    return value


def _optional_str(data: dict[str, Any], key: str, where: str, *, default: str) -> str:
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise BenchmarkCaseError(f"case {where!r}: field {key!r} must be a string")
    return value


def _optional_int(data: dict[str, Any], key: str, where: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchmarkCaseError(f"case {where!r}: field {key!r} must be an integer or null")
    return value


def _str_list(data: dict[str, Any], key: str, where: str) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BenchmarkCaseError(f"case {where!r}: field {key!r} must be a list of strings")
    return list(value)


def _parse_expectations(value: Any, where: str) -> BenchmarkExpectations:
    if value is None:
        return BenchmarkExpectations()
    if not isinstance(value, dict):
        raise BenchmarkCaseError(f"case {where!r}: 'expectations' must be a mapping")
    unknown = set(value) - _EXPECTATION_KEYS
    if unknown:
        raise BenchmarkCaseError(
            f"case {where!r}: unknown expectation key(s): {', '.join(sorted(map(str, unknown)))}"
        )

    exp = BenchmarkExpectations()
    if "min_token_savings_percent" in value:
        exp.min_token_savings_percent = _as_float(value, "min_token_savings_percent", where)
    if "max_token_savings_percent" in value:
        exp.max_token_savings_percent = _as_float(value, "max_token_savings_percent", where)
    if "min_required_marker_recall" in value:
        exp.min_required_marker_recall = _as_float(value, "min_required_marker_recall", where)
    if "allow_approximate_token_count" in value:
        exp.allow_approximate_token_count = _as_bool(value, "allow_approximate_token_count", where)
    if "max_forbidden_markers_found" in value:
        exp.max_forbidden_markers_found = _as_int(value, "max_forbidden_markers_found", where)

    if not 0.0 <= exp.min_required_marker_recall <= 1.0:
        raise BenchmarkCaseError(
            f"case {where!r}: min_required_marker_recall must be within [0.0, 1.0]"
        )
    if exp.min_token_savings_percent > exp.max_token_savings_percent:
        raise BenchmarkCaseError(
            f"case {where!r}: min_token_savings_percent exceeds max_token_savings_percent"
        )
    if exp.max_forbidden_markers_found < 0:
        raise BenchmarkCaseError(
            f"case {where!r}: max_forbidden_markers_found must not be negative"
        )
    return exp


def _as_float(data: dict[str, Any], key: str, where: str) -> float:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkCaseError(f"case {where!r}: expectation {key!r} must be a number")
    return float(value)


def _as_int(data: dict[str, Any], key: str, where: str) -> int:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchmarkCaseError(f"case {where!r}: expectation {key!r} must be an integer")
    return value


def _as_bool(data: dict[str, Any], key: str, where: str) -> bool:
    value = data[key]
    if not isinstance(value, bool):
        raise BenchmarkCaseError(f"case {where!r}: expectation {key!r} must be a boolean")
    return value
