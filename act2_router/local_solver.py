"""Local solver interfaces and mock/default backends."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from abc import ABC, abstractmethod

from act2_router.schemas import LocalAnswer, TaskInput


class LocalSolver(ABC):
    @abstractmethod
    def solve(self, task: TaskInput, prompt: str) -> LocalAnswer:
        """Return a local answer. Local tokens count as zero for Track 1 scoring."""


class MockLocalSolver(LocalSolver):
    """Deterministic local solver for tests and unconfigured demos."""

    def __init__(self, model_name: str = "mock-local") -> None:
        self.model_name = model_name

    def solve(self, task: TaskInput, prompt: str) -> LocalAnswer:
        started = time.perf_counter()
        context = task.context.strip()
        if task.expected_format and "json" in task.expected_format.lower():
            answer = json.dumps({"answer": _first_sentence(context) or "mock local answer"})
        elif task.expected_format and "markdown table" in task.expected_format.lower():
            answer = (
                "| answer |\n| --- |\n| " + (_first_sentence(context) or "mock local answer") + " |"
            )
        else:
            answer = _first_sentence(context) or f"Mock local answer for {task.task_id}."
        return LocalAnswer(
            answer=answer,
            model_name=self.model_name,
            latency_ms=int((time.perf_counter() - started) * 1000),
            metadata={"backend": "mock", "prompt_chars": len(prompt)},
        )


class HTTPLocalSolver(LocalSolver):
    """Small adapter for OpenAI-compatible local endpoints."""

    def __init__(self, backend: str, model_name: str, endpoint: str) -> None:
        self.backend = backend
        self.model_name = model_name
        self.endpoint = endpoint.rstrip("/")

    def solve(self, task: TaskInput, prompt: str) -> LocalAnswer:
        started = time.perf_counter()
        if self.backend == "ollama":
            url = f"{self.endpoint}/api/generate"
            payload = {"model": self.model_name, "prompt": prompt, "stream": False}
            answer_key = "response"
        else:
            url = f"{self.endpoint}/chat/completions"
            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
            answer_key = "choices"

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 local endpoint
            data = json.loads(response.read().decode("utf-8"))
        if answer_key == "response":
            text = str(data.get("response", ""))
        else:
            text = str(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
        return LocalAnswer(
            answer=text,
            model_name=self.model_name,
            latency_ms=int((time.perf_counter() - started) * 1000),
            metadata={"backend": self.backend, "endpoint": self.endpoint},
        )


def _first_sentence(text: str) -> str:
    for separator in [". ", "\n"]:
        if separator in text:
            return text.split(separator, 1)[0].strip().rstrip(".") + "."
    return text[:240].strip()


def create_local_solver_from_env() -> LocalSolver:
    backend = os.getenv("LOCAL_MODEL_BACKEND", "mock").lower()
    model = os.getenv("LOCAL_MODEL_NAME", "mock-local")
    if backend == "mock":
        return MockLocalSolver(model)
    endpoint = os.getenv("LOCAL_MODEL_ENDPOINT")
    if not endpoint:
        return MockLocalSolver(f"{model} (mock: missing LOCAL_MODEL_ENDPOINT)")
    if backend not in {"ollama", "llamacpp", "vllm", "transformers"}:
        return MockLocalSolver(f"{model} (mock: unsupported backend {backend})")
    return HTTPLocalSolver(backend=backend, model_name=model, endpoint=endpoint)
