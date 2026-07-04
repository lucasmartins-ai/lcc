"""Router-specific exceptions."""

from __future__ import annotations


class RouterError(Exception):
    """Base exception for controlled router failures."""


class TaskLoadError(RouterError):
    """Raised when a task fixture cannot be loaded."""


class RemoteCallError(RouterError):
    """Raised when a configured remote call fails before a controlled answer is built."""
