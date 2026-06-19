"""Build an optimized downstream prompt from a ``PromptSpec``."""

from __future__ import annotations

from dataclasses import dataclass, field

from lcc.prompt_builder.templates import TEMPLATES


@dataclass
class PromptSpec:
    """Inputs for prompt construction."""

    question: str
    context: str
    task_type: str = "general"
    constraints: list[str] = field(default_factory=list)
    max_output_tokens: int | None = None
    allow_external_knowledge: bool = False
    format_requirements: list[str] | None = None


def build_prompt(spec: PromptSpec, template_name: str = "default") -> str:
    """Render ``spec`` using the named template.

    Raises ``KeyError`` with a helpful message when the template is unknown. Register more
    templates in ``lcc.prompt_builder.templates.TEMPLATES``.
    """
    try:
        template = TEMPLATES[template_name]
    except KeyError:
        available = ", ".join(sorted(TEMPLATES))
        raise KeyError(
            f"Unknown prompt template {template_name!r}. Available templates: {available}."
        ) from None
    return template(spec)


def available_templates() -> list[str]:
    """Return the sorted names of registered templates."""
    return sorted(TEMPLATES)
