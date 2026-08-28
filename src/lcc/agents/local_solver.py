"""Local solver interfaces and adapters."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from lcc.agents.local_agent import (
    LocalAgent,
    LocalAgentConfig,
    create_local_agent_from_env,
)
from lcc.router.schemas import LocalAnswer, TaskInput


class LocalSolver(ABC):
    @abstractmethod
    def solve(self, task: TaskInput, prompt: str) -> LocalAnswer:
        """Return a local answer with zero remote tokens used."""


class LocalAgentSolver(LocalSolver):
    """Bridge adapter that routes requests through the specialized LocalAgent."""

    def __init__(self, agent: LocalAgent | None = None) -> None:
        self.agent = agent or create_local_agent_from_env()

    def solve(self, task: TaskInput, prompt: str) -> LocalAnswer:
        return self.agent.solve(task, prompt)


class MockLocalSolver(LocalSolver):
    """Deterministic local solver for tests and unconfigured environments."""

    def __init__(self, model_name: str = "mock-local") -> None:
        self.model_name = model_name
        self._agent = LocalAgent(LocalAgentConfig(backend="mock", model_name=model_name))

    def solve(self, task: TaskInput, prompt: str) -> LocalAnswer:
        return self._agent.solve(task, prompt)


class HTTPLocalSolver(LocalSolver):
    """Adapter for Ollama, llama.cpp, and OpenAI-compatible endpoints."""

    def __init__(
        self,
        backend: str,
        model_name: str,
        endpoint: str,
        family: str = "auto",
        quantization: str = "e4b",
    ) -> None:
        self.backend = backend
        self.model_name = model_name
        self.endpoint = endpoint.rstrip("/")
        self._agent = LocalAgent(
            LocalAgentConfig(
                backend=backend,
                model_name=model_name,
                endpoint=endpoint,
                family=family,
                quantization=quantization,
            )
        )

    def solve(self, task: TaskInput, prompt: str) -> LocalAnswer:
        return self._agent.solve(task, prompt)


def create_local_solver_from_env() -> LocalSolver:
    backend = os.getenv("LOCAL_MODEL_BACKEND", "mock").lower()
    model = os.getenv("LOCAL_MODEL_NAME", "gemma-4-e4b")
    if backend == "mock":
        return MockLocalSolver(model)
    endpoint = os.getenv("LOCAL_MODEL_ENDPOINT")
    if not endpoint:
        return MockLocalSolver(f"{model} (mock: missing LOCAL_MODEL_ENDPOINT)")
    if backend not in {"ollama", "llamacpp", "vllm", "transformers", "mlx", "openai_compat"}:
        return MockLocalSolver(f"{model} (mock: unsupported backend {backend})")
    family = os.getenv("LOCAL_MODEL_FAMILY", "auto")
    quantization = os.getenv("LOCAL_MODEL_QUANTIZATION", "e4b")
    return HTTPLocalSolver(
        backend=backend,
        model_name=model,
        endpoint=endpoint,
        family=family,
        quantization=quantization,
    )
