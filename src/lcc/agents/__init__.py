"""Local LLM agents, solvers, and quality verification gates."""

from lcc.agents.local_agent import (
    ChatFormatter,
    LocalAgent,
    LocalAgentConfig,
    create_local_agent_from_env,
    detect_model_family,
)
from lcc.agents.local_solver import (
    HTTPLocalSolver,
    LocalAgentSolver,
    LocalSolver,
    MockLocalSolver,
    create_local_solver_from_env,
)
from lcc.agents.local_verifier import (
    LocalLLMVerifier,
    RuleBasedVerifier,
    create_verifier,
)

__all__ = [
    "LocalAgent",
    "LocalAgentConfig",
    "create_local_agent_from_env",
    "detect_model_family",
    "ChatFormatter",
    "LocalSolver",
    "LocalAgentSolver",
    "MockLocalSolver",
    "HTTPLocalSolver",
    "create_local_solver_from_env",
    "RuleBasedVerifier",
    "LocalLLMVerifier",
    "create_verifier",
]
