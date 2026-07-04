"""Token accounting helpers for router-side remote usage estimates."""

from __future__ import annotations

from lcc.token_budget import count_tokens


def estimate_tokens(text: str, model: str | None = None) -> int:
    """Return a conservative local estimate when provider usage is unavailable."""
    heuristic = count_tokens(text, model, allow_exact=False).value
    char_floor = int(len(text) / 3.5) + (1 if text else 0)
    return max(heuristic, char_floor)
