"""Backwards-compatibility alias for cloud_client."""

from lcc.router.cloud_client import (
    FireworksRemoteSolver,
    MockRemoteSolver,
    RemoteSolver,
    build_fireworks_prompt,
    create_remote_solver_from_env,
)

__all__ = [
    "RemoteSolver",
    "MockRemoteSolver",
    "FireworksRemoteSolver",
    "create_remote_solver_from_env",
    "build_fireworks_prompt",
]
