"""Tests for Gemma 4 e4b and Qwen3.5-4B LocalAgent and Router integration."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from lcc.agents.local_agent import (
    ChatFormatter,
    LocalAgent,
    LocalAgentConfig,
    _extract_json,
    create_local_agent_from_env,
    detect_model_family,
)
from lcc.agents.local_solver import LocalAgentSolver, MockLocalSolver
from lcc.router.router import LCCRouter
from lcc.router.schemas import (
    ModelFamily,
    RouteDecision,
    TaskInput,
    VerificationDecision,
)


def test_detect_model_family() -> None:
    assert detect_model_family("gemma-4-e4b") == ModelFamily.GEMMA
    assert detect_model_family("gemma2:2b") == ModelFamily.GEMMA
    assert detect_model_family("gemma3:4b") == ModelFamily.GEMMA
    assert detect_model_family("qwen3.5-4b") == ModelFamily.QWEN
    assert detect_model_family("qwen2.5:3b") == ModelFamily.QWEN
    assert detect_model_family("custom-model", explicit_family="gemma") == ModelFamily.GEMMA
    assert detect_model_family("custom-model", explicit_family="qwen") == ModelFamily.QWEN
    assert detect_model_family("llama-3-8b") == ModelFamily.GENERIC


def test_gemma_chat_formatter() -> None:
    prompt, stop_tokens = ChatFormatter.format(
        ModelFamily.GEMMA,
        user_message="Explain quantization",
        system_message="You are a concise expert.",
    )
    assert "<start_of_turn>user" in prompt
    assert "<end_of_turn>" in prompt
    assert "<start_of_turn>model" in prompt
    assert "You are a concise expert." in prompt
    assert "Explain quantization" in prompt
    assert "<end_of_turn>" in stop_tokens


def test_qwen_chat_formatter() -> None:
    prompt, stop_tokens = ChatFormatter.format(
        ModelFamily.QWEN,
        user_message="Generate valid JSON",
        system_message="Strict JSON only.",
    )
    assert "<|im_start|>system\nStrict JSON only.<|im_end|>" in prompt
    assert "<|im_start|>user\nGenerate valid JSON<|im_end|>" in prompt
    assert "<|im_start|>assistant\n" in prompt
    assert "<|im_end|>" in stop_tokens


def test_local_agent_solve_mock_text() -> None:
    agent = LocalAgent(
        LocalAgentConfig(
            backend="mock",
            model_name="gemma-4-e4b",
            quantization="e4b",
        )
    )
    task = TaskInput(
        task_id="test-1",
        instruction="Summarize",
        context="Deterministic context is essential. Second sentence.",
    )
    answer = agent.solve(task)
    assert "Deterministic context is essential." in answer.answer
    assert answer.model_name == "gemma-4-e4b"
    assert answer.metadata["family"] == "gemma"
    assert answer.metadata["quantization"] == "e4b"


def test_local_agent_solve_mock_json() -> None:
    agent = LocalAgent(
        LocalAgentConfig(
            backend="mock",
            model_name="qwen3.5-4b",
            quantization="e4b",
        )
    )
    task = TaskInput(
        task_id="test-json",
        instruction="Extract data",
        context="Sample data content.",
        expected_format="json",
    )
    answer = agent.solve(task)
    parsed = json.loads(answer.answer)
    assert "answer" in parsed
    assert answer.metadata["family"] == "qwen"


def test_local_agent_verify_mock() -> None:
    agent = LocalAgent(LocalAgentConfig(backend="mock", model_name="gemma-4-e4b"))
    task = TaskInput(task_id="test-verify", instruction="Count tokens", expected_format="json")
    valid_verdict = agent.verify(task, candidate='{"answer": "42"}')
    assert valid_verdict.decision == VerificationDecision.ACCEPT_LOCAL
    assert valid_verdict.format_valid is True

    invalid_verdict = agent.verify(task, candidate="not valid json")
    assert invalid_verdict.decision == VerificationDecision.ESCALATE_REMOTE
    assert invalid_verdict.format_valid is False


def test_local_agent_health_check_mock() -> None:
    agent = LocalAgent(LocalAgentConfig(backend="mock", model_name="gemma-4-e4b"))
    health = agent.health_check()
    assert health.healthy is True
    assert health.model_name == "gemma-4-e4b"
    assert health.backend == "mock"
    assert health.family == ModelFamily.GEMMA


def test_local_agent_health_check_offline() -> None:
    agent = LocalAgent(
        LocalAgentConfig(
            backend="ollama",
            model_name="gemma-4-e4b",
            endpoint="http://127.0.0.1:9999",  # non-existent port
        )
    )
    health = agent.health_check()
    assert health.healthy is False
    assert health.status == "offline"


def test_local_agent_ollama_call() -> None:
    agent = LocalAgent(
        LocalAgentConfig(
            backend="ollama",
            model_name="gemma-4-e4b",
            endpoint="http://127.0.0.1:11434",
        )
    )
    mock_response = {"response": "Local response from Gemma 4 e4b"}

    with patch.object(agent, "_http_post", return_value=mock_response):
        task = TaskInput(task_id="t-ollama", instruction="Hi")
        answer = agent.solve(task)
        assert answer.answer == "Local response from Gemma 4 e4b"
        assert answer.metadata["backend"] == "ollama"


def test_local_agent_openai_compatible_call() -> None:
    agent = LocalAgent(
        LocalAgentConfig(
            backend="llamacpp",
            model_name="qwen3.5-4b",
            endpoint="http://127.0.0.1:8080/v1",
        )
    )
    mock_response = {
        "choices": [{"message": {"content": "Response from Qwen3.5-4B llama.cpp"}}]
    }

    with patch.object(agent, "_http_post", return_value=mock_response):
        task = TaskInput(task_id="t-llamacpp", instruction="Test Qwen")
        answer = agent.solve(task)
        assert answer.answer == "Response from Qwen3.5-4B llama.cpp"
        assert answer.metadata["family"] == "qwen"


def test_extract_json_with_markdown_fences() -> None:
    raw_markdown = '```json\n{"decision": "ACCEPT_LOCAL", "confidence": 0.95, "format_valid": true}\n```'
    extracted = _extract_json(raw_markdown)
    assert extracted["decision"] == "ACCEPT_LOCAL"
    assert extracted["confidence"] == 0.95


def test_create_local_agent_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_MODEL_BACKEND", "ollama")
    monkeypatch.setenv("LOCAL_MODEL_NAME", "gemma-4-e4b")
    monkeypatch.setenv("LOCAL_MODEL_ENDPOINT", "http://127.0.0.1:11434")
    monkeypatch.setenv("LOCAL_MODEL_QUANTIZATION", "e4b")

    agent = create_local_agent_from_env()
    assert agent.backend == "ollama"
    assert agent.model_name == "gemma-4-e4b"
    assert agent.family == ModelFamily.GEMMA
    assert agent.config.quantization == "e4b"


def test_local_solver_adapters() -> None:
    mock_solver = MockLocalSolver("gemma-4-e4b")
    task = TaskInput(task_id="t1", instruction="Test", context="Sample context.")
    ans1 = mock_solver.solve(task, "prompt")
    assert ans1.model_name == "gemma-4-e4b"

    agent_solver = LocalAgentSolver()
    ans2 = agent_solver.solve(task, "prompt")
    assert ans2.model_name == "gemma-4-e4b"


def test_router_with_gemma_local_agent() -> None:
    agent = LocalAgent(LocalAgentConfig(backend="mock", model_name="gemma-4-e4b"))
    solver = LocalAgentSolver(agent)
    router = LCCRouter(local_solver=solver)

    task = TaskInput(
        task_id="task-local-only",
        instruction="Short simple task",
        context="Brief clean context with zero noise.",
    )
    final = router.run(task)
    assert final.remote_tokens_used == 0
    assert final.route_taken in {RouteDecision.LOCAL_ONLY.value, RouteDecision.LOCAL_THEN_VERIFY.value}
