"""Provider abstraction for semantic decision backends (ADR 0013, ADR 0015).

Separates context compilation (LCC) from semantic decision-making (Jev, Laya, Mechanical).
LCC reduces and structures the context, and passes it to the selected provider.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from lcc.relevance.jev import JEV_CONTEXT_LIMIT_TOKENS

__all__ = [
    "SEMANTIC_PROVIDERS",
    "SemanticProvider",
    "JevProvider",
    "LayaProvider",
    "MechanicalProvider",
    "UnsupportedOperationError",
    "get_semantic_provider",
]

SEMANTIC_PROVIDERS: tuple[str, ...] = ("jev", "laya", "mechanical")


class UnsupportedOperationError(RuntimeError):
    """Raised when a semantic operation is requested that the provider does not support."""


@runtime_checkable
class SemanticProvider(Protocol):
    """Protocol for semantic decision providers.

    All providers evaluate typed questions ('noul', 'choice', 'score') over an input state,
    returning structured answers with calibrated probabilities, confidence, and usage metadata.
    """

    @property
    def name(self) -> str:
        """Provider name identifier (e.g. 'jev', 'laya', 'mechanical')."""
        ...

    @property
    def model(self) -> str:
        """Configured model identifier."""
        ...

    @property
    def last_resolved_model(self) -> str:
        """Resolved concrete model version from the last execution."""
        ...

    @property
    def context_limit(self) -> int:
        """Maximum context window supported by the model (in tokens)."""
        ...

    @property
    def is_local(self) -> bool:
        """Whether the provider executes strictly locally without network access."""
        ...

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        """Evaluate typed questions over state."""
        ...

    def supports_operation(self, operation: str) -> bool:
        """Check whether the provider supports an operation (e.g. 'noul', 'choice', 'score')."""
        ...

    def is_available(self) -> bool:
        """Whether this provider can be used in the current environment."""
        ...


class JevProvider:
    """Remote semantic decision backend using TypeSafe System One ('Jev')."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "jev"

    @property
    def model(self) -> str:
        return getattr(self._client, "model", "jev-latest")

    @model.setter
    def model(self, value: str) -> None:
        self._client.model = value

    @property
    def last_resolved_model(self) -> str:
        return getattr(self._client, "last_resolved_model", self.model)

    @property
    def context_limit(self) -> int:
        # Jev remote System One context window: same number the client refuses at.
        return JEV_CONTEXT_LIMIT_TOKENS

    @property
    def is_local(self) -> bool:
        return False

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        return self._client.evaluate(state, questions)

    def supports_operation(self, operation: str) -> bool:
        return operation in ("noul", "choice", "score")

    def is_available(self) -> bool:
        if self._client is not None:
            return True
        import os

        return bool(os.getenv("TYPESAFE_API_KEY"))


class LayaProvider:
    """Local non-autoregressive System 1 semantic decision backend using Laya."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "laya"

    @property
    def model(self) -> str:
        return getattr(self._client, "model", "convaiinnovations/laya-multilingual")

    @model.setter
    def model(self, value: str) -> None:
        if self._client is not None:
            self._client.model = value

    @property
    def last_resolved_model(self) -> str:
        return getattr(self._client, "last_resolved_model", self.model)

    @property
    def context_limit(self) -> int:
        return getattr(self._client, "context_limit", 1024)

    @property
    def is_local(self) -> bool:
        return True

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise UnsupportedOperationError("Laya client is not initialized")
        return self._client.evaluate(state, questions)

    def supports_operation(self, operation: str) -> bool:
        if hasattr(self._client, "supports_operation"):
            return self._client.supports_operation(operation)
        return operation in ("noul", "choice", "score")

    def is_available(self) -> bool:
        if self._client is not None:
            return True
        try:
            import laya  # noqa: F401

            return True
        except ImportError:
            return False


class MechanicalProvider:
    """Fully local lexical overlap scorer (fallback/baseline)."""

    def __init__(self) -> None:
        self._model = "mechanical-v1"
        self._last_resolved_model = "mechanical-v1"

    @property
    def name(self) -> str:
        return "mechanical"

    @property
    def model(self) -> str:
        return self._model

    @property
    def last_resolved_model(self) -> str:
        return self._last_resolved_model

    @property
    def context_limit(self) -> int:
        return 1_000_000  # Effectively unbounded for local string operations

    @property
    def is_local(self) -> bool:
        return True

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        raise UnsupportedOperationError(
            "MechanicalProvider does not execute arbitrary System 1 questions; "
            "it scores relevance via lexical token overlap directly in the compactor."
        )

    def supports_operation(self, operation: str) -> bool:
        return operation == "lexical_overlap"

    def is_available(self) -> bool:
        return True


def get_semantic_provider(name: str, client: Any = None) -> SemanticProvider:
    """Retrieve an initialized semantic provider by name."""
    if name == "jev":
        return JevProvider(client)
    elif name == "laya":
        return LayaProvider(client)
    elif name == "mechanical":
        return MechanicalProvider()
    raise ValueError(
        f"Unknown semantic provider '{name}'. Available providers: {SEMANTIC_PROVIDERS}"
    )
