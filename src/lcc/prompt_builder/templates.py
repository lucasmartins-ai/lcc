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


#: Registry of available templates. Add new templates here.
TEMPLATES: dict[str, Callable[[PromptSpec], str]] = {
    "default": render_default,
}
