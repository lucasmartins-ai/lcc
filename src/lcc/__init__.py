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
    __version__ = "0.2.0"

from lcc.compressor import CompressionResult, LccCompressor, LccOptimizer
from lcc.pipeline import OptimizationRequest, OptimizationResult, optimize

__all__ = [
    "__version__",
    "LccCompressor",
    "LccOptimizer",
    "CompressionResult",
    "OptimizationRequest",
    "OptimizationResult",
    "optimize",
]
