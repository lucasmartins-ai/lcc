from __future__ import annotations

from act2_router.fireworks_client import MockRemoteSolver, create_remote_solver_from_env
from act2_router.schemas import TaskInput


def test_missing_api_key_uses_mock_remote(monkeypatch) -> None:
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    solver = create_remote_solver_from_env()
    assert isinstance(solver, MockRemoteSolver)


def test_mock_remote_counts_estimated_tokens() -> None:
    solver = MockRemoteSolver("mock")
    answer = solver.complete(TaskInput("t", "Q", "Context"), "prompt text")

    assert answer.total_tokens == answer.prompt_tokens + answer.completion_tokens
    assert answer.usage_estimated is True
    assert "mock" in answer.model_name
