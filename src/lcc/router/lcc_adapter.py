"""Backwards-compatibility alias for context_adapter."""

from lcc.router.context_adapter import (
    inspect_context,
    optimize_context_if_needed,
    prepare_context,
)

__all__ = [
    "inspect_context",
    "prepare_context",
    "optimize_context_if_needed",
]
