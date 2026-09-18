"""Prompt templates. A template is a callable that renders a ``PromptSpec`` to text.

New templates register themselves in ``TEMPLATES`` so the builder stays open for extension
without changing its interface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lcc.prompt_builder.builder import PromptSpec

_SAFETY_CONSTRAINTS_CLOSED = [
    "Base the answer strictly on the provided context.",
    "Do not fabricate sources, numbers, citations, or quotations.",
    "State uncertainty explicitly when the context is insufficient.",
]
_SAFETY_CONSTRAINTS_OPEN = [
    "Prefer the provided context; you may use general knowledge, but label it clearly.",
    "Do not fabricate sources, numbers, citations, or quotations.",
    "State uncertainty explicitly when the evidence is insufficient.",
]


def _render_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def render_default(spec: PromptSpec) -> str:
    """Render the default, evidence-aware prompt template."""
    if spec.allow_external_knowledge:
        role = (
            "You are a careful technical assistant. Prefer the provided context. If you "
            "use outside knowledge, label it explicitly. If the context is insufficient, "
            "say so. Do not invent facts, numbers, citations, or sources."
        )
        constraints = list(_SAFETY_CONSTRAINTS_OPEN)
    else:
        role = (
            "You are a careful technical assistant. Use only the provided context unless "
            "explicitly allowed otherwise. If the context is insufficient, say so. Do not "
            "invent facts, numbers, citations, or sources."
        )
        constraints = list(_SAFETY_CONSTRAINTS_CLOSED)
    constraints.extend(spec.constraints)

    response_requirements = [
        "Direct answer to the question.",
        "Key evidence drawn from the provided context.",
        "Limitations or uncertainties, stated explicitly when evidence is insufficient.",
        "Suggested next steps if the provided information is not enough.",
    ]
    if spec.format_requirements:
        response_requirements.extend(spec.format_requirements)

    sections = [
        role,
        f"Task type: {spec.task_type}",
        "User question:\n" + (spec.question.strip() or "(no question provided)"),
        "Constraints:\n" + _render_bullets(constraints),
        "Context:\n" + (spec.context.strip() or "(no context provided)"),
        "Response requirements:\n"
        + "\n".join(f"{i}. {req}" for i, req in enumerate(response_requirements, start=1)),
    ]
    if spec.max_output_tokens is not None:
        sections.append(
            "Length guidance: keep the response within approximately "
            f"{spec.max_output_tokens} tokens."
        )
    return "\n\n".join(sections) + "\n"


def render_claude_xml(spec: PromptSpec) -> str:
    """Render an XML-tagged contract prompt optimized for Claude
    (Sonnet 5/Opus 5/3.7), Gemini 3.6, and KV-Cache."""
    if spec.allow_external_knowledge:
        role = (
            "You are a frontier technical assistant. Prefer the provided context. If you "
            "use outside knowledge, label it explicitly. If the context is insufficient, "
            "say so. Do not invent facts, numbers, citations, or sources."
        )
        constraints = list(_SAFETY_CONSTRAINTS_OPEN)
    else:
        role = (
            "You are a frontier technical assistant. Use only the provided context unless "
            "explicitly allowed otherwise. If the context is insufficient, say so. Do not "
            "invent facts, numbers, citations, or sources."
        )
        constraints = list(_SAFETY_CONSTRAINTS_CLOSED)
    constraints.extend(spec.constraints)

    response_requirements = [
        "Direct answer to the question with zero fluff.",
        "Key evidence drawn from the provided context.",
        "Limitations or uncertainties, stated explicitly when evidence is insufficient.",
        "Suggested next steps if the provided information is not enough.",
    ]
    if spec.format_requirements:
        response_requirements.extend(spec.format_requirements)

    constraints_xml = "\n".join(f"    <rule>{c}</rule>" for c in constraints)
    reqs_xml = "\n".join(f"    <criterion>{r}</criterion>" for r in response_requirements)

    sections = [
        "<system_instructions>",
        f"  <role>{role}</role>",
        f"  <task_type>{spec.task_type}</task_type>",
        "  <constraints>\n" + constraints_xml + "\n  </constraints>",
        "  <definition_of_done>\n" + reqs_xml + "\n  </definition_of_done>",
    ]
    if spec.max_output_tokens is not None:
        sections.append(
            f"  <length_guidance>Keep response within ~{spec.max_output_tokens} "
            "tokens.</length_guidance>"
        )
    sections.append("</system_instructions>")

    context_body = spec.context.strip() or "(no context provided)"
    sections.append(f"<context>\n{context_body}\n</context>")

    question_body = spec.question.strip() or "(no question provided)"
    sections.append(f"<user_query>\n{question_body}\n</user_query>")

    return "\n\n".join(sections) + "\n"


def render_code_agent(spec: PromptSpec) -> str:
    """Render an agentic contract prompt optimized for AI IDEs
    (Cursor, Antigravity, Codex, Claude Code)."""
    if spec.allow_external_knowledge:
        constraints = list(_SAFETY_CONSTRAINTS_OPEN)
    else:
        constraints = list(_SAFETY_CONSTRAINTS_CLOSED)
    constraints.extend(
        [
            "Preserve existing codebase architecture, formatting, and conventions.",
            "Write production-grade, type-safe, runnable code without placeholders.",
            "Minimize conversational filler; deliver exact code diffs or implementations.",
            "Never delete environment configurations, lockfiles, or unrelated modules.",
        ]
    )
    constraints.extend(spec.constraints)

    response_requirements = [
        "Direct code modification or answer solving the exact task.",
        "Accurate code blocks with syntax highlighting language identifiers.",
        "Edge case handling, regression verification, and explicit assumptions.",
    ]
    if spec.format_requirements:
        response_requirements.extend(spec.format_requirements)

    sections = [
        "# System: AI Coding Agent Instructions & Operational Contract",
        f"**Task Type:** `{spec.task_type}`",
        "### Operational Boundaries & Negative Constraints:\n" + _render_bullets(constraints),
        "### Reference Context & Codebase Memory:\n```\n"
        + (spec.context.strip() or "(no context provided)")
        + "\n```",
        "### User Task / Objective:\n" + (spec.question.strip() or "(no question provided)"),
        "### Definition of Done:\n"
        + "\n".join(f"{i}. {req}" for i, req in enumerate(response_requirements, start=1)),
    ]
    if spec.max_output_tokens is not None:
        sections.append(f"**Length Guidance:** Limit response to ~{spec.max_output_tokens} tokens.")

    return "\n\n".join(sections) + "\n"


def render_structured_markdown(spec: PromptSpec) -> str:
    """Render a clean structured markdown prompt for OpenAI
    (gpt-4o, o1, o3-mini) and general LLMs."""
    if spec.allow_external_knowledge:
        role = (
            "You are a careful technical assistant. Prefer the provided context. If you "
            "use outside knowledge, label it explicitly. If the context is insufficient, "
            "say so. Do not invent facts, numbers, citations, or sources."
        )
        constraints = list(_SAFETY_CONSTRAINTS_OPEN)
    else:
        role = (
            "You are a careful technical assistant. Use only the provided context unless "
            "explicitly allowed otherwise. If the context is insufficient, say so. Do not "
            "invent facts, numbers, citations, or sources."
        )
        constraints = list(_SAFETY_CONSTRAINTS_CLOSED)
    constraints.extend(spec.constraints)

    response_requirements = [
        "Direct answer addressing the user query.",
        "Key evidence drawn from the context.",
        "Explicit disclosure of uncertainties or limitations.",
    ]
    if spec.format_requirements:
        response_requirements.extend(spec.format_requirements)

    sections = [
        f"## Role & Instructions\n{role}\n\n**Task Type:** {spec.task_type}",
        "## Constraints\n" + _render_bullets(constraints),
        "## Context\n" + (spec.context.strip() or "(no context provided)"),
        "## Task\n" + (spec.question.strip() or "(no question provided)"),
        "## Response Requirements\n"
        + "\n".join(f"{i}. {req}" for i, req in enumerate(response_requirements, start=1)),
    ]
    if spec.max_output_tokens is not None:
        sections.append(f"**Length Guidance:** Keep within ~{spec.max_output_tokens} tokens.")

    return "\n\n".join(sections) + "\n"


#: Registry of available templates. Add new templates here.
TEMPLATES: dict[str, Callable[[PromptSpec], str]] = {
    "default": render_default,
    "claude_xml": render_claude_xml,
    "xml": render_claude_xml,
    "claude": render_claude_xml,
    "code_agent": render_code_agent,
    "cursor": render_code_agent,
    "codex": render_code_agent,
    "structured_markdown": render_structured_markdown,
    "markdown": render_structured_markdown,
}
