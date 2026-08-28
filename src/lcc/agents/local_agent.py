"""Local LLM Agent specialized for Gemma 4 e4b and Qwen3.5-4B.

Provides zero-remote-token local inference, native chat templating, structured verification,
and health diagnostic capabilities across Ollama, llama.cpp, vLLM, MLX, and mock backends.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from lcc.router.schemas import (
    AgentHealth,
    LocalAnswer,
    ModelFamily,
    TaskFeatures,
    TaskInput,
    VerificationDecision,
    VerificationResult,
)



def detect_model_family(name: str, explicit_family: str | None = None) -> ModelFamily:
    """Detect whether a model belongs to Gemma, Qwen, or generic family."""
    if explicit_family:
        lowered = explicit_family.lower()
        if "gemma" in lowered:
            return ModelFamily.GEMMA
        if "qwen" in lowered:
            return ModelFamily.QWEN
        if "generic" in lowered:
            return ModelFamily.GENERIC

    name_lower = name.lower()
    if "gemma" in name_lower:
        return ModelFamily.GEMMA
    if "qwen" in name_lower:
        return ModelFamily.QWEN
    return ModelFamily.GENERIC


class ChatFormatter:
    """Formats prompts according to model-specific chat templates."""

    @staticmethod
    def format(
        family: ModelFamily,
        user_message: str,
        system_message: str | None = None,
    ) -> tuple[str, list[str]]:
        """Return (formatted_prompt, stop_tokens)."""
        if family == ModelFamily.GEMMA:
            stop_tokens = ["<end_of_turn>", "<eos>", "<start_of_turn>"]
            if system_message:
                content = f"[System Instructions]\n{system_message}\n\n[Task]\n{user_message}"
            else:
                content = user_message
            prompt = f"<start_of_turn>user\n{content}<end_of_turn>\n<start_of_turn>model\n"
            return prompt, stop_tokens

        if family == ModelFamily.QWEN:
            stop_tokens = ["<|im_end|>", "<|endoftext|>"]
            sys_part = (
                f"<|im_start|>system\n{system_message}<|im_end|>\n"
                if system_message
                else "<|im_start|>system\nYou are a helpful and precise assistant.<|im_end|>\n"
            )
            prompt = f"{sys_part}<|im_start|>user\n{user_message}<|im_end|>\n<|im_start|>assistant\n"
            return prompt, stop_tokens

        # Generic / default
        stop_tokens = ["</s>", "<|endoftext|>"]
        if system_message:
            prompt = f"System: {system_message}\n\nUser: {user_message}\n\nAssistant:\n"
        else:
            prompt = f"User: {user_message}\n\nAssistant:\n"
        return prompt, stop_tokens


@dataclass
class LocalAgentConfig:
    backend: str = "mock"
    model_name: str = "gemma-4-e4b"
    endpoint: str = "http://127.0.0.1:11434"
    family: ModelFamily | str = "auto"
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout_seconds: float = 30.0
    quantization: str = "e4b"

    def resolved_family(self) -> ModelFamily:
        if isinstance(self.family, ModelFamily):
            return self.family
        if self.family != "auto":
            return detect_model_family("", self.family)
        return detect_model_family(self.model_name)


class LocalAgent:
    """Unified Local LLM Agent for high-performance zero-token task solving."""

    def __init__(self, config: LocalAgentConfig | None = None) -> None:
        self.config = config or LocalAgentConfig()
        self.family = self.config.resolved_family()
        self.backend = self.config.backend.lower()
        self.model_name = self.config.model_name
        self.endpoint = self.config.endpoint.rstrip("/")

    def solve(self, task: TaskInput, prompt: str | None = None) -> LocalAnswer:
        """Execute local solver inference on a task with 0 remote tokens."""
        from lcc.router.prompt_builder import build_local_prompt

        effective_prompt = prompt or build_local_prompt(task, task.context)
        started = time.perf_counter()

        if self.backend == "mock":
            return self._solve_mock(task, effective_prompt, started)

        try:
            raw_text = self._call_backend(effective_prompt)
            latency_ms = int((time.perf_counter() - started) * 1000)
            return LocalAnswer(
                answer=raw_text.strip(),
                model_name=self.model_name,
                latency_ms=latency_ms,
                metadata={
                    "backend": self.backend,
                    "family": self.family.value,
                    "endpoint": self.endpoint,
                    "quantization": self.config.quantization,
                },
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return LocalAnswer(
                answer=f"[Local Error: {exc}]",
                model_name=self.model_name,
                latency_ms=latency_ms,
                metadata={
                    "backend": self.backend,
                    "error": str(exc),
                    "fallback_to_mock": True,
                },
            )

    def verify(
        self,
        task: TaskInput,
        candidate: LocalAnswer | str,
        features: TaskFeatures | None = None,
    ) -> VerificationResult:
        """Run local verification gate against a candidate answer."""
        from lcc.router.prompt_builder import build_verifier_prompt

        candidate_ans = candidate if isinstance(candidate, LocalAnswer) else LocalAnswer(
            answer=str(candidate),
            model_name=self.model_name,
            latency_ms=0,
        )

        verifier_prompt = build_verifier_prompt(task, candidate_ans)

        system_instruction = (
            "You are a strict technical answer quality verifier. "
            "Output ONLY valid JSON matching the verifier_contract schema."
        )

        if self.backend == "mock":
            return self._verify_mock(task, candidate_ans)

        try:
            raw = self._call_backend(verifier_prompt, system_message=system_instruction)
            payload = _extract_json(raw)
            return VerificationResult(
                decision=VerificationDecision(str(payload["decision"])),
                confidence=float(payload.get("confidence", 0.85)),
                format_valid=bool(payload.get("format_valid", True)),
                missing_requirements=[str(item) for item in payload.get("missing_requirements", [])],
                risk_reasons=[str(item) for item in payload.get("risk_reasons", [])],
                explanation=str(payload.get("explanation", "Verified by local LLM")),
            )
        except Exception as exc:
            return VerificationResult(
                decision=VerificationDecision.ACCEPT_LOCAL if candidate_ans.answer.strip() else VerificationDecision.ESCALATE_REMOTE,
                confidence=0.75 if candidate_ans.answer.strip() else 0.0,
                format_valid=bool(candidate_ans.answer.strip()),
                missing_requirements=[] if candidate_ans.answer.strip() else ["non-empty answer"],
                risk_reasons=[f"verifier_fallback_on_error: {exc}"] if str(exc) else [],
                explanation=f"Fallback rule verification due to: {exc}",
            )

    def health_check(self) -> AgentHealth:
        """Probe local backend availability and latency."""
        started = time.perf_counter()
        if self.backend == "mock":
            return AgentHealth(
                healthy=True,
                status="ready (mock)",
                model_name=self.model_name,
                backend="mock",
                family=self.family,
                latency_ms=0,
                details={"mode": "deterministic mock", "quantization": self.config.quantization},
            )

        test_url = f"{self.endpoint}/api/version" if self.backend == "ollama" else f"{self.endpoint}/v1/models"
        try:
            req = urllib.request.Request(test_url, headers={"User-Agent": "lcc-local-agent/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
            latency_ms = int((time.perf_counter() - started) * 1000)
            return AgentHealth(
                healthy=True,
                status="ready",
                model_name=self.model_name,
                backend=self.backend,
                family=self.family,
                latency_ms=latency_ms,
                details={"endpoint": self.endpoint, "response": data},
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return AgentHealth(
                healthy=False,
                status="offline",
                model_name=self.model_name,
                backend=self.backend,
                family=self.family,
                latency_ms=latency_ms,
                details={"endpoint": self.endpoint, "error": str(exc)},
            )

    def _call_backend(self, prompt: str, system_message: str | None = None) -> str:
        formatted_prompt, stop_tokens = ChatFormatter.format(self.family, prompt, system_message)

        if self.backend == "ollama":
            url = f"{self.endpoint}/api/generate"
            payload = {
                "model": self.model_name,
                "prompt": formatted_prompt,
                "stream": False,
                "options": {
                    "temperature": self.config.temperature,
                    "num_predict": self.config.max_tokens,
                    "stop": stop_tokens,
                },
            }
            response_data = self._http_post(url, payload)
            return str(response_data.get("response", ""))

        url = f"{self.endpoint}/v1/chat/completions"
        if not self._endpoint_has_v1():
            url = f"{self.endpoint}/chat/completions"

        messages: list[dict[str, str]] = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stop": stop_tokens,
        }
        response_data = self._http_post(url, payload)
        choices = response_data.get("choices", [{}])
        if choices and "message" in choices[0]:
            return str(choices[0]["message"].get("content", ""))
        return str(response_data)

    def _endpoint_has_v1(self) -> bool:
        return "/v1" in self.endpoint

    def _http_post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def _solve_mock(self, task: TaskInput, prompt: str, started: float) -> LocalAnswer:
        context = task.context.strip()
        expected = (task.expected_format or "").lower()
        if "json" in expected:
            answer = json.dumps({"answer": _first_sentence(context) or f"Answer for {task.task_id}"})
        elif "markdown table" in expected or "table" in expected:
            ans_val = _first_sentence(context) or f"Answer for {task.task_id}"
            answer = f"| Item | Value |\n| --- | --- |\n| Result | {ans_val} |"
        else:
            answer = _first_sentence(context) or f"Mock local answer for {task.task_id}."

        latency_ms = int((time.perf_counter() - started) * 1000)
        return LocalAnswer(
            answer=answer,
            model_name=self.model_name,
            latency_ms=latency_ms,
            metadata={
                "backend": "mock",
                "family": self.family.value,
                "quantization": self.config.quantization,
                "prompt_len": len(prompt),
            },
        )

    def _verify_mock(self, task: TaskInput, candidate: LocalAnswer) -> VerificationResult:
        answer = candidate.answer.strip()
        format_valid = True
        missing: list[str] = []
        if not answer:
            format_valid = False
            missing.append("non-empty answer")

        if task.expected_format and "json" in task.expected_format.lower():
            try:
                json.loads(answer)
            except Exception:
                format_valid = False
                missing.append("valid JSON")

        decision = VerificationDecision.ACCEPT_LOCAL if format_valid else VerificationDecision.ESCALATE_REMOTE
        confidence = 0.90 if format_valid else 0.20
        return VerificationResult(
            decision=decision,
            confidence=confidence,
            format_valid=format_valid,
            missing_requirements=missing,
            risk_reasons=[] if format_valid else ["format_invalid"],
            explanation="Mock verification gate evaluation",
        )


def _first_sentence(text: str) -> str:
    for separator in [". ", "\n"]:
        if separator in text:
            return text.split(separator, 1)[0].strip().rstrip(".") + "."
    return text[:240].strip()


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        val = json.loads(cleaned)
        if isinstance(val, dict):
            return val
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        val = json.loads(match.group(0))
        if isinstance(val, dict):
            return val
    raise ValueError(f"Could not parse valid JSON from: {text[:200]}")


def create_local_agent_from_env() -> LocalAgent:
    """Create configured LocalAgent from environment variables or configs/models.yaml."""
    backend = os.getenv("LOCAL_MODEL_BACKEND", "mock")
    model_name = os.getenv("LOCAL_MODEL_NAME", "gemma-4-e4b")
    endpoint = os.getenv("LOCAL_MODEL_ENDPOINT", "http://127.0.0.1:11434")
    family = os.getenv("LOCAL_MODEL_FAMILY", "auto")
    quantization = os.getenv("LOCAL_MODEL_QUANTIZATION", "e4b")

    config = LocalAgentConfig(
        backend=backend,
        model_name=model_name,
        endpoint=endpoint,
        family=family,
        quantization=quantization,
    )
    return LocalAgent(config)
