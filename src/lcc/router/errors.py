"""Exception classes for the LCC hybrid router and agent modules."""

from __future__ import annotations


class RouterError(Exception):
    """Base exception for router operations."""


class RemoteProviderError(RouterError):
    """Raised when remote cloud provider execution fails."""


class LocalSolverError(RouterError):
    """Raised when local solver fails unexpectedly."""
