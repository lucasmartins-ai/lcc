"""Local Context Compiler (lcc).

A deterministic, local-first toolkit that cleans, deduplicates, structures, and measures
text context before it is sent to a large language model. The MVP performs no network
calls and requires no API key (see docs/architecture.md and the ADRs in docs/adr/).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("local-context-compiler")
except PackageNotFoundError:  # running from a source tree without an installation
    __version__ = "0.1.0"

__all__ = ["__version__"]
