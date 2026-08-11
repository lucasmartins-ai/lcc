"""Model pricing lookup and input-cost estimation.

Prices are configurable. A small built-in table (``BUILTIN_PRICING``) ships so the tool
works with no config file; users can override it with a YAML file (config/pricing.yaml)
via ``--pricing``. All bundled prices are EDITABLE EXAMPLES, not guaranteed current.
"""

from __future__ import annotations

from typing import Any

from lcc.schemas import PricingInfo

# USD per 1,000,000 tokens. EXAMPLE VALUES -- verify against your provider before relying
# on cost output. Kept in sync with config/pricing.yaml.
BUILTIN_PRICING: dict[str, Any] = {
    "currency": "USD",
    "unit": "per_million_tokens",
    "source": "Built-in example pricing -- edit config/pricing.yaml or pass --pricing.",
    "models": {
        # Anthropic (2026 & 3.x series)
        "claude-opus-5": {"input": 5.00, "output": 25.00},
        "claude-sonnet-5": {"input": 2.00, "output": 10.00},
        "claude-fable-5": {"input": 10.00, "output": 50.00},
        "claude-haiku-4.5": {"input": 1.00, "output": 5.00},
        "claude-3-7-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-5-haiku": {"input": 0.80, "output": 4.00},

        # OpenAI & Codex (2026 GPT-5.6 & o-series)
        "gpt-5.6-sol": {"input": 5.00, "output": 30.00},
        "gpt-5.6-terra": {"input": 2.00, "output": 12.00},
        "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
        "o3": {"input": 5.00, "output": 20.00},
        "o3-mini": {"input": 1.10, "output": 4.40},
        "o1": {"input": 15.00, "output": 60.00},
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},

        # Google Gemini & Antigravity (2026 Gemini 3.x series)
        "gemini-3.6-flash": {"input": 1.50, "output": 7.50},
        "gemini-3.1-pro": {"input": 2.00, "output": 12.00},
        "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},

        # DeepSeek
        "deepseek-v4-pro": {"input": 0.435, "output": 0.87},
        "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
        "deepseek-v3": {"input": 0.14, "output": 0.28},
        "deepseek-r1": {"input": 0.55, "output": 2.19},

        # Backward compatibility aliases
        "gpt-4.1": {"input": 2.00, "output": 8.00},
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
        "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    },
}


def get_model_pricing(pricing_doc: dict[str, Any], model: str) -> PricingInfo:
    """Look up ``model`` in a pricing document.

    Returns a ``PricingInfo`` whose ``found`` flag is False (and prices ``None``) when the
    model is absent, so the caller can warn instead of inventing a cost.
    """
    currency = str(pricing_doc.get("currency", "USD"))
    source = str(pricing_doc.get("source", "unspecified"))
    models = pricing_doc.get("models") or {}
    entry = models.get(model)
    if not isinstance(entry, dict):
        return PricingInfo(model, None, None, currency, source, found=False)
    input_price = entry.get("input")
    output_price = entry.get("output")
    return PricingInfo(
        model=model,
        input_per_million=float(input_price) if input_price is not None else None,
        output_per_million=float(output_price) if output_price is not None else None,
        currency=currency,
        source=source,
        found=True,
    )


def estimate_input_cost(tokens: int, input_per_million: float | None) -> float | None:
    """Return the estimated input cost for ``tokens``, or ``None`` if no price is known."""
    if input_per_million is None:
        return None
    return tokens * input_per_million / 1_000_000


def load_pricing(path: str | None = None) -> dict[str, Any]:
    """Load a pricing document, returning ``BUILTIN_PRICING`` when ``path`` is ``None``.

    Reading a YAML file requires PyYAML. Raises ``FileNotFoundError`` / ``ValueError`` on
    problems so the CLI can report them with a clear, non-zero exit.
    """
    if path is None:
        return BUILTIN_PRICING
    import yaml  # local import: only needed when an external file is used

    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Pricing file not found: {path}") from exc
    if not isinstance(data, dict) or "models" not in data:
        raise ValueError(f"Pricing file {path!r} must be a mapping with a 'models' key.")
    return data
