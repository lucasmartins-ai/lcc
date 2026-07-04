"""Fireworks AI client and mock remote fallback."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from act2_router.prompt_builder import build_remote_prompt
from act2_router.schemas import RemoteAnswer, TaskInput
from act2_router.token_accounting import estimate_tokens

DEFAULT_FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"


class RemoteSolver:
    def complete(self, task: TaskInput, prompt: str) -> RemoteAnswer:
        raise NotImplementedError


class MockRemoteSolver(RemoteSolver):
    def __init__(self, model_name: str = "mock-fireworks") -> None:
        self.model_name = model_name

    def complete(self, task: TaskInput, prompt: str) -> RemoteAnswer:
        started = time.perf_counter()
        answer = _first_sentence(task.context) or f"Mock Fireworks answer for {task.task_id}."
        prompt_tokens = estimate_tokens(prompt, self.model_name)
        completion_tokens = estimate_tokens(answer, self.model_name)
        return RemoteAnswer(
            answer=answer,
            model_name=f"{self.model_name} (mock)",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage_estimated=True,
        )


class FireworksClient(RemoteSolver):
    """Tiny OpenAI-compatible chat completions client using stdlib HTTP."""

    def __init__(
        self,
        api_key: str,
        model_id: str,
        base_url: str = DEFAULT_FIREWORKS_BASE_URL,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries

    def complete(self, task: TaskInput, prompt: str) -> RemoteAnswer:
        started = time.perf_counter()
        payload = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        body = json.dumps(payload).encode("utf-8")
        url = f"{self.base_url}/chat/completions"
        last_error: str | None = None

        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as response:  # noqa: S310 configured API
                    data = json.loads(response.read().decode("utf-8"))
                return self._remote_answer(data, prompt, started)
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}: {exc.reason}"
                if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504}:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = str(exc)
            if attempt < self.max_retries:
                time.sleep(0.25 * (attempt + 1))

        answer = f"[remote_error] Fireworks call failed: {last_error or 'unknown error'}"
        prompt_tokens = estimate_tokens(prompt, self.model_id)
        return RemoteAnswer(
            answer=answer,
            model_name=self.model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            total_tokens=prompt_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage_estimated=True,
            error=last_error or "unknown error",
        )

    def _remote_answer(self, data: dict[str, object], prompt: str, started: float) -> RemoteAnswer:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            text = ""
        else:
            first = choices[0]
            text = ""
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    text = str(message.get("content", ""))
                else:
                    text = str(first.get("text", ""))
        usage = data.get("usage")
        estimated = True
        if isinstance(usage, dict):
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
            estimated = False
        else:
            prompt_tokens = estimate_tokens(prompt, self.model_id)
            completion_tokens = estimate_tokens(text, self.model_id)
            total_tokens = prompt_tokens + completion_tokens
        return RemoteAnswer(
            answer=text,
            model_name=self.model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage_estimated=estimated,
        )


def create_remote_solver_from_env() -> RemoteSolver:
    api_key = os.getenv("FIREWORKS_API_KEY")
    model_id = os.getenv("FIREWORKS_MODEL_ID", "mock-fireworks")
    if not api_key:
        return MockRemoteSolver(model_id)
    return FireworksClient(
        api_key=api_key,
        model_id=model_id,
        base_url=os.getenv("FIREWORKS_BASE_URL", DEFAULT_FIREWORKS_BASE_URL),
    )


def build_fireworks_prompt(task: TaskInput, context: str) -> str:
    return build_remote_prompt(task, context)


def _first_sentence(text: str) -> str:
    for separator in [". ", "\n"]:
        if separator in text:
            return text.split(separator, 1)[0].strip().rstrip(".") + "."
    return text[:240].strip()
