"""Tests for the prompt builder and templates."""

from __future__ import annotations

import pytest

from lcc.prompt_builder import PromptSpec, available_templates, build_prompt


def test_prompt_contains_core_sections():
    spec = PromptSpec(
        question="What are the key points?",
        context="Some cleaned context.",
        task_type="summary",
        constraints=["Answer in English."],
        max_output_tokens=300,
    )
    prompt = build_prompt(spec)
    assert "What are the key points?" in prompt
    assert "Some cleaned context." in prompt
    assert "Answer in English." in prompt
    assert "Task type: summary" in prompt
    assert "Response requirements:" in prompt
    assert "300 tokens" in prompt
    assert "only the provided context" in prompt
    assert "Do not" in prompt and "invent" in prompt


def test_allow_external_knowledge_changes_role():
    spec = PromptSpec(question="q", context="c", allow_external_knowledge=True)
    prompt = build_prompt(spec)
    assert "outside knowledge" in prompt


def test_unknown_template_raises():
    spec = PromptSpec(question="q", context="c")
    with pytest.raises(KeyError):
        build_prompt(spec, template_name="does-not-exist")


def test_available_templates_includes_default():
    assert "default" in available_templates()


def test_no_max_output_means_no_length_guidance():
    spec = PromptSpec(question="q", context="c")
    assert "Length guidance" not in build_prompt(spec)


def test_format_requirements_are_appended():
    spec = PromptSpec(question="q", context="c", format_requirements=["Use a Markdown table."])
    assert "Use a Markdown table." in build_prompt(spec)
