"""Cloud escalation provider client (Fireworks AI and OpenAI-compatible endpoints)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from lcc.router.errors import RemoteProviderError
from lcc.router.prompt_builder import build_remote_prompt
from lcc.router.schemas import RemoteAnswer, TaskInput
from lcc.router.token_accounting import estimate_tokens


class RemoteSolver(ABC):
    @abstractmethod
    def complete(self, task: TaskInput, prompt: str) -> RemoteAnswer:
        """Execute cloud model inference and return answer with token accounting."""


class MockRemoteSolver(RemoteSolver):
    def __init__(self, model_name: str = "mock-fireworks") -> None:
        self.model_name = model_name

    def complete(self, task: TaskInput, prompt: str) -> RemoteAnswer:
        started = time.perf_counter()
        pt = estimate_tokens(prompt)
        text = f"Mock cloud answer for {task.task_id}."
        ct = estimate_tokens(text)
        return RemoteAnswer(
            answer=text,
            model_name=self.model_name,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage_estimated=True,
        )


class FireworksRemoteSolver(RemoteSolver):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.fireworks.ai/inference/v1",
        model_id: str = "accounts/fireworks/models/llama-v3p3-70b-instruct",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id

    def complete(self, task: TaskInput, prompt: str) -> RemoteAnswer:
        started = time.perf_counter()
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
            choice = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            pt = int(usage.get("prompt_tokens") or estimate_tokens(prompt))
            ct = int(usage.get("completion_tokens") or estimate_tokens(choice))
            tot = int(usage.get("total_tokens") or (pt + ct))
            return RemoteAnswer(
                answer=choice.strip(),
                model_name=self.model_id,
                prompt_tokens=pt,
                completion_tokens=ct,
                total_tokens=tot,
                latency_ms=int((time.perf_counter() - started) * 1000),
                usage_estimated=not bool(usage),
            )
        except Exception as exc:
            raise RemoteProviderError(f"Cloud model request failed: {exc}") from exc


def create_remote_solver_from_env() -> RemoteSolver:
    key = os.getenv("FIREWORKS_API_KEY") or os.getenv("CLOUD_API_KEY")
    if not key:
        return MockRemoteSolver()
    base_url = os.getenv(
        "FIREWORKS_BASE_URL",
        os.getenv("CLOUD_BASE_URL", "https://api.fireworks.ai/inference/v1"),
    )
    model_id = os.getenv(
        "FIREWORKS_MODEL_ID",
        os.getenv(
            "CLOUD_MODEL_ID", "accounts/fireworks/models/llama-v3p3-70b-instruct"
        ),
    )
    return FireworksRemoteSolver(api_key=key, base_url=base_url, model_id=model_id)


def build_fireworks_prompt(task: TaskInput, context: str) -> str:
    return build_remote_prompt(task, context)
