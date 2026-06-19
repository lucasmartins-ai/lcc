"""Token counting with an exact (tiktoken) path and an honest heuristic fallback."""

from __future__ import annotations

from lcc.schemas import TokenCount, TokenCountMethod

try:  # tiktoken is optional; everything degrades gracefully without it (ADR 0005/0006).
    import tiktoken

    _HAS_TIKTOKEN = True
except Exception:  # pragma: no cover - exercised only when tiktoken is absent
    tiktoken = None  # type: ignore[assignment]
    _HAS_TIKTOKEN = False

_DEFAULT_ENCODING = "cl100k_base"


def approximate_token_count(text: str) -> int:
    """Estimate a token count without a tokenizer.

    Blends two common heuristics -- roughly 4 characters per token and roughly 0.75 words
    per token -- and averages them. This is a coarse fallback; expect about +/-20-30%
    error versus a real tokenizer. Returns 0 for empty or whitespace-only text.
    """
    if not text.strip():
        return 0
    char_estimate = len(text) / 4.0
    words = len(text.split())
    word_estimate = words / 0.75 if words else 0.0
    estimate = (char_estimate + word_estimate) / 2 if word_estimate else char_estimate
    return max(1, round(estimate))


def _resolve_encoding(model: str | None):
    """Return ``(encoding, is_exact)`` for a model, falling back to the default encoding."""
    if model:
        try:
            return tiktoken.encoding_for_model(model), True
        except KeyError:
            return tiktoken.get_encoding(_DEFAULT_ENCODING), False
    return tiktoken.get_encoding(_DEFAULT_ENCODING), False


def count_tokens(text: str, model: str | None = None, *, allow_exact: bool = True) -> TokenCount:
    """Count tokens in ``text``, preferring an exact tiktoken count for ``model``.

    Falls back to a heuristic when tiktoken is unavailable, errors (e.g. a vocab download
    is blocked), or does not recognize the model. The returned ``TokenCount.method`` states
    whether the result is exact or approximate (ADR 0005).
    """
    if allow_exact and _HAS_TIKTOKEN:
        try:
            encoding, is_exact = _resolve_encoding(model)
            value = len(encoding.encode(text))
            if is_exact:
                return TokenCount(value, TokenCountMethod.EXACT, "tiktoken", encoding.name)
            return TokenCount(
                value,
                TokenCountMethod.APPROXIMATE,
                "tiktoken",
                encoding.name,
                note=(
                    f"Model {model!r} has no known tiktoken encoding; counted with "
                    f"{encoding.name!r} as a fallback."
                ),
            )
        except Exception as exc:  # pragma: no cover - defensive (e.g. vocab download fails)
            return TokenCount(
                approximate_token_count(text),
                TokenCountMethod.APPROXIMATE,
                "heuristic",
                None,
                note=f"tiktoken failed ({type(exc).__name__}); used the heuristic estimator.",
            )

    note = None if _HAS_TIKTOKEN else "tiktoken is not installed; used the heuristic estimator."
    return TokenCount(
        approximate_token_count(text), TokenCountMethod.APPROXIMATE, "heuristic", None, note
    )
