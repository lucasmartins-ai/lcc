"""Token counting and pricing (local-only; tiktoken optional)."""

from __future__ import annotations

from lcc.token_budget.counters import approximate_token_count, count_tokens
from lcc.token_budget.pricing import (
    BUILTIN_PRICING,
    estimate_input_cost,
    get_model_pricing,
    load_pricing,
)

__all__ = [
    "BUILTIN_PRICING",
    "approximate_token_count",
    "count_tokens",
    "estimate_input_cost",
    "get_model_pricing",
    "load_pricing",
]
