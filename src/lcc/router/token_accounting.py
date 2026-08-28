"""Token estimation for router features and fallback paths."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Fast deterministic token estimator (~4 chars per token)."""
    return max(1, len(text) // 4) if text else 0
