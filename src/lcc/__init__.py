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
    __version__ = "0.5.0"

from lcc.agents import (
    LocalAgent,
    LocalAgentConfig,
    create_local_agent_from_env,
)
from lcc.compressor import CompressionResult, LccCompressor, LccOptimizer
from lcc.intake import (
    IntakePipeline,
    IntakeResult,
    LccIntake,
    ParsedIntake,
    ReadinessState,
    StructuredBrief,
    parse_intake,
    process_intake,
)
from lcc.pipeline import OptimizationRequest, OptimizationResult, optimize
from lcc.router import (
    FinalAnswer,
    LCCRouter,
    RouteDecision,
    TaskInput,
    VerificationDecision,
    VerificationResult,
)
from lcc.toon import encode_toon

__all__ = [
    "__version__",
    "LccCompressor",
    "LccOptimizer",
    "CompressionResult",
    "OptimizationRequest",
    "OptimizationResult",
    "optimize",
    "encode_toon",
    "LccIntake",
    "IntakePipeline",
    "IntakeResult",
    "ParsedIntake",
    "ReadinessState",
    "StructuredBrief",
    "parse_intake",
    "process_intake",
    "LocalAgent",
    "LocalAgentConfig",
    "create_local_agent_from_env",
    "LCCRouter",
    "TaskInput",
    "FinalAnswer",
    "RouteDecision",
    "VerificationDecision",
    "VerificationResult",
]


