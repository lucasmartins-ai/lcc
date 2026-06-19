"""Tests for deterministic text cleaning (normalize + boilerplate)."""

from __future__ import annotations

from lcc.cleaning.boilerplate import remove_common_boilerplate
from lcc.cleaning.normalize import normalize_text


def test_normalize_converts_line_endings():
    result = normalize_text("a\r\nb\rc")
    assert result.text == "a\nb\nc"
    assert "normalize_line_endings" in {step.name for step in result.steps}


def test_normalize_strips_trailing_whitespace():
    result = normalize_text("hello   \nworld\t\n")
    assert result.text == "hello\nworld"


def test_normalize_collapses_blank_line_runs():
    result = normalize_text("a\n\n\n\n\nb")
    assert result.text == "a\n\nb"


def test_normalize_collapses_inner_spaces_but_keeps_indentation():
    result = normalize_text("    code    here")
    assert result.text == "    code here"


def test_normalize_preserves_unicode():
    result = normalize_text("café — naïve\n\nrésumé")
    assert "café" in result.text
    assert "résumé" in result.text


def test_normalize_empty_and_whitespace_only():
    assert normalize_text("").text == ""
    assert normalize_text("   \n  \n").text == ""


def test_boilerplate_removes_signature_and_page_marker():
    text = "Real content here.\nSent from my iPhone\nPage 3 of 10\nMore content."
    result = remove_common_boilerplate(text)
    assert "Sent from my iPhone" not in result.text
    assert "Page 3 of 10" not in result.text
    assert "Real content here." in result.text
    assert "More content." in result.text
    assert result.actions


def test_boilerplate_removes_long_rule_but_keeps_markdown_hr():
    text = "Title\n====\nBody\n---\nEnd"
    result = remove_common_boilerplate(text)
    assert "====" not in result.text  # 4-char decorative rule removed
    assert "---" in result.text  # 3-char Markdown thematic break preserved
    assert "Title" in result.text
    assert "Body" in result.text


def test_boilerplate_keeps_meaningful_lines():
    text = "The unsubscribe rate fell 12% this quarter.\nThis page covers billing."
    result = remove_common_boilerplate(text)
    assert result.text == text
    assert result.actions == []


def test_boilerplate_can_be_given_empty_pattern_set():
    text = "Sent from my iPhone"
    result = remove_common_boilerplate(text, patterns={})
    assert result.text == text
    assert result.actions == []
