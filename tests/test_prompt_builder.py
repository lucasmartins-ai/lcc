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


def test_claude_xml_template_renders_tags_and_ordering():
    spec = PromptSpec(
        question="Find bug in authentication logic",
        context="def auth(): pass",
        task_type="code-review",
        constraints=["Preserve existing API."],
        max_output_tokens=500,
    )
    prompt = build_prompt(spec, template_name="claude_xml")
    assert "<system_instructions>" in prompt
    assert "<definition_of_done>" in prompt
    assert "<context>" in prompt
    assert "<user_query>" in prompt
    assert "<rule>Preserve existing API.</rule>" in prompt
    assert "def auth(): pass" in prompt
    assert "Find bug in authentication logic" in prompt
    # Verify prompt caching order: system_instructions and context appear before user_query
    assert prompt.index("<system_instructions>") < prompt.index("<context>") < prompt.index("<user_query>")


def test_code_agent_template_renders_markdown_and_standards():
    spec = PromptSpec(
        question="Refactor compressor method",
        context="class LccCompressor: pass",
        task_type="refactor",
        constraints=["Do not break tests."],
    )
    prompt = build_prompt(spec, template_name="code_agent")
    assert "# System: AI Coding Agent Instructions & Operational Contract" in prompt
    assert "### Reference Context & Codebase Memory:" in prompt
    assert "class LccCompressor: pass" in prompt
    assert "### User Task / Objective:\nRefactor compressor method" in prompt
    assert "Do not break tests." in prompt


def test_structured_markdown_template():
    spec = PromptSpec(
        question="Analyze performance bottleneck",
        context="Latency is 450ms.",
        task_type="analysis",
    )
    prompt = build_prompt(spec, template_name="structured_markdown")
    assert "## Role & Instructions" in prompt
    assert "## Context\nLatency is 450ms." in prompt
    assert "## Task\nAnalyze performance bottleneck" in prompt

