"""Local Context Compiler (lcc).

A deterministic, local-first toolkit that cleans, deduplicates, structures, and measures
text context before it is sent to a large language model. The MVP performs no network
calls and requires no API key (see docs/architecture.md and the ADRs in docs/adr/).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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

__version__: str

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

# ponytail: names load on first use, so `lcc hint --hook` (every prompt) pays only for the
# modules it imports. A new export goes in TYPE_CHECKING, __all__ and here.
_EXPORTS = {
    "lcc.agents": ("LocalAgent", "LocalAgentConfig", "create_local_agent_from_env"),
    "lcc.compressor": ("CompressionResult", "LccCompressor", "LccOptimizer"),
    "lcc.intake": (
        "IntakePipeline",
        "IntakeResult",
        "LccIntake",
        "ParsedIntake",
        "ReadinessState",
        "StructuredBrief",
        "parse_intake",
        "process_intake",
    ),
    "lcc.pipeline": ("OptimizationRequest", "OptimizationResult", "optimize"),
    "lcc.router": (
        "FinalAnswer",
        "LCCRouter",
        "RouteDecision",
        "TaskInput",
        "VerificationDecision",
        "VerificationResult",
    ),
    "lcc.toon": ("encode_toon",),
}
_HOME = {name: module for module, names in _EXPORTS.items() for name in names}


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("local-context-compiler")
    except PackageNotFoundError:  # running from a source tree without an installation
        return "1.4.0"


def __getattr__(name: str) -> Any:
    if name == "__version__":
        value: Any = _version()
    elif name in _HOME:
        value = getattr(import_module(_HOME[name]), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
