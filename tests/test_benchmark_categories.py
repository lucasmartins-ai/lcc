"""Tests for the categorized ground truth of the research corpora.

The benchmark is only as good as its ground truth. These tests check the properties that make
the per-category recall metric meaningful: every marker actually detects its own block, every
item is above the scoring floor (or nothing could ever drop it and the item would test
nothing), every category is represented, and recall is computed per category rather than as one
flat number.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

RESEARCH = Path(__file__).resolve().parents[1] / "benchmarks" / "research"
SCALES = ("small", "medium", "large")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MAKE = _load("_make_corpora", RESEARCH / "make_corpora.py")
MATRIX = _load("_run_matrix", RESEARCH / "run_matrix.py")

INDEX = json.loads((RESEARCH / "corpora" / "index.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("scale", SCALES)
def test_every_marker_detects_its_own_block(scale: str):
    """A marker that does not match its own text would report a loss that never happened."""
    for item in MAKE.BLOCKS:
        assert re.search(item["marker"], item["text"]), (
            f"marker {item['marker']!r} does not match its own block"
        )


def test_index_agrees_with_the_generator():
    """The committed index is what the metric reads, so it must match the generator exactly."""
    for scale in SCALES:
        expected = [
            {"category": b["category"], "marker": b["marker"]} for b in MAKE.BLOCKS
        ]
        assert INDEX[scale]["items"] == expected, f"{scale}: index.json is stale"
        assert INDEX[scale]["categories"] == list(MAKE.CATEGORIES)


@pytest.mark.parametrize("scale", SCALES)
def test_every_item_is_above_the_scoring_floor(scale: str):
    """Below `--min-block-chars` nothing is ever scored, so the item would test nothing."""
    for item in MAKE.BLOCKS:
        assert len(item["text"]) >= 80, (
            f"{scale}: block for {item['category']} is {len(item['text'])} chars, below the "
            "80-char scoring floor"
        )


@pytest.mark.parametrize("scale", SCALES)
def test_every_declared_category_is_represented(scale: str):
    declared = set(INDEX[scale]["categories"])
    present = {item["category"] for item in INDEX[scale]["items"]}
    assert declared == present, f"{scale}: declared {declared} but found {present}"
    assert "critical_fact" in present
    assert len(present) >= 5, "the whole point is a spread of information categories"


def test_categories_are_the_documented_set():
    expected = {
        "critical_fact",
        "constraint",
        "negative_constraint",
        "exception",
        "temporal",
        "contradiction",
    }
    for scale in SCALES:
        assert set(INDEX[scale]["categories"]) == expected


def test_recall_is_reported_per_category_not_just_in_total():
    scale = "small"
    text = (RESEARCH / "corpora" / f"{scale}.md").read_text(encoding="utf-8")
    result = MATRIX.recall(text, scale)

    assert result["recall"] == 1.0, "the untouched corpus keeps everything by definition"
    assert result["missing"] == []
    assert set(result["by_category"]) == set(INDEX[scale]["categories"])
    for category, stats in result["by_category"].items():
        assert stats["kept"] == stats["total"], f"{category} lost an item in the raw corpus"
        assert stats["recall"] == 1.0
    assert sum(s["total"] for s in result["by_category"].values()) == len(INDEX[scale]["items"])


def test_recall_detects_a_lost_item_and_names_its_category():
    scale = "small"
    text = (RESEARCH / "corpora" / f"{scale}.md").read_text(encoding="utf-8")
    victim = next(i for i in MAKE.BLOCKS if i["category"] == "negative_constraint")
    damaged = text.replace(victim["text"], "[lcc-compact: dropped 1 block (120 chars)]")

    result = MATRIX.recall(damaged, scale)
    assert result["recall"] < 1.0
    assert victim["marker"] in result["missing"]
    assert result["by_category"]["negative_constraint"]["recall"] == 0.0
    assert result["by_category"]["critical_fact"]["recall"] == 1.0


def test_corpora_on_disk_match_the_generator():
    """The committed corpora must be exactly what the generator produces, or the index lies."""
    for scale in SCALES:
        expected = MAKE.build(scale)["text"]
        on_disk = (RESEARCH / "corpora" / f"{scale}.md").read_text(encoding="utf-8")
        assert on_disk == expected, f"{scale}: corpora/{scale}.md is stale; rerun make_corpora.py"
